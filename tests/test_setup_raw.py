from __future__ import annotations

from io import StringIO

import ai_collab.cli as cli
from ai_collab.core.config import Config
from rich.console import Console

from ai_collab.tui.setup_raw import render_raw_setup_screen, run_setup_raw


def test_init_prefers_raw_setup_for_raw_mode(monkeypatch) -> None:
    config = Config.create_default()
    saved: dict[str, bool] = {"called": False}
    raw_calls: list[str] = []

    monkeypatch.setattr(cli.Config, "initialize", classmethod(lambda cls: config))
    monkeypatch.setattr(cli.Config, "save", lambda self: saved.__setitem__("called", True))
    monkeypatch.setattr(cli.sys, "stdin", type("_TTY", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(cli, "_run_init_setup_raw", lambda cfg: raw_calls.append(cfg.current_controller), raising=False)
    monkeypatch.setattr(cli, "_run_init_setup_tui", lambda cfg: (_ for _ in ()).throw(AssertionError("textual setup should not run")))
    monkeypatch.setattr(cli, "_run_init_wizard", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy text wizard should not run")))

    cli.init.callback.__wrapped__(None, force=True, interactive=True, ui_mode="raw", auto_install_deps=True)

    assert raw_calls == ["claude"]
    assert saved["called"] is True


def test_render_raw_setup_screen_shows_numbered_choices() -> None:
    config = Config.create_default()
    output = render_raw_setup_screen(config, screen_id="language")

    assert "Step 1/7" in output
    assert "1. English (en-US)" in output
    assert "2. 中文 (zh-CN)" in output
    assert "Current draft" in output


def test_run_setup_raw_applies_scripted_answers() -> None:
    config = Config.create_default()
    answers = iter(["2", "3", "2", "1", "2", "2", "2", "1"])
    console = Console(file=StringIO(), force_terminal=False, color_system=None, width=100)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    run_setup_raw(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert config.ui_language == "zh-CN"
    assert config.current_controller == "gemini"
    assert config.providers["gemini"].enabled is True
    assert config.providers["codex"].enabled is True
    assert config.providers["claude"].enabled is False
    assert config.runtime_mode == "direct"
    assert config.entry_surface == "command"
    assert config.auto_collaboration["enabled"] is False
