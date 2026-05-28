"""Thin prompt-style init flow for ai-collab."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from io import StringIO
from typing import Callable, Literal

import click
from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from ai_collab.core.config import Config
from ai_collab.tui.setup import (
    CONTROLLER_LABELS,
    ENTRY_SURFACE_LABELS,
    LANGUAGE_LABELS,
    RUNTIME_MODE_LABELS,
    SetupFormData,
    apply_setup_form,
    resolve_setup_defaults,
)

InputFn = Callable[..., str]
SelectFn = Callable[..., str]
SelectionMode = Literal["single", "multi"]
SUPPORTED_LANGS = {"en-US", "zh-CN"}
ALL_AGENTS = ("codex", "claude", "gemini")
AGENT_VALUE_MAP = {"1": "codex", "2": "claude", "3": "gemini"}
STEP_ORDER = (
    "language",
    "enabled_agents",
    "controller",
    "runtime",
    "entry",
    "collaboration",
    "review",
)
BANNER_SUBTITLE = "multi-agent coding orchestrator"
PROVIDER_THEME = {
    "codex": "#06B6D4",
    "claude": "#FB923C",
    "gemini": "#22C55E",
}
TEXT = {
    "en-US": {
        "step": "Step",
        "title_language": "Display language",
        "hint_language": "Choose the display language for ai-collab.",
        "title_enabled_agents": "Enabled agents",
        "hint_enabled_agents": "Pick which agents stay enabled by default.",
        "note_enabled_agents": "All agents start enabled. Use Enter / Space to toggle, c to continue, and keep at least one agent enabled.",
        "title_controller": "Default controller",
        "hint_controller": "Pick the lead agent from the enabled agents.",
        "note_controller": "You can change this later with ai-collab config or /config in the interactive console.",
        "option_controller_codex_desc": "Best for end-to-end implementation, refactors, tests, and parallel agent workflows.",
        "option_controller_claude_desc": "Best for codebase understanding, editing, debugging, and workflow automation.",
        "option_controller_gemini_desc": "Best for large context, multimodal input, research, and terminal automation.",
        "title_runtime": "Default runtime",
        "hint_runtime": "Choose how ai-collab runs longer multi-agent sessions.",
        "note_runtime": "Currently enabled: {agents}. tmux is the stable choice for long-running collaboration; direct is lighter but depends more on your current terminal environment.",
        "title_entry": "Default entry",
        "hint_entry": "Choose how ai-collab greets you after setup.",
        "title_collaboration": "Auto collaboration",
        "hint_collaboration": "Decide whether collaboration starts enabled by default.",
        "option_collab_on_desc": "New tasks start with the controller deciding whether to delegate work to other agents.",
        "option_collab_off_desc": "New tasks stay controller-only until you explicitly delegate work yourself.",
        "title_review": "Review",
        "hint_review": "Confirm the draft before writing ~/.ai-collab/config.json.",
        "option_tmux": "tmux (stable, recommended)",
        "option_tmux_desc": "Best for longer sessions, pane watching, and stable collaboration.",
        "option_direct": "direct (lightweight, advanced)",
        "option_direct_desc": "Starts more directly, but terminal control and compatibility depend more on the current environment.",
        "option_guided": "Guided launcher",
        "option_guided_desc": "Start in the guided menu for common flows.",
        "option_command": "Command-first",
        "option_command_desc": "Jump straight into the minimal command surface.",
        "option_collab_on": "Enabled",
        "option_collab_off": "Manual / disabled",
        "option_save": "Save and finish",
        "option_save_desc": "Write the config file and finish setup.",
        "option_advanced": "Open advanced config",
        "option_advanced_desc": "Open the config menu to adjust finer default preferences and long-term habits.",
        "option_back": "Go back",
        "option_back_desc": "Return to the previous step and adjust the draft.",
        "current_defaults": "Current defaults",
        "section_ui": "Interface",
        "section_agents": "Agents",
        "section_runtime": "Runtime",
        "section_ui_icon": "🖥",
        "section_agents_icon": "🤖",
        "section_runtime_icon": "⚙",
        "label_language": "Language",
        "label_controller": "Controller",
        "label_providers": "Enabled agents",
        "label_runtime": "Default runtime",
        "label_entry": "Default entry",
        "label_collaboration": "Auto collaboration",
        "value_entry_guided": "Guided launcher",
        "value_entry_command": "Command-first",
        "value_runtime_tmux": "tmux (stable, recommended)",
        "value_runtime_direct": "direct (lightweight, advanced)",
        "value_collaboration_on": "Enabled",
        "value_collaboration_off": "Manual",
        "footer_text": "Type a number · Enter confirm · b back · q quit",
        "footer_text_multi": "Type numbers like 1,3 (blank keeps all) · Enter confirm · b back · q quit",
        "footer_text_review": "Type a number · Enter confirm · q quit",
        "footer_live": "↑/↓ move · Enter confirm · b back · q quit · Esc cancel",
        "footer_live_multi": "↑/↓ move · Enter/Space toggle · c continue · b back · q quit · Esc cancel",
        "footer_live_review": "↑/↓ move · Enter confirm · q quit · Esc cancel",
        "default_tag": " default",
        "continue": "Continue",
        "back": "Back",
        "quit": "Quit setup",
    },
    "zh-CN": {
        "step": "步骤",
        "title_language": "显示语言",
        "hint_language": "选择 ai-collab 的显示语言。",
        "title_enabled_agents": "启用 Agent",
        "hint_enabled_agents": "选择哪些 Agent 默认保持启用。",
        "note_enabled_agents": "默认全部启用。使用 Enter / Space 切换，c 继续，并至少保留一个 Agent。",
        "title_controller": "默认主控",
        "hint_controller": "从已启用的 Agent 中选择默认主控。",
        "note_controller": "之后可在 ai-collab config 或交互终端的 /config 随时修改。",
        "option_controller_codex_desc": "适合端到端工程执行、重构、测试与并行 Agent 工作流。",
        "option_controller_claude_desc": "适合代码库理解、编辑、调试与工作流自动化。",
        "option_controller_gemini_desc": "适合大上下文、多模态输入、搜索调研与终端自动化。",
        "title_runtime": "默认运行方式",
        "hint_runtime": "选择 ai-collab 默认执行多 Agent 任务的方式。",
        "note_runtime": "当前已启用：{agents}。tmux 更适合长期会话、分屏观察与稳定协作；direct 更轻，但终端接管与兼容性更依赖当前环境。",
        "title_entry": "默认入口",
        "hint_entry": "选择初始化完成后 ai-collab 默认进入的入口。",
        "title_collaboration": "自动协作",
        "hint_collaboration": "决定新会话是否默认开启协作。",
        "option_collab_on_desc": "新任务会先由主控判断，再按需要派发给其他 Agent。",
        "option_collab_off_desc": "默认只使用主控，需要时再手动分配给其他 Agent。",
        "title_review": "确认配置",
        "hint_review": "确认这些默认设置，然后写入 ~/.ai-collab/config.json。",
        "option_tmux": "tmux（稳定，推荐）",
        "option_tmux_desc": "适合长期会话、分屏观察与稳定协作。",
        "option_direct": "direct（轻量，进阶）",
        "option_direct_desc": "启动更直接，但终端接管与兼容性更依赖当前环境。",
        "option_guided": "引导式启动器",
        "option_guided_desc": "从引导式菜单开始，适合常用操作流程。",
        "option_command": "命令优先",
        "option_command_desc": "直接进入最简命令入口，适合熟悉命令的用户。",
        "option_collab_on": "启用",
        "option_collab_off": "手动 / 禁用",
        "option_save": "保存并完成",
        "option_save_desc": "写入配置文件并结束初始化。",
        "option_advanced": "进入详细配置",
        "option_advanced_desc": "进入 config 菜单，继续调整更细的默认偏好与长期习惯。",
        "option_back": "返回上一步",
        "option_back_desc": "回到上一项继续调整当前草稿。",
        "current_defaults": "当前配置",
        "section_ui": "界面",
        "section_agents": "Agent",
        "section_runtime": "运行",
        "section_ui_icon": "🖥",
        "section_agents_icon": "🤖",
        "section_runtime_icon": "⚙",
        "label_language": "语言",
        "label_controller": "主控",
        "label_providers": "启用 Agent",
        "label_runtime": "默认运行方式",
        "label_entry": "默认入口",
        "label_collaboration": "自动协作",
        "value_entry_guided": "引导式启动器",
        "value_entry_command": "命令优先",
        "value_runtime_tmux": "tmux（稳定，推荐）",
        "value_runtime_direct": "direct（轻量，进阶）",
        "value_collaboration_on": "启用",
        "value_collaboration_off": "手动",
        "footer_text": "输入数字 · Enter 确认 · b 返回 · q 退出",
        "footer_text_multi": "输入如 1,3（留空保持全选） · Enter 确认 · b 返回 · q 退出",
        "footer_text_review": "输入数字 · Enter 确认 · q 退出",
        "footer_live": "↑/↓ 移动 · Enter 确认 · b 返回 · q 退出 · Esc 取消",
        "footer_live_multi": "↑/↓ 移动 · Enter/Space 切换 · c 继续 · b 返回 · q 退出 · Esc 取消",
        "footer_live_review": "↑/↓ 移动 · Enter 确认 · q 退出 · Esc 取消",
        "default_tag": " 默认",
        "continue": "继续",
        "back": "返回",
        "quit": "退出设置",
    },
}


@dataclass
class InitPromptState:
    form: SetupFormData

    @classmethod
    def from_config(cls, config: Config) -> "InitPromptState":
        form = resolve_setup_defaults(config)
        if not any(form.providers.get(name, False) for name in ALL_AGENTS):
            form.providers = {name: True for name in ALL_AGENTS}
        return cls(form=form)


@dataclass(frozen=True)
class InitPromptScreen:
    step_id: str
    title: str
    hint: str
    options: list[tuple[str, str]]
    default_value: str
    progress_index: int
    progress_total: int
    selection_mode: SelectionMode = "single"
    descriptions: dict[str, str] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class InitSelectorRow:
    value: str
    prefix: str
    marker: str
    marker_style: str
    label: str
    label_style: str
    description: str = ""
    description_style: str = "fg:#64748B italic"
    meta: str = ""
    meta_style: str = ""
    is_pointed: bool = False
    is_default: bool = False
    checked: bool = False
    provider: str | None = None



def _lang(value: str | None) -> str:
    return value if value in SUPPORTED_LANGS else "en-US"



def _msg(lang: str, key: str) -> str:
    return TEXT[_lang(lang)][key]



def build_init_banner(width: int = 90) -> list[str]:
    if width < 56:
        return ["AI COLLAB", BANNER_SUBTITLE]
    if width >= 100:
        banner = [
            "   █████╗ ██╗        ██████╗ ██████╗ ██╗     ██╗      █████╗ ██████╗ ",
            "  ██╔══██╗██║       ██╔════╝██╔═══██╗██║     ██║     ██╔══██╗██╔══██╗",
            "  ███████║██║       ██║     ██║   ██║██║     ██║     ███████║██████╔╝",
            "  ██╔══██║██║       ██║     ██║   ██║██║     ██║     ██╔══██║██╔══██╗",
            "  ██║  ██║██║       ╚██████╗╚██████╔╝███████╗███████╗██║  ██║██████╔╝",
            "  ╚═╝  ╚═╝╚═╝        ╚═════╝ ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝ ",
            BANNER_SUBTITLE,
        ]
        return [line[:width].rstrip() for line in banner]
    banner = [
        "    _    ___      ___      _ _       _",
        "   / \\  |_ _|    / __|___ | | | __ _| |__",
        "  / _ \\  | |    | (__/ _ \\| | |/ _` | '_ \\",
        " /_/ \\_\\|___|    \\___\\___/|_|_|\\__,_|_.__/",
        BANNER_SUBTITLE,
    ]
    return [line[:width].rstrip() for line in banner]



def _enabled_agents(form: SetupFormData) -> list[str]:
    enabled = [name for name in ALL_AGENTS if form.providers.get(name, False)]
    return enabled or list(ALL_AGENTS)



def _set_enabled_agents(form: SetupFormData, enabled_agents: list[str]) -> None:
    enabled_set = set(enabled_agents) or {ALL_AGENTS[0]}
    form.providers = {name: name in enabled_set for name in ALL_AGENTS}
    if form.controller not in enabled_set:
        form.controller = next(name for name in ALL_AGENTS if name in enabled_set)



def _enabled_agents_display(lang: str, form: SetupFormData) -> str:
    labels = [CONTROLLER_LABELS.get(name, name.title()) for name in _enabled_agents(form)]
    return '、'.join(labels) if lang == 'zh-CN' else ', '.join(labels)



def _runtime_note(state: InitPromptState) -> str:
    lang = _lang(state.form.ui_language)
    return _msg(lang, 'note_runtime').format(agents=_enabled_agents_display(lang, state.form))



def _enabled_agent_values(form: SetupFormData) -> list[str]:
    return [value for value, agent in AGENT_VALUE_MAP.items() if form.providers.get(agent, False)]



def _resolve_screen(state: InitPromptState, step_id: str) -> InitPromptScreen:
    lang = _lang(state.form.ui_language)
    progress_index = STEP_ORDER.index(step_id) + 1
    progress_total = len(STEP_ORDER)
    if step_id == "language":
        return InitPromptScreen(
            step_id=step_id,
            title=_msg(lang, "title_language"),
            hint=_msg(lang, "hint_language"),
            options=[("1", "English (en-US)"), ("2", "中文 (zh-CN)")],
            default_value="1",
            progress_index=progress_index,
            progress_total=progress_total,
            selection_mode="single",
        )
    if step_id == "enabled_agents":
        return InitPromptScreen(
            step_id=step_id,
            title=_msg(lang, "title_enabled_agents"),
            hint=_msg(lang, "hint_enabled_agents"),
            options=[(str(index + 1), CONTROLLER_LABELS[name]) for index, name in enumerate(ALL_AGENTS)],
            default_value="1",
            progress_index=progress_index,
            progress_total=progress_total,
            selection_mode="multi",
            descriptions={
                str(index + 1): _msg(lang, f"option_controller_{name}_desc")
                for index, name in enumerate(ALL_AGENTS)
            },
            note=_msg(lang, "note_enabled_agents"),
        )
    if step_id == "controller":
        enabled = _enabled_agents(state.form)
        options = [(str(index + 1), CONTROLLER_LABELS[name]) for index, name in enumerate(enabled)]
        return InitPromptScreen(
            step_id=step_id,
            title=_msg(lang, "title_controller"),
            hint=_msg(lang, "hint_controller"),
            options=options,
            default_value="1",
            progress_index=progress_index,
            progress_total=progress_total,
            selection_mode="single",
            descriptions={
                str(index + 1): _msg(lang, f"option_controller_{name}_desc")
                for index, name in enumerate(enabled)
            },
            note=_msg(lang, "note_controller"),
        )
    if step_id == "runtime":
        return InitPromptScreen(
            step_id=step_id,
            title=_msg(lang, "title_runtime"),
            hint=_msg(lang, "hint_runtime"),
            options=[("1", _msg(lang, "option_tmux")), ("2", _msg(lang, "option_direct"))],
            default_value="1",
            progress_index=progress_index,
            progress_total=progress_total,
            selection_mode="single",
            descriptions={
                "1": _msg(lang, "option_tmux_desc"),
                "2": _msg(lang, "option_direct_desc"),
            },
            note=_runtime_note(state),
        )
    if step_id == "entry":
        return InitPromptScreen(
            step_id=step_id,
            title=_msg(lang, "title_entry"),
            hint=_msg(lang, "hint_entry"),
            options=[("1", _msg(lang, "option_guided")), ("2", _msg(lang, "option_command"))],
            default_value="1",
            progress_index=progress_index,
            progress_total=progress_total,
            selection_mode="single",
            descriptions={
                "1": _msg(lang, "option_guided_desc"),
                "2": _msg(lang, "option_command_desc"),
            },
        )
    if step_id == "collaboration":
        return InitPromptScreen(
            step_id=step_id,
            title=_msg(lang, "title_collaboration"),
            hint=_msg(lang, "hint_collaboration"),
            options=[("1", _msg(lang, "option_collab_on")), ("2", _msg(lang, "option_collab_off"))],
            default_value="1",
            progress_index=progress_index,
            progress_total=progress_total,
            selection_mode="single",
            descriptions={
                "1": _msg(lang, "option_collab_on_desc"),
                "2": _msg(lang, "option_collab_off_desc"),
            },
        )
    return InitPromptScreen(
        step_id=step_id,
        title=_msg(lang, "title_review"),
        hint=_msg(lang, "hint_review"),
        options=[("1", _msg(lang, "option_save")), ("2", _msg(lang, "option_back")), ("3", _msg(lang, "option_advanced"))],
        default_value="1",
        progress_index=progress_index,
        progress_total=progress_total,
        selection_mode="single",
        descriptions={
            "1": _msg(lang, "option_save_desc"),
            "2": _msg(lang, "option_back_desc"),
            "3": _msg(lang, "option_advanced_desc"),
        },
    )



def _entry_label(lang: str, entry_surface: str) -> str:
    mapping = {
        "guided": _msg(lang, "value_entry_guided"),
        "command": _msg(lang, "value_entry_command"),
    }
    return mapping.get(entry_surface, entry_surface)



def _runtime_label(lang: str, runtime_mode: str) -> str:
    mapping = {
        "tmux": _msg(lang, "value_runtime_tmux"),
        "direct": _msg(lang, "value_runtime_direct"),
    }
    return mapping.get(runtime_mode, runtime_mode)



def _review_sections(form: SetupFormData) -> list[tuple[str, str, list[tuple[str, str]]]]:
    lang = _lang(form.ui_language)
    providers = [CONTROLLER_LABELS.get(name, name.title()) for name in _enabled_agents(form)]
    collaboration = _msg(lang, "value_collaboration_on") if form.auto_collaboration_enabled else _msg(lang, "value_collaboration_off")
    return [
        (
            _msg(lang, "section_ui_icon"),
            _msg(lang, "section_ui"),
            [
                (_msg(lang, "label_language"), LANGUAGE_LABELS.get(form.ui_language, form.ui_language)),
                (_msg(lang, "label_entry"), _entry_label(lang, form.entry_surface)),
            ],
        ),
        (
            _msg(lang, "section_agents_icon"),
            _msg(lang, "section_agents"),
            [
                (_msg(lang, "label_controller"), CONTROLLER_LABELS.get(form.controller, form.controller.title())),
                (_msg(lang, "label_providers"), ", ".join(providers)),
            ],
        ),
        (
            _msg(lang, "section_runtime_icon"),
            _msg(lang, "section_runtime"),
            [
                (_msg(lang, "label_runtime"), _runtime_label(lang, form.runtime_mode)),
                (_msg(lang, "label_collaboration"), collaboration),
            ],
        ),
    ]



def _build_review_summary_lines(form: SetupFormData) -> list[str]:
    lines: list[str] = []
    for index, (icon, title, items) in enumerate(_review_sections(form)):
        if index:
            lines.append("")
        lines.append(f"{icon} {title}")
        for label, value in items:
            lines.append(f"  • {label}: {value}")
    return lines



def _screen_width(console_obj: Console | None) -> int:
    if console_obj is None:
        return 90
    try:
        return max(72, min(int(console_obj.width), 160))
    except Exception:
        return 90



def _progress_heading(screen: InitPromptScreen, lang: str) -> str:
    return f"{_msg(lang, 'step')} {screen.progress_index}/{screen.progress_total} · {screen.title}"



def _review_section_titles(lang: str) -> set[str]:
    return {
        f"{_msg(lang, 'section_ui_icon')} {_msg(lang, 'section_ui')}",
        f"{_msg(lang, 'section_agents_icon')} {_msg(lang, 'section_agents')}",
        f"{_msg(lang, 'section_runtime_icon')} {_msg(lang, 'section_runtime')}",
    }



def _provider_value_fragments(value: str) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    parts = [part.strip() for part in value.split(",")]
    for index, part in enumerate(parts):
        provider_key = next((name for name, label in CONTROLLER_LABELS.items() if label == part), None)
        style = f"bold {PROVIDER_THEME[provider_key]}" if provider_key in PROVIDER_THEME else "bold white"
        fragments.append((style, part))
        if index < len(parts) - 1:
            fragments.append(("dim", ", "))
    return fragments



def _review_value_text(label: str, value: str) -> Text:
    text = Text("  • ", style="dim")
    text.append(f"{label}: ", style="#94A3B8")
    if label in {"Enabled agents", "启用 Agent"}:
        for style, fragment in _provider_value_fragments(value):
            text.append(fragment, style=style)
        return text
    provider_key = next((name for name, provider_label in CONTROLLER_LABELS.items() if provider_label == value), None)
    if provider_key in PROVIDER_THEME:
        text.append(value, style=f"bold {PROVIDER_THEME[provider_key]}")
        return text
    if value in {_msg("en-US", "value_collaboration_on"), _msg("zh-CN", "value_collaboration_on")}:
        text.append(value, style="bold #22C55E")
        return text
    if value in {_msg("en-US", "value_collaboration_off"), _msg("zh-CN", "value_collaboration_off")}:
        text.append(value, style="#94A3B8")
        return text
    if value in {
        _msg("en-US", "value_entry_guided"),
        _msg("zh-CN", "value_entry_guided"),
        _msg("en-US", "value_runtime_tmux"),
        _msg("zh-CN", "value_runtime_tmux"),
    }:
        text.append(value, style="bold #E2E8F0")
        return text
    text.append(value, style="white")
    return text



def _print_review_summary(console_obj: Console, form: SetupFormData, *, lang: str) -> None:
    console_obj.print(Text(_msg(lang, "current_defaults"), style="bold #F8FAFC"))
    for index, (icon, title, items) in enumerate(_review_sections(form)):
        if index:
            console_obj.print()
        console_obj.print(Text(f"{icon} {title}", style="bold #E5E7EB"))
        for label, value in items:
            console_obj.print(_review_value_text(label, value))



def _footer_key(screen: InitPromptScreen) -> str:
    if screen.step_id == 'review':
        return 'footer_text_review'
    return 'footer_text_multi' if screen.selection_mode == 'multi' else 'footer_text'



def _live_footer_key(screen: InitPromptScreen) -> str:
    if screen.step_id == 'review':
        return 'footer_live_review'
    return 'footer_live_multi' if screen.selection_mode == 'multi' else 'footer_live'



def render_init_prompt_screen(config_or_state: Config | InitPromptState, *, step_id: str = "language") -> str:
    state = config_or_state if isinstance(config_or_state, InitPromptState) else InitPromptState.from_config(config_or_state)
    screen = _resolve_screen(state, step_id)
    lang = _lang(state.form.ui_language)
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    for line in build_init_banner(90):
        style = "bold #7DD3FC" if line != BANNER_SUBTITLE else "dim"
        console.print(Text(line, style=style))
    console.print()
    console.print(Text(_progress_heading(screen, lang), style="bold"))
    console.print(Text(screen.hint, style="dim"))
    if screen.note:
        console.print(Text(screen.note, style="dim italic"))
    console.print()
    if screen.selection_mode == "multi":
        checked_values = set(_enabled_agent_values(state.form))
        for value, label in screen.options:
            marker = "●" if value in checked_values else "○"
            console.print(f"  {marker} {value}. {label}")
            description = screen.descriptions.get(value, "")
            if description:
                console.print(Text(f"      {description}", style="dim italic"))
    else:
        for value, label in screen.options:
            prefix = "›" if value == screen.default_value else " "
            console.print(f"{prefix} {value}. {label}")
            description = screen.descriptions.get(value, "")
            if description:
                console.print(Text(f"    {description}", style="dim italic"))
    if step_id == "review":
        console.print()
        _print_review_summary(console, state.form, lang=lang)
    console.print()
    console.print(Text(_msg(lang, _footer_key(screen)), style="dim"))
    return buffer.getvalue().rstrip() + "\n"



def _prompt_input(prompt: str, *, choices: list[str], default: str) -> str:
    return Prompt.ask(prompt, choices=choices, default=default)



def _prompt_multi_input(prompt: str, *, default: str) -> str:
    return Prompt.ask(prompt, default=default)



def _provider_for_option(state: InitPromptState, screen: InitPromptScreen, value: str) -> str | None:
    if screen.step_id == "enabled_agents":
        return AGENT_VALUE_MAP.get(value)
    if screen.step_id == "controller":
        enabled = _enabled_agents(state.form)
        index = int(value) - 1
        if 0 <= index < len(enabled):
            return enabled[index]
    return None



def _checked_for_row(state: InitPromptState, screen: InitPromptScreen, value: str) -> bool:
    if screen.selection_mode != "multi":
        return False
    provider = _provider_for_option(state, screen, value)
    return bool(provider and state.form.providers.get(provider, False))



def _build_selector_row(
    state: InitPromptState,
    screen: InitPromptScreen,
    *,
    value: str,
    label: str,
    pointed_value: str,
) -> InitSelectorRow:
    provider = _provider_for_option(state, screen, value)
    checked = _checked_for_row(state, screen, value)
    is_pointed = value == pointed_value
    is_default = value == screen.default_value
    lang = _lang(state.form.ui_language)
    prefix = "❯ " if is_pointed else "  "
    marker = ""
    marker_style = ""
    if screen.selection_mode == "multi":
        marker = "●" if checked else "○"
        if checked and provider in PROVIDER_THEME:
            marker_style = f"fg:{PROVIDER_THEME[provider]} bold"
        else:
            marker_style = "fg:#64748B"
    description = screen.descriptions.get(value, "")
    if is_pointed:
        color = PROVIDER_THEME.get(provider, "#7DD3FC")
        return InitSelectorRow(
            value=value,
            prefix=prefix,
            marker=marker,
            marker_style=marker_style,
            label=label,
            label_style=f"fg:{color} bold",
            description=description,
            description_style="fg:#64748B italic",
            is_pointed=True,
            is_default=is_default,
            checked=checked,
            provider=provider,
        )
    if is_default and screen.selection_mode == "single":
        return InitSelectorRow(
            value=value,
            prefix=prefix,
            marker=marker,
            marker_style=marker_style,
            label=label,
            label_style="fg:#F8FAFC bold",
            description=description,
            description_style="fg:#64748B italic",
            meta=_msg(lang, "default_tag"),
            meta_style="fg:#64748B",
            is_default=True,
            checked=checked,
            provider=provider,
        )
    return InitSelectorRow(
        value=value,
        prefix=prefix,
        marker=marker,
        marker_style=marker_style,
        label=label,
        label_style="fg:#CBD5E1",
        description=description,
        description_style="fg:#64748B italic",
        checked=checked,
        provider=provider,
    )



def _build_selector_rows(
    state: InitPromptState,
    screen: InitPromptScreen,
    *,
    pointed_value: str,
    allow_back: bool,
) -> list[InitSelectorRow]:
    lang = _lang(state.form.ui_language)
    allow_aux_back = allow_back and screen.step_id != 'review'
    rows = [
        _build_selector_row(state, screen, value=value, label=label, pointed_value=pointed_value)
        for value, label in screen.options
    ]
    if screen.selection_mode == "multi":
        rows.append(
            InitSelectorRow(
                value="c",
                prefix="❯ " if pointed_value == "c" else "  ",
                marker="",
                marker_style="",
                label=_msg(lang, "continue"),
                label_style="fg:#7DD3FC bold" if pointed_value == "c" else "fg:#CBD5E1",
                is_pointed=pointed_value == "c",
            )
        )
    if allow_aux_back:
        rows.append(
            InitSelectorRow(
                value="b",
                prefix="❯ " if pointed_value == "b" else "  ",
                marker="",
                marker_style="",
                label=_msg(lang, "back"),
                label_style="fg:#7DD3FC bold" if pointed_value == "b" else "fg:#CBD5E1",
                is_pointed=pointed_value == "b",
            )
        )
    rows.append(
        InitSelectorRow(
            value="q",
            prefix="❯ " if pointed_value == "q" else "  ",
            marker="",
            marker_style="",
            label=_msg(lang, "quit"),
            label_style="fg:#7DD3FC bold" if pointed_value == "q" else "fg:#CBD5E1",
            is_pointed=pointed_value == "q",
        )
    )
    return rows



def _render_interactive_header(
    state: InitPromptState,
    step_id: str,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> InitPromptScreen:
    screen = _resolve_screen(state, step_id)
    lang = _lang(state.form.ui_language)
    if clear_screen:
        console_obj.clear()
    width = _screen_width(console_obj)
    for line in build_init_banner(width):
        style = "bold #7DD3FC" if line != BANNER_SUBTITLE else "dim"
        console_obj.print(Text(line, style=style))
    console_obj.print()
    console_obj.print(Text(_progress_heading(screen, lang), style="bold"))
    console_obj.print(Text(screen.hint, style="dim"))
    if step_id == "review":
        console_obj.print()
        _print_review_summary(console_obj, state.form, lang=lang)
    console_obj.print()
    return screen



def _parse_multi_choice(choice: str, valid_choices: list[str]) -> list[str]:
    values = []
    seen: set[str] = set()
    for part in choice.split(","):
        item = part.strip()
        if not item:
            continue
        if item not in valid_choices:
            raise ValueError(item)
        if item not in seen:
            seen.add(item)
            values.append(item)
    if not values:
        raise ValueError("empty")
    return values



def _select_with_prompt_toolkit(
    state: InitPromptState,
    screen: InitPromptScreen,
    *,
    allow_back: bool,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    _render_interactive_header(state, screen.step_id, console_obj=console_obj, clear_screen=clear_screen)

    option_values = [value for value, _label in screen.options]
    values = [row.value for row in _build_selector_rows(state, screen, pointed_value=screen.default_value, allow_back=allow_back)]
    pointed_index = values.index(screen.default_value) if screen.default_value in values else 0
    live_footer = _msg(_lang(state.form.ui_language), _live_footer_key(screen))
    selected_multi = set(_enabled_agent_values(state.form)) if screen.selection_mode == "multi" else set()

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _toggle(value: str) -> None:
        if value not in option_values:
            return
        if value in selected_multi:
            if len(selected_multi) > 1:
                selected_multi.remove(value)
        else:
            selected_multi.add(value)
        _set_enabled_agents(state.form, [AGENT_VALUE_MAP[item] for item in option_values if item in selected_multi])

    def _tokens():
        rows = _build_selector_rows(state, screen, pointed_value=_current_value(), allow_back=allow_back)
        fragments: list[tuple[str, str]] = []
        for row in rows:
            fragments.append(("", row.prefix))
            if row.marker:
                fragments.append((row.marker_style, f"{row.marker} "))
            fragments.append((row.label_style, row.label))
            if row.meta:
                fragments.append((row.meta_style, row.meta))
            fragments.append(("", "\n"))
            if row.description:
                fragments.append(("", "    "))
                fragments.append((row.description_style, row.description))
                fragments.append(("", "\n"))
        fragments.append(("fg:#64748B", f"\n{live_footer}"))
        return fragments

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    if screen.selection_mode == "multi":
        @bindings.add(" ", eager=True)
        def _space(event) -> None:
            current = _current_value()
            if current in option_values:
                _toggle(current)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        current = _current_value()
        if current == "b":
            event.app.exit(result="b")
            return
        if current == "q":
            event.app.exit(result="q")
            return
        if screen.selection_mode == "multi":
            if current == "c":
                ordered = [value for value in option_values if value in selected_multi]
                event.app.exit(result=",".join(ordered))
                return
            if current in option_values:
                _toggle(current)
                return
        event.app.exit(result=current)

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

    if screen.selection_mode == "multi":
        @bindings.add("c", eager=True)
        def _continue(event) -> None:
            ordered = [value for value in option_values if value in selected_multi]
            event.app.exit(result=",".join(ordered))

    if allow_back and screen.step_id != 'review':
        @bindings.add("b", eager=True)
        def _back(event) -> None:
            event.app.exit(result="b")

    for key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        @bindings.add(key, eager=True)
        def _pick(event, key_value=key) -> None:
            if key_value not in values:
                return
            nonlocal pointed_index
            pointed_index = values.index(key_value)
            if screen.selection_mode == "multi" and key_value in option_values:
                _toggle(key_value)
            elif screen.selection_mode == "single":
                event.app.exit(result=key_value)

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



def _ask_choice(
    state: InitPromptState,
    step_id: str,
    *,
    input_fn,
    console_obj: Console,
    clear_screen: bool,
    allow_back: bool,
    selector_fn: SelectFn | None = None,
) -> str:
    screen = _resolve_screen(state, step_id)
    if selector_fn is not None:
        return selector_fn(state, screen, allow_back=allow_back, console_obj=console_obj, clear_screen=clear_screen)

    if input_fn is _prompt_input and sys.stdin.isatty():
        try:
            return _select_with_prompt_toolkit(
                state,
                screen,
                allow_back=allow_back,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
        except Exception:
            pass

    if clear_screen:
        console_obj.clear()
    console_obj.print(render_init_prompt_screen(state, step_id=step_id), end="")
    valid_choices = [value for value, _label in screen.options]
    if allow_back and screen.step_id != 'review':
        valid_choices.append("b")
    valid_choices.append("q")
    if screen.selection_mode == "multi" and input_fn is _prompt_input:
        default = ",".join(_enabled_agent_values(state.form)) or screen.default_value
        return _prompt_multi_input("Select", default=default)
    return input_fn("Select", choices=valid_choices, default=screen.default_value)



def _persist_language_choice(config: Config, language: str) -> None:
    config.ui_language = _lang(language)
    config.save()



def run_init_prompt(
    config: Config,
    *,
    input_fn=_prompt_input,
    console_obj: Console | None = None,
    clear_screen: bool = True,
    selector_fn: SelectFn | None = None,
) -> None:
    console_obj = console_obj or Console()
    state = InitPromptState.from_config(config)
    history: list[str] = []
    step_id = "language"

    while True:
        choice = _ask_choice(
            state,
            step_id,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            allow_back=bool(history),
            selector_fn=selector_fn,
        )
        if choice == "q":
            raise click.Abort()
        if choice == "b":
            if history:
                step_id = history.pop()
            continue

        previous = step_id
        if step_id == "language":
            state.form.ui_language = "en-US" if choice == "1" else "zh-CN"
            _persist_language_choice(config, state.form.ui_language)
            step_id = "enabled_agents"
        elif step_id == "enabled_agents":
            selected_values = _parse_multi_choice(choice, [value for value, _label in _resolve_screen(state, step_id).options])
            enabled_agents = [AGENT_VALUE_MAP[value] for value in selected_values]
            _set_enabled_agents(state.form, enabled_agents)
            step_id = "controller"
        elif step_id == "controller":
            enabled = _enabled_agents(state.form)
            index = max(0, min(len(enabled) - 1, int(choice) - 1))
            state.form.controller = enabled[index]
            step_id = "runtime"
        elif step_id == "runtime":
            state.form.runtime_mode = "tmux" if choice == "1" else "direct"
            step_id = "entry"
        elif step_id == "entry":
            state.form.entry_surface = "guided" if choice == "1" else "command"
            step_id = "collaboration"
        elif step_id == "collaboration":
            state.form.auto_collaboration_enabled = choice == "1"
            step_id = "review"
        else:
            if choice == "1":
                apply_setup_form(config, state.form)
                return
            if choice == "2":
                step_id = history.pop() if history else "collaboration"
                continue
            temp_config = config.model_copy(deep=True)
            apply_setup_form(temp_config, state.form)
            from ai_collab.config_prompt import run_config_menu_prompt
            saved = run_config_menu_prompt(temp_config, console_obj=console_obj, clear_screen=clear_screen)
            if saved:
                return
            continue

        history.append(previous)
