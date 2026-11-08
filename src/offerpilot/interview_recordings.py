from __future__ import annotations

# 面试录音：上传存储 + OpenAI 兼容 ASR 转写。
# 上传边界见 interview_recordings_contracts.py；转写为后台线程任务，状态落库，
# 由 API 轮询读取。录音文件保存在 <data_dir>/interview-recordings/ 下。

import hashlib
import json
import re
import shutil
import subprocess  # noqa: S404 - 仅以受控参数调用 ffmpeg/ffprobe
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import httpx

from offerpilot.interview_recordings_contracts import (
    ACCEPTED_RECORDING_SUFFIX,
    INTERVIEW_RECORDING_DIRNAME,
    MAX_RECORDING_BYTES,
    InterviewRecordingError,
)
from offerpilot.repositories.interview_recordings import (
    InterviewRecordingsRepository,
    RecordingCreate,
    TranscriptResult,
    recording_json,
)

_SHA = re.compile(r"^[0-9a-f]{64}\Z")
_SAFE_SUFFIX = re.compile(r"^[. A-Za-z0-9_\u4e00-\u9fff-]{1,120}\Z")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _safe_filename(name: str) -> str:
    name = (name or "recording").strip()
    if not _SAFE_SUFFIX.fullmatch(name):
        return "recording.bin"
    return name


class InterviewRecordingStore:
    """录音文件的受信存储边界：校验、去重落盘、路径解析带符号链接防护。"""

    def __init__(self, session_factory, data_dir: Path):  # type: ignore[no-untyped-def]
        self._session_factory = session_factory
        self._root = Path(data_dir) / INTERVIEW_RECORDING_DIRNAME
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, sha256: str, recording_id: int) -> Path | None:
        if not _SHA.fullmatch(str(sha256 or "")):
            return None
        root = self._root.resolve()
        candidate = root / f"{recording_id}_{sha256[:16]}"
        if not candidate.is_file():
            return None
        try:
            resolved = candidate.resolve()
            if root not in resolved.parents:
                return None
        except OSError:
            return None
        return candidate

    def upload(
        self,
        content: bytes,
        *,
        application_id: int | None,
        event_id: int | None,
        filename: str,
        mime_type: str,
        note_id: int | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise InterviewRecordingError("recording_empty")
        if len(content) > MAX_RECORDING_BYTES:
            raise InterviewRecordingError("recording_too_large")
        suffix = Path(filename or "").suffix.lower()
        if suffix not in ACCEPTED_RECORDING_SUFFIX:
            raise InterviewRecordingError("recording_format_unsupported")
        digest = hashlib.sha256(content).hexdigest()
        repository = InterviewRecordingsRepository(self._session_factory)
        recording = repository.create(
            RecordingCreate(
                application_id=application_id,
                application_event_id=event_id,
                filename=_safe_filename(filename or "recording.bin"),
                mime_type=(mime_type or "")[:120],
                size_bytes=len(content),
                sha256=digest,
            )
        )
        target = self._root / f"{recording.id}_{digest[:16]}"
        if not target.exists():
            self._write_atomic(target, content)
        return recording_json(recording)

    def _write_atomic(self, target: Path, content: bytes) -> None:
        temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temp.write_bytes(content)
        temp.replace(target)

    def delete(self, recording_id: int) -> None:
        repository = InterviewRecordingsRepository(self._session_factory)
        recording = repository.get(recording_id)
        if recording is None:
            raise InterviewRecordingError("recording_not_found")
        repository.delete(recording_id)
        path = self._resolve(recording.sha256, recording.id)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def read_bytes(self, recording_id: int) -> bytes:
        repository = InterviewRecordingsRepository(self._session_factory)
        recording = repository.get(recording_id)
        if recording is None:
            raise InterviewRecordingError("recording_not_found")
        path = self._resolve(recording.sha256, recording.id)
        if path is None:
            raise InterviewRecordingError("recording_file_missing")
        return path.read_bytes()


@dataclass(frozen=True)
class AsrSettings:
    provider: str
    base_url: str
    api_key: str
    model: str
    language: str


def asr_settings_from_config(config: Any) -> AsrSettings | None:
    asr = config.asr
    if not asr.enabled or not asr.api_key.strip() or not asr.base_url.strip() or not asr.model.strip():
        return None
    return AsrSettings(
        provider=asr.provider,
        base_url=asr.base_url.strip(),
        api_key=asr.api_key.strip(),
        model=asr.model.strip(),
        language=asr.language.strip(),
    )


def asr_capability(config: Any) -> dict[str, Any]:
    settings = asr_settings_from_config(config)
    return {
        "enabled": settings is not None,
        "reason": "" if settings is not None else "语音识别服务未配置",
        "provider": config.asr.provider,
        "model": config.asr.model,
        "ffmpeg_available": ffmpeg_available(),
        "max_file_bytes": MAX_RECORDING_BYTES,
    }


TranscribeCall = Callable[[AsrSettings, bytes, str], dict[str, Any]]


def _mask_key(key: str) -> str:
    key = key.strip()
    if not key:
        return ""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 8 else "已设置"


def asr_settings_view(config: Any) -> dict[str, Any]:
    """设置页读取用：密钥只返回是否已设置与掩码，不回传明文。"""
    asr = config.asr
    return {
        "provider": asr.provider,
        "base_url": asr.base_url,
        "model": asr.model,
        "language": asr.language,
        "enabled": asr.enabled,
        "api_key_set": bool(asr.api_key.strip()),
        "api_key_hint": _mask_key(asr.api_key),
        "ffmpeg_available": ffmpeg_available(),
    }


_ASR_EDITABLE = frozenset({"base_url", "model", "language", "enabled", "api_key", "clear_api_key"})


def apply_asr_settings_update(current: Any, payload: dict[str, Any]) -> Any:
    """api_key 为空或缺省时保留原值；clear_api_key=true 时清空。"""
    if set(payload) - _ASR_EDITABLE:
        raise ValueError("包含不支持的字段")
    data = current.model_dump()
    for field in ("base_url", "model", "language"):
        if field in payload:
            if not isinstance(payload[field], str):
                raise ValueError(f"{field} 必须是字符串")
            data[field] = payload[field].strip()
    if "enabled" in payload:
        if not isinstance(payload["enabled"], bool):
            raise ValueError("enabled 必须是布尔值")
        data["enabled"] = payload["enabled"]
    if payload.get("clear_api_key") is True:
        data["api_key"] = ""
    elif isinstance(payload.get("api_key"), str) and payload["api_key"].strip():
        data["api_key"] = payload["api_key"].strip()
    local = ("http://127.0.0.1", "http://localhost")
    if data["base_url"] and not data["base_url"].startswith(("https://", *local)):
        raise ValueError("服务地址需使用 https（本机地址除外）")
    return type(current)(**data)


def silent_wav(seconds: float = 1.0) -> bytes:
    """连接测试用的静音 WAV（16kHz 单声道），不含任何用户内容。"""
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buffer.getvalue()


def openai_compatible_transcribe(
    settings: AsrSettings, audio: bytes, filename: str, *, client: httpx.Client | None = None
) -> dict[str, Any]:
    """POST {base_url}/audio/transcriptions；verbose_json 不被支持时退回 json。"""
    url = settings.base_url.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    data: dict[str, str] = {"model": settings.model, "response_format": "verbose_json"}
    if settings.language:
        data["language"] = settings.language
    http = client or httpx.Client(timeout=600.0)
    try:
        response = http.post(url, headers=headers, data=data, files={"file": (filename, audio)})
        if response.status_code in {400, 422}:
            data["response_format"] = "json"
            response = http.post(url, headers=headers, data=data, files={"file": (filename, audio)})
    except httpx.HTTPError as exc:
        raise InterviewRecordingError("asr_request_failed") from exc
    finally:
        if client is None:
            http.close()
    if response.status_code >= 400:
        raise InterviewRecordingError("asr_request_failed")
    try:
        payload = response.json()
    except ValueError as exc:
        raise InterviewRecordingError("asr_response_invalid") from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str):
        raise InterviewRecordingError("asr_response_invalid")
    segments: list[dict[str, Any]] = []
    for item in payload.get("segments") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            segments.append({
                "start": float(item.get("start") or 0.0),
                "end": float(item.get("end") or 0.0),
                "text": item["text"].strip(),
            })
    return {"text": text.strip(), "segments": segments}


CHUNK_SECONDS = 600


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - 固定参数列表，无 shell
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=120, check=True,
        )
        return round(float(out.stdout.strip()), 2)
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _split_chunks(source: Path, workdir: Path) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []
    try:
        subprocess.run(  # noqa: S603 - 固定参数列表，无 shell
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-vn", "-ac", "1", "-ar", "16000", "-f", "segment",
             "-segment_time", str(CHUNK_SECONDS), "-c:a", "pcm_s16le",
             str(workdir / "chunk_%04d.wav")],
            capture_output=True, timeout=3600, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise InterviewRecordingError("asr_chunk_failed") from exc
    return sorted(workdir.glob("chunk_*.wav"))


class TranscriptionCoordinator:
    """每个录音同一时刻最多一个转写线程；进程退出由 daemon 线程自然终止。"""

    def __init__(self, store: InterviewRecordingStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._active: set[int] = set()

    def start(
        self,
        recording_id: int,
        *,
        load_config: Callable[[], Any],
        transcribe: TranscribeCall = openai_compatible_transcribe,
    ) -> None:
        repository = InterviewRecordingsRepository(self._store._session_factory)
        with self._lock:
            if recording_id in self._active:
                raise InterviewRecordingError("recording_state_conflict")
            self._active.add(recording_id)
        thread = threading.Thread(
            target=self._run,
            args=(recording_id, load_config, transcribe),
            kwargs={"repository": repository},
            daemon=True,
            name=f"asr-{recording_id}",
        )
        thread.start()

    def run_inline(
        self,
        recording_id: int,
        *,
        load_config: Callable[[], Any],
        transcribe: TranscribeCall,
    ) -> None:
        """测试与同步场景：在当前线程执行完整转写流程。"""
        repository = InterviewRecordingsRepository(self._store._session_factory)
        self._run(recording_id, load_config, transcribe, repository=repository)

    def _run(
        self,
        recording_id: int,
        load_config: Callable[[], Any],
        transcribe: TranscribeCall,
        *,
        repository: InterviewRecordingsRepository,
    ) -> None:
        try:
            settings = asr_settings_from_config(load_config())
            if settings is None:
                raise InterviewRecordingError("asr_unconfigured")
            recording = repository.get(recording_id)
            if recording is None:
                raise InterviewRecordingError("recording_not_found")
            audio = self._store.read_bytes(recording_id)
            result = self._transcribe_all(
                recording_id, repository, settings, audio, recording.filename, transcribe
            )
            repository.complete_transcription(recording_id, result)
        except InterviewRecordingError as exc:
            repository.fail_transcription(recording_id, str(exc))
        except Exception:  # noqa: BLE001 - 未知异常统一落库为请求失败，不泄露内容
            repository.fail_transcription(recording_id, "asr_request_failed")
        finally:
            with self._lock:
                self._active.discard(recording_id)

    def _transcribe_all(
        self,
        recording_id: int,
        repository: InterviewRecordingsRepository,
        settings: AsrSettings,
        audio: bytes,
        filename: str,
        transcribe: TranscribeCall,
    ) -> TranscriptResult:
        if not ffmpeg_available():
            # 无 ffmpeg：整文件单次提交，受服务商单文件大小限制。
            repository.set_progress(recording_id, 1, 0)
            part = transcribe(settings, audio, filename or "recording.bin")
            segments = part["segments"] or (
                [{"start": 0.0, "end": 0.0, "text": part["text"]}] if part["text"] else []
            )
            return TranscriptResult(
                text=part["text"],
                segments_json=json.dumps(segments, ensure_ascii=False),
                duration_seconds=None,
                asr_provider=settings.provider,
                asr_model=settings.model,
                chunk_count=1,
            )
        with tempfile.TemporaryDirectory(prefix="offerpilot-asr-") as tmp:
            workdir = Path(tmp)
            source = workdir / ("source" + (Path(filename or "").suffix.lower() or ".bin"))
            source.write_bytes(audio)
            duration = _probe_duration(source)
            chunks = _split_chunks(source, workdir)
            if not chunks:
                raise InterviewRecordingError("asr_chunk_failed")
            repository.set_progress(recording_id, len(chunks), 0)
            texts: list[str] = []
            merged_segments: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks):
                part = transcribe(settings, chunk.read_bytes(), chunk.name)
                offset = float(index * CHUNK_SECONDS)
                if part["text"]:
                    texts.append(part["text"])
                if part["segments"]:
                    for seg in part["segments"]:
                        merged_segments.append({
                            "start": round(seg["start"] + offset, 2),
                            "end": round(seg["end"] + offset, 2),
                            "text": seg["text"],
                        })
                elif part["text"]:
                    merged_segments.append({
                        "start": offset, "end": offset + CHUNK_SECONDS, "text": part["text"],
                    })
                repository.set_progress(recording_id, len(chunks), index + 1)
            return TranscriptResult(
                text="\n".join(texts),
                segments_json=json.dumps(merged_segments, ensure_ascii=False),
                duration_seconds=duration,
                asr_provider=settings.provider,
                asr_model=settings.model,
                chunk_count=len(chunks),
            )
