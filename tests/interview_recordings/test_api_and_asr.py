from __future__ import annotations

import wave
import struct
import io

import httpx
import pytest
from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.interview_recordings import (
    AsrSettings,
    TranscriptionCoordinator,
    InterviewRecordingStore,
    openai_compatible_transcribe,
)
from offerpilot.interview_recordings_contracts import InterviewRecordingError
from offerpilot.db import session_factory_for_data_dir

# 合成的非凭据占位串（"t"*8），仅用于构造 AsrSettings 结构，不指向任何真实服务。
DUMMY_ASR_KEY = "t" * 8


def _seed(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "星澜智能", "position_name": "测试开发"},
    ).json()
    event = client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "interview",
            "subtype": "一面",
            "scheduled_at": "2026-11-07T15:00:00+08:00",
            "duration_minutes": 60,
        },
    ).json()
    return client, app, event


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"".join(
            struct.pack("<h", 3000 if i % 100 < 50 else -3000) for i in range(32000)
        ))
    return buffer.getvalue()


def test_recording_upload_list_get_delete_lifecycle(tmp_path):
    client, _app, event = _seed(tmp_path)
    audio = _wav()
    response = client.post(
        f"/api/interview-events/{event['id']}/recording?filename=面试录音.wav",
        content=audio,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["application_event_id"] == event["id"]
    assert body["size_bytes"] == len(audio)
    assert body["filename"] == "面试录音.wav"

    listing = client.get(f"/api/interview-recordings?event_id={event['id']}")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [body["id"]]

    assert client.get(f"/api/interview-recordings/{body['id']}").status_code == 200
    assert client.delete(f"/api/interview-recordings/{body['id']}").status_code == 200
    assert client.get(f"/api/interview-recordings/{body['id']}").status_code == 404


def test_recording_rejects_unsupported_format(tmp_path):
    client, _app, event = _seed(tmp_path)
    assert client.post(
        f"/api/interview-events/{event['id']}/recording?filename=a.txt",
        content=b"123",
    ).status_code == 415


def test_transcribe_requires_asr_configuration(tmp_path):
    client, _app, event = _seed(tmp_path)
    recording = client.post(
        f"/api/interview-events/{event['id']}/recording?filename=a.wav", content=_wav()
    ).json()
    response = client.post(f"/api/interview-recordings/{recording['id']}/transcribe")
    assert response.status_code == 422
    assert response.json()["error_code"] == "asr_unconfigured"


def test_openai_compatible_transcribe_retries_plain_json(monkeypatch):
    settings = AsrSettings(
        provider="openai_compatible", base_url="https://asr.example/v1",
        api_key=DUMMY_ASR_KEY, model="SenseVoiceSmall", language="zh",
    )
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": "verbose_json unsupported"})
        return httpx.Response(200, json={"text": " 你好，请介绍一下项目。 "})

    with httpx.Client(transport=httpx.MockTransport(handler)) as fake:
        payload = openai_compatible_transcribe(settings, b"audio-bytes", "a.wav", client=fake)
    assert payload["text"] == "你好，请介绍一下项目。"
    assert payload["segments"] == []


def test_openai_compatible_transcribe_parses_segments(monkeypatch):
    settings = AsrSettings(
        provider="openai_compatible", base_url="https://asr.example/v1",
        api_key=DUMMY_ASR_KEY, model="SenseVoiceSmall", language="zh",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "text": "第一句。第二句。",
            "segments": [
                {"start": 0.0, "end": 1.5, "text": " 第一句。 "},
                {"start": 1.5, "end": 3.0, "text": "第二句。"},
            ],
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as fake:
        rich = openai_compatible_transcribe(settings, b"audio", "a.wav", client=fake)
    assert rich["segments"][1]["text"] == "第二句。"
    assert rich["segments"][0]["start"] == 0.0


def test_openai_compatible_transcribe_maps_errors(monkeypatch):
    settings = AsrSettings(
        provider="openai_compatible", base_url="https://asr.example/v1",
        api_key=DUMMY_ASR_KEY, model="m", language="zh",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with httpx.Client(transport=httpx.MockTransport(handler)) as fake:
        with pytest.raises(InterviewRecordingError) as exc_info:
            openai_compatible_transcribe(settings, b"audio", "a.wav", client=fake)
    assert str(exc_info.value) == "asr_request_failed"


def test_transcribe_inline_with_mocked_asr_completes(tmp_path):
    client, _app, event = _seed(tmp_path)
    recording = client.post(
        f"/api/interview-events/{event['id']}/recording?filename=a.wav",
        content=_wav(),
    ).json()
    from offerpilot.config import load_config

    config = load_config(tmp_path)
    config.asr.enabled = True
    config.asr.api_key = DUMMY_ASR_KEY
    config.asr.base_url = "https://asr.example/v1"
    config.asr.model = "SenseVoiceSmall"

    def fake_transcribe(settings, audio: bytes, filename: str) -> dict:
        assert audio
        return {"text": "请介绍一下你的项目。", "segments": [
            {"start": 0.0, "end": 2.0, "text": "请介绍一下你的项目。"},
        ]}

    store = InterviewRecordingStore(session_factory_for_data_dir(tmp_path), tmp_path)
    coordinator = TranscriptionCoordinator(store)
    coordinator.run_inline(
        recording["id"], load_config=lambda: config, transcribe=fake_transcribe
    )
    final = client.get(f"/api/interview-recordings/{recording['id']}").json()
    assert final["status"] == "completed"
    assert final["transcript_text"] == "请介绍一下你的项目。"
    assert final["transcript_segments"][0]["text"] == "请介绍一下你的项目。"
    assert final["chunk_count"] == 1 and final["chunks_done"] == 1


def test_asr_settings_masks_key_keeps_it_when_blank_and_can_clear(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    initial = client.get("/api/settings/asr").json()
    assert initial["api_key_set"] is False and initial["enabled"] is False

    saved = client.put("/api/settings/asr", json={"api_key": DUMMY_ASR_KEY, "enabled": True})
    assert saved.status_code == 200
    body = saved.json()
    assert body["api_key_set"] is True and body["enabled"] is True
    assert DUMMY_ASR_KEY not in saved.text

    kept = client.put("/api/settings/asr", json={"api_key": "", "model": "m2"}).json()
    assert kept["api_key_set"] is True and kept["model"] == "m2"

    cleared = client.put("/api/settings/asr", json={"clear_api_key": True}).json()
    assert cleared["api_key_set"] is False


def test_asr_settings_rejects_unknown_fields_and_plain_http(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    assert client.put("/api/settings/asr", json={"secret": "x"}).status_code == 422
    assert client.put(
        "/api/settings/asr", json={"base_url": "http://asr.example/v1"}
    ).status_code == 422
    assert client.put(
        "/api/settings/asr", json={"base_url": "http://127.0.0.1:9000/v1"}
    ).status_code == 200


def test_asr_settings_test_reports_unconfigured(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    result = client.post("/api/settings/asr/test").json()
    assert result["ok"] is False
    assert "未配置" in result["error"]


class _DraftModel:
    supports_json_schema = True

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def complete(self, messages, tools, response_format=None):
        self.calls.append({"messages": messages, "response_format": response_format})
        from types import SimpleNamespace

        return SimpleNamespace(content=self.content)


def _completed_recording(tmp_path, model):
    import json as _json

    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    _app = client.post(
        "/api/applications", json={"company_name": "星澜智能", "position_name": "测试开发"}
    ).json()
    event = client.post("/api/application-events", json={
        "application_id": _app["id"], "event_type": "interview", "subtype": "一面",
        "scheduled_at": "2026-11-07T15:00:00+08:00", "duration_minutes": 60,
    }).json()
    recording = client.post(
        f"/api/interview-events/{event['id']}/recording?filename=a.wav", content=_wav()
    ).json()
    from offerpilot.config import load_config

    config = load_config(tmp_path)
    config.asr.enabled, config.asr.api_key = True, DUMMY_ASR_KEY
    store = InterviewRecordingStore(session_factory_for_data_dir(tmp_path), tmp_path)
    TranscriptionCoordinator(store).run_inline(
        recording["id"], load_config=lambda: config,
        transcribe=lambda s, a, f: {"text": "请介绍一下你的项目。我做过缓存优化。", "segments": []},
    )
    assert _json.loads(_json.dumps(recording))["id"]
    return client, recording


def test_review_draft_returns_structured_draft_without_saving(tmp_path):
    payload = '{"summary":"整体顺利","questions":["项目介绍"],"self_reflection":"表达清晰","difficulty_points":"缓存细节"}'
    model = _DraftModel(payload)
    client, recording = _completed_recording(tmp_path, model)

    response = client.post(
        f"/api/interview-recordings/{recording['id']}/review-draft",
        json={"company": "星澜智能", "position": "测试开发", "round": "一面"},
    )
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["questions"] == "- 项目介绍"
    assert draft["summary"] == "整体顺利"
    assert model.calls[0]["response_format"]["type"] == "json_schema"
    assert "缓存优化" in model.calls[0]["messages"][1].content
    assert client.get("/api/notes").json() == []


def test_review_draft_requires_completed_transcript(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, chat_model=_DraftModel("{}")))
    _seed_client, _app, event = _seed(tmp_path)
    recording = client.post(
        f"/api/interview-events/{event['id']}/recording?filename=a.wav", content=_wav()
    ).json()
    response = client.post(f"/api/interview-recordings/{recording['id']}/review-draft")
    assert response.status_code == 409


def test_review_draft_maps_unusable_model_output(tmp_path):
    client, recording = _completed_recording(tmp_path, _DraftModel("不是 JSON"))
    response = client.post(f"/api/interview-recordings/{recording['id']}/review-draft")
    assert response.status_code == 502
    assert response.json()["error_code"] == "draft_unparseable"


_STRICT_DRAFT = {"summary": "整体顺利", "questions": "- 项目介绍",
                 "self_reflection": "表达清晰", "difficulty_points": "缓存细节"}


def _strict_reply(arguments: dict) -> httpx.Response:
    import json as _json

    return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [{
        "id": "call_1", "type": "function",
        "function": {"name": "submit_review_draft", "arguments": _json.dumps(arguments, ensure_ascii=False)},
    }]}}]})


def test_deepseek_strict_request_contract_and_parsing():
    import json as _json

    from offerpilot.ai.recording_review_draft import generate_review_draft_deepseek_strict

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": _json.loads(request.content)})
        return _strict_reply(_STRICT_DRAFT)

    with httpx.Client(transport=httpx.MockTransport(handler)) as fake:
        draft = generate_review_draft_deepseek_strict(
            DUMMY_ASR_KEY, "deepseek-flash", "请介绍一下项目", round_name="一面", client=fake,
        )
    assert draft == _STRICT_DRAFT
    body = seen[0]["body"]
    assert seen[0]["url"] == "https://api.deepseek.com/beta/chat/completions"
    assert body["thinking"] == {"type": "disabled"}
    assert body["tool_choice"]["function"]["name"] == "submit_review_draft"
    tool = body["tools"][0]["function"]
    assert tool["strict"] is True
    assert tool["parameters"]["additionalProperties"] is False
    assert set(tool["parameters"]["required"]) == set(_STRICT_DRAFT)
    assert "response_format" not in body


def test_deepseek_strict_rejects_schema_mismatch_and_provider_error():
    from offerpilot.ai.recording_review_draft import (
        RecordingReviewDraftError,
        generate_review_draft_deepseek_strict,
    )

    replies = iter([_strict_reply({"summary": "缺字段"}), httpx.Response(400, json={"error": {}})])
    with httpx.Client(transport=httpx.MockTransport(lambda request: next(replies))) as fake:
        with pytest.raises(RecordingReviewDraftError) as mismatch:
            generate_review_draft_deepseek_strict(DUMMY_ASR_KEY, "m", "转写", client=fake)
        with pytest.raises(RecordingReviewDraftError) as failed:
            generate_review_draft_deepseek_strict(DUMMY_ASR_KEY, "m", "转写", client=fake)
    assert str(mismatch.value) == "draft_schema_mismatch"
    assert str(failed.value) == "draft_provider_failed"


def test_deepseek_strict_credentials_only_for_official_endpoint():
    from offerpilot.ai.recording_review_draft import deepseek_strict_credentials
    from offerpilot.config import AIProviderProfile, Config

    def config_for(base_url: str) -> Config:
        return Config(active_provider_id="p", providers=[AIProviderProfile(
            id="p", provider="openai_compatible", base_url=base_url,
            api_key=DUMMY_ASR_KEY, model="deepseek-flash")])

    assert deepseek_strict_credentials(config_for("https://api.deepseek.com/v1")) == (
        DUMMY_ASR_KEY, "deepseek-flash")
    assert deepseek_strict_credentials(config_for("https://api.siliconflow.cn/v1")) is None
    assert deepseek_strict_credentials(config_for("https://api.deepseek.com.evil.example/v1")) is None


def _use_deepseek_provider(tmp_path) -> None:
    from offerpilot.config import AIProviderProfile, load_config, save_config

    config = load_config(tmp_path)
    config.providers = [AIProviderProfile(
        id="ds", provider="openai_compatible", base_url="https://api.deepseek.com/v1",
        api_key=DUMMY_ASR_KEY, model="deepseek-flash")]
    config.active_provider_id = "ds"
    save_config(tmp_path, config)


def test_review_draft_route_prefers_deepseek_strict_mode(tmp_path, monkeypatch):
    import offerpilot.interview_recording_routes as routes

    model = _DraftModel('{"summary":"通用路径"}')
    client, recording = _completed_recording(tmp_path, model)
    _use_deepseek_provider(tmp_path)
    calls: list[tuple] = []

    def fake_strict(api_key, model_name, transcript, **context):
        calls.append((model_name, context["round_name"]))
        return dict(_STRICT_DRAFT)

    monkeypatch.setattr(routes, "generate_review_draft_deepseek_strict", fake_strict)
    response = client.post(
        f"/api/interview-recordings/{recording['id']}/review-draft", json={"round": "一面"}
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "deepseek_strict_tool"
    assert response.json()["draft"] == _STRICT_DRAFT
    assert calls == [("deepseek-flash", "一面")]
    assert model.calls == []


def test_review_draft_route_falls_back_when_strict_mode_fails(tmp_path, monkeypatch):
    import offerpilot.interview_recording_routes as routes
    from offerpilot.ai.recording_review_draft import RecordingReviewDraftError

    payload = '{"summary":"通用路径","questions":"- 项目","self_reflection":"","difficulty_points":""}'
    model = _DraftModel(payload)
    client, recording = _completed_recording(tmp_path, model)
    _use_deepseek_provider(tmp_path)

    def failing_strict(*args, **kwargs):
        raise RecordingReviewDraftError("draft_provider_failed")

    monkeypatch.setattr(routes, "generate_review_draft_deepseek_strict", failing_strict)
    response = client.post(f"/api/interview-recordings/{recording['id']}/review-draft")
    assert response.status_code == 200
    assert response.json()["mode"] == "generic"
    assert response.json()["draft"]["summary"] == "通用路径"
    assert len(model.calls) == 1
