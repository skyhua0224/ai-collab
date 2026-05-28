"""Formal single-page Textual launcher UI for ai-collab."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Select, Static, TextArea

from ai_collab.core.config import Config
from ai_collab.tui.launcher_service import run_launcher_flow
from ai_collab.ux_lab_v3 import UxLabV3Result


class LauncherTextualApp(App[Optional[UxLabV3Result]]):
    BINDINGS = [
        Binding("ctrl+p", "plan", "Plan"),
        Binding("f5", "plan", "Plan"),
        Binding("ctrl+l", "launch", "Launch"),
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    Screen {
      layout: vertical;
    }

    #launcher-body {
      padding: 1 2;
    }

    .muted {
      color: $text-muted;
    }

    Input, Select {
      margin: 1 0;
    }

    #task {
      height: 12;
      margin: 1 0;
    }

    #status {
      margin-top: 1;
    }

    #plan-preview {
      margin-top: 1;
      min-height: 10;
      border: round $primary;
      padding: 1;
    }
    """

    def __init__(
        self,
        *,
        config: Config,
        cwd: Path,
        workspace: Path,
        controller: str,
        task: str,
        planner_mode: str,
        output_bundle: Optional[Path],
    ) -> None:
        super().__init__()
        self.config_obj = config
        self.cwd = cwd
        self.initial_workspace = workspace
        self.initial_controller = controller
        self.initial_task = task
        self.initial_planner_mode = planner_mode
        self.output_bundle = output_bundle
        self.result: Optional[UxLabV3Result] = None
        self.plan_result: Optional[UxLabV3Result] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="launcher-body"):
            yield Static("ai-collab Launcher")
            yield Static("Single-page launcher. Ctrl+P plans, Ctrl+L exports, Esc cancels.", classes="muted")
            yield Static("Workspace", classes="muted")
            yield Input(value=str(self.initial_workspace), id="workspace")
            yield Static("Controller", classes="muted")
            yield Select(
                options=[("Codex", "codex"), ("Claude", "claude"), ("Gemini", "gemini")],
                value=self.initial_controller,
                allow_blank=False,
                id="controller",
            )
            yield Static("Planner mode", classes="muted")
            yield Select(
                options=[("live", "live"), ("mock", "mock")],
                value=self.initial_planner_mode,
                allow_blank=False,
                id="planner-mode",
            )
            yield Static("Task", classes="muted")
            yield TextArea(self.initial_task, id="task")
            yield Static("Ready.", id="status")
            yield Static("No plan yet.", id="plan-preview")
        yield Footer()

    def _collect_inputs(self) -> dict[str, object]:
        workspace = Path(self.query_one("#workspace", Input).value or str(self.cwd)).expanduser()
        controller = str(self.query_one("#controller", Select).value or self.initial_controller)
        planner_mode = str(self.query_one("#planner-mode", Select).value or self.initial_planner_mode)
        task = self.query_one("#task", TextArea).text.strip()
        return {
            "workspace": workspace,
            "controller": controller,
            "planner_mode": planner_mode,
            "task": task,
        }

    def _render_plan_preview(self, result: UxLabV3Result) -> str:
        if not result.plan:
            return result.error_message or "No plan returned."
        lines = []
        for item in result.plan:
            lines.append(f"{item.sx}  {item.agent}  {item.eta_minutes}m  {item.title}")
            lines.append(f"    done_when: {item.done_when}")
        return "\n".join(lines)

    def action_plan(self) -> None:
        values = self._collect_inputs()
        result = run_launcher_flow(
            config=self.config_obj,
            cwd=self.cwd,
            workspace=values["workspace"],
            controller=values["controller"],
            task=values["task"],
            task_file=None,
            skip_review=False,
            planner_mode=str(values["planner_mode"]),
            output_bundle=self.output_bundle,
        )
        self.plan_result = result
        status = self.query_one("#status", Static)
        preview = self.query_one("#plan-preview", Static)
        if result.status == "error":
            status.update(result.error_message or "Planning failed.")
            preview.update(result.error_message or "Planning failed.")
            return
        status.update(f"Plan ready: {len(result.plan)} step(s)")
        preview.update(self._render_plan_preview(result))

    def action_launch(self) -> None:
        values = self._collect_inputs()
        result = run_launcher_flow(
            config=self.config_obj,
            cwd=self.cwd,
            workspace=values["workspace"],
            controller=values["controller"],
            task=values["task"],
            task_file=None,
            skip_review=True,
            planner_mode=str(values["planner_mode"]),
            output_bundle=self.output_bundle,
        )
        self.result = result
        self.exit(result=result)

    def action_cancel(self) -> None:
        self.exit(result=None)


def run_textual_launcher_tui(
    *,
    config: Config,
    cwd: Path,
    workspace: Optional[Path] = None,
    controller: Optional[str] = None,
    task: Optional[str] = None,
    planner_mode: str = "live",
    output_bundle: Optional[Path] = None,
) -> UxLabV3Result:
    app = LauncherTextualApp(
        config=config,
        cwd=cwd,
        workspace=Path(workspace or cwd).expanduser().resolve(),
        controller=str(controller or config.current_controller),
        task=str(task or ""),
        planner_mode=planner_mode,
        output_bundle=output_bundle,
    )
    result = app.run()
    if isinstance(result, UxLabV3Result):
        return result
    return UxLabV3Result(
        status="error",
        workspace=Path(workspace or cwd).expanduser().resolve(),
        controller=str(controller or config.current_controller),
        task=str(task or ""),
        lang=getattr(config, "ui_language", "en-US"),
        planner_mode=planner_mode,
        plan=[],
        error_message="Launcher cancelled",
    )
