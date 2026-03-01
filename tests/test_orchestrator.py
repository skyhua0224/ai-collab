"""Tests for orchestration planning outputs embedded in detector results."""

from __future__ import annotations

from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationDetector


def test_orchestration_plan_exposes_available_agents_and_model_info() -> None:
    """Detector result should surface available agents and selected model/profile per role."""
    config = Config.create_default()
    config.auto_collaboration = {
        "enabled": True,
        "assignment_map": {
            "discover": {"agent": "gemini", "profile": "powerful"},
            "define": {"agent": "claude", "profile": "default"},
            "develop": {"agent": "codex", "profile": "medium"},
            "deliver": {"agent": "claude", "profile": "default"},
        },
        "triggers": [
            {
                "name": "fullstack-superapp",
                "description": "Fullstack development",
                "patterns": ["fullstack"],
                "primary": "codex",
                "reviewers": ["claude", "gemini"],
                "workflow": "full-stack",
            }
        ],
    }
    config.workflows = {
        "full-stack": {
            "description": "Full-stack workflow",
            "phases": [
                {"agent": "claude", "action": "plan", "output": "architecture notes"},
                {"agent": "gemini", "action": "design-frontend", "output": "ui draft"},
                {"agent": "codex", "action": "implement-core", "output": "api and ui"},
                {"agent": "claude", "action": "review-gate", "output": "quality report"},
            ],
        }
    }

    detector = CollaborationDetector(config)
    task = "Build a tiny todo app with frontend + backend and persistent storage"
    result = detector.detect(task, "codex")

    assert result.need_collaboration is True
    assert result.available_agents
    assert any(item.get("agent") == "codex" for item in result.available_agents)
    assert any(item.get("selected_model") for item in result.available_agents)

    assert result.orchestration_plan
    backend_steps = [item for item in result.orchestration_plan if item.get("role") == "backend-build"]
    assert backend_steps
    assert backend_steps[0]["agent"] == "codex"
    assert backend_steps[0]["selected_model"]

