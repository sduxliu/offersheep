"""面试录音转写稿 → 复盘草稿。

只生成供用户核对的草稿（总结、面试问题、自我反思、薄弱点），不写入任何记录；
保存仍由用户在复盘表单中确认，遵循产品写入需人工确认的约束。

DeepSeek 官方 API 的 response_format 只支持 text / json_object（不支持 json_schema）；
严格按 JSON Schema 输出需走 Tool Calls 的 strict 模式（Beta 端点），且强制指定工具时
必须关闭思考模式。官方 DeepSeek 端点优先走该路径，失败再回退通用路径。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from offerpilot.ai.types import Message
from offerpilot.ai.workflows import parse_json_reply

MAX_TRANSCRIPT_CHARS = 24000
DRAFT_FIELDS = ("summary", "questions", "self_reflection", "difficulty_points")

REVIEW_DRAFT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(DRAFT_FIELDS),
    "properties": {name: {"type": "string"} for name in DRAFT_FIELDS},
}

REVIEW_DRAFT_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "interview_recording_review_draft",
        "strict": True,
        "schema": REVIEW_DRAFT_JSON_SCHEMA,
    },
}

DEEPSEEK_OFFICIAL_HOST = "api.deepseek.com"
DEEPSEEK_STRICT_TOOL_NAME = "submit_review_draft"
DEEPSEEK_STRICT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": DEEPSEEK_STRICT_TOOL_NAME,
        "strict": True,
        "description": "提交面试复盘草稿",
        "parameters": REVIEW_DRAFT_JSON_SCHEMA,
    },
}

SYSTEM_PROMPT = (
    "你是求职面试复盘助手。输入是一场面试录音的自动转写稿，可能含识别错误，"
    "通常没有标注说话人。请只依据转写稿为候选人整理复盘草稿，"
    "不要编造转写稿中没有出现的问题、数字或结论；不确定处注明“（转写不清）”。"
    "只输出 JSON 对象，字段均为中文字符串：\n"
    "summary：3-5 句面试整体概述；\n"
    "questions：面试官提出的问题清单，每行一条，以“- ”开头，可附候选人回答要点；\n"
    "self_reflection：候选人表现的亮点与可改进之处，每行一条；\n"
    "difficulty_points：答得不好或需要补强的知识点，每行一条，附简短补强建议。"
)


class RecordingReviewDraftError(RuntimeError):
    """模型输出无法形成可用草稿；错误码不含转写内容。"""


def _user_prompt(transcript: str, company: str, position: str, round_name: str) -> str:
    parts = [
        f"公司：{company}" if company else "",
        f"岗位：{position}" if position else "",
        f"轮次：{round_name}" if round_name else "",
    ]
    context = "、".join(part for part in parts if part)
    header = f"面试信息：{context}\n" if context else ""
    clipped = transcript.strip()[:MAX_TRANSCRIPT_CHARS]
    return f"{header}面试转写稿如下：\n<<<\n{clipped}\n>>>"


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(line if line.startswith("- ") else f"- {line}" for line in lines)
    return ""


def generate_review_draft(
    model: Any,
    transcript: str,
    *,
    company: str = "",
    position: str = "",
    round_name: str = "",
) -> dict[str, str]:
    if not transcript.strip():
        raise RecordingReviewDraftError("transcript_empty")
    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=_user_prompt(transcript, company, position, round_name)),
    ]
    if bool(getattr(model, "supports_json_schema", False)):
        reply = model.complete(messages, [], response_format=REVIEW_DRAFT_RESPONSE_FORMAT)
    else:
        reply = model.complete(messages, [])
    try:
        payload = parse_json_reply(str(getattr(reply, "content", "") or ""))
    except (RuntimeError, ValueError) as exc:
        raise RecordingReviewDraftError("draft_unparseable") from exc
    draft = {name: _as_text(payload.get(name)) for name in DRAFT_FIELDS}
    if not any(draft.values()):
        raise RecordingReviewDraftError("draft_empty")
    return draft


def deepseek_strict_credentials(config: Any) -> tuple[str, str] | None:
    """当前启用的是 DeepSeek 官方端点时返回 (api_key, model)，否则 None。"""
    provider = config.active_provider()
    host = urlsplit(provider.base_url or "").hostname
    if host != DEEPSEEK_OFFICIAL_HOST or not provider.enabled or not provider.api_key.strip():
        return None
    return provider.api_key.strip(), provider.model


def generate_review_draft_deepseek_strict(
    api_key: str,
    model: str,
    transcript: str,
    *,
    company: str = "",
    position: str = "",
    round_name: str = "",
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """DeepSeek Tool Calls strict 模式：输出由服务端按 JSON Schema 强制约束。"""
    if not transcript.strip():
        raise RecordingReviewDraftError("transcript_empty")
    body = {
        "model": model,
        "max_tokens": 4096,
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(transcript, company, position, round_name)},
        ],
        "tools": [DEEPSEEK_STRICT_TOOL],
        "tool_choice": {"type": "function", "function": {"name": DEEPSEEK_STRICT_TOOL_NAME}},
    }
    http = client or httpx.Client(timeout=180.0)
    try:
        response = http.post(
            "https://api.deepseek.com/beta/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except httpx.HTTPError as exc:
        raise RecordingReviewDraftError("draft_provider_failed") from exc
    finally:
        if client is None:
            http.close()
    if response.status_code >= 400:
        raise RecordingReviewDraftError("draft_provider_failed")
    try:
        message = response.json()["choices"][0]["message"]
        call = next(item for item in message.get("tool_calls") or []
                    if item["function"]["name"] == DEEPSEEK_STRICT_TOOL_NAME)
        payload = json.loads(call["function"]["arguments"])
    except (ValueError, KeyError, IndexError, TypeError, StopIteration) as exc:
        raise RecordingReviewDraftError("draft_unparseable") from exc
    if not isinstance(payload, dict) or set(payload) != set(DRAFT_FIELDS) or not all(
        isinstance(payload[name], str) for name in DRAFT_FIELDS
    ):
        raise RecordingReviewDraftError("draft_schema_mismatch")
    draft = {name: payload[name].strip() for name in DRAFT_FIELDS}
    if not any(draft.values()):
        raise RecordingReviewDraftError("draft_empty")
    return draft
