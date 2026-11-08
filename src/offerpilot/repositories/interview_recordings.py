from __future__ import annotations

# 业务地图：docs/architecture/code-map/interview.md（面试录音转写与复盘）。
# InterviewRecording 保存上传的录音事实与转写结果；复盘字段填充与 AI 提案仍由
# notes / interview_review_proposals 链路负责，本仓库不回写复盘。

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import InterviewRecording
from offerpilot.repositories.session_binding import (
    finish_repository_write,
    repository_session,
)


@dataclass(frozen=True)
class RecordingCreate:
    application_id: int | None
    application_event_id: int | None
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    segments_json: str
    duration_seconds: float | None
    asr_provider: str
    asr_model: str
    chunk_count: int


class InterviewRecordingsRepository:
    def __init__(self, session_factory: sessionmaker[Session], session: Session | None = None):
        self._session_factory = session_factory
        self._session = session

    def create(self, data: RecordingCreate) -> InterviewRecording:
        with repository_session(self._session_factory, self._session) as session:
            recording = InterviewRecording(
                application_id=data.application_id,
                application_event_id=data.application_event_id,
                filename=data.filename[:255],
                mime_type=data.mime_type[:120],
                size_bytes=max(0, int(data.size_bytes)),
                sha256=data.sha256,
                status="uploaded",
            )
            session.add(recording)
            session.flush()
            session.refresh(recording)
            finish_repository_write(session, self._session)
            return recording

    def get(self, recording_id: int) -> InterviewRecording | None:
        with repository_session(self._session_factory, self._session) as session:
            return session.get(InterviewRecording, recording_id)

    def list_for_event(self, event_id: int) -> list[InterviewRecording]:
        with repository_session(self._session_factory, self._session) as session:
            return list(
                session.scalars(
                    select(InterviewRecording)
                    .where(InterviewRecording.application_event_id == event_id)
                    .order_by(InterviewRecording.id.desc())
                )
            )

    def start_transcription(self, recording_id: int) -> InterviewRecording | None:
        """uploaded/failed → transcribing；completed/transcribing 由调用方拒绝。"""
        with repository_session(self._session_factory, self._session) as session:
            recording = session.get(InterviewRecording, recording_id)
            if recording is None:
                return None
            if recording.status in {"transcribing", "completed"}:
                return recording
            recording.status = "transcribing"
            recording.error_code = ""
            recording.chunks_done = 0
            recording.chunk_count = 0
            session.add(recording)
            finish_repository_write(session, self._session)
            session.refresh(recording)
            return recording

    def set_progress(self, recording_id: int, chunk_count: int, chunks_done: int) -> None:
        with repository_session(self._session_factory, self._session) as session:
            recording = session.get(InterviewRecording, recording_id)
            if recording is None:
                return
            recording.chunk_count = max(0, int(chunk_count))
            recording.chunks_done = max(0, int(chunks_done))
            session.add(recording)
            finish_repository_write(session, self._session)

    def complete_transcription(self, recording_id: int, result: TranscriptResult) -> None:
        with repository_session(self._session_factory, self._session) as session:
            recording = session.get(InterviewRecording, recording_id)
            if recording is None:
                return
            recording.transcript_text = result.text
            recording.transcript_segments_json = result.segments_json
            recording.duration_seconds = result.duration_seconds
            recording.asr_provider = result.asr_provider[:120]
            recording.asr_model = result.asr_model[:120]
            recording.chunk_count = max(0, int(result.chunk_count))
            recording.chunks_done = recording.chunk_count
            recording.status = "completed"
            recording.error_code = ""
            session.add(recording)
            finish_repository_write(session, self._session)

    def fail_transcription(self, recording_id: int, error_code: str) -> None:
        with repository_session(self._session_factory, self._session) as session:
            recording = session.get(InterviewRecording, recording_id)
            if recording is None:
                return
            recording.status = "failed"
            recording.error_code = str(error_code)[:120]
            session.add(recording)
            finish_repository_write(session, self._session)

    def delete(self, recording_id: int) -> bool:
        with repository_session(self._session_factory, self._session) as session:
            recording = session.get(InterviewRecording, recording_id)
            if recording is None:
                return False
            session.delete(recording)
            finish_repository_write(session, self._session)
            return True


def recording_json(recording: InterviewRecording) -> dict[str, Any]:
    return {
        "id": recording.id,
        "application_id": recording.application_id,
        "application_event_id": recording.application_event_id,
        "note_id": recording.note_id,
        "filename": recording.filename,
        "mime_type": recording.mime_type,
        "size_bytes": recording.size_bytes,
        "duration_seconds": recording.duration_seconds,
        "status": recording.status,
        "error_code": recording.error_code,
        "transcript_text": recording.transcript_text,
        "transcript_segments": json.loads(recording.transcript_segments_json or "[]"),
        "transcript_language": recording.transcript_language,
        "asr_provider": recording.asr_provider,
        "asr_model": recording.asr_model,
        "chunk_count": recording.chunk_count,
        "chunks_done": recording.chunks_done,
        "created_at": recording.created_at.isoformat() if recording.created_at else None,
        "updated_at": recording.updated_at.isoformat() if recording.updated_at else None,
    }
