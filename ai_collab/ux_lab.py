"""
Experimental fullscreen UX lab for ai-collab.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from ai_collab.core.config import Config

SUPPORTED_LANGS = ("en-US", "zh-CN")
DEFAULT_AGENTS = ("codex", "claude", "gemini")
ASCII_BANNER = [
    "      _      ___      ___            _ _       _     ",
    "     / \\    |_ _|    / __|___  _ __ | | | __ _| |__  ",
    "    / _ \\    | |    | |   / _ \\| '_ \\| | |/ _` | '_ \\ ",
    "   / ___ \\   | |    | |__| (_) | | | | | | (_| | |_) |",
    "  /_/   \\_\\ |___|    \\___\\___/|_| |_|_|_|\\__,_|_.__/ ",
]

LAB_TEXT = {
    "en-US": {
        "subtitle": "Controller-first orchestration lab",
        "workspace_title": "Step 1  Workspace",
        "workspace_current": "Current directory",
        "workspace_question": "Use this folder as the ai-collab target workspace?",
        "workspace_search": "Search known folders",
        "workspace_manual": "Manual path or new folder",
        "workspace_known": "Known folders",
        "workspace_use_current": "Use current folder",
        "workspace_use_selected": "Use selected folder",
        "workspace_use_typed": "Use typed path",
        "workspace_create": "Create folder",
        "workspace_ready": "Workspace selected: {path}",
        "workspace_missing": "Typed path does not exist yet. Create it or choose an existing folder.",
        "workspace_invalid": "Select or type a valid folder first.",
        "workspace_created": "Created workspace folder: {path}",
        "controller_title": "Step 2  Controller",
        "controller_prompt": "Choose the controller agent with Left/Right, then continue.",
        "controller_selected": "Selected controller: {name}",
        "task_title": "Step 3  Task",
        "task_prompt": "Describe the task. Paste is supported. Type /nano or /vim, or use F2/F3.",
        "task_editor_loaded": "Loaded editor content back into the task box.",
        "task_editor_missing": "{editor} is not available in PATH.",
        "task_required": "Task cannot be empty.",
        "open_nano": "Open nano",
        "open_vim": "Open vim",
        "plan_title": "Step 4  Planning",
        "plan_status_prepare": "Preparing controller request...",
        "plan_status_plan": "Waiting for controller JSON plan...",
        "plan_status_render": "Rendering editable task plan...",
        "plan_ready": "Plan ready. Review before send.",
        "review_title": "Step 5  Review Plan",
        "review_table": "Planned tasks",
        "review_detail": "Selected task",
        "review_prev": "Previous",
        "review_next": "Next",
        "review_add": "Add task",
        "review_delete": "Delete task",
        "review_save": "Save changes",
        "review_send": "Send",
        "review_done_when": "Done when",
        "review_eta": "ETA (min)",
        "review_agent": "Assigned agent",
        "review_saved": "Saved task changes.",
        "review_added": "Added a new task.",
        "review_deleted": "Deleted the selected task.",
        "review_keep_one": "Keep at least one task in the plan.",
        "review_bad_eta": "ETA must be a positive integer.",
        "send_title": "Bundle Ready",
        "send_body": "Exported the V1 launch bundle.\nThis version stops before tmux launch so the UX can be validated safely.",
        "send_path": "Bundle path: {path}",
        "send_back": "Back to review",
        "send_exit": "Exit",
        "back": "Back",
        "continue": "Continue",
        "exit": "Exit",
        "footer_workspace": "Tab switches focus. Enter activates a button. Ctrl-C exits.",
        "footer_controller": "Left/Right switches controller. Enter continues. Esc goes back.",
        "footer_task": "F2 opens nano. F3 opens vim. Ctrl-C exits.",
        "footer_plan": "Planning in mock mode. Ctrl-C exits.",
        "footer_review": "Tab between controls. Save before Send if you edited fields.",
        "footer_send": "Bundle exported. Review or exit.",
        "field_title": "Title",
        "field_done_when": "Done when",
        "field_eta": "ETA",
        "field_agent": "Agent",
        "step_prefix": "Step",
    },
    "zh-CN": {
        "subtitle": "主控优先编排实验场",
        "workspace_title": "第 1 步  工作目录",
        "workspace_current": "当前目录",
        "workspace_question": "是否将这个文件夹作为本次 ai-collab 的目标工作目录？",
        "workspace_search": "搜索已知文件夹",
        "workspace_manual": "手动输入路径或新建目录",
        "workspace_known": "已知文件夹",
        "workspace_use_current": "使用当前目录",
        "workspace_use_selected": "使用选中目录",
        "workspace_use_typed": "使用输入路径",
        "workspace_create": "新建目录",
        "workspace_ready": "已选择工作目录：{path}",
        "workspace_missing": "输入的路径还不存在。请先创建，或选择已有目录。",
        "workspace_invalid": "请先选择目录或输入有效路径。",
        "workspace_created": "已创建工作目录：{path}",
        "controller_title": "第 2 步  选择主控",
        "controller_prompt": "使用左右键切换主控 Agent，然后继续。",
        "controller_selected": "已选择主控：{name}",
        "task_title": "第 3 步  输入任务",
        "task_prompt": "支持直接输入和粘贴。输入 /nano 或 /vim，或直接按 F2/F3 打开编辑器。",
        "task_editor_loaded": "编辑器内容已经回填到任务输入框。",
        "task_editor_missing": "PATH 中没有找到 {editor}。",
        "task_required": "任务内容不能为空。",
        "open_nano": "打开 nano",
        "open_vim": "打开 vim",
        "plan_title": "第 4 步  主控规划",
        "plan_status_prepare": "正在准备主控请求……",
        "plan_status_plan": "正在等待主控返回 JSON 计划……",
        "plan_status_render": "正在渲染可编辑任务清单……",
        "plan_ready": "计划已生成，请确认后再发送。",
        "review_title": "第 5 步  检查计划",
        "review_table": "任务清单",
        "review_detail": "当前任务",
        "review_prev": "上一个",
        "review_next": "下一个",
        "review_add": "新增任务",
        "review_delete": "删除任务",
        "review_save": "保存修改",
        "review_send": "发送",
        "review_done_when": "完成标准",
        "review_eta": "预计耗时（分钟）",
        "review_agent": "执行 Agent",
        "review_saved": "任务修改已保存。",
        "review_added": "已新增任务。",
        "review_deleted": "已删除当前任务。",
        "review_keep_one": "计划里至少保留一个任务。",
        "review_bad_eta": "预计耗时必须是正整数。",
        "send_title": "已导出 Bundle",
        "send_body": "V1 已导出启动 bundle。\n这一版会停在 tmux 启动之前，先验证交互流程本身。",
        "send_path": "Bundle 路径：{path}",
        "send_back": "返回检查",
        "send_exit": "退出",
        "back": "返回",
        "continue": "继续",
        "exit": "退出",
        "footer_workspace": "Tab 切换焦点，Enter 触发按钮，Ctrl-C 退出。",
        "footer_controller": "左右键切换主控，Enter 继续，Esc 返回上一步。",
        "footer_task": "F2 打开 nano，F3 打开 vim，Ctrl-C 退出。",
        "footer_plan": "当前使用 mock 规划器，Ctrl-C 可退出。",
        "footer_review": "Tab 在控件间切换。若改了字段，发送前先保存。",
        "footer_send": "Bundle 已导出，可返回检查或直接退出。",
        "field_title": "标题",
        "field_done_when": "完成标准",
        "field_eta": "预计耗时",
        "field_agent": "Agent",
        "step_prefix": "步骤",
    },
}

AGENT_LABELS = {
    "en-US": {"codex": "Codex", "claude": "Claude", "gemini": "Gemini"},
    "zh-CN": {"codex": "Codex", "claude": "Claude", "gemini": "Gemini"},
}

AGENT_STYLE = {
    "codex": "class:agent-codex",
    "claude": "class:agent-claude",
    "gemini": "class:agent-gemini",
}


@dataclass
class LabPlanItem:
    sx: str
    title: str
    agent: str
    eta_minutes: int
    done_when: str


@dataclass
class UxLabResult:
    status: str
    workspace: Path
    controller: str
    task: str
    lang: str
    planner_mode: str
    plan: list[LabPlanItem]
    bundle_path: Optional[Path] = None


def resolve_lab_language(config_lang: Optional[str]) -> str:
    """Resolve UX lab language directly from config."""
    if config_lang in SUPPORTED_LANGS:
        return str(config_lang)
    return "en-US"


def filter_workspace_candidates(candidates: Sequence[Path], query: str) -> list[Path]:
    """Filter workspace candidates without changing their relative order."""
    needle = str(query or "").strip().lower()
    if not needle:
        return [Path(candidate) for candidate in candidates]

    result: list[Path] = []
    for candidate in candidates:
        value = str(candidate).lower()
        if needle in value or needle in candidate.name.lower():
            result.append(Path(candidate))
    return result


def parse_task_editor_command(value: str) -> Optional[str]:
    """Return external editor name for supported slash commands."""
    normalized = str(value or "").strip().lower()
    if normalized == "/nano":
        return "nano"
    if normalized == "/vim":
        return "vim"
    return None


def build_mock_plan(
    task: str,
    controller: str,
    lang: str,
    *,
    available_agents: Optional[Sequence[str]] = None,
) -> list[LabPlanItem]:
    """Build a localized mock plan for UX validation."""
    runtime_lang = resolve_lab_language(lang)
    ordered_agents = _ordered_agents(controller, available_agents)
    preview = _task_preview(task)

    if runtime_lang == "zh-CN":
        return [
            LabPlanItem(
                sx="S1",
                title=f"{_agent_label(controller, runtime_lang)} 拆解任务并产出主控计划",
                agent=controller,
                eta_minutes=8,
                done_when=f"形成可编辑的任务清单，覆盖目标、分工与验收标准：{preview}",
            ),
            LabPlanItem(
                sx="S2",
                title=f"{_agent_label(ordered_agents[1], runtime_lang)} 执行第一条并行任务",
                agent=ordered_agents[1],
                eta_minutes=14,
                done_when="子控完成分配任务，并明确输出“任务完成”与可交付结果。",
            ),
            LabPlanItem(
                sx="S3",
                title=f"{_agent_label(ordered_agents[2], runtime_lang)} 复核收尾与关闭策略",
                agent=ordered_agents[2],
                eta_minutes=10,
                done_when="主控可以汇总状态，并向用户询问关闭还是保留协作窗口。",
            ),
        ]

    return [
        LabPlanItem(
            sx="S1",
            title=f"{_agent_label(controller, runtime_lang)} drafts the controller plan",
            agent=controller,
            eta_minutes=8,
            done_when=f"Produce an editable task list with scope, owners, and acceptance criteria for {preview}.",
        ),
        LabPlanItem(
            sx="S2",
            title=f"{_agent_label(ordered_agents[1], runtime_lang)} executes the first delegated track",
            agent=ordered_agents[1],
            eta_minutes=14,
            done_when="The delegated agent finishes the assigned track and explicitly reports task completion.",
        ),
        LabPlanItem(
            sx="S3",
            title=f"{_agent_label(ordered_agents[2], runtime_lang)} reviews closure and handoff",
            agent=ordered_agents[2],
            eta_minutes=10,
            done_when="The controller can summarize status and ask whether helper panes should stay open or close.",
        ),
    ]


def launch_ux_lab(
    *,
    config: Config,
    cwd: Path,
    workspace: Optional[Path] = None,
    controller: Optional[str] = None,
    task: Optional[str] = None,
    task_file: Optional[Path] = None,
    skip_review: bool = False,
    planner_mode: str = "mock",
    output_bundle: Optional[Path] = None,
    non_interactive: bool = False,
) -> UxLabResult:
    """Launch the experimental UX lab or run it in non-interactive mode."""
    lang = resolve_lab_language(getattr(config, "ui_language", "en-US"))
    resolved_task = _resolve_task_text(task=task, task_file=task_file)
    resolved_workspace = Path(workspace or cwd).expanduser().resolve()
    available_agents = _enabled_agents(config)
    resolved_controller = _resolve_controller(controller or config.current_controller, available_agents)

    if non_interactive:
        plan = build_mock_plan(
            resolved_task,
            resolved_controller,
            lang,
            available_agents=available_agents,
        )
        bundle_path = None
        if skip_review:
            bundle_path = export_launch_bundle(
                workspace=resolved_workspace,
                controller=resolved_controller,
                task=resolved_task,
                lang=lang,
                planner_mode=planner_mode,
                plan=plan,
                output_path=output_bundle,
            )
            status = "sent"
        else:
            status = "planned"
        return UxLabResult(
            status=status,
            workspace=resolved_workspace,
            controller=resolved_controller,
            task=resolved_task,
            lang=lang,
            planner_mode=planner_mode,
            plan=plan,
            bundle_path=bundle_path,
        )

    app = _build_prompt_toolkit_app(
        config=config,
        cwd=Path(cwd).resolve(),
        workspace=resolved_workspace,
        controller=resolved_controller,
        task=resolved_task,
        lang=lang,
        skip_review=skip_review,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
    )
    return app.run()


def export_launch_bundle(
    *,
    workspace: Path,
    controller: str,
    task: str,
    lang: str,
    planner_mode: str,
    plan: Sequence[LabPlanItem],
    output_path: Optional[Path] = None,
) -> Path:
    """Persist the V1 launch bundle for later orchestration integration."""
    destination = output_path.expanduser().resolve() if output_path else _default_bundle_path(workspace)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "ux-lab-v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "controller": controller,
        "task": task,
        "lang": lang,
        "planner_mode": planner_mode,
        "plan": [asdict(item) for item in plan],
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def _resolve_task_text(*, task: Optional[str], task_file: Optional[Path]) -> str:
    if task_file is not None:
        return Path(task_file).expanduser().read_text(encoding="utf-8").strip()
    return str(task or "").strip()


def _enabled_agents(config: Config) -> list[str]:
    providers = getattr(config, "providers", {}) or {}
    enabled = [name for name, provider in providers.items() if getattr(provider, "enabled", False)]
    if not enabled:
        return list(DEFAULT_AGENTS)
    ordered = [agent for agent in DEFAULT_AGENTS if agent in enabled]
    for agent in enabled:
        if agent not in ordered:
            ordered.append(agent)
    return ordered


def _resolve_controller(controller: str, available_agents: Sequence[str]) -> str:
    if controller in available_agents:
        return controller
    return available_agents[0] if available_agents else "codex"


def _ordered_agents(controller: str, available_agents: Optional[Sequence[str]]) -> list[str]:
    ordered: list[str] = []
    for agent in [controller, *(available_agents or ()), *DEFAULT_AGENTS]:
        if agent and agent not in ordered:
            ordered.append(agent)
    while len(ordered) < 3:
        ordered.append(controller or "codex")
    return ordered[:3]


def _task_preview(task: str) -> str:
    normalized = " ".join(str(task or "").split())
    if not normalized:
        return "the requested task"
    if len(normalized) <= 56:
        return normalized
    return normalized[:53].rstrip() + "..."


def _agent_label(agent: str, lang: str) -> str:
    return AGENT_LABELS.get(resolve_lab_language(lang), AGENT_LABELS["en-US"]).get(agent, agent.title())


def _default_bundle_path(workspace: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return workspace / ".ai-collab" / "ux-lab" / f"bundle-{stamp}.json"


def _discover_workspace_candidates(cwd: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _push(path: Path) -> None:
        resolved = path.expanduser().resolve()
        if not resolved.is_dir() or resolved in seen:
            return
        candidates.append(resolved)
        seen.add(resolved)

    _push(cwd)
    if cwd.parent != cwd:
        _push(cwd.parent)

    home = Path.home()
    for name in ("Desktop", "Documents", "Downloads", "Projects", "Code", "Workspace"):
        path = home / name
        if path.exists():
            _push(path)

    for path in list(_safe_iterdirs(cwd.parent))[:12]:
        _push(path)

    for path in list(_safe_iterdirs(home))[:24]:
        _push(path)

    return candidates


def _safe_iterdirs(path: Path) -> list[Path]:
    try:
        items = [item for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")]
    except OSError:
        return []
    return sorted(items, key=lambda item: item.name.lower())


def _build_prompt_toolkit_app(
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
) -> "_UxLabPromptToolkitApp":
    return _UxLabPromptToolkitApp(
        config=config,
        cwd=cwd,
        workspace=workspace,
        controller=controller,
        task=task,
        lang=lang,
        skip_review=skip_review,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
    )


class _UxLabPromptToolkitApp:
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
    ) -> None:
        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, VSplit, Window
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.styles import Style
            from prompt_toolkit.widgets import Box, Button, Frame, RadioList, TextArea
        except ImportError as exc:  # pragma: no cover - dependency is present in runtime.
            raise RuntimeError("prompt_toolkit is required for ai-collab ux-lab") from exc

        self._Application = Application
        self._DynamicContainer = DynamicContainer
        self._HSplit = HSplit
        self._Layout = Layout
        self._VSplit = VSplit
        self._Window = Window
        self._FormattedTextControl = FormattedTextControl
        self._Style = Style
        self._Box = Box
        self._Button = Button
        self._Frame = Frame
        self._RadioList = RadioList
        self._TextArea = TextArea

        self.config = config
        self.cwd = cwd
        self.workspace = workspace
        self.lang = resolve_lab_language(lang)
        self.controller = controller
        self.planner_mode = planner_mode
        self.skip_review = skip_review
        self.output_bundle = output_bundle
        self.task_value = task
        self.available_agents = _enabled_agents(config)
        self.candidates = _discover_workspace_candidates(cwd)
        if self.workspace not in self.candidates:
            self.candidates.insert(0, self.workspace)
        self.filtered_candidates = list(self.candidates)
        self.status_message = ""
        self.screen = "workspace"
        self.planning_stage = 0
        self.plan: list[LabPlanItem] = []
        self.review_index = 0
        self.bundle_path: Optional[Path] = None
        self.result = UxLabResult(
            status="cancelled",
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=[],
        )

        self.controller_index = self.available_agents.index(self.controller) if self.controller in self.available_agents else 0

        self.workspace_query_input = self._TextArea(
            text="",
            multiline=False,
            height=1,
            prompt="> ",
        )
        self.workspace_manual_input = self._TextArea(
            text=str(self.workspace),
            multiline=False,
            height=1,
            prompt="> ",
        )
        self.workspace_list = self._RadioList(
            values=self._workspace_values(),
            default=str(self.workspace),
        )
        self.task_input = self._TextArea(
            text=self.task_value,
            multiline=True,
            scrollbar=True,
            wrap_lines=True,
        )
        self.review_title_input = self._TextArea(text="", multiline=False, height=1, prompt="> ")
        self.review_eta_input = self._TextArea(text="10", multiline=False, height=1, prompt="> ")
        self.review_done_input = self._TextArea(text="", multiline=True, height=5, prompt="> ")
        self.review_agent_list = self._RadioList(
            values=[(agent, _agent_label(agent, self.lang)) for agent in self.available_agents],
            default=self.controller,
        )

        self.workspace_query_input.buffer.on_text_changed += self._on_workspace_query_change

        self.use_current_button = self._Button(self._t("workspace_use_current"), handler=self._use_current_workspace, width=20)
        self.use_selected_button = self._Button(self._t("workspace_use_selected"), handler=self._use_selected_workspace, width=22)
        self.use_typed_button = self._Button(self._t("workspace_use_typed"), handler=self._use_typed_workspace, width=20)
        self.create_workspace_button = self._Button(self._t("workspace_create"), handler=self._create_workspace, width=16)
        self.controller_back_button = self._Button(self._t("back"), handler=self._go_workspace, width=14)
        self.controller_continue_button = self._Button(self._t("continue"), handler=self._go_task, width=14)
        self.task_back_button = self._Button(self._t("back"), handler=self._go_controller, width=14)
        self.task_continue_button = self._Button(self._t("continue"), handler=self._start_planning, width=14)
        self.nano_button = self._Button(self._t("open_nano"), handler=lambda: self._open_editor("nano"), width=16)
        self.vim_button = self._Button(self._t("open_vim"), handler=lambda: self._open_editor("vim"), width=16)
        self.review_prev_button = self._Button(self._t("review_prev"), handler=self._review_prev, width=16)
        self.review_next_button = self._Button(self._t("review_next"), handler=self._review_next, width=16)
        self.review_save_button = self._Button(self._t("review_save"), handler=self._save_review_item, width=18)
        self.review_add_button = self._Button(self._t("review_add"), handler=self._add_review_item, width=16)
        self.review_delete_button = self._Button(self._t("review_delete"), handler=self._delete_review_item, width=16)
        self.review_back_button = self._Button(self._t("back"), handler=self._go_task, width=14)
        self.review_send_button = self._Button(self._t("review_send"), handler=self._send_plan, width=14)
        self.sent_back_button = self._Button(self._t("send_back"), handler=self._go_review, width=18)
        self.sent_exit_button = self._Button(self._t("send_exit"), handler=self._exit_success, width=14)

        self.workspace_container = self._build_workspace_container()
        self.controller_container = self._build_controller_container()
        self.task_container = self._build_task_container()
        self.plan_container = self._build_plan_container()
        self.review_container = self._build_review_container()
        self.sent_container = self._build_sent_container()

        self.kb = KeyBindings()
        self._bind_keys()

        root = self._Box(
            body=self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._banner_fragments), height=len(ASCII_BANNER) + 2),
                    self._DynamicContainer(self._current_body),
                    self._Window(self._FormattedTextControl(self._footer_fragments), height=2),
                ]
            ),
            padding=1,
            style="class:app",
        )
        self.app = self._Application(
            layout=self._Layout(root),
            key_bindings=self.kb,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.15,
            style=self._build_style(),
        )
        self.status_message = self._t("workspace_ready", path=str(self.workspace))
        self._focus(self.use_current_button)

    def run(self) -> UxLabResult:
        return self.app.run()

    def _bind_keys(self) -> None:
        @self.kb.add("c-c")
        @self.kb.add("c-q")
        def _exit_early(event: Any) -> None:  # noqa: ANN401
            self._cancel(event)

        @self.kb.add("escape")
        def _go_back(event: Any) -> None:  # noqa: ANN401
            if self.screen == "controller":
                self._go_workspace()
            elif self.screen == "task":
                self._go_controller()
            elif self.screen == "review":
                self._go_task()
            elif self.screen == "sent":
                self._go_review()

        @self.kb.add("left")
        def _prev_controller(event: Any) -> None:  # noqa: ANN401
            if self.screen == "controller":
                self.controller_index = (self.controller_index - 1) % len(self.available_agents)
                self.controller = self.available_agents[self.controller_index]
                self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
                event.app.invalidate()

        @self.kb.add("right")
        def _next_controller(event: Any) -> None:  # noqa: ANN401
            if self.screen == "controller":
                self.controller_index = (self.controller_index + 1) % len(self.available_agents)
                self.controller = self.available_agents[self.controller_index]
                self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
                event.app.invalidate()

        @self.kb.add("f2")
        def _nano_shortcut(event: Any) -> None:  # noqa: ANN401
            if self.screen == "task":
                self._open_editor("nano")
                event.app.invalidate()

        @self.kb.add("f3")
        def _vim_shortcut(event: Any) -> None:  # noqa: ANN401
            if self.screen == "task":
                self._open_editor("vim")
                event.app.invalidate()

    def _build_style(self) -> Any:
        return self._Style.from_dict(
            {
                "app": "bg:#0b1321 #dbe7f5",
                "frame.border": "#243b53",
                "frame.label": "bold #f8fafc",
                "banner": "bold #7dd3fc",
                "muted": "#94a3b8",
                "status": "bold #f8fafc",
                "button": "bg:#172554 #e2e8f0",
                "button.focused": "bg:#0f766e #f8fafc bold",
                "radio": "#dbe7f5",
                "radio-selected": "bg:#12314d #f8fafc",
                "radio-checked": "bold #f8fafc",
                "text-area": "bg:#0f172a #e2e8f0",
                "agent-codex": "bold #67e8f9",
                "agent-claude": "bold #fdba74",
                "agent-gemini": "bold #86efac",
                "selected-row": "bg:#102a43 #f8fafc",
            }
        )

    def _banner_fragments(self) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        for line in ASCII_BANNER:
            lines.append(("class:banner", line + "\n"))
        lines.append(("class:muted", self._t("subtitle") + "\n"))
        lines.append(("class:muted", f"{self._t('workspace_current')}: {self.workspace}\n"))
        return lines

    def _footer_fragments(self) -> list[tuple[str, str]]:
        footer_key = {
            "workspace": "footer_workspace",
            "controller": "footer_controller",
            "task": "footer_task",
            "planning": "footer_plan",
            "review": "footer_review",
            "sent": "footer_send",
        }.get(self.screen, "footer_workspace")
        return [
            ("class:status", self.status_message + "\n"),
            ("class:muted", self._t(footer_key)),
        ]

    def _current_body(self) -> Any:
        mapping = {
            "workspace": self.workspace_container,
            "controller": self.controller_container,
            "task": self.task_container,
            "planning": self.plan_container,
            "review": self.review_container,
            "sent": self.sent_container,
        }
        return mapping[self.screen]

    def _build_workspace_container(self) -> Any:
        current_block = self._Window(self._FormattedTextControl(self._workspace_intro_fragments), height=4)
        return self._Frame(
            self._HSplit(
                [
                    current_block,
                    self._Frame(self.workspace_query_input, title=self._t("workspace_search")),
                    self._Frame(self.workspace_list, title=self._t("workspace_known")),
                    self._Frame(self.workspace_manual_input, title=self._t("workspace_manual")),
                    self._VSplit(
                        [
                            self.use_current_button,
                            self.use_selected_button,
                            self.use_typed_button,
                            self.create_workspace_button,
                        ],
                        padding=1,
                    ),
                ]
            ),
            title=self._t("workspace_title"),
        )

    def _build_controller_container(self) -> Any:
        return self._Frame(
            self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._controller_intro_fragments), height=3),
                    self._Frame(
                        self._Window(self._FormattedTextControl(self._controller_card_fragments), height=7),
                        title=self._t("controller_title"),
                    ),
                    self._Window(self._FormattedTextControl(self._controller_status_fragments), height=2),
                    self._VSplit([self.controller_back_button, self.controller_continue_button], padding=1),
                ]
            ),
            title=self._t("controller_title"),
        )

    def _build_task_container(self) -> Any:
        return self._Frame(
            self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._task_intro_fragments), height=3),
                    self._Frame(self.task_input, title=self._t("task_title")),
                    self._VSplit(
                        [
                            self.nano_button,
                            self.vim_button,
                            self.task_back_button,
                            self.task_continue_button,
                        ],
                        padding=1,
                    ),
                ]
            ),
            title=self._t("task_title"),
        )

    def _build_plan_container(self) -> Any:
        return self._Frame(
            self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._planning_fragments), height=10),
                ]
            ),
            title=self._t("plan_title"),
        )

    def _build_review_container(self) -> Any:
        detail_form = self._HSplit(
            [
                self._Window(self._FormattedTextControl(self._review_selected_fragments), height=2),
                self._Frame(self.review_title_input, title=self._t("field_title")),
                self._Frame(self.review_eta_input, title=self._t("field_eta")),
                self._Frame(self.review_done_input, title=self._t("field_done_when")),
                self._Frame(self.review_agent_list, title=self._t("field_agent")),
                self._VSplit(
                    [
                        self.review_prev_button,
                        self.review_next_button,
                        self.review_save_button,
                        self.review_add_button,
                        self.review_delete_button,
                    ],
                    padding=1,
                ),
                self._VSplit([self.review_back_button, self.review_send_button], padding=1),
            ]
        )
        return self._Frame(
            self._VSplit(
                [
                    self._Frame(
                        self._Window(self._FormattedTextControl(self._review_table_fragments)),
                        title=self._t("review_table"),
                    ),
                    self._Frame(detail_form, title=self._t("review_detail")),
                ],
                padding=1,
            ),
            title=self._t("review_title"),
        )

    def _build_sent_container(self) -> Any:
        return self._Frame(
            self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._sent_fragments), height=7),
                    self._VSplit([self.sent_back_button, self.sent_exit_button], padding=1),
                ]
            ),
            title=self._t("send_title"),
        )

    def _workspace_intro_fragments(self) -> list[tuple[str, str]]:
        return [
            ("", f"{self._t('workspace_current')}: {self.cwd}\n"),
            ("", self._t("workspace_question") + "\n"),
            ("class:muted", self._t("workspace_search")),
        ]

    def _controller_intro_fragments(self) -> list[tuple[str, str]]:
        return [
            ("", self._t("controller_prompt") + "\n"),
            (AGENT_STYLE.get(self.controller, "class:status"), self._t("controller_selected", name=_agent_label(self.controller, self.lang))),
        ]

    def _controller_card_fragments(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for index, agent in enumerate(self.available_agents):
            selected = index == self.controller_index
            prefix = "▶ " if selected else "  "
            style = AGENT_STYLE.get(agent, "")
            if selected:
                style = f"{style} class:selected-row".strip()
            fragments.append((style, f"{prefix}[ { _agent_label(agent, self.lang) } ]  "))
        fragments.append(("", "\n\n"))
        fragments.append(("class:muted", self._t("controller_prompt")))
        return fragments

    def _controller_status_fragments(self) -> list[tuple[str, str]]:
        return [
            (AGENT_STYLE.get(self.controller, "class:status"), self._t("controller_selected", name=_agent_label(self.controller, self.lang)))
        ]

    def _task_intro_fragments(self) -> list[tuple[str, str]]:
        return [
            ("", self._t("task_prompt") + "\n"),
            ("class:muted", "/nano  /vim"),
        ]

    def _planning_fragments(self) -> list[tuple[str, str]]:
        stages = [
            self._t("plan_status_prepare"),
            self._t("plan_status_plan"),
            self._t("plan_status_render"),
        ]
        fragments: list[tuple[str, str]] = []
        for index, label in enumerate(stages):
            marker = "●" if index <= self.planning_stage else "○"
            style = "class:status" if index <= self.planning_stage else "class:muted"
            fragments.append((style, f"{marker} {label}\n"))
        return fragments

    def _review_table_fragments(self) -> list[tuple[str, str]]:
        if not self.plan:
            return [("class:muted", "No plan items yet.")]

        fragments: list[tuple[str, str]] = [("class:muted", "SX   Agent     ETA   Title\n")]
        for index, item in enumerate(self.plan):
            row_style = "class:selected-row " if index == self.review_index else ""
            agent_style = AGENT_STYLE.get(item.agent, "")
            fragments.append(
                (f"{row_style}{agent_style}".strip(), f"{item.sx:<4} {item.agent:<8} {item.eta_minutes:>3}m  {item.title}\n")
            )
            fragments.append(("class:muted", f"     {item.done_when}\n\n"))
        return fragments

    def _review_selected_fragments(self) -> list[tuple[str, str]]:
        if not self.plan:
            return [("class:muted", "")]
        item = self.plan[self.review_index]
        return [
            ("class:status", f"{item.sx}  "),
            (AGENT_STYLE.get(item.agent, "class:status"), _agent_label(item.agent, self.lang)),
        ]

    def _sent_fragments(self) -> list[tuple[str, str]]:
        path_line = self._t("send_path", path=str(self.bundle_path)) if self.bundle_path else ""
        return [
            ("", self._t("send_body") + "\n\n"),
            ("class:status", path_line),
        ]

    def _workspace_values(self) -> list[tuple[str, str]]:
        values = [(str(path), str(path)) for path in self.filtered_candidates]
        return values or [(str(self.cwd), str(self.cwd))]

    def _on_workspace_query_change(self, _buffer: Any) -> None:  # noqa: ANN401
        self.filtered_candidates = filter_workspace_candidates(self.candidates, self.workspace_query_input.text)
        values = self._workspace_values()
        self.workspace_list.values = values
        self.workspace_list.current_value = values[0][0]
        self.workspace_list._selected_index = 0
        self.app.invalidate()

    def _use_current_workspace(self) -> None:
        self.workspace = self.cwd
        self.workspace_manual_input.buffer.text = str(self.workspace)
        self.status_message = self._t("workspace_ready", path=str(self.workspace))
        self._go_controller()

    def _use_selected_workspace(self) -> None:
        selected = Path(str(self.workspace_list.current_value)).expanduser()
        if not selected.exists():
            self.status_message = self._t("workspace_invalid")
            return
        self.workspace = selected.resolve()
        self.workspace_manual_input.buffer.text = str(self.workspace)
        self.status_message = self._t("workspace_ready", path=str(self.workspace))
        self._go_controller()

    def _use_typed_workspace(self) -> None:
        typed = Path(self.workspace_manual_input.text.strip()).expanduser()
        if not typed.is_dir():
            self.status_message = self._t("workspace_missing")
            return
        self.workspace = typed.resolve()
        self.status_message = self._t("workspace_ready", path=str(self.workspace))
        self._go_controller()

    def _create_workspace(self) -> None:
        typed = Path(self.workspace_manual_input.text.strip()).expanduser()
        if not typed:
            self.status_message = self._t("workspace_invalid")
            return
        typed.mkdir(parents=True, exist_ok=True)
        self.workspace = typed.resolve()
        if self.workspace not in self.candidates:
            self.candidates.insert(0, self.workspace)
            self.filtered_candidates = filter_workspace_candidates(self.candidates, self.workspace_query_input.text)
        self.status_message = self._t("workspace_created", path=str(self.workspace))
        self._go_controller()

    def _go_workspace(self) -> None:
        self.screen = "workspace"
        self.status_message = self._t("workspace_ready", path=str(self.workspace))
        self._focus(self.use_current_button)
        self.app.invalidate()

    def _go_controller(self) -> None:
        self.screen = "controller"
        self.controller_index = self.available_agents.index(self.controller) if self.controller in self.available_agents else 0
        self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
        self._focus(self.controller_continue_button)
        self.app.invalidate()

    def _go_task(self) -> None:
        self.screen = "task"
        self.status_message = self._t("task_prompt")
        self._focus(self.task_input)
        self.app.invalidate()

    def _go_review(self) -> None:
        self.screen = "review"
        self._load_review_item(self.review_index)
        self.status_message = self._t("plan_ready")
        self._focus(self.review_title_input)
        self.app.invalidate()

    def _start_planning(self) -> None:
        editor = parse_task_editor_command(self.task_input.text)
        if editor is not None:
            self._open_editor(editor)
            return

        self.task_value = self.task_input.text.strip()
        if not self.task_value:
            self.status_message = self._t("task_required")
            return

        self.screen = "planning"
        self.status_message = self._t("plan_status_prepare")
        self.planning_stage = 0
        self.app.invalidate()
        self.app.create_background_task(self._run_mock_planner())

    async def _run_mock_planner(self) -> None:
        import asyncio

        await asyncio.sleep(0.35)
        self.planning_stage = 1
        self.status_message = self._t("plan_status_plan")
        self.app.invalidate()
        await asyncio.sleep(0.45)
        self.planning_stage = 2
        self.status_message = self._t("plan_status_render")
        self.app.invalidate()
        await asyncio.sleep(0.3)
        self.plan = build_mock_plan(
            self.task_value,
            self.controller,
            self.lang,
            available_agents=self.available_agents,
        )
        self.review_index = 0
        self._load_review_item(0)
        self.status_message = self._t("plan_ready")
        if self.skip_review:
            self._send_plan()
            return
        self.screen = "review"
        self._focus(self.review_title_input)
        self.app.invalidate()

    def _open_editor(self, editor: str) -> None:
        if shutil.which(editor) is None:
            self.status_message = self._t("task_editor_missing", editor=editor)
            return
        self.app.create_background_task(self._open_editor_async(editor))

    async def _open_editor_async(self, editor: str) -> None:
        from prompt_toolkit.application import run_in_terminal

        def _run() -> str:
            with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as handle:
                seed = self.task_input.text.strip()
                if parse_task_editor_command(seed) is not None:
                    seed = ""
                handle.write(seed)
                handle.flush()
                temp_path = Path(handle.name)
            try:
                subprocess.run([editor, str(temp_path)], check=False)
                return temp_path.read_text(encoding="utf-8")
            finally:
                temp_path.unlink(missing_ok=True)

        content = await run_in_terminal(_run, render_cli_done=True)
        self.task_input.buffer.text = content.rstrip()
        self.status_message = self._t("task_editor_loaded")
        self._focus(self.task_input)
        self.app.invalidate()

    def _load_review_item(self, index: int) -> None:
        if not self.plan:
            return
        self.review_index = max(0, min(index, len(self.plan) - 1))
        item = self.plan[self.review_index]
        self.review_title_input.buffer.text = item.title
        self.review_eta_input.buffer.text = str(item.eta_minutes)
        self.review_done_input.buffer.text = item.done_when
        self.review_agent_list.current_value = item.agent
        for idx, (value, _label) in enumerate(self.review_agent_list.values):
            if value == item.agent:
                self.review_agent_list._selected_index = idx
                break

    def _save_review_item(self) -> None:
        if not self.plan:
            return
        eta_raw = self.review_eta_input.text.strip()
        if not eta_raw.isdigit() or int(eta_raw) <= 0:
            self.status_message = self._t("review_bad_eta")
            return
        current = self.plan[self.review_index]
        current.title = self.review_title_input.text.strip() or current.title
        current.done_when = self.review_done_input.text.strip() or current.done_when
        current.eta_minutes = int(eta_raw)
        current.agent = str(self.review_agent_list.current_value)
        self.status_message = self._t("review_saved")
        self.app.invalidate()

    def _review_prev(self) -> None:
        if not self.plan:
            return
        self._save_review_item()
        self._load_review_item((self.review_index - 1) % len(self.plan))
        self.app.invalidate()

    def _review_next(self) -> None:
        if not self.plan:
            return
        self._save_review_item()
        self._load_review_item((self.review_index + 1) % len(self.plan))
        self.app.invalidate()

    def _add_review_item(self) -> None:
        sx = f"S{len(self.plan) + 1}"
        self.plan.append(
            LabPlanItem(
                sx=sx,
                title=f"{sx} draft",
                agent=self.controller,
                eta_minutes=10,
                done_when="",
            )
        )
        self._renumber_plan()
        self._load_review_item(len(self.plan) - 1)
        self.status_message = self._t("review_added")
        self.app.invalidate()

    def _delete_review_item(self) -> None:
        if len(self.plan) <= 1:
            self.status_message = self._t("review_keep_one")
            return
        del self.plan[self.review_index]
        self._renumber_plan()
        self._load_review_item(max(0, self.review_index - 1))
        self.status_message = self._t("review_deleted")
        self.app.invalidate()

    def _renumber_plan(self) -> None:
        for index, item in enumerate(self.plan, start=1):
            item.sx = f"S{index}"

    def _send_plan(self) -> None:
        if self.screen == "review":
            self._save_review_item()
        self.bundle_path = export_launch_bundle(
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=self.plan,
            output_path=self.output_bundle,
        )
        self.result = UxLabResult(
            status="sent",
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=list(self.plan),
            bundle_path=self.bundle_path,
        )
        self.screen = "sent"
        self.status_message = self._t("send_path", path=str(self.bundle_path))
        self._focus(self.sent_exit_button)
        self.app.invalidate()

    def _exit_success(self) -> None:
        self.app.exit(result=self.result)

    def _cancel(self, event: Any) -> None:  # noqa: ANN401
        cancelled = UxLabResult(
            status="cancelled",
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=list(self.plan),
            bundle_path=self.bundle_path,
        )
        event.app.exit(result=cancelled)

    def _focus(self, element: Any) -> None:  # noqa: ANN401
        try:
            self.app.layout.focus(element)
        except Exception:  # noqa: BLE001
            return

    def _t(self, key: str, **kwargs: Any) -> str:  # noqa: ANN401
        table = LAB_TEXT.get(self.lang, LAB_TEXT["en-US"])
        return str(table.get(key, key)).format(**kwargs)
