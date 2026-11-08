"""Content-free contracts shared by recording storage, API and diagnostics.

References contain no paths, URLs, credentials or audio bytes. Only the trusted
storage boundary can resolve a recording row to bytes, immediately before an
ASR provider call.
"""

from __future__ import annotations

import re

MAX_RECORDING_BYTES = 500 * 1024 * 1024
ACCEPTED_RECORDING_MIME = frozenset(
    {
        "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/m4a",
        "audio/aac", "audio/wav", "audio/x-wav", "audio/wave", "audio/webm",
    }
)
ACCEPTED_RECORDING_SUFFIX = frozenset({".mp3", ".m4a", ".aac", ".wav", ".webm"})
RECORDING_ID_PATTERN = re.compile(r"^ir_[0-9a-f]{32}\Z")

INTERVIEW_RECORDING_DIRNAME = "interview-recordings"


class InterviewRecordingError(ValueError):
    """Finite, content-free error codes safe for API and diagnostic surfaces."""


def interview_recording_error_message(error: InterviewRecordingError) -> str:
    labels = {
        "recording_too_large": "录音文件不能超过 500 MiB。",
        "recording_format_unsupported": "仅支持 MP3、M4A/AAC、WAV、WebM 音频文件。",
        "recording_empty": "录音文件为空。",
        "recording_event_mismatch": "录音不属于当前面试事件。",
        "recording_not_found": "录音不存在或已被删除。",
        "recording_state_conflict": "当前状态不允许该操作，请刷新后重试。",
        "recording_file_missing": "录音文件已丢失，请重新上传。",
        "asr_unconfigured": "语音识别服务未配置：请在 设置 → AI 与模型 中配置语音识别服务。",
        "asr_request_failed": "语音识别请求失败，请稍后重试或检查服务商状态。",
        "asr_response_invalid": "语音识别返回内容无法解析，请确认服务商与模型支持 OpenAI 兼容转写接口。",
        "asr_chunk_failed": "语音识别分片转写失败，请重试。",
    }
    return labels.get(str(error), "录音不可用，请重新上传。")
