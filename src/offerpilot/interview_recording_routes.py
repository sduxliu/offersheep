"""面试录音上传/转写/删除路由；镜像 chat_image_routes 的独立 router 模式。"""

from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import APIRouter, Body, Request
from starlette.responses import JSONResponse, Response

from offerpilot.ai.recording_review_draft import (
    RecordingReviewDraftError,
    deepseek_strict_credentials,
    generate_review_draft,
    generate_review_draft_deepseek_strict,
)
from offerpilot.interview_recordings_contracts import (
    MAX_RECORDING_BYTES,
    InterviewRecordingError,
    interview_recording_error_message,
)
from offerpilot.interview_recordings import (
    InterviewRecordingStore,
    TranscriptionCoordinator,
    apply_asr_settings_update,
    asr_capability,
    asr_settings_from_config,
    asr_settings_view,
    openai_compatible_transcribe,
    silent_wav,
)
from offerpilot.repositories.interview_recordings import (
    InterviewRecordingsRepository,
    recording_json,
)

_STATUS_BY_CODE = {
    "recording_not_found": 404,
    "recording_state_conflict": 409,
    "recording_too_large": 413,
    "recording_empty": 422,
    "recording_format_unsupported": 415,
    "recording_file_missing": 410,
    "asr_unconfigured": 422,
    "asr_request_failed": 502,
    "asr_response_invalid": 502,
    "asr_chunk_failed": 502,
}


def interview_recording_error_response(error: InterviewRecordingError) -> JSONResponse:
    code = str(error)
    status = _STATUS_BY_CODE.get(code, 422)
    return JSONResponse(
        {"error": interview_recording_error_message(error), "error_code": code},
        status_code=status,
    )


def interview_recording_router(
    store: InterviewRecordingStore,
    coordinator: TranscriptionCoordinator,
    get_config: Callable[[], Any],
    get_event: Callable[[int], Any],
    save_config: Callable[[Any], None] | None = None,
    get_chat_model: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings/asr")
    def read_asr_settings() -> dict[str, Any]:
        return asr_settings_view(get_config())

    @router.put("/api/settings/asr")
    def update_asr_settings(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        if save_config is None:
            return JSONResponse({"error": "当前环境不支持修改配置"}, status_code=503)
        config = get_config()
        try:
            config.asr = apply_asr_settings_update(config.asr, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc), "error_code": "asr_settings_invalid"}, status_code=422)
        save_config(config)
        return JSONResponse(asr_settings_view(config))

    @router.post("/api/settings/asr/test")
    def test_asr_settings() -> dict[str, Any]:
        settings = asr_settings_from_config(get_config())
        if settings is None:
            return {"ok": False, "error": interview_recording_error_message(
                InterviewRecordingError("asr_unconfigured"))}
        started = time.monotonic()
        try:
            openai_compatible_transcribe(settings, silent_wav(), "asr-test.wav")
        except InterviewRecordingError as exc:
            return {"ok": False, "error": interview_recording_error_message(exc)}
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000),
                "model": settings.model, "message": "连接成功"}

    @router.get("/api/interview-recordings/capability")
    def capability() -> dict[str, Any]:
        return asr_capability(get_config())

    @router.post("/api/interview-events/{event_id}/recording")
    async def upload(event_id: int, request: Request) -> JSONResponse:
        event = get_event(event_id)
        if event is None:
            return JSONResponse(
                {"error": "面试事件不存在", "error_code": "recording_event_missing"},
                status_code=404,
            )
        suffix = (request.query_params.get("filename") or "").rsplit(".", 1)[-1]
        mime = (request.headers.get("content-type") or "application/octet-stream").split(";")[0]
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_RECORDING_BYTES:
                return interview_recording_error_response(
                    InterviewRecordingError("recording_too_large")
                )
            body.extend(chunk)
        try:
            result = store.upload(
                bytes(body),
                application_id=event.application_id,
                event_id=event_id,
                filename=request.query_params.get("filename") or f"recording.{suffix or 'bin'}",
                mime_type=mime,
            )
        except InterviewRecordingError as exc:
            return interview_recording_error_response(exc)
        return JSONResponse(result, status_code=201)

    @router.get("/api/interview-recordings")
    def list_recordings(event_id: int | None = None) -> JSONResponse:
        if event_id is None:
            return JSONResponse(
                {"error": "需要 event_id 查询参数", "error_code": "recording_invalid_request"},
                status_code=422,
            )
        repository = InterviewRecordingsRepository(store._session_factory)
        recordings = repository.list_for_event(event_id)
        return JSONResponse([recording_json(item) for item in recordings])

    @router.get("/api/interview-recordings/{recording_id}")
    def get_recording(recording_id: int) -> JSONResponse:
        repository = InterviewRecordingsRepository(store._session_factory)
        recording = repository.get(recording_id)
        if recording is None:
            return interview_recording_error_response(
                InterviewRecordingError("recording_not_found")
            )
        return JSONResponse(recording_json(recording))

    @router.post("/api/interview-recordings/{recording_id}/transcribe")
    def start_transcription(recording_id: int) -> JSONResponse:
        repository = InterviewRecordingsRepository(store._session_factory)
        recording = repository.get(recording_id)
        if recording is None:
            return interview_recording_error_response(
                InterviewRecordingError("recording_not_found")
            )
        if recording.status in {"transcribing", "completed"}:
            return interview_recording_error_response(
                InterviewRecordingError("recording_state_conflict")
            )
        if asr_settings_from_config(get_config()) is None:
            return interview_recording_error_response(
                InterviewRecordingError("asr_unconfigured")
            )
        try:
            coordinator.start(recording_id, load_config=get_config)
        except InterviewRecordingError as exc:
            return interview_recording_error_response(exc)
        return JSONResponse(recording_json(recording), status_code=202)

    @router.delete("/api/interview-recordings/{recording_id}")
    def delete_recording(recording_id: int) -> Response:
        try:
            store.delete(recording_id)
            return JSONResponse({"message": "Deleted"})
        except InterviewRecordingError as exc:
            return interview_recording_error_response(exc)

    @router.post("/api/interview-recordings/{recording_id}/review-draft")
    def create_review_draft(
        recording_id: int, payload: dict[str, Any] | None = Body(default=None)
    ) -> JSONResponse:
        """转写稿 → AI 复盘草稿；只返回草稿，保存由用户在复盘表单确认。"""
        body = payload or {}
        recording = InterviewRecordingsRepository(store._session_factory).get(recording_id)
        if recording is None:
            return interview_recording_error_response(
                InterviewRecordingError("recording_not_found")
            )
        if recording.status != "completed" or not recording.transcript_text.strip():
            return interview_recording_error_response(
                InterviewRecordingError("recording_state_conflict")
            )
        company = str(body.get("company") or "")[:200]
        position = str(body.get("position") or "")[:200]
        round_name = str(body.get("round") or "")[:50]
        strict = deepseek_strict_credentials(get_config())
        if strict is not None:
            try:
                draft = generate_review_draft_deepseek_strict(
                    strict[0], strict[1], recording.transcript_text,
                    company=company, position=position, round_name=round_name,
                )
                return JSONResponse({"recording_id": recording_id, "draft": draft,
                                     "mode": "deepseek_strict_tool"})
            except RecordingReviewDraftError:
                pass  # 严格模式不可用时回退到通用路径
        model = get_chat_model() if get_chat_model is not None else None
        if model is None:
            return JSONResponse({"error": "AI 服务不可用"}, status_code=503)
        if isinstance(model, JSONResponse):
            return model
        try:
            draft = generate_review_draft(
                model, recording.transcript_text,
                company=company, position=position, round_name=round_name,
            )
        except RecordingReviewDraftError as exc:
            return JSONResponse(
                {"error": "AI 未能生成可用的复盘草稿，请重试", "error_code": str(exc)},
                status_code=502,
            )
        except Exception:  # noqa: BLE001 - 服务商异常统一映射，不外泄细节
            return JSONResponse(
                {"error": "AI 服务调用失败，请检查模型配置后重试", "error_code": "draft_provider_failed"},
                status_code=502,
            )
        return JSONResponse({"recording_id": recording_id, "draft": draft, "mode": "generic"})
    return router