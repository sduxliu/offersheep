"""`oc track`：面向 ZCode 等编码 Agent 的求职记录命令组。

所有命令通过 HTTP 调用正在运行的本地服务（先执行 `uv run oc start`），
与界面走同一套接口与校验；输出均为 JSON，便于 Agent 解析。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, Optional

import httpx
import typer

from offerpilot.config import load_config, resolve_data_dir

track_app = typer.Typer(help="求职记录：投递、待办提醒、面试录音与复盘（JSON 输出，适合 Agent 调用）")

DEFAULT_API = "http://127.0.0.1:8080"
EVENT_TYPES = ("custom", "deadline", "interview", "written_test", "offer_step")


def build_client() -> httpx.Client:
    """测试可替换为 TestClient；默认连接本机服务并自动携带本地访问令牌。"""
    base_url = os.environ.get("OFFERSHEEP_API", DEFAULT_API)
    headers: dict[str, str] = {}
    try:
        config = load_config(resolve_data_dir())
        if config.auth_enabled and config.auth_token:
            headers["X-OfferPilot-Token"] = config.auth_token
    except OSError:
        pass
    return httpx.Client(base_url=base_url, headers=headers, timeout=300.0)


def _emit(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(message: str, *, status: int | None = None, detail: Any = None) -> NoReturn:
    body: dict[str, Any] = {"ok": False, "error": message}
    if status is not None:
        body["status"] = status
    if detail is not None:
        body["detail"] = detail
    typer.echo(json.dumps(body, ensure_ascii=False), err=True)
    raise typer.Exit(1)


def _request(method: str, path: str, **kwargs: Any) -> Any:
    try:
        with build_client() as client:
            response = client.request(method, "/api" + path, **kwargs)
    except httpx.ConnectError:
        _fail("无法连接 OfferSheep 服务，请先运行 `uv run oc start`")
    if response.status_code >= 400:
        try:
            detail: Any = response.json()
        except ValueError:
            detail = response.text[:500]
        _fail("请求失败", status=response.status_code, detail=detail)
    if not response.content:
        return None
    return response.json()


def parse_local_time(value: str) -> str:
    """接受 `2026-11-10 09:00` / ISO 时间；无时区时按本机时区，返回 RFC3339。"""
    text = value.strip().replace(" ", "T", 1)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        _fail(f"时间格式无效：{value}（示例：2026-11-10 09:00）")
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat(timespec="seconds")


@track_app.command("apps")
def list_apps(status: Optional[str] = typer.Option(None, help="按状态过滤：pending/applied/written_test/interview/offer/closed")) -> None:
    """列出投递记录。"""
    _emit(_request("GET", "/applications", params={"status": status} if status else None))


@track_app.command("add-app")
def add_app(
    company: str = typer.Option(..., help="公司名"),
    position: str = typer.Option(..., help="岗位名"),
    url: str = typer.Option("", help="岗位链接"),
    status: str = typer.Option("applied", help="初始状态，默认 applied（已投递）"),
    notes: str = typer.Option("", help="备注，如投递渠道、内推人"),
) -> None:
    """新增一条投递记录。"""
    payload = {"company_name": company, "position_name": position, "job_url": url,
               "status": status, "notes": notes}
    _emit(_request("POST", "/applications", json=payload))


@track_app.command("set-status")
def set_status(
    app_id: int = typer.Argument(..., help="投递 ID"),
    status: str = typer.Argument(..., help="新状态：pending/applied/written_test/interview/offer/closed"),
    reason: str = typer.Option("", help="关闭原因（status=closed 时必填）"),
) -> None:
    """更新投递状态（保留其余字段不变）。"""
    current = _request("GET", f"/applications/{app_id}")
    payload = {key: current.get(key) for key in ("company_name", "position_name", "job_url", "notes")}
    payload["status"] = status
    if status == "closed":
        if not reason:
            _fail("关闭投递需要 --reason")
        payload["closed_reason"] = reason
    _emit(_request("PUT", f"/applications/{app_id}", json=payload))


def _event_payload(event: dict[str, Any], **changes: Any) -> dict[str, Any]:
    keys = ("application_id", "event_type", "subtype", "tags", "round", "scheduled_at",
            "duration_minutes", "location", "notes", "remind_at", "status")
    payload = {key: event.get(key) for key in keys}
    payload.update(changes)
    return payload


@track_app.command("add-todo")
def add_todo(
    app_id: int = typer.Argument(..., help="投递 ID（待办挂在某条投递下）"),
    title: str = typer.Option(..., help="待办标题，如「跟进一面结果」"),
    due: str = typer.Option(..., help="截止时间，如 2026-11-10 09:00"),
    remind: Optional[str] = typer.Option(None, help="提醒时间，默认截止前 1 小时"),
    event_type: str = typer.Option("custom", "--type", help="类型：custom/deadline/interview/written_test/offer_step"),
    minutes: int = typer.Option(30, help="时长（分钟）"),
    notes: str = typer.Option("", help="备注"),
) -> None:
    """创建待办/日程并设置提醒。"""
    if event_type not in EVENT_TYPES:
        _fail(f"--type 只能是 {', '.join(EVENT_TYPES)}")
    scheduled = parse_local_time(due)
    remind_at = parse_local_time(remind) if remind else (
        datetime.fromisoformat(scheduled) - timedelta(hours=1)
    ).isoformat(timespec="seconds")
    payload = {"application_id": app_id, "event_type": event_type, "subtype": title,
               "scheduled_at": scheduled, "duration_minutes": max(1, minutes),
               "notes": notes, "remind_at": remind_at, "status": "todo"}
    _emit(_request("POST", "/application-events", json=payload))


@track_app.command("add-interview")
def add_interview(
    app_id: int = typer.Argument(..., help="投递 ID"),
    at: str = typer.Option(..., help="面试时间，如 2026-11-12 14:00"),
    round_name: str = typer.Option("一面", "--round", help="轮次"),
    minutes: int = typer.Option(60, help="时长（分钟）"),
    location: str = typer.Option("", help="地点或会议链接"),
) -> None:
    """登记一场面试（默认面试前 1 天提醒）。"""
    scheduled = parse_local_time(at)
    remind_at = (datetime.fromisoformat(scheduled) - timedelta(days=1)).isoformat(timespec="seconds")
    payload = {"application_id": app_id, "event_type": "interview", "subtype": round_name,
               "scheduled_at": scheduled, "duration_minutes": max(1, minutes),
               "location": location, "remind_at": remind_at, "status": "todo"}
    _emit(_request("POST", "/application-events", json=payload))


@track_app.command("todos")
def list_todos(
    app_id: Optional[int] = typer.Option(None, "--app", help="只看某条投递"),
    pending: bool = typer.Option(False, help="只看未完成"),
) -> None:
    """列出待办与日程。"""
    events = _request("GET", "/application-events",
                      params={"application_id": app_id} if app_id else None)
    if pending:
        events = [item for item in events if item.get("status") == "todo"]
    _emit(events)


@track_app.command("done")
def mark_done(event_id: int = typer.Argument(..., help="待办/日程 ID")) -> None:
    """把待办或面试标记为完成。"""
    event = _request("GET", f"/application-events/{event_id}")
    _emit(_request("PUT", f"/application-events/{event_id}", json=_event_payload(event, status="done")))


@track_app.command("reminders")
def reminders(timezone: str = typer.Option("Asia/Shanghai", help="显示时区")) -> None:
    """查看当前需要处理的提醒（今日提醒卡片的数据源）。"""
    _emit(_request("GET", "/reminders/candidates", params={"timezone": timezone}))


@track_app.command("mail-import")
def mail_import(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="邮件文本文件（≤100KB，UTF-8）"),
    subject: str = typer.Option("手动提供的邮件", help="邮件主题"),
    received: Optional[str] = typer.Option(None, help="收到时间，如 2026-11-08 10:00"),
) -> None:
    """导入一封求职邮件：本地规则提取面试/笔试后生成待审建议，不自动写入日程。"""
    text = file.read_text(encoding="utf-8", errors="replace")
    moment = parse_local_time(received) if received else datetime.now().astimezone().isoformat(timespec="seconds")
    payload: dict[str, Any] = {"subject": subject, "body_text": text, "received_at": moment}
    _emit(_request("POST", "/job-mail/imports", json=payload))


@track_app.command("mail-suggestions")
def mail_suggestions(
    pending_only: bool = typer.Option(True, "--pending/--all", help="只看待审（默认）或全部"),
) -> None:
    """查看求职邮件生成的待审日程建议（用界面「提醒」页核对后写入）。"""
    items = _request("GET", "/job-mail/suggestions", params={"status": "" if not pending_only else "pending",
                                                             "limit": 100})
    _emit(items)


@track_app.command("upload")
def upload_recording(
    event_id: int = typer.Argument(..., help="面试日程 ID"),
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="录音文件 mp3/m4a/wav/webm"),
) -> None:
    """上传面试录音。"""
    _emit(_request("POST", f"/interview-events/{event_id}/recording",
                   params={"filename": file.name}, content=file.read_bytes(),
                   headers={"Content-Type": "application/octet-stream"}))


@track_app.command("transcribe")
def transcribe(
    recording_id: int = typer.Argument(..., help="录音 ID"),
    wait: bool = typer.Option(True, help="等待转写完成后再返回"),
    timeout: int = typer.Option(1800, help="最长等待秒数"),
) -> None:
    """开始转写录音（默认等待完成并输出转写稿）。"""
    result = _request("POST", f"/interview-recordings/{recording_id}/transcribe")
    deadline = time.monotonic() + timeout
    while wait and result.get("status") == "transcribing" and time.monotonic() < deadline:
        time.sleep(3)
        result = _request("GET", f"/interview-recordings/{recording_id}")
    _emit(result)


@track_app.command("recording")
def show_recording(recording_id: int = typer.Argument(..., help="录音 ID")) -> None:
    """查看录音状态与转写稿。"""
    _emit(_request("GET", f"/interview-recordings/{recording_id}"))


@track_app.command("review-draft")
def review_draft(
    recording_id: int = typer.Argument(..., help="已完成转写的录音 ID"),
    save: bool = typer.Option(False, help="把草稿保存为复盘记录（默认只输出草稿，不写入）"),
) -> None:
    """用 AI 从转写稿生成复盘草稿；加 --save 才会写入复盘。"""
    recording = _request("GET", f"/interview-recordings/{recording_id}")
    context: dict[str, Any] = {}
    event: dict[str, Any] | None = None
    if recording.get("application_event_id"):
        event = _request("GET", f"/application-events/{recording['application_event_id']}")
        context = {"company": event.get("company_name") or "", "position": event.get("position_name") or "",
                   "round": event.get("subtype") or ""}
    draft = _request("POST", f"/interview-recordings/{recording_id}/review-draft", json=context)["draft"]
    if not save:
        _emit({"saved": False, "draft": draft})
        return
    if event is None:
        _fail("录音未绑定面试日程，无法保存为复盘")
    reflection = "\n".join(part for part in (f"总结：{draft['summary']}" if draft["summary"] else "",
                                              draft["self_reflection"]) if part)
    note = _request("POST", f"/applications/{event['application_id']}/notes", json={
        "round": context.get("round", ""),
        "date": str(event.get("scheduled_at") or "")[:10],
        "questions": draft["questions"],
        "self_reflection": reflection,
        "difficulty_points": draft["difficulty_points"],
        "application_event_id": event["id"],
    })
    _emit({"saved": True, "note": note, "draft": draft})
