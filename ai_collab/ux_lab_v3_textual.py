"""
Textual-based interactive UX lab V3.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, DirectoryTree, Footer, Input, OptionList, Static, Tab, Tabs, TextArea, Tree

from ai_collab.core.config import Config
from ai_collab.core.run_state import RunStateStore
from ai_collab.ux_lab_v3 import (
    TEXT,
    UxLabV3Result,
    _agent_label,
    _discover_workspace_candidates,
    _enabled_agents,
    _resolve_controller,
    _resolve_task_text,
    _fit_width,
    _task_preview,
    build_brand_banner,
    build_command_bar_state,
    build_controller_cards,
    build_workspace_hint_line,
    build_workspace_preview_lines,
    build_workspace_session_lines,
    build_mock_plan_v3,
    build_planning_panel_lines,
    build_review_list_lines,
    build_step_track,
    choose_review_layout,
    choose_workspace_layout,
    discover_recent_workspaces,
    derive_workspace_tree_root,
    export_launch_bundle_v3,
    interpret_workspace_submission,
    parse_review_command,
    record_workspace_history,
    request_live_plan,
    resolve_v3_language,
)


def run_textual_ux_lab_v3(
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
) -> UxLabV3Result:
    lang = resolve_v3_language(getattr(config, "ui_language", "en-US"))
    resolved_task = _resolve_task_text(task=task, task_file=task_file)
    resolved_workspace = Path(workspace or cwd).expanduser().resolve()
    available_agents = _enabled_agents(config)
    resolved_controller = _resolve_controller(controller or config.current_controller, available_agents)
    mode = planner_mode if planner_mode in {"live", "mock"} else "live"
    app = UxLabV3TextualApp(
        config=config,
        cwd=Path(cwd).resolve(),
        workspace=resolved_workspace,
        controller=resolved_controller,
        task=resolved_task,
        lang=lang,
        skip_review=skip_review,
        planner_mode=mode,
        output_bundle=output_bundle,
    )
    result = app.run()
    if isinstance(result, UxLabV3Result):
        return result
    return app.result


class WorkspaceDirectoryTree(DirectoryTree):
    ICON_NODE_EXPANDED = "▾ "
    ICON_NODE = "▸ "
    ICON_FILE = "· "

    def __init__(self, path: str | Path, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self.auto_expand = False

    def filter_paths(self, paths):  # type: ignore[override]
        visible: list[Path] = []
        for path in paths:
            try:
                if not path.is_dir() or path.name.startswith("."):
                    continue
            except OSError:
                continue
            visible.append(path)
        return sorted(visible, key=lambda item: item.name.lower())


class UxLabV3TextualApp(App[UxLabV3Result]):
    CSS = """
    Screen {
      layout: vertical;
      background: #08111b;
      color: #dbe7f5;
    }

    #brand {
      height: auto;
      padding: 1 1 0 1;
      content-align: left middle;
      color: #f8fafc;
      text-style: bold;
    }

    #step-track {
      height: auto;
      padding: 0 1 1 1;
      color: #9fd8ff;
    }

    #body {
      height: 1fr;
      padding: 0 1;
    }

    .screen-panel {
      display: none;
      height: 1fr;
      border: round #243b53;
      padding: 1 2;
    }

    .screen-panel.active {
      display: block;
    }

    #workspace-screen {
      border: none;
      padding: 0 1 1 1;
    }

    .help-block {
      color: #8fa7c0;
      margin-bottom: 1;
    }

    #workspace-toolbar {
      layout: horizontal;
      height: 3;
      align: left middle;
      margin-bottom: 1;
    }

    #workspace-tabs {
      width: 44;
      min-width: 34;
      max-width: 44;
      height: 3;
      margin-right: 1;
    }

    #workspace-tabs:focus {
      background: transparent;
    }

    #workspace-tabs Tab {
      min-width: 10;
      height: 3;
      padding: 0 1;
      margin-right: 1;
      border: none;
      border-top: tall #1b2a38;
      border-bottom: tall #050a0f;
      color: #7891a8;
      text-style: bold;
      background: #09131d;
      content-align: center middle;
    }

    #workspace-tabs Tab.-active {
      color: #f8fafc;
      background: #12324a;
      border-top: tall #8ee7ff;
      border-bottom: tall #071b29;
    }

    #workspace-tabs Tab:hover {
      color: #e6f4ff;
      background: #0d2435;
      border-top: tall #356383;
    }

    #workspace-current-path {
      width: 1fr;
      min-width: 20;
      height: 3;
      padding: 0 1;
      border: none;
      background: transparent;
      color: #8fa7c0;
      content-align: right middle;
    }

    #workspace-continue {
      width: auto;
      min-width: 10;
      height: 3;
      margin-left: 1;
    }

    #workspace-continue.-style-default {
      color: #f8fafc;
      background: #14507d;
      border: none;
      border-top: tall #4ac0ff;
      border-bottom: tall #0b2740;
      text-style: bold;
    }

    #workspace-continue.-style-default:hover {
      background: #176696;
      border-top: tall #78d5ff;
    }

    #workspace-continue.-style-default:focus {
      text-style: bold reverse;
    }

    #workspace-continue.-style-default.-active {
      background: #14507d;
      border-bottom: tall #4ac0ff;
      border-top: tall #0b2740;
      tint: #08111b 20%;
    }

    #workspace-picker {
      layout: horizontal;
      height: 1fr;
      background: transparent;
      padding: 0;
      border: none;
    }

    #workspace-picker.stack {
      layout: vertical;
    }

    #workspace-browser {
      width: 6fr;
      height: 1fr;
      border: round #2a465f;
      background: #0b1621;
      padding: 0 1;
      overflow: hidden;
      scrollbar-gutter: stable;
    }

    #workspace-browser.focused {
      border: heavy #8ee7ff;
      background: #0d1f2d;
    }

    #workspace-inspector {
      width: 4fr;
      height: 1fr;
      margin-left: 1;
    }

    #workspace-current-overview {
      height: 1fr;
      color: #dbe7f5;
      padding: 1 2;
      overflow-y: auto;
    }

    #workspace-preview {
      width: 1fr;
      height: 1fr;
      border: round #243b53;
      background: #0f1824;
      color: #dbe7f5;
      padding: 1 2;
      overflow-y: auto;
      scrollbar-gutter: stable;
      scrollbar-size-vertical: 1;
      scrollbar-background: #09121b;
      scrollbar-background-hover: #122131;
      scrollbar-background-active: #122131;
      scrollbar-color: #355873;
      scrollbar-color-hover: #8ee7ff;
      scrollbar-color-active: #8ee7ff;
      scrollbar-corner-color: #09121b;
    }

    #workspace-picker.stack #workspace-browser {
      width: 1fr;
      height: 2fr;
    }

    #workspace-picker.stack #workspace-inspector {
      width: 1fr;
      height: 1fr;
      margin-left: 0;
      margin-top: 1;
    }

    .workspace-picker-panel {
      display: none;
      height: 1fr;
    }

    .workspace-picker-panel.active {
      display: block;
    }

    #workspace-recent-list,
    #workspace-tree,
    #review-agent {
      height: 1fr;
    }

    #workspace-recent-list,
    #workspace-tree {
      border: none;
      background: transparent;
      padding: 0 1;
      scrollbar-gutter: stable;
      scrollbar-size-vertical: 1;
      scrollbar-background: #09121b;
      scrollbar-background-hover: #122131;
      scrollbar-background-active: #122131;
      scrollbar-color: #355873;
      scrollbar-color-hover: #8ee7ff;
      scrollbar-color-active: #8ee7ff;
      scrollbar-corner-color: #09121b;
    }

    #workspace-recent-list:focus,
    #workspace-tree:focus {
      border: none;
    }

    #workspace-recent-empty {
      display: none;
      height: 1fr;
      content-align: center middle;
      color: #6f859b;
      text-style: italic;
      padding: 0 3;
    }

    #workspace-recent-list > .option-list--option {
      padding: 0 1;
    }

    #workspace-recent-list > .option-list--option-hover {
      background: #0f2132;
    }

    #workspace-recent-list > .option-list--option-highlighted {
      background: #17496d;
      color: #f8fafc;
      text-style: bold;
    }

    #workspace-recent-list:focus > .option-list--option-highlighted {
      background: #8ee7ff;
      color: #08111b;
    }

    #workspace-tree > .tree--guides {
      color: #24435a;
    }

    #workspace-tree > .tree--guides-hover {
      color: #5ca7d8;
    }

    #workspace-tree > .tree--guides-selected,
    #workspace-tree > .tree--cursor {
      color: #f8fafc;
    }

    #workspace-tree > .tree--highlight-line {
      background: #0f2132;
    }

    #workspace-tree > .tree--cursor {
      background: #17496d;
      text-style: bold;
    }

    #workspace-tree:focus > .tree--cursor {
      background: #8ee7ff;
      color: #08111b;
    }

    #workspace-shortcuts {
      height: 1;
      margin-top: 1;
      color: #8fa7c0;
      padding: 0 1;
    }

    #task-editor,
    #review-done,
    #review-title,
    #review-eta,
    #command-bar {
      background: #0d1826;
      border: round #243b53;
    }

    #command-bar.workspace-idle {
      background: #09131d;
      border: round #1d3448;
    }

    #task-editor,
    #review-done {
      height: 1fr;
    }

    #controller-cards {
      layout: horizontal;
      height: auto;
      width: 1fr;
      padding-top: 1;
    }

    .controller-card {
      width: 1fr;
      min-height: 12;
      border: round #243b53;
      padding: 1 2;
      margin-right: 1;
      background: #0d1826;
      text-align: left;
      content-align: left top;
      color: #dbe7f5;
    }

    .controller-card:last-child {
      margin-right: 0;
    }

    .controller-card.selected,
    .controller-card:focus {
      border: heavy #8ee7ff;
      background: #10263a;
    }

    .controller-card:hover {
      background: #12283c;
      border: round #4d6a86;
    }

    .field-label {
      margin-top: 1;
      margin-bottom: 0;
      color: #8fa7c0;
    }

    #review-main {
      layout: horizontal;
      height: 1fr;
    }

    #review-main.stack {
      layout: vertical;
    }

    #review-list-pane,
    #review-detail-pane {
      height: 1fr;
      width: 1fr;
    }

    #review-list {
      border: round #243b53;
      background: #0d1826;
      padding: 1;
      height: 1fr;
    }

    #review-agent {
      background: #0d1826;
      border: round #243b53;
    }

    #review-meta,
    #planning-log,
    #controller-help,
    #task-info,
    #error-message,
    #sent-message {
      padding: 0 0 1 0;
    }

    #status-line {
      height: 1;
      padding: 0 1;
      color: #f8fafc;
      text-style: bold;
    }

    #command-label {
      height: 1;
      padding: 0 1;
      color: #93c5fd;
    }

    #command-help {
      height: 1;
      padding: 0 1;
      color: #8fa7c0;
    }

    Footer {
      dock: bottom;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit", priority=True),
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+s", "confirm", "Save / Plan"),
        Binding("f5", "confirm", show=False),
        Binding("f2", "open_nano", "Nano"),
        Binding("f3", "open_vim", "Vim"),
        Binding("up", "move_up", show=False),
        Binding("down", "move_down", show=False),
        Binding("left", "move_left", show=False),
        Binding("right", "move_right", show=False),
        Binding("space", "use_workspace_selection", show=False),
        Binding("colon", "open_command_bar", show=False),
    ]

    def __init__(
        self,
        *,
        config: Config,
        cwd: Path,
        workspace: Path,
        controller: str,
        task: str,
        lang: str,
        skip_review: bool,
        planner_mode: str,
        output_bundle: Optional[Path],
        history_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.cwd = cwd
        self.workspace = workspace
        self.controller = controller
        self.lang = resolve_v3_language(lang)
        self.skip_review = skip_review
        self.planner_mode = planner_mode
        self.output_bundle = output_bundle
        self.available_agents = _enabled_agents(config)
        self.task_value = task
        self.plan = []
        self.bundle_path: Optional[Path] = None
        self.error_message = ""
        self.review_index = 0
        self.screen_name = "workspace"
        self.planning_started_at = 0.0
        self.planning_log: list[str] = []
        self.candidates = _discover_workspace_candidates(cwd)
        if self.workspace not in self.candidates:
            self.candidates.insert(0, self.workspace)
        self.workspace_mode = "current"
        self.workspace_command_mode = False
        self.workspace_history_path = history_path
        self.recent_workspaces = discover_recent_workspaces(
            workspace=self.workspace,
            cwd=self.cwd,
            candidates=self.candidates,
            history_path=history_path,
        )
        self.filtered_recent_workspaces = list(self.recent_workspaces)
        self.recent_index = self._selected_recent_index(self.workspace)
        self.workspace_tree_root = derive_workspace_tree_root(self.candidates, self.workspace, self.cwd)
        self.workspace_tree_selected = self.workspace
        self.status_message = self._t("workspace_ready", path=str(self.workspace))
        self.result = UxLabV3Result(
            status="cancelled",
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=[],
        )
        self._planning_timer = None

    def compose(self) -> ComposeResult:
        yield Static(id="brand")
        yield Static(id="step-track")
        with Container(id="body"):
            with Vertical(id="workspace-screen", classes="screen-panel"):
                with Horizontal(id="workspace-toolbar"):
                    yield Tabs(
                        Tab(self._workspace_tab_label("current"), id="workspace-tab-current"),
                        Tab(self._workspace_tab_label("recent"), id="workspace-tab-recent"),
                        Tab(self._workspace_tab_label("tree"), id="workspace-tab-tree"),
                        active="workspace-tab-current",
                        id="workspace-tabs",
                    )
                    yield Static(id="workspace-current-path")
                    yield Button(id="workspace-continue")
                with Container(id="workspace-picker"):
                    with Vertical(id="workspace-browser"):
                        with Vertical(id="workspace-panel-current", classes="workspace-picker-panel"):
                            yield Static(id="workspace-current-overview")
                        with Vertical(id="workspace-panel-recent", classes="workspace-picker-panel"):
                            yield OptionList(id="workspace-recent-list")
                            yield Static(id="workspace-recent-empty")
                        with Vertical(id="workspace-panel-tree", classes="workspace-picker-panel"):
                            yield WorkspaceDirectoryTree(str(self.workspace_tree_root), id="workspace-tree")
                    with Vertical(id="workspace-inspector"):
                        yield Static(id="workspace-preview")
                yield Static(id="workspace-shortcuts")
            with Vertical(id="controller-screen", classes="screen-panel"):
                yield Static(id="controller-help", classes="help-block")
                with Horizontal(id="controller-cards"):
                    yield Button(id="controller-card-codex", classes="controller-card")
                    yield Button(id="controller-card-claude", classes="controller-card")
                    yield Button(id="controller-card-gemini", classes="controller-card")
            with Vertical(id="task-screen", classes="screen-panel"):
                yield Static(id="task-info", classes="help-block")
                yield TextArea("", id="task-editor")
            with Vertical(id="planning-screen", classes="screen-panel"):
                yield Static(id="planning-log")
            with Vertical(id="review-screen", classes="screen-panel"):
                with Horizontal(id="review-main"):
                    with Vertical(id="review-list-pane"):
                        yield Static(id="review-list-info", classes="help-block")
                        yield Static(id="review-list")
                    with Vertical(id="review-detail-pane"):
                        yield Static(id="review-meta")
                        yield Static(self._t("detail_title_label"), classes="field-label")
                        yield Input(id="review-title")
                        yield Static(self._t("detail_eta_label"), classes="field-label")
                        yield Input(id="review-eta")
                        yield Static(self._t("review_detail_done"), classes="field-label")
                        yield TextArea("", id="review-done")
                        yield Static(self._t("detail_agent_label"), classes="field-label")
                        yield OptionList(*[_agent_label(agent, self.lang) for agent in self.available_agents], id="review-agent")
            with Vertical(id="error-screen", classes="screen-panel"):
                yield Static(id="error-message")
            with Vertical(id="sent-screen", classes="screen-panel"):
                yield Static(id="sent-message")
        yield Static(id="status-line")
        yield Static(id="command-label")
        yield Static(id="command-help")
        yield Input(placeholder="", id="command-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._planning_timer = self.set_interval(0.15, self._tick_planning_panel, pause=False)
        self.query_one("#task-editor", TextArea).load_text(self.task_value)
        self._refresh_all()
        self._focus_workspace_mode()

    def on_resize(self) -> None:
        self._refresh_step_track()
        self._refresh_workspace_layout()
        self._refresh_review_layout()

    def _watch_focused(self) -> None:
        super()._watch_focused()
        self.call_after_refresh(self._refresh_workspace_focus_state)

    def on_descendant_focus(self, _event: events.DescendantFocus) -> None:
        if self.screen_name == "workspace":
            focused_id = getattr(self.focused, "id", None)
            if focused_id == "command-bar" and not self.workspace_command_mode:
                self.workspace_command_mode = True
                self._refresh_command_bar()
            elif focused_id != "command-bar" and self.workspace_command_mode:
                self.workspace_command_mode = False
                self._refresh_command_bar()
        self.call_after_refresh(self._refresh_workspace_focus_state)

    def on_descendant_blur(self, _event: events.DescendantBlur) -> None:
        self.call_after_refresh(self._refresh_workspace_focus_state)

    def on_key(self, event: events.Key) -> None:
        if event.character == ":" and self.screen_name == "workspace" and not isinstance(self.focused, (Input, TextArea)):
            self.action_open_command_bar()
            event.stop()
            return
        if event.key == "space" and self.screen_name == "workspace" and not isinstance(self.focused, (Input, TextArea)):
            self.action_use_workspace_selection()
            event.stop()
            return
        if event.key == "enter" and self.screen_name == "workspace" and isinstance(self.focused, DirectoryTree):
            self.focused.action_toggle_node()
            event.stop()

    @on(Input.Changed, "#command-bar")
    def _command_bar_changed(self, event: Input.Changed) -> None:
        if self.screen_name != "workspace":
            self._refresh_command_bar()
            return
        if self.workspace_mode == "recent":
            decision = interpret_workspace_submission(
                raw=event.value,
                cwd=self.cwd,
                selected=self._selected_recent_workspace(),
            )
            if decision.kind == "filter":
                query = decision.query.lower()
                self.filtered_recent_workspaces = [path for path in self.recent_workspaces if query in str(path).lower()]
            elif decision.kind in {"use", "create", "missing"} and not any(sep in event.value for sep in ("/", "\\")):
                query = event.value.lower().strip()
                self.filtered_recent_workspaces = [path for path in self.recent_workspaces if query in str(path).lower()]
            else:
                self.filtered_recent_workspaces = list(self.recent_workspaces)
            if self.filtered_recent_workspaces:
                self.recent_index = min(self.recent_index, len(self.filtered_recent_workspaces) - 1)
        else:
            self.filtered_recent_workspaces = list(self.recent_workspaces)
        self._refresh_recent_list()
        self._refresh_workspace_panel()
        self._refresh_command_bar()

    @on(Input.Submitted, "#command-bar")
    def _command_bar_submitted(self, _event: Input.Submitted) -> None:
        self._submit_command_bar()

    @on(OptionList.OptionHighlighted, "#workspace-recent-list")
    def _workspace_recent_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.filtered_recent_workspaces:
            return
        self.recent_index = max(0, min(event.option_index, len(self.filtered_recent_workspaces) - 1))
        self.status_message = f"{self._t('workspace_selected')}: {self._selected_recent_workspace()}"
        self._refresh_status()
        self._refresh_workspace_panel()

    @on(OptionList.OptionSelected, "#workspace-recent-list")
    def _workspace_recent_selected(self, _event: OptionList.OptionSelected) -> None:
        if self.screen_name == "workspace" and self.workspace_mode == "recent":
            self._submit_workspace()

    @on(Tree.NodeHighlighted, "#workspace-tree")
    def _workspace_tree_highlighted(self, event: Tree.NodeHighlighted) -> None:
        node = event.node
        data = getattr(node, "data", None)
        path = getattr(data, "path", None)
        if isinstance(path, Path) and path.is_dir():
            self.workspace_tree_selected = path.resolve()
            self._refresh_workspace_panel()

    @on(Tree.NodeSelected, "#workspace-tree")
    def _workspace_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        data = getattr(node, "data", None)
        path = getattr(data, "path", None)
        if isinstance(path, Path) and path.is_dir():
            self.workspace_tree_selected = path.resolve()
            self.status_message = f"{self._t('workspace_selected')}: {self.workspace_tree_selected}"
            self._refresh_status()
            self._refresh_workspace_panel()

    @on(DirectoryTree.DirectorySelected, "#workspace-tree")
    def _workspace_tree_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.workspace_tree_selected = event.path.resolve()
        self.status_message = f"{self._t('workspace_selected')}: {self.workspace_tree_selected}"
        self._refresh_status()
        self._refresh_workspace_panel()

    @on(Tabs.TabActivated, "#workspace-tabs")
    def _workspace_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = str(event.tab.id or "")
        if not tab_id.startswith("workspace-tab-"):
            return
        self._set_workspace_mode(tab_id.replace("workspace-tab-", "", 1))

    @on(Button.Pressed, "#workspace-continue")
    def _workspace_continue_pressed(self, _event: Button.Pressed) -> None:
        if self.screen_name == "workspace":
            self.action_use_workspace_selection()

    @on(Button.Pressed, ".controller-card")
    def _controller_card_pressed(self, event: Button.Pressed) -> None:
        card_id = str(event.button.id or "")
        if not card_id.startswith("controller-card-"):
            return
        selected = card_id.replace("controller-card-", "", 1)
        if selected == self.controller:
            self._switch_screen("task")
            return
        self.controller = selected
        self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
        self._refresh_status()
        self._refresh_controller_panel()
        self._refresh_task_panel()
        event.button.focus()

    @on(OptionList.OptionHighlighted, "#review-agent")
    def _review_agent_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self.screen_name == "review" and 0 <= event.option_index < len(self.available_agents):
            self.status_message = self._t("review_saved", field="agent", step=self._current_step_id())
            self.query_one("#status-line", Static).update(self.status_message)

    def action_quit_app(self) -> None:
        self.exit(result=self._result(status="cancelled"))

    def action_go_back(self) -> None:
        if self.screen_name == "workspace" and self.workspace_command_mode:
            self.workspace_command_mode = False
            self.query_one("#command-bar", Input).value = ""
            self._refresh_command_bar()
            self._focus_workspace_mode()
            return
        mapping = {
            "controller": "workspace",
            "task": "controller",
            "review": "task",
            "error": "task",
            "sent": "review",
        }
        target = mapping.get(self.screen_name)
        if target:
            self._switch_screen(target)

    def action_confirm(self) -> None:
        if self.screen_name == "workspace":
            self._submit_workspace()
        elif self.screen_name == "controller":
            self._submit_controller()
        elif self.screen_name == "task":
            self._start_planning()
        elif self.screen_name == "review":
            self._save_review_form()
        elif self.screen_name == "sent":
            self.exit(result=self._result(status="sent"))
        else:
            self._submit_command_bar()

    def action_open_nano(self) -> None:
        if self.screen_name == "task":
            self._open_editor("nano")

    def action_open_vim(self) -> None:
        if self.screen_name == "task":
            self._open_editor("vim")

    def action_open_command_bar(self) -> None:
        if self.screen_name == "workspace" and not isinstance(self.focused, (Input, TextArea)):
            self.workspace_command_mode = True
            self._refresh_command_bar()
            self.query_one("#command-bar", Input).focus()
            self.status_message = self._t("workspace_help")
            self._refresh_status()

    def action_use_workspace_selection(self) -> None:
        if self.screen_name != "workspace" or isinstance(self.focused, (Input, TextArea)):
            return
        self._use_workspace(self._workspace_submission_target(), created=False)

    def action_move_up(self) -> None:
        if isinstance(self.focused, (Input, TextArea)) and self.screen_name in {"task", "review"}:
            return
        if self.screen_name == "workspace":
            if self.workspace_mode == "recent" and isinstance(self.focused, OptionList):
                self.focused.action_cursor_up()
            elif self.workspace_mode == "tree" and isinstance(self.focused, DirectoryTree):
                self.focused.action_cursor_up()
        elif self.screen_name == "review":
            self._move_review(-1)

    def action_move_down(self) -> None:
        if isinstance(self.focused, (Input, TextArea)) and self.screen_name in {"task", "review"}:
            return
        if self.screen_name == "workspace":
            if self.workspace_mode == "recent" and isinstance(self.focused, OptionList):
                self.focused.action_cursor_down()
            elif self.workspace_mode == "tree" and isinstance(self.focused, DirectoryTree):
                self.focused.action_cursor_down()
        elif self.screen_name == "review":
            self._move_review(1)

    def action_move_left(self) -> None:
        if isinstance(self.focused, (Input, TextArea)):
            return
        if self.screen_name == "workspace":
            self._cycle_workspace_mode(-1)
        elif self.screen_name == "controller":
            self._move_controller(-1)
        elif self.screen_name == "review":
            self._move_review_agent(-1)

    def action_move_right(self) -> None:
        if isinstance(self.focused, (Input, TextArea)):
            return
        if self.screen_name == "workspace":
            self._cycle_workspace_mode(1)
        elif self.screen_name == "controller":
            self._move_controller(1)
        elif self.screen_name == "review":
            self._move_review_agent(1)

    def _refresh_all(self) -> None:
        self._refresh_brand()
        self._refresh_step_track()
        self._refresh_screen_visibility()
        self._refresh_status()
        self._refresh_command_bar()
        self._refresh_workspace_layout()
        self._refresh_recent_list()
        self._refresh_workspace_panel()
        self._refresh_controller_panel()
        self._refresh_task_panel()
        self._refresh_planning_panel()
        self._refresh_review_layout()
        self._refresh_review_panel()
        self._refresh_error_panel()
        self._refresh_sent_panel()
        self._refresh_workspace_focus_state()

    def _refresh_brand(self) -> None:
        width = max(40, self.size.width - 2)
        self.query_one("#brand", Static).update("\n".join(build_brand_banner(width, self.lang)))

    def _refresh_step_track(self) -> None:
        width = max(40, self.size.width - 2)
        self.query_one("#step-track", Static).update("\n".join(build_step_track(self.screen_name, self.lang, width)))

    def _refresh_screen_visibility(self) -> None:
        for name in ("workspace", "controller", "task", "planning", "review", "error", "sent"):
            widget = self.query_one(f"#{name}-screen", Vertical)
            widget.display = name == self.screen_name
            widget.set_class(name == self.screen_name, "active")

    def _refresh_status(self) -> None:
        status = self.query_one("#status-line", Static)
        if self.screen_name == "workspace":
            status.display = False
            status.update("")
            return
        status.display = True
        status.update(self.status_message)

    def _refresh_command_bar(self) -> None:
        command_value = self._command_bar_value()
        command_label = self.query_one("#command-label", Static)
        command_help = self.query_one("#command-help", Static)
        command_bar = self.query_one("#command-bar", Input)
        state = build_command_bar_state(
            screen=self.screen_name,
            lang=self.lang,
            raw=command_value,
        )
        mapping = {
            "workspace": "input_workspace",
            "controller": "input_controller",
            "task": "input_task",
            "planning": "input_planning",
            "review": "input_review",
            "error": "input_error",
            "sent": "input_sent",
        }
        if self.screen_name == "workspace":
            command_label.display = False
            command_help.display = False
            command_bar.display = True
            command_bar.set_class(not self.workspace_command_mode, "workspace-idle")
        else:
            command_label.display = True
            command_label.update(self._t(mapping.get(self.screen_name, "input_workspace")))
            command_help.display = True
            command_help.update(state.help_text)
            command_bar.display = True
            command_bar.remove_class("workspace-idle")
        try:
            command_bar.placeholder = state.placeholder
        except Exception:
            return

    def _refresh_workspace_panel(self) -> None:
        selected = self._workspace_submission_target()
        try:
            browser = self.query_one("#workspace-browser", Vertical)
            current_panel = self.query_one("#workspace-current-overview", Static)
            current_path = self.query_one("#workspace-current-path", Static)
            continue_button = self.query_one("#workspace-continue", Button)
            tabs = self.query_one("#workspace-tabs", Tabs)
            current_tab = self.query_one("#workspace-tab-current", Tab)
            recent_tab = self.query_one("#workspace-tab-recent", Tab)
            tree_tab = self.query_one("#workspace-tab-tree", Tab)
            preview = self.query_one("#workspace-preview", Static)
            shortcuts = self.query_one("#workspace-shortcuts", Static)
        except Exception:
            return
        active_tab = f"workspace-tab-{self.workspace_mode}"
        if tabs.active != active_tab:
            tabs.active = active_tab
        current_tab.label = self._workspace_tab_label("current")
        recent_tab.label = self._workspace_tab_label("recent")
        tree_tab.label = self._workspace_tab_label("tree")
        browser.border_title = self._workspace_browser_title()
        preview.border_title = self._workspace_preview_title()
        for mode in ("current", "recent", "tree"):
            panel = self.query_one(f"#workspace-panel-{mode}", Vertical)
            panel.display = mode == self.workspace_mode
            panel.set_class(mode == self.workspace_mode, "active")

        current_label = "当前目录" if self.lang == "zh-CN" else "Current folder"
        current_display = self._display_path(self.cwd)
        if current_display == "~":
            current_display = str(self.cwd)
        current_path.update(f"{current_label}  {current_display}")
        continue_button.label = self._workspace_continue_label()
        browser_width = max(24, browser.region.width - 4 if browser.region.width else (self.size.width // 2))
        current_panel.update("\n".join(self._workspace_current_overview_lines(width=browser_width)).strip())
        preview_width = max(24, preview.region.width - 4 if preview.region.width else (self.size.width // 3))
        preview.update(
            "\n".join(
                build_workspace_session_lines(
                    selected=selected,
                    width=preview_width,
                    lang=self.lang,
                )
            )
        )
        shortcuts.update(build_workspace_hint_line(mode=self.workspace_mode, width=max(36, self.size.width - 8), lang=self.lang))
        self._refresh_workspace_focus_state()

    def _command_bar_value(self) -> str:
        try:
            return self.query_one("#command-bar", Input).value.strip()
        except Exception:
            return ""

    def _refresh_controller_panel(self) -> None:
        self.query_one("#controller-help", Static).update(self._t("controller_help"))
        cards = {card.agent: card for card in build_controller_cards(self.controller, self.lang)}
        for agent in ("codex", "claude", "gemini"):
            card = cards[agent]
            widget = self.query_one(f"#controller-card-{agent}", Button)
            widget.label = f"{card.title}\n{card.summary}\n\n{card.detail}"
            widget.set_class(card.selected, "selected")

    def _refresh_task_panel(self) -> None:
        task_text = self.query_one("#task-editor", TextArea).text
        line_count = len(task_text.splitlines()) if task_text else 0
        preview = _task_preview(task_text)
        text = (
            f"{self._t('task_help')}\n\n"
            f"{self._t('detail_workspace_label')}: {self.workspace}\n"
            f"{self._t('detail_agent_label')}: {_agent_label(self.controller, self.lang)}  ·  {self._planner_notice()}\n"
            f"{self._t('detail_task_lines_label')}: {line_count}\n"
            f"{preview if task_text else self._t('task_help')}"
        )
        self.query_one("#task-info", Static).update(text)

    def _refresh_planning_panel(self) -> None:
        elapsed = max(0.0, time.monotonic() - self.planning_started_at)
        widget = self.query_one("#planning-log", Static)
        content_width = max(36, widget.region.width - 2 if widget.region.width else self.size.width - 8)
        lines = build_planning_panel_lines(
            task=self.task_value,
            workspace=self.workspace,
            controller=self.controller,
            planner_mode=self.planner_mode,
            lang=self.lang,
            width=content_width,
            elapsed_seconds=elapsed,
            log_lines=self.planning_log,
            plan_count=len(self.plan),
        )
        widget.update("\n".join(lines))

    def _tick_planning_panel(self) -> None:
        if self.screen_name == "planning" and self.planning_started_at:
            self._refresh_planning_panel()

    def _refresh_review_layout(self) -> None:
        container = self.query_one("#review-main", Horizontal)
        container.set_class(choose_review_layout(self.size.width) == "stack", "stack")

    def _refresh_review_panel(self) -> None:
        self.query_one("#review-list-info", Static).update(
            f"{self._t('review_help')}\n{self._t('review_step_count', count=str(len(self.plan)))}"
        )
        if not self.plan:
            self.query_one("#review-list", Static).update("")
            self.query_one("#review-meta", Static).update("")
            return
        width = max(28, (self.size.width // 2) - 6)
        lines = build_review_list_lines(self.plan, self.review_index, width)
        self.query_one("#review-list", Static).update("\n".join(lines))
        item = self.plan[self.review_index]
        self.query_one("#review-meta", Static).update(
            self._t(
                "review_detail_meta",
                sx=item.sx,
                agent=_agent_label(item.agent, self.lang),
                eta=str(item.eta_minutes),
            )
            + "\n\n"
            + "/create ...   /delete   /save   /send   /task"
        )

    def _refresh_error_panel(self) -> None:
        if not self.error_message:
            return
        self.query_one("#error-message", Static).update(f"{self._t('error_help')}\n\n{self.error_message}\n\n/retry   /task")

    def _refresh_sent_panel(self) -> None:
        path_text = str(self.bundle_path) if self.bundle_path else "-"
        self.query_one("#sent-message", Static).update(
            f"{self._t('sent_help')}\n\n{self._t('send_done', path=path_text)}\n\n"
            f"{self._t('detail_workspace_label')}: {self.workspace}\n{path_text}\n\n{self._t('send_exit')}"
        )

    def _refresh_workspace_layout(self) -> None:
        try:
            picker = self.query_one("#workspace-picker", Container)
        except Exception:
            return
        picker.set_class(choose_workspace_layout(self.size.width) == "stack", "stack")

    def _refresh_recent_list(self) -> None:
        option_list = self.query_one("#workspace-recent-list", OptionList)
        empty_state = self.query_one("#workspace-recent-empty", Static)
        option_list.clear_options()
        if self.filtered_recent_workspaces:
            option_list.display = True
            empty_state.display = False
            option_list.add_options([self._workspace_recent_option_text(path) for path in self.filtered_recent_workspaces])
            option_list.highlighted = max(0, min(self.recent_index, len(self.filtered_recent_workspaces) - 1))
        else:
            option_list.display = False
            empty_state.display = True
            empty_state.update(self._workspace_recent_empty_text())
            if self.screen_name == "workspace" and self.workspace_mode == "recent" and isinstance(self.focused, OptionList):
                self.query_one("#workspace-tabs", Tabs).focus()

    def _selected_recent_workspace(self) -> Optional[Path]:
        if not self.filtered_recent_workspaces:
            return None
        return self.filtered_recent_workspaces[max(0, min(self.recent_index, len(self.filtered_recent_workspaces) - 1))]

    def _selected_recent_index(self, workspace: Path) -> int:
        for index, path in enumerate(self.filtered_recent_workspaces):
            if path == workspace:
                return index
        return 0

    def _cycle_workspace_mode(self, delta: int) -> None:
        modes = ("current", "recent", "tree")
        index = modes.index(self.workspace_mode) if self.workspace_mode in modes else 0
        self._set_workspace_mode(modes[(index + delta) % len(modes)])

    def _workspace_mode_label(self, mode: str) -> str:
        labels = {
            "en-US": {
                "current": "Current",
                "recent": "Recent",
                "tree": "Tree",
            },
            "zh-CN": {
                "current": "当前目录",
                "recent": "最近使用",
                "tree": "目录树",
            },
        }
        return labels[self.lang].get(mode, mode)

    def _workspace_tab_label(self, mode: str) -> str:
        if mode == "recent":
            count = len(self.recent_workspaces)
            if self.lang == "zh-CN":
                return f"{self._workspace_mode_label(mode)} {count}"
            return f"{self._workspace_mode_label(mode)} {count}"
        return self._workspace_mode_label(mode)

    def _workspace_continue_label(self) -> str:
        return "继续" if self.lang == "zh-CN" else "Continue"

    def _workspace_browser_title(self) -> str:
        if self.workspace_mode == "current":
            return "当前目录" if self.lang == "zh-CN" else "Current Folder"
        if self.workspace_mode == "tree":
            return "目录树" if self.lang == "zh-CN" else "Directory Tree"
        count = len(self.filtered_recent_workspaces)
        if self.lang == "zh-CN":
            return f"最近使用目录 ({count})"
        return f"Recent Folders ({count})"

    def _workspace_preview_title(self) -> str:
        return "检查器" if self.lang == "zh-CN" else "Inspector"

    def _workspace_recent_empty_text(self) -> str:
        if self.lang == "zh-CN":
            return "暂无最近使用的目录"
        return "No recent folders yet"

    def _refresh_workspace_focus_state(self) -> None:
        try:
            browser = self.query_one("#workspace-browser", Vertical)
        except Exception:
            return
        browser_has_focus = (
            self.screen_name == "workspace"
            and isinstance(self.focused, (OptionList, DirectoryTree))
        )
        browser.set_class(browser_has_focus, "focused")

    def _workspace_confirm_label(self) -> str:
        if self.workspace_mode == "tree":
            return "使用选中目录" if self.lang == "zh-CN" else "Use Selected Folder"
        return "使用高亮目录" if self.lang == "zh-CN" else "Use Highlighted Folder"

    def _workspace_footer_text(self, selected: Path) -> str:
        current_label = "当前" if self.lang == "zh-CN" else "Current"
        selected_label = "已选" if self.lang == "zh-CN" else "Selected"
        parts = [f"{current_label} {self._display_path(self.cwd)}"]
        if selected.resolve() != self.cwd.resolve():
            parts.append(f"{selected_label} {self._display_path(selected)}")
        parts.append(build_workspace_hint_line(mode=self.workspace_mode, width=max(28, self.size.width - 24), lang=self.lang))
        return "  ·  ".join(parts)

    def _workspace_selection_text(self) -> str:
        selected = self._workspace_submission_target()
        if self.lang == "zh-CN":
            return f"当前选择: {self._display_path(selected)}"
        return f"Current selection: {self._display_path(selected)}"

    def _workspace_summary_line(self, *, label: str, path: Path, suffix: str = "") -> str:
        text = f"{label}: {self._display_path(path)}"
        if suffix:
            text = f"{text}   ·   {suffix}"
        return text

    def _display_path(self, path: Path) -> str:
        resolved = Path(path).expanduser().resolve()
        home = Path.home().expanduser().resolve()
        try:
            relative = resolved.relative_to(home)
        except ValueError:
            return str(resolved)
        return "~" if str(relative) == "." else f"~/{relative}"

    def _workspace_recent_option_text(self, path: Path) -> str:
        resolved = Path(path).expanduser().resolve()
        display = self._display_path(resolved)
        title = resolved.name or display
        return f"{title}  ·  {display}"

    def _workspace_current_overview_lines(self, *, width: int) -> list[str]:
        path = self.cwd.resolve()
        runs = RunStateStore.list_runs(cwd=path, limit=6)
        flags: list[str] = []
        if (path / ".git").exists():
            flags.append("Git 仓库" if self.lang == "zh-CN" else "Git repo")
        if (path / ".ai-collab").exists():
            flags.append("ai-collab 已初始化" if self.lang == "zh-CN" else "ai-collab ready")
        flags.append(
            f"{len(runs)} 个可恢复运行" if self.lang == "zh-CN" else f"{len(runs)} resumable runs"
        )
        children = self._workspace_signal_entries(path, limit=max(4, min(7, self.size.height // 4)))
        lines = [
            _fit_width(self._display_path(path), width),
            _fit_width(" · ".join(flags), width),
            "",
        ]
        if self.lang == "zh-CN":
            lines.extend(
                [
                    _fit_width("继续会在这个目录读取 / 写入", width),
                    _fit_width("• .ai-collab/runs/", width),
                    _fit_width("• .ai-collab/ux-lab-v3/", width),
                    "",
                    _fit_width("项目信号", width),
                ]
            )
        else:
            lines.extend(
                [
                    _fit_width("Continue will read and write here", width),
                    _fit_width("• .ai-collab/runs/", width),
                    _fit_width("• .ai-collab/ux-lab-v3/", width),
                    "",
                    _fit_width("Project signals", width),
                ]
            )
        for child in children:
            lines.append(_fit_width(f"• {child}", width))
        return lines

    def _workspace_signal_entries(self, path: Path, *, limit: int) -> list[str]:
        preferred = [".git", ".ai-collab", "ai_collab", "tests", "config", "README.md", "pyproject.toml", "bin"]
        chosen: list[str] = []
        seen: set[str] = set()
        for name in preferred:
            candidate = path / name
            if candidate.exists() and name not in seen:
                chosen.append(f"{name}/" if candidate.is_dir() else name)
                seen.add(name)
        try:
            children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            children = []
        for child in children:
            if child.name in seen:
                continue
            chosen.append(f"{child.name}/" if child.is_dir() else child.name)
            seen.add(child.name)
            if len(chosen) >= limit:
                break
        return chosen[:limit]

    def _workspace_submission_target(self) -> Path:
        if self.workspace_mode == "current":
            return self.cwd.resolve()
        if self.workspace_mode == "recent":
            return self._selected_recent_workspace() or self.workspace
        return self.workspace_tree_selected or self.workspace

    def _set_workspace_mode(self, mode: str) -> None:
        if mode not in {"current", "recent", "tree"}:
            return
        self.workspace_mode = mode
        self.status_message = self._t("workspace_ready", path=str(self._workspace_submission_target()))
        self._refresh_status()
        self._refresh_workspace_panel()
        self._focus_workspace_mode()

    def _focus_workspace_mode(self) -> None:
        self.workspace_command_mode = False
        self._refresh_command_bar()
        if self.workspace_mode == "current":
            self.query_one("#workspace-tabs", Tabs).focus()
        elif self.workspace_mode == "recent":
            if self.filtered_recent_workspaces:
                self.query_one("#workspace-recent-list", OptionList).focus()
            else:
                self.query_one("#workspace-tabs", Tabs).focus()
        else:
            self.query_one("#workspace-tree", DirectoryTree).focus()
        self._refresh_workspace_focus_state()

    def _move_controller(self, delta: int) -> None:
        current_index = self.available_agents.index(self.controller)
        self.controller = self.available_agents[(current_index + delta) % len(self.available_agents)]
        self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
        self._refresh_status()
        self._refresh_controller_panel()
        self._refresh_task_panel()

    def _move_review(self, delta: int) -> None:
        if not self.plan:
            return
        self._save_review_form(silent=True)
        self._load_review_form((self.review_index + delta) % len(self.plan))
        self.status_message = f"{self.plan[self.review_index].sx}: {self.plan[self.review_index].title}"
        self._refresh_status()
        self._refresh_review_panel()

    def _move_review_agent(self, delta: int) -> None:
        if not self.plan:
            return
        item = self.plan[self.review_index]
        current_index = self.available_agents.index(item.agent) if item.agent in self.available_agents else 0
        item.agent = self.available_agents[(current_index + delta) % len(self.available_agents)]
        self._load_review_form(self.review_index)
        self.status_message = self._t("review_saved", field="agent", step=item.sx)
        self._refresh_status()
        self._refresh_review_panel()

    def _submit_command_bar(self) -> None:
        if self.screen_name == "workspace":
            self._submit_workspace()
        elif self.screen_name == "controller":
            self._submit_controller()
        elif self.screen_name == "task":
            self._run_task_command(self.query_one("#command-bar", Input).value.strip())
        elif self.screen_name == "review":
            self._run_review_command(self.query_one("#command-bar", Input).value.strip())
        elif self.screen_name == "error":
            self._run_error_command(self.query_one("#command-bar", Input).value.strip())
        elif self.screen_name == "sent":
            self._run_sent_command(self.query_one("#command-bar", Input).value.strip())

    def _submit_workspace(self) -> None:
        command_bar = self.query_one("#command-bar", Input)
        decision = interpret_workspace_submission(
            raw=command_bar.value,
            cwd=self.cwd,
            selected=self._workspace_submission_target(),
        )
        if decision.kind == "create" and decision.path is not None:
            decision.path.mkdir(parents=True, exist_ok=True)
            command_bar.value = ""
            self._use_workspace(decision.path.resolve(), created=True)
            return
        if decision.kind == "use" and decision.path is not None:
            command_bar.value = ""
            self._use_workspace(decision.path.resolve(), created=False)
            return
        if decision.kind == "missing":
            self.status_message = self._t("workspace_missing")
            self._refresh_status()
            return
        self.status_message = self._t("workspace_help")
        self._refresh_status()

    def _use_workspace(self, path: Path, *, created: bool) -> None:
        self.workspace = path.resolve()
        self.workspace_command_mode = False
        record_workspace_history(self.workspace, history_path=self.workspace_history_path)
        self._reset_workspace_candidates()
        key = "workspace_created" if created else "workspace_ready"
        self.status_message = self._t(key, path=str(self.workspace))
        self._switch_screen("controller")

    def _submit_controller(self) -> None:
        command_bar = self.query_one("#command-bar", Input)
        typed = command_bar.value.strip().lower().lstrip("/")
        if typed in self.available_agents:
            self.controller = typed
        command_bar.value = ""
        self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
        self._switch_screen("task")

    def _run_task_command(self, raw: str) -> None:
        command = str(raw or "").strip().lower()
        if not command:
            return
        command_bar = self.query_one("#command-bar", Input)
        if command == "/back":
            command_bar.value = ""
            self._switch_screen("controller")
            return
        if command == "/nano":
            command_bar.value = ""
            self._open_editor("nano")
            return
        if command == "/vim":
            command_bar.value = ""
            self._open_editor("vim")
            return
        if command == "/plan":
            command_bar.value = ""
            self._start_planning()
            return
        self.status_message = self._t("task_help")
        self._refresh_status()

    def _run_review_command(self, raw: str) -> None:
        command_bar = self.query_one("#command-bar", Input)
        command = parse_review_command(raw)
        item = self.plan[self.review_index] if self.plan else None
        if command.action == "send":
            command_bar.value = ""
            self._send_plan()
            return
        if command.action == "save":
            command_bar.value = ""
            self._save_review_form()
            return
        if command.action in {"task", "back"}:
            command_bar.value = ""
            self._switch_screen("task")
            return
        if command.action == "delete":
            command_bar.value = ""
            self._delete_step()
            return
        if command.action == "create":
            command_bar.value = ""
            self._create_step(command.value)
            return
        if item is None:
            self.status_message = self._t("review_unknown")
            self._refresh_status()
            return
        if command.action == "title":
            self.query_one("#review-title", Input).value = command.value or self.query_one("#review-title", Input).value
            self._save_review_form()
        elif command.action == "done":
            self.query_one("#review-done", TextArea).load_text(command.value or self.query_one("#review-done", TextArea).text)
            self._save_review_form()
        elif command.action == "eta":
            if not command.value.isdigit() or int(command.value) <= 0:
                self.status_message = self._t("review_bad_eta")
                self._refresh_status()
                return
            self.query_one("#review-eta", Input).value = command.value
            self._save_review_form()
        elif command.action == "agent":
            if command.value.lower() not in self.available_agents:
                self.status_message = self._t("review_unknown")
                self._refresh_status()
                return
            item.agent = command.value.lower()
            self._load_review_form(self.review_index)
            self.status_message = self._t("review_saved", field="agent", step=item.sx)
            self._refresh_status()
            self._refresh_review_panel()
        else:
            self.status_message = self._t("review_unknown")
            self._refresh_status()
            return
        command_bar.value = ""

    def _run_error_command(self, raw: str) -> None:
        command_bar = self.query_one("#command-bar", Input)
        command = parse_review_command(raw)
        if command.action in {"retry", "noop"}:
            command_bar.value = ""
            self._start_planning()
            return
        if command.action in {"task", "back"}:
            command_bar.value = ""
            self._switch_screen("task")

    def _run_sent_command(self, raw: str) -> None:
        command_bar = self.query_one("#command-bar", Input)
        command = parse_review_command(raw)
        if command.action in {"exit", "noop"}:
            self.exit(result=self._result(status="sent"))
            return
        if command.action in {"back", "task"}:
            command_bar.value = ""
            self._switch_screen("review")

    def _create_step(self, title: str) -> None:
        self._save_review_form(silent=True)
        sx = f"S{len(self.plan) + 1}"
        self.plan.append(build_mock_plan_v3(title or sx, self.controller, self.lang, available_agents=[self.controller])[0])
        self.plan[-1].sx = sx
        self.plan[-1].title = title or sx
        self.plan[-1].done_when = self.plan[-1].done_when or ""
        self._renumber_plan()
        self._load_review_form(len(self.plan) - 1)
        self.status_message = self._t("review_created", step=sx)
        self._refresh_status()
        self._refresh_review_panel()

    def _delete_step(self) -> None:
        if len(self.plan) <= 1:
            self.status_message = self._t("review_keep_one")
            self._refresh_status()
            return
        deleted = self.plan.pop(self.review_index)
        self._renumber_plan()
        self._load_review_form(max(0, min(self.review_index, len(self.plan) - 1)))
        self.status_message = self._t("review_deleted", step=deleted.sx)
        self._refresh_status()
        self._refresh_review_panel()

    def _renumber_plan(self) -> None:
        for index, item in enumerate(self.plan, start=1):
            item.sx = f"S{index}"

    def _start_planning(self) -> None:
        self.task_value = self.query_one("#task-editor", TextArea).text.strip()
        if not self.task_value:
            self.status_message = self._t("task_missing")
            self._refresh_status()
            return
        self.screen_name = "planning"
        self.error_message = ""
        self.planning_started_at = time.monotonic()
        self.planning_log = [self._t("planning_prepare"), self._t("planning_call")]
        self.status_message = self._planner_notice()
        self.query_one("#command-bar", Input).value = ""
        self._refresh_all()
        self.run_worker(self._run_planning(), group="planning", exclusive=True)

    async def _run_planning(self) -> None:
        if self.planner_mode == "mock":
            await asyncio.sleep(0.8)
            self.plan = build_mock_plan_v3(self.task_value, self.controller, self.lang, available_agents=self.available_agents)
            self._finish_planning_success()
            return

        items, error = await asyncio.to_thread(
            request_live_plan,
            config=self.config,
            controller=self.controller,
            task=self.task_value,
            workspace=self.workspace,
            lang=self.lang,
        )
        if error:
            self.error_message = error
            self.screen_name = "error"
            self.status_message = self._t("planning_failed", error=error)
            self.query_one("#command-bar", Input).value = ""
            self._refresh_all()
            self.query_one("#command-bar", Input).focus()
            return
        assert items is not None
        self.plan = items
        self._finish_planning_success()

    def _finish_planning_success(self) -> None:
        self._load_review_form(0)
        if self.skip_review:
            self._send_plan()
            return
        self.screen_name = "review"
        self.status_message = self._t("planning_ready")
        self.query_one("#command-bar", Input).value = ""
        self._refresh_all()
        self.query_one("#review-title", Input).focus()

    def _send_plan(self) -> None:
        if self.screen_name == "review":
            self._save_review_form(silent=True)
        self.bundle_path = export_launch_bundle_v3(
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=self.plan,
            output_path=self.output_bundle,
        )
        self.screen_name = "sent"
        self.status_message = self._t("send_done", path=str(self.bundle_path))
        self.query_one("#command-bar", Input).value = ""
        self._refresh_all()
        self.query_one("#command-bar", Input).focus()

    def _open_editor(self, editor: str) -> None:
        if shutil.which(editor) is None:
            self.status_message = self._t("task_editor_missing", editor=editor)
            self._refresh_status()
            return
        task_editor = self.query_one("#task-editor", TextArea)
        with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as handle:
            handle.write(task_editor.text.strip())
            handle.flush()
            temp_path = Path(handle.name)
        try:
            with self.suspend():
                subprocess.run([editor, str(temp_path)], check=False)
            task_editor.load_text(temp_path.read_text(encoding="utf-8").rstrip())
            self.status_message = self._t("task_editor_loaded")
            self._refresh_status()
            self._refresh_task_panel()
        finally:
            temp_path.unlink(missing_ok=True)

    def _switch_screen(self, screen_name: str) -> None:
        self.screen_name = screen_name
        command_bar = self.query_one("#command-bar", Input)
        command_bar.value = ""
        if screen_name == "workspace":
            self.workspace_command_mode = False
            self.status_message = self._t("workspace_ready", path=str(self.workspace))
            self._refresh_all()
            self._focus_workspace_mode()
        elif screen_name == "controller":
            self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
            self._refresh_all()
            self._focus_controller_card()
        elif screen_name == "task":
            self.status_message = self._planner_notice()
            self._refresh_all()
            self.query_one("#task-editor", TextArea).focus()
        elif screen_name == "review":
            self._load_review_form(self.review_index)
            self.status_message = self._t("planning_ready")
            self._refresh_all()
            self.query_one("#review-title", Input).focus()
        elif screen_name == "error":
            self.status_message = self._t("planning_failed", error=self.error_message)
            self._refresh_all()
            self.query_one("#command-bar", Input).focus()
        elif screen_name == "sent":
            self.status_message = self._t("send_done", path=str(self.bundle_path or ""))
            self._refresh_all()
            self.query_one("#command-bar", Input).focus()

    def _focus_controller_card(self) -> None:
        try:
            self.query_one(f"#controller-card-{self.controller}", Button).focus()
        except Exception:
            self.query_one("#command-bar", Input).focus()

    def _reset_workspace_candidates(self) -> None:
        if self.workspace not in self.candidates:
            self.candidates.insert(0, self.workspace)
        self.workspace_tree_root = derive_workspace_tree_root(self.candidates, self.workspace, self.cwd)
        self.workspace_tree_selected = self.workspace
        self.recent_workspaces = discover_recent_workspaces(
            workspace=self.workspace,
            cwd=self.cwd,
            candidates=self.candidates,
            history_path=self.workspace_history_path,
        )
        self.filtered_recent_workspaces = list(self.recent_workspaces)
        self.recent_index = self._selected_recent_index(self.workspace)
        tree = self.query_one("#workspace-tree", DirectoryTree)
        tree.path = self.workspace_tree_root
        tree.reload()
        self._refresh_workspace_panel()

    def _current_step_id(self) -> str:
        if not self.plan:
            return "-"
        return self.plan[self.review_index].sx

    def _load_review_form(self, index: int) -> None:
        if not self.plan:
            return
        self.review_index = max(0, min(index, len(self.plan) - 1))
        item = self.plan[self.review_index]
        self.query_one("#review-title", Input).value = item.title
        self.query_one("#review-eta", Input).value = str(item.eta_minutes)
        self.query_one("#review-done", TextArea).load_text(item.done_when)
        agent_widget = self.query_one("#review-agent", OptionList)
        agent_widget.highlighted = max(0, self.available_agents.index(item.agent))
        self._refresh_review_panel()

    def _save_review_form(self, *, silent: bool = False) -> bool:
        if not self.plan:
            return False
        eta_raw = self.query_one("#review-eta", Input).value.strip()
        if not eta_raw.isdigit() or int(eta_raw) <= 0:
            if not silent:
                self.status_message = self._t("review_bad_eta")
                self._refresh_status()
            return False
        item = self.plan[self.review_index]
        item.title = self.query_one("#review-title", Input).value.strip() or item.title
        item.done_when = self.query_one("#review-done", TextArea).text.strip() or item.done_when
        item.eta_minutes = int(eta_raw)
        agent_index = self.query_one("#review-agent", OptionList).highlighted
        if 0 <= agent_index < len(self.available_agents):
            item.agent = self.available_agents[agent_index]
        if not silent:
            self.status_message = self._t("review_saved_form")
            self._refresh_status()
            self._refresh_review_panel()
        return True

    def _planner_notice(self) -> str:
        return self._t("planner_live") if self.planner_mode == "live" else self._t("planner_mock")

    def _result(self, *, status: str) -> UxLabV3Result:
        return UxLabV3Result(
            status=status,
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value or self.query_one("#task-editor", TextArea).text.strip(),
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=list(self.plan),
            bundle_path=self.bundle_path,
            error_message=self.error_message or None,
        )

    def _t(self, key: str, **kwargs: str) -> str:
        table = TEXT.get(self.lang, TEXT["en-US"])
        return str(table.get(key, key)).format(**kwargs)
