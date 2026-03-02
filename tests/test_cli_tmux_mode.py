"""Tests for ai-collab tmux launch behavior."""

from __future__ import annotations

from types import SimpleNamespace

import ai_collab.cli as cli
from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationResult


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
    )

    assert "不要问用户" in prompt
    assert "禁止先运行 `--help` / `-h` / `--version`" in prompt
    assert "NEED_ELEVATION: <command> | reason=<error>" in prompt
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
    assert "NEED_ELEVATION: <command> | reason=<error>" in prompt


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


def test_relay_to_controller_input_enabled_default_true(monkeypatch) -> None:
    """Relay input injection should be enabled by default for controller visibility."""
    monkeypatch.delenv("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", raising=False)
    assert cli._relay_to_controller_input_enabled() is True

    monkeypatch.setenv("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", "0")
    assert cli._relay_to_controller_input_enabled() is False


def test_emit_relay_event_writes_log_and_injects_input_by_default(monkeypatch, tmp_path) -> None:
    """Relay event should always write event log and inject pane input by default."""
    sent = {"count": 0}

    monkeypatch.delenv("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", raising=False)
    monkeypatch.setattr(
        cli,
        "send_pane_text",
        lambda **_kwargs: sent.__setitem__("count", sent["count"] + 1),
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
    assert sent["count"] == 1


def test_extract_handoff_targets_accepts_live_line_suffix_noise() -> None:
    """Terminal spinner noise after marker should not block extraction."""
    text = "HANDOFF_TO: gemini•Marking step completion"
    assert cli._extract_handoff_targets(text) == ["gemini"]


def test_extract_step_done_ids_accepts_live_line_suffix_noise() -> None:
    """STEP_DONE markers should parse even with inline summary suffix."""
    text = "STEP_DONE: S2 | 已完成阶段输出"
    assert cli._extract_step_done_ids(text) == ["S2"]


def test_normalize_terminal_text_for_markers_strips_ansi_and_carriage() -> None:
    """Marker normalization should convert carriage updates into parsable plain lines."""
    raw = "A\r\x1b[31mHANDOFF_TO: claude\x1b[0m\rSTEP_DONE: S3"
    normalized = cli._normalize_terminal_text_for_markers(raw)
    assert "HANDOFF_TO: claude" in normalized
    assert "STEP_DONE: S3" in normalized
    assert "\\x1b[" not in normalized


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
