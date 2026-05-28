from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import ai_collab.cli as cli
from ai_collab.core.config import Config


def test_launch_command_uses_formal_launcher_module(monkeypatch, tmp_path) -> None:
    config = Config.create_default()
    ctx = SimpleNamespace(obj={"config": config})
    captured: dict[str, object] = {}

    def _fake_run_launcher_tui(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="sent", bundle_path=tmp_path / "bundle.json", plan=[])

    monkeypatch.setattr("ai_collab.tui.launcher.run_launcher_tui", _fake_run_launcher_tui)

    cli.launch.callback.__wrapped__(
        ctx,
        workspace=tmp_path,
        controller="gemini",
        task="Build launcher",
        task_file=None,
        skip_review=True,
        planner_mode="mock",
        output_bundle=tmp_path / "bundle.json",
        non_interactive=True,
    )

    assert captured["config"] is config
    assert captured["cwd"] == Path.cwd()
    assert captured["workspace"] == tmp_path
    assert captured["controller"] == "gemini"
    assert captured["task"] == "Build launcher"
    assert captured["skip_review"] is True
    assert captured["planner_mode"] == "mock"


def test_launch_command_requires_task_in_non_interactive_mode() -> None:
    config = Config.create_default()
    ctx = SimpleNamespace(obj={"config": config})

    try:
        cli.launch.callback.__wrapped__(
            ctx,
            workspace=None,
            controller=None,
            task=None,
            task_file=None,
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
            non_interactive=True,
        )
        raise AssertionError("launch should require task input in non-interactive mode")
    except Exception as exc:
        assert exc.__class__.__name__ == "UsageError"


def test_textual_launcher_uses_single_page_without_tabs_or_buttons() -> None:
    import ai_collab.tui.launcher_textual as launcher_textual
    from textual.widgets import Button, Tabs

    async def _run() -> None:
        app = launcher_textual.LauncherTextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Build a better launcher UI",
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert len(list(app.query(Button))) == 0
            assert len(list(app.query(Tabs))) == 0

    asyncio.run(_run())


def test_textual_launcher_can_plan_in_place(monkeypatch) -> None:
    import ai_collab.tui.launcher_textual as launcher_textual
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result
    from textual.widgets import Static

    def _fake_run_launcher_flow(**kwargs):
        return UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="en-US",
            planner_mode=kwargs["planner_mode"],
            plan=[
                LabPlanItem("S1", "Controller plan", "codex", 8, "Return a plan"),
                LabPlanItem("S2", "Review", "claude", 10, "Check results"),
            ],
            bundle_path=None,
        )

    monkeypatch.setattr(launcher_textual, "run_launcher_flow", _fake_run_launcher_flow)

    async def _run() -> None:
        app = launcher_textual.LauncherTextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Build a better launcher UI",
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_plan()
            await pilot.pause()
            preview = app.query_one("#plan-preview", Static)
            rendered = str(preview.render())
            assert "S1" in rendered
            assert "Controller plan" in rendered
            assert "S2" in rendered

    asyncio.run(_run())
