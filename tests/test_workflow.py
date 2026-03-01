"""Tests for workflow execution with persona auto-assignment and escalation."""

from __future__ import annotations

import subprocess

import pytest

from ai_collab.core.config import Config
from ai_collab.core.workflow import WorkflowManager


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
            "discover": {"min_output_chars": 60},
            "develop": {"min_output_chars": 80},
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


def test_auto_assign_persona_and_activate_skills(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow should auto-assign persona and merge persona + auto skills into prompt."""
    config.workflows = {
        "impl-workflow": {
            "description": "Implementation workflow",
            "phases": [
                {
                    "agent": "codex",
                    "action": "develop",
                    "output": "feature patch",
                    "skills": ["tests-first"],
                }
            ],
        }
    }

    captured_prompts: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_prompts.append(str(cmd[-1]))
        return _ok(
            "Implementation complete with tests, integration notes, rollback plan, and risk checklist."
        )

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", fake_run)

    manager = WorkflowManager(config)
    results = manager.execute_workflow(
        "impl-workflow",
        "Implement auth flow",
        {"auto_skills": "systematic-debugging"},
    )

    assert results["phase_1"]["success"] is True
    assert results["phase_1"]["persona"] == "implementation-engineer"
    assert "feature-implementation" in results["phase_1"]["active_skills"]
    assert "systematic-debugging" in results["phase_1"]["active_skills"]
    assert "Persona: implementation-engineer" in captured_prompts[0]
    assert "feature-implementation" in captured_prompts[0]
    assert "systematic-debugging" in captured_prompts[0]


def test_quality_completion_criteria_retries_until_satisfied(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short outputs should fail completion criteria and trigger retry."""
    config.workflows = {
        "discover-workflow": {
            "description": "Discover workflow",
            "phases": [{"agent": "gemini", "action": "discover", "output": "research notes"}],
        }
    }

    calls = {"count": 0}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        if calls["count"] == 1:
            return _ok("too short")
        return _ok("Long enough discover output with findings, alternatives, and trade-offs.")

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", fake_run)

    manager = WorkflowManager(config)
    results = manager.execute_workflow("discover-workflow", "Research options", {})

    assert calls["count"] == 2
    assert results["phase_1"]["success"] is True
    assert results["phase_1"]["attempts"] == 2


def test_repeated_failure_triggers_codex_takeover(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated phase failures should trigger takeover by configured controller agent."""
    config.workflows = {
        "design-workflow": {
            "description": "Design workflow",
            "phases": [{"agent": "gemini", "action": "discover", "output": "draft"}],
        }
    }

    calls = {"gemini": 0, "codex": 0}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        binary = cmd[0]
        if binary == "gemini":
            calls["gemini"] += 1
            return _err("gemini failed")
        if binary == "codex":
            calls["codex"] += 1
            return _ok("Codex takeover delivered stable output with concrete actions.")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", fake_run)

    manager = WorkflowManager(config)
    results = manager.execute_workflow("design-workflow", "Design widgets", {})

    assert calls["gemini"] == 2
    assert calls["codex"] == 1
    assert results["phase_1"]["success"] is True
    assert results["phase_1"]["taken_over"] is True
    assert results["phase_1"]["agent"] == "codex"


def test_repeated_failure_can_escalate_to_user_decision(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When repeated failures happen on controller agent, workflow asks user for decision."""
    config.workflows = {
        "review-workflow": {
            "description": "Review workflow",
            "phases": [{"agent": "codex", "action": "deliver", "output": "final report"}],
        }
    }

    monkeypatch.setattr("ai_collab.core.workflow.subprocess.run", lambda *_args, **_kwargs: _err("still failing"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "skip")

    manager = WorkflowManager(config)
    results = manager.execute_workflow(
        "review-workflow",
        "Deliver final report",
        {"interactive": True},
    )

    assert results["phase_1"]["success"] is False
    assert results["phase_1"]["status"] == "skipped_by_user"
    assert results["_summary"]["status"] == "completed_with_skips"


def test_codex_cli_auto_adds_skip_repo_check_outside_git(config: Config, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """When cwd is not a git repo, codex CLI should include --skip-git-repo-check."""
    manager = WorkflowManager(config)
    monkeypatch.chdir(tmp_path)

    cli = manager._build_phase_cli("codex", "high")

    assert "--skip-git-repo-check" in cli
