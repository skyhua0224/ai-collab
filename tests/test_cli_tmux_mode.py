"""Tests for ai-collab tmux launch behavior."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import ai_collab.cli as cli
from click.testing import CliRunner
from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationResult
from ai_collab.core.run_state import RunStateStore
from rich.console import Console


def _sample_result() -> SimpleNamespace:
    return SimpleNamespace(
        execution_mode="multi-agent",
        orchestration_plan=[
            {"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.4"},
            {"agent": "gemini", "role": "frontend-build", "selected_model": "gemini-cli-auto"},
        ],
    )


def test_tmux_launch_defaults_to_controller_only(monkeypatch) -> None:
    """Default tmux mode should start only controller pane (no prewarmed subagents)."""
    result = _sample_result()
    called = {"spawn": 0, "attach": 0}

    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _result: True)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%1")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "_start_handoff_watcher", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "spawn_subagent_pane", lambda **_kwargs: called.__setitem__("spawn", called["spawn"] + 1))
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: called.__setitem__("attach", called["attach"] + 1))

    ok = cli._launch_tmux_orchestration(
        task="build tiny todo",
        controller="codex",
        result=result,
        prewarm_subagents=False,
    )

    assert ok is True
    assert called["spawn"] == 0
    assert called["attach"] == 1


def test_tmux_launch_can_prewarm_subagents(monkeypatch) -> None:
    """Prewarm mode should create panes for non-controller agents."""
    result = _sample_result()
    called = {"spawn": 0}

    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _result: True)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%1")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "_start_handoff_watcher", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "spawn_subagent_pane",
        lambda **_kwargs: (called.__setitem__("spawn", called["spawn"] + 1), "%2")[1],
    )
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    ok = cli._launch_tmux_orchestration(
        task="build tiny todo",
        controller="codex",
        result=result,
        prewarm_subagents=True,
    )

    assert ok is True
    assert called["spawn"] == 1


def test_tmux_launch_injects_controller_prompt_text(monkeypatch) -> None:
    """Controller pane should receive prompt text after controller UI starts."""
    result = _sample_result()
    sent_text: list[str] = []

    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _result: True)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%1")
    monkeypatch.setattr(cli, "_start_handoff_watcher", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "_inject_prompt_to_pane",
        lambda **kwargs: (sent_text.append(str(kwargs.get("text", ""))), True)[1],
    )
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    ok = cli._launch_tmux_orchestration(
        task="build tiny todo",
        controller="codex",
        result=result,
        prewarm_subagents=False,
    )

    assert ok is True
    assert sent_text
    assert ".ai-collab/briefings/" in sent_text[0]


def test_tmux_launch_prints_log_directory(monkeypatch, tmp_path) -> None:
    """tmux launch should print where pane logs are written."""
    result = _sample_result()
    printed: list[str] = []

    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _result: True)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%1")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "_start_handoff_watcher", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "pane_logs_dir", lambda **_kwargs: tmp_path / "pane-logs")
    monkeypatch.setattr(
        cli.console,
        "print",
        lambda *args, **_kwargs: printed.append(" ".join(str(item) for item in args)),
    )

    ok = cli._launch_tmux_orchestration(
        task="build tiny todo",
        controller="codex",
        result=result,
        prewarm_subagents=False,
    )

    assert ok is True
    assert any("Pane logs:" in line for line in printed)
    assert any(str(tmp_path / "pane-logs") in line for line in printed)


def test_tmux_inline_mode_uses_current_session_without_attach(monkeypatch, tmp_path) -> None:
    """Inline mode should create pane in current tmux and skip attach-session."""
    result = _sample_result()
    called = {"attach": 0}

    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _result: True)
    monkeypatch.setattr(
        cli,
        "create_inline_controller_workspace",
        lambda **_kwargs: ("dev-session", "%9"),
    )
    monkeypatch.setattr(
        cli,
        "create_controller_workspace",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not create new tmux session")),
    )
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "_start_handoff_watcher", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "pane_logs_dir", lambda **_kwargs: tmp_path / "pane-logs")
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: called.__setitem__("attach", called["attach"] + 1))

    ok = cli._launch_tmux_orchestration(
        task="build tiny todo",
        controller="codex",
        result=result,
        prewarm_subagents=False,
        tmux_target="inline",
    )

    assert ok is True
    assert called["attach"] == 0


def test_resolve_tmux_session_name_preserves_existing_session(monkeypatch) -> None:
    """When preferred session exists, launcher should pick a new session name."""
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda name: name == "ai-collab-live")

    resolved = cli._resolve_tmux_session_name("ai-collab-live")

    assert resolved != "ai-collab-live"
    assert resolved.startswith("ai-collab-live-")


def test_build_subagent_prompt_enforces_completion_protocol() -> None:
    """Sub-agent prompt should forbid asking user and require handoff markers."""
    prompt = cli._build_subagent_prompt(
        task="实现极小待办",
        steps=[{"id": "S4", "role": "frontend-build", "selected_model": "gemini-3.1-pro-preview", "reason": "ui"}],
        lang="zh-CN",
        controller="codex",
        run_id="run-test-001",
        step_tickets=[{"step_id": "S4", "nonce": "abc123"}],
    )

    assert "不要问用户" in prompt
    assert "禁止先运行 `--help` / `-h` / `--version`" in prompt
    assert "NEED_ELEVATION: <command> | reason=<error>" in prompt
    assert "AI_COLLAB_EVENT" in prompt
    assert "run-test-001" in prompt
    assert "nonce=abc123" in prompt
    assert "STEP_DONE: <step_id>" in prompt
    assert "HANDOFF_TO: codex" in prompt
    assert "=== SUBAGENT_COMPLETE ===" in prompt


def test_build_controller_execution_prompt_forbids_probe_commands() -> None:
    """Controller execution prompt should forbid preflight probes and require elevation marker."""
    prompt = cli._build_controller_execution_prompt(
        plan={"controller": "codex", "steps": [{"id": "S1", "owner": "codex"}]},
        lang="zh-CN",
    )

    assert "禁止运行 `--help` / `-h` / `--version`" in prompt
    assert "禁止读取 `cli.py` / `SKILL.md` / 搜索源码来确认参数" in prompt
    assert "若用户要求“真实子 Agent”，禁止使用 `--agent-cmd` shell 模拟" in prompt
    assert "固定命令合同" in prompt
    assert "ai-collab tmux-watch --pane-id <pane_id> --timeout-seconds <n> --json-output" in prompt
    assert "NEED_ELEVATION: <command> | reason=<error>" in prompt


def test_build_controller_planning_request_forbids_probe_commands() -> None:
    """Controller planning request should include no-probe and elevation constraints."""
    config = Config(
        providers={},
        quality_gate={"enabled": True, "threshold": 75},
    )
    result = SimpleNamespace(
        available_agents=[
            {
                "agent": "codex",
                "selected_model": "gpt-5.4",
                "model_profile": "high",
                "strengths": "implementation",
            }
        ]
    )

    prompt = cli._build_controller_planning_request(
        task="实现极小待办",
        controller="codex",
        result=result,
        config=config,
        lang="zh-CN",
    )

    assert "禁止先运行 `--help` / `-h` / `--version`" in prompt
    assert "禁止读取 `cli.py` / `SKILL.md` / 搜索源码来确认参数" in prompt
    assert "若要求真实子 Agent 测试，禁止使用 `--agent-cmd` shell 模拟" in prompt
    assert "ai-collab 命令合同" in prompt
    assert "监控与故障处理策略（必须执行）" in prompt
    assert "error/model_capacity_exhausted" in prompt
    assert "NEED_ELEVATION: <command> | reason=<error>" in prompt


def test_build_controller_planning_request_includes_role_boundary_policy() -> None:
    config = Config.create_default()
    result = SimpleNamespace(
        available_agents=[
            {
                "agent": "codex",
                "selected_model": "gpt-5.4",
                "model_profile": "high",
                "strengths": "implementation, testing, debugging",
            },
            {
                "agent": "claude",
                "selected_model": "claude-sonnet-4-6",
                "model_profile": "default",
                "strengths": "reasoning, code-review, testing",
            },
            {
                "agent": "gemini",
                "selected_model": "gemini-3.1-pro-preview",
                "model_profile": "powerful",
                "strengths": "research, architecture, ecosystem",
            },
        ]
    )

    prompt = cli._build_controller_planning_request(
        task="制作一个贪吃蛇小游戏",
        controller="codex",
        result=result,
        config=config,
        lang="zh-CN",
    )

    assert "当前协作偏好（优先遵守）" in prompt
    assert "方案选项 / 技术骨架 / 架构取舍：gemini" in prompt
    assert "主实现 / 跨文件编码 / 问题修复：codex" in prompt
    assert "验收 / 回归测试 / 质量审查 / 补充修改：claude" in prompt
    assert "不要因为当前 controller 是 codex 就默认把所有编码步骤都交给 codex" in prompt


def test_build_controller_planning_request_includes_v2_stage_metadata() -> None:
    config = Config.create_default()
    result = SimpleNamespace(
        available_agents=[
            {
                "agent": "codex",
                "selected_model": "gpt-5.4",
                "model_profile": "high",
                "strengths": "implementation, testing, debugging",
            },
            {
                "agent": "claude",
                "selected_model": "claude-sonnet-4-6",
                "model_profile": "default",
                "strengths": "reasoning, code-review, testing",
            },
            {
                "agent": "gemini",
                "selected_model": "gemini-3.1-pro-preview",
                "model_profile": "powerful",
                "strengths": "research, architecture, ecosystem",
            },
        ]
    )

    prompt = cli._build_controller_planning_request(
        task="制作一个贪吃蛇小游戏",
        controller="codex",
        result=result,
        config=config,
        lang="zh-CN",
    )

    assert '"workflow_engine": "v2"' in prompt
    assert '"session_preset": "auto"' in prompt
    assert '"workflow_blueprint": "delivery-loop"' in prompt
    assert '"responsibility_stage": "collect"' in prompt
    assert '"artifact_type": "evidence-pack"' in prompt
    assert '"boundary": "只收集现状，不直接改代码或重设方案"' in prompt
    assert '"timebox_minutes": 15' in prompt
    assert "responsibility_stage 必须使用阶段职责，而不是直接写 Agent 名称" in prompt


def test_build_controller_execution_prompt_mentions_v2_stage_boundaries() -> None:
    prompt = cli._build_controller_execution_prompt(
        plan={
            "plan_version": "1.0",
            "workflow_engine": "v2",
            "session_preset": "auto",
            "workflow_blueprint": "delivery-loop",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "lead"}],
            "steps": [
                {
                    "id": "S1",
                    "owner": "codex",
                    "goal": "收集当前项目现状",
                    "input": "用户任务",
                    "output": "evidence-pack",
                    "done_when": "形成现状证据包",
                    "eta_minutes": 15,
                    "responsibility_stage": "collect",
                    "artifact_type": "evidence-pack",
                    "boundary": "只收集现状，不直接改代码或重设方案",
                    "timebox_minutes": 15,
                }
            ],
            "approval_question": "是否按此计划开始制作贪吃蛇小游戏？",
        },
        lang="zh-CN",
    )

    assert "如果 step 含有 `responsibility_stage` / `artifact_type` / `boundary` / `timebox_minutes`，必须按这些字段理解步骤边界" in prompt
    assert "不得在 collect 阶段直接进入大规模实现" in prompt
    assert "不得在 validate 阶段擅自重设方案" in prompt


def test_handoff_forwards_startup_pattern(monkeypatch, tmp_path) -> None:
    """CLI handoff should forward --startup-pattern to launcher script."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script = scripts_dir / "tmux_agent_handoff.py"
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(cli, "_resolve_orchestrator_skill_source", lambda: tmp_path)

    class _Result:
        returncode = 0

    def _fake_run(cmd, check=False):  # noqa: ARG001
        captured["cmd"] = list(cmd)
        return _Result()

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    try:
        cli.handoff.callback(
            agent="gemini",
            agent_cmd=None,
            model=None,
            session="controller-test",
            window_name=None,
            tmux_layout="split",
            split_policy="controller-bottom",
            split_direction="vertical",
            split_percent=35,
            split_target_pane="%1",
            controller_pane="%1",
            controller_height_percent=50,
            shell=None,
            repo_root=str(tmp_path),
            prompt_file=None,
            prompt="hello",
            no_prompt=False,
            prompt_mode="auto",
            completion_action="keep",
            completion_timeout=120.0,
            completion_notify_mode="status",
            ask_launch_options=False,
            wait_shell_timeout=20.0,
            wait_agent_timeout=60.0,
            capture_lines=120,
            shell_settle_delay=2.0,
            shell_idle_quiet_for=1.5,
            shell_probe_timeout=12.0,
            agent_idle_quiet_for=1.5,
            agent_min_runtime=2.0,
            startup_pattern="Type your message|/model",
            enter_delay=0.6,
            verbose=False,
        )
        raise AssertionError("handoff should exit via SystemExit")
    except SystemExit as exc:
        assert exc.code == 0

    cmd = captured.get("cmd", [])
    assert "--startup-pattern" in cmd
    idx = cmd.index("--startup-pattern")
    assert cmd[idx + 1] == "Type your message|/model"


def test_handoff_updates_run_state_with_spawned_pane(monkeypatch, tmp_path) -> None:
    """Successful handoff in controller context should persist subagent spawn state."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script = scripts_dir / "tmux_agent_handoff.py"
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_resolve_orchestrator_skill_source", lambda: tmp_path)

    store = RunStateStore.create(
        cwd=tmp_path,
        session="sess-a",
        controller_agent="codex",
        controller_pane="%1",
    )
    before_snapshot = {
        "session": "sess-a",
        "available": True,
        "windows": [
            {
                "index": "1",
                "name": "ai-collab",
                "active": "1",
                "panes": [{"pane_id": "%1"}],
            }
        ],
    }
    after_snapshot = {
        "session": "sess-a",
        "available": True,
        "windows": [
            {
                "index": "1",
                "name": "ai-collab",
                "active": "1",
                "panes": [{"pane_id": "%1"}, {"pane_id": "%2"}],
            }
        ],
    }
    store.update_tmux_layout_snapshot(session="sess-a", snapshot=before_snapshot, reason="seed")

    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda preferred=None: "sess-a")
    monkeypatch.setattr(cli, "_find_active_run_store_for_session", lambda **_kwargs: store)
    monkeypatch.setattr(
        cli,
        "capture_pane_text",
        lambda **_kwargs: "S2_START\nSTEP_DONE: S2\n",
    )
    monkeypatch.setattr(
        cli,
        "_resolve_runtime_session_id_for_agent",
        lambda **_kwargs: "runtime-subagent-001",
    )

    def _fake_record_tmux_layout_snapshot(*, run_store, session, reason):  # noqa: ARG001
        run_store.update_tmux_layout_snapshot(
            session="sess-a",
            snapshot=after_snapshot,
            reason="controller_handoff_command",
        )

    monkeypatch.setattr(cli, "_record_tmux_layout_snapshot", _fake_record_tmux_layout_snapshot)

    class _Result:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, check=False: _Result())  # noqa: ARG005
    monkeypatch.setenv("AI_COLLAB_ACTIVE", "1")

    try:
        cli.handoff.callback(
            agent="codex",
            agent_cmd=None,
            model=None,
            session="sess-a",
            window_name=None,
            tmux_layout="split",
            split_policy="controller-bottom",
            split_direction="vertical",
            split_percent=35,
            split_target_pane="%1",
            controller_pane="%1",
            controller_height_percent=50,
            shell=None,
            repo_root=str(tmp_path),
            prompt_file=None,
            prompt="hello",
            no_prompt=False,
            prompt_mode="auto",
            completion_action="keep",
            completion_timeout=120.0,
            completion_notify_mode="status",
            ask_launch_options=False,
            wait_shell_timeout=20.0,
            wait_agent_timeout=60.0,
            capture_lines=120,
            shell_settle_delay=2.0,
            shell_idle_quiet_for=1.5,
            shell_probe_timeout=12.0,
            agent_idle_quiet_for=1.5,
            agent_min_runtime=2.0,
            startup_pattern=None,
            enter_delay=0.6,
            verbose=False,
        )
        raise AssertionError("handoff should exit via SystemExit")
    except SystemExit as exc:
        assert exc.code == 0

    state = store.snapshot()
    assert state["phase"] == "subagent_spawned"
    assert state["phase_detail"] == "codex:%2"
    assert state["agents"]["codex"]["status"] == "running"
    assert state["agents"]["codex"]["pane_id"] == "%2"
    assert state["agents"]["codex"]["runtime_session_id"] == "runtime-subagent-001"
    assert state["steps"]["S2"]["status"] == "done"
    events = store.paths.events_file.read_text(encoding="utf-8")
    assert '"type": "subagent_spawned"' in events
    assert '"type": "step_done"' in events


def test_tmux_open_builds_short_wrapper_command(monkeypatch, tmp_path) -> None:
    """tmux-open should invoke handoff with split/controller-bottom defaults."""
    captured: dict[str, list[str]] = {}

    class _Result:
        returncode = 0

    def _fake_run(cmd, check=False):  # noqa: ARG001
        captured["cmd"] = list(cmd)
        return _Result()

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    try:
        cli.tmux_open.callback(
            agent="gemini",
            agent_cmd=None,
            model="gemini-3.1-pro-preview",
            session="0",
            layout="split",
            controller_pane="%1",
            window_name="x",
            repo_root=str(tmp_path),
            prompt="hello",
            prompt_file=None,
            completion="ask",
            notify="input",
        )
        raise AssertionError("tmux-open should exit via SystemExit")
    except SystemExit as exc:
        assert exc.code == 0

    cmd = captured.get("cmd", [])
    assert cmd[:4] == [cli.sys.executable, "-m", "ai_collab.cli", "handoff"]
    assert "--split-policy" in cmd
    assert "controller-bottom" in cmd
    assert "--no-ask-launch-options" in cmd
    assert "--completion-notify-mode" in cmd


def test_tmux_close_test_generates_prompt_and_calls_tmux_open(monkeypatch, tmp_path) -> None:
    """tmux-close-test should materialize a prompt file then invoke tmux-open wrapper."""
    captured: dict[str, list[str]] = {}
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("x", encoding="utf-8")

    class _Result:
        returncode = 0

    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: prompt_file)

    def _fake_run(cmd, check=False):  # noqa: ARG001
        captured["cmd"] = list(cmd)
        return _Result()

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    try:
        cli.tmux_close_test.callback(
            controller="codex",
            subagent="codex",
            duration=90,
            watch1=60,
            watch2=45,
            session="0",
            window_name="controller-close-test",
            repo_root=str(tmp_path),
        )
        raise AssertionError("tmux-close-test should exit via SystemExit")
    except SystemExit as exc:
        assert exc.code == 0

    cmd = captured.get("cmd", [])
    assert cmd[:4] == [cli.sys.executable, "-m", "ai_collab.cli", "tmux-open"]
    assert "--prompt-file" in cmd
    assert str(prompt_file) in cmd
    assert "--completion" in cmd
    idx = cmd.index("--completion")
    assert cmd[idx + 1] == "none"


def test_help_tmux_watch_shows_short_and_long_options() -> None:
    """tmux-watch help should present short/long option pairs in standard click format."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["tmux-watch", "--help"])
    assert result.exit_code == 0
    assert "-p, --pane-id" in result.output
    assert "-t, --timeout-seconds" in result.output
    assert "-i, --poll-seconds" in result.output
    assert "-n, --capture-lines" in result.output
    assert "-j, --json-output" in result.output


def test_help_handoff_shows_short_and_long_options() -> None:
    """handoff help should present short/long option pairs in standard click format."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["handoff", "--help"])
    assert result.exit_code == 0
    assert "-a, --agent" in result.output
    assert "-x, --agent-cmd" in result.output
    assert "-s, --session" in result.output
    assert "-l, --tmux-layout" in result.output
    assert "-c, --controller-pane" in result.output
    assert "-r, --repo-root" in result.output
    assert "-k, --completion-action" in result.output


def test_help_monitor_shows_short_and_long_options() -> None:
    """monitor help should present short/long option pairs in standard click format."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["monitor", "--help"])
    assert result.exit_code == 0
    assert "-s, --session" in result.output
    assert "-w, --cwd" in result.output
    assert "-c, --controller" in result.output
    assert "-l, --layout" in result.output
    assert "-t, --task-hint" in result.output


def test_help_init_shows_short_pair_flags() -> None:
    """init help should show short pair flags for boolean options."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["init", "--help"])
    assert result.exit_code == 0
    assert "-i, --interactive / -I, --non-interactive" in result.output
    assert "-a, --auto-install-deps / -A, --no-auto-install-deps" in result.output


def test_help_relay_smoke_shows_short_and_long_options() -> None:
    """relay-smoke help should show short/long options including pair flags."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["relay-smoke", "--help"])
    assert result.exit_code == 0
    assert "-a, --agent" in result.output
    assert "-c, --controller-agent" in result.output
    assert "-t, --timeout-seconds" in result.output
    assert "-k, --keep-pane / -K, --auto-close-pane" in result.output


def test_help_resume_group_and_list_show_short_and_long_options() -> None:
    """resume group/list help should expose standard short+long flags."""
    runner = CliRunner()
    group_help = runner.invoke(cli.main, ["resume", "--help"])
    list_help = runner.invoke(cli.main, ["resume", "list", "--help"])
    assert group_help.exit_code == 0
    assert list_help.exit_code == 0
    assert "recover" in group_help.output
    assert "prune" in group_help.output
    assert "-w, --cwd" in list_help.output
    assert "-n, --limit" in list_help.output
    assert "-j, --json-output" in list_help.output


def test_resume_prune_keeps_only_selected_session(tmp_path) -> None:
    """resume prune should delete runs outside selected session."""
    keep_store = RunStateStore.create(
        cwd=tmp_path,
        session="keep-session",
        controller_agent="codex",
        controller_pane="%1",
    )
    drop_store_a = RunStateStore.create(
        cwd=tmp_path,
        session="drop-session",
        controller_agent="codex",
        controller_pane="%2",
    )
    drop_store_b = RunStateStore.create(
        cwd=tmp_path,
        session="drop-session",
        controller_agent="gemini",
        controller_pane="%3",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        [
            "resume",
            "prune",
            "-w",
            str(tmp_path),
            "--keep-session",
            "keep-session",
            "--yes",
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    assert keep_store.run_id in result.output
    assert drop_store_a.run_id in result.output
    assert drop_store_b.run_id in result.output
    payload = json.loads(cli.ANSI_ESCAPE_RE.sub("", result.output))
    assert payload["deleted_count"] == 2

    remaining = RunStateStore.list_runs(cwd=tmp_path, limit=20)
    assert len(remaining) == 1
    assert remaining[0]["run_id"] == keep_store.run_id


def test_collect_runner_inputs_accepts_prompt_alias() -> None:
    """Runner input collector should accept --prompt alias and mode/provider aliases."""
    args = SimpleNamespace(
        task=[],
        prompt="build api contract",
        provider="claude",
        execution_mode="tmux",
    )
    provider, mode, task = cli._collect_runner_inputs(
        args=args,
        provider_prefix=None,
        default_provider="codex",
        providers=["claude", "codex", "gemini"],
        lang="en-US",
        decision_ui=None,
    )
    assert provider == "claude"
    assert mode == "tmux"
    assert task == "build api contract"


def test_collect_runner_inputs_rejects_prompt_and_positional_mix() -> None:
    """Runner input collector should reject positional task mixed with --prompt."""
    args = SimpleNamespace(
        task=["positional", "task"],
        prompt="inline prompt",
        provider="codex",
        execution_mode="auto",
    )
    try:
        cli._collect_runner_inputs(
            args=args,
            provider_prefix=None,
            default_provider="codex",
            providers=["codex", "gemini", "claude"],
            lang="en-US",
            decision_ui=None,
        )
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "Use either positional task or --prompt" in str(exc)


def test_resume_list_show_rename_roundtrip(tmp_path) -> None:
    """resume list/show/rename should read and update persisted run state."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.set_entry_prompt(text="Read and execute task file: /tmp/briefing.md")
    runner = CliRunner()

    listed = runner.invoke(cli.main, ["resume", "list", "-w", str(tmp_path), "-j"])
    assert listed.exit_code == 0
    assert store.run_id in listed.output
    assert "entry_prompt_preview" in listed.output
    assert "Read and execute task file" in listed.output

    renamed = runner.invoke(
        cli.main,
        ["resume", "rename", store.run_id, "nightly-checkpoint", "-w", str(tmp_path)],
    )
    assert renamed.exit_code == 0
    assert "nightly-checkpoint" in renamed.output

    shown = runner.invoke(cli.main, ["resume", "show", store.run_id, "-w", str(tmp_path), "-j"])
    assert shown.exit_code == 0
    assert "nightly-checkpoint" in shown.output
    assert store.run_id in shown.output


def test_resume_list_json_exposes_short_id_mode_and_pending_count(tmp_path) -> None:
    """resume list json should expose compact recovery fields."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.bind_agent(
        agent="gemini",
        pane_id="%2",
        step_tickets=[{"step_id": "S1", "nonce": "n1"}],
    )
    store.set_entry_prompt(text="Read and execute task file: /tmp/brief.md")
    store.set_label(label="phase1-alpha")
    store.set_mode(mode="tmux")

    runner = CliRunner()
    listed = runner.invoke(cli.main, ["resume", "list", "-w", str(tmp_path), "-j"])
    assert listed.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", listed.output)
    payload = json.loads(cleaned)
    assert payload
    assert payload[0]["short_id"] == store.run_id.split("-")[-1]
    assert payload[0]["mode"] == "tmux"
    assert payload[0]["workspace"] == str(tmp_path)
    assert payload[0]["pending_count"] == 1
    assert payload[0]["name"] == "phase1-alpha"


def test_resume_show_accepts_short_id_and_label_query(tmp_path) -> None:
    """resume show should accept short id or label as query."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.set_label(label="nightly-a")
    short_id = store.run_id.split("-")[-1]
    runner = CliRunner()

    by_short = runner.invoke(cli.main, ["resume", "show", short_id, "-w", str(tmp_path), "-j"])
    assert by_short.exit_code == 0
    assert store.run_id in by_short.output

    by_label = runner.invoke(cli.main, ["resume", "show", "nightly-a", "-w", str(tmp_path), "-j"])
    assert by_label.exit_code == 0
    assert store.run_id in by_label.output


def test_resume_show_syncs_controller_step_markers(monkeypatch, tmp_path) -> None:
    """resume show should sync STEP_* markers from live controller pane text."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    monkeypatch.setattr(
        cli,
        "capture_pane_text",
        lambda **_kwargs: "S3_START\nSTEP_DONE: S3\n",
    )
    runner = CliRunner()

    shown = runner.invoke(cli.main, ["resume", "show", store.run_id, "-w", str(tmp_path), "-j"])
    assert shown.exit_code == 0
    refreshed = RunStateStore.load(cwd=tmp_path, run_id=store.run_id)
    assert refreshed is not None
    snapshot = refreshed.snapshot()
    assert snapshot["steps"]["S3"]["status"] == "done"


def test_resume_list_syncs_controller_step_markers(monkeypatch, tmp_path) -> None:
    """resume list should opportunistically sync STEP_* markers for active runs."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    monkeypatch.setattr(
        cli,
        "capture_pane_text",
        lambda **_kwargs: "STEP_DONE: S3\n",
    )
    runner = CliRunner()

    listed = runner.invoke(cli.main, ["resume", "list", "-w", str(tmp_path), "-j"])
    assert listed.exit_code == 0
    refreshed = RunStateStore.load(cwd=tmp_path, run_id=store.run_id)
    assert refreshed is not None
    snapshot = refreshed.snapshot()
    assert snapshot["steps"]["S3"]["status"] == "done"


def test_resume_recover_accepts_short_id_query(monkeypatch, tmp_path) -> None:
    """resume recover should accept short id query."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="lost-session",
        controller_agent="codex",
        controller_pane="%1",
    )
    short_id = store.run_id.split("-")[-1]
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **_kwargs: ("codex", False, True),
    )
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", short_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    assert f'"run_id": "{store.run_id}"' in result.output


def test_resume_recover_recreates_session_and_rebinds(monkeypatch, tmp_path) -> None:
    """resume recover should recreate missing tmux session and update controller binding."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="lost-session",
        controller_agent="codex",
        controller_pane="%1",
    )
    attach_called = {"count": 0}

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **_kwargs: ("codex", False, True),
    )
    monkeypatch.setattr(
        cli,
        "_write_briefing_file",
        lambda **_kwargs: tmp_path / "briefing.txt",
    )
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(
        cli,
        "attach_session",
        lambda **_kwargs: attach_called.__setitem__("count", attach_called["count"] + 1),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    assert '"created_new_session": true' in result.output
    assert '"controller_pane": "%99"' in result.output
    assert attach_called["count"] == 0

    loaded = RunStateStore.load(cwd=tmp_path, run_id=store.run_id)
    assert loaded is not None
    state = loaded.snapshot()
    assert state["session"] == "lost-session"
    assert state["controller"]["pane_id"] == "%99"


def test_resume_recover_prefers_existing_pane_session(monkeypatch, tmp_path) -> None:
    """When pane still exists, recover should reuse pane session over stale saved session."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="0",
        controller_agent="codex",
        controller_pane="%9",
    )
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "dev-session")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "fallback-session")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda session: session == "dev-session")
    monkeypatch.setattr(cli, "_tmux_pane_exists_in_session", lambda **_kwargs: True)
    monkeypatch.setattr(
        cli,
        "create_controller_workspace",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not create new session")),
    )
    monkeypatch.setattr(
        cli,
        "_spawn_resume_controller_pane",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not spawn new pane")),
    )
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **_kwargs: ("", False, True),
    )
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", result.output)
    assert '"session": "dev-session"' in cleaned
    assert '"created_new_session": false' in cleaned
    assert '"created_new_pane": false' in cleaned
    assert '"launch_command": ""' in cleaned


def test_resume_recover_uses_runtime_session_resume_command(monkeypatch, tmp_path) -> None:
    """When pane/session must be recreated, recover should launch agent with runtime resume id."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="lost-session",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.set_controller_runtime_session_id(runtime_session_id="abc123")
    launched: dict[str, str] = {}

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **_kwargs: ("codex resume abc123", True, True),
    )
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **kwargs: launched.__setitem__("cmd", str(kwargs.get("text", ""))),
    )
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", result.output)
    assert '"created_new_session": true' in cleaned
    assert '"created_new_pane": true' in cleaned
    assert '"runtime_session_restored": true' in cleaned
    assert '"launch_command": "codex resume abc123"' in cleaned
    assert '"launch_ready": true' in cleaned


def test_resolve_runtime_session_id_for_agent_reads_latest_resume_from_log(monkeypatch, tmp_path) -> None:
    """Runtime id resolver should recover latest codex resume id from pane logs."""
    log_dir = tmp_path / ".ai-collab" / "logs" / "0"
    log_dir.mkdir(parents=True, exist_ok=True)
    pane_log = log_dir / "pane-0.log"
    pane_log.write_text(
        "old line\n"
        "To continue this session, run codex resume 11111111-1111-1111-1111-111111111111\n"
        "other output\n"
        "To continue this session, run codex resume 019cb3d8-30eb-73d0-9389-c96572a074aa\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "capture_pane_text",
        lambda **_kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "tmux")),
    )

    state = {
        "controller": {"agent": "codex", "pane_id": "%0", "runtime_session_id": ""},
        "agents": {},
        "tmux": {},
    }
    resolved = cli._resolve_runtime_session_id_for_agent(
        state=state,
        agent="codex",
        pane_id="%0",
        sessions=["0"],
        cwd=tmp_path,
    )

    assert resolved == "019cb3d8-30eb-73d0-9389-c96572a074aa"


def test_extract_resume_ids_for_agent_ignores_placeholder_words() -> None:
    """Resume id extraction should ignore guide text like 'codex resume session'."""
    text = (
        "guide: run codex resume session id\\n"
        "To continue this session, run codex resume 019cb3d8-30eb-73d0-9389-c96572a074aa\\n"
    )
    ids = cli._extract_resume_ids_for_agent(text=text, agent="codex")
    assert ids == ["019cb3d8-30eb-73d0-9389-c96572a074aa"]


def test_resume_recover_infers_controller_runtime_session_when_missing(monkeypatch, tmp_path) -> None:
    """resume recover should infer runtime id when state has empty controller runtime_session_id."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="lost-session",
        controller_agent="codex",
        controller_pane="%1",
    )
    launched: dict[str, str] = {}

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
    monkeypatch.setattr(
        cli,
        "_resolve_runtime_session_id_for_agent",
        lambda **_kwargs: "019cb3d8-30eb-73d0-9389-c96572a074aa",
    )
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **kwargs: (
            launched.__setitem__("runtime", str(kwargs.get("runtime_session_id", ""))),
            ("codex resume 019cb3d8-30eb-73d0-9389-c96572a074aa", True, True),
        )[1],
    )
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", result.output)
    assert launched.get("runtime") == "019cb3d8-30eb-73d0-9389-c96572a074aa"
    assert '"runtime_session_id": "019cb3d8-30eb-73d0-9389-c96572a074aa"' in cleaned
    assert '"launch_command": "codex resume 019cb3d8-30eb-73d0-9389-c96572a074aa"' in cleaned


def test_resume_recover_restores_subagent_runtime_session(monkeypatch, tmp_path) -> None:
    """resume recover should restore sub-agent pane with runtime session id when pane is missing."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="lost-session",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.bind_agent(
        agent="claude",
        pane_id="%2",
        step_tickets=[{"step_id": "S2", "nonce": "n2"}],
    )
    store.set_agent_runtime_session_id(agent="claude", runtime_session_id="sub-claude-xyz")
    sent: list[str] = []

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **kwargs: (
            ("claude --resume sub-claude-xyz", True, True)
            if str(kwargs.get("agent", "")).strip() == "claude"
            else ("codex", False, True)
        ),
    )
    monkeypatch.setattr(cli, "_tmux_pane_exists_in_session", lambda **_kwargs: False)
    monkeypatch.setattr(cli, "_spawn_resume_subagent_pane", lambda **_kwargs: "%100")
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **kwargs: sent.append(str(kwargs.get("text", ""))),
    )
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", result.output)
    assert '"restored_subagent_count": 1' in cleaned
    assert '"agent": "claude"' in cleaned
    assert '"runtime_session_restored": true' in cleaned
    assert '"launch_command": "claude --resume sub-claude-xyz"' in cleaned


def test_resume_recover_keeps_existing_subagent_pane_without_relaunch(monkeypatch, tmp_path) -> None:
    """resume recover should not relaunch sub-agent if pane exists and agent already running."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="dev-session",
        controller_agent="codex",
        controller_pane="%9",
    )
    store.bind_agent(
        agent="claude",
        pane_id="%2",
        step_tickets=[{"step_id": "S2", "nonce": "n2"}],
    )
    store.set_agent_runtime_session_id(agent="claude", runtime_session_id="sub-claude-xyz")
    sent: list[str] = []

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "dev-session")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "dev-session")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: True)
    monkeypatch.setattr(cli, "_tmux_pane_exists_in_session", lambda **_kwargs: True)
    monkeypatch.setattr(
        cli,
        "_spawn_resume_subagent_pane",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not spawn sub-agent pane")),
    )

    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **_kwargs: ("", False, True),
    )
    monkeypatch.setattr(cli, "send_pane_text", lambda **kwargs: sent.append(str(kwargs.get("text", ""))))
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(cli, "_inject_prompt_to_pane", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )
    assert result.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", result.output)
    assert '"restored_subagent_count": 1' in cleaned
    assert '"created_new_pane": false' in cleaned
    # Only dispatch prompt should be sent to controller in this case.
    assert all("resume sub-claude-xyz" not in text for text in sent)


def test_help_root_group_supports_short_help_and_version_flags() -> None:
    """Root click group help should expose standard short/long help and version flags."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["--help"])
    assert result.exit_code == 0
    assert "-h, --help" in result.output
    assert "-V, --version" in result.output


def test_runner_help_shows_short_and_long_options(capsys) -> None:
    """Runner help should include short aliases for high-frequency options."""
    try:
        cli.runner_main(argv=["--help"], prog_name="ai-collab")
        raise AssertionError("runner_main --help should exit via SystemExit")
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "--provider" in text and "-p" in text
    assert "--dry-run" in text and "-d" in text
    assert "--lang" in text and "-l" in text
    assert "--ui-mode" in text and "-u" in text
    assert "--execution-mode" in text and "-x" in text
    assert "--tmux-target" in text and "-t" in text
    assert "--auto-install-deps" in text and "-i" in text
    assert "--interactive-decisions" in text and "-I" in text
    assert "--allow-nested" in text and "-a" in text
    assert "--controller-first" in text and "-c" in text


def test_model_select_help_shows_short_and_long_options(monkeypatch, capsys) -> None:
    """Model select help should include short aliases for execution and UI options."""
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab model-select", "--help"])
    try:
        cli.model_select_main()
        raise AssertionError("model_select_main --help should exit via SystemExit")
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "--complexity" in text and "-c" in text
    assert "--output" in text and "-o" in text
    assert "--execute" in text and "-x" in text
    assert "--ui-mode" in text and "-u" in text
    assert "--auto-install-deps" in text and "-i" in text
    assert "--interactive-decisions" in text and "-d" in text


def test_project_main_routes_tmux_open_and_close_test_to_click_main(monkeypatch) -> None:
    """project_main should route tmux-open/tmux-close-test as admin commands."""
    calls: list[list[str]] = []

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        calls.append(list(args))

    monkeypatch.setattr(cli.main, "main", _fake_click_main)

    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "tmux-open", "--help"])
    cli.project_main()
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "tmux-close-test", "--help"])
    cli.project_main()

    assert calls[0][0] == "tmux-open"
    assert calls[1][0] == "tmux-close-test"


def test_project_main_routes_resume_to_click_main(monkeypatch) -> None:
    """project_main should route resume command to click main."""
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "resume", "list"])

    cli.project_main()

    assert captured["args"] == ["resume", "list"]


def test_project_main_rewrites_resume_shortcut_to_recover(monkeypatch) -> None:
    """project_main should support `ai-collab resume <run>` shortcut."""
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "resume", "5c23", "-w", "."])

    cli.project_main()

    assert captured["args"] == ["resume", "recover", "5c23", "-w", "."]


def test_project_main_keeps_resume_help_unmodified(monkeypatch) -> None:
    """project_main should not rewrite `resume --help` into recover shortcut."""
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "resume", "--help"])

    cli.project_main()

    assert captured["args"] == ["resume", "--help"]


def test_project_main_accepts_short_version_flag(monkeypatch) -> None:
    """project_main should accept -V and forward to click version flow."""
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "-V"])

    cli.project_main()

    assert captured["args"] == ["--version"]




def test_project_main_prompts_self_update_before_config_when_behind(monkeypatch) -> None:
    config = cli.Config.create_default()
    config.application["auto_check_updates"] = True
    calls: dict[str, object] = {"updated": False, "dispatched": False}

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(cli, "check_pypi_update", lambda **_: type("Result", (), {
        "status": "behind",
        "local_version": "0.1.5.dev0",
        "remote_version": "0.1.6",
    })())
    monkeypatch.setattr(cli.Confirm, "ask", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "run_self_update", lambda **_: calls.__setitem__("updated", True) or True)
    monkeypatch.setattr(cli.main, "main", lambda **kwargs: calls.__setitem__("dispatched", True))
    monkeypatch.setattr(cli, "runner_main", lambda *args, **kwargs: calls.__setitem__("dispatched", True))
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "config"])

    cli.project_main()

    assert calls["updated"] is True
    assert calls["dispatched"] is False


def test_project_main_skips_self_update_prompt_when_local_version_is_ahead(monkeypatch) -> None:
    config = cli.Config.create_default()
    config.application["auto_check_updates"] = True
    calls: dict[str, object] = {"updated": False, "args": None}

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(cli, "check_pypi_update", lambda **_: type("Result", (), {
        "status": "ahead",
        "local_version": "0.1.5.dev0",
        "remote_version": "0.1.4",
    })())
    monkeypatch.setattr(cli, "run_self_update", lambda **_: calls.__setitem__("updated", True) or True)
    monkeypatch.setattr(cli.main, "main", lambda **kwargs: calls.__setitem__("args", kwargs.get("args")))
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "config"])

    cli.project_main()

    assert calls["updated"] is False
    assert calls["args"] == ["config"]

def test_resolve_orchestrator_skill_source_uses_packaged_skill() -> None:
    """Init skill installer should resolve packaged orchestrator skill source."""
    source = cli._resolve_orchestrator_skill_source()

    assert source is not None
    assert source.name == "ai-collab-orchestrator"
    assert source.parent.name == "skills"
    assert (source / "SKILL.md").exists()


def test_resolve_prompt_injection_delay_defaults(monkeypatch) -> None:
    """Prompt injection delay should use agent defaults when env is not set."""
    monkeypatch.delenv("AI_COLLAB_PROMPT_INJECT_DELAY_SECONDS", raising=False)

    assert cli._resolve_prompt_injection_delay("codex") == 1.2
    assert cli._resolve_prompt_injection_delay("claude") == 2.0
    assert cli._resolve_prompt_injection_delay("gemini") == 2.0


def test_resolve_prompt_injection_delay_env_override(monkeypatch) -> None:
    """Prompt injection delay should accept env override when valid."""
    monkeypatch.setenv("AI_COLLAB_PROMPT_INJECT_DELAY_SECONDS", "3.5")
    assert cli._resolve_prompt_injection_delay("codex") == 3.5

    monkeypatch.setenv("AI_COLLAB_PROMPT_INJECT_DELAY_SECONDS", "invalid")
    assert cli._resolve_prompt_injection_delay("codex") == 1.2


def test_result_for_tmux_launch_prefers_controller_plan_multi_agent() -> None:
    """Approved controller multi-agent plan should enable tmux launch payload."""
    result = CollaborationResult(
        need_collaboration=True,
        execution_mode="single-agent",
        orchestration_plan=[],
        selected_agents=["codex"],
    )
    controller_plan = {
        "requires_multi_agent": True,
        "agents": [
            {"name": "codex", "model": "gpt-5.4"},
            {"name": "claude", "model": "claude-sonnet-4-6"},
        ],
        "steps": [
            {"id": "S1", "owner": "codex", "goal": "controller step"},
            {"id": "S2", "owner": "claude", "goal": "review step"},
        ],
    }

    launch_result = cli._result_for_tmux_launch(result, controller_plan)

    assert launch_result.execution_mode == "multi-agent"
    assert len(launch_result.orchestration_plan) == 2
    assert launch_result.selected_agents == ["codex", "claude"]


def test_resolve_agent_ready_timeout_defaults(monkeypatch) -> None:
    """Agent readiness timeout should use safer short defaults."""
    monkeypatch.delenv("AI_COLLAB_AGENT_READY_TIMEOUT_SECONDS", raising=False)

    assert cli._resolve_agent_ready_timeout("codex") == 15.0
    assert cli._resolve_agent_ready_timeout("claude") == 25.0
    assert cli._resolve_agent_ready_timeout("gemini") == 25.0


def test_wait_for_agent_ready_codex_auto_confirms_directory_trust(monkeypatch) -> None:
    """Codex readiness check should auto-confirm trust gate instead of blocking."""
    snapshots = iter(
        [
            "Do you trust the contents of this directory?\nPress enter to continue",
            "OpenAI Codex\nReady",
        ]
    )
    sent = {"count": 0}

    monkeypatch.setattr(
        cli,
        "capture_pane_text",
        lambda **_kwargs: next(snapshots, "OpenAI Codex\nReady"),
    )
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **_kwargs: sent.__setitem__("count", sent["count"] + 1),
    )

    ready = cli._wait_for_agent_ready(pane_id="%1", agent="codex", timeout_seconds=1.0)

    assert ready is True
    assert sent["count"] >= 1


def test_wait_for_agent_ready_claude_auto_confirms_directory_trust(monkeypatch) -> None:
    """Claude readiness check should auto-confirm trust gate before injection."""
    snapshots = iter(
        [
            "Security guide\nYes, I trust this folder\nEnter to confirm",
            "Claude Code\nready",
        ]
    )
    sent = {"count": 0}

    monkeypatch.setattr(
        cli,
        "capture_pane_text",
        lambda **_kwargs: next(snapshots, "Claude Code\nready"),
    )
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **_kwargs: sent.__setitem__("count", sent["count"] + 1),
    )

    ready = cli._wait_for_agent_ready(pane_id="%1", agent="claude", timeout_seconds=1.0)

    assert ready is True
    assert sent["count"] >= 1


def test_wait_for_agent_ready_does_not_accept_shell_output(monkeypatch) -> None:
    """Generic shell output should not be treated as agent-ready."""
    monkeypatch.setattr(cli, "capture_pane_text", lambda **_kwargs: "zsh prompt output")

    ready = cli._wait_for_agent_ready(pane_id="%1", agent="codex", timeout_seconds=0.1)

    assert ready is False


def test_inject_prompt_to_pane_returns_false_when_agent_not_ready(monkeypatch) -> None:
    """Prompt injection must not write into shell when readiness check fails."""
    monkeypatch.setattr(cli, "_wait_for_agent_ready", lambda **_kwargs: False)
    monkeypatch.setattr(
        cli,
        "paste_pane_text",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not paste when not ready")),
    )
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not send when not ready")),
    )

    ok = cli._inject_prompt_to_pane(pane_id="%1", text="hello", agent="codex")

    assert ok is False


def test_inject_prompt_to_pane_uses_literal_send_for_short_dispatch(monkeypatch) -> None:
    """Short dispatch prompts should be typed, not pasted, to avoid pasted-mode issues."""
    called = {"type": 0, "send": 0, "paste": 0}

    monkeypatch.setattr(cli, "_wait_for_agent_ready", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "wait_for_pane_quiet", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "_pane_contains_probe", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "type_pane_text", lambda **_kwargs: called.__setitem__("type", called["type"] + 1))
    monkeypatch.setattr(cli, "send_pane_text", lambda **_kwargs: called.__setitem__("send", called["send"] + 1))
    monkeypatch.setattr(cli, "paste_pane_text", lambda **_kwargs: called.__setitem__("paste", called["paste"] + 1))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)

    ok = cli._inject_prompt_to_pane(
        pane_id="%1",
        text="读取并执行文件:\n/tmp/briefing.txt\n完成后结束。",
        agent="codex",
    )

    assert ok is True
    assert called["type"] >= 1
    assert called["send"] >= 1
    assert called["paste"] == 0


def test_inject_prompt_to_pane_no_retry_for_codex_on_probe_miss(monkeypatch) -> None:
    """Codex prompt injection should not retry on probe miss to avoid double-send."""
    called = {"type": 0, "send": 0, "paste": 0}

    monkeypatch.setattr(cli, "_wait_for_agent_ready", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "wait_for_pane_quiet", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "_pane_contains_probe", lambda **_kwargs: False)
    monkeypatch.setattr(cli, "type_pane_text", lambda **_kwargs: called.__setitem__("type", called["type"] + 1))
    monkeypatch.setattr(cli, "send_pane_text", lambda **_kwargs: called.__setitem__("send", called["send"] + 1))
    monkeypatch.setattr(cli, "paste_pane_text", lambda **_kwargs: called.__setitem__("paste", called["paste"] + 1))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)

    ok = cli._inject_prompt_to_pane(
        pane_id="%1",
        text="Read and execute task file: /tmp/briefing.txt",
        agent="codex",
    )

    assert ok is False
    assert called["type"] == 1
    assert called["send"] == 1
    assert called["paste"] == 0


def test_inject_prompt_to_pane_retry_once_for_gemini_on_probe_miss(monkeypatch) -> None:
    """Gemini prompt injection may retry once on probe miss."""
    called = {"type": 0, "send": 0, "paste": 0}

    monkeypatch.setattr(cli, "_wait_for_agent_ready", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "wait_for_pane_quiet", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "_pane_contains_probe", lambda **_kwargs: False)
    monkeypatch.setattr(cli, "type_pane_text", lambda **_kwargs: called.__setitem__("type", called["type"] + 1))
    monkeypatch.setattr(cli, "send_pane_text", lambda **_kwargs: called.__setitem__("send", called["send"] + 1))
    monkeypatch.setattr(cli, "paste_pane_text", lambda **_kwargs: called.__setitem__("paste", called["paste"] + 1))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)

    ok = cli._inject_prompt_to_pane(
        pane_id="%1",
        text="读取并执行任务文件：/tmp/briefing.txt",
        agent="gemini",
    )

    assert ok is False
    assert called["type"] == 2
    assert called["send"] == 2
    assert called["paste"] == 0


def test_launch_agent_in_pane_waits_for_shell_input_ready(monkeypatch) -> None:
    """Launcher should wait for shell input readiness before sending agent command."""
    calls = {"shell_wait": 0, "ctrl_c": 0, "sent": []}

    def _fake_shell_wait(**_kwargs):
        calls["shell_wait"] += 1
        return calls["shell_wait"] >= 2

    monkeypatch.setattr(cli, "_wait_for_shell_input_ready_in_pane", _fake_shell_wait)
    monkeypatch.setattr(cli, "wait_for_pane_quiet", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_agent_ready", lambda **_kwargs: True)
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **kwargs: calls["sent"].append(str(kwargs.get("text", ""))),
    )

    def _fake_run(cmd, **_kwargs):
        if isinstance(cmd, list) and "send-keys" in cmd and "C-c" in cmd:
            calls["ctrl_c"] += 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    launch_cmd, restored, ready = cli._launch_agent_in_pane_with_wait(
        pane_id="%1",
        agent="codex",
        runtime_session_id="",
    )

    assert ready is True
    assert restored is False
    assert launch_cmd == "codex"
    assert calls["ctrl_c"] == 1
    assert calls["sent"] == ["codex"]


def test_resume_recover_skips_prompt_inject_when_launch_not_ready(monkeypatch, tmp_path) -> None:
    """resume recover should never inject prompt when controller launch did not become ready."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="lost-session",
        controller_agent="codex",
        controller_pane="%1",
    )

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli, "_tmux_resolve_session_for_pane", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_detect_tmux_session_name", lambda **_kwargs: "")
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
    monkeypatch.setattr(
        cli,
        "_launch_agent_in_pane_with_wait",
        lambda **_kwargs: ("codex", False, False),
    )
    monkeypatch.setattr(cli, "_write_briefing_file", lambda **_kwargs: tmp_path / "briefing.txt")
    monkeypatch.setattr(cli, "_build_prompt_dispatch_message", lambda **_kwargs: "resume dispatch")
    monkeypatch.setattr(
        cli,
        "_inject_prompt_to_pane",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not inject when launch_ready=false")),
    )
    monkeypatch.setattr(cli, "attach_session", lambda **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["resume", "recover", store.run_id, "-w", str(tmp_path), "-A", "-j"],
    )

    assert result.exit_code == 0
    cleaned = cli.ANSI_ESCAPE_RE.sub("", result.output)
    assert '"launch_ready": false' in cleaned
    assert '"prompt_injected": false' in cleaned


def test_prompt_probe_uses_stable_prefix_for_colon_messages() -> None:
    """Probe should avoid long path suffix to survive wrapped terminal output."""
    text = "Read and execute task file: /Users/skyhua/test/.ai-collab/briefings/abc.txt"
    probe = cli._prompt_probe(text)
    assert probe == "read and execute task file"


def test_resolve_runtime_language_prefers_system_chinese(monkeypatch) -> None:
    """Runtime language should follow zh locale when no CLI override is passed."""
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("AI_COLLAB_PREFER_SYSTEM_LANG", "1")

    resolved = cli._resolve_runtime_language(cli_lang=None, config_lang="en-US")

    assert resolved == "zh-CN"


def test_resolve_runtime_language_uses_macos_applelanguages_when_lang_neutral(monkeypatch) -> None:
    """On macOS, language fallback should read AppleLanguages when LANG is neutral."""
    class _Result:
        stdout = "(\n    \"zh-Hans-CN\",\n    \"en-US\"\n)\n"

    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("AI_COLLAB_PREFER_SYSTEM_LANG", "1")
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.subprocess, "run", lambda *_a, **_k: _Result())

    resolved = cli._resolve_runtime_language(cli_lang=None, config_lang="en-US")

    assert resolved == "zh-CN"


def test_relay_to_controller_input_enabled_default_false(monkeypatch) -> None:
    """Relay input injection should be disabled by default to avoid polluting prompt input."""
    monkeypatch.delenv("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", raising=False)
    assert cli._relay_to_controller_input_enabled() is False

    monkeypatch.setenv("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", "1")
    assert cli._relay_to_controller_input_enabled() is True


def test_emit_relay_event_writes_log_without_input_injection_by_default(monkeypatch, tmp_path) -> None:
    """Relay event should write log and avoid injecting pane input unless explicitly enabled."""
    sent = {"count": 0}
    status_calls = {"count": 0}

    monkeypatch.delenv("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", raising=False)
    monkeypatch.delenv("AI_COLLAB_RELAY_STATUS_MESSAGE", raising=False)
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **_kwargs: sent.__setitem__("count", sent["count"] + 1),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: status_calls.__setitem__("count", status_calls["count"] + 1),
    )

    cli._emit_relay_event(
        cwd=tmp_path,
        session="ai-collab-live",
        controller_pane="%1",
        message="[ai-collab relay] gemini step done -> S2",
    )

    event_file = tmp_path / ".ai-collab" / "logs" / "ai-collab-live" / "events.log"
    assert event_file.exists()
    assert "gemini step done -> S2" in event_file.read_text(encoding="utf-8")
    assert sent["count"] == 0
    assert status_calls["count"] >= 1


def test_notify_controller_to_confirm_subagent_close_enabled(monkeypatch) -> None:
    """Completion hook should show status and inject prompt into controller input by default."""
    sent: list[str] = []
    status_calls = {"count": 0}
    monkeypatch.delenv("AI_COLLAB_CONTROLLER_ASK_CLOSE_ON_COMPLETE", raising=False)
    monkeypatch.delenv("AI_COLLAB_CONTROLLER_CLOSE_PROMPT_TO_INPUT", raising=False)
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **kwargs: sent.append(str(kwargs.get("text", ""))),
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: status_calls.__setitem__("count", status_calls["count"] + 1),
    )

    cli._notify_controller_to_confirm_subagent_close(
        controller_pane="%1",
        agent="claude",
        pane_id="%2",
    )

    assert len(sent) >= 2
    assert "First ask user whether to close" in sent[0]
    assert sent[1] == ""
    assert status_calls["count"] >= 1


def test_notify_controller_to_confirm_subagent_close_can_inject_when_enabled(monkeypatch) -> None:
    """Optional input injection should work when explicitly enabled."""
    sent: list[str] = []
    monkeypatch.setenv("AI_COLLAB_CONTROLLER_ASK_CLOSE_ON_COMPLETE", "1")
    monkeypatch.setenv("AI_COLLAB_CONTROLLER_CLOSE_PROMPT_TO_INPUT", "1")
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **kwargs: sent.append(str(kwargs.get("text", ""))),
    )
    monkeypatch.setattr(cli.subprocess, "run", lambda *_args, **_kwargs: None)

    cli._notify_controller_to_confirm_subagent_close(
        controller_pane="%1",
        agent="claude",
        pane_id="%2",
    )

    assert sent
    assert "First ask user whether to close" in sent[0]


def test_extract_handoff_targets_accepts_live_line_suffix_noise() -> None:
    """Terminal spinner noise after marker should not block extraction."""
    text = "HANDOFF_TO: gemini•Marking step completion"
    assert cli._extract_handoff_targets(text) == ["gemini"]


def test_extract_step_done_ids_accepts_live_line_suffix_noise() -> None:
    """STEP_DONE markers should parse even with inline summary suffix."""
    text = "STEP_DONE: S2 | 已完成阶段输出"
    assert cli._extract_step_done_ids(text) == ["S2"]


def test_extract_step_start_ids_accepts_plain_and_alias_markers() -> None:
    """STEP_START and Sx_START markers should both parse into step ids."""
    text = """
STEP_START: S2
S3_START
"""
    assert cli._extract_step_start_ids(text) == ["S2", "S3"]


def test_sync_controller_progress_from_text_updates_steps(tmp_path) -> None:
    """Controller marker sync should auto-create and complete step states."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="sess-a",
        controller_agent="codex",
        controller_pane="%1",
    )

    cli._sync_controller_progress_from_text(
        run_store=store,
        text="S2_START\nSTEP_DONE: S2\n",
        source="test",
    )

    state = store.snapshot()
    assert state["steps"]["S2"]["status"] == "done"
    assert state["steps"]["S2"]["agent"] == "codex"
    assert state["phase"] == "step_completed"
    events = store.paths.events_file.read_text(encoding="utf-8")
    assert '"type": "step_started"' in events
    assert '"type": "step_done"' in events


def test_format_steps_triad_prefers_phase_marker_and_reason() -> None:
    """Steps triad should show step+status+progress and short reason."""
    item = {
        "phase": "subagent_spawned",
        "phase_detail": "codex:%2",
        "steps": {
            "S2": {"status": "running"},
        },
        "agents": {
            "codex": {"status": "running"},
        },
    }
    assert cli._format_steps_triad(item) == "S2 running (0/1)"


def test_format_steps_triad_done_state_is_concise() -> None:
    """Done steps should not append reason suffix."""
    item = {
        "phase": "step_completed",
        "phase_detail": "S3:done",
        "steps": {
            "S2": {"status": "done"},
            "S3": {"status": "done"},
        },
        "agents": {
            "codex": {"status": "completed"},
        },
    }
    assert cli._format_steps_triad(item) == "S3 done (2/2)"


def test_truncate_prompt_preview_for_table_keeps_short_and_ellipsis_long() -> None:
    """Only prompt preview should be ellipsized for compact table display."""
    assert cli._truncate_prompt_preview_for_table("short prompt") == "short prompt"
    assert cli._truncate_prompt_preview_for_table(
        "读取并执行任务文件：/Users/skyhua/.ai-collab/briefings/abcdef.txt",
        max_chars=12,
    ).endswith("…")


def test_extract_runtime_session_ids_from_common_lines() -> None:
    """Runtime session ids should be parsed from common session/conversation markers."""
    text = """
Session ID: abcdef123456
conversation_id=run-8899-xy
resume ZZZ998877
"""
    values = cli._extract_runtime_session_ids(text)
    assert "abcdef123456" in values
    assert "run-8899-xy" in values
    assert "ZZZ998877" in values


def test_capture_tmux_layout_snapshot_returns_unavailable_when_tmux_missing(monkeypatch) -> None:
    """Layout snapshot helper should degrade gracefully when tmux is unavailable."""
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    snapshot = cli._capture_tmux_layout_snapshot(session="s1", preview_lines=3)
    assert snapshot["available"] is False
    assert snapshot["session"] == "s1"


def test_extract_ai_collab_events_parses_json_lines() -> None:
    """Structured AI_COLLAB_EVENT lines should parse into dict payloads."""
    text = """
AI_COLLAB_EVENT: {"type":"step_done","run_id":"r1","step_id":"S2","nonce":"n2","status":"ok"}
noise
AI_COLLAB_EVENT {"type":"subagent_complete","run_id":"r1","agent":"claude","status":"ok"}
"""
    events = cli._extract_ai_collab_events(text)
    assert len(events) == 2
    assert events[0]["type"] == "step_done"
    assert events[1]["type"] == "subagent_complete"


def test_extract_ai_collab_events_parses_wrapped_json_lines() -> None:
    """Wrapped terminal lines should still parse into one structured event payload."""
    text = """
AI_COLLAB_EVENT: {"type":"step_done","run_id":"r1","step_id":"S1","nonce":"n1","status":"ok","summary":"line1
line2"}
STEP_DONE: S1
"""
    events = cli._extract_ai_collab_events(text)
    assert len(events) == 1
    assert events[0]["type"] == "step_done"
    assert events[0]["step_id"] == "S1"


def test_build_step_tickets_sets_missing_ids() -> None:
    """Step ticket builder should assign step ids and non-empty nonces."""
    steps = [{"role": "impl"}, {"id": "S9", "role": "review"}]
    tickets = cli._build_step_tickets(steps)
    assert steps[0]["id"] == "S1"
    assert steps[1]["id"] == "S9"
    assert tickets[0]["step_id"] == "S1"
    assert tickets[1]["step_id"] == "S9"
    assert tickets[0]["nonce"]


def test_normalize_terminal_text_for_markers_strips_ansi_and_carriage() -> None:
    """Marker normalization should convert carriage updates into parsable plain lines."""
    raw = "A\r\x1b[31mHANDOFF_TO: claude\x1b[0m\rSTEP_DONE: S3"
    normalized = cli._normalize_terminal_text_for_markers(raw)
    assert "HANDOFF_TO: claude" in normalized
    assert "STEP_DONE: S3" in normalized
    assert "\\x1b[" not in normalized


def test_wait_for_agent_ready_claude_trust_gate_selects_trust_option(monkeypatch) -> None:
    """Claude trust gate should auto-select option 1 instead of raw Enter."""
    snapshots = iter(
        [
            "Claude Code'll be able to read\\n1. Yes, I trust this folder\\n2. No, exit\\nEnter to confirm",
            '❯ Try "create a util logging.py that..."\\nctrl+t to hide tasks',
        ]
    )
    sent_texts: list[str] = []

    monkeypatch.setattr(cli, "capture_pane_text", lambda **_kwargs: next(snapshots))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **kwargs: sent_texts.append(str(kwargs.get("text", ""))),
    )

    ok = cli._wait_for_agent_ready(pane_id="%1", agent="claude", timeout_seconds=2.0)
    assert ok is True
    assert "1" in sent_texts


def test_runner_blocks_nested_orchestration(monkeypatch) -> None:
    """When already in ai-collab session, ai-collab should refuse nested runs by default."""
    import os
    import sys
    from io import StringIO
    from contextlib import redirect_stdout, redirect_stderr

    monkeypatch.setenv("AI_COLLAB_ACTIVE", "1")
    monkeypatch.setenv("AI_COLLAB_ROLE", "controller")
    monkeypatch.setattr(sys, "argv", ["ai-collab", "--provider", "codex", "tiny task"])

    out = StringIO()
    err = StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        cli.runner_main()

    text = out.getvalue() + err.getvalue()
    assert "Nested orchestration is disabled" in text
    os.environ.pop("AI_COLLAB_ACTIVE", None)
    os.environ.pop("AI_COLLAB_ROLE", None)


class _FakeQuestionary:
    class _Result:
        def __init__(self, value: str):
            self._value = value

        def ask(self) -> str:
            return self._value

    def text(self, _prompt: str, default: str = "") -> "_FakeQuestionary._Result":
        return _FakeQuestionary._Result("tiny todo task")


def test_collect_runner_inputs_with_interactive_prompt(monkeypatch) -> None:
    """When task is missing, interactive flow should ask provider/mode/task."""
    args = SimpleNamespace(
        task=[],
        provider=None,
        execution_mode="auto",
    )
    choices = iter(["gemini", "tmux"])
    monkeypatch.setattr(
        cli,
        "_select_decision",
        lambda *_args, **_kwargs: next(choices),
    )
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    provider, mode, task = cli._collect_runner_inputs(
        args=args,
        provider_prefix=None,
        default_provider="codex",
        providers=["claude", "codex", "gemini"],
        lang="zh-CN",
        decision_ui=_FakeQuestionary(),
    )

    assert provider == "gemini"
    assert mode == "tmux"
    assert task == "tiny todo task"


def test_build_controller_prompt_document_contains_roster_and_json_contract() -> None:
    """Controller prompt doc should include config-driven roster and JSON plan schema."""
    config = Config.create_default()
    config.auto_collaboration = {
        "persona_phase_map": {"discover": "research-analyst"},
        "persona_skill_map": {"research-analyst": ["ecosystem-research"]},
    }
    result = SimpleNamespace(
        available_agents=[
            {
                "agent": "codex",
                "selected_model": "gpt-5.4",
                "model_profile": "high",
                "strengths": "implementation, backend",
            },
            {
                "agent": "claude",
                "selected_model": "sonnet-4.6",
                "model_profile": "default",
                "strengths": "reasoning, architecture",
            },
        ],
        orchestration_plan=[
            {"role": "tech-selection", "agent": "claude", "selected_model": "sonnet-4.6", "reason": "strengths"},
            {"role": "backend-build", "agent": "codex", "selected_model": "gpt-5.4", "reason": "strengths"},
        ],
    )

    prompt = cli._build_controller_prompt_document(
        task="实现极小待办功能",
        controller="codex",
        result=result,
        config=config,
        lang="zh-CN",
    )

    assert "可用 Agent 与模型" in prompt
    assert "codex" in prompt
    assert "claude" in prompt
    assert '"plan_version": "1.0"' in prompt
    assert "approval_question" in prompt


def test_wizard_selected_tmux_skips_action_menu(monkeypatch) -> None:
    """If user already selected tmux in wizard flow, do not ask action menu again."""
    config = Config.create_default()
    config.current_controller = "codex"
    config.ui_language = "zh-CN"

    fake_result = SimpleNamespace(
        need_collaboration=True,
        workflow_engine="v2",
        session_preset="design-first",
        workflow_blueprint="design-led-loop",
        primary="codex",
        reviewers=["claude", "gemini"],
        project_categories=[],
        suggested_skills=[],
        available_agents=[],
        orchestration_plan=[{"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.4"}],
        selected_agents=["codex", "claude"],
        execution_mode="multi-agent",
        model_dump=lambda: {},
    )

    monkeypatch.setattr(cli.Config, "load", lambda: config)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab"])
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli, "_pick_ui_backend", lambda *_a, **_k: object())
    monkeypatch.setattr(cli, "_collect_runner_inputs", lambda **_k: ("codex", "tmux", "tiny todo"))
    monkeypatch.setattr(cli, "_prepare_controller_prompt_document", lambda **_k: "controller prompt")
    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _r: True)
    monkeypatch.setattr(cli, "_launch_tmux_orchestration", lambda **_k: True)
    monkeypatch.setattr(cli, "_print_orchestration_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_request_controller_plan", lambda **_k: {"plan_version": "1.0", "steps": []})
    monkeypatch.setattr(cli, "_show_controller_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_ask_yes_no", lambda *_a, **_k: True)
    monkeypatch.setattr(cli.CollaborationDetector, "detect", lambda *_a, **_k: fake_result)

    menu_called = {"value": False}

    def _fail_if_called(*_a, **_k):
        menu_called["value"] = True
        raise AssertionError("action menu should be skipped")

    monkeypatch.setattr(cli, "_select_decision", _fail_if_called)

    cli.runner_main()

    assert menu_called["value"] is False



def test_tmux_mode_disables_controller_first_by_default(monkeypatch) -> None:
    """tmux mode should skip controller-first planning unless explicitly requested."""
    config = Config.create_default()
    config.current_controller = "claude"
    config.ui_language = "zh-CN"
    config.auto_collaboration = {"enabled": True, "controller_first": True}

    fake_result = SimpleNamespace(
        need_collaboration=True,
        workflow_engine="v2",
        session_preset="auto",
        workflow_blueprint="delivery-loop",
        primary="codex",
        reviewers=["claude", "gemini"],
        project_categories=[],
        suggested_skills=[],
        available_agents=[],
        orchestration_plan=[{"agent": "claude", "role": "controller", "selected_model": "claude-sonnet-4-6"}],
        selected_agents=["claude", "codex", "gemini"],
        execution_mode="multi-agent",
        model_dump=lambda: {},
    )

    monkeypatch.setattr(cli.Config, "load", lambda: config)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "--provider", "claude", "--execution-mode", "tmux", "tiny todo"])
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli.CollaborationDetector, "detect", lambda *_a, **_k: fake_result)
    monkeypatch.setattr(cli, "_pick_ui_backend", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_can_launch_tmux", lambda _r: True)
    monkeypatch.setattr(cli, "_prepare_controller_prompt_document", lambda **_k: "controller prompt")
    monkeypatch.setattr(cli, "_launch_tmux_orchestration", lambda **_k: True)
    monkeypatch.setattr(cli, "_print_orchestration_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli,
        "_request_controller_plan",
        lambda **_k: (_ for _ in ()).throw(AssertionError("controller-first should be skipped in tmux mode")),
    )

    cli.runner_main()


def test_extract_json_object_from_mixed_text() -> None:
    """Should parse first JSON object from mixed stdout/stderr text."""
    payload = cli._extract_json_object(
        "log line\n{\"plan_version\":\"1.0\",\"steps\":[{\"id\":\"S1\"}]}\nmore logs"
    )

    assert isinstance(payload, dict)
    assert payload["plan_version"] == "1.0"
    assert payload["steps"][0]["id"] == "S1"


def test_dry_run_controller_first_prefers_controller_plan(monkeypatch) -> None:
    """In dry-run, controller-first should show controller JSON plan when available."""
    import sys

    config = Config.create_default()
    config.current_controller = "codex"
    config.ui_language = "zh-CN"
    config.auto_collaboration = {"enabled": True, "controller_first": True}

    fake_result = SimpleNamespace(
        need_collaboration=True,
        workflow_engine="v2",
        session_preset="design-first",
        workflow_blueprint="design-led-loop",
        primary="codex",
        reviewers=["claude"],
        project_categories=[],
        suggested_skills=[],
        available_agents=[],
        orchestration_plan=[{"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.4"}],
        selected_agents=["codex"],
        execution_mode="multi-agent",
        model_dump=lambda: {},
    )

    shown = {"plan": False}

    monkeypatch.setattr(cli.Config, "load", lambda: config)
    monkeypatch.setattr(sys, "argv", ["ai-collab", "--provider", "codex", "--dry-run", "tiny todo"])
    monkeypatch.setattr(cli.CollaborationDetector, "detect", lambda *_a, **_k: fake_result)
    monkeypatch.setattr(cli, "_print_orchestration_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli,
        "_request_controller_plan",
        lambda **_k: {"plan_version": "1.0", "steps": [{"id": "S1"}]},
    )
    monkeypatch.setattr(cli, "_show_controller_plan", lambda *_a, **_k: shown.__setitem__("plan", True))
    monkeypatch.setattr(
        cli,
        "_build_controller_prompt_document",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should not build fallback prompt")),
    )

    cli.runner_main()

    assert shown["plan"] is True


def test_runner_forwards_v2_route_metadata_to_workflow_manager(monkeypatch) -> None:
    config = Config.create_default()
    config.current_controller = "codex"
    config.ui_language = "zh-CN"
    config.auto_collaboration = {"enabled": True, "controller_first": False}

    fake_result = SimpleNamespace(
        need_collaboration=True,
        workflow_engine="v2",
        session_preset="design-first",
        workflow_blueprint="design-led-loop",
        responsibility_stages=["collect", "model", "plan", "artifact", "execute", "validate", "correct", "deliver"],
        primary="codex",
        reviewers=["claude", "gemini"],
        project_categories=["superapp-fullstack"],
        suggested_skills=["api-integration"],
        available_agents=[],
        orchestration_plan=[{"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.4"}],
        selected_agents=["codex", "claude", "gemini"],
        execution_mode="multi-agent",
        model_dump=lambda: {},
    )

    captured: dict[str, object] = {}

    class _FakeWorkflowManager:
        def __init__(self, _config):  # noqa: D401, ANN001
            pass

        def execute_workflow(self, workflow_name, task, context):  # noqa: ANN001
            captured["workflow_name"] = workflow_name
            captured["task"] = task
            captured["context"] = context
            return {}

    monkeypatch.setattr(cli.Config, "load", lambda: config)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "--provider", "codex", "--execution-mode", "direct", "build module"])
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli.CollaborationDetector, "detect", lambda *_a, **_k: fake_result)
    monkeypatch.setattr(cli, "_print_orchestration_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_print_available_agents", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "WorkflowManager", _FakeWorkflowManager)

    cli.runner_main()

    assert captured["workflow_name"] == "design-led-loop"
    assert captured["task"] == "build module"
    assert captured["context"]["workflow_engine"] == "v2"
    assert captured["context"]["session_preset"] == "design-first"
    assert captured["context"]["workflow_blueprint"] == "design-led-loop"
    assert "legacy_workflow" not in captured["context"]


def test_request_controller_plan_adds_codex_skip_repo_flag(monkeypatch) -> None:
    """Controller planning call for codex should include --skip-git-repo-check."""
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.4"
    captured = {"cmd": []}

    class _Result:
        returncode = 0
        stdout = '{"plan_version":"1.0","controller":"codex","requires_multi_agent":false,"agents":[],"steps":[],"approval_question":"Proceed?"}'
        stderr = ""

    def _fake_run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        return _Result()

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    plan, error = cli._request_controller_plan(
        config=config,
        controller="codex",
        prompt_text="return json only",
    )

    assert error is None
    assert isinstance(plan, dict)
    assert "--skip-git-repo-check" in captured["cmd"]


def test_list_command_shows_v2_presets_and_hides_built_in_legacy_catalog(monkeypatch) -> None:
    config = Config.create_default()

    runner = CliRunner()
    monkeypatch.setattr(cli.Config, "load", lambda: config)

    result = runner.invoke(cli.main, ["list"])

    assert result.exit_code == 0
    assert "Session Presets" in result.output
    assert "design-first" in result.output
    assert "design-led-loop" in result.output
    assert "Legacy Compatibility Workflows" not in result.output


def test_build_controller_planner_env_isolates_codex_home(tmp_path, monkeypatch) -> None:
    source_home = tmp_path / ".codex"
    source_home.mkdir(parents=True, exist_ok=True)
    (source_home / "config.toml").write_text(
        """
model_provider = "right_code"
model = "gpt-5.4"
model_reasoning_effort = "xhigh"
disable_response_storage = true

[model_providers.right_code]
name = "right_code"
base_url = "http://127.0.0.1:15721/v1"
wire_api = "responses"
requires_openai_auth = true

[mcp_servers.pp_mysql]
type = "stdio"
command = "mcp-server-mysql"

[projects."/tmp/other"]
trust_level = "trusted"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (source_home / "auth.json").write_text("{\"token\":\"test\"}\n", encoding="utf-8")

    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.chdir(tmp_path)

    env = cli._build_controller_planner_env(controller="codex", temp_dir=str(tmp_path / "planner-temp"))

    isolated_home = Path(env["CODEX_HOME"])
    assert isolated_home != source_home
    assert (isolated_home / "config.toml").exists()
    assert (isolated_home / "auth.json").exists()
    config_text = (isolated_home / "config.toml").read_text(encoding="utf-8")
    assert "mcp_servers" not in config_text
    assert "right_code" in config_text
    assert str(tmp_path.resolve()) in config_text
    assert env["OTEL_SDK_DISABLED"] == "true"



def test_build_controller_planner_command_for_codex_uses_schema_and_output_files() -> None:
    """Codex planner should use exec mode plus schema and final-message output file."""
    cmd = cli._build_controller_planner_command(
        provider_cli="codex --model gpt-5.4",
        controller="codex",
        prompt_text="return json only",
        schema_path="/tmp/schema.json",
        output_path="/tmp/output.json",
    )

    assert cmd[:2] == ["codex", "exec"]
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("--output-schema") + 1] == "/tmp/schema.json"
    assert cmd[cmd.index("--output-last-message") + 1] == "/tmp/output.json"
    assert cmd[-1] == "return json only"



def test_build_controller_planner_command_for_claude_uses_print_json_schema() -> None:
    """Claude planner should switch to print/json/schema mode and drop resume flags."""
    cmd = cli._build_controller_planner_command(
        provider_cli="claude -c --model claude-sonnet-4-6 --output-format text",
        controller="claude",
        prompt_text="return json only",
    )

    assert "-c" not in cmd
    assert "-p" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert "--json-schema" in cmd
    assert cmd[-1] == "return json only"



def test_build_controller_planner_command_for_gemini_uses_json_plan_prompt() -> None:
    """Gemini planner should force json output, plan approval mode, and headless prompt."""
    cmd = cli._build_controller_planner_command(
        provider_cli="gemini -o text --approval-mode yolo -y",
        controller="gemini",
        prompt_text="return json only",
    )

    assert "-y" not in cmd
    assert cmd[cmd.index("-o") + 1] == "json"
    assert cmd[cmd.index("--approval-mode") + 1] == "plan"
    assert cmd[-2:] == ["-p", "return json only"]



def test_request_controller_plan_prefers_codex_output_last_message(monkeypatch) -> None:
    """Codex planner should parse the structured final message file when provided."""
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.4"
    captured = {"cmd": []}

    class _Result:
        returncode = 0
        stdout = "progress line"
        stderr = ""

    def _fake_run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "plan_version": "1.0",
                    "controller": "codex",
                    "requires_multi_agent": False,
                    "agents": [],
                    "steps": [],
                    "approval_question": "Proceed?",
                }
            ),
            encoding="utf-8",
        )
        return _Result()

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    plan, error = cli._request_controller_plan(
        config=config,
        controller="codex",
        prompt_text="return json only",
    )

    assert error is None
    assert isinstance(plan, dict)
    assert plan["controller"] == "codex"
    assert "--output-last-message" in captured["cmd"]


def test_request_controller_plan_falls_back_to_codex_jsonl_when_last_message_empty(monkeypatch) -> None:
    """If Codex writes an empty last-message file, retry with JSONL parsing."""
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.4"
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, *, stdout: str, stderr: str = "", returncode: int = 0) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            output_path = Path(cmd[cmd.index("--output-last-message") + 1])
            output_path.write_text("", encoding="utf-8")
            return _Result(stdout="", stderr="Warning: no last agent message; wrote empty content")
        return _Result(
            stdout='\n'.join(
                [
                    '{"type":"turn.started"}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"plan_version\\":\\"1.0\\",\\"controller\\":\\"codex\\",\\"requires_multi_agent\\":false,\\"agents\\":[{\\"name\\":\\"codex\\",\\"model\\":\\"gpt-5.4\\",\\"persona\\":\\"controller\\",\\"why\\":\\"\\"}],\\"steps\\":[{\\"id\\":\\"S1\\",\\"owner\\":\\"codex\\",\\"goal\\":\\"测试\\",\\"input\\":\\"\\",\\"output\\":\\"测试\\",\\"done_when\\":\\"完成测试\\",\\"eta_minutes\\":5}],\\"approval_question\\":\\"Proceed?\\"}"}}',
                    '{"type":"turn.completed"}',
                ]
            )
        )

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    plan, error = cli._request_controller_plan(
        config=config,
        controller="codex",
        prompt_text="return json only",
    )

    assert error is None
    assert isinstance(plan, dict)
    assert plan["controller"] == "codex"
    assert len(calls) == 2
    assert "--json" in calls[1]


def test_request_controller_plan_falls_back_when_codex_last_message_warning_has_nonzero_exit(monkeypatch) -> None:
    """Even with nonzero exit, Codex last-message warning should still trigger JSONL fallback."""
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.4"
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, *, stdout: str, stderr: str = "", returncode: int = 0) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            output_path = Path(cmd[cmd.index("--output-last-message") + 1])
            output_path.write_text("", encoding="utf-8")
            return _Result(
                stdout="",
                stderr="Warning: no last agent message; wrote empty content to /tmp/out.json",
                returncode=1,
            )
        return _Result(
            stdout='\n'.join(
                [
                    '{"type":"turn.started"}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"plan_version\\":\\"1.0\\",\\"controller\\":\\"codex\\",\\"requires_multi_agent\\":false,\\"agents\\":[{\\"name\\":\\"codex\\",\\"model\\":\\"gpt-5.4\\",\\"persona\\":\\"controller\\",\\"why\\":\\"\\"}],\\"steps\\":[{\\"id\\":\\"S1\\",\\"owner\\":\\"codex\\",\\"goal\\":\\"测试\\",\\"input\\":\\"\\",\\"output\\":\\"测试\\",\\"done_when\\":\\"完成测试\\",\\"eta_minutes\\":5}],\\"approval_question\\":\\"Proceed?\\"}"}}',
                    '{"type":"turn.completed"}',
                ]
            ),
            returncode=0,
        )

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    plan, error = cli._request_controller_plan(
        config=config,
        controller="codex",
        prompt_text="return json only",
    )

    assert error is None
    assert isinstance(plan, dict)
    assert plan["controller"] == "codex"
    assert len(calls) == 2
    assert "--json" in calls[1]


def test_extract_controller_plan_from_jsonl_ignores_user_prompt_example_json() -> None:
    jsonl = '\n'.join(
        [
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"type":"user_message","text":"请严格使用下面这个字段结构：{\\"plan_version\\":\\"1.0\\",\\"controller\\":\\"codex\\",\\"requires_multi_agent\\":true,\\"agents\\":[],\\"steps\\":[{\\"id\\":\\"S1\\",\\"owner\\":\\"codex\\",\\"goal\\":\\"\\",\\"done_when\\":\\"\\",\\"eta_minutes\\":10}],\\"approval_question\\":\\"是否执行？\\"}"}}',
            '{"type":"turn.completed"}',
        ]
    )

    plan = cli._extract_controller_plan_from_jsonl(jsonl)

    assert plan is None


def test_extract_controller_plan_from_jsonl_accepts_agent_message_payload() -> None:
    jsonl = '\n'.join(
        [
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"plan_version\\":\\"1.0\\",\\"controller\\":\\"codex\\",\\"requires_multi_agent\\":false,\\"agents\\":[{\\"name\\":\\"codex\\",\\"model\\":\\"gpt-5.4\\",\\"persona\\":\\"controller\\",\\"why\\":\\"\\"}],\\"steps\\":[{\\"id\\":\\"S1\\",\\"owner\\":\\"codex\\",\\"goal\\":\\"实现贪吃蛇基础框架\\",\\"input\\":\\"制作一个贪吃蛇小游戏\\",\\"output\\":\\"基础框架\\",\\"done_when\\":\\"窗口可打开且蛇能响应方向键\\",\\"eta_minutes\\":15}],\\"approval_question\\":\\"已生成针对贪吃蛇小游戏的初步实现计划，是否开始执行？\\"}"}}',
            '{"type":"turn.completed"}',
        ]
    )

    plan = cli._extract_controller_plan_from_jsonl(jsonl)

    assert plan is not None
    assert plan["controller"] == "codex"
    assert plan["steps"][0]["goal"] == "实现贪吃蛇基础框架"


def test_request_controller_plan_does_not_parse_codex_prompt_echo_from_stdout(monkeypatch) -> None:
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.4"
    calls: list[list[str]] = []

    prompt_echo = """OpenAI Codex v0.114.0 (research preview)
--------
user
请严格使用下面这个字段结构，不要改字段名：
{
  "plan_version": "1.0",
  "controller": "codex",
  "requires_multi_agent": true,
  "agents": [],
  "steps": [{"id":"S1","owner":"codex","goal":"","done_when":"","eta_minutes":10}],
  "approval_question": "是否执行？"
}
"""

    class _Result:
        def __init__(self, *, stdout: str, stderr: str = "", returncode: int = 0) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            output_path = Path(cmd[cmd.index("--output-last-message") + 1])
            output_path.write_text("", encoding="utf-8")
            return _Result(stdout=prompt_echo, stderr="Warning: no last agent message; wrote empty content", returncode=0)
        return _Result(stdout="")

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    plan, error = cli._request_controller_plan(
        config=config,
        controller="codex",
        prompt_text="制作一个贪吃蛇小游戏",
    )

    assert plan is None
    assert error is not None
    assert len(calls) == 2


def test_request_controller_plan_prefers_codex_fallback_stream_error(monkeypatch) -> None:
    """Codex fallback should surface the real stream/provider failure, not the empty last-message warning."""
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.4"
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, *, stdout: str, stderr: str = "", returncode: int = 0) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            output_path = Path(cmd[cmd.index("--output-last-message") + 1])
            output_path.write_text("", encoding="utf-8")
            return _Result(
                stdout="",
                stderr="Warning: no last agent message; wrote empty content to /tmp/out.json",
                returncode=0,
            )
        return _Result(
            stdout='\n'.join(
                [
                    '{"type":"thread.started","thread_id":"abc"}',
                    '{"type":"turn.started"}',
                    '{"type":"error","message":"Reconnecting... 1/5 (stream disconnected before completion: error sending request for url (http://127.0.0.1:15721/v1/responses))"}',
                    '{"type":"turn.failed","error":{"message":"stream disconnected before completion: error sending request for url (http://127.0.0.1:15721/v1/responses)"}}',
                ]
            ),
            stderr="",
            returncode=1,
        )

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    plan, error = cli._request_controller_plan(
        config=config,
        controller="codex",
        prompt_text="制作一个贪吃蛇小游戏",
    )

    assert plan is None
    assert error == "stream disconnected before completion: error sending request for url (http://127.0.0.1:15721/v1/responses)"
    assert len(calls) == 2



def test_extract_controller_plan_payload_handles_wrapped_provider_json() -> None:
    """Wrapped provider JSON should still yield the inner controller plan payload."""
    payload = {
        "type": "result",
        "result": {
            "content": '{"plan_version":"1.0","controller":"claude","requires_multi_agent":true,"agents":[],"steps":[],"approval_question":"Proceed?"}'
        },
    }

    plan = cli._extract_controller_plan_payload(payload)

    assert isinstance(plan, dict)
    assert plan["controller"] == "claude"


def test_controller_plan_schema_is_strict_for_codex_structured_output() -> None:
    """Codex/OpenAI structured outputs require closed object schemas."""
    schema = cli._controller_plan_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())

    agent_item = schema["properties"]["agents"]["items"]
    assert agent_item["type"] == "object"
    assert agent_item["additionalProperties"] is False
    assert set(agent_item["required"]) == set(agent_item["properties"].keys())

    step_item = schema["properties"]["steps"]["items"]
    assert step_item["type"] == "object"
    assert step_item["additionalProperties"] is False
    assert set(step_item["required"]) == set(step_item["properties"].keys())
    assert "eta_minutes" in step_item["required"]
    assert step_item["properties"]["responsibility_stage"]["type"] == ["string", "null"]
    assert step_item["properties"]["artifact_type"]["type"] == ["string", "null"]
    assert step_item["properties"]["boundary"]["type"] == ["string", "null"]
    assert step_item["properties"]["timebox_minutes"]["type"] == ["integer", "null"]


def test_controller_plan_schema_allows_v2_metadata_fields() -> None:
    schema = cli._controller_plan_schema()
    properties = schema["properties"]
    step_properties = schema["properties"]["steps"]["items"]["properties"]

    assert "workflow_engine" in properties
    assert "session_preset" in properties
    assert "workflow_blueprint" in properties
    assert "responsibility_stage" in step_properties
    assert "artifact_type" in step_properties
    assert "boundary" in step_properties
    assert "timebox_minutes" in step_properties
    assert properties["workflow_engine"]["type"] == ["string", "null"]
    assert properties["session_preset"]["type"] == ["string", "null"]
    assert properties["workflow_blueprint"]["type"] == ["string", "null"]


def test_render_controller_plan_skips_null_v2_metadata() -> None:
    text = cli._render_controller_plan(
        {
            "controller": "codex",
            "workflow_engine": None,
            "session_preset": None,
            "workflow_blueprint": None,
            "requires_multi_agent": False,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "ship"}],
            "steps": [
                {
                    "id": "S1",
                    "owner": "codex",
                    "goal": "实现",
                    "input": "任务输入",
                    "output": "代码",
                    "done_when": "完成",
                    "eta_minutes": 10,
                    "responsibility_stage": None,
                    "artifact_type": None,
                    "boundary": None,
                    "timebox_minutes": None,
                }
            ],
            "approval_question": "是否同意该计划？",
        },
        lang="zh-CN",
    )

    assert "工作流引擎: None" not in text
    assert "会话预设: None" not in text
    assert "蓝图: None" not in text
    assert "stage=None" not in text


def test_render_controller_plan_hides_raw_json_braces() -> None:
    """Rendered plan should be human-readable summary, not raw JSON dump."""
    text = cli._render_controller_plan(
        {
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "claude", "model": "claude-sonnet-4-6", "persona": "requirements-architect", "why": "tech"}],
            "steps": [{"id": "S1", "owner": "claude", "goal": "选型", "done_when": "完成"}],
            "approval_question": "是否同意该计划？",
        },
        lang="zh-CN",
    )

    assert "主控: codex" in text
    assert "Agent 编排" in text
    assert "{\n" not in text


def test_prepare_controller_prompt_document_no_auto_editor(monkeypatch, tmp_path) -> None:
    """Interactive prompt doc flow should not auto-open editor when edit_prompt is False."""
    fake_result = SimpleNamespace(
        available_agents=[],
        orchestration_plan=[],
    )
    config = Config.create_default()
    prompt_file = tmp_path / "controller.md"

    monkeypatch.setattr(cli, "_select_decision", lambda *_a, **_k: "send")
    monkeypatch.setattr(
        cli,
        "_write_controller_prompt_file",
        lambda **kwargs: (
            prompt_file.write_text(str(kwargs["text"]), encoding="utf-8"),
            prompt_file,
        )[1],
    )
    monkeypatch.setattr(
        cli,
        "_open_file_in_editor",
        lambda **_k: (_ for _ in ()).throw(AssertionError("editor should not open")),
    )

    prompt = cli._prepare_controller_prompt_document(
        task="tiny todo",
        controller="codex",
        result=fake_result,
        config=config,
        lang="zh-CN",
        decision_ui=None,
        interactive=True,
        edit_prompt=False,
    )

    assert prompt is not None
    assert "主控 Agent 执行文档" in prompt


def test_extract_handoff_targets_ignores_instructional_text() -> None:
    """Instructional bullet/codeblock text must not trigger sub-agent spawning."""
    text = """
- HANDOFF_TO: gemini
`SPAWN_AGENT: claude`
done_when: 输出 HANDOFF_TO: codex
"""
    targets = cli._extract_handoff_targets(text)
    assert targets == []


def test_extract_handoff_targets_accepts_plain_control_lines() -> None:
    """Plain control marker lines should be parsed for watcher routing."""
    text = """
STEP_DONE: S1
HANDOFF_TO: gemini
SPAWN_AGENT: claude
"""
    targets = cli._extract_handoff_targets(text)
    assert targets == ["gemini", "claude"]


def test_extract_step_done_ids_accepts_plain_lines_only() -> None:
    """STEP_DONE extraction should ignore placeholder/instructional lines."""
    text = """
- STEP_DONE: <step_id>
STEP_DONE: S2
"""
    step_ids = cli._extract_step_done_ids(text)
    assert step_ids == ["S2"]


def test_contains_completion_marker_accepts_standalone_marker_line() -> None:
    """Completion marker should match when emitted as a standalone output line."""
    text = """
some output
=== TASK_COMPLETE ===
"""
    assert cli._contains_completion_marker(text) is True


def test_contains_completion_marker_ignores_inline_command_echo() -> None:
    """Inline marker text in echoed command should not be treated as completion."""
    text = "zsh -lc 'sleep 65; printf \"=== TASK_COMPLETE ===\\n\"; exec zsh'"
    assert cli._contains_completion_marker(text) is False


def test_classify_watch_issue_detects_gemini_high_demand_screen() -> None:
    """Gemini high-demand panel should be treated as capacity exhaustion."""
    text = """
We are currently experiencing high demand.
1. Keep trying
2. Switch to gemini-3-flash-preview
"""
    assert cli._classify_watch_issue(text) == "model_capacity_exhausted"


def test_tmux_watch_ignores_seeded_completion_marker(monkeypatch) -> None:
    """Existing marker already in pane history must not complete watch immediately."""
    marker_seed = "instruction line\\n=== TASK_COMPLETE ===\\n"
    printed: list[str] = []
    clock = {"t": 0.0}

    def _fake_monotonic() -> float:
        clock["t"] += 0.25
        return clock["t"]

    def _fake_run(cmd, capture_output=False, text=False, check=False):  # noqa: ARG001
        if cmd[:2] == ["tmux", "capture-pane"]:
            return SimpleNamespace(returncode=0, stdout=marker_seed, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli.subprocess, "run", _fake_run)
    monkeypatch.setattr(cli.time, "monotonic", _fake_monotonic)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        cli.console,
        "print",
        lambda *args, **kwargs: printed.append(" ".join(str(a) for a in args)),
    )

    cli.tmux_watch.callback(
        pane_id="%1",
        timeout_seconds=1.0,
        poll_seconds=0.2,
        capture_lines=220,
        json_output=True,
    )

    assert printed
    payload_text = printed[-1]
    assert '"status": "timeout"' in payload_text
    assert '"reason": "still_running"' in payload_text


def test_tmux_watch_reports_seeded_high_demand_as_capacity_error(monkeypatch) -> None:
    """When high-demand panel is already visible, watch should report capacity error."""
    high_demand_seed = """
We are currently experiencing high demand.
● 1. Keep trying
  2. Switch to gemini-3-flash-preview
  3. Stop
"""
    printed: list[str] = []
    clock = {"t": 0.0}

    def _fake_monotonic() -> float:
        clock["t"] += 0.5
        return clock["t"]

    def _fake_run(cmd, capture_output=False, text=False, check=False):  # noqa: ARG001
        if cmd[:2] == ["tmux", "capture-pane"]:
            return SimpleNamespace(returncode=0, stdout=high_demand_seed, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(cli.subprocess, "run", _fake_run)
    monkeypatch.setattr(cli.time, "monotonic", _fake_monotonic)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        cli.console,
        "print",
        lambda *args, **kwargs: printed.append(" ".join(str(a) for a in args)),
    )

    try:
        cli.tmux_watch.callback(
            pane_id="%1",
            timeout_seconds=12.0,
            poll_seconds=0.2,
            capture_lines=220,
            json_output=True,
        )
        raise AssertionError("tmux-watch should exit non-zero on error status")
    except SystemExit as exc:
        assert exc.code == 1

    assert printed
    payload_text = printed[-1]
    assert '"status": "error"' in payload_text
    assert '"reason": "model_capacity_exhausted"' in payload_text


def test_project_main_routes_launch_and_settings_to_click_main(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        calls.append(list(args))

    monkeypatch.setattr(cli.main, "main", _fake_click_main)

    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "launch", "--help"])
    cli.project_main()
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "settings"])
    cli.project_main()

    assert calls[0][0] == "launch"
    assert calls[1][0] == "settings"


def test_project_main_uses_guided_entry_surface_when_no_args(monkeypatch) -> None:
    config = cli.Config.create_default()
    config.entry_surface = "guided"
    calls = {"guided": False, "runner": False}

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(cli, "run_entry_prompt", lambda cfg: calls.__setitem__("guided", cfg is config), raising=False)
    monkeypatch.setattr(cli, "runner_main", lambda *args, **kwargs: calls.__setitem__("runner", True))
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab"])

    cli.project_main()

    assert calls["guided"] is True
    assert calls["runner"] is False


def test_project_main_uses_command_entry_surface_when_no_args(monkeypatch) -> None:
    config = cli.Config.create_default()
    config.entry_surface = "command"
    calls = {"guided": False, "runner_args": None}

    monkeypatch.setattr(cli.Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(cli, "run_entry_prompt", lambda cfg: calls.__setitem__("guided", True), raising=False)
    monkeypatch.setattr(cli, "runner_main", lambda *args, **kwargs: calls.__setitem__("runner_args", kwargs.get("argv")))
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab"])

    cli.project_main()

    assert calls["guided"] is False
    assert calls["runner_args"] == []


def test_entry_prompt_fragments_keep_init_config_style_language() -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"

    fragments = cli._entry_prompt_fragments(config, pointed_value="2")
    joined = "".join(text for _style, text in fragments)

    assert ("fg:#F8FAFC bold", "开始新任务") in fragments
    assert ("fg:#7DD3FC bold", "恢复之前会话") in fragments
    assert ("fg:#64748B italic", "先定位工作区，再选择一个已保存运行进行恢复。") in fragments
    assert ("fg:#CBD5E1", "退出") in fragments
    assert "↑/↓ 移动" in joined




def test_entry_prompt_fragments_include_header_and_banner() -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"

    fragments = cli._entry_prompt_fragments(config, pointed_value="1")
    joined = "".join(text for _style, text in fragments)

    assert "█████" in joined
    assert "ai-collab" in joined
    assert "选择接下来要做的事。" in joined


def test_entry_prompt_prompt_toolkit_style_converts_rich_background_syntax() -> None:
    from ai_collab.entry_prompt import _prompt_toolkit_style

    assert _prompt_toolkit_style("bold #0F172A on #7DD3FC") == "bold #0F172A bg:#7DD3FC"
    assert _prompt_toolkit_style("fg:#64748B italic") == "fg:#64748B italic"


def test_entry_prompt_selector_clears_before_prompt_toolkit(monkeypatch) -> None:
    from ai_collab.entry_prompt import _select_screen
    import sys

    captured: dict[str, object] = {}

    class _Console:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)

        def run(self) -> str:
            return "1"

    console = _Console()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("prompt_toolkit.application.Application", _FakeApplication)

    result = _select_screen(
        lambda pointed: [("bold", f"title {pointed}")],
        values=["1", "q"],
        default_value="1",
        selector_fn=None,
        input_fn=None,
        console_obj=console,
        clear_screen=True,
        screen_id="entry_root",
    )

    assert result == "1"
    assert console.clear_calls == 1
    assert captured["full_screen"] is False

def test_entry_prompt_home_copy_focuses_on_real_actions() -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"

    fragments = cli._entry_prompt_fragments(config, pointed_value="1")
    joined = "".join(text for _style, text in fragments)

    assert "恢复之前会话" in joined
    assert "选择一个常用入口" not in joined
    assert "新任务会先选工作区" in joined



def test_run_entry_prompt_guides_new_task_through_workspace_selection(monkeypatch, tmp_path) -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"
    captured: dict[str, object] = {}
    choices = iter(["1", "1"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launch_prompt",
        lambda **kwargs: captured.update(kwargs) or None,
    )

    cli.run_entry_prompt(
        config,
        selector_fn=lambda **_: next(choices),
        console_obj=console,
        clear_screen=False,
    )

    assert captured["workspace"] == tmp_path.resolve()
    assert captured["cwd"] == tmp_path.resolve()
    output = buffer.getvalue()
    assert "新任务工作区" in output
    assert "1 工作区" in output
    assert "2 草稿" in output
    assert "● ●" not in output



def test_run_entry_prompt_guides_resume_through_workspace_and_session(monkeypatch, tmp_path) -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"
    captured = {"args": None}
    choices = iter(["2", "1", "1"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    store = RunStateStore.create(cwd=tmp_path, session="dev-session", controller_agent="codex", controller_pane="%1")
    store.set_label(label="修复入口流程")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli.main,
        "main",
        lambda *, args, prog_name, standalone_mode: captured.__setitem__("args", list(args)),
    )

    cli.run_entry_prompt(
        config,
        selector_fn=lambda **_: next(choices),
        console_obj=console,
        clear_screen=False,
    )

    assert captured["args"] == ["resume", "recover", store.run_id, "-w", str(tmp_path.resolve())]
    assert "恢复会话" in buffer.getvalue()


def test_run_entry_prompt_uses_keyboard_selector_before_numeric_prompt(monkeypatch) -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"
    captured = {"args": None, "prompt_called": False}
    choices = iter(["3", "q", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    monkeypatch.setattr(
        cli.main,
        "main",
        lambda *, args, prog_name, standalone_mode: captured.__setitem__("args", list(args)),
    )
    monkeypatch.setattr(
        cli.Prompt,
        "ask",
        lambda *args, **kwargs: captured.__setitem__("prompt_called", True) or "1",
    )

    cli.run_entry_prompt(
        config,
        selector_fn=lambda **_: next(choices),
        console_obj=console,
        clear_screen=False,
    )

    output = buffer.getvalue()
    assert captured["args"] is None
    assert captured["prompt_called"] is False
    assert "↑/↓" in output
    assert "输入数字" not in output


def test_entry_prompt_fragments_show_numeric_prefixes() -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"

    fragments = cli._entry_prompt_fragments(config, pointed_value="1")
    joined = "".join(text for _style, text in fragments)

    assert "1. 开始新任务" in joined
    assert "2. 恢复之前会话" in joined
    assert "3. 打开配置" in joined
    assert "4. 重新初始化" in joined



def test_run_entry_prompt_opens_config_inline_and_returns_home(monkeypatch, tmp_path) -> None:
    config = cli.Config.create_default()
    config.ui_language = "zh-CN"
    calls = {"config": 0, "dispatch": []}
    choices = iter(["3", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ai_collab.config_prompt.run_config_menu_prompt",
        lambda *args, **kwargs: calls.__setitem__("config", calls["config"] + 1) or False,
    )
    monkeypatch.setattr(
        cli.main,
        "main",
        lambda *, args, prog_name, standalone_mode: calls["dispatch"].append(list(args)),
    )

    cli.run_entry_prompt(
        config,
        selector_fn=lambda **_: next(choices),
        console_obj=console,
        clear_screen=False,
    )

    assert calls["config"] == 1
    assert calls["dispatch"] == []
    assert buffer.getvalue().count("开始新任务") >= 2



def test_resume_selection_screen_shows_scannable_metadata(monkeypatch, tmp_path) -> None:
    from ai_collab.entry_prompt import _select_resume_run

    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=110)
    store = RunStateStore.create(cwd=tmp_path, session="resume-session", controller_agent="codex", controller_pane="%1")
    store.set_label(label="修复入口主流程")
    store.set_entry_prompt(text="读取并执行任务文件：/Users/skyhua/.ai-collab/briefings/20260309-105411-codex-controller.txt")
    store.set_step_status(step_id="S1", status="done", agent="codex", summary="完成入口规划")
    store.set_step_status(step_id="S2", status="running", agent="claude", summary="继续处理恢复逻辑")

    state = json.loads(store.paths.state_file.read_text(encoding='utf-8'))
    state["updated_at"] = "2026-03-14T12:34:56+00:00"
    for step in state.get("steps", {}).values():
        if isinstance(step, dict):
            step["updated_at"] = "2026-03-14T12:34:56+00:00"
    store.paths.state_file.write_text(json.dumps(state), encoding='utf-8')

    result, run_id = _select_resume_run(
        config=config,
        workspace=tmp_path,
        selector_fn=lambda **_: "q",
        input_fn=None,
        console_obj=console,
        clear_screen=False,
    )

    output = buffer.getvalue()
    assert result == "quit"
    assert run_id is None
    assert "2026-03-14" in output
    assert "1/2" in output
    assert "Codex" in output
    assert "修复入口主流程" in output



def test_resume_selection_screen_shows_page_indicator_for_many_runs(monkeypatch, tmp_path) -> None:
    from ai_collab.entry_prompt import _select_resume_run

    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=110)

    for index in range(12):
        store = RunStateStore.create(cwd=tmp_path, session=f"resume-{index}", controller_agent="codex", controller_pane="%1")
        store.set_label(label=f"任务 {index + 1}")

    result, run_id = _select_resume_run(
        config=config,
        workspace=tmp_path,
        selector_fn=lambda **_: "q",
        input_fn=None,
        console_obj=console,
        clear_screen=False,
    )

    output = buffer.getvalue()
    assert result == "quit"
    assert run_id is None
    assert "第 1/2 页" in output
