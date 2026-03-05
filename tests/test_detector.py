"""Tests for collaboration detection."""

import pytest

from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationDetector
from ai_collab.core.profiler import ProjectProfile


@pytest.fixture
def config():
    """Create test configuration."""
    config = Config.create_default()
    config.auto_collaboration = {
        "enabled": True,
        "consensus_threshold": 0.75,
        "triggers": [
            {
                "name": "visual-design",
                "description": "Visual design tasks",
                "patterns": ["html", "css", "mockup", "design"],
                "primary": "gemini",
                "reviewers": ["claude"],
                "workflow": "design-review",
            },
            {
                "name": "implementation",
                "description": "Implementation tasks",
                "patterns": ["implement", "feature", "function"],
                "primary": "codex",
                "reviewers": ["claude"],
                "workflow": "code-review",
            },
            {
                "name": "docs-writing",
                "description": "Documentation tasks",
                "patterns": ["doc", "readme"],
                "primary": "claude",
                "reviewers": ["gemini"],
                "workflow": "docs-review",
            },
        ],
    }
    config.workflows = {
        "design-review": {
            "description": "Design review workflow",
            "phases": [
                {"agent": "gemini", "action": "design", "output": "mockup"},
                {"agent": "claude", "action": "review", "output": "feedback"},
            ],
        },
        "code-review": {
            "description": "Code review workflow",
            "phases": [
                {"agent": "codex", "action": "implement", "output": "code"},
                {"agent": "claude", "action": "review", "output": "feedback"},
            ],
        },
        "docs-review": {
            "description": "Docs workflow",
            "phases": [
                {"agent": "claude", "action": "draft", "output": "document"},
                {"agent": "gemini", "action": "polish", "output": "clarity improvements"},
            ],
        },
    }
    return config


def _mock_profile(monkeypatch, *, categories: list[str]) -> None:
    monkeypatch.setattr(
        "ai_collab.core.profiler.ProjectProfiler.detect",
        lambda self: ProjectProfile(root="/tmp/workspace", categories=categories, signals={}),
    )


def test_detect_prefers_profile_mapping_over_task_keywords(config, monkeypatch):
    """Detector should route by profile mapping instead of raw keyword pattern matches."""
    _mock_profile(monkeypatch, categories=["docs-text"])
    config.auto_collaboration["profile_trigger_map"] = {
        "docs-text": {"default": "docs-writing", "implementation": "docs-writing"}
    }
    detector = CollaborationDetector(config)
    result = detector.detect("Create an HTML mockup", "claude")

    assert result.need_collaboration is True
    assert result.trigger == "docs-writing"
    assert result.primary == "claude"
    assert "gemini" in result.reviewers
    assert result.workflow_name == "docs-review"
    assert result.matched_patterns == []


def test_empty_task_still_builds_multi_agent_plan_from_config(config, monkeypatch):
    """Empty task should use configured routing defaults and still produce multi-agent orchestration."""
    _mock_profile(monkeypatch, categories=["superapp-fullstack"])
    config.auto_collaboration["assignment_map"] = {
        "discover": {"agent": "gemini", "profile": "powerful"},
        "define": {"agent": "claude", "profile": "default"},
        "develop": {"agent": "codex", "profile": "medium"},
        "deliver": {"agent": "claude", "profile": "default"},
    }
    config.auto_collaboration["profile_trigger_map"] = {
        "superapp-fullstack": {
            "default": "fullstack-superapp",
            "implementation": "fullstack-superapp",
        }
    }
    config.auto_collaboration["triggers"].append(
        {
            "name": "fullstack-superapp",
            "description": "Fullstack development",
            "patterns": ["fullstack"],
            "primary": "codex",
            "reviewers": ["claude", "gemini"],
            "workflow": "code-review",
        }
    )
    detector = CollaborationDetector(config)
    result = detector.detect("", "codex")

    assert result.need_collaboration is True
    assert result.execution_mode == "multi-agent"
    roles = {item["role"] for item in result.orchestration_plan}
    assert "ecosystem-research" in roles
    assert "tech-selection" in roles
    assert "implementation" in roles
    assert "quality-review" in roles


def test_detect_implementation(config, monkeypatch):
    """Implementation intent should still map to implementation trigger via planner-derived intent."""
    _mock_profile(monkeypatch, categories=["systems-tooling"])
    detector = CollaborationDetector(config)
    result = detector.detect("Implement user authentication feature", "claude")

    assert result.need_collaboration is True
    assert result.trigger == "implementation"
    assert result.primary == "codex"
    assert "claude" in result.reviewers
    assert result.workflow_name == "code-review"


def test_no_collaboration_when_only_one_provider_enabled(config, monkeypatch):
    """Collaboration should be disabled when planner can only select a single enabled provider."""
    _mock_profile(monkeypatch, categories=["systems-tooling"])
    config.providers["claude"].enabled = False
    config.providers["gemini"].enabled = False
    detector = CollaborationDetector(config)
    result = detector.detect("Simple code review", "claude")

    assert result.need_collaboration is False
    assert result.execution_mode == "single-agent"


def test_collaboration_disabled(config):
    """Test when collaboration is disabled."""
    config.auto_collaboration["enabled"] = False
    detector = CollaborationDetector(config)
    result = detector.detect("Create HTML mockup", "claude")

    assert result.need_collaboration is False


def test_legacy_auto_orchestration_key_is_still_supported(config):
    """Legacy key auto_orchestration_enabled should continue to work."""
    config.auto_collaboration = {
        "auto_orchestration_enabled": True,
        "consensus_threshold": 0.75,
        "triggers": config.auto_collaboration["triggers"],
    }
    detector = CollaborationDetector(config)

    result = detector.detect("Create an HTML mockup", "claude")

    assert result.need_collaboration is True
    assert result.trigger == "implementation"


def test_detect_fullstack_from_profile_mapping_without_keyword_match(config, monkeypatch):
    """Planner should infer fullstack flow from project profile mapping without relying on task keywords."""
    _mock_profile(monkeypatch, categories=["superapp-fullstack"])
    config.auto_collaboration["profile_trigger_map"] = {
        "superapp-fullstack": {
            "default": "fullstack-superapp",
            "implementation": "fullstack-superapp",
        }
    }
    config.auto_collaboration["triggers"].append(
        {
            "name": "fullstack-superapp",
            "description": "Fullstack development",
            "patterns": ["superapp", "fullstack"],
            "primary": "codex",
            "reviewers": ["claude", "gemini"],
            "workflow": "full-stack",
        }
    )
    config.workflows["full-stack"] = {
        "description": "Full-stack workflow",
        "phases": [
            {"agent": "claude", "action": "plan", "output": "architecture notes"},
            {"agent": "gemini", "action": "design-frontend", "output": "ui draft"},
            {"agent": "codex", "action": "implement-core", "output": "api and ui"},
            {"agent": "claude", "action": "review-gate", "output": "quality report"},
        ],
    }
    detector = CollaborationDetector(config)

    task = "实现一个极小的待办功能"
    result = detector.detect(task, "codex")

    assert result.need_collaboration is True
    assert result.trigger == "fullstack-superapp"
    assert result.workflow_name == "full-stack"
    assert len(result.orchestration_plan) >= 3
    roles = {item["role"] for item in result.orchestration_plan}
    assert "frontend-build" in roles
    assert "backend-build" in roles
    assert "quality-review" in roles


def test_generate_prompt(config, monkeypatch):
    """Test generating collaboration prompt."""
    _mock_profile(monkeypatch, categories=["systems-tooling"])
    detector = CollaborationDetector(config)
    result = detector.detect("Implement backend endpoint", "claude")

    prompt = detector.generate_prompt("Implement backend endpoint", result, "claude")

    assert "Multi-AI Collaboration" in prompt
    assert "implementation" in prompt
    assert "codex" in prompt
    assert "claude" in prompt
