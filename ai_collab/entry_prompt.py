from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from math import ceil
from pathlib import Path
import sys
from typing import Callable, Optional

import click
from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from ai_collab.core.config import Config
from ai_collab.core.run_state import RunStateStore

TextInputFn = Callable[..., str]
SelectFn = Callable[..., str]
DispatchFn = Callable[[list[str]], None]
SUPPORTED_LANGS = {"en-US", "zh-CN"}

TEXT = {
    "en-US": {
        "title": "ai-collab",
        "hint": "Choose what you want to do next.",
        "note": "New tasks start by picking a workspace first. Resume also starts by locating the workspace, then choosing a saved run.",
        "root_start": "Start new task",
        "root_start_desc": "Pick a workspace first, then open the task draft and planning flow.",
        "root_resume": "Resume previous session",
        "root_resume_desc": "Locate a workspace, then pick one saved run to recover.",
        "root_config": "Open config",
        "root_config_desc": "Adjust long-term defaults and personal preferences.",
        "root_init": "Run init",
        "root_init_desc": "Revisit language, agents, runtime, and entry defaults.",
        "workspace_new_title": "Workspace for new task",
        "workspace_new_hint": "Choose where this new task should run.",
        "workspace_new_note": "The workspace sets the project root, bundle export location, and future resume history.",
        "workspace_resume_title": "Workspace for resume",
        "workspace_resume_hint": "Locate the workspace that contains the session you want to restore.",
        "workspace_resume_note": "After choosing a workspace, ai-collab will list the runs saved under .ai-collab/runs.",
        "workspace_current": "Use current directory",
        "workspace_current_desc": "Use the folder where you launched ai-collab right now.",
        "workspace_recent": "Choose recent workspace",
        "workspace_recent_desc": "Pick from projects you used recently with ai-collab.",
        "workspace_browse": "Browse folders",
        "workspace_browse_desc": "Walk the directory tree or search / paste a path.",
        "recent_title_new": "Recent workspaces",
        "recent_hint_new": "Choose a recent workspace for the new task.",
        "recent_note_new": "Recent workspaces come from ai-collab history and exported bundles.",
        "recent_title_resume": "Recent workspaces with sessions",
        "recent_hint_resume": "Choose a recent workspace, then pick the session to restore.",
        "recent_note_resume": "Only workspaces with saved runs are useful for resume.",
        "recent_empty_new": "No recent workspaces yet.",
        "recent_empty_resume": "No recent workspaces with resumable sessions yet.",
        "browse_title": "Browse folders",
        "browse_hint": "Move through folders, select the current folder, or search / paste a path.",
        "browse_note": "Entering a full path jumps there directly. Entering a keyword filters the current folder list.",
        "browse_use_current": "Use this folder",
        "browse_use_current_desc": "Current browser location",
        "browse_parent": "Go to parent folder",
        "browse_parent_desc": "Move one level up in the directory tree.",
        "browse_search": "Search or paste path",
        "browse_search_desc": "Type a full path to jump, or a keyword to filter children.",
        "browse_search_prompt": "Path or keyword",
        "browse_search_missing": "That folder does not exist. The value is now used as a keyword filter.",
        "browse_children_prefix": "Open",
        "browse_filter_none": "No filter",
        "session_title": "Choose session to restore",
        "session_hint": "Pick one saved run from this workspace.",
        "session_note": "Recover uses the saved run state under .ai-collab/runs and reattaches tmux resources when possible.",
        "session_empty": "No resumable sessions were found in this workspace.",
        "back": "Back",
        "back_step": "Back to previous step",
        "home": "Back to home",
        "quit": "Quit",
        "footer_live": "↑/↓ move · Enter confirm · q quit · Esc cancel",
        "status_run_count": "{count} resumable runs",
        "status_no_runs": "No saved runs yet",
        "status_current_dir": "Current directory",
        "status_recent_dir": "Recent workspace",
        "status_path_jump": "Jumped to {path}",
        "status_filter": "Filtering children by: {query}",
        "status_page": "Page {page}/{total} · {count} items",
        "status_running": "Running",
        "status_completed": "Completed",
        "status_idle": "Idle",
        "status_degraded": "Needs attention",
        "status_unknown": "Unknown",
        "status_no_steps_label": "No steps",
        "status_prompt_empty": "No task summary recorded",
    },
    "zh-CN": {
        "title": "ai-collab",
        "hint": "选择接下来要做的事。",
        "note": "新任务会先选工作区，再进入任务草稿；恢复会话会先定位工作区，再选择已有运行。",
        "root_start": "开始新任务",
        "root_start_desc": "先选择工作区，再进入任务草稿与规划流程。",
        "root_resume": "恢复之前会话",
        "root_resume_desc": "先定位工作区，再选择一个已保存运行进行恢复。",
        "root_config": "打开配置",
        "root_config_desc": "调整长期默认项与个人偏好。",
        "root_init": "重新初始化",
        "root_init_desc": "重新确认语言、Agent、运行方式与默认入口。",
        "workspace_new_title": "新任务工作区",
        "workspace_new_hint": "先决定这次新任务在哪个目录下运行。",
        "workspace_new_note": "工作区决定项目根目录、bundle 导出位置，以及后续恢复记录归属。",
        "workspace_resume_title": "恢复会话工作区",
        "workspace_resume_hint": "先找到保存这次运行记录的工作区。",
        "workspace_resume_note": "选定工作区后，ai-collab 会列出该目录下 .ai-collab/runs 中的可恢复运行。",
        "workspace_current": "使用当前目录",
        "workspace_current_desc": "直接使用你现在启动 ai-collab 的目录。",
        "workspace_recent": "选择最近工作区",
        "workspace_recent_desc": "从最近使用过的项目目录中挑一个继续。",
        "workspace_browse": "浏览目录",
        "workspace_browse_desc": "按目录树继续进入，也可搜索或直接粘贴路径。",
        "recent_title_new": "最近工作区",
        "recent_hint_new": "为新任务选择一个最近使用过的工作区。",
        "recent_note_new": "最近工作区来自 ai-collab 历史记录与导出的 bundle。",
        "recent_title_resume": "最近工作区中的会话",
        "recent_hint_resume": "先选最近工作区，再从里面选择要恢复的运行。",
        "recent_note_resume": "这里只展示对恢复会话有帮助的最近工作区。",
        "recent_empty_new": "暂时还没有最近工作区。",
        "recent_empty_resume": "最近工作区里还没有可恢复会话。",
        "browse_title": "浏览目录",
        "browse_hint": "在目录间移动，使用当前目录，或搜索 / 粘贴路径直接跳转。",
        "browse_note": "输入完整路径会直接跳到该目录；输入关键字则会过滤当前目录下的子目录。",
        "browse_use_current": "使用这个目录",
        "browse_use_current_desc": "当前浏览位置",
        "browse_parent": "返回上一级目录",
        "browse_parent_desc": "向上回到父目录继续选择。",
        "browse_search": "搜索或粘贴路径",
        "browse_search_desc": "输入完整路径可跳转；输入关键字可过滤子目录。",
        "browse_search_prompt": "路径或关键字",
        "browse_search_missing": "目录不存在，已把输入内容当作当前目录过滤关键字。",
        "browse_children_prefix": "进入",
        "browse_filter_none": "未过滤",
        "session_title": "选择要恢复的会话",
        "session_hint": "从这个工作区里挑一个已保存运行。",
        "session_note": "恢复会使用 .ai-collab/runs 里的保存状态，并尽可能重新接回 tmux 会话资源。",
        "session_empty": "这个工作区里还没有可恢复会话。",
        "back": "返回",
        "back_step": "返回上一步",
        "home": "返回主菜单",
        "quit": "退出",
        "footer_live": "↑/↓ 移动 · Enter 确认 · q 退出 · Esc 取消",
        "status_run_count": "{count} 个可恢复运行",
        "status_no_runs": "暂无已保存运行",
        "status_current_dir": "当前目录",
        "status_recent_dir": "最近工作区",
        "status_path_jump": "已跳转到 {path}",
        "status_filter": "正在按关键字过滤：{query}",
        "status_page": "第 {page}/{total} 页 · 共 {count} 项",
        "status_running": "运行中",
        "status_completed": "已完成",
        "status_idle": "等待中",
        "status_degraded": "需关注",
        "status_unknown": "未知",
        "status_no_steps_label": "未生成步骤",
        "status_prompt_empty": "未记录任务摘要",
    },
}


@dataclass(frozen=True)
class EntryItem:
    value: str
    label: str
    description: str


def _lang(config: Config) -> str:
    candidate = getattr(config, "ui_language", "en-US")
    return candidate if candidate in SUPPORTED_LANGS else "en-US"


def _copy(config: Config) -> dict[str, str]:
    return TEXT[_lang(config)]


def _short_path(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
        return f"~/{relative}" if str(relative) != "." else "~"
    except ValueError:
        return str(resolved)


PAGE_SIZE = 8


def _display_value(value: str) -> str:
    cleaned = str(value or "").strip()
    return f"{cleaned}. " if cleaned else ""


def _step_title(config: Config, current: int, total: int, title: str) -> str:
    return f"Step {current}/{total} · {title}" if _lang(config) == "en-US" else f"步骤 {current}/{total} · {title}"


def _step_labels(config: Config, total: int) -> list[str]:
    lang = _lang(config)
    if total == 5:
        return [
            "Workspace" if lang == "en-US" else "工作区",
            "Task" if lang == "en-US" else "草稿",
            "Controller" if lang == "en-US" else "主控",
            "Plan" if lang == "en-US" else "规划",
            "Confirm" if lang == "en-US" else "确认",
        ]
    if total == 2:
        return [
            "Workspace" if lang == "en-US" else "工作区",
            "Session" if lang == "en-US" else "会话",
        ]
    return [str(index) for index in range(1, total + 1)]


def _step_fragments(config: Config, current: int, total: int) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    labels = _step_labels(config, total)
    for index, label in enumerate(labels, start=1):
        if index < current:
            style = "bold #7DD3FC"
            marker = "✓"
        elif index == current:
            style = "bold #0F172A on #7DD3FC"
            marker = "●"
        else:
            style = "fg:#64748B"
            marker = "○"
        fragments.append((style, f" {marker} {index} {label} "))
        if index < total:
            fragments.append(("fg:#334155", "─"))
    return fragments


def _paginate_items(items: list[EntryItem], *, pointed_value: str, page_size: int = PAGE_SIZE) -> tuple[list[EntryItem], int, int]:
    if len(items) <= page_size:
        return items, 1, 1
    try:
        pointed_index = next(index for index, item in enumerate(items) if item.value == pointed_value)
    except StopIteration:
        pointed_index = 0
    page_index = pointed_index // page_size
    total_pages = ceil(len(items) / page_size)
    start = page_index * page_size
    end = start + page_size
    return items[start:end], page_index + 1, total_pages


def _format_timestamp(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw.replace("T", " ")[:16]
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def _status_label(config: Config, status: str) -> str:
    copy = _copy(config)
    value = str(status or "").strip().lower()
    mapping = {
        "running": copy["status_running"],
        "completed": copy["status_completed"],
        "done": copy["status_completed"],
        "idle": copy["status_idle"],
        "created": copy["status_idle"],
        "degraded": copy["status_degraded"],
    }
    return mapping.get(value, copy["status_unknown"])


def _progress_label(config: Config, value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw == "No steps":
        return _copy(config)["status_no_steps_label"]
    if _lang(config) == "zh-CN" and raw.endswith(" done") and "/" in raw:
        return raw.replace(" done", " 完成")
    return raw


def _controller_label(agent: str) -> str:
    from ai_collab.tui.setup import CONTROLLER_LABELS

    value = str(agent or "").strip()
    return CONTROLLER_LABELS.get(value, value.title() if value else "-")


def _resume_item(config: Config, item: dict[str, object], index: int) -> EntryItem:
    label = str(item.get("name", "")).strip() or str(item.get("short_id", "-")).strip() or "-"
    meta = [
        _status_label(config, str(item.get("status", ""))),
        _progress_label(config, str(item.get("steps_progress", "") or item.get("sx", ""))),
        _controller_label(str(item.get("controller_agent", ""))),
        _format_timestamp(str(item.get("last_active_at", "") or item.get("updated_at", "") or item.get("created_at", ""))),
    ]
    meta_line = " · ".join(part for part in meta if part)
    preview = str(item.get("entry_prompt_preview", "")).strip() or _copy(config)["status_prompt_empty"]
    short_id = str(item.get("short_id", "")).strip()
    preview_line = f"#{short_id} · {preview}" if short_id else preview
    description = meta_line
    if preview_line:
        description = f"{description}\n{preview_line}" if description else preview_line
    return EntryItem(str(index), label, description)


def _row_style(*, value: str, pointed_value: str, default_value: str) -> str:
    if value == pointed_value:
        return "fg:#7DD3FC bold"
    if value == default_value:
        return "fg:#F8FAFC bold"
    return "fg:#CBD5E1"


def _banner_fragments() -> list[tuple[str, str]]:
    from ai_collab.init_prompt import build_init_banner

    fragments: list[tuple[str, str]] = []
    for line in build_init_banner(100):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        fragments.append((style, line))
        fragments.append(("", "\n"))
    fragments.append(("", "\n"))
    return fragments


def _screen_fragments(
    *,
    config: Config,
    title: str,
    hint: str,
    note: str,
    items: list[EntryItem],
    pointed_value: str,
    default_value: str,
    allow_back: bool,
    back_label: str | None = None,
    allow_home: bool = False,
    step_current: int | None = None,
    step_total: int | None = None,
) -> list[tuple[str, str]]:
    copy = _copy(config)
    visible_items, current_page, total_pages = _paginate_items(items, pointed_value=pointed_value)
    fragments = _banner_fragments()
    if step_current is not None and step_total is not None:
        fragments.extend(_step_fragments(config, step_current, step_total))
        fragments.append(("", "\n\n"))
    fragments.append(("bold", title))
    fragments.append(("", "\n"))
    if hint:
        fragments.append(("dim", hint))
        fragments.append(("", "\n"))
    if note:
        fragments.append(("fg:#64748B italic", note))
        fragments.append(("", "\n"))
    if total_pages > 1:
        fragments.append(("fg:#475569", copy["status_page"].format(page=current_page, total=total_pages, count=len(items))))
        fragments.append(("", "\n"))
    fragments.append(("", "\n"))
    for item in visible_items:
        fragments.append(("", "> " if item.value == pointed_value else "  "))
        fragments.append(("fg:#64748B", _display_value(item.value)))
        fragments.append((_row_style(value=item.value, pointed_value=pointed_value, default_value=default_value), item.label))
        fragments.append(("", "\n"))
        if item.description:
            for line in str(item.description).splitlines():
                fragments.append(("", "    "))
                fragments.append(("fg:#64748B italic", line))
                fragments.append(("", "\n"))
    if allow_back:
        fragments.append(("", "> " if pointed_value == "b" else "  "))
        fragments.append(("fg:#64748B", _display_value("b")))
        fragments.append(("fg:#7DD3FC bold" if pointed_value == "b" else "fg:#CBD5E1", back_label or copy["back"]))
        fragments.append(("", "\n"))
    if allow_home:
        fragments.append(("", "> " if pointed_value == "h" else "  "))
        fragments.append(("fg:#64748B", _display_value("h")))
        fragments.append(("fg:#7DD3FC bold" if pointed_value == "h" else "fg:#CBD5E1", copy["home"]))
        fragments.append(("", "\n"))
    fragments.append(("", "> " if pointed_value == "q" else "  "))
    fragments.append(("fg:#64748B", _display_value("q")))
    fragments.append(("fg:#7DD3FC bold" if pointed_value == "q" else "fg:#CBD5E1", copy["quit"]))
    fragments.append(("", "\n\n"))
    fragments.append(("fg:#64748B", copy["footer_live"]))
    return fragments
def _print_fragments(console_obj: Console, fragments: list[tuple[str, str]], *, clear_screen: bool) -> None:
    if clear_screen:
        console_obj.clear()
    line_buffer = Text()
    for style, segment in fragments:
        if segment == "\n":
            console_obj.print(line_buffer)
            line_buffer = Text()
            continue
        if segment == "\n\n":
            console_obj.print(line_buffer)
            console_obj.print()
            line_buffer = Text()
            continue
        line_buffer.append(segment, style=style)
    if line_buffer.plain:
        console_obj.print(line_buffer)


def _prompt_toolkit_style(style: str) -> str:
    normalized = str(style or "").strip()
    if not normalized or " on " not in normalized:
        return normalized
    parts = normalized.split()
    converted: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "on" and index + 1 < len(parts):
            converted.append(f"bg:{parts[index + 1]}")
            index += 2
            continue
        converted.append(part)
        index += 1
    return " ".join(converted)


def _select_screen(
    render_fragments,
    *,
    values: list[str],
    default_value: str,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
    screen_id: str,
) -> str:
    if selector_fn is not None:
        _print_fragments(console_obj, render_fragments(default_value), clear_screen=clear_screen)
        return str(selector_fn(screen=screen_id, choices=values, default_value=default_value))

    if input_fn is not None or not sys.stdin.isatty():
        _print_fragments(console_obj, render_fragments(default_value), clear_screen=clear_screen)
        ask = input_fn or Prompt.ask
        return str(ask("Select", choices=values, default=default_value))

    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    pointed_index = values.index(default_value) if default_value in values else 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens() -> list[tuple[str, str]]:
        return [(_prompt_toolkit_style(style), segment) for style, segment in render_fragments(_current_value())]

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result=_current_value())

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

    if "b" in values:
        @bindings.add("b", eager=True)
        def _back(event) -> None:
            event.app.exit(result="b")

    if "h" in values:
        @bindings.add("h", eager=True)
        def _home(event) -> None:
            event.app.exit(result="h")

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(_tokens, focusable=True, show_cursor=False),
                dont_extend_height=True,
                always_hide_cursor=True,
            )
        ),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
    )
    choice = app.run()
    if choice is None:
        raise click.Abort()
    return str(choice)


def _prompt_text(input_fn: TextInputFn | None, *, label: str, default: str) -> str:
    if input_fn is not None:
        return str(input_fn(label, default=default))
    try:
        return str(Prompt.ask(label, default=default))
    except UnicodeDecodeError:
        try:
            from prompt_toolkit import prompt as pt_prompt
        except Exception:
            return str(default)
        return str(pt_prompt(f"{label} ({default}): ", default=default))


def _root_items(config: Config) -> list[EntryItem]:
    copy = _copy(config)
    return [
        EntryItem("1", copy["root_start"], copy["root_start_desc"]),
        EntryItem("2", copy["root_resume"], copy["root_resume_desc"]),
        EntryItem("3", copy["root_config"], copy["root_config_desc"]),
        EntryItem("4", copy["root_init"], copy["root_init_desc"]),
    ]


def _entry_prompt_fragments(config_obj: Config, *, pointed_value: str = "1") -> list[tuple[str, str]]:
    copy = _copy(config_obj)
    return _screen_fragments(
        config=config_obj,
        title=copy["title"],
        hint=copy["hint"],
        note=copy["note"],
        items=_root_items(config_obj),
        pointed_value=pointed_value,
        default_value="1",
        allow_back=False,
    )


def _render_entry_prompt_screen(
    config_obj: Config,
    *,
    console_obj: Console,
    clear_screen: bool,
    pointed_value: str | None = None,
    live: bool = False,
) -> list[tuple[str, str, str]]:
    items = [(item.value, item.label, item.description) for item in _root_items(config_obj)]
    _print_fragments(console_obj, _entry_prompt_fragments(config_obj, pointed_value=pointed_value or "1"), clear_screen=clear_screen)
    return items


def _select_entry_prompt_with_prompt_toolkit(
    config_obj: Config,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    items = _root_items(config_obj)
    values = [item.value for item in items] + ["q"]
    return _select_screen(
        lambda pointed: _entry_prompt_fragments(config_obj, pointed_value=pointed),
        values=values,
        default_value="1",
        selector_fn=None,
        input_fn=None,
        console_obj=console_obj,
        clear_screen=clear_screen,
        screen_id="entry_root",
    )


def _entry_recent_workspaces(cwd: Path, *, limit: int = 12) -> list[Path]:
    from ai_collab.ux_lab_v3 import discover_recent_workspaces

    resolved = Path(cwd).expanduser().resolve()
    candidates = [resolved]
    if resolved.parent != resolved:
        candidates.append(resolved.parent)
    return discover_recent_workspaces(workspace=resolved, cwd=resolved, candidates=candidates, limit=limit)


def _record_workspace_history(workspace: Path) -> None:
    from ai_collab.ux_lab_v3 import record_workspace_history

    try:
        record_workspace_history(workspace)
    except Exception:
        return


def _run_count(workspace: Path, *, limit: int = 20) -> int:
    return len(RunStateStore.list_runs(cwd=workspace, limit=limit))


def _safe_iterdirs(path: Path) -> list[Path]:
    try:
        items = [item for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")]
    except OSError:
        return []
    return sorted(items, key=lambda item: item.name.lower())


def _select_workspace_source(
    *,
    config: Config,
    mode: str,
    cwd: Path,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> tuple[str, Path | None]:
    copy = _copy(config)
    title = _step_title(config, 1, 5, copy["workspace_new_title"]) if mode == "launch" else _step_title(config, 1, 2, copy["workspace_resume_title"])
    hint = copy["workspace_new_hint"] if mode == "launch" else copy["workspace_resume_hint"]
    note = copy["workspace_new_note"] if mode == "launch" else copy["workspace_resume_note"]
    items = [
        EntryItem("1", copy["workspace_current"], f"{copy['status_current_dir']} · {_short_path(cwd)}"),
        EntryItem("2", copy["workspace_recent"], copy["workspace_recent_desc"]),
        EntryItem("3", copy["workspace_browse"], copy["workspace_browse_desc"]),
    ]
    while True:
        choice = _select_screen(
            lambda pointed: _screen_fragments(
                config=config,
                title=title,
                hint=hint,
                note=note,
                items=items,
                pointed_value=pointed,
                default_value="1",
                allow_back=True,
                back_label=copy["home"],
                step_current=1 if mode == "launch" else 1,
                step_total=5 if mode == "launch" else 2,
            ),
            values=["1", "2", "3", "b", "q"],
            default_value="1",
            selector_fn=selector_fn,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            screen_id=f"workspace_source_{mode}",
        )
        if choice == "1":
            return ("selected", cwd)
        if choice == "2":
            result, workspace = _select_recent_workspace(
                config=config,
                mode=mode,
                cwd=cwd,
                selector_fn=selector_fn,
                input_fn=input_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if result == "selected":
                return result, workspace
            if result == "quit":
                return result, None
            continue
        if choice == "3":
            result, workspace = _browse_workspace(
                config=config,
                mode=mode,
                cwd=cwd,
                selector_fn=selector_fn,
                input_fn=input_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if result == "selected":
                return result, workspace
            if result == "quit":
                return result, None
            continue
        if choice == "b":
            return ("back", None)
        return ("quit", None)


def _select_recent_workspace(
    *,
    config: Config,
    mode: str,
    cwd: Path,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> tuple[str, Path | None]:
    copy = _copy(config)
    recent = _entry_recent_workspaces(cwd)
    run_counts = {path: _run_count(path) for path in recent}
    if mode == "resume":
        recent = [path for path in recent if run_counts.get(path, 0) > 0]
    title = _step_title(config, 1, 5, copy["recent_title_new"]) if mode == "launch" else _step_title(config, 1, 2, copy["recent_title_resume"])
    hint = copy["recent_hint_new"] if mode == "launch" else copy["recent_hint_resume"]
    note = copy["recent_note_new"] if mode == "launch" else copy["recent_note_resume"]
    items = [
        EntryItem(
            str(index),
            _short_path(path),
            (copy["status_run_count"].format(count=run_counts.get(path, 0)) if run_counts.get(path, 0) > 0 else copy["status_no_runs"]),
        )
        for index, path in enumerate(recent, start=1)
    ]
    if not items:
        note = f"{note}\n{copy['recent_empty_new' if mode == 'launch' else 'recent_empty_resume']}"
    values = [item.value for item in items] + ["b", "h", "q"]
    default_value = items[0].value if items else "b"
    choice = _select_screen(
        lambda pointed: _screen_fragments(
            config=config,
            title=title,
            hint=hint,
            note=note,
            items=items,
            pointed_value=pointed,
            default_value=default_value,
            allow_back=True,
            back_label=copy["back_step"],
            step_current=1 if mode == "launch" else 1,
            step_total=5 if mode == "launch" else 2,
        ),
        values=values,
        default_value=default_value,
        selector_fn=selector_fn,
        input_fn=input_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
        screen_id=f"recent_workspace_{mode}",
    )
    if choice == "b":
        return ("back", None)
    if choice == "h":
        return ("home", None)
    if choice == "q":
        return ("quit", None)
    selected = recent[int(choice) - 1]
    return ("selected", selected)


def _browse_workspace(
    *,
    config: Config,
    mode: str,
    cwd: Path,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> tuple[str, Path | None]:
    copy = _copy(config)
    current = Path(cwd).expanduser().resolve()
    query = ""
    status = ""
    while True:
        children = _safe_iterdirs(current)
        filtered = [path for path in children if query in path.name.lower()] if query else children
        items = [
            EntryItem("1", copy["browse_use_current"], f"{copy['browse_use_current_desc']} · {_short_path(current)}"),
            EntryItem("2", copy["browse_parent"], f"{copy['browse_parent_desc']} · {_short_path(current.parent if current.parent != current else current)}"),
            EntryItem("3", copy["browse_search"], f"{copy['browse_search_desc']} · {query or copy['browse_filter_none']}"),
        ]
        for index, path in enumerate(filtered, start=4):
            items.append(EntryItem(str(index), f"{copy['browse_children_prefix']} · {path.name}", _short_path(path)))
        note = copy["browse_note"]
        if status:
            note = f"{note}\n{status}"
        values = [item.value for item in items] + ["b", "q"]
        choice = _select_screen(
            lambda pointed: _screen_fragments(
                config=config,
                title=_step_title(config, 1, 5, copy["browse_title"]) if mode == "launch" else _step_title(config, 1, 2, copy["browse_title"]),
                hint=f"{copy['browse_hint']} · {_short_path(current)}",
                note=note,
                items=items,
                pointed_value=pointed,
                default_value="1",
                allow_back=True,
                back_label=copy["back_step"],
                step_current=1,
                step_total=5 if mode == "launch" else 2,
            ),
            values=values,
            default_value="1",
            selector_fn=selector_fn,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            screen_id="browse_workspace",
        )
        status = ""
        if choice == "1":
            return ("selected", current)
        if choice == "2":
            if current.parent != current:
                current = current.parent
            continue
        if choice == "3":
            value = _prompt_text(input_fn, label=copy["browse_search_prompt"], default=str(current)).strip()
            if not value:
                query = ""
                continue
            candidate = Path(value).expanduser()
            if candidate.exists() and candidate.is_dir():
                current = candidate.resolve()
                query = ""
                status = copy["status_path_jump"].format(path=_short_path(current))
            else:
                query = value.lower()
                status = copy["status_filter"].format(query=value)
            continue
        if choice == "b":
            return ("back", None)
        if choice == "q":
            return ("quit", None)
        index = int(choice) - 4
        if 0 <= index < len(filtered):
            current = filtered[index]


def _select_resume_run(
    *,
    config: Config,
    workspace: Path,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> tuple[str, str | None]:
    copy = _copy(config)
    runs = RunStateStore.list_runs(cwd=workspace, limit=40)
    items = [_resume_item(config, item, index) for index, item in enumerate(runs, start=1)]
    note = copy["session_note"] if items else f"{copy['session_note']}\n{copy['session_empty']}"
    values = [item.value for item in items] + ["b", "q"]
    default_value = items[0].value if items else "b"
    choice = _select_screen(
        lambda pointed: _screen_fragments(
            config=config,
            title=_step_title(config, 2, 2, copy["session_title"]),
            hint=f"{copy['session_hint']} · {_short_path(workspace)}",
            note=note,
            items=items,
            pointed_value=pointed,
            default_value=default_value,
            allow_back=True,
            back_label=copy["back_step"],
            allow_home=True,
            step_current=2,
            step_total=2,
        ),
        values=values,
        default_value=default_value,
        selector_fn=selector_fn,
        input_fn=input_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
        screen_id="resume_session",
    )
    if choice == "b":
        return ("back", None)
    if choice == "h":
        return ("home", None)
    if choice == "q":
        return ("quit", None)
    return ("selected", str(runs[int(choice) - 1].get("run_id", "")).strip())


def run_entry_prompt(
    config_obj: Config,
    *,
    input_fn: Callable[..., str] | None = None,
    selector_fn: Callable[..., str] | None = None,
    console_obj: Console | None = None,
    clear_screen: bool = True,
    dispatch_command: DispatchFn | None = None,
    cwd: Path | None = None,
) -> None:
    console_obj = console_obj or Console(force_terminal=True)
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    dispatch = dispatch_command or (lambda args: None)

    while True:
        choice = _select_screen(
            lambda pointed: _entry_prompt_fragments(config_obj, pointed_value=pointed),
            values=["1", "2", "3", "4", "q"],
            default_value="1",
            selector_fn=selector_fn,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            screen_id="entry_root",
        )
        if choice == "q":
            return
        if choice == "3":
            from ai_collab.config_prompt import run_config_menu_prompt

            kwargs = {
                "console_obj": console_obj,
                "clear_screen": clear_screen,
            }
            if selector_fn is not None:
                def _config_selector(*args, **kwargs_inner):
                    items = args[1] if len(args) > 1 else []
                    choices = [str(getattr(item, "value", "")).strip() for item in items if str(getattr(item, "value", "")).strip()]
                    choices.append("q")
                    default_value = choices[0] if choices else "q"
                    return selector_fn(screen="config_menu", choices=choices, default_value=default_value)
                kwargs["selector_fn"] = _config_selector
            if input_fn is not None:
                kwargs["input_fn"] = input_fn
            run_config_menu_prompt(config_obj, **kwargs)
            continue
        if choice == "4":
            from ai_collab.init_prompt import run_init_prompt

            kwargs = {
                "console_obj": console_obj,
                "clear_screen": clear_screen,
            }
            if selector_fn is not None:
                def _init_selector(*args, **kwargs_inner):
                    screen = args[1] if len(args) > 1 else None
                    options = getattr(screen, "options", [])
                    choices = [str(value).strip() for value, _label in options if str(value).strip()]
                    if kwargs_inner.get("allow_back"):
                        choices.append("b")
                    choices.append("q")
                    default_value = choices[0] if choices else "q"
                    screen_id = getattr(screen, "step_id", "init")
                    return selector_fn(screen=screen_id, choices=choices, default_value=default_value)
                kwargs["selector_fn"] = _init_selector
            if input_fn is not None:
                kwargs["input_fn"] = input_fn
            try:
                run_init_prompt(config_obj, **kwargs)
            except click.Abort:
                pass
            continue
        if choice == "1":
            while True:
                result, workspace = _select_workspace_source(
                    config=config_obj,
                    mode="launch",
                    cwd=root,
                    selector_fn=selector_fn,
                    input_fn=input_fn,
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
                if result == "back":
                    break
                if result == "quit" or workspace is None:
                    return
                _record_workspace_history(workspace)
                from ai_collab.launch_prompt import run_launch_prompt

                launch_result = run_launch_prompt(
                    config=config_obj,
                    cwd=workspace,
                    workspace=workspace,
                    controller=None,
                    task=None,
                    task_file=None,
                    planner_mode="live",
                    output_bundle=None,
                    input_fn=input_fn,
                    selector_fn=selector_fn,
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                    from_entry=True,
                )
                if launch_result == "back":
                    continue
                if launch_result == "home":
                    break
                return
            continue
        if choice == "2":
            while True:
                result, workspace = _select_workspace_source(
                    config=config_obj,
                    mode="resume",
                    cwd=root,
                    selector_fn=selector_fn,
                    input_fn=input_fn,
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
                if result == "back":
                    break
                if result == "quit" or workspace is None:
                    return
                run_result, run_id = _select_resume_run(
                    config=config_obj,
                    workspace=workspace,
                    selector_fn=selector_fn,
                    input_fn=input_fn,
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
                if run_result == "back":
                    continue
                if run_result == "home":
                    break
                if run_result == "quit" or not run_id:
                    return
                _record_workspace_history(workspace)
                dispatch(["resume", "recover", run_id, "-w", str(workspace)])
                return
            continue
__all__ = [
    "_entry_prompt_fragments",
    "_render_entry_prompt_screen",
    "_select_entry_prompt_with_prompt_toolkit",
    "run_entry_prompt",
]
