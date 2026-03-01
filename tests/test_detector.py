"""Tests for collaboration detection."""

import pytest

from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationDetector, CollaborationResult


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
    }
    return config


def test_detect_visual_design(config):
    """Test detecting visual design tasks."""
    detector = CollaborationDetector(config)
    result = detector.detect("Create an HTML mockup", "claude")

    assert result.need_collaboration is True
    assert result.trigger == "visual-design"
    assert result.primary == "gemini"
    assert "claude" in result.reviewers
    assert result.workflow_name == "design-review"


def test_detect_implementation(config):
    """Test detecting implementation tasks."""
    detector = CollaborationDetector(config)
    result = detector.detect("Implement user authentication feature", "claude")

    assert result.need_collaboration is True
    assert result.trigger == "implementation"
    assert result.primary == "codex"
    assert "claude" in result.reviewers
    assert result.workflow_name == "code-review"


def test_no_collaboration_needed(config):
    """Test when no collaboration is needed."""
    detector = CollaborationDetector(config)
    result = detector.detect("Simple code review", "claude")

    assert result.need_collaboration is False
    assert result.trigger is None


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
    assert result.trigger == "visual-design"


def test_detect_fullstack_from_capabilities_without_direct_keyword_match(config):
    """Planner should infer fullstack flow from task capabilities, not only raw trigger keywords."""
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

    task = "实现一个极小的待办功能，有前端和后端，后端要保存数据"
    result = detector.detect(task, "codex")

    assert result.need_collaboration is True
    assert result.trigger == "fullstack-superapp"
    assert result.workflow_name == "full-stack"
    assert len(result.orchestration_plan) >= 3
    roles = {item["role"] for item in result.orchestration_plan}
    assert "frontend-build" in roles
    assert "backend-build" in roles
    assert "quality-review" in roles


def test_generate_prompt(config):
    """Test generating collaboration prompt."""
    detector = CollaborationDetector(config)
    result = detector.detect("Create HTML mockup", "claude")

    prompt = detector.generate_prompt("Create HTML mockup", result, "claude")

    assert "Multi-AI Collaboration" in prompt
    assert "visual-design" in prompt
    assert "gemini" in prompt
    assert "claude" in prompt
