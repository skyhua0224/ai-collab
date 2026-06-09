"""
Experimental fullscreen UX lab V3 for ai-collab.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import textwrap
from typing import Any, Callable, Optional, Sequence

from ai_collab.core.config import Config, resolve_collaboration_role_leads
from ai_collab.core.run_state import RunStateStore
from ai_collab.core.workflow_v2 import resolve_session_preset

SUPPORTED_LANGS = ("en-US", "zh-CN")
DEFAULT_AGENTS = ("codex", "claude", "gemini")
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

TEXT = {
    "en-US": {
        "subtitle": "Controller-first orchestration lab",
        "workspace_title": "Step 1 · Workspace",
        "workspace_help": "Left/Right switches source. Press Enter / Space to continue, or use Continue. Press : for a full path or `/new <path>`.",
        "controller_title": "Step 2 · Controller",
        "controller_help": "Use Left/Right to switch, or type codex / claude / gemini and press Enter.",
        "task_title": "Step 3 · Task",
        "task_help": "Edit the task in the main editor. Use the command bar for `/plan`, `/nano`, `/vim`, `/back`.",
        "planning_title": "Step 4 · Planning",
        "planning_help": "The controller is being asked for structured JSON. No implicit fallback is allowed.",
        "planning_summary_title": "Planning request",
        "planning_status_title": "Status",
        "planning_events_title": "Recent events",
        "planning_task_label": "Task",
        "planning_workspace_label": "Workspace",
        "planning_controller_label": "Controller",
        "planning_elapsed_label": "Elapsed",
        "planning_steps_label": "Planned steps",
        "planning_next_label": "Next",
        "planning_stage_prepare": "Preparing prompt",
        "planning_stage_call": "Calling controller",
        "planning_stage_wait": "Waiting for structured plan",
        "planning_stage_done": "Plan received",
        "planning_escape_hint": "Esc returns to the task screen after planning finishes. Ctrl-C exits immediately.",
        "review_title": "Step 5 · Review Plan",
        "review_help": "Use Up/Down to select steps. Use `/title`, `/done`, `/eta`, `/agent`, `/create`, `/delete`, `/send`.",
        "error_title": "Step 4 · Planning Failed",
        "error_help": "Use `/retry` to call the controller again or `/task` to go back.",
        "sent_title": "Step 6 · Bundle Ready",
        "sent_help": "V3 stops at bundle export so the UX can be validated before tmux wiring.",
        "workspace_current": "Current directory",
        "workspace_selected": "Target workspace",
        "workspace_candidates": "Candidate folders",
        "workspace_enter_uses": "Enter will use",
        "workspace_filter": "Filter",
        "workspace_missing": "That path does not exist. Use `/new <path>` if you want to create it.",
        "workspace_created": "Created workspace folder: {path}",
        "workspace_ready": "Workspace selected: {path}",
        "controller_selected": "Controller: {name}",
        "task_missing": "Task cannot be empty.",
        "task_editor_loaded": "Editor content loaded back into the task editor.",
        "task_editor_missing": "{editor} is not available in PATH.",
        "planning_prepare": "Preparing the controller planning prompt",
        "planning_call": "Calling the controller in non-interactive JSON mode",
        "planning_ready": "Plan received. Review before send.",
        "planning_failed": "Planning failed: {error}",
        "review_saved": "Updated {field} for {step}.",
        "review_saved_form": "Saved the current step.",
        "review_created": "Added {step}.",
        "review_deleted": "Deleted {step}.",
        "review_keep_one": "Keep at least one step in the plan.",
        "review_bad_eta": "ETA must be a positive integer.",
        "review_unknown": "Unknown command. Use /title, /done, /eta, /agent, /create, /delete, /send.",
        "input_workspace": "Workspace command bar",
        "input_controller": "Quick switch or continue",
        "input_task": "Command bar (/plan /nano /vim /back)",
        "input_planning": "Planning status",
        "input_review": "Quick actions (/create /delete /save /send /task)",
        "input_error": "Recovery command bar",
        "input_sent": "Finish command bar",
        "footer": "Tab toggles editor focus · Enter submits the bottom bar · F5 or Ctrl-S plans · Ctrl-C exits",
        "planner_live": "Planner mode: live",
        "planner_mock": "Planner mode: mock",
        "send_done": "Bundle exported to {path}",
        "send_exit": "Type /exit or press Enter to close this screen.",
        "review_column_header": "SX   Agent    ETA   Title",
        "review_detail_title": "Selected step",
        "review_detail_done": "Done when",
        "detail_title_label": "Title",
        "detail_agent_label": "Owner",
        "detail_eta_label": "ETA",
        "detail_workspace_label": "Workspace",
        "detail_task_lines_label": "Task lines",
        "detail_command_examples": "Examples",
        "review_step_count": "{count} step(s)",
        "review_list_title": "Plan list",
        "review_detail_meta": "{sx} · {agent} · {eta}m",
        "workspace_no_matches": "(no matching folders)",
    },
    "zh-CN": {
        "subtitle": "主控优先编排实验场",
        "workspace_title": "第 1 步 · 工作目录",
        "workspace_help": "左右键切换来源；Enter / Space 直接继续，也可以点 Continue。按 : 输入完整路径，或用 `/new <路径>` 新建目录。",
        "controller_title": "第 2 步 · 选择主控",
        "controller_help": "使用左右键切换，或直接输入 codex / claude / gemini 再按 Enter。",
        "task_title": "第 3 步 · 输入任务",
        "task_help": "在主编辑区编写任务。底部命令栏用于 `/plan`、`/nano`、`/vim`、`/back`。",
        "planning_title": "第 4 步 · 主控规划",
        "planning_help": "正在请求主控返回结构化 JSON。不会发生隐式 fallback。",
        "planning_summary_title": "本次规划请求",
        "planning_status_title": "当前状态",
        "planning_events_title": "最近事件",
        "planning_task_label": "任务",
        "planning_workspace_label": "工作目录",
        "planning_controller_label": "主控",
        "planning_elapsed_label": "耗时",
        "planning_steps_label": "计划步骤数",
        "planning_next_label": "下一步",
        "planning_stage_prepare": "准备提示词",
        "planning_stage_call": "调用主控",
        "planning_stage_wait": "等待结构化计划返回",
        "planning_stage_done": "已收到计划",
        "planning_escape_hint": "规划完成后可用 Esc 返回任务页。Ctrl-C 会立即退出。",
        "review_title": "第 5 步 · 检查计划",
        "review_help": "上下键选择步骤。使用 `/title`、`/done`、`/eta`、`/agent`、`/create`、`/delete`、`/send`。",
        "error_title": "第 4 步 · 规划失败",
        "error_help": "输入 `/retry` 重新请求主控，或输入 `/task` 返回任务页。",
        "sent_title": "第 6 步 · Bundle 已生成",
        "sent_help": "V3 先停在 bundle 导出阶段，先验证交互，再接 tmux。",
        "workspace_current": "当前目录",
        "workspace_selected": "目标工作目录",
        "workspace_candidates": "候选目录",
        "workspace_enter_uses": "直接 Enter 将使用",
        "workspace_filter": "筛选",
        "workspace_missing": "该路径不存在。如果要创建，请使用 `/new <路径>`。",
        "workspace_created": "已创建工作目录：{path}",
        "workspace_ready": "已选择工作目录：{path}",
        "controller_selected": "当前主控：{name}",
        "task_missing": "任务内容不能为空。",
        "task_editor_loaded": "编辑器内容已经回填到任务编辑区。",
        "task_editor_missing": "PATH 中没有找到 {editor}。",
        "planning_prepare": "正在准备主控规划提示词",
        "planning_call": "正在以非交互 JSON 模式调用主控",
        "planning_ready": "计划已返回，请检查后再发送。",
        "planning_failed": "规划失败：{error}",
        "review_saved": "已更新 {step} 的 {field}。",
        "review_saved_form": "已保存当前步骤。",
        "review_created": "已新增 {step}。",
        "review_deleted": "已删除 {step}。",
        "review_keep_one": "计划里至少保留一个步骤。",
        "review_bad_eta": "预计耗时必须是正整数。",
        "review_unknown": "未知命令。可使用 /title、/done、/eta、/agent、/create、/delete、/send。",
        "input_workspace": "工作目录命令栏",
        "input_controller": "快速切换 / 继续",
        "input_task": "命令栏（/plan /nano /vim /back）",
        "input_planning": "规划状态",
        "input_review": "快捷操作栏（/create /delete /save /send /task）",
        "input_error": "恢复命令栏",
        "input_sent": "结束命令栏",
        "footer": "Tab 切换编辑区焦点 · Enter 提交底部输入栏 · F5 或 Ctrl-S 开始规划 · Ctrl-C 退出",
        "planner_live": "规划器模式：live",
        "planner_mock": "规划器模式：mock",
        "send_done": "Bundle 已导出到 {path}",
        "send_exit": "输入 /exit 或直接按 Enter 关闭本页。",
        "review_column_header": "SX   Agent    ETA   标题",
        "review_detail_title": "当前步骤",
        "review_detail_done": "完成标准",
        "detail_title_label": "标题",
        "detail_agent_label": "执行 Agent",
        "detail_eta_label": "预计耗时",
        "detail_workspace_label": "工作目录",
        "detail_task_lines_label": "任务行数",
        "detail_command_examples": "命令示例",
        "review_step_count": "共 {count} 个步骤",
        "review_list_title": "步骤列表",
        "review_detail_meta": "{sx} · {agent} · {eta} 分钟",
        "workspace_no_matches": "（没有匹配目录）",
    },
}

AGENT_LABELS = {
    "en-US": {"codex": "Codex", "claude": "Claude", "gemini": "Gemini"},
    "zh-CN": {"codex": "Codex", "claude": "Claude", "gemini": "Gemini"},
}

AGENT_STYLES = {
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
class ControllerCard:
    agent: str
    title: str
    summary: str
    detail: str
    selected: bool


@dataclass
class WorkspaceSubmission:
    kind: str
    path: Optional[Path] = None
    query: str = ""


@dataclass
class ReviewCommand:
    action: str
    value: str = ""


@dataclass
class CommandBarState:
    placeholder: str
    help_text: str
    value: str = ""


@dataclass
class UxLabV3Result:
    status: str
    workspace: Path
    controller: str
    task: str
    lang: str
    planner_mode: str
    plan: list[LabPlanItem]
    bundle_path: Optional[Path] = None
    error_message: Optional[str] = None
    controller_plan: Optional[dict[str, Any]] = None
    execution_mode: str = "single-agent"
    orchestration_plan: list[dict[str, str]] = field(default_factory=list)
    selected_agents: list[str] = field(default_factory=list)
    available_agents: list[dict[str, str]] = field(default_factory=list)


@dataclass
class WorkspaceSessionRecord:
    run_id: str
    created_at: str
    updated_at: str
    controller: str
    phase: str
    phase_detail: str
    mode: str
    session: str
    helper_count: int
    task_preview: str = ""
    tmux_available: Optional[bool] = None


def resolve_v3_language(config_lang: Optional[str]) -> str:
    if config_lang in SUPPORTED_LANGS:
        return str(config_lang)
    return "en-US"


def _resolve_v2_prompt_defaults(config: Optional[Config]) -> tuple[str, str]:
    preset = "auto"
    if config is not None:
        auto_cfg = config.auto_collaboration or {}
        if isinstance(auto_cfg, dict):
            preset = str(auto_cfg.get("default_session_preset", "auto")).strip() or "auto"
    try:
        blueprint = resolve_session_preset(preset).workflow_key
    except KeyError:
        preset = "auto"
        blueprint = resolve_session_preset(preset).workflow_key
    return preset, blueprint


def build_brand_banner(width: int, lang: str) -> list[str]:
    runtime_lang = resolve_v3_language(lang)
    subtitle = TEXT[runtime_lang]["subtitle"]
    if width < 60:
        return ["ai-collab", subtitle]
    if width >= 160:
        banner = [
            "   █████╗ ██╗        ██████╗ ██████╗ ██╗     ██╗      █████╗ ██████╗ ",
            "  ██╔══██╗██║       ██╔════╝██╔═══██╗██║     ██║     ██╔══██╗██╔══██╗",
            "  ███████║██║       ██║     ██║   ██║██║     ██║     ███████║██████╔╝",
            "  ██╔══██║██║       ██║     ██║   ██║██║     ██║     ██╔══██║██╔══██╗",
            "  ██║  ██║██║       ╚██████╗╚██████╔╝███████╗███████╗██║  ██║██████╔╝",
            "  ╚═╝  ╚═╝╚═╝        ╚═════╝ ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝ ",
            subtitle,
        ]
        return [line[:width] for line in banner]
    if width >= 100:
        banner = [
            "    _    ___      ___      _ _       _",
            "   / \\  |_ _|    / __|___ | | | __ _| |__",
            "  / _ \\  | |    | (__/ _ \\| | |/ _` | '_ \\",
            " /_/ \\_\\|___|    \\___\\___/|_|_|\\__,_|_.__/",
            subtitle,
        ]
        return [line[:width] for line in banner]
    line = f"  _    ___      ___      _ _       _   {subtitle}"
    if len(line) <= width:
        return [line]
    return ["ai-collab", subtitle[:width]]


def choose_review_layout(width: int) -> str:
    return "split" if width >= 120 else "stack"


def choose_workspace_layout(width: int) -> str:
    return "split" if width >= 100 else "stack"


def build_workspace_summary_lines(
    *,
    cwd: Path,
    selected: Path,
    mode: str,
    width: int,
    lang: str,
) -> list[str]:
    runtime_lang = resolve_v3_language(lang)
    mode_labels = {
        "en-US": {"current": "Current", "recent": "Recent", "tree": "Tree"},
        "zh-CN": {"current": "当前目录", "recent": "最近使用", "tree": "目录树"},
    }[runtime_lang]
    if runtime_lang == "zh-CN":
        return [
            _fit_width(f"当前: {Path(cwd).expanduser().resolve()}", width),
            _fit_width(f"选择: {Path(selected).expanduser().resolve()}   模式: {mode_labels.get(mode, mode)}", width),
        ]
    return [
        _fit_width(f"Current: {Path(cwd).expanduser().resolve()}", width),
        _fit_width(f"Selected: {Path(selected).expanduser().resolve()}   Mode: {mode_labels.get(mode, mode)}", width),
    ]


def build_workspace_hint_line(*, mode: str, width: int, lang: str) -> str:
    runtime_lang = resolve_v3_language(lang)
    hints = {
        "en-US": {
            "current": "[←→] source  [Enter/Space] continue  [:] full path",
            "recent": "[←→] source  [↑↓] move  [Enter/Space] continue  [:] filter",
            "tree": "[←→] source  [Enter] expand  [Space] continue  [:] full path",
        },
        "zh-CN": {
            "current": "[←→] 切换来源  [Enter/Space] 继续  [:] 完整路径",
            "recent": "[←→] 切换来源  [↑↓] 移动  [Enter/Space] 继续  [:] 筛选",
            "tree": "[←→] 切换来源  [Enter] 展开  [Space] 继续  [:] 完整路径",
        },
    }[runtime_lang]
    return _fit_width(hints.get(mode, hints["current"]), width)


def build_workspace_preview_lines(
    *,
    selected: Path,
    mode: str,
    width: int,
    lang: str,
    child_limit: int = 8,
) -> list[str]:
    runtime_lang = resolve_v3_language(lang)
    selected_path = Path(selected).expanduser().resolve()
    is_dir = selected_path.is_dir()
    try:
        stat_result = selected_path.stat()
        modified = datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        modified = "-"

    try:
        children = sorted(
            selected_path.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        ) if is_dir else []
    except OSError:
        children = []

    child_count = len(children)

    if runtime_lang == "zh-CN":
        lines = [
            _fit_width(str(selected_path), width),
            _fit_width(f"{'目录' if is_dir else '文件'} · {child_count} 项 · 更新于 {modified}", width),
            "",
        ]
        if not is_dir:
            lines.append(_fit_width("当前选中项不是目录。", width))
            return lines
        if not children:
            lines.append(_fit_width("（空目录）", width))
            return lines
        lines.append(_fit_width("内容", width))
        for child in children[: max(1, child_limit)]:
            suffix = "/" if child.is_dir() else ""
            lines.append(_fit_width(f"• {child.name}{suffix}", width))
        if child_count > child_limit:
            lines.append(_fit_width(f"... 还有 {child_count - child_limit} 项", width))
        return lines

    lines = [
        _fit_width(str(selected_path), width),
        _fit_width(f"{'Directory' if is_dir else 'File'} · {child_count} items · Updated {modified}", width),
        "",
    ]
    if not is_dir:
        lines.append(_fit_width("The current selection is not a directory.", width))
        return lines
    if not children:
        lines.append(_fit_width("(empty directory)", width))
        return lines
    lines.append(_fit_width("Contents", width))
    for child in children[: max(1, child_limit)]:
        suffix = "/" if child.is_dir() else ""
        lines.append(_fit_width(f"• {child.name}{suffix}", width))
    if child_count > child_limit:
        lines.append(_fit_width(f"... {child_count - child_limit} more", width))
    return lines


def _display_workspace_path(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    home = Path.home().expanduser().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return "~" if str(relative) == "." else f"~/{relative}"


def build_workspace_session_lines(
    *,
    selected: Path,
    width: int,
    lang: str,
    records: Optional[Sequence[WorkspaceSessionRecord]] = None,
    limit: int = 4,
) -> list[str]:
    runtime_lang = resolve_v3_language(lang)
    selected_path = Path(selected).expanduser().resolve()
    if records is None:
        runs = RunStateStore.list_runs(cwd=selected_path, limit=max(1, int(limit)))
    else:
        runs = []

    run_count = len(runs)
    kind = _workspace_kind_label(selected_path, runtime_lang)
    path_display = _display_workspace_path(selected_path)
    lines = [
        _fit_width("工作区" if runtime_lang == "zh-CN" else "Workspace", width),
        _fit_width(path_display, width),
        _fit_width(
            (f"{kind} · {run_count} 个可恢复运行" if runtime_lang == "zh-CN" else f"{kind} · {run_count} resumable runs"),
            width,
        ),
        "",
        _fit_width("恢复候选" if runtime_lang == "zh-CN" else "Resume Candidates", width),
    ]

    if not runs:
        lines.extend(
            [
                "",
                _fit_width("暂无可恢复运行" if runtime_lang == "zh-CN" else "No resumable runs yet", width),
                _fit_width(
                    "运行 `ai-collab resume list -w <目录>` 后会显示在这里"
                    if runtime_lang == "zh-CN"
                    else "Run `ai-collab resume list -w <path>` and entries will appear here",
                    width,
                ),
            ]
        )
        return lines

    header = _workspace_resume_header(width=width, lang=runtime_lang)
    if header:
        lines.append(header)
    for item in runs[: max(1, int(limit))]:
        lines.extend(_workspace_resume_row_lines(item=item, width=width, lang=runtime_lang, workspace=selected_path))
    return lines


def _workspace_kind_label(path: Path, lang: str) -> str:
    if (path / ".git").exists():
        return "Git 仓库" if lang == "zh-CN" else "Git repo"
    return "目录" if lang == "zh-CN" else "Folder"


def _workspace_resume_header(*, width: int, lang: str) -> str:
    if width < 54:
        return ""
    id_w = 8
    name_w = max(10, min(18, width - 34))
    status_w = 9
    updated_w = 7
    title_name = "名称" if lang == "zh-CN" else "Name"
    title_status = "状态" if lang == "zh-CN" else "Status"
    title_updated = "更新" if lang == "zh-CN" else "Updated"
    return _fit_width(
        f"{'ID':<{id_w}}  {title_name:<{name_w}}  {title_status:<{status_w}}  {title_updated:<{updated_w}}",
        width,
    )


def _workspace_resume_row_lines(*, item: dict[str, Any], width: int, lang: str, workspace: Path) -> list[str]:
    short_id = str(item.get("short_id", "") or "-")
    name = str(item.get("name", "") or short_id or "-")
    status = str(item.get("status", "") or "-")
    updated = _compact_age(str(item.get("updated_at", "")), lang=lang)
    steps = str(item.get("steps_progress", "") or item.get("sx", "") or "No steps")
    mode = str(item.get("mode", "") or "-")
    prompt = str(item.get("entry_prompt_preview", "") or "").strip()
    if not prompt:
        run_id = str(item.get("run_id", "") or "").strip()
        if run_id:
            prompt = _load_workspace_run_task_preview(workspace / '.ai-collab' / 'runs' / run_id / 'events.jsonl')
    if not prompt:
        prompt = str(item.get("phase_detail", "") or "-").strip()

    if width < 54:
        lines = [
            _fit_width(f"{short_id}  {status}  {updated}", width),
            _fit_width(f"{name} · {steps} · {mode}", width),
        ]
        wrapped = _wrap_inline_text(prompt, width, max_lines=1)
        lines.extend(_fit_width(piece, width) for piece in wrapped)
        lines.append("")
        return lines

    id_w = 8
    name_w = max(10, min(18, width - 34))
    status_w = 9
    updated_w = 7
    lead = _fit_width(f"{short_id:<{id_w}}  {name:<{name_w}}  {status:<{status_w}}  {updated:<{updated_w}}", width)
    detail = _fit_width(f"{' ' * (id_w + 2)}{steps} · {mode}", width)
    lines = [lead, detail]
    wrapped = _wrap_inline_text(prompt, max(12, width - (id_w + 2)), max_lines=1 if width < 64 else 2)
    for piece in wrapped:
        lines.append(_fit_width(f"{' ' * (id_w + 2)}{piece}", width))
    lines.append("")
    return lines


def _compact_age(value: str, *, lang: str) -> str:
    raw = str(value).strip()
    if not raw:
        return "-"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:7]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds()))
    if delta < 60:
        return "刚刚" if lang == "zh-CN" else "now"
    minutes = delta // 60
    if minutes < 60:
        return f"{minutes}分前" if lang == "zh-CN" else f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前" if lang == "zh-CN" else f"{hours}h"
    days = hours // 24
    return f"{days}天前" if lang == "zh-CN" else f"{days}d"


def build_step_track(screen: str, lang: str, width: int) -> list[str]:
    runtime_lang = resolve_v3_language(lang)
    labels = {
        "en-US": {
            "workspace": "Workspace",
            "controller": "Controller",
            "task": "Task",
            "planning": "Planning",
            "review": "Review",
            "sent": "Bundle",
        },
        "zh-CN": {
            "workspace": "工作目录",
            "controller": "主控",
            "task": "任务",
            "planning": "规划",
            "review": "检查",
            "sent": "Bundle",
        },
    }[runtime_lang]
    current = "planning" if screen == "error" else screen
    ordered = ["workspace", "controller", "task", "planning", "review", "sent"]
    if width < 78:
        index = ordered.index(current) + 1 if current in ordered else 1
        return [_fit_width(f"【{index:02d} {labels.get(current, labels['workspace'])}】", width)]

    pieces: list[str] = []
    for index, step in enumerate(ordered, start=1):
        label = f"{index:02d} {labels[step]}"
        pieces.append(f"【{label}】" if step == current else label)
    line = "  ".join(pieces)
    if len(line) <= width:
        return [line]
    return [_fit_width("  ".join(pieces[:3]), width), _fit_width("  ".join(pieces[3:]), width)]


def build_controller_cards(selected: str, lang: str) -> list[ControllerCard]:
    runtime_lang = resolve_v3_language(lang)
    selected_agent = selected if selected in DEFAULT_AGENTS else DEFAULT_AGENTS[0]
    copy = {
        "en-US": {
            "codex": ("Codex", "OpenAI · Codex CLI", "OpenAI's terminal coding agent for code, patching, tests, and repo work."),
            "claude": ("Claude", "Anthropic · Claude Code", "Anthropic's Claude Code CLI for coding, planning, and review in the terminal."),
            "gemini": ("Gemini", "Google · Gemini CLI", "Google's Gemini CLI for research, multimodal context, and terminal collaboration."),
        },
        "zh-CN": {
            "codex": ("Codex", "OpenAI · Codex CLI", "OpenAI 开发的终端编码代理，偏代码修改、补丁、测试和仓库操作。"),
            "claude": ("Claude", "Anthropic · Claude Code", "Anthropic 开发的 Claude Code 终端工具，偏编码、规划和审查。"),
            "gemini": ("Gemini", "Google · Gemini CLI", "Google 开发的 Gemini CLI，偏研究、上下文整合和终端协作。"),
        },
    }[runtime_lang]
    return [
        ControllerCard(
            agent=agent,
            title=copy[agent][0],
            summary=copy[agent][1],
            detail=copy[agent][2],
            selected=agent == selected_agent,
        )
        for agent in DEFAULT_AGENTS
    ]


def derive_workspace_tree_root(candidates: Sequence[Path], workspace: Path, cwd: Path) -> Path:
    workspace_path = Path(workspace).expanduser().resolve()
    cwd_path = Path(cwd).expanduser().resolve()
    home = Path.home().expanduser().resolve()

    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for path in (workspace_path, cwd_path, *candidates):
        resolved = Path(path).expanduser().resolve()
        if resolved not in seen:
            resolved_paths.append(resolved)
            seen.add(resolved)

    try:
        common_root = Path(os.path.commonpath([str(path) for path in resolved_paths]))
    except ValueError:
        common_root = workspace_path.parent

    anchor_only = Path(common_root.anchor) if common_root.anchor else common_root
    if workspace_path.is_relative_to(home):
        if common_root == home or common_root.is_relative_to(home):
            return common_root
        return home
    if common_root != anchor_only:
        return common_root
    if workspace_path.parent != workspace_path:
        return workspace_path.parent
    if cwd_path.parent != cwd_path:
        return cwd_path.parent
    return cwd_path


def build_review_list_lines(items: Sequence[LabPlanItem], selected_index: int, width: int) -> list[str]:
    safe_width = max(22, int(width))
    result: list[str] = []
    for index, item in enumerate(items):
        selected = index == selected_index
        meta_prefix = "› " if selected else "  "
        body_prefix = "│ " if selected else "  "
        meta = _fit_width(f"{meta_prefix}{item.sx}  {item.agent}  {item.eta_minutes}m", safe_width)
        result.append(meta)
        title_width = max(8, safe_width - len(body_prefix))
        for wrapped in _wrap_inline_text(item.title, title_width, max_lines=2):
            result.append(_fit_width(f"{body_prefix}{wrapped}", safe_width))
        if index != len(items) - 1:
            result.append("")
    return result


def build_planning_panel_lines(
    *,
    task: str,
    workspace: Path,
    controller: str,
    planner_mode: str,
    lang: str,
    width: int,
    elapsed_seconds: float,
    log_lines: Sequence[str],
    plan_count: int = 0,
) -> list[str]:
    runtime_lang = resolve_v3_language(lang)
    safe_width = max(36, int(width))
    elapsed = max(0.0, float(elapsed_seconds))
    spinner = SPINNER_FRAMES[int(elapsed * 8) % len(SPINNER_FRAMES)] if elapsed > 0 else "•"
    task_preview = _task_preview(task)
    planner_label = TEXT[runtime_lang]["planner_live"] if planner_mode == "live" else TEXT[runtime_lang]["planner_mock"]
    if plan_count > 0:
        stage = TEXT[runtime_lang]["planning_stage_done"]
        next_step = TEXT[runtime_lang]["planning_ready"]
    elif len(log_lines) >= 2:
        stage = TEXT[runtime_lang]["planning_stage_wait"]
        next_step = TEXT[runtime_lang]["planning_escape_hint"]
    elif log_lines:
        stage = TEXT[runtime_lang]["planning_stage_call"]
        next_step = TEXT[runtime_lang]["planning_stage_wait"]
    else:
        stage = TEXT[runtime_lang]["planning_stage_prepare"]
        next_step = TEXT[runtime_lang]["planning_stage_call"]

    lines = [
        TEXT[runtime_lang]["planning_help"],
        "",
        f"[{TEXT[runtime_lang]['planning_summary_title']}]",
        _fit_width(f"{TEXT[runtime_lang]['planning_task_label']}: {task_preview}", safe_width),
        _fit_width(f"{TEXT[runtime_lang]['planning_workspace_label']}: {Path(workspace).expanduser().resolve()}", safe_width),
        _fit_width(f"{TEXT[runtime_lang]['planning_controller_label']}: {_agent_label(controller, runtime_lang)}  ·  {planner_label}", safe_width),
        "",
        f"[{TEXT[runtime_lang]['planning_status_title']}]",
        _fit_width(f"{spinner} {stage}", safe_width),
        _fit_width(f"{TEXT[runtime_lang]['planning_elapsed_label']}: {elapsed:.1f}s", safe_width),
        _fit_width(f"{TEXT[runtime_lang]['planning_steps_label']}: {plan_count if plan_count > 0 else '-'}", safe_width),
        _fit_width(f"{TEXT[runtime_lang]['planning_next_label']}: {next_step}", safe_width),
        "",
        f"[{TEXT[runtime_lang]['planning_events_title']}]",
    ]
    if log_lines:
        lines.extend(_fit_width(f"• {line}", safe_width) for line in log_lines[-8:])
    else:
        lines.append(_fit_width(f"• {TEXT[runtime_lang]['planning_stage_prepare']}", safe_width))
    return lines


def build_command_bar_state(screen: str, lang: str, raw: str = "") -> CommandBarState:
    runtime_lang = resolve_v3_language(lang)
    typed = str(raw or "").strip().lower()
    if runtime_lang == "zh-CN":
        base = {
            "workspace": CommandBarState(
                placeholder=": 路径  /new <路径>  关键字筛选",
                help_text="左右切换来源 · Enter / Space 继续 · Esc 返回",
            ),
            "controller": CommandBarState(
                placeholder="输入 codex / claude / gemini，或直接按 Enter 使用当前主控",
                help_text="左右键切换卡片 · Enter 直接继续 · 鼠标点击卡片即可选择",
            ),
            "task": CommandBarState(
                placeholder="/plan  /nano  /vim  /back",
                help_text="大编辑区写任务；底部输入栏只负责快捷命令",
            ),
            "planning": CommandBarState(
                placeholder="规划进行中",
                help_text="正在等待主控返回 JSON 计划",
            ),
            "review": CommandBarState(
                placeholder="/save  /create ...  /delete  /send  /task",
                help_text="右侧表单直接编辑；输入 / 可查看快捷命令",
            ),
            "error": CommandBarState(
                placeholder="/retry  /task",
                help_text="规划已中止，只能重试或返回任务页",
            ),
            "sent": CommandBarState(
                placeholder="/exit  /back",
                help_text="Bundle 已导出，可关闭或返回检查页",
            ),
        }
        slash = {
            "task": "/plan  /nano  /vim  /back",
            "review": "/save  /create  /delete  /send  /task",
            "error": "/retry  /task",
            "sent": "/exit  /back",
            "controller": "/codex  /claude  /gemini",
        }
    else:
        base = {
            "workspace": CommandBarState(
                placeholder=": path  /new <path>  filter",
                help_text="Left/Right switches source · Enter / Space continues · Esc returns",
            ),
            "controller": CommandBarState(
                placeholder="Type codex / claude / gemini, or press Enter to keep the current controller",
                help_text="Left/Right switches cards · Enter continues · click a card to select it",
            ),
            "task": CommandBarState(
                placeholder="/plan  /nano  /vim  /back",
                help_text="Use the large editor for the task; the bottom bar is only for shortcuts",
            ),
            "planning": CommandBarState(
                placeholder="Planning in progress",
                help_text="Waiting for the controller to return structured JSON",
            ),
            "review": CommandBarState(
                placeholder="/save  /create ...  /delete  /send  /task",
                help_text="Edit the right-hand form directly; type / to view quick commands",
            ),
            "error": CommandBarState(
                placeholder="/retry  /task",
                help_text="Planning stopped here. Retry or go back to the task screen",
            ),
            "sent": CommandBarState(
                placeholder="/exit  /back",
                help_text="The bundle is exported. Close or go back to review",
            ),
        }
        slash = {
            "task": "/plan  /nano  /vim  /back",
            "review": "/save  /create  /delete  /send  /task",
            "error": "/retry  /task",
            "sent": "/exit  /back",
            "controller": "/codex  /claude  /gemini",
        }
    state = base.get(screen, base["workspace"])
    if typed.startswith("/"):
        suggestion = slash.get(screen)
        if suggestion:
            return CommandBarState(placeholder=state.placeholder, help_text=suggestion, value="")
    return state


def interpret_workspace_submission(raw: str, cwd: Path, selected: Optional[Path]) -> WorkspaceSubmission:
    text = str(raw or "").strip()
    if not text:
        return WorkspaceSubmission(kind="use", path=(selected or cwd).expanduser().resolve())
    if text.lower().startswith("/new "):
        return WorkspaceSubmission(kind="create", path=Path(text[5:].strip()).expanduser())
    candidate = Path(text).expanduser()
    if candidate.is_dir():
        return WorkspaceSubmission(kind="use", path=candidate.resolve())
    if "/" in text or "\\" in text:
        return WorkspaceSubmission(kind="missing", path=candidate)
    if selected is not None:
        return WorkspaceSubmission(kind="use", path=selected.expanduser().resolve())
    return WorkspaceSubmission(kind="filter", query=text)


def parse_review_command(raw: str) -> ReviewCommand:
    text = str(raw or "").strip()
    if not text:
        return ReviewCommand(action="noop")
    if not text.startswith("/"):
        return ReviewCommand(action="unknown", value=text)
    action, _sep, value = text[1:].partition(" ")
    normalized = action.strip().lower()
    if normalized in {"send", "delete", "task", "retry", "exit", "back", "save"}:
        return ReviewCommand(action=normalized, value=value.strip())
    if normalized in {"title", "done", "eta", "agent", "create"}:
        return ReviewCommand(action=normalized, value=value.strip())
    return ReviewCommand(action="unknown", value=value.strip())


def build_planner_prompt(
    task: str,
    controller: str,
    workspace: Path,
    lang: str,
    config: Optional[Config] = None,
) -> str:
    runtime_lang = resolve_v3_language(lang)
    workspace_text = str(Path(workspace).expanduser().resolve())
    controller_label = _agent_label(controller, runtime_lang)
    task_text = str(task or "").strip()
    role_leads = resolve_collaboration_role_leads(config)
    architecture_lead = role_leads.get("architecture", "gemini")
    implementation_lead = role_leads.get("implementation", "codex")
    testing_lead = role_leads.get("testing", "claude")
    session_preset, workflow_blueprint = _resolve_v2_prompt_defaults(config)
    architecture_label = _agent_label(architecture_lead, runtime_lang)
    implementation_label = _agent_label(implementation_lead, runtime_lang)
    testing_label = _agent_label(testing_lead, runtime_lang)
    if runtime_lang == "zh-CN":
        return f"""你是 ai-collab 的主控 Agent：{controller_label}。

请只输出一个 JSON 对象，不要输出 Markdown，不要输出解释文字。
不要运行任何命令，不要读取或搜索工作区文件，不要调用任何工具。
不要为了“先理解项目”而执行额外步骤；你现在的唯一任务就是直接产出规划 JSON。
即使信息不足，也要基于用户任务文本和通用工程经验做最合理的默认假设，并立即输出最终 JSON。
请严格使用下面这个字段结构，不要改字段名：
{{
  "plan_version": "1.0",
  "workflow_engine": "v2",
  "session_preset": "{session_preset}",
  "workflow_blueprint": "{workflow_blueprint}",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "{architecture_lead}", "model": "unknown", "persona": "options-architect", "why": "负责方案选项、技术骨架与架构取舍"}},
    {{"name": "{implementation_lead}", "model": "unknown", "persona": "implementation-lead", "why": "负责主实现与跨文件修改"}},
    {{"name": "{testing_lead}", "model": "unknown", "persona": "quality-reviewer", "why": "负责验收、测试设计与补充修补"}}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "{architecture_lead}",
      "goal": "明确方案选项与技术骨架",
      "input": "用户任务",
      "output": "现状证据包与可执行方案方向",
      "done_when": "完成现状收集，明确关键约束，并给出可执行方案方向或是否需要进入 artifact 阶段",
      "eta_minutes": 15,
      "responsibility_stage": "collect",
      "artifact_type": "evidence-pack",
      "boundary": "只收集现状，不直接改代码或重设方案",
      "timebox_minutes": 15
    }},
    {{
      "id": "S2",
      "owner": "{implementation_lead}",
      "goal": "完成主实现",
      "input": "已确认的方案与技术骨架",
      "output": "可运行主功能",
      "done_when": "核心功能可运行，且关键交互或主流程可手动验证",
      "eta_minutes": 45,
      "responsibility_stage": "execute",
      "artifact_type": "code-change",
      "boundary": "仅在已批准方向内实现，不擅自扩大范围或改写需求",
      "timebox_minutes": 45
    }},
    {{
      "id": "S3",
      "owner": "{testing_lead}",
      "goal": "执行验收与补充修补",
      "input": "已实现功能",
      "output": "验收结论与必要修补",
      "done_when": "给出明确通过/失败结论，列出检查项；若发现超出边界的问题，明确交回 correct 阶段",
      "eta_minutes": 20,
      "responsibility_stage": "validate",
      "artifact_type": "validation-report",
      "boundary": "以验收和风险识别为主，不在本阶段擅自重设方案",
      "timebox_minutes": 20
    }}
  ],
  "approval_question": "是否执行？"
}}

工作目录: {workspace_text}
输出语言: 中文
用户任务:
{task_text}

优先职责边界（如果任务确实需要多 Agent，优先按此分工）:
- 方案选项 / 技术骨架 / 架构取舍：{architecture_label}
- 主实现 / 跨文件编码 / 问题修复：{implementation_label}
- 验收 / 回归测试 / 质量审查 / 补充修改：{testing_label}
- 不要因为当前 controller 是 {controller} 就默认把主实现分给 {controller}；只有在任务明显不需要某个角色时，才可以省略该角色。

要求:
1. JSON 兼容 ai-collab controller planning schema。
2. steps 使用 S1、S2、S3 这样的编号。
3. owner 只能是 codex、claude、gemini 之一。
4. 若能估算，请在每个 step 中提供 eta_minutes 正整数。
5. done_when 必须可验证。
6. 不允许 fallback 到内置分工，即使信息不足也要先给出最合理的 JSON 计划。
7. approval_question 必须是中文确认问题，并且要明确提到当前任务主题，不能只写“是否执行？”。
8. 不要返回占位式步骤标题，例如 S1、步骤1、计划、任务、测试；每个 goal 都必须是具体动作短句。
9. 不要返回模板化 done_when，例如“完成 S1 并给出可检查结果”；done_when 必须说明具体验收标准。
10. 如果 requires_multi_agent=true，则至少给出 2 个步骤，并且至少 2 个 Agent 真正拥有步骤。
11. 最终输出必须直接是 JSON 对象本身，不能先给分析过程、不能先说“我先去查看代码”。
12. workflow_engine 固定为 `v2`；session_preset 与 workflow_blueprint 必须匹配当前任务的合理默认。
13. 每个 step 都应尽量补充 responsibility_stage、artifact_type、boundary、timebox_minutes。
14. responsibility_stage 必须是 collect / model / plan / artifact / execute / validate / correct / deliver 之一，而不是直接写 Agent 名称。
15. 若 validate 阶段发现问题需要继续修补，可新增 correct 阶段；若任务需要 mockup / contract / skeleton，可新增 artifact 阶段。
"""
    return f"""You are the ai-collab controller agent: {controller_label}.

Return exactly one JSON object. Do not add Markdown fences or commentary.
Do not run commands, do not read or search workspace files, and do not call any tools.
Do not spend turns inspecting the repository first. Your only job is to return the planning JSON immediately.
If information is incomplete, make the most reasonable defaults from the task text and general software-engineering judgment, then return the final JSON directly.
Use exactly this field structure and do not rename any keys:
{{
  "plan_version": "1.0",
  "workflow_engine": "v2",
  "session_preset": "{session_preset}",
  "workflow_blueprint": "{workflow_blueprint}",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "{architecture_lead}", "model": "unknown", "persona": "options-architect", "why": "Owns options, technical skeleton, and architecture trade-offs"}},
    {{"name": "{implementation_lead}", "model": "unknown", "persona": "implementation-lead", "why": "Owns the main implementation and cross-file edits"}},
    {{"name": "{testing_lead}", "model": "unknown", "persona": "quality-reviewer", "why": "Owns acceptance, test design, and follow-up fixes"}}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "{architecture_lead}",
      "goal": "Collect context and define the technical direction",
      "input": "user task",
      "output": "evidence pack and execution direction",
      "done_when": "Current constraints are collected and the next direction is explicit",
      "eta_minutes": 15,
      "responsibility_stage": "collect",
      "artifact_type": "evidence-pack",
      "boundary": "Collect current facts only; do not implement or redesign in this step",
      "timebox_minutes": 15
    }},
    {{
      "id": "S2",
      "owner": "{implementation_lead}",
      "goal": "Deliver the main implementation",
      "input": "selected approach and skeleton",
      "output": "working core feature",
      "done_when": "The primary workflow runs and the main interaction can be checked manually",
      "eta_minutes": 45,
      "responsibility_stage": "execute",
      "artifact_type": "code-change",
      "boundary": "Implement only within the approved direction; do not expand scope",
      "timebox_minutes": 45
    }},
    {{
      "id": "S3",
      "owner": "{testing_lead}",
      "goal": "Run acceptance and follow-up fixes",
      "input": "implemented feature",
      "output": "acceptance result and necessary follow-up fixes",
      "done_when": "Acceptance verdict is explicit, checks are listed, and out-of-bound issues are handed back for correction",
      "eta_minutes": 20,
      "responsibility_stage": "validate",
      "artifact_type": "validation-report",
      "boundary": "Validate and identify risk; do not silently reset the solution direction here",
      "timebox_minutes": 20
    }}
  ],
  "approval_question": "Should ai-collab execute this plan?"
}}

Workspace: {workspace_text}
Output language: English
User task:
{task_text}

Preferred role split (when the task really benefits from multiple agents):
- Options / technical skeleton / architecture trade-offs: {architecture_label}
- Main implementation / cross-file coding / bug fixing: {implementation_label}
- Acceptance / regression testing / quality review / follow-up fixes: {testing_label}
- Do not assign the main implementation to {controller} just because the current controller is {controller}; only omit a role when the task genuinely does not need it.

Requirements:
1. The JSON must match the ai-collab controller planning schema.
2. Number steps as S1, S2, S3, and so on.
3. Each owner must be one of codex, claude, or gemini.
4. Include eta_minutes as a positive integer when you can estimate it.
5. done_when must be verifiable.
6. Do not fall back to a built-in delegation strategy.
7. approval_question must explicitly mention the current task topic, not only generic text such as “Proceed?”.
8. Do not return placeholder step titles such as S1, Step 1, Plan, Task, or Test; each goal must be concrete.
9. Do not return templated done_when text such as “Complete S1 and provide a checkable result.”; make it specific.
10. If requires_multi_agent=true, provide at least 2 steps and ensure at least 2 agents actually own steps.
11. The final output must be the JSON object itself, not analysis or a preamble such as “I will inspect the repo first”.
12. workflow_engine must be `v2`; session_preset and workflow_blueprint must be a sensible match for the task.
13. Each step should include responsibility_stage, artifact_type, boundary, and timebox_minutes whenever possible.
14. responsibility_stage must be one of collect / model / plan / artifact / execute / validate / correct / deliver, not an agent name.
15. Add a correct stage when validation uncovers bounded issues, and add an artifact stage when the task needs mockup / contract / skeleton work.
"""


def map_controller_plan_to_items(payload: dict[str, Any], lang: str) -> list[LabPlanItem]:
    runtime_lang = resolve_v3_language(lang)
    steps = payload.get("steps", [])
    if not isinstance(steps, list) or not steps:
        raise ValueError("Controller plan does not contain steps")

    items: list[LabPlanItem] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id", "")).strip() or f"S{index}"
        owner = str(step.get("owner", "")).strip().lower() or "codex"
        goal = str(step.get("goal", "")).strip()
        output_text = str(step.get("output", "")).strip()
        title = goal or output_text or step_id
        done_when = str(step.get("done_when", "")).strip()
        if not done_when:
            if runtime_lang == "zh-CN":
                done_when = f"完成 {title} 并给出可检查结果。"
            else:
                done_when = f"Complete {title} and provide a checkable result."
        items.append(
            LabPlanItem(
                sx=step_id.upper(),
                title=title,
                agent=owner if owner in DEFAULT_AGENTS else "codex",
                eta_minutes=_coerce_eta_minutes(step.get("eta_minutes"), owner=owner, index=index),
                done_when=done_when,
            )
        )
    if not items:
        raise ValueError("Controller plan steps are empty")
    return items


def request_live_plan(
    *,
    config: Config,
    controller: str,
    task: str,
    workspace: Path,
    lang: str,
    request_plan: Optional[Callable[..., tuple[Optional[dict[str, Any]], Optional[str]]]] = None,
) -> tuple[Optional[list[LabPlanItem]], Optional[str]]:
    request_callable = request_plan
    if request_callable is None:
        from ai_collab import cli as cli_module

        request_callable = cli_module._request_controller_plan

    plan_payload, error = request_callable(
        config=config,
        controller=controller,
        prompt_text=build_planner_prompt(task=task, controller=controller, workspace=workspace, lang=lang, config=config),
    )
    if error:
        return None, error
    if not isinstance(plan_payload, dict):
        return None, "Controller returned empty planning payload"
    try:
        return map_controller_plan_to_items(plan_payload, lang=lang), None
    except ValueError as exc:
        return None, str(exc)


def launch_ux_lab_v3(
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
    lang = resolve_v3_language(getattr(config, "ui_language", "en-US"))
    resolved_task = _resolve_task_text(task=task, task_file=task_file)
    resolved_workspace = Path(workspace or cwd).expanduser().resolve()
    available_agents = _enabled_agents(config)
    resolved_controller = _resolve_controller(controller or config.current_controller, available_agents)
    mode = planner_mode if planner_mode in {"live", "mock"} else "live"

    if non_interactive:
        if mode == "mock":
            plan = build_mock_plan_v3(resolved_task, resolved_controller, lang, available_agents=available_agents)
            error = None
        else:
            plan, error = request_live_plan(
                config=config,
                controller=resolved_controller,
                task=resolved_task,
                workspace=resolved_workspace,
                lang=lang,
            )
        if error:
            return UxLabV3Result(
                status="error",
                workspace=resolved_workspace,
                controller=resolved_controller,
                task=resolved_task,
                lang=lang,
                planner_mode=mode,
                plan=[],
                error_message=error,
            )
        assert plan is not None
        bundle_path = None
        status = "planned"
        if skip_review:
            bundle_path = export_launch_bundle_v3(
                workspace=resolved_workspace,
                controller=resolved_controller,
                task=resolved_task,
                lang=lang,
                planner_mode=mode,
                plan=plan,
                output_path=output_bundle,
            )
            status = "sent"
        return UxLabV3Result(
            status=status,
            workspace=resolved_workspace,
            controller=resolved_controller,
            task=resolved_task,
            lang=lang,
            planner_mode=mode,
            plan=plan,
            bundle_path=bundle_path,
        )

    try:
        from ai_collab.ux_lab_v3_textual import run_textual_ux_lab_v3

        return run_textual_ux_lab_v3(
            config=config,
            cwd=Path(cwd).resolve(),
            workspace=resolved_workspace,
            controller=resolved_controller,
            task=resolved_task,
            skip_review=skip_review,
            planner_mode=mode,
            output_bundle=output_bundle,
        )
    except ImportError:
        app = _UxLabV3PromptToolkitApp(
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
        return app.run()


def export_launch_bundle_v3(
    *,
    workspace: Path,
    controller: str,
    task: str,
    lang: str,
    planner_mode: str,
    plan: Sequence[LabPlanItem],
    output_path: Optional[Path] = None,
    controller_plan: Optional[dict[str, Any]] = None,
) -> Path:
    destination = output_path.expanduser().resolve() if output_path else _default_bundle_path(workspace)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "ux-lab-v3",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "controller": controller,
        "task": task,
        "lang": lang,
        "planner_mode": planner_mode,
        "plan": [asdict(item) for item in plan],
    }
    if controller_plan:
        payload["controller_plan"] = controller_plan
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def build_mock_plan_v3(
    task: str,
    controller: str,
    lang: str,
    *,
    available_agents: Optional[Sequence[str]] = None,
) -> list[LabPlanItem]:
    runtime_lang = resolve_v3_language(lang)
    ordered_agents = _ordered_agents(controller, available_agents)
    preview = _task_preview(task)
    if runtime_lang == "zh-CN":
        return [
            LabPlanItem("S1", f"{_agent_label(controller, runtime_lang)} 先完成主控拆解", controller, 8, f"输出 JSON 计划，覆盖任务主题：{preview}"),
            LabPlanItem("S2", f"{_agent_label(ordered_agents[1], runtime_lang)} 执行第一条并行子任务", ordered_agents[1], 14, "子控明确输出“任务完成”。"),
            LabPlanItem("S3", f"{_agent_label(ordered_agents[2], runtime_lang)} 负责收尾检查", ordered_agents[2], 10, "主控询问关闭还是保留协作窗口。"),
        ]
    return [
        LabPlanItem("S1", f"{_agent_label(controller, runtime_lang)} drafts the controller plan", controller, 8, f"Return a JSON plan for {preview}."),
        LabPlanItem("S2", f"{_agent_label(ordered_agents[1], runtime_lang)} executes the first delegated track", ordered_agents[1], 14, "The delegated agent explicitly reports task completion."),
        LabPlanItem("S3", f"{_agent_label(ordered_agents[2], runtime_lang)} reviews closure", ordered_agents[2], 10, "The controller asks whether helper panes should stay open or close."),
    ]


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
    compact = " ".join(str(task or "").split())
    if not compact:
        return "the requested task"
    if len(compact) <= 56:
        return compact
    return compact[:53].rstrip() + "..."


def _agent_label(agent: str, lang: str) -> str:
    labels = AGENT_LABELS.get(resolve_v3_language(lang), AGENT_LABELS["en-US"])
    return labels.get(agent, agent.title())


def _coerce_eta_minutes(value: Any, *, owner: str, index: int) -> int:
    try:
        eta = int(str(value).strip())
        if eta > 0:
            return eta
    except Exception:  # noqa: BLE001
        pass
    defaults = {"codex": 12, "claude": 10, "gemini": 11}
    return defaults.get(owner, 10) + max(0, index - 1) * 2


def _default_bundle_path(workspace: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return workspace / ".ai-collab" / "ux-lab-v3" / f"bundle-{stamp}.json"


def _default_workspace_history_path() -> Path:
    return Config.get_config_dir() / "ux-lab-v3-history.json"


def load_workspace_session_records(workspace: Path, *, limit: int = 4) -> list[WorkspaceSessionRecord]:
    runs_dir = Path(workspace).expanduser().resolve() / ".ai-collab" / "runs"
    if not runs_dir.exists():
        return []

    records: list[WorkspaceSessionRecord] = []
    for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True):
        state = _load_json_file(run_dir / "state.json")
        if not isinstance(state, dict):
            continue

        controller_data = state.get("controller") if isinstance(state.get("controller"), dict) else {}
        agents_data = state.get("agents") if isinstance(state.get("agents"), dict) else {}
        tmux_data = state.get("tmux") if isinstance(state.get("tmux"), dict) else {}
        tmux_snapshot = tmux_data.get("layout_snapshot") if isinstance(tmux_data.get("layout_snapshot"), dict) else {}
        task_preview = _load_workspace_run_task_preview(run_dir / "events.jsonl")

        records.append(
            WorkspaceSessionRecord(
                run_id=str(state.get("run_id") or run_dir.name),
                created_at=str(state.get("created_at") or ""),
                updated_at=str(state.get("updated_at") or ""),
                controller=str(controller_data.get("agent") or ""),
                phase=str(state.get("phase") or ""),
                phase_detail=str(state.get("phase_detail") or ""),
                mode=str(state.get("mode") or ""),
                session=str(state.get("session") or ""),
                helper_count=len(agents_data),
                task_preview=task_preview,
                tmux_available=tmux_snapshot.get("available") if isinstance(tmux_snapshot, dict) else None,
            )
        )
        if len(records) >= max(1, int(limit)):
            break
    return records


def _load_workspace_history_from_bundles(bundle_dir: Path, *, limit: int = 8) -> list[Path]:
    if not bundle_dir.exists():
        return []
    recent: list[Path] = []
    seen: set[Path] = set()
    for bundle in sorted(bundle_dir.glob("bundle-*.json"), reverse=True):
        try:
            payload = json.loads(bundle.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        workspace = payload.get("workspace")
        if not workspace:
            continue
        try:
            candidate = Path(str(workspace)).expanduser().resolve()
        except Exception:  # noqa: BLE001
            continue
        if not candidate.is_dir() or candidate in seen:
            continue
        recent.append(candidate)
        seen.add(candidate)
        if len(recent) >= max(1, int(limit)):
            break
    return recent


def load_workspace_history(*, history_path: Optional[Path] = None) -> list[Path]:
    path = Path(history_path or _default_workspace_history_path()).expanduser()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []
    history: list[Path] = []
    seen: set[Path] = set()
    for item in payload:
        try:
            candidate = Path(str(item)).expanduser().resolve()
        except Exception:  # noqa: BLE001
            continue
        if not candidate.is_dir() or candidate in seen:
            continue
        history.append(candidate)
        seen.add(candidate)
    return history


def discover_recent_workspaces(
    *,
    workspace: Path,
    cwd: Path,
    candidates: Sequence[Path],
    history_path: Optional[Path] = None,
    bundle_dir: Optional[Path] = None,
    limit: int = 8,
) -> list[Path]:
    max_items = max(1, int(limit))
    resolved_workspace = Path(workspace).expanduser().resolve()
    resolved_cwd = Path(cwd).expanduser().resolve()
    default_bundle_dir = resolved_workspace / ".ai-collab" / "ux-lab-v3"
    recent_sources = [
        *load_workspace_history(history_path=history_path),
        *_load_workspace_history_from_bundles(Path(bundle_dir or default_bundle_dir).expanduser(), limit=max_items),
        resolved_workspace,
        resolved_cwd,
        *[Path(path).expanduser().resolve() for path in candidates],
    ]
    recent: list[Path] = []
    seen: set[Path] = set()
    for path in recent_sources:
        if not path.is_dir() or path in seen:
            continue
        recent.append(path)
        seen.add(path)
        if len(recent) >= max_items:
            break
    return recent


def record_workspace_history(
    workspace: Path,
    *,
    history_path: Optional[Path] = None,
    limit: int = 8,
) -> list[Path]:
    resolved = Path(workspace).expanduser().resolve()
    history = [resolved]
    history.extend(path for path in load_workspace_history(history_path=history_path) if path != resolved)
    trimmed = history[: max(1, int(limit))]
    path = Path(history_path or _default_workspace_history_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([str(item) for item in trimmed], ensure_ascii=False, indent=2), encoding="utf-8")
    return trimmed


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
    for base in (cwd.parent, home):
        for path in _safe_iterdirs(base)[:24]:
            _push(path)
    return candidates


def _safe_iterdirs(path: Path) -> list[Path]:
    try:
        items = [item for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")]
    except OSError:
        return []
    return sorted(items, key=lambda item: item.name.lower())


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _load_workspace_run_task_preview(events_path: Path) -> str:
    if not events_path.exists():
        return ""
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if payload.get("type") != "run_started":
                continue
            event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            task = str(event_payload.get("task") or "").strip()
            if task:
                return _task_preview(task)
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _format_workspace_session_timestamp(value: str) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return _fit_width(value, 16)


def _workspace_phase_label(phase: str, lang: str) -> str:
    labels = {
        "en-US": {
            "created": "Created",
            "controller_started": "Controller started",
            "subagent_spawned": "Helper spawned",
            "monitoring": "Monitoring",
            "completed": "Completed",
            "failed": "Failed",
        },
        "zh-CN": {
            "created": "已创建",
            "controller_started": "主控已启动",
            "subagent_spawned": "已拉起子控",
            "monitoring": "监控中",
            "completed": "已完成",
            "failed": "失败",
        },
    }
    runtime_lang = resolve_v3_language(lang)
    if phase in labels[runtime_lang]:
        return labels[runtime_lang][phase]
    fallback = phase.replace("_", " ").strip()
    if not fallback:
        return "-"
    return fallback.title() if runtime_lang == "en-US" else fallback


def _wrap_inline_text(value: str, width: int, *, max_lines: Optional[int] = None) -> list[str]:
    text = " ".join(str(value or "").split())
    if not text:
        return [""]
    wrapped = textwrap.wrap(
        text,
        width=max(1, width),
        break_long_words=True,
        break_on_hyphens=False,
    )
    if max_lines is not None and len(wrapped) > max_lines:
        limited = wrapped[:max_lines]
        last_width = max(1, width)
        limited[-1] = _fit_width(limited[-1], last_width - 3).rstrip() + "..."
        return limited
    return wrapped


def _fit_width(value: str, width: int) -> str:
    text = str(value)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: max(0, width - 3)].rstrip() + "..."


class _UxLabV3PromptToolkitApp:
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
            from prompt_toolkit.application import Application, run_in_terminal
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, VSplit, Window
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.layout.dimension import D
            from prompt_toolkit.styles import Style
            from prompt_toolkit.widgets import Box, Frame, RadioList, TextArea
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("prompt_toolkit is required for ai-collab ux-lab-v3") from exc

        self._Application = Application
        self._run_in_terminal = run_in_terminal
        self._Box = Box
        self._DynamicContainer = DynamicContainer
        self._Frame = Frame
        self._HSplit = HSplit
        self._VSplit = VSplit
        self._Layout = Layout
        self._RadioList = RadioList
        self._Window = Window
        self._FormattedTextControl = FormattedTextControl
        self._D = D
        self._Style = Style
        self._TextArea = TextArea

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
        self.plan: list[LabPlanItem] = []
        self.bundle_path: Optional[Path] = None
        self.error_message = ""
        self.review_index = 0
        self.screen = "workspace"
        self.planning_started_at = 0.0
        self.planning_log: list[str] = []

        self.candidates = _discover_workspace_candidates(cwd)
        if self.workspace not in self.candidates:
            self.candidates.insert(0, self.workspace)
        self.filtered_candidates = list(self.candidates)
        self.workspace_index = self._selected_workspace_index(self.workspace)

        self.workspace_list = self._RadioList(
            values=self._workspace_values(),
            default=str(self.workspace),
        )
        self.task_input = self._TextArea(
            text=self.task_value,
            multiline=True,
            scrollbar=True,
            wrap_lines=True,
            prompt="",
        )
        self.review_title_input = self._TextArea(text="", multiline=False, height=1, prompt="")
        self.review_eta_input = self._TextArea(text="10", multiline=False, height=1, prompt="")
        self.review_done_input = self._TextArea(text="", multiline=True, height=4, prompt="")
        self.review_agent_list = self._RadioList(
            values=[(agent, _agent_label(agent, self.lang)) for agent in self.available_agents],
            default=self.controller,
        )
        self.command_input = self._TextArea(
            text="",
            multiline=False,
            wrap_lines=False,
            prompt="> ",
        )
        self.command_input.window.height = self._D(min=1, preferred=1, max=1)
        self.command_input.buffer.on_text_changed += self._on_command_text_changed

        self.kb = KeyBindings()
        self._bind_keys()

        root = self._Box(
            body=self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._banner_fragments), height=self._D(min=2, preferred=3, max=4)),
                    self._DynamicContainer(self._body_container),
                    self._Window(self._FormattedTextControl(self._input_label_fragments), height=self._D(min=1, preferred=1, max=1)),
                    self.command_input,
                    self._Window(self._FormattedTextControl(self._footer_fragments), height=self._D(min=2, preferred=2, max=2)),
                ]
            ),
            padding=1,
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
        self._focus_workspace_list()

    def run(self) -> UxLabV3Result:
        return self.app.run()

    def _build_style(self) -> Any:
        return self._Style.from_dict(
            {
                "": "bg:#08111b #dbe7f5",
                "frame.border": "#243b53",
                "frame.label": "bold #f8fafc",
                "brand": "bold #f8fafc",
                "step": "#6b87a7",
                "step-current": "bold #8ee7ff",
                "divider": "#24435f",
                "muted": "#8fa7c0",
                "title": "bold #f8fafc",
                "status": "bold #f8fafc",
                "command-label": "bold #93c5fd",
                "command": "bg:#0e1a29 #e2e8f0",
                "radio": "#dbe7f5",
                "radio-checked": "bold #f8fafc",
                "radio-selected": "bg:#11314b #f8fafc",
                "agent-codex": "bold #67e8f9",
                "agent-claude": "bold #fdba74",
                "agent-gemini": "bold #86efac",
                "selected": "bg:#11314b #f8fafc",
                "error": "bold #fda4af",
                "success": "bold #86efac",
                "hint": "#7dd3fc",
                "text-area": "bg:#0d1826 #e2e8f0",
            }
        )

    def _bind_keys(self) -> None:
        @self.kb.add("c-c")
        @self.kb.add("c-q")
        def _quit(event: Any) -> None:  # noqa: ANN401
            event.app.exit(result=self._result(status="cancelled"))

        @self.kb.add("escape", eager=True)
        def _go_back(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "controller":
                self._switch_screen("workspace")
            elif self.screen == "task":
                self._switch_screen("controller")
            elif self.screen == "review":
                self._switch_screen("task")
            elif self.screen == "error":
                self._switch_screen("task")
            elif self.screen == "sent":
                self._switch_screen("review")

        @self.kb.add("tab", eager=True)
        def _toggle_focus(_event: Any) -> None:  # noqa: ANN401
            try:
                self.app.layout.focus_next()
            except Exception:  # noqa: BLE001
                self._focus_command_bar()

        @self.kb.add("s-tab", eager=True)
        def _toggle_focus_back(_event: Any) -> None:  # noqa: ANN401
            try:
                self.app.layout.focus_previous()
            except Exception:  # noqa: BLE001
                self._focus_command_bar()

        @self.kb.add("enter", eager=True)
        def _enter(event: Any) -> None:  # noqa: ANN401
            if self.app.layout.has_focus(self.command_input):
                self._submit_command_bar()
                return
            if self.screen == "task" and self.app.layout.has_focus(self.task_input):
                event.current_buffer.insert_text("\n")
                return
            if self.screen == "review" and self.app.layout.has_focus(self.review_done_input):
                event.current_buffer.insert_text("\n")
                return
            if self.screen == "workspace":
                self._submit_workspace()
                return
            if self.screen == "controller":
                self._submit_controller()
                return
            if self.screen == "review":
                self._save_review_item()
                return

        @self.kb.add("f5", eager=True)
        @self.kb.add("c-s", eager=True)
        def _confirm(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "task":
                self._run_task_command("/plan")
            elif self.screen == "review":
                self._save_review_item()
            else:
                self._submit_command_bar()

        @self.kb.add("left", eager=True)
        def _left(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "controller":
                self._move_controller(-1)
            elif self.screen == "review":
                self._move_selected_agent(-1)

        @self.kb.add("right", eager=True)
        def _right(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "controller":
                self._move_controller(1)
            elif self.screen == "review":
                self._move_selected_agent(1)

        @self.kb.add("up", eager=True)
        def _up(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "workspace":
                self._move_workspace(-1)
            elif self.screen == "review":
                self._move_review(-1)

        @self.kb.add("down", eager=True)
        def _down(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "workspace":
                self._move_workspace(1)
            elif self.screen == "review":
                self._move_review(1)

        @self.kb.add("f2", eager=True)
        def _nano(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "task":
                self._run_task_command("/nano")

        @self.kb.add("f3", eager=True)
        def _vim(_event: Any) -> None:  # noqa: ANN401
            if self.screen == "task":
                self._run_task_command("/vim")

    def _banner_fragments(self) -> list[tuple[str, str]]:
        width = shutil.get_terminal_size((100, 40)).columns
        banner = build_brand_banner(width, self.lang)
        fragments: list[tuple[str, str]] = []
        for line in banner:
            fragments.append(("class:brand", line + "\n"))
        for line in build_step_track(self.screen, self.lang, width):
            fragments.append(("class:step-current", line + "\n"))
        return fragments

    def _input_label_fragments(self) -> list[tuple[str, str]]:
        mapping = {
            "workspace": "input_workspace",
            "controller": "input_controller",
            "task": "input_task",
            "planning": "input_planning",
            "review": "input_review",
            "error": "input_error",
            "sent": "input_sent",
        }
        return [("class:command-label", self._t(mapping.get(self.screen, "input_workspace")))]

    def _footer_fragments(self) -> list[tuple[str, str]]:
        return [
            ("class:status", self.status_message + "\n"),
            ("class:muted", self._footer_hint()),
        ]

    def _body_container(self) -> Any:
        if self.screen == "workspace":
            return self._workspace_container()
        if self.screen == "controller":
            return self._controller_container()
        if self.screen == "task":
            return self._task_container()
        if self.screen == "planning":
            return self._planning_container()
        if self.screen == "review":
            return self._review_container()
        if self.screen == "error":
            return self._error_container()
        return self._sent_container()

    def _workspace_container(self) -> Any:
        return self._Frame(
            self._HSplit(
                [
                    self._Window(self._FormattedTextControl(self._workspace_fragments), height=self._D(min=6, preferred=7, max=8), wrap_lines=True),
                    self._Frame(self.workspace_list, title=self._t("workspace_candidates")),
                ]
            ),
            title=self._t("workspace_title"),
        )

    def _controller_container(self) -> Any:
        return self._Frame(
            self._Window(self._FormattedTextControl(self._controller_fragments), wrap_lines=True),
            title=self._t("controller_title"),
        )

    def _task_container(self) -> Any:
        info = self._Window(self._FormattedTextControl(self._task_fragments), height=self._D(min=4, preferred=5, max=6), wrap_lines=True)
        return self._Frame(self._HSplit([info, self.task_input]), title=self._t("task_title"))

    def _planning_container(self) -> Any:
        return self._Frame(
            self._Window(self._FormattedTextControl(self._planning_fragments), wrap_lines=True),
            title=self._t("planning_title"),
        )

    def _review_container(self) -> Any:
        width = shutil.get_terminal_size((100, 40)).columns
        list_panel = self._Frame(
            self._Window(self._FormattedTextControl(self._review_list_fragments), wrap_lines=True),
            title=self._t("review_list_title"),
        )
        detail_form = self._HSplit(
            [
                self._Window(self._FormattedTextControl(self._review_detail_fragments), height=self._D(min=4, preferred=5, max=6), wrap_lines=True),
                self._Frame(self.review_title_input, title=self._t("detail_title_label")),
                self._Frame(self.review_eta_input, title=self._t("detail_eta_label")),
                self._Frame(self.review_done_input, title=self._t("review_detail_done")),
                self._Frame(self.review_agent_list, title=self._t("detail_agent_label")),
            ]
        )
        detail_panel = self._Frame(detail_form, title=self._t("review_detail_title"))
        if choose_review_layout(width) == "split":
            body = self._VSplit([list_panel, detail_panel], padding=1)
        else:
            body = self._HSplit([list_panel, detail_panel])
        return self._Frame(body, title=self._t("review_title"))

    def _error_container(self) -> Any:
        return self._Frame(
            self._Window(self._FormattedTextControl(self._error_fragments), wrap_lines=True),
            title=self._t("error_title"),
        )

    def _sent_container(self) -> Any:
        return self._Frame(
            self._Window(self._FormattedTextControl(self._sent_fragments), wrap_lines=True),
            title=self._t("sent_title"),
        )

    def _workspace_fragments(self) -> list[tuple[str, str]]:
        filter_value = self.command_input.text.strip() or "..."
        selected = self._selected_candidate() or self.workspace
        return [
            ("class:muted", self._t("workspace_help") + "\n\n"),
            ("class:status", f"{self._t('workspace_current')}: "),
            ("", f"{self.cwd}\n"),
            ("class:status", f"{self._t('workspace_enter_uses')}: "),
            ("", f"{selected}\n"),
            ("class:status", f"{self._t('workspace_filter')}: "),
            ("", filter_value + "\n"),
            ("class:hint", "/new /tmp/ai-collab-lab\n"),
        ]

    def _controller_fragments(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = [
            ("class:muted", self._t("controller_help") + "\n\n"),
        ]
        cards = build_controller_cards(self.controller, self.lang)
        for card in cards:
            marker = "[*]" if card.selected else "[ ]"
            title_style = AGENT_STYLES.get(card.agent, "class:title")
            if card.selected:
                title_style = f"{title_style} class:selected".strip()
            fragments.append((title_style, f"{marker} {card.title}  {card.summary}\n"))
            for line in _wrap_inline_text(card.detail, max(22, shutil.get_terminal_size((100, 40)).columns - 4)):
                fragments.append(("class:muted", f"    {line}\n"))
            fragments.append(("class:divider", "    ───────────────────────────────────────\n"))
        return fragments

    def _task_fragments(self) -> list[tuple[str, str]]:
        task_text = self.task_input.text.strip()
        line_count = len(task_text.splitlines()) if task_text else 0
        preview = _task_preview(task_text)
        return [
            ("class:muted", self._t("task_help") + "\n\n"),
            ("class:status", f"{self._t('detail_workspace_label')}: {self.workspace}\n"),
            ("class:status", f"{self._t('detail_agent_label')}: {_agent_label(self.controller, self.lang)}  ·  {self._planner_notice()}\n"),
            ("class:status", f"{self._t('detail_task_lines_label')}: {line_count}\n"),
            ("class:hint", preview if task_text else self._t("task_help")),
        ]

    def _planning_fragments(self) -> list[tuple[str, str]]:
        width = shutil.get_terminal_size((100, 40)).columns
        elapsed = max(0.0, time.monotonic() - self.planning_started_at)
        fragments: list[tuple[str, str]] = []
        for index, line in enumerate(
            build_planning_panel_lines(
                task=self.task_value,
                workspace=self.workspace,
                controller=self.controller,
                planner_mode=self.planner_mode,
                lang=self.lang,
                width=max(36, width - 6),
                elapsed_seconds=elapsed,
                log_lines=self.planning_log,
                plan_count=len(self.plan),
            )
        ):
            style = "class:muted" if index == 0 else "class:hint"
            if line.startswith("["):
                style = "class:status"
            fragments.append((style, f"{line}\n"))
        return fragments

    def _review_list_fragments(self) -> list[tuple[str, str]]:
        width = shutil.get_terminal_size((100, 40)).columns
        split = choose_review_layout(width) == "split"
        list_width = max(24, ((width - 3) // 2) if split else width - 2)
        visible_items = self._visible_plan_items()
        local_index = 0
        for idx, (actual_index, _item) in enumerate(visible_items):
            if actual_index == self.review_index:
                local_index = idx
                break
        fragments: list[tuple[str, str]] = [
            ("class:muted", self._t("review_help") + "\n"),
            ("class:status", self._t("review_step_count", count=str(len(self.plan))) + "\n\n"),
        ]
        for line in build_review_list_lines([item for _index, item in visible_items], local_index, list_width):
            style = "class:selected" if line.startswith(("› ", "│ ")) else ""
            fragments.append((style, line + "\n"))
        return fragments

    def _review_detail_fragments(self) -> list[tuple[str, str]]:
        if not self.plan:
            return [("class:muted", "")]
        item = self.plan[self.review_index]
        return [
            (
                AGENT_STYLES.get(item.agent, "class:status"),
                self._t(
                    "review_detail_meta",
                    sx=item.sx,
                    agent=_agent_label(item.agent, self.lang),
                    eta=str(item.eta_minutes),
                )
                + "\n\n",
            ),
            ("class:muted", self._t("detail_command_examples") + "\n"),
            ("class:hint", "/create ...   /delete   /send   /task   /save\n"),
            ("class:hint", "Up/Down select · F5/Ctrl-S save current form\n"),
        ]

    def _error_fragments(self) -> list[tuple[str, str]]:
        width = max(24, shutil.get_terminal_size((100, 40)).columns - 2)
        error_lines = _wrap_inline_text(self.error_message or self.status_message, width)
        fragments: list[tuple[str, str]] = [
            ("class:muted", self._t("error_help") + "\n\n"),
        ]
        for line in error_lines:
            fragments.append(("class:error", line + "\n"))
        fragments.append(("class:hint", "\n/retry   /task"))
        return fragments

    def _sent_fragments(self) -> list[tuple[str, str]]:
        path_text = str(self.bundle_path) if self.bundle_path else "-"
        width = max(24, shutil.get_terminal_size((100, 40)).columns - 2)
        fragments: list[tuple[str, str]] = [
            ("class:muted", self._t("sent_help") + "\n\n"),
            ("class:success", self._t("send_done", path=path_text) + "\n\n"),
            ("class:status", f"{self._t('detail_workspace_label')}: {self.workspace}\n"),
        ]
        for line in _wrap_inline_text(path_text, width):
            fragments.append(("class:hint", line + "\n"))
        fragments.append(("class:hint", "\n" + self._t("send_exit")))
        return fragments

    def _on_command_text_changed(self, _buffer: Any) -> None:  # noqa: ANN401
        if self.screen != "workspace":
            return
        decision = interpret_workspace_submission(
            raw=self.command_input.text,
            cwd=self.cwd,
            selected=self._selected_candidate(),
        )
        if decision.kind == "filter":
            self.filtered_candidates = filter_workspace_candidates(self.candidates, decision.query)
        elif decision.kind in {"use", "create", "missing"} and not any(sep in self.command_input.text for sep in ("/", "\\")):
            self.filtered_candidates = filter_workspace_candidates(self.candidates, self.command_input.text)
        else:
            self.filtered_candidates = list(self.candidates)
        if self.filtered_candidates:
            self.workspace_index = min(self.workspace_index, len(self.filtered_candidates) - 1)
        self._sync_workspace_list()
        self.app.invalidate()

    def _visible_candidates(self) -> list[tuple[int, Path]]:
        if not self.filtered_candidates:
            return []
        items: list[tuple[int, Path]] = []
        start = max(0, self.workspace_index - 3)
        end = min(len(self.filtered_candidates), start + 8)
        start = max(0, end - 8)
        for offset in range(start, end):
            items.append((offset, self.filtered_candidates[offset]))
        return items

    def _selected_candidate(self) -> Optional[Path]:
        value = str(getattr(self.workspace_list, "current_value", "") or "").strip()
        if value:
            candidate = Path(value).expanduser()
            if candidate.is_dir():
                return candidate.resolve()
        if not self.filtered_candidates:
            return None
        return self.filtered_candidates[max(0, min(self.workspace_index, len(self.filtered_candidates) - 1))]

    def _selected_workspace_index(self, workspace: Path) -> int:
        for index, path in enumerate(self.filtered_candidates):
            if path == workspace:
                return index
        return 0

    def _move_workspace(self, delta: int) -> None:
        if not self.filtered_candidates:
            return
        self.workspace_index = (self.workspace_index + delta) % len(self.filtered_candidates)
        self._sync_workspace_list()
        selected = self._selected_candidate()
        if selected is not None:
            self.status_message = f"{self._t('workspace_selected')}: {selected}"
        self.app.invalidate()

    def _move_controller(self, delta: int) -> None:
        current_index = self.available_agents.index(self.controller)
        self.controller = self.available_agents[(current_index + delta) % len(self.available_agents)]
        self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
        self.app.invalidate()

    def _move_review(self, delta: int) -> None:
        if not self.plan:
            return
        self._save_review_item(silent=True)
        self._load_review_item((self.review_index + delta) % len(self.plan))
        self.status_message = f"{self.plan[self.review_index].sx}: {self.plan[self.review_index].title}"
        self.app.invalidate()

    def _move_selected_agent(self, delta: int) -> None:
        if not self.plan:
            return
        item = self.plan[self.review_index]
        current_index = self.available_agents.index(item.agent) if item.agent in self.available_agents else 0
        item.agent = self.available_agents[(current_index + delta) % len(self.available_agents)]
        self._load_review_item(self.review_index)
        self.status_message = self._t("review_saved", field="agent", step=item.sx)
        self.app.invalidate()

    def _submit_command_bar(self) -> None:
        if self.screen == "workspace":
            self._submit_workspace()
        elif self.screen == "controller":
            self._submit_controller()
        elif self.screen == "task":
            self._run_task_command(self.command_input.text.strip())
        elif self.screen == "review":
            self._run_review_command(self.command_input.text.strip())
        elif self.screen == "error":
            self._run_error_command(self.command_input.text.strip())
        elif self.screen == "sent":
            self._run_sent_command(self.command_input.text.strip())

    def _submit_workspace(self) -> None:
        decision = interpret_workspace_submission(
            raw=self.command_input.text,
            cwd=self.cwd,
            selected=self._selected_candidate(),
        )
        if decision.kind == "create" and decision.path is not None:
            decision.path.mkdir(parents=True, exist_ok=True)
            self.workspace = decision.path.resolve()
            self._reset_workspace_candidates()
            self.status_message = self._t("workspace_created", path=str(self.workspace))
            self.command_input.buffer.text = ""
            self._switch_screen("controller")
            return
        if decision.kind == "use" and decision.path is not None:
            self.workspace = decision.path.resolve()
            self._reset_workspace_candidates()
            self.status_message = self._t("workspace_ready", path=str(self.workspace))
            self.command_input.buffer.text = ""
            self._switch_screen("controller")
            return
        if decision.kind == "missing":
            self.status_message = self._t("workspace_missing")
            return
        self.status_message = self._t("workspace_help")

    def _reset_workspace_candidates(self) -> None:
        if self.workspace not in self.candidates:
            self.candidates.insert(0, self.workspace)
        self.filtered_candidates = list(self.candidates)
        self.workspace_index = self._selected_workspace_index(self.workspace)
        self._sync_workspace_list()

    def _submit_controller(self) -> None:
        typed = self.command_input.text.strip().lower()
        if typed in self.available_agents:
            self.controller = typed
        self.command_input.buffer.text = ""
        self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
        self._switch_screen("task")

    def _run_task_command(self, raw: str) -> None:
        command = str(raw or "").strip().lower()
        if not command:
            return
        if command == "/back":
            self.command_input.buffer.text = ""
            self._switch_screen("controller")
            return
        if command == "/nano":
            self.command_input.buffer.text = ""
            self._open_editor("nano")
            return
        if command == "/vim":
            self.command_input.buffer.text = ""
            self._open_editor("vim")
            return
        if command == "/plan":
            self.command_input.buffer.text = ""
            self._start_planning()
            return
        self.status_message = self._t("task_help")

    def _run_review_command(self, raw: str) -> None:
        command = parse_review_command(raw)
        item = self.plan[self.review_index] if self.plan else None
        if command.action == "send":
            self.command_input.buffer.text = ""
            self._send_plan()
            return
        if command.action == "save":
            self.command_input.buffer.text = ""
            self._save_review_item()
            return
        if command.action in {"task", "back"}:
            self.command_input.buffer.text = ""
            self._switch_screen("task")
            return
        if command.action == "delete":
            self.command_input.buffer.text = ""
            self._delete_step()
            return
        if command.action == "create":
            self.command_input.buffer.text = ""
            self._create_step(command.value)
            return
        if item is None:
            self.status_message = self._t("review_unknown")
            return
        if command.action == "title":
            self.review_title_input.buffer.text = command.value or self.review_title_input.text
            self._save_review_item()
        elif command.action == "done":
            self.review_done_input.buffer.text = command.value or self.review_done_input.text
            self._save_review_item()
        elif command.action == "eta":
            if not command.value.isdigit() or int(command.value) <= 0:
                self.status_message = self._t("review_bad_eta")
                return
            self.review_eta_input.buffer.text = command.value
            self._save_review_item()
        elif command.action == "agent":
            if command.value.lower() not in self.available_agents:
                self.status_message = self._t("review_unknown")
                return
            item.agent = command.value.lower()
            self._load_review_item(self.review_index)
            self.status_message = self._t("review_saved", field="agent", step=item.sx)
        else:
            self.status_message = self._t("review_unknown")
            return
        self.command_input.buffer.text = ""
        self.app.invalidate()

    def _run_error_command(self, raw: str) -> None:
        command = parse_review_command(raw)
        if command.action in {"retry", "noop"}:
            self.command_input.buffer.text = ""
            self._start_planning()
            return
        if command.action in {"task", "back"}:
            self.command_input.buffer.text = ""
            self._switch_screen("task")

    def _run_sent_command(self, raw: str) -> None:
        command = parse_review_command(raw)
        if command.action in {"exit", "noop"}:
            self.app.exit(result=self._result(status="sent"))
            return
        if command.action in {"back", "task"}:
            self.command_input.buffer.text = ""
            self._switch_screen("review")

    def _create_step(self, title: str) -> None:
        self._save_review_item(silent=True)
        step = LabPlanItem(
            sx=f"S{len(self.plan) + 1}",
            title=title or f"S{len(self.plan) + 1}",
            agent=self.controller,
            eta_minutes=10,
            done_when="",
        )
        self.plan.append(step)
        self._renumber_plan()
        self._load_review_item(len(self.plan) - 1)
        self.status_message = self._t("review_created", step=step.sx)
        self.app.invalidate()

    def _delete_step(self) -> None:
        if len(self.plan) <= 1:
            self.status_message = self._t("review_keep_one")
            return
        deleted = self.plan.pop(self.review_index)
        self._renumber_plan()
        self._load_review_item(max(0, min(self.review_index, len(self.plan) - 1)))
        self.status_message = self._t("review_deleted", step=deleted.sx)
        self.app.invalidate()

    def _renumber_plan(self) -> None:
        for index, item in enumerate(self.plan, start=1):
            item.sx = f"S{index}"

    def _start_planning(self) -> None:
        editor_command = str(self.task_input.text.strip()).lower()
        if editor_command in {"/nano", "/vim"}:
            self._open_editor(editor_command[1:])
            return
        self.task_value = self.task_input.text.strip()
        if not self.task_value:
            self.status_message = self._t("task_missing")
            return
        self.screen = "planning"
        self.error_message = ""
        self.planning_started_at = time.monotonic()
        self.planning_log = [self._t("planning_prepare"), self._t("planning_call")]
        self.status_message = self._planner_notice()
        self.command_input.buffer.text = ""
        self._focus_command_bar()
        self.app.create_background_task(self._run_planning())
        self.app.invalidate()

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
            self.screen = "error"
            self.status_message = self._t("planning_failed", error=error)
            self.command_input.buffer.text = "/retry"
            self._focus_command_bar()
            self.app.invalidate()
            return
        assert items is not None
        self.plan = items
        self._finish_planning_success()

    def _finish_planning_success(self) -> None:
        self._load_review_item(0)
        if self.skip_review:
            self._send_plan()
            return
        self.screen = "review"
        self.status_message = self._t("planning_ready")
        self.command_input.buffer.text = ""
        self._focus_review_primary()
        self.app.invalidate()

    def _send_plan(self) -> None:
        if self.screen == "review":
            self._save_review_item(silent=True)
        self.bundle_path = export_launch_bundle_v3(
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value,
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=self.plan,
            output_path=self.output_bundle,
        )
        self.screen = "sent"
        self.status_message = self._t("send_done", path=str(self.bundle_path))
        self.command_input.buffer.text = "/exit"
        self._focus_command_bar()
        self.app.invalidate()

    def _open_editor(self, editor: str) -> None:
        if shutil.which(editor) is None:
            self.status_message = self._t("task_editor_missing", editor=editor)
            return
        self.app.create_background_task(self._open_editor_async(editor))

    async def _open_editor_async(self, editor: str) -> None:
        def _run() -> str:
            with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as handle:
                handle.write(self.task_input.text.strip())
                handle.flush()
                temp_path = Path(handle.name)
            try:
                subprocess.run([editor, str(temp_path)], check=False)
                return temp_path.read_text(encoding="utf-8")
            finally:
                temp_path.unlink(missing_ok=True)

        content = await self._run_in_terminal(_run, render_cli_done=True)
        self.task_input.buffer.text = content.rstrip()
        self.status_message = self._t("task_editor_loaded")
        self._focus_task_editor()
        self.app.invalidate()

    def _switch_screen(self, screen: str) -> None:
        self.screen = screen
        if screen == "workspace":
            self.status_message = self._t("workspace_ready", path=str(self.workspace))
            self._focus_workspace_list()
        elif screen == "controller":
            self.status_message = self._t("controller_selected", name=_agent_label(self.controller, self.lang))
            self._focus_command_bar()
        elif screen == "task":
            self.status_message = self._planner_notice()
            self._focus_task_editor()
        elif screen == "review":
            self._load_review_item(self.review_index)
            self.status_message = self._t("planning_ready")
            self._focus_review_primary()
        elif screen == "error":
            self.status_message = self._t("planning_failed", error=self.error_message)
            self._focus_command_bar()
        elif screen == "sent":
            self.status_message = self._t("send_done", path=str(self.bundle_path or ""))
            self._focus_command_bar()
        self.app.invalidate()

    def _focus_task_editor(self) -> None:
        try:
            self.app.layout.focus(self.task_input)
        except Exception:  # noqa: BLE001
            return

    def _focus_command_bar(self) -> None:
        try:
            self.app.layout.focus(self.command_input)
        except Exception:  # noqa: BLE001
            return

    def _focus_workspace_list(self) -> None:
        try:
            self.app.layout.focus(self.workspace_list)
        except Exception:  # noqa: BLE001
            self._focus_command_bar()

    def _focus_review_primary(self) -> None:
        try:
            self.app.layout.focus(self.review_title_input)
        except Exception:  # noqa: BLE001
            self._focus_command_bar()

    def _workspace_values(self) -> list[tuple[str, str]]:
        values = [(str(path), str(path)) for path in self.filtered_candidates]
        return values or [(str(self.workspace), str(self.workspace))]

    def _sync_workspace_list(self) -> None:
        values = self._workspace_values()
        self.workspace_list.values = values
        selected = self._selected_candidate()
        selected_text = str(selected) if selected is not None else values[0][0]
        self.workspace_list.current_value = selected_text
        for index, (value, _label) in enumerate(values):
            if value == selected_text:
                self.workspace_list._selected_index = index
                return
        self.workspace_list.current_value = values[0][0]
        self.workspace_list._selected_index = 0

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

    def _save_review_item(self, *, silent: bool = False) -> bool:
        if not self.plan:
            return False
        eta_raw = self.review_eta_input.text.strip()
        if not eta_raw.isdigit() or int(eta_raw) <= 0:
            if not silent:
                self.status_message = self._t("review_bad_eta")
            return False
        item = self.plan[self.review_index]
        item.title = self.review_title_input.text.strip() or item.title
        item.done_when = self.review_done_input.text.strip() or item.done_when
        item.eta_minutes = int(eta_raw)
        selected_agent = str(self.review_agent_list.current_value or "").strip().lower()
        if selected_agent in self.available_agents:
            item.agent = selected_agent
        if not silent:
            self.status_message = self._t("review_saved_form")
            self.app.invalidate()
        return True

    def _visible_plan_items(self) -> list[tuple[int, LabPlanItem]]:
        if not self.plan:
            return []
        if len(self.plan) <= 7:
            return list(enumerate(self.plan))
        start = max(0, self.review_index - 3)
        end = min(len(self.plan), start + 7)
        start = max(0, end - 7)
        return [(index, self.plan[index]) for index in range(start, end)]

    def _planner_notice(self) -> str:
        return self._t("planner_live") if self.planner_mode == "live" else self._t("planner_mock")

    def _footer_hint(self) -> str:
        hints = {
            "en-US": {
                "workspace": "Up/Down move · Enter accepts the highlighted folder · paste a full path or /new <path>",
                "controller": "Left/Right switch controller · Enter continues · type an agent id to jump",
                "task": "Main editor stays large here · Tab switches to the bottom bar · F5 or Ctrl-S requests the plan",
                "planning": "Live planner only by default · no hidden fallback · wait, or Ctrl-C to exit",
                "review": "Up/Down select step · edit the right-side form directly · F5 saves · bottom bar is only for quick actions",
                "error": "Planning stopped here · /retry tries the live controller again · /task returns to editing",
                "sent": "Bundle exported for inspection · /back returns to review · /exit closes",
            },
            "zh-CN": {
                "workspace": "上下键移动 · Enter 直接接受高亮目录 · 也可以粘贴完整路径或输入 /new <路径>",
                "controller": "左右键切换主控 · Enter 继续 · 也可以直接输入 agent id 跳转",
                "task": "这一页保留大编辑区 · Tab 切到底部输入栏 · F5 或 Ctrl-S 请求主控规划",
                "planning": "默认走 live planner · 不会悄悄 fallback · 等待返回，或 Ctrl-C 退出",
                "review": "上下键切换步骤 · 右侧表单直接编辑当前步骤 · F5 保存 · 底部输入栏只做快捷操作",
                "error": "规划在这里被明确中止 · /retry 再试一次 live 主控 · /task 返回任务页",
                "sent": "Bundle 已导出供检查 · /back 回到检查页 · /exit 关闭",
            },
        }
        return hints[self.lang].get(self.screen, self._t("footer"))

    def _result(self, *, status: str) -> UxLabV3Result:
        return UxLabV3Result(
            status=status,
            workspace=self.workspace,
            controller=self.controller,
            task=self.task_value or self.task_input.text.strip(),
            lang=self.lang,
            planner_mode=self.planner_mode,
            plan=list(self.plan),
            bundle_path=self.bundle_path,
            error_message=self.error_message or None,
        )

    def _t(self, key: str, **kwargs: Any) -> str:
        table = TEXT.get(self.lang, TEXT["en-US"])
        return str(table.get(key, key)).format(**kwargs)


__all__ = [
    "CommandBarState",
    "ControllerCard",
    "LabPlanItem",
    "ReviewCommand",
    "UxLabV3Result",
    "WorkspaceSubmission",
    "build_brand_banner",
    "build_command_bar_state",
    "build_controller_cards",
    "build_workspace_preview_lines",
    "build_workspace_hint_line",
    "build_workspace_summary_lines",
    "build_mock_plan_v3",
    "build_planner_prompt",
    "build_review_list_lines",
    "build_step_track",
    "choose_review_layout",
    "choose_workspace_layout",
    "derive_workspace_tree_root",
    "discover_recent_workspaces",
    "export_launch_bundle_v3",
    "interpret_workspace_submission",
    "launch_ux_lab_v3",
    "load_workspace_history",
    "map_controller_plan_to_items",
    "parse_review_command",
    "record_workspace_history",
    "request_live_plan",
    "resolve_v3_language",
]
