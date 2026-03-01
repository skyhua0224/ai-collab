"""Tests for configuration management."""

import json
import tempfile
from pathlib import Path

import pytest

from ai_collab.core.config import Config, ProviderConfig, QualityGateConfig


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


def test_config_with_workflows(tmp_path):
    """Test configuration with workflows."""
    config = Config.create_default()
    config.workflows = {
        "test-workflow": {
            "description": "Test workflow",
            "phases": [
                {"agent": "claude", "action": "test", "output": "result"}
            ],
        }
    }

    # Mock config directory
    original_get_config_dir = Config.get_config_dir
    Config.get_config_dir = classmethod(lambda cls: tmp_path)

    try:
        # Save config
        config.save()

        # Check workflows file exists
        workflows_file = tmp_path / "workflows.json"
        assert workflows_file.exists()

        # Load config
        loaded_config = Config.load()

        assert "test-workflow" in loaded_config.workflows
        assert loaded_config.workflows["test-workflow"]["description"] == "Test workflow"

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
                "cli": "codex exec --model gpt-5.3-codex",
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
        "workflows": {},
        "auto_collaboration": {"enabled": True, "auto_orchestration_enabled": True, "triggers": []},
    }

    merged, changed = Config._apply_template_defaults(data)

    assert changed is True
    assert merged["providers"]["claude"]["models"]["default"] == "claude-sonnet-4-6"
    assert merged["providers"]["claude"]["models"]["cost_effective"]["model"] == "claude-haiku-4-5"
    assert merged["providers"]["claude"]["models"]["powerful"]["model"] == "claude-opus-4-6"
    assert merged["providers"]["gemini"]["model_selection"] == "powerful"
    assert merged["providers"]["gemini"]["models"]["auto_route_default"] is False
