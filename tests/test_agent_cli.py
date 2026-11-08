from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from typer.testing import CliRunner

import offerpilot.agent_cli as agent_cli
from offerpilot.api import create_app
from offerpilot.cli import app as cli_app

runner = CliRunner()
DUMMY_ASR_KEY = "t" * 8


class _Reusable:
    """让每条命令复用同一个 TestClient，而不是每次触发应用生命周期。"""

    def __init__(self, client: TestClient):
        self.client = client

    def __enter__(self) -> TestClient:
        return self.client

    def __exit__(self, *exc: object) -> bool:
        return False


def _wire(monkeypatch, tmp_path, chat_model=None) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path, chat_model=chat_model))
    monkeypatch.setattr(agent_cli, "build_client", lambda: _Reusable(client))
    return client


def _run(*args: str) -> dict | list:
    result = runner.invoke(cli_app, ["track", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_application_add_list_and_status_change(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    created = _run("add-app", "--company", "星澜智能", "--position", "测试开发", "--notes", "Boss 直聘")
    assert created["status"] == "applied"

    _run("set-status", str(created["id"]), "interview")
    apps = _run("apps", "--status", "interview")
    assert [item["id"] for item in apps] == [created["id"]]
    assert apps[0]["notes"] == "Boss 直聘"


def test_closing_requires_reason(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    created = _run("add-app", "--company", "A", "--position", "B")
    result = runner.invoke(cli_app, ["track", "set-status", str(created["id"]), "closed"])
    assert result.exit_code == 1


def test_todo_with_reminder_and_done(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    app_id = _run("add-app", "--company", "A", "--position", "B")["id"]
    todo = _run("add-todo", str(app_id), "--title", "跟进一面结果", "--due", "2026-11-20 10:00")
    assert todo["status"] == "todo" and todo["remind_at"]
    assert [item["id"] for item in _run("todos", "--pending")] == [todo["id"]]

    _run("done", str(todo["id"]))
    assert _run("todos", "--pending") == []


def test_parse_local_time_adds_offset():
    value = agent_cli.parse_local_time("2026-11-20 10:00")
    assert value.startswith("2026-11-20T10:00:00") and ("+" in value[19:] or "-" in value[19:])


def test_transcribe_reports_unconfigured_asr(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    app_id = _run("add-app", "--company", "A", "--position", "B")["id"]
    event = _run("add-interview", str(app_id), "--at", "2026-11-12 14:00")
    sample = tmp_path / "a.wav"
    sample.write_bytes(b"RIFF" + b"\x00" * 64)
    recording = _run("upload", str(event["id"]), str(sample))
    result = runner.invoke(cli_app, ["track", "transcribe", str(recording["id"]), "--no-wait"])
    assert result.exit_code == 1
    assert "asr_unconfigured" in result.stderr


class _DraftModel:
    supports_json_schema = False

    def complete(self, messages, tools, response_format=None):
        return SimpleNamespace(content=json.dumps({
            "summary": "整体顺利", "questions": "- 项目介绍",
            "self_reflection": "表达清晰", "difficulty_points": "缓存细节",
        }, ensure_ascii=False))


def test_review_draft_save_creates_linked_note(monkeypatch, tmp_path):
    import wave

    client = _wire(monkeypatch, tmp_path, chat_model=_DraftModel())
    app_id = _run("add-app", "--company", "星澜智能", "--position", "测试开发")["id"]
    event = _run("add-interview", str(app_id), "--at", "2026-11-12 14:00", "--round", "二面")
    sample = tmp_path / "a.wav"
    with wave.open(str(sample), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    recording = _run("upload", str(event["id"]), str(sample))

    from offerpilot.config import load_config
    from offerpilot.db import session_factory_for_data_dir
    from offerpilot.interview_recordings import InterviewRecordingStore, TranscriptionCoordinator

    config = load_config(tmp_path)
    config.asr.enabled, config.asr.api_key = True, DUMMY_ASR_KEY
    store = InterviewRecordingStore(session_factory_for_data_dir(tmp_path), tmp_path)
    TranscriptionCoordinator(store).run_inline(
        recording["id"], load_config=lambda: config,
        transcribe=lambda s, a, f: {"text": "请介绍一下项目", "segments": []},
    )

    preview = _run("review-draft", str(recording["id"]))
    assert preview["saved"] is False and client.get("/api/notes").json() == []

    saved = _run("review-draft", str(recording["id"]), "--save")
    assert saved["saved"] is True
    note = saved["note"]
    assert note["application_event_id"] == event["id"]
    assert note["round"] == "二面"
    assert note["questions"] == "- 项目介绍"
    assert "总结：整体顺利" in note["self_reflection"]
