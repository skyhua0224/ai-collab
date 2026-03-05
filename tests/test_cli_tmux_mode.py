"""Tests for ai-collab tmux launch behavior."""

from __future__ import annotations

from types import SimpleNamespace

import ai_collab.cli as cli
from click.testing import CliRunner
from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationResult
from ai_collab.core.run_state import RunStateStore


def _sample_result() -> SimpleNamespace:
    return SimpleNamespace(
        execution_mode="multi-agent",
        orchestration_plan=[
            {"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.3-codex"},
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
                "selected_model": "gpt-5.3-codex",
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
    assert "-w, --cwd" in list_help.output
    assert "-n, --limit" in list_help.output
    assert "-j, --json-output" in list_help.output


def test_resume_list_show_rename_roundtrip(tmp_path) -> None:
    """resume list/show/rename should read and update persisted run state."""
    store = RunStateStore.create(
        cwd=tmp_path,
        session="s1",
        controller_agent="codex",
        controller_pane="%1",
    )
    runner = CliRunner()

    listed = runner.invoke(cli.main, ["resume", "list", "-w", str(tmp_path), "-j"])
    assert listed.exit_code == 0
    assert store.run_id in listed.output

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
    monkeypatch.setattr(cli, "_tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(cli, "create_controller_workspace", lambda **_kwargs: "%99")
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


def test_project_main_accepts_short_version_flag(monkeypatch) -> None:
    """project_main should accept -V and forward to click version flow."""
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "-V"])

    cli.project_main()

    assert captured["args"] == ["--version"]


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
            {"name": "codex", "model": "gpt-5.3-codex"},
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
                "selected_model": "gpt-5.3-codex",
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
            {"role": "backend-build", "agent": "codex", "selected_model": "gpt-5.3-codex", "reason": "strengths"},
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
        workflow_name="full-stack",
        primary="codex",
        reviewers=["claude", "gemini"],
        project_categories=[],
        suggested_skills=[],
        available_agents=[],
        orchestration_plan=[{"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.3-codex"}],
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
        workflow_name="full-stack",
        primary="codex",
        reviewers=["claude"],
        project_categories=[],
        suggested_skills=[],
        available_agents=[],
        orchestration_plan=[{"agent": "codex", "role": "backend-build", "selected_model": "gpt-5.3-codex"}],
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


def test_request_controller_plan_adds_codex_skip_repo_flag(monkeypatch) -> None:
    """Controller planning call for codex should include --skip-git-repo-check."""
    config = Config.create_default()
    config.providers["codex"].cli = "codex exec --model gpt-5.3-codex"
    captured = {"cmd": []}

    class _Result:
        returncode = 0
        stdout = '{"plan_version":"1.0","steps":[]}'
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
