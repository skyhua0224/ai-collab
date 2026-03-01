"""Tests for model selection."""

import pytest

from ai_collab.core.config import Config
from ai_collab.core.selector import ModelSelector


@pytest.fixture
def config():
    """Create test configuration."""
    config = Config.create_default()

    # Add model configurations
    config.providers["codex"].models = {
        "enabled_profiles": ["low", "medium", "high"],
        "thinking_levels": {
            "low": {"flag": "--thinking low", "description": "Simple tasks"},
            "medium": {"flag": "--thinking medium", "description": "Medium tasks"},
            "high": {"flag": "--thinking high", "description": "Complex tasks"},
        },
        "default_thinking": "medium",
    }

    config.providers["gemini"].models = {
        "auto_route_default": True,
        "enabled_profiles": ["auto", "cost_effective", "powerful"],
        "cost_effective": {
            "model": "gemini-3-flash-preview",
            "flag": "--model gemini-3-flash-preview",
            "description": "Fast",
        },
        "powerful": {
            "model": "gemini-3.1-pro-preview",
            "flag": "--model gemini-3.1-pro-preview",
            "description": "High quality",
        },
    }

    config.providers["claude"].models = {
        "default": "sonnet-4.6",
        "enabled_profiles": ["default", "cost_effective", "powerful"],
        "cost_effective": {
            "model": "sonnet-4.6",
            "flag": "--model sonnet-4.6",
            "description": "Cost-effective",
        },
        "powerful": {
            "model": "opus-4.6",
            "flag": "--model opus-4.6",
            "description": "Powerful",
        },
    }
    config.providers["claude"].model_selection = "default"
    config.providers["gemini"].model_selection = "default"

    return config


def test_select_codex_default(config):
    """Test selecting Codex model with default complexity."""
    selector = ModelSelector(config)
    result = selector.select_model("codex", "Implement feature", "default")

    assert result.model == "gpt-5.3-codex"
    assert result.thinking == "medium"
    assert "--thinking medium" in result.cli


def test_select_codex_low(config):
    """Test selecting Codex model with low complexity."""
    selector = ModelSelector(config)
    result = selector.select_model("codex", "Format code", "low")

    assert result.model == "gpt-5.3-codex"
    assert result.thinking == "low"
    assert "--thinking low" in result.cli


def test_select_codex_respects_enabled_profiles(config):
    """Test Codex falls back to enabled thinking levels."""
    config.providers["codex"].models["enabled_profiles"] = ["low"]
    config.providers["codex"].models["default_thinking"] = "high"
    selector = ModelSelector(config)
    result = selector.select_model("codex", "Implement feature", "default")

    assert result.thinking == "low"
    assert "--thinking low" in result.cli


def test_select_gemini_powerful(config):
    """Test selecting Gemini powerful model."""
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Complex UI design", "high")

    assert result.model == "gemini-3.1-pro-preview"
    assert "--model gemini-3.1-pro-preview" in result.cli


def test_select_gemini_cost_effective(config):
    """Test selecting Gemini cost-effective model."""
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Simple design", "low")

    assert result.model == "gemini-3-flash-preview"
    assert "--model gemini-3-flash-preview" in result.cli


def test_select_gemini_default_auto_route(config):
    """Test Gemini default auto-routing when enabled."""
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Any task", "default")

    assert result.model == "gemini-cli-auto"
    assert result.cli == "gemini -o text --approval-mode yolo"


def test_select_gemini_default_with_explicit_mode(config):
    """Test Gemini default selection uses configured mode when auto-route disabled."""
    config.providers["gemini"].models["auto_route_default"] = False
    config.providers["gemini"].model_selection = "powerful"
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Complex UI design", "default")

    assert result.model == "gemini-3.1-pro-preview"
    assert "--model gemini-3.1-pro-preview" in result.cli


def test_select_gemini_default_prefers_powerful_when_auto_disabled(config):
    """When auto-route is disabled and no explicit profile is set, default to powerful."""
    config.providers["gemini"].models["auto_route_default"] = False
    config.providers["gemini"].model_selection = "default"
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Any task", "default")

    assert result.model == "gemini-3.1-pro-preview"
    assert "--model gemini-3.1-pro-preview" in result.cli


def test_select_gemini_enabled_profiles_disable_auto(config):
    """Test Gemini uses enabled pinned profile when auto is not enabled."""
    config.providers["gemini"].models["enabled_profiles"] = ["cost_effective"]
    config.providers["gemini"].models["auto_route_default"] = True
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Any task", "default")

    assert result.model == "gemini-3-flash-preview"
    assert "--model gemini-3-flash-preview" in result.cli


def test_select_claude_default(config):
    """Test selecting Claude default model."""
    selector = ModelSelector(config)
    result = selector.select_model("claude", "Code review", "default")

    assert result.model == "sonnet-4.6"


def test_select_claude_cost_effective_mode(config):
    """Test Claude selection mode applies configured model profile."""
    config.providers["claude"].model_selection = "cost_effective"
    selector = ModelSelector(config)
    result = selector.select_model("claude", "Code review", "default")

    assert result.model == "sonnet-4.6"
    assert "--model sonnet-4.6" in result.cli


def test_select_claude_respects_enabled_profiles(config):
    """Test Claude falls back to enabled profile when configured mode is disabled."""
    config.providers["claude"].model_selection = "powerful"
    config.providers["claude"].models["enabled_profiles"] = ["cost_effective"]
    selector = ModelSelector(config)
    result = selector.select_model("claude", "Code review", "default")

    assert result.model == "sonnet-4.6"
    assert "--model sonnet-4.6" in result.cli


def test_select_claude_catalog_profile(config):
    """Test Claude supports dynamically discovered catalog model profiles."""
    config.providers["claude"].models["catalog_profiles"] = {
        "catalog_claude_sonnet_4_7": {
            "model": "claude-sonnet-4.7",
            "flag": "--model claude-sonnet-4.7",
            "description": "catalog model",
        }
    }
    config.providers["claude"].models["enabled_profiles"] = ["catalog_claude_sonnet_4_7"]
    config.providers["claude"].model_selection = "catalog_claude_sonnet_4_7"
    selector = ModelSelector(config)
    result = selector.select_model("claude", "Code review", "default")

    assert result.model == "claude-sonnet-4.7"
    assert "--model claude-sonnet-4.7" in result.cli


def test_select_gemini_catalog_profile(config):
    """Test Gemini supports dynamically discovered catalog model profiles."""
    config.providers["gemini"].models["catalog_profiles"] = {
        "catalog_gemini_2_5_pro": {
            "model": "gemini-2.5-pro",
            "flag": "--model gemini-2.5-pro",
            "description": "catalog model",
        }
    }
    config.providers["gemini"].models["enabled_profiles"] = ["catalog_gemini_2_5_pro"]
    config.providers["gemini"].model_selection = "catalog_gemini_2_5_pro"
    config.providers["gemini"].models["auto_route_default"] = False
    selector = ModelSelector(config)
    result = selector.select_model("gemini", "Any task", "default")

    assert result.model == "gemini-2.5-pro"
    assert "--model gemini-2.5-pro" in result.cli


def test_unknown_provider(config):
    """Test selecting unknown provider."""
    selector = ModelSelector(config)

    with pytest.raises(ValueError, match="Unknown provider"):
        selector.select_model("unknown", "Task", "default")
