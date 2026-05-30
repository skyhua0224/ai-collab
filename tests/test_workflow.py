"""Tests for workflow execution with persona auto-assignment and escalation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_collab.core.config import Config
from ai_collab.core.workflow import WorkflowManager, WorkflowPhase


@pytest.fixture
def config() -> Config:
    """Create a workflow test configuration."""
    cfg = Config.create_default()
    cfg.providers["codex"].cli = "codex"
    cfg.providers["gemini"].cli = "gemini"
    cfg.providers["claude"].cli = "claude"

    cfg.auto_collaboration = {
        "enabled": True,
        "persona_auto_assign": True,
        "persona_phase_map": {
            "discover": "research-analyst",
            "define": "requirements-architect",
            "develop": "implementation-engineer",
            "deliver": "quality-auditor",
        },
        "persona_skill_map": {
            "research-analyst": ["ecosystem-research"],
            "requirements-architect": ["scope-control"],
            "implementation-engineer": ["feature-implementation", "integration-check"],
            "quality-auditor": ["code-review", "risk-review"],
        },
        "phase_completion_criteria": {
            "default": {"min_output_chars": 40},
            "collect": {"min_output_chars": 60},
            "execute": {"min_output_chars": 80},
        },
        "escalation_policy": {
            "max_retries": 1,
            "takeover_agent": "codex",
            "takeover_after_failures": 2,
            "ask_user_on_repeated_failure": True,
        },
    }

    return cfg


def _ok(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["fake"], returncode=0, stdout=stdout, stderr="")


def _err(stderr: str = "failed") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["fake"], returncode=1, stdout="", stderr=stderr)


def test_resolve_execute_phase_assigns_implementation_persona_and_skills(config: Config) -> None:
    """V2 execute stage should resolve to implementation persona and merged skills."""
    manager = WorkflowManager(config)
    phase = WorkflowPhase(
        agent="codex",
        action="execute:execute-change",
        output="feature patch",
        skills=["tests-first"],
        responsibility_stage="execute",
        goal="Implement the requested change",
    )

    resolved = manager._resolve_phase_plan(phase, {"auto_skills": "systematic-debugging"})
    prompt = manager._build_phase_prompt(
        resolved_phase=resolved,
        task="Implement auth flow",
        context={"auto_skills": "systematic-debugging"},
        previous_results={},
        attempt=1,
    )

    assert resolved["persona"] == "implementation-engineer"
    assert "feature-implementation" in resolved["active_skills"]
    assert "integration-check" in resolved["active_skills"]
    assert "systematic-debugging" in resolved["active_skills"]
    assert "Persona: implementation-engineer" in prompt
    assert "feature-implementation" in prompt
    assert "systematic-debugging" in prompt


def test_quality_completion_criteria_retries_until_satisfied(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short outputs should fail completion criteria and trigger retry."""
    manager = WorkflowManager(config)
    resolved = manager._resolve_phase_plan(
        WorkflowPhase(
            agent="gemini",
            action="collect:collect-context",
            output="research notes",
            responsibility_stage="collect",
        ),
        {},
    )

    calls = {"count": 0}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        if calls["count"] == 1:
            return _ok("too short")
        return _ok("Long enough collect output with evidence, constraints, alternatives, and next steps.")

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", fake_run)

    result = manager._execute_phase_with_policy(
        resolved_phase=resolved,
        task="Research options",
        context={},
        previous_results={},
    )

    assert calls["count"] == 2
    assert result["success"] is True
    assert result["attempts"] == 2


def test_repeated_failure_triggers_codex_takeover(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated phase failures should trigger takeover by configured controller agent."""
    manager = WorkflowManager(config)
    resolved = manager._resolve_phase_plan(
        WorkflowPhase(
            agent="gemini",
            action="collect:collect-context",
            output="draft",
            responsibility_stage="collect",
        ),
        {},
    )

    calls = {"gemini": 0, "codex": 0}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        binary = Path(cmd[0]).stem.lower()
        if binary == "gemini":
            calls["gemini"] += 1
            return _err("gemini failed")
        if binary == "codex":
            calls["codex"] += 1
            return _ok("Codex takeover delivered stable output with evidence, actions, and bounded risk notes.")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", fake_run)

    result = manager._execute_phase_with_policy(
        resolved_phase=resolved,
        task="Design widgets",
        context={},
        previous_results={},
    )

    assert calls["gemini"] == 2
    assert calls["codex"] == 1
    assert result["success"] is True
    assert result["taken_over"] is True
    assert result["agent"] == "codex"


def test_repeated_failure_can_escalate_to_user_decision(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When repeated failures happen on controller agent, workflow asks user for decision."""
    manager = WorkflowManager(config)
    resolved = manager._resolve_phase_plan(
        WorkflowPhase(
            agent="codex",
            action="deliver:deliver-outcome",
            output="final report",
            responsibility_stage="deliver",
        ),
        {},
    )

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", lambda *_args, **_kwargs: _err("still failing"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "skip")

    result = manager._execute_phase_with_policy(
        resolved_phase=resolved,
        task="Deliver final report",
        context={"interactive": True},
        previous_results={},
    )

    assert result["success"] is False
    assert result["status"] == "skipped_by_user"


def test_codex_cli_auto_adds_skip_repo_check_outside_git(config: Config, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """When cwd is not a git repo, codex CLI should include --skip-git-repo-check."""
    manager = WorkflowManager(config)
    monkeypatch.chdir(tmp_path)

    cli = manager._build_phase_cli("codex", "high")

    assert "--model gpt-5.5" in cli
    assert 'model_reasoning_effort="high"' in cli
    assert "--skip-git-repo-check" in cli


def test_execute_workflow_uses_intent_routed_v2_when_no_route(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_collab.core.workflow.subprocess.run",
        lambda *_args, **_kwargs: _ok(
            "Collected context, modeled trade-offs, built an execution direction, implemented the change, "
            "validated outcomes, corrected drift, and delivered a concise summary."
        ),
    )

    manager = WorkflowManager(config)
    results = manager.execute_workflow("", "实现一个新功能", {"intent": "implementation"})

    assert results["_summary"]["workflow_engine"] == "v2"
    assert results["_summary"]["workflow_blueprint"] == "delivery-loop"
    assert results["_summary"]["compatibility_mode"] == "intent-routed-v2"
    assert results["_summary"]["requested_route"] == ""
    assert results["_summary"]["total_phases"] == 7


def test_explicit_v2_blueprint_aligns_summary_session_preset(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_collab.core.workflow.subprocess.run",
        lambda *_args, **_kwargs: _ok(
            "Validation completed with acceptance notes, bounded fix guidance, and a concise handoff."
        ),
    )

    manager = WorkflowManager(config)
    results = manager.execute_workflow(
        "",
        "验收当前改动",
        {
            "workflow_engine": "v2",
            "workflow_blueprint": "validation-loop",
        },
    )

    assert results["_summary"]["workflow_engine"] == "v2"
    assert results["_summary"]["workflow_blueprint"] == "validation-loop"
    assert results["_summary"]["session_preset"] == "validation-first"
    assert results["_summary"]["compatibility_mode"] == "direct-v2-blueprint"


def test_session_preset_context_resolves_v2_route(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_collab.core.workflow.subprocess.run",
        lambda *_args, **_kwargs: _ok(
            "Document structure chosen, source material collected, final document drafted, and handoff completed."
        ),
    )

    manager = WorkflowManager(config)
    results = manager.execute_workflow(
        "",
        "写一份 README",
        {
            "session_preset": "document-first",
        },
    )

    assert results["_summary"]["workflow_engine"] == "v2"
    assert results["_summary"]["workflow_blueprint"] == "document-loop"
    assert results["_summary"]["session_preset"] == "document-first"
    assert results["_summary"]["compatibility_mode"] == "direct-v2-preset"


def test_execute_workflow_rejects_unknown_route(config: Config) -> None:
    manager = WorkflowManager(config)

    with pytest.raises(ValueError, match="Unknown workflow route: code-review"):
        manager.execute_workflow("code-review", "实现一个新功能", {})
