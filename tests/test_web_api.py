from __future__ import annotations

import http.client
import os
import sys
import threading
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from ai_collab import web_api
from ai_collab.web_api import (
    ProviderRun,
    WebApiHandler,
    WebApiState,
    _build_provider_command,
    _parse_unified_diff,
    _run_provider_reply,
    _stream_provider_output,
)


def test_content_diff_detects_new_file_without_git(tmp_path: Path) -> None:
    before = web_api._snapshot_contents(str(tmp_path))
    (tmp_path / "Hello.md").write_text("Hello world.\nsecond line\n", encoding="utf-8")
    after = web_api._snapshot_contents(str(tmp_path))
    review = web_api._diff_content_snapshots(before, after)
    files = {item["path"]: item for item in review["files"]}
    assert "Hello.md" in files
    assert files["Hello.md"]["status"] == "added"
    assert files["Hello.md"]["add"] == 2


def test_content_diff_only_reports_changed_line(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    before = web_api._snapshot_contents(str(tmp_path))
    target.write_text("a\nb\nCHANGED\nd\ne\n", encoding="utf-8")
    after = web_api._snapshot_contents(str(tmp_path))
    review = web_api._diff_content_snapshots(before, after)
    files = {item["path"]: item for item in review["files"]}
    assert files["app.py"]["add"] == 1
    assert files["app.py"]["del"] == 1


def _routing_config(**clis: str) -> SimpleNamespace:
    base = {"claude": "echo", "codex": "echo", "gemini": "echo"}
    base.update(clis)
    strengths = {
        "claude": ["reasoning", "code-review", "architecture", "documentation", "security"],
        "codex": ["implementation", "testing", "debugging", "integration", "backend"],
        "gemini": ["visual-design", "html-css", "research", "ecosystem", "frontend"],
    }
    return SimpleNamespace(
        current_controller="codex",
        providers={name: SimpleNamespace(enabled=True, strengths=strengths[name], cli=base[name]) for name in strengths},
    )


def test_compact_title_keeps_chinese_title_short() -> None:
    title = web_api._compact_title("帮我新建一个用户登录页面并调整样式")
    assert len(title) <= 10
    assert "用户登录" in title


def test_reply_to_run_routes_with_workspace_path_before_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = WebApiState(tmp_path)
    workspace = tmp_path / "mycode"
    workspace.mkdir()
    run = state.create_run(workspace, "做一个前端页面")
    called: dict[str, object] = {}

    def fake_route(config: object, message: str, *, cwd: str | None = None) -> str:
        called["cwd"] = cwd
        return "codex"

    monkeypatch.setattr(web_api, "_route_controller", fake_route)
    monkeypatch.setattr(web_api, "_run_provider_reply", lambda *args, **kwargs: "ok")

    state.reply_to_run(run, "做一个前端页面")
    assert called["cwd"] == str(workspace.resolve())


def test_route_controller_picks_provider_by_strengths() -> None:
    config = _routing_config()
    assert web_api._route_controller(config, "帮我审查一下这段代码的安全漏洞") == "claude"
    assert web_api._route_controller(config, "实现一个登录接口并加测试") == "codex"
    assert web_api._route_controller(config, "设计一个前端界面的配色方案") == "gemini"
    assert web_api._route_controller(config, "做一个前端页面，调整下样式和配色") == "gemini"
    # No routing keyword → fall back to the current controller.
    assert web_api._route_controller(config, "你好") == "codex"


def test_route_controller_skips_unavailable_clis() -> None:
    # Gemini's CLI is not installed → a frontend task must not route to it.
    config = _routing_config(gemini="definitely-not-a-real-cli-xyz")
    assert web_api._route_controller(config, "做一个前端页面调整样式") != "gemini"
    # Current controller unavailable → route to an available provider instead.
    config2 = _routing_config(codex="definitely-not-a-real-cli-xyz")
    assert web_api._route_controller(config2, "你好") in {"claude", "gemini"}


def test_route_controller_falls_back_to_default_when_probe_reports_trust_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _routing_config()

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "Gemini CLI is not running in a trusted directory. Use --skip-trust."

    monkeypatch.setattr(web_api.subprocess, "run", lambda *args, **kwargs: FakeResult())
    web_api._PROVIDER_HEALTH.clear()
    assert web_api._route_controller(config, "做一个前端页面，调整下样式和配色", cwd=str(tmp_path)) == "codex"


def test_route_controller_honors_explicit_provider_request(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _routing_config()

    def fake_judge(cfg: object, message: str) -> str:
        low = message.lower()
        if "报错" in message:
            return ""  # only mentioned/complained about a model → not a request
        if "claude" in low:
            return "claude"
        if "gemini" in low:
            return "gemini"
        return ""

    monkeypatch.setattr(web_api, "_judge_provider_with_llm", fake_judge)
    # A frontend task would normally route to gemini, but the judged "用 claude" wins.
    assert web_api._route_controller(config, "这个前端页面请一定要用 claude 来做") == "claude"
    assert web_api._route_controller(config, "帮我用 gemini 调研一下") == "gemini"
    # Merely mentioning a provider (judge says "none") must NOT override routing.
    assert web_api._route_controller(config, "claude 之前报错了，帮我实现登录接口并加测试") == "codex"


def test_explicit_provider_request_rule_fallback() -> None:
    config = _routing_config()
    assert web_api._explicit_provider_request(config, "请用 claude 来做", use_llm=False) == "claude"
    assert web_api._explicit_provider_request(config, "切到 gemini", use_llm=False) == "gemini"
    # A bare mention without a request verb is not an explicit request.
    assert web_api._explicit_provider_request(config, "codex 报错了", use_llm=False) is None


def test_explicit_provider_request_skips_llm_without_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_judge(cfg: object, message: str) -> str:
        calls["n"] += 1
        return ""

    monkeypatch.setattr(web_api, "_judge_provider_with_llm", fake_judge)
    config = _routing_config()
    # No provider named → never spend an LLM call (zero cost for ordinary messages).
    assert web_api._explicit_provider_request(config, "实现一个登录接口并加测试") is None
    assert calls["n"] == 0


def test_route_controller_frontend_falls_back_to_claude_before_codex() -> None:
    # Gemini is the best fit for frontend work but its CLI is missing; the chain
    # must land on claude (not the codex default) per the requested fallback order.
    config = _routing_config(gemini="definitely-not-a-real-cli-xyz")
    assert web_api._route_controller(config, "做一个前端页面，调整下样式和配色") == "claude"


def test_codex_command_enables_workspace_write() -> None:
    config = SimpleNamespace(
        current_controller="codex",
        providers={"codex": SimpleNamespace(cli="codex exec --model gpt-5.5")},
    )
    cmd = _build_provider_command(config, "create Hello.md")
    assert "--sandbox" in cmd
    assert "workspace-write" in cmd
    assert cmd[-1] == "create Hello.md"


def test_claude_command_streams_json() -> None:
    config = SimpleNamespace(current_controller="claude", providers={"claude": SimpleNamespace(cli="claude")})
    cmd = _build_provider_command(config, "hi", "claude")
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--verbose" in cmd
    assert "--include-partial-messages" in cmd
    assert cmd[-1] == "hi"


def test_extract_text_parses_claude_stream_json() -> None:
    stream = "\n".join([
        '{"type":"system","subtype":"init"}',
        '{"type":"system","subtype":"thinking_tokens","estimated_tokens":50}',
        '{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"hmm"},{"type":"text","text":"二分查找是一种…"}]}}',
        '{"type":"result","subtype":"success","is_error":false,"result":"二分查找是一种对有序数组的查找算法。"}',
    ])
    assert web_api._extract_codex_text(stream) == "二分查找是一种对有序数组的查找算法。"


def test_extract_text_accumulates_claude_partial_deltas() -> None:
    # Mid-stream (only partial deltas, no complete message yet) the text accumulates
    # so the UI can show progress; thinking deltas are ignored.
    stream = "\n".join([
        '{"type":"stream_event","event":{"delta":{"type":"thinking_delta","thinking":"hmm"}}}',
        '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"你好"}}}',
        '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"，世界"}}}',
    ])
    assert web_api._extract_codex_text(stream) == "你好，世界"
    # Once the complete result lands it takes over from the accumulated partials.
    full = stream + '\n{"type":"result","subtype":"success","is_error":false,"result":"你好，世界！完整。"}'
    assert web_api._extract_codex_text(full) == "你好，世界！完整。"


def test_extract_text_ignores_claude_error_result() -> None:
    stream = "\n".join([
        '{"type":"assistant","message":{"content":[{"type":"text","text":"部分答案"}]}}',
        '{"type":"result","subtype":"error","is_error":true,"result":"boom"}',
    ])
    # An errored result must not override the assistant text we already streamed.
    assert web_api._extract_codex_text(stream) == "部分答案"


def test_run_provider_reply_returns_extracted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_stream(cmd: object, **kwargs: object) -> ProviderRun:
        return ProviderRun(returncode=0, stdout='{"type":"assistant_message","text":"ok"}', stderr="")

    monkeypatch.setattr(web_api, "_stream_provider_output", fake_stream)
    config = SimpleNamespace(current_controller="gemini", providers={"gemini": SimpleNamespace(cli="echo")})
    assert _run_provider_reply(config, [], "hi") == "ok"


def test_run_provider_reply_uses_provider_idle_and_max_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    # A long task must NOT be cut off at a fixed wall-clock limit; explicit
    # idle/max fields pass straight through.
    captured: dict[str, object] = {}

    def fake_stream(cmd: object, **kwargs: object) -> ProviderRun:
        captured.update(kwargs)
        return ProviderRun(returncode=0, stdout='{"type":"assistant_message","text":"ok"}', stderr="")

    monkeypatch.setattr(web_api, "_stream_provider_output", fake_stream)
    config = SimpleNamespace(
        current_controller="codex",
        providers={"codex": SimpleNamespace(cli="echo", idle_timeout=90, max_timeout=600)},
    )
    assert _run_provider_reply(config, [], "hi") == "ok"
    assert captured["idle_timeout"] == 90
    assert captured["max_timeout"] == 600


def test_legacy_timeout_never_becomes_ceiling_or_shrinks_idle() -> None:
    # With default idle disabled, a short legacy `timeout` must not cap long tasks.
    idle, hard = web_api._provider_timeouts(SimpleNamespace(timeout=120))
    assert hard == web_api.PROVIDER_MAX_TIMEOUT
    assert idle == 0
    assert hard >= idle
    # Explicit idle_timeout still works for deployments that want hang detection.
    idle2, _ = web_api._provider_timeouts(SimpleNamespace(timeout=120, idle_timeout=600))
    assert idle2 == 600


def test_run_provider_reply_keeps_partial_output_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_stream(cmd: object, **kwargs: object) -> ProviderRun:
        return ProviderRun(
            returncode=-1,
            stdout='{"type":"assistant_message","text":"已生成一半"}',
            stderr="",
            timed_out=True,
            timeout_reason="180 秒无输出",
        )

    monkeypatch.setattr(web_api, "_stream_provider_output", fake_stream)
    config = SimpleNamespace(current_controller="codex", providers={"codex": SimpleNamespace(cli="echo")})
    reply = _run_provider_reply(config, [], "做一个页面")
    # Partial work is preserved (with a note) rather than discarded as an error.
    assert "已生成一半" in reply
    assert "停止" in reply


def test_run_provider_reply_streams_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_stream(cmd: object, *, on_chunk=None, **kwargs: object) -> ProviderRun:
        if on_chunk:
            on_chunk('{"type":"assistant_message","text":"hello"}\n')
            on_chunk('{"type":"assistant_message","text":"hello world"}\n')
        return ProviderRun(returncode=0, stdout='{"type":"assistant_message","text":"hello world"}', stderr="")

    monkeypatch.setattr(web_api, "_stream_provider_output", fake_stream)
    deltas: list[str] = []
    config = SimpleNamespace(current_controller="codex", providers={"codex": SimpleNamespace(cli="echo")})
    reply = _run_provider_reply(config, [], "hi", on_delta=deltas.append)
    assert reply == "hello world"
    assert "".join(deltas) == "hello world"


def test_run_provider_reply_runs_in_selected_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "mycode"
    workspace.mkdir()
    captured: dict[str, object] = {}

    def fake_stream(cmd: object, **kwargs: object) -> ProviderRun:
        captured["cwd"] = kwargs.get("cwd")
        return ProviderRun(returncode=0, stdout='{"type":"assistant_message","text":"done"}', stderr="")

    monkeypatch.setattr(web_api, "_stream_provider_output", fake_stream)
    config = SimpleNamespace(current_controller="codex", providers={"codex": SimpleNamespace(cli="echo")})
    reply = _run_provider_reply(config, [], "hi", cwd=str(workspace))
    assert captured["cwd"] == str(workspace)
    assert reply == "done"


def test_stream_provider_output_kills_process_after_idle(tmp_path: Path) -> None:
    # Prints one line (arming the idle gate), then goes silent far longer than the
    # idle window → watchdog terminates it but still returns the early output.
    script = "import time, sys; print('hello', flush=True); time.sleep(30)"
    chunks: list[str] = []
    result = _stream_provider_output(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=dict(os.environ),
        idle_timeout=1.0,
        max_timeout=30.0,
        on_chunk=chunks.append,
    )
    assert result.timed_out is True
    assert "中断" in result.timeout_reason
    assert any("hello" in chunk for chunk in chunks)


def test_stream_provider_output_does_not_kill_silent_thinking(tmp_path: Path) -> None:
    # A CLI that thinks silently (no output) before exiting must NOT be killed by the
    # idle timer — the idle gate only arms after the first output byte.
    script = "import time; time.sleep(2)"
    result = _stream_provider_output(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=dict(os.environ),
        idle_timeout=0.4,
        max_timeout=30.0,
    )
    assert result.timed_out is False
    assert result.returncode == 0


def test_stream_provider_output_completes_normally(tmp_path: Path) -> None:
    result = _stream_provider_output(
        [sys.executable, "-c", "print('done')"],
        cwd=str(tmp_path),
        env=dict(os.environ),
        idle_timeout=5.0,
        max_timeout=10.0,
    )
    assert result.timed_out is False
    assert result.returncode == 0
    assert "done" in result.stdout


def test_parse_unified_diff_counts_and_types() -> None:
    sample = (
        "diff --git a/foo.py b/foo.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"
        "-old = 1\n"
        "+new = 2\n"
        "+added = 3\n"
        " print(old)\n"
    )
    files = _parse_unified_diff(sample)
    assert len(files) == 1
    assert files[0]["path"] == "foo.py"
    assert files[0]["add"] == 2
    assert files[0]["del"] == 1
    line_types = [line["type"] for line in files[0]["hunks"][0]["lines"]]
    assert line_types == ["context", "del", "add", "add", "context"]


def test_delete_run_removes_projection_and_persisted_state(tmp_path: Path) -> None:
    state = WebApiState(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    run = state.create_run(workspace, "build the ui")
    assert run.id in state.runs

    assert state.delete_run(run.id) is True
    assert run.id not in state.runs
    assert state.delete_run(run.id) is False

    persisted = state.state_path.read_text(encoding="utf-8")
    assert run.id not in persisted


@pytest.fixture()
def running_server(tmp_path: Path) -> Iterator[tuple[ThreadingHTTPServer, WebApiState]]:
    state = WebApiState(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), WebApiHandler)
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_delete_removes_run(running_server: tuple[ThreadingHTTPServer, WebApiState], tmp_path: Path) -> None:
    server, state = running_server
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run = state.create_run(workspace, "delete me over http")
    host, port = server.server_address[0], server.server_address[1]

    with closing(http.client.HTTPConnection(host, port, timeout=5)) as conn:
        # CORS preflight must advertise DELETE so the browser allows the request.
        conn.request("OPTIONS", f"/api/runs/{run.id}")
        preflight = conn.getresponse()
        preflight.read()
        assert "DELETE" in (preflight.getheader("Access-Control-Allow-Methods") or "")

        conn.request("DELETE", f"/api/runs/{run.id}")
        response = conn.getresponse()
        response.read()
        assert response.status == 200

    assert run.id not in state.runs
    assert run.id not in state.state_path.read_text(encoding="utf-8")
