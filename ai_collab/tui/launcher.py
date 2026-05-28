"""Formal launcher TUI entrypoint for ai-collab."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ai_collab.core.config import Config
from ai_collab.tui.launcher_service import run_launcher_flow
from ai_collab.tui.launcher_textual import run_textual_launcher_tui
from ai_collab.ux_lab_v3 import UxLabV3Result


def run_launcher_tui(
    *,
    config: Config,
    cwd: Path,
    workspace: Optional[Path] = None,
    controller: Optional[str] = None,
    task: Optional[str] = None,
    task_file: Optional[Path] = None,
    skip_review: bool = False,
    planner_mode: str = "live",
    output_bundle: Optional[Path] = None,
    non_interactive: bool = False,
) -> UxLabV3Result:
    """Run the formal launcher flow.

    The current implementation delegates to the V3 prototype internals while
    establishing a stable public module boundary for the real product TUI.
    """
    if non_interactive:
        return run_launcher_flow(
            config=config,
            cwd=cwd,
            workspace=workspace,
            controller=controller,
            task=task,
            task_file=task_file,
            skip_review=skip_review,
            planner_mode=planner_mode,
            output_bundle=output_bundle,
        )
    return run_textual_launcher_tui(
        config=config,
        cwd=cwd,
        workspace=workspace,
        controller=controller,
        task=task,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
    )
