from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from ai_collab.core.config import Config


def test_prompt_text_falls_back_to_prompt_toolkit_on_unicode_decode(monkeypatch) -> None:
    from ai_collab import entry_prompt

    monkeypatch.setattr(
        entry_prompt.Prompt,
        "ask",
        lambda *args, **kwargs: (_ for _ in ()).throw(UnicodeDecodeError("utf-8", b"\xe2", 0, 1, "boom")),
    )

    captured: dict[str, str] = {}

    def _fake_prompt(message: str, *, default: str = "") -> str:
        captured["message"] = message
        captured["default"] = default
        return "test_game"

    monkeypatch.setattr("prompt_toolkit.prompt", _fake_prompt)

    value = entry_prompt._prompt_text(None, label="路径或关键字", default="/Users/skyhua")

    assert value == "test_game"
    assert "路径或关键字" in captured["message"]
    assert captured["default"] == "/Users/skyhua"


def test_browse_workspace_search_jumps_to_matching_path(monkeypatch, tmp_path) -> None:
    from ai_collab import entry_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    workspace = tmp_path / "test_game"
    workspace.mkdir()

    choices = iter(["3", "1"])
    monkeypatch.setattr(
        entry_prompt,
        "_select_screen",
        lambda *args, **kwargs: next(choices),
    )
    monkeypatch.setattr(
        entry_prompt,
        "_prompt_text",
        lambda *args, **kwargs: str(workspace),
    )

    result, selected = entry_prompt._browse_workspace(
        config=config,
        mode="launch",
        cwd=tmp_path,
        selector_fn=None,
        input_fn=None,
        console_obj=Console(file=StringIO(), force_terminal=False, color_system=None, width=120),
        clear_screen=False,
    )

    assert result == "selected"
    assert selected == workspace.resolve()
