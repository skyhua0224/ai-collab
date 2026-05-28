from __future__ import annotations

from types import SimpleNamespace

import ai_collab.cli as cli
from ai_collab.core.config import Config
from ai_collab.tui.settings import SettingsFormData, apply_settings_form, resolve_settings_defaults


def test_resolve_settings_defaults_reads_current_config() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "gemini"
    config.entry_surface = "command"
    config.runtime_mode = "direct"
    config.providers["claude"].enabled = False

    form = resolve_settings_defaults(config)

    assert form.ui_language == "zh-CN"
    assert form.controller == "gemini"
    assert form.entry_surface == "command"
    assert form.runtime_mode == "direct"
    assert form.providers["claude"] is False


def test_apply_settings_form_updates_config() -> None:
    config = Config.create_default()
    form = SettingsFormData(
        ui_language="zh-CN",
        controller="codex",
        entry_surface="guided",
        runtime_mode="tmux",
        providers={"codex": True, "claude": True, "gemini": False},
        auto_collaboration_enabled=False,
    )

    apply_settings_form(config, form)

    assert config.ui_language == "zh-CN"
    assert config.current_controller == "codex"
    assert config.entry_surface == "guided"
    assert config.runtime_mode == "tmux"
    assert config.providers["gemini"].enabled is False
    assert config.auto_collaboration["enabled"] is False


def test_settings_command_uses_new_config_prompt(monkeypatch) -> None:
    config = Config.create_default()
    ctx = SimpleNamespace(obj={"config": config})
    called: list[Config] = []

    monkeypatch.setattr("ai_collab.config_prompt.run_config_menu_prompt", lambda cfg: called.append(cfg) or True)

    cli.settings.callback.__wrapped__(ctx)

    assert called == [config]


def test_config_set_get_supports_new_core_fields(capsys, monkeypatch) -> None:
    config = Config.create_default()
    ctx = SimpleNamespace(obj={"config": config})
    monkeypatch.setattr(cli.Config, "save", lambda self: None)

    cli.config.callback.__wrapped__(ctx, action="set", key="current_controller", value="gemini")
    cli.config.callback.__wrapped__(ctx, action="set", key="entry_surface", value="command")
    cli.config.callback.__wrapped__(ctx, action="set", key="runtime_mode", value="direct")
    cli.config.callback.__wrapped__(ctx, action="get", key="current_controller", value=None)
    cli.config.callback.__wrapped__(ctx, action="get", key="entry_surface", value=None)
    cli.config.callback.__wrapped__(ctx, action="get", key="runtime_mode", value=None)

    captured = capsys.readouterr().out
    assert config.current_controller == "gemini"
    assert config.entry_surface == "command"
    assert config.runtime_mode == "direct"
    assert "current_controller: gemini" in captured
    assert "entry_surface: command" in captured
    assert "runtime_mode: direct" in captured
