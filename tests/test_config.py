"""Tests for configuration management."""

import json
import tempfile
from pathlib import Path

import pytest

from ai_collab.core.config import (
    RECOMMENDED_INTENT_PREFERENCES,
    Config,
    ProviderConfig,
    QualityGateConfig,
    resolve_collaboration_role_leads,
)


def test_create_default_config():
    """Test creating default configuration."""
    config = Config.create_default()

    assert config.version == "1.0"
    assert config.ui_language in {"en-US", "zh-CN"}
    assert config.current_controller == "claude"
    assert config.delegation_strategy == "auto"
    assert len(config.providers) == 3
    assert config.quality_gate.enabled is True
    assert config.quality_gate.threshold == 75


def test_provider_config():
    """Test provider configuration."""
    provider = ProviderConfig(
        cli="claude",
        enabled=True,
        timeout=120,
        strengths=["reasoning", "code-review"],
    )

    assert provider.cli == "claude"
    assert provider.enabled is True
    assert provider.timeout == 120
    assert "reasoning" in provider.strengths


def test_quality_gate_config():
    """Test quality gate configuration."""
    gate = QualityGateConfig(enabled=True, threshold=80)

    assert gate.enabled is True
    assert gate.threshold == 80


def test_config_save_and_load(tmp_path):
    """Test saving and loading configuration."""
    # Create config with temporary directory
    config = Config.create_default()

    # Mock config directory
    original_get_config_dir = Config.get_config_dir
    Config.get_config_dir = classmethod(lambda cls: tmp_path)

    try:
        # Save config
        config.save()

        # Check files exist
        config_file = tmp_path / "config.json"
        assert config_file.exists()

        # Load config
        loaded_config = Config.load()

        assert loaded_config.version == config.version
        assert loaded_config.current_controller == config.current_controller
        assert len(loaded_config.providers) == len(config.providers)

    finally:
        # Restore original method
        Config.get_config_dir = original_get_config_dir


def test_config_load_strips_legacy_workflow_sections(tmp_path):
    """Loading config should drop deprecated workflow storage and rewrite clean JSON."""
    config = Config.create_default()
    original_get_config_dir = Config.get_config_dir
    Config.get_config_dir = classmethod(lambda cls: tmp_path)

    try:
        data = config.model_dump()
        data["workflows"] = {
            "old-flow": {
                "description": "Deprecated workflow",
                "phases": [{"agent": "claude", "action": "review", "output": "notes"}],
            }
        }
        (tmp_path / "config.json").write_text(json.dumps(data), encoding="utf-8")
        (tmp_path / "workflows.json").write_text("{}", encoding="utf-8")

        loaded = Config.load()

        assert not hasattr(loaded, "workflows")
        persisted = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert "workflows" not in persisted
        assert (tmp_path / "workflows.json").exists()
    finally:
        Config.get_config_dir = original_get_config_dir


def test_apply_template_defaults_migrates_model_ids():
    """Template merge should migrate legacy model aliases to strict IDs."""
    data = {
        "version": "1.1",
        "ui_language": "zh-CN",
        "current_controller": "codex",
        "providers": {
            "claude": {
                "cli": "claude",
                "enabled": True,
                "timeout": 120,
                "strengths": [],
                "models": {
                    "default": "sonnet-4.6",
                    "cost_effective": {"model": "haiku-4.5", "flag": "--model haiku-4.5"},
                    "powerful": {"model": "opus-4.6", "flag": "--model opus-4.6"},
                },
                "model_selection": "default",
            },
            "codex": {
                "cli": "codex exec --model gpt-5.4",
                "enabled": True,
                "timeout": 300,
                "strengths": [],
                "models": {},
                "model_selection": "default",
            },
            "gemini": {
                "cli": "gemini -o text --approval-mode yolo",
                "enabled": True,
                "timeout": 600,
                "strengths": [],
                "models": {
                    "auto_route_default": True,
                    "cost_effective": {"model": "gemini-3-flash-preview"},
                    "powerful": {"model": "gemini-3.1-pro-preview"},
                },
                "model_selection": "default",
            },
        },
        "delegation_strategy": "auto",
        "quality_gate": {"enabled": True, "threshold": 75},
        "auto_collaboration": {"enabled": True, "auto_orchestration_enabled": True, "triggers": []},
    }

    merged, changed = Config._apply_template_defaults(data)

    assert changed is True
    assert merged["providers"]["claude"]["models"]["default"] == "claude-sonnet-4-6"
    assert merged["providers"]["claude"]["models"]["cost_effective"]["model"] == "claude-haiku-4-5"
    assert merged["providers"]["claude"]["models"]["powerful"]["model"] == "claude-opus-4-6"
    assert merged["providers"]["gemini"]["model_selection"] == "powerful"
    assert merged["providers"]["gemini"]["models"]["auto_route_default"] is False



def test_create_default_config_includes_routing_preferences():
    config = Config.create_default()

    assert config.routing["mode"] == "recommended"
    assert config.routing["cost_bias"] == "balanced"
    assert config.routing["intent_preferences"]["implementation"][0] == "codex"
    assert config.auto_collaboration["preset"] == "auto-route"
    assert config.auto_collaboration["default_session_preset"] == "auto"
    assert config.auto_collaboration["workflow_engine"] == "v2"


def test_recommended_routing_aligns_with_product_role_split():
    assert RECOMMENDED_INTENT_PREFERENCES["architecture"][0] == "gemini"
    assert RECOMMENDED_INTENT_PREFERENCES["implementation"][0] == "codex"
    assert RECOMMENDED_INTENT_PREFERENCES["testing"][0] == "claude"

    leads = resolve_collaboration_role_leads(Config.create_default())

    assert leads["research"] == "gemini"
    assert leads["architecture"] == "gemini"
    assert leads["implementation"] == "codex"
    assert leads["testing"] == "claude"


def test_create_default_config_includes_economics_preferences():
    config = Config.create_default()

    assert config.economics["pricing_mode"] == "disabled"
    assert config.economics["providers"]["codex"]["billing_mode"] == "unconfigured"
    assert config.economics["providers"]["claude"]["billing_mode"] == "unconfigured"
    assert config.economics["providers"]["gemini"]["billing_mode"] == "unconfigured"


def test_apply_template_defaults_adds_economics_section():
    data = {
        "version": "1.1",
        "ui_language": "zh-CN",
        "current_controller": "codex",
        "providers": {
            "claude": {"cli": "claude", "enabled": True, "timeout": 120, "strengths": [], "models": {}, "model_selection": "default"},
            "codex": {"cli": "codex exec --model gpt-5.4", "enabled": True, "timeout": 300, "strengths": [], "models": {}, "model_selection": "default"},
            "gemini": {"cli": "gemini -o text --approval-mode yolo", "enabled": True, "timeout": 600, "strengths": [], "models": {}, "model_selection": "powerful"},
        },
        "delegation_strategy": "auto",
        "quality_gate": {"enabled": True, "threshold": 75},
        "routing": {"mode": "recommended", "cost_bias": "balanced", "intent_preferences": {}},
        "auto_collaboration": {"enabled": True, "auto_orchestration_enabled": True, "triggers": []},
    }

    merged, changed = Config._apply_template_defaults(data)

    assert changed is True
    assert merged["economics"]["pricing_mode"] == "disabled"
    assert merged["economics"]["providers"]["codex"]["billing_mode"] == "unconfigured"
    assert merged["economics"]["providers"]["claude"]["quota_window"] == "none"


def test_apply_template_defaults_upgrades_legacy_trigger_workflow_field() -> None:
    data = {
        "version": "1.1",
        "ui_language": "zh-CN",
        "current_controller": "codex",
        "providers": {
            "claude": {"cli": "claude", "enabled": True, "timeout": 120, "strengths": [], "models": {}, "model_selection": "default"},
            "codex": {"cli": "codex exec --model gpt-5.4", "enabled": True, "timeout": 300, "strengths": [], "models": {}, "model_selection": "default"},
            "gemini": {"cli": "gemini -o text --approval-mode yolo", "enabled": True, "timeout": 600, "strengths": [], "models": {}, "model_selection": "powerful"},
        },
        "delegation_strategy": "auto",
        "quality_gate": {"enabled": True, "threshold": 75},
        "routing": {"mode": "recommended", "cost_bias": "balanced", "intent_preferences": {}},
        "auto_collaboration": {
            "enabled": True,
            "auto_orchestration_enabled": True,
            "triggers": [
                {
                    "name": "docs-writing",
                    "description": "Documentation tasks",
                    "patterns": ["doc", "readme"],
                    "primary": "claude",
                    "reviewers": ["gemini"],
                    "workflow": "docs-review",
                }
            ],
        },
    }

    merged, changed = Config._apply_template_defaults(data)
    trigger = merged["auto_collaboration"]["triggers"][0]

    assert changed is True
    assert "workflow" not in trigger
    assert "legacy_workflow" not in trigger
    assert trigger["session_preset"] == "document-first"
    assert trigger["workflow_blueprint"] == "document-loop"


def test_apply_template_defaults_does_not_map_deprecated_workflow_name_for_unknown_trigger() -> None:
    data = {
        "version": "1.1",
        "ui_language": "zh-CN",
        "current_controller": "codex",
        "providers": {
            "claude": {"cli": "claude", "enabled": True, "timeout": 120, "strengths": [], "models": {}, "model_selection": "default"},
            "codex": {"cli": "codex exec --model gpt-5.4", "enabled": True, "timeout": 300, "strengths": [], "models": {}, "model_selection": "default"},
            "gemini": {"cli": "gemini -o text --approval-mode yolo", "enabled": True, "timeout": 600, "strengths": [], "models": {}, "model_selection": "powerful"},
        },
        "delegation_strategy": "auto",
        "quality_gate": {"enabled": True, "threshold": 75},
        "routing": {"mode": "recommended", "cost_bias": "balanced", "intent_preferences": {}},
        "auto_collaboration": {
            "enabled": True,
            "auto_orchestration_enabled": True,
            "triggers": [
                {
                    "name": "custom-review",
                    "description": "Custom trigger",
                    "patterns": ["review"],
                    "primary": "claude",
                    "reviewers": ["codex"],
                    "workflow": "docs-review",
                }
            ],
        },
    }

    merged, changed = Config._apply_template_defaults(data)
    trigger = merged["auto_collaboration"]["triggers"][0]

    assert changed is True
    assert "workflow" not in trigger
    assert "legacy_workflow" not in trigger
    assert "workflow_blueprint" not in trigger


def test_create_default_config_includes_app_and_billing_strategy_defaults():
    config = Config.create_default()

    assert config.application["auto_check_updates"] is True
    assert config.economics["quota_strategy"] == "balanced"
    assert config.economics["cross_provider_fallback"] == "same-provider-first"
    assert "xhigh" in config.providers["codex"].models["enabled_profiles"]
    assert config.providers["codex"].models["default_model"] == "gpt-5.4"
    assert config.providers["codex"].models["thinking_levels"]["high"]["model"] == "gpt-5.5"
