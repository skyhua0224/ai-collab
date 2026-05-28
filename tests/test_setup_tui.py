from __future__ import annotations

import asyncio

import ai_collab.cli as cli
from ai_collab.core.config import Config
from ai_collab.tui.setup import (
    SetupFormData,
    SetupTextualApp,
    apply_setup_form,
    build_setup_summary,
    resolve_setup_defaults,
    resolve_setup_step_titles,
)


def test_resolve_setup_defaults_reads_current_config() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    config.entry_surface = "guided"
    config.runtime_mode = "tmux"
    config.providers["claude"].enabled = False

    defaults = resolve_setup_defaults(config)

    assert defaults.ui_language == "zh-CN"
    assert defaults.controller == "codex"
    assert defaults.entry_surface == "guided"
    assert defaults.runtime_mode == "tmux"
    assert defaults.providers["codex"] is True
    assert defaults.providers["claude"] is False


def test_apply_setup_form_updates_core_config_fields() -> None:
    config = Config.create_default()
    form = SetupFormData(
        ui_language="zh-CN",
        controller="gemini",
        entry_surface="guided",
        runtime_mode="tmux",
        providers={"codex": True, "claude": False, "gemini": True},
        auto_collaboration_enabled=False,
    )

    apply_setup_form(config, form)

    assert config.ui_language == "zh-CN"
    assert config.current_controller == "gemini"
    assert config.entry_surface == "guided"
    assert config.runtime_mode == "tmux"
    assert config.providers["codex"].enabled is True
    assert config.providers["claude"].enabled is False
    assert config.providers["gemini"].enabled is True
    assert config.auto_collaboration["enabled"] is False
    assert config.auto_collaboration["auto_orchestration_enabled"] is False


def test_init_tui_mode_keeps_setup_tui(monkeypatch) -> None:
    config = Config.create_default()
    saved: dict[str, bool] = {"called": False}
    setup_calls: list[str] = []

    monkeypatch.setattr(cli.Config, "initialize", classmethod(lambda cls: config))
    monkeypatch.setattr(cli.Config, "save", lambda self: saved.__setitem__("called", True))
    monkeypatch.setattr(cli.sys, "stdin", type("_TTY", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(cli, "_run_init_setup_prompt", lambda cfg: (_ for _ in ()).throw(AssertionError("prompt init should not run")), raising=False)
    monkeypatch.setattr(cli, "_run_init_setup_raw", lambda cfg: (_ for _ in ()).throw(AssertionError("raw init should not run")), raising=False)
    monkeypatch.setattr(cli, "_run_init_setup_tui", lambda cfg: setup_calls.append(cfg.current_controller))

    cli.init.callback.__wrapped__(None, force=True, interactive=True, ui_mode="tui", auto_install_deps=True)

    assert setup_calls == ["claude"]
    assert saved["called"] is True


def test_resolve_setup_step_titles_is_sequential() -> None:
    assert resolve_setup_step_titles("en-US") == [
        "Language",
        "Controller",
        "Providers",
        "Runtime",
        "Entry",
        "Collaboration",
        "Review",
    ]
    assert resolve_setup_step_titles("zh-CN") == ["语言", "主控", "提供方", "运行方式", "入口", "协作", "确认"]


def test_build_setup_summary_reflects_current_choices() -> None:
    form = SetupFormData(
        ui_language="zh-CN",
        controller="gemini",
        entry_surface="guided",
        runtime_mode="tmux",
        providers={"codex": True, "claude": False, "gemini": True},
        auto_collaboration_enabled=True,
    )

    summary = build_setup_summary(form)

    assert "Language: 中文 (zh-CN)" in summary
    assert "Controller: Gemini" in summary
    assert "Entry: Guided launcher" in summary
    assert "Runtime: tmux runtime" in summary
    assert "Providers: Codex, Gemini" in summary
    assert "Auto collaboration: Enabled" in summary


def test_setup_tui_enter_advances_from_language_step() -> None:
    from textual.widgets import ContentSwitcher, OptionList, Static

    async def _run() -> None:
        app = SetupTextualApp(resolve_setup_defaults(Config.create_default()))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.current_step == 0
            assert app.focused is not None
            assert app.focused.id == "language-options"

            await pilot.press("down", "enter")
            await pilot.pause()

            assert app.current_step == 1
            assert app.query_one("#setup-steps", ContentSwitcher).current == "step-controller"
            assert app.focused is not None
            assert app.focused.id == "controller-options"
            summary = str(app.query_one("#summary", Static).render())
            assert "中文 (zh-CN)" in summary
            language_options = app.query_one("#language-options", OptionList)
            assert language_options.highlighted == 1

    asyncio.run(_run())


def test_setup_tui_back_key_returns_to_previous_step() -> None:
    async def _run() -> None:
        app = SetupTextualApp(resolve_setup_defaults(Config.create_default()))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()
            assert app.current_step == 1

            await pilot.press("b")
            await pilot.pause()
            assert app.current_step == 0
            assert app.focused is not None
            assert app.focused.id == "language-options"

    asyncio.run(_run())


def test_setup_tui_backup_profile_waits_for_backup_choice() -> None:
    async def _run() -> None:
        app = SetupTextualApp(resolve_setup_defaults(Config.create_default()))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.current_step == 2
            assert app.focused is not None
            assert app.focused.id == "providers-profile"

            await pilot.press("up", "enter")
            await pilot.pause()
            assert app.current_step == 2
            assert app.focused is not None
            assert app.focused.id == "backup-provider"

            await pilot.press("enter")
            await pilot.pause()
            assert app.current_step == 3
            assert app.focused is not None
            assert app.focused.id == "runtime-options"

    asyncio.run(_run())
