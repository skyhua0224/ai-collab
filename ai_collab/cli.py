"""
Main CLI entry point for ai-collab.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import is_dataclass, replace
from datetime import datetime, timezone
import importlib
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional, Tuple
from uuid import uuid4

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from ai_collab import __version__ as AI_COLLAB_VERSION

from ai_collab.core.config import Config, resolve_collaboration_role_leads
from ai_collab.core.detector import CollaborationDetector
from ai_collab.core.environment import (
    detect_os_name,
    detect_provider_status,
    resolve_executable,
    resolve_subprocess_command,
)
from ai_collab.core.selector import ModelSelector
from ai_collab.core.run_state import RunStateStore
from ai_collab.core.updates import check_pypi_update, run_self_update
from ai_collab.core.tmux_workspace import (
    TmuxWorkspaceError,
    attach_session,
    capture_pane_text,
    create_controller_workspace,
    create_inline_controller_workspace,
    create_tmux_workspace,
    pane_logs_dir,
    paste_pane_text,
    send_pane_text,
    spawn_subagent_pane,
    type_pane_text,
    wait_for_pane_quiet,
)
from ai_collab.core.workflow import WorkflowManager, _run_command_live_pipe
from ai_collab.core.workflow_v2 import (
    WorkflowBlueprintV2,
    WorkflowStageV2,
    builtin_session_presets,
    resolve_session_preset,
    resolve_workflow_blueprint,
)
from ai_collab.terminal_ui import build_live_output_prefix, render_tmux_block

console = Console(force_terminal=True, legacy_windows=False)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\].*?\x1b\\")
COMPLETION_MARKER_LINE_RE = re.compile(r"(?mi)^\s*===\s*(?:SUBAGENT_COMPLETE|TASK_COMPLETE)\s*===\s*$")
LIVE_PREFIX_RE = re.compile(r"^\s*│\s[^│]+\s│\s?")
_LAST_DIRECT_RUNTIME_ERROR = ""


I18N = {
    "en-US": {
        "wizard_title": "🧭 Init Wizard",
        "wizard_desc": "Set up collaboration by project categories and default models.",
        "language_prompt": "Language / 语言",
        "os_label": "Detected OS",
        "provider_scan": "Local provider status",
        "provider_auto_enabled": "Automatically enabled available agents: {names}",
        "provider_enable": "Enable provider {name}?",
        "provider_missing_note": "command not found",
        "fallback_enabled": "No provider selected, enabled fallback: {name}",
        "step_enable_agents": "Select enabled agents",
        "step_allocation": "Work allocation strategy",
        "use_default_allocation": "Use default role/stage allocation?",
        "step_custom_assignment": "Custom role/stage model mapping",
        "assignment_use_default": "{index}. {name}: default {agent} - {profile}. Keep default?",
        "assignment_select_agent": "Select agent for {name}",
        "assignment_select_model": "Select model/profile for {name}",
        "step_controller": "Controller agent",
        "step_demo": "Demo test",
        "run_demo_prompt": "Run demo test now?",
        "demo_task_prompt": "Demo task prompt",
        "demo_task_default": "Build a tiny to-do feature with discover/define/develop/deliver and report each phase.",
        "demo_ready": "Demo tmux session ready: {session}",
        "demo_attach": "Attach with: tmux attach -t {session}",
        "demo_paste": "Paste this prompt in controller pane:",
        "demo_attach_now": "Attach to tmux now?",
        "controller_prompt": "Choose current controller",
        "category_title": "Project category switches",
        "category_enable": "Enable category {name}?",
        "category_reco": "recommended: {provider}",
        "category_none": "No category selected, fallback to: {name}",
        "role_title": "Three brains, one workflow",
        "role_provider": "Provider",
        "role_responsibility": "Responsibility",
        "role_codex": "Implementation depth (code, architecture, logic)",
        "role_gemini": "Ecosystem breadth (research, alternatives, security signals)",
        "role_claude": "Synthesis (orchestration, consensus, final review)",
        "phase_title": "Double-Diamond phase routing",
        "phase_column": "Phase",
        "phase_routing": "Routing",
        "phase_discover": "Discover",
        "phase_define": "Define",
        "phase_develop": "Develop",
        "phase_deliver": "Deliver",
        "route_discover": "Gemini lead, Codex parallel technical checks, Claude synthesis",
        "route_define": "Claude lead with Codex/Gemini consensus",
        "route_develop": "Codex lead implementation, Claude quality guard",
        "route_deliver": "Claude adversarial review, Codex fixes, Gemini cross-check",
        "persona_title": "Persona category switches",
        "persona_enable": "Enable persona category {name}?",
        "gate_note": "Consensus quality gate set to {threshold}%",
        "model_title": "Default model strategy per enabled provider",
        "wizard_done": "Wizard complete.",
        "status_title": "AI Collaboration System Status",
        "status_lang": "UI Language",
        "status_os": "Detected OS",
        "yes_label": "Yes",
        "no_label": "No",
        "install_label": "Auto-install dependency",
        "text_label": "Use text mode",
        "abort_label": "Abort",
        "missing_tui_dep": "TUI dependency 'questionary' is missing. Choose action",
        "install_failed": "Install failed. Choose fallback",
        "model_enable": "Enable model option {option} for {provider}?",
        "model_fallback": "No model option selected for {provider}, fallback to: {option}",
        "model_default_prompt": "Choose default model option for {provider}",
        "provider_codex": "Codex",
        "provider_claude": "Claude",
        "provider_gemini": "Gemini",
        "codex_low_desc": "Simple tasks (formatting, small edits)",
        "codex_medium_desc": "Feature implementation and refactoring",
        "codex_high_desc": "Complex architecture and multi-module logic",
        "gemini_auto_desc": "let Gemini CLI choose model",
        "recommended_mark": "(recommended)",
        "models_by_agent_title": "Agent model catalog",
        "model_source": "Source: {source}",
        "source_slash": "provider /model",
        "source_fallback": "local config fallback",
        "agent_pick_prompt": "Select agent to configure model defaults",
        "agent_pick_done": "Finish model configuration",
        "yes_value": "yes",
        "no_value": "no",
    },
    "zh-CN": {
        "wizard_title": "🧭 初始化向导",
        "wizard_desc": "基于项目分类配置协作策略与默认模型。",
        "language_prompt": "语言 / Language",
        "os_label": "检测到的系统",
        "provider_scan": "本地 Provider 状态",
        "provider_auto_enabled": "已自动启用可用 Agent：{names}",
        "provider_enable": "是否启用 {name}？",
        "provider_missing_note": "命令不可用",
        "fallback_enabled": "未选择任何 Provider，已启用兜底：{name}",
        "step_enable_agents": "选择启用的 Agent",
        "step_allocation": "工作分配策略",
        "use_default_allocation": "是否使用默认职责/阶段分配？",
        "step_custom_assignment": "自定义职责/阶段模型映射",
        "assignment_use_default": "{index}. {name}: 默认 {agent} - {profile}，是否保留默认？",
        "assignment_select_agent": "为 {name} 选择 Agent",
        "assignment_select_model": "为 {name} 选择模型/档位",
        "step_controller": "主控 Agent",
        "step_demo": "Demo 测试",
        "run_demo_prompt": "是否立即进行 demo 测试？",
        "demo_task_prompt": "Demo 任务提示词",
        "demo_task_default": "实现一个极小的待办功能，按 discover/define/develop/deliver 输出每阶段结果。",
        "demo_ready": "Demo tmux 会话已创建：{session}",
        "demo_attach": "使用以下命令进入：tmux attach -t {session}",
        "demo_paste": "将以下提示词粘贴到主控窗口：",
        "demo_attach_now": "是否现在进入 tmux 会话？",
        "controller_prompt": "选择当前主控",
        "category_title": "项目分类开关",
        "category_enable": "是否启用分类 {name}？",
        "category_reco": "推荐主控：{provider}",
        "category_none": "未选择分类，已兜底启用：{name}",
        "role_title": "Three brains, one workflow（固定分工）",
        "role_provider": "Provider",
        "role_responsibility": "职责",
        "role_codex": "实现深度（代码、架构、逻辑落地）",
        "role_gemini": "生态广度（调研、备选方案、安全信号）",
        "role_claude": "综合收敛（编排、共识门、最终审查）",
        "phase_title": "Double-Diamond 阶段路由",
        "phase_column": "阶段",
        "phase_routing": "默认路由",
        "phase_discover": "Discover",
        "phase_define": "Define",
        "phase_develop": "Develop",
        "phase_deliver": "Deliver",
        "route_discover": "Gemini 主导调研，Codex 并行技术校验，Claude 汇总",
        "route_define": "Claude 主导定义，Codex/Gemini 共识校验",
        "route_develop": "Codex 主导开发实现，Claude 质量守门",
        "route_deliver": "Claude 对抗式审查，Codex 修复，Gemini 交叉复核",
        "persona_title": "Persona 分类开关",
        "persona_enable": "是否启用 Persona 分类 {name}？",
        "gate_note": "共识质量门阈值已设为 {threshold}%",
        "model_title": "已启用 Provider 的默认模型策略",
        "wizard_done": "向导完成。",
        "status_title": "AI 协作系统状态",
        "status_lang": "界面语言",
        "status_os": "系统类型",
        "yes_label": "是",
        "no_label": "否",
        "install_label": "自动安装依赖",
        "text_label": "使用文本模式",
        "abort_label": "退出",
        "missing_tui_dep": "缺少 TUI 依赖 questionary，选择处理方式",
        "install_failed": "安装失败，选择兜底方式",
        "model_enable": "是否启用 {provider} 的模型选项 {option}？",
        "model_fallback": "{provider} 未选择任何模型选项，已兜底使用：{option}",
        "model_default_prompt": "为 {provider} 选择默认模型选项",
        "provider_codex": "Codex",
        "provider_claude": "Claude",
        "provider_gemini": "Gemini",
        "codex_low_desc": "简单任务（格式整理、小幅修改）",
        "codex_medium_desc": "功能实现与重构",
        "codex_high_desc": "复杂架构与多模块逻辑",
        "gemini_auto_desc": "让 Gemini CLI 自动选择模型",
        "recommended_mark": "（推荐）",
        "models_by_agent_title": "Agent 模型目录",
        "model_source": "来源：{source}",
        "source_slash": "provider /model",
        "source_fallback": "本地配置兜底",
        "agent_pick_prompt": "选择要配置模型默认值的 Agent",
        "agent_pick_done": "完成模型配置",
        "yes_value": "是",
        "no_value": "否",
    },
}

PROVIDER_THEME = {
    "codex": {"hex": "#06B6D4", "rich": "bright_cyan", "icon_nerd": "●", "icon_plain": "●"},
    "claude": {"hex": "#FB923C", "rich": "bright_yellow", "icon_nerd": "●", "icon_plain": "●"},
    "gemini": {"hex": "#22C55E", "rich": "bright_green", "icon_nerd": "●", "icon_plain": "●"},
}

PROVIDER_BRAND = {
    "codex": "OpenAI",
    "claude": "Anthropic",
    "gemini": "Google",
}

PROJECT_CATEGORY_PRESETS = {
    "docs-text": {
        "en": "Docs / Blog",
        "zh": "文档 / 博客",
        "recommended_controller": "claude",
    },
    "superapp-fullstack": {
        "en": "Superapp Fullstack",
        "zh": "全栈项目（小程序/Web/Backend）",
        "recommended_controller": "codex",
    },
    "macos-swift": {
        "en": "macOS Swift Native",
        "zh": "macOS Swift 原生",
        "recommended_controller": "codex",
    },
    "mobile-native": {
        "en": "iOS / Android Native",
        "zh": "iOS / Android 原生",
        "recommended_controller": "codex",
    },
    "systems-tooling": {
        "en": "Systems / Tooling",
        "zh": "工具链项目（bash/python/node/rust）",
        "recommended_controller": "codex",
    },
    "game-dev": {
        "en": "Game Development",
        "zh": "游戏开发（Unity/UE/Ren'Py）",
        "recommended_controller": "gemini",
    },
}

PERSONA_CATEGORY_PRESETS = {
    "software_engineering": {"en": "Software Engineering", "zh": "软件工程"},
    "specialized_development": {"en": "Specialized Development", "zh": "专项开发"},
    "documentation_communication": {"en": "Docs & Communication", "zh": "文档与沟通"},
    "research_strategy": {"en": "Research & Strategy", "zh": "研究与策略"},
    "creative_design": {"en": "Creative & Design", "zh": "创意与设计"},
}

WORK_ALLOCATION_ITEMS = [
    {"key": "code_patterns", "en": "code patterns", "zh": "code patterns", "agent": "codex", "profile": "high"},
    {
        "key": "ecosystem_research",
        "en": "ecosystem breadth",
        "zh": "ecosystem breadth",
        "agent": "gemini",
        "profile": "auto",
    },
    {"key": "synthesis", "en": "final synthesis", "zh": "final synthesis", "agent": "claude", "profile": "default"},
    {"key": "discover", "en": "discover phase", "zh": "discover 阶段", "agent": "gemini", "profile": "auto"},
    {"key": "define", "en": "define phase", "zh": "define 阶段", "agent": "claude", "profile": "default"},
    {"key": "develop", "en": "develop phase", "zh": "develop 阶段", "agent": "codex", "profile": "high"},
    {"key": "deliver", "en": "deliver phase", "zh": "deliver 阶段", "agent": "claude", "profile": "default"},
]


def _msg(lang: str, key: str, **kwargs: str) -> str:
    table = I18N.get(lang, I18N["en-US"])
    raw = table.get(key, key)
    return raw.format(**kwargs)


def _system_prefers_zh_locale() -> bool:
    """Detect whether current terminal locale prefers Chinese UI."""
    locale_hint = " ".join(
        part
        for part in (
            os.environ.get("LC_ALL", ""),
            os.environ.get("LC_MESSAGES", ""),
            os.environ.get("LANG", ""),
        )
        if part
    ).lower()
    if locale_hint:
        zh_tokens = ("zh", "chinese", "hans", "hant")
        if any(token in locale_hint for token in zh_tokens):
            return True

    # macOS users often keep LANG=C.UTF-8 while system UI is Chinese.
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except Exception:  # noqa: BLE001
            return False
        output = (result.stdout or "").lower()
        return "zh" in output
    return False


def _resolve_runtime_language(*, cli_lang: Optional[str], config_lang: str) -> str:
    """Resolve runtime language from CLI override, config, and system locale."""
    if cli_lang in I18N:
        return str(cli_lang)

    prefer_system = os.environ.get("AI_COLLAB_PREFER_SYSTEM_LANG", "1").strip().lower()
    prefer_system_lang = prefer_system not in {"0", "false", "no", "off"}
    if prefer_system_lang and _system_prefers_zh_locale():
        return "zh-CN"

    if config_lang in I18N:
        return config_lang
    return "en-US"


def _provider_display_plain(name: str, *, include_brand: bool = False) -> str:
    theme = PROVIDER_THEME.get(name, {"icon_plain": "●"})
    label = _msg("en-US", f"provider_{name}")
    if include_brand and PROVIDER_BRAND.get(name):
        label = f"{label} ({PROVIDER_BRAND[name]})"
    return f"{_provider_icon(theme)} {label}"


def _provider_display_rich(name: str, *, include_brand: bool = False) -> str:
    theme = PROVIDER_THEME.get(name, {"rich": "cyan", "icon_plain": "●"})
    color = theme["rich"]
    icon = _provider_icon(theme)
    label = _msg("en-US", f"provider_{name}")
    if include_brand and PROVIDER_BRAND.get(name):
        label = f"{label} ({PROVIDER_BRAND[name]})"
    return f"[{color}]{icon} {label}[/{color}]"


def _provider_icon(theme: dict) -> str:
    icon_set = os.environ.get("AI_COLLAB_ICON_SET", "plain").strip().lower()
    if icon_set == "plain":
        return str(theme.get("icon_plain", "●"))
    # Default to Nerd Font icons; fallback to plain when output encoding is non-UTF.
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    if "utf" not in encoding:
        return str(theme.get("icon_plain", "●"))
    return str(theme.get("icon_nerd", theme.get("icon_plain", "●")))


def _format_os_name(os_name: str) -> str:
    mapping = {
        "macos": "macOS",
        "linux": "Linux",
        "windows": "Windows",
    }
    return mapping.get(os_name, os_name)


def _sanitize_model_key(model_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_")
    return slug or "model"


def _extract_model_ids(text: str) -> list[str]:
    if not text:
        return []
    patterns = [
        r"\b(claude-[a-z0-9][a-z0-9.\-]*)\b",
        r"\b(gemini-[a-z0-9][a-z0-9.\-]*)\b",
        r"\b(gpt-[a-z0-9][a-z0-9.\-]*)\b",
        r"\b((?:sonnet|opus|haiku)-[a-z0-9][a-z0-9.\-]*)\b",
        r"\b(o[0-9][a-z0-9.\-]*)\b",
        r"--model\s+([a-z0-9][a-z0-9.\-]*)",
        r"\bmodel:\s*([a-z0-9][a-z0-9.\-]*)\b",
    ]
    found: list[str] = []
    for pattern in patterns:
        for item in re.findall(pattern, text.lower()):
            model_id = item.strip()
            if model_id and model_id not in found:
                found.append(model_id)
    return found


def _quick_health_check(provider: str, *, timeout_sec: int = 3) -> tuple[bool, str]:
    """
    Quick availability check for a provider command without invoking the CLI.
    Returns (success: bool, error_message: str).
    """
    from ai_collab.core.config import Config
    config = Config.load()
    provider_config = config.providers.get(provider)
    if not provider_config:
        return False, "Provider not configured"

    executable = resolve_executable(provider_config.cli)
    if not executable:
        return False, f"Executable not found: {provider_config.cli}"

    if provider not in {"claude", "gemini", "codex"}:
        return False, f"Unknown provider: {provider}"
    if not os.access(executable, os.X_OK):
        return False, f"Command is not executable: {executable}"
    return True, ""


def _discover_provider_models(provider: str, provider_config, *, timeout_sec: int = 3) -> list[str]:
    """
    Best-effort model discovery from provider '/model' command.
    Falls back silently when unsupported, unavailable, or timed out.
    """
    executable = resolve_executable(provider_config.cli)
    if not executable:
        return []

    cmd: list[str]
    if provider == "claude":
        cmd = [executable, "-p", "/model", "--output-format", "text", "--permission-mode", "default"]
    elif provider == "gemini":
        cmd = [executable, "-p", "/model", "-o", "text", "--approval-mode", "default"]
    elif provider == "codex":
        cmd = [executable, "exec", "--sandbox", "read-only", "/model"]
    else:
        return []

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    discovered = _extract_model_ids(output)

    # Keep provider-relevant ids and de-duplicate.
    if provider == "claude":
        discovered = [x for x in discovered if x.startswith("claude-") or x.startswith(("sonnet-", "opus-", "haiku-"))]
    elif provider == "gemini":
        discovered = [x for x in discovered if x.startswith("gemini-")]
    elif provider == "codex":
        discovered = [x for x in discovered if x.startswith(("gpt-", "o"))]

    uniq: list[str] = []
    for item in discovered:
        if item not in uniq:
            uniq.append(item)
    return uniq


def _questionary_style(questionary_module, provider: Optional[str] = None):
    base = [
        ("qmark", "fg:#94A3B8 bold"),
        ("question", "fg:#E5E7EB bold"),
        ("answer", "fg:#A7F3D0 bold"),
        ("pointer", "fg:#60A5FA bold"),
        ("highlighted", "fg:#60A5FA"),
    ]
    if provider and provider in PROVIDER_THEME:
        color = PROVIDER_THEME[provider]["hex"]
        base = [
            ("qmark", "fg:#94A3B8 bold"),
            ("question", f"fg:{color} bold"),
            ("answer", f"fg:{color} bold"),
            ("pointer", f"fg:{color} bold"),
            ("highlighted", f"fg:{color}"),
        ]
    return questionary_module.Style(base)


def _questionary_available() -> bool:
    try:
        import questionary  # noqa: F401
    except Exception:
        return False
    return True


def _install_questionary() -> bool:
    """Install questionary dependency using current Python runtime."""
    console.print("[yellow]Installing missing dependency: questionary...[/yellow]")
    cmd = [sys.executable, "-m", "pip", "install", "questionary>=2.0.1"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip().splitlines()
        tail = stderr[-1] if stderr else "unknown pip error"
        console.print(f"[red]Failed to install questionary:[/red] {tail}")
        return False
    importlib.invalidate_caches()
    if _questionary_available():
        console.print("[green]questionary installed successfully.[/green]")
        return True
    console.print("[red]questionary install completed but import still fails.[/red]")
    return False


def _resolve_ui_mode(requested: str, *, auto_install_deps: bool, lang: str = "en-US") -> str:
    """Resolve init wizard UI mode."""
    if requested == "text":
        return "text"
    if _questionary_available():
        return "tui"

    if not sys.stdin.isatty():
        if auto_install_deps and _install_questionary():
            return "tui"
        if requested == "tui":
            console.print(
                "[yellow]TUI requested but questionary is missing in non-interactive terminal. "
                "Fallback to text mode.[/yellow]"
            )
        return "text"

    default_action = "install" if auto_install_deps else "text"
    action = _select_decision(
        _msg(lang, "missing_tui_dep"),
        [
            ("install", _msg(lang, "install_label")),
            ("text", _msg(lang, "text_label")),
            ("abort", _msg(lang, "abort_label")),
        ],
        questionary_module=None,
        default_value=default_action,
    )
    if action == "abort":
        raise click.Abort()
    if action == "install":
        if _install_questionary():
            return "tui"
        fallback = _select_decision(
            _msg(lang, "install_failed"),
            [
                ("text", _msg(lang, "text_label")),
                ("abort", _msg(lang, "abort_label")),
            ],
            questionary_module=None,
            default_value="text",
        )
        if fallback == "abort":
            raise click.Abort()
        return "text"
    return "text"


def _pick_ui_backend(ui_mode: str, *, auto_install_deps: bool, lang: str = "en-US"):
    """
    Return questionary module for tui backend, or None for text backend.
    """
    resolved = _resolve_ui_mode(ui_mode, auto_install_deps=auto_install_deps, lang=lang)
    if resolved == "tui":
        import questionary as _questionary

        return _questionary
    return None


def _run_init_setup_tui(config_obj: Config) -> None:
    """Launch the formal setup TUI used by the real init flow."""
    from ai_collab.tui.setup import run_setup_tui

    run_setup_tui(config_obj)


def _run_init_setup_raw(config_obj: Config) -> None:
    """Launch the non-framework raw terminal setup flow."""
    from ai_collab.tui.setup_raw import run_setup_raw

    run_setup_raw(config_obj)


def _run_init_setup_prompt(config_obj: Config) -> None:
    """Launch the thin prompt-style bootstrap flow."""
    from ai_collab.init_prompt import run_init_prompt

    run_init_prompt(config_obj)


def _select_decision(
    prompt: str,
    options: list[tuple[str, str]],
    *,
    questionary_module,
    default_value: Optional[str] = None,
    provider: Optional[str] = None,
):
    """Choose one option from list[(value, label)] with tui/text UI."""
    if questionary_module:
        choice = questionary_module.select(
            prompt,
            choices=[questionary_module.Choice(title=label, value=value) for value, label in options],
            default=default_value,
            style=_questionary_style(questionary_module, provider=provider),
        ).ask()
        if choice is None:
            raise click.Abort()
        return choice

    keys = [value for value, _ in options]
    display = " / ".join([f"{value} ({label})" for value, label in options])
    default = default_value if default_value in keys else keys[0]
    return Prompt.ask(f"{prompt} [{display}]", choices=keys, default=default)


def _ask_yes_no(
    prompt: str,
    *,
    lang: str,
    questionary_module,
    default_yes: bool = True,
    provider: Optional[str] = None,
) -> bool:
    """Localized yes/no prompt for both TUI and text mode."""
    yes_value = _msg(lang, "yes_value")
    no_value = _msg(lang, "no_value")
    options = [
        (yes_value, _msg(lang, "yes_label")),
        (no_value, _msg(lang, "no_label")),
    ]
    if questionary_module:
        choices = [questionary_module.Choice(title=label, value=value) for value, label in options]
        selected = questionary_module.select(
            prompt,
            choices=choices,
            default=yes_value if default_yes else no_value,
            style=_questionary_style(questionary_module, provider=provider),
        ).ask()
        if selected is None:
            raise click.Abort()
        return selected == yes_value
    selected = Prompt.ask(
        prompt,
        choices=[yes_value, no_value],
        default=yes_value if default_yes else no_value,
    )
    return selected == yes_value


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(AI_COLLAB_VERSION, "-V", "--version")
@click.pass_context
def main(ctx: click.Context) -> None:
    """AI Collaboration System - Multi-AI orchestration and workflow management."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.load()


@main.command()
@click.argument("task", required=True)
@click.option("--provider", "-p", help="Current AI provider (claude/codex/gemini)")
@click.option("--output", "-o", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def detect(ctx: click.Context, task: str, provider: Optional[str], output: str) -> None:
    """Detect if a task needs multi-AI collaboration."""
    config = ctx.obj["config"]
    detector = CollaborationDetector(config)

    result = detector.detect(task, provider or config.current_controller)

    if output == "json":
        console.print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return

    if result.need_collaboration:
        console.print("\n[bold green]🤝 Collaboration Recommended[/bold green]")
        console.print(f"Trigger: {result.trigger}")
        console.print(f"Description: {result.description}")
        console.print(f"Primary: {result.primary}")
        console.print(f"Reviewers: {', '.join(result.reviewers)}")
        console.print(f"Workflow: {_result_workflow_label(result)}")
        if result.intent:
            console.print(f"Intent: {result.intent}")
        if result.project_categories:
            console.print(f"Project Categories: {', '.join(result.project_categories)}")
        if result.suggested_skills:
            console.print(f"Auto Skills: {', '.join(result.suggested_skills)}")
    else:
        console.print("\n[yellow]Single AI can handle this task[/yellow]")
        if result.intent:
            console.print(f"Intent: {result.intent}")
        if result.project_categories:
            console.print(f"Project Categories: {', '.join(result.project_categories)}")
        if result.suggested_skills:
            console.print(f"Suggested Skills: {', '.join(result.suggested_skills)}")


@main.command()
@click.argument("provider", required=True)
@click.argument("task", required=True)
@click.option("--complexity", "-c", type=click.Choice(["low", "medium", "high"]), help="Task complexity")
@click.option("--output", "-o", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def select(ctx: click.Context, provider: str, task: str, complexity: Optional[str], output: str) -> None:
    """Select the best model for a provider and task."""
    config = ctx.obj["config"]
    selector = ModelSelector(config)

    result = selector.select_model(provider, task, complexity or "default")

    if output == "json":
        output_data = {
            "provider": provider,
            "model": result.model,
            "cli": result.cli,
            "description": result.description,
            "thinking": result.thinking,
        }
        console.print(json.dumps(output_data, indent=2, ensure_ascii=False))
    else:
        console.print("\n[bold cyan]Model Selection[/bold cyan]")
        console.print(f"Provider: {provider}")
        console.print(f"Model: {result.model}")
        console.print(f"CLI: {result.cli}")
        console.print(f"Description: {result.description}")


@main.command()
@click.option("--workspace", type=click.Path(path_type=Path, file_okay=False, dir_okay=True))
@click.option("--controller", type=click.Choice(["codex", "claude", "gemini"]))
@click.option("--task", help="Prefill the task input box")
@click.option("--task-file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--skip-review", is_flag=True, help="Trust the generated plan and export immediately")
@click.option("--planner-mode", type=click.Choice(["mock"]), default="mock", show_default=True)
@click.option("--output-bundle", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--non-interactive", is_flag=True, help="Run the same flow without launching fullscreen TUI")
@click.pass_context
def ux_lab(
    ctx: click.Context,
    workspace: Optional[Path],
    controller: Optional[str],
    task: Optional[str],
    task_file: Optional[Path],
    skip_review: bool,
    planner_mode: str,
    output_bundle: Optional[Path],
    non_interactive: bool,
) -> None:
    """Launch the experimental fullscreen UX lab."""
    if non_interactive and not ((task and task.strip()) or task_file):
        raise click.UsageError("--non-interactive requires --task or --task-file")

    from ai_collab.ux_lab import launch_ux_lab

    config_obj = ctx.obj["config"]
    result = launch_ux_lab(
        config=config_obj,
        cwd=Path.cwd(),
        workspace=workspace,
        controller=controller,
        task=task,
        task_file=task_file,
        skip_review=skip_review,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
        non_interactive=non_interactive,
    )

    if result.status == "planned":
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("SX")
        table.add_column("Agent")
        table.add_column("ETA")
        table.add_column("Title")
        for item in result.plan:
            table.add_row(item.sx, item.agent, f"{item.eta_minutes}m", item.title)
        console.print(table)
        console.print(
            "Use `--skip-review` to export the bundle directly, or run `ai-collab ux-lab` for the fullscreen editor."
        )
        return

    if result.status == "sent" and result.bundle_path is not None:
        console.print(str(result.bundle_path))


@main.command()
@click.option("--workspace", type=click.Path(path_type=Path, file_okay=False, dir_okay=True))
@click.option("--controller", type=click.Choice(["codex", "claude", "gemini"]))
@click.option("--task", help="Prefill the task input box")
@click.option("--task-file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--skip-review", is_flag=True, help="Trust the generated plan and export immediately")
@click.option("--planner-mode", type=click.Choice(["live", "mock"]), default="live", show_default=True)
@click.option("--output-bundle", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--non-interactive", is_flag=True, help="Run the same flow without launching fullscreen TUI")
@click.pass_context
def ux_lab_v3(
    ctx: click.Context,
    workspace: Optional[Path],
    controller: Optional[str],
    task: Optional[str],
    task_file: Optional[Path],
    skip_review: bool,
    planner_mode: str,
    output_bundle: Optional[Path],
    non_interactive: bool,
) -> None:
    """Launch the experimental fullscreen UX lab V3."""
    if non_interactive and not ((task and task.strip()) or task_file):
        raise click.UsageError("--non-interactive requires --task or --task-file")

    from ai_collab.ux_lab_v3 import launch_ux_lab_v3

    config_obj = ctx.obj["config"]
    result = launch_ux_lab_v3(
        config=config_obj,
        cwd=Path.cwd(),
        workspace=workspace,
        controller=controller,
        task=task,
        task_file=task_file,
        skip_review=skip_review,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
        non_interactive=non_interactive,
    )

    if result.status == "error":
        raise click.ClickException(result.error_message or "ux-lab-v3 planning failed")

    if result.status == "planned":
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("SX")
        table.add_column("Agent")
        table.add_column("ETA")
        table.add_column("Title")
        for item in result.plan:
            table.add_row(item.sx, item.agent, f"{item.eta_minutes}m", item.title)
        console.print(table)
        console.print(
            "Use `--skip-review` to export the bundle directly, or run `ai-collab ux-lab-v3` for the fullscreen editor."
        )
        return

    if result.status == "sent" and result.bundle_path is not None:
        console.print(str(result.bundle_path))


@main.command()
@click.option("--workspace", type=click.Path(path_type=Path, file_okay=False, dir_okay=True))
@click.option("--controller", type=click.Choice(["codex", "claude", "gemini"]))
@click.option("--task", help="Prefill the task input box")
@click.option("--task-file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--skip-review", is_flag=True, help="Trust the generated plan and export immediately")
@click.option("--planner-mode", type=click.Choice(["live", "mock"]), default="live", show_default=True)
@click.option("--output-bundle", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--non-interactive", is_flag=True, help="Run the same flow without launching fullscreen TUI")
@click.pass_context
def launch(
    ctx: click.Context,
    workspace: Optional[Path],
    controller: Optional[str],
    task: Optional[str],
    task_file: Optional[Path],
    skip_review: bool,
    planner_mode: str,
    output_bundle: Optional[Path],
    non_interactive: bool,
) -> None:
    """Launch the thin terminal task-start flow."""
    config_obj = ctx.obj["config"]

    if non_interactive:
        if not ((task and task.strip()) or task_file):
            raise click.UsageError("--non-interactive requires --task or --task-file")

        from ai_collab.tui.launcher import run_launcher_tui

        result = run_launcher_tui(
            config=config_obj,
            cwd=Path.cwd(),
            workspace=workspace,
            controller=controller,
            task=task,
            task_file=task_file,
            skip_review=skip_review,
            planner_mode=planner_mode,
            output_bundle=output_bundle,
            non_interactive=True,
        )

        if result.status == "error":
            raise click.ClickException(result.error_message or "launcher planning failed")

        if result.status == "planned":
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("SX")
            table.add_column("Agent")
            table.add_column("ETA")
            table.add_column("Title")
            for item in result.plan:
                table.add_row(item.sx, item.agent, f"{item.eta_minutes}m", item.title)
            console.print(table)
            console.print(
                "Use `--skip-review` to export the bundle directly, or run `ai-collab launch` for the thin terminal flow."
            )
            return

        if result.status == "sent" and result.bundle_path is not None:
            console.print(str(result.bundle_path))
        return

    from ai_collab.launch_prompt import run_launch_prompt

    result = run_launch_prompt(
        config=config_obj,
        cwd=Path.cwd(),
        workspace=workspace,
        controller=controller,
        task=task,
        task_file=task_file,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
    )
    if result is not None and result.status == "error":
        raise click.ClickException(result.error_message or "launcher planning failed")


@main.command()
@click.pass_context
def settings(ctx: click.Context) -> None:
    """Open the thin settings/config experience."""
    from ai_collab.config_prompt import run_config_menu_prompt

    config_obj = ctx.obj["config"]
    if run_config_menu_prompt(config_obj):
        console.print("[green]✅ Settings saved[/green]")


@main.command()
@click.argument("action", type=click.Choice(["set", "get", "interactive"]), required=False, default="interactive")
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.pass_context
def config(ctx: click.Context, action: str, key: Optional[str], value: Optional[str]) -> None:
    """
    Configuration management.

    Examples:
        ai-collab config                                    # Interactive config
        ai-collab config set auto_orchestration true        # Enable auto orchestration
        ai-collab config set auto_orchestration false       # Disable auto orchestration
        ai-collab config get auto_orchestration             # Get current value
        ai-collab config set ui_language zh-CN              # Set UI language
        ai-collab config get ui_language                    # Get UI language
    """
    config_obj = ctx.obj["config"]

    if action == "set":
        if not key:
            console.print("[red]Error: key is required for 'set' action[/red]")
            console.print("Usage: ai-collab config set <key> <value>")
            return

        if not value:
            console.print("[red]Error: value is required for 'set' action[/red]")
            console.print("Usage: ai-collab config set <key> <value>")
            return

        # Handle special keys
        if key == "auto_orchestration":
            bool_value = value.lower() in ("true", "yes", "1", "on", "enabled")
            auto_cfg = _set_auto_orchestration(dict(config_obj.auto_collaboration or {}), bool_value)
            config_obj.auto_collaboration = auto_cfg
            config_obj.save()

            status = "enabled" if bool_value else "disabled"
            console.print(f"[green]✓ Auto-orchestration {status}[/green]")

            if bool_value:
                console.print("\n[cyan]Multi-AI orchestration will be automatically activated.[/cyan]")
                console.print("To disable: ai-collab config set auto_orchestration false")
            else:
                console.print("\n[cyan]Working in solo mode. Multi-AI orchestration disabled.[/cyan]")
                console.print("To enable: ai-collab config set auto_orchestration true")
        elif key == "ui_language":
            if value not in I18N:
                console.print(f"[yellow]Unsupported ui_language: {value}[/yellow]")
                console.print(f"Available ui_language: {', '.join(I18N.keys())}")
                return
            config_obj.ui_language = value
            config_obj.save()
            console.print(f"[green]✓ ui_language set to {value}[/green]")
        elif key == "current_controller":
            if value not in {"codex", "claude", "gemini"}:
                console.print(f"[yellow]Unsupported controller: {value}[/yellow]")
                return
            config_obj.current_controller = value
            config_obj.save()
            console.print(f"[green]✓ current_controller set to {value}[/green]")
        elif key == "entry_surface":
            if value not in {"guided", "command"}:
                console.print(f"[yellow]Unsupported entry_surface: {value}[/yellow]")
                return
            config_obj.entry_surface = value
            config_obj.save()
            console.print(f"[green]✓ entry_surface set to {value}[/green]")
        elif key == "runtime_mode":
            if value not in {"tmux", "direct"}:
                console.print(f"[yellow]Unsupported runtime_mode: {value}[/yellow]")
                return
            config_obj.runtime_mode = value
            config_obj.save()
            console.print(f"[green]✓ runtime_mode set to {value}[/green]")
        else:
            console.print(f"[yellow]Unknown config key: {key}[/yellow]")
            console.print("Available keys: auto_orchestration, ui_language, current_controller, entry_surface, runtime_mode")

    elif action == "get":
        if not key:
            console.print("[red]Error: key is required for 'get' action[/red]")
            console.print("Usage: ai-collab config get <key>")
            return

        if key == "auto_orchestration":
            auto_cfg = config_obj.auto_collaboration or {}
            enabled = _auto_orchestration_enabled(auto_cfg)
            console.print(f"auto_orchestration: {enabled}")
        elif key == "ui_language":
            console.print(f"ui_language: {config_obj.ui_language}")
        elif key == "current_controller":
            console.print(f"current_controller: {config_obj.current_controller}")
        elif key == "entry_surface":
            console.print(f"entry_surface: {getattr(config_obj, 'entry_surface', 'guided')}")
        elif key == "runtime_mode":
            console.print(f"runtime_mode: {getattr(config_obj, 'runtime_mode', 'tmux')}")
        else:
            console.print(f"[yellow]Unknown config key: {key}[/yellow]")
            console.print("Available keys: auto_orchestration, ui_language, current_controller, entry_surface, runtime_mode")

    else:  # interactive
        from ai_collab.config_prompt import run_config_menu_prompt

        if run_config_menu_prompt(config_obj):
            console.print("\n[green]✅ Configuration saved![/green]")


@main.command()
@click.option("--force", "-f", is_flag=True, help="Force reinitialize")
@click.option(
    "-i/-I",
    "--interactive/--non-interactive",
    default=True,
    show_default=False,
    help="Run provider/model setup wizard during init",
)
@click.option(
    "--ui-mode",
    "-u",
    type=click.Choice(["auto", "tui", "text", "raw"]),
    default="auto",
    show_default=True,
    help="Init interaction mode (auto/text use thin CLI bootstrap)",
)
@click.option(
    "-a/-A",
    "--auto-install-deps/--no-auto-install-deps",
    default=True,
    show_default=False,
    help="Automatically install missing wizard dependencies (for TUI)",
)
@click.pass_context
def init(
    ctx: click.Context,
    force: bool,
    interactive: bool,
    ui_mode: str,
    auto_install_deps: bool,
) -> None:
    """Initialize configuration files."""
    config_dir = Path.home() / ".ai-collab"
    config_file = config_dir / "config.json"

    if config_file.exists() and not force:
        console.print("[yellow]Configuration already exists. Use --force to reinitialize.[/yellow]")
        return

    config_obj = Config.initialize()

    if interactive:
        if not sys.stdin.isatty():
            console.print("[yellow]Non-interactive terminal detected, skipping init wizard.[/yellow]")
        else:
            if ui_mode in {"auto", "text"}:
                _run_init_setup_prompt(config_obj)
            elif ui_mode == "raw":
                _run_init_setup_raw(config_obj)
            else:
                _run_init_setup_tui(config_obj)
            config_obj.save()

    console.print(f"[green]✅ Configuration initialized at {config_dir}[/green]")


@main.command(name="list")
@click.pass_context
def list_workflows(ctx: click.Context) -> None:
    """List V2 session presets."""

    preset_table = Table(title="Session Presets")
    preset_table.add_column("Preset", style="cyan")
    preset_table.add_column("Blueprint", style="magenta")
    preset_table.add_column("Description", style="white")

    for key, preset in builtin_session_presets().items():
        preset_table.add_row(key, preset.workflow_key, preset.description)

    console.print(preset_table)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current configuration status."""
    config_obj = ctx.obj["config"]
    lang = _resolve_runtime_language(cli_lang=None, config_lang=config_obj.ui_language)
    os_name = detect_os_name()
    runtime = detect_provider_status(config_obj.providers)

    console.print(f"\n[bold]{_msg(lang, 'status_title')}[/bold]")
    console.print(f"{_msg(lang, 'status_lang')}: [cyan]{lang}[/cyan]")
    console.print(f"{_msg(lang, 'status_os')}: [cyan]{_format_os_name(os_name)}[/cyan]")
    console.print(f"Current Controller: [cyan]{config_obj.current_controller}[/cyan]")
    console.print(f"Delegation Strategy: [yellow]{config_obj.delegation_strategy}[/yellow]")
    console.print(
        f"Quality Gate: [{'green' if config_obj.quality_gate_enabled else 'red'}]"
        f"{'Enabled' if config_obj.quality_gate_enabled else 'Disabled'}[/]"
    )

    console.print("\n[bold]Providers:[/bold]")
    for name, provider in config_obj.providers.items():
        configured_icon = "✅" if provider.enabled else "❌"
        local_icon = "🟢" if runtime.get(name) and runtime[name].available else "🔴"
        local_cmd = runtime[name].executable if runtime.get(name) else ""
        version = runtime[name].version if runtime.get(name) else ""
        detected_model = runtime[name].detected_model if runtime.get(name) else ""
        suffix = f" | local={local_icon} {local_cmd}"
        if version:
            suffix += f" | {version}"
        if detected_model:
            suffix += f" | model={detected_model}"
        console.print(f"  {configured_icon} {name}: {provider.cli}{suffix}")


@main.group()
def resume() -> None:
    """Inspect and recover persisted orchestration runs."""


def _resume_pending_steps(state: dict[str, Any]) -> list[tuple[str, str, str]]:
    steps = state.get("steps", {})
    rows: list[tuple[str, str, str]] = []
    if not isinstance(steps, dict):
        return rows
    done_values = {"done", "complete", "completed", "accepted"}
    for step_id, details in steps.items():
        if not isinstance(details, dict):
            continue
        status = str(details.get("status", "")).strip().lower()
        if status in done_values:
            continue
        agent = str(details.get("agent", "")).strip()
        rows.append((str(step_id), agent, status or "pending"))
    rows.sort(key=lambda item: item[0])
    return rows


def _step_sort_key(step_id: str) -> tuple[int, int, str]:
    raw = str(step_id).strip()
    match = re.match(r"(?i)^s(\d+)$", raw)
    if match:
        return (0, int(match.group(1)), raw.upper())
    return (1, 0, raw.lower())


def _normalize_step_status_for_display(status: str) -> str:
    value = str(status or "").strip().lower()
    if value in {"done", "complete", "completed", "accepted"}:
        return "done"
    if value in {"running", "in_progress"}:
        return "running"
    if value in {"assigned"}:
        return "queued"
    if value in {"pending"}:
        return "pending"
    return value or "pending"


def _extract_step_phase_marker(item: dict[str, Any]) -> tuple[str, str]:
    phase = str(item.get("phase", "")).strip().lower()
    detail = str(item.get("phase_detail", "")).strip()
    if phase not in {"step_started", "step_completed"}:
        return ("", "")
    match = re.match(r"^\s*(S\d+)\s*:\s*([A-Za-z0-9_\-]+)\s*$", detail, flags=re.IGNORECASE)
    if not match:
        return ("", "")
    return (match.group(1).upper(), _normalize_step_status_for_display(match.group(2)))


def _summarize_run_reason(item: dict[str, Any]) -> str:
    agents = item.get("agents", {})
    agent_statuses: list[str] = []
    if isinstance(agents, dict):
        for details in agents.values():
            if not isinstance(details, dict):
                continue
            value = str(details.get("status", "")).strip().lower()
            if value:
                agent_statuses.append(value)
    priority = [
        ("timeout_hard", "hard-timeout"),
        ("waiting_timeout_soft", "soft-timeout"),
        ("pane_unavailable", "pane-missing"),
    ]
    for status in agent_statuses:
        if status.startswith("error"):
            return "agent-error"
    for key, label in priority:
        if key in agent_statuses:
            return label
    phase = str(item.get("phase", "")).strip().lower()
    return ""


def _format_steps_triad(item: dict[str, Any]) -> str:
    steps = item.get("steps", {})
    if not isinstance(steps, dict) or not steps:
        return "No steps"

    done_values = {"done", "complete", "completed", "accepted"}
    done_count = 0
    pending_ids: list[str] = []
    done_ids: list[str] = []
    status_by_step: dict[str, str] = {}
    for sid, details in steps.items():
        sid_text = str(sid).strip()
        if not sid_text:
            continue
        status = "pending"
        if isinstance(details, dict):
            status = str(details.get("status", "")).strip().lower() or "pending"
        status_by_step[sid_text] = status
        if status in done_values:
            done_count += 1
            done_ids.append(sid_text)
        else:
            pending_ids.append(sid_text)

    total = len(status_by_step)
    if total <= 0:
        return "No steps"

    marker_step, marker_status = _extract_step_phase_marker(item)
    current_step = marker_step
    current_status = marker_status

    if not current_step:
        if pending_ids:
            pending_ids.sort(key=_step_sort_key)
            current_step = pending_ids[0]
            current_status = _normalize_step_status_for_display(status_by_step.get(current_step, "pending"))
        else:
            done_ids.sort(key=_step_sort_key)
            current_step = done_ids[-1] if done_ids else ""
            current_status = "done" if current_step else ""

    if not current_status:
        current_status = _normalize_step_status_for_display(status_by_step.get(current_step, "pending"))

    progress = f"{done_count}/{total}"
    if current_step:
        summary = f"{current_step} {current_status} ({progress})"
    else:
        summary = f"{progress} done"

    reason = _summarize_run_reason(item)
    if reason and current_status != "done":
        summary = f"{summary} · {reason}"
    return summary


def _truncate_prompt_preview_for_table(text: str, *, max_chars: int = 20) -> str:
    compact = " ".join(str(text or "").split())
    if not compact:
        return "-"
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "…"


def _resolve_run_query(*, cwd: Path, query: str) -> str:
    """Resolve run query by full id, short id, or label (exact/prefix)."""
    needle = str(query).strip()
    if not needle:
        raise click.ClickException("run query cannot be empty")
    runs = RunStateStore.list_runs(cwd=cwd, limit=500)
    if not runs:
        raise click.ClickException("no run state found under .ai-collab/runs")

    def _pick(matches: list[str]) -> Optional[str]:
        if len(matches) == 1:
            return matches[0]
        return None

    full_exact = [str(item.get("run_id", "")) for item in runs if str(item.get("run_id", "")) == needle]
    found = _pick(full_exact)
    if found:
        return found

    short_exact = [str(item.get("run_id", "")) for item in runs if str(item.get("short_id", "")) == needle]
    found = _pick(short_exact)
    if found:
        return found

    label_exact = [str(item.get("run_id", "")) for item in runs if str(item.get("label", "")).strip() == needle]
    found = _pick(label_exact)
    if found:
        return found

    full_prefix = [str(item.get("run_id", "")) for item in runs if str(item.get("run_id", "")).startswith(needle)]
    found = _pick(full_prefix)
    if found:
        return found

    short_prefix = [str(item.get("run_id", "")) for item in runs if str(item.get("short_id", "")).startswith(needle)]
    found = _pick(short_prefix)
    if found:
        return found

    label_prefix = [
        str(item.get("run_id", ""))
        for item in runs
        if str(item.get("label", "")).strip() and str(item.get("label", "")).startswith(needle)
    ]
    found = _pick(label_prefix)
    if found:
        return found

    merged = list(dict.fromkeys(full_exact + short_exact + label_exact + full_prefix + short_prefix + label_prefix))
    if not merged:
        raise click.ClickException(f"run not found for query: {needle}")
    sample = ", ".join(merged[:5])
    raise click.ClickException(f"run query is ambiguous: {needle}. matches: {sample}")


def _humanize_age(iso_text: str) -> str:
    value = str(iso_text).strip()
    if not value:
        return "-"
    try:
        if value.endswith("Z"):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - parsed.astimezone(timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"
    hours = minutes // 60
    if hours < 24:
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"
    days = hours // 24
    if days < 30:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} ago"
    months = days // 30
    if months < 12:
        unit = "month" if months == 1 else "months"
        return f"{months} {unit} ago"
    years = months // 12
    unit = "year" if years == 1 else "years"
    return f"{years} {unit} ago"


def _tmux_pane_exists_in_session(*, session: str, pane_id: str) -> bool:
    target = str(pane_id).strip()
    if not target:
        return False
    result = subprocess.run(
        ["tmux", "list-panes", "-t", session, "-F", "#{pane_id}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    panes = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return target in panes


def _detect_tmux_session_name(*, preferred: Optional[str] = None) -> str:
    """Best-effort resolve current/attached tmux session name."""
    name = str(preferred or "").strip()
    if name:
        return name

    current = subprocess.run(
        ["tmux", "display-message", "-p", "#S"],
        capture_output=True,
        text=True,
        check=False,
    )
    if current.returncode == 0 and current.stdout.strip():
        return current.stdout.strip()

    sessions = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if sessions.returncode != 0:
        return ""
    attached: list[str] = []
    all_sessions: list[str] = []
    for line in sessions.stdout.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        candidate = parts[0].strip()
        if not candidate:
            continue
        all_sessions.append(candidate)
        if len(parts) > 1 and parts[1].strip() == "1":
            attached.append(candidate)
    return attached[0] if attached else (all_sessions[0] if all_sessions else "")


def _tmux_resolve_session_for_pane(*, pane_id: str) -> str:
    """Resolve session name for a pane id, if it still exists."""
    target = str(pane_id).strip()
    if not target:
        return ""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", target, "#{session_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _tmux_current_command_for_pane(*, pane_id: str) -> str:
    """Return current command for a pane, empty when unavailable."""
    target = str(pane_id).strip()
    if not target:
        return ""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", target, "#{pane_current_command}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip().lower()


def _resume_launch_command_for_agent(*, agent: str, runtime_session_id: str) -> tuple[str, bool]:
    """Build launch command and whether it restores previous runtime session."""
    name = str(agent).strip().lower() or "codex"
    runtime_id = str(runtime_session_id).strip()
    if not runtime_id:
        return name, False
    escaped = shlex.quote(runtime_id)
    if name == "codex":
        return f"codex resume {escaped}", True
    if name == "claude":
        return f"claude --resume {escaped}", True
    if name == "gemini":
        return f"gemini --resume {escaped}", True
    return name, False


def _launch_agent_in_pane_with_wait(
    *,
    pane_id: str,
    agent: str,
    runtime_session_id: str,
) -> tuple[str, bool, bool]:
    """
    Launch agent in pane with shell/agent readiness waits.

    Returns: (launch_command, runtime_session_restored, launch_ready)
    """
    normalized_agent = str(agent).strip().lower() or "codex"
    primary_cmd, primary_is_resume = _resume_launch_command_for_agent(
        agent=normalized_agent,
        runtime_session_id=runtime_session_id,
    )
    candidates: list[tuple[str, bool]] = [(primary_cmd, primary_is_resume)]
    if primary_is_resume:
        candidates.append((normalized_agent, False))

    for command, restored in candidates:
        shell_ready = _wait_for_shell_input_ready_in_pane(
            pane_id=pane_id,
            timeout_seconds=16.0,
        )
        if not shell_ready:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane_id, "C-c"],
                capture_output=True,
                text=True,
                check=False,
            )
            shell_ready = _wait_for_shell_input_ready_in_pane(
                pane_id=pane_id,
                timeout_seconds=8.0,
            )
        if not shell_ready:
            continue
        wait_for_pane_quiet(
            pane_id=pane_id,
            timeout_seconds=8.0,
            stable_checks=2,
            poll_interval=0.35,
        )
        send_pane_text(
            pane_id=pane_id,
            text=command,
            press_enter=True,
            delay_seconds=0.6,
        )
        ready = _wait_for_agent_ready(
            pane_id=pane_id,
            agent=normalized_agent,
            timeout_seconds=_resolve_agent_ready_timeout(normalized_agent),
        )
        if ready:
            return command, restored, True
    fallback_cmd = candidates[-1][0] if candidates else normalized_agent
    return fallback_cmd, False, False


def _agent_from_subagent_title(title: str) -> str:
    prefix = "ai-collab:subagent:"
    value = str(title).strip()
    if not value.startswith(prefix):
        return ""
    return value[len(prefix):].strip().lower()


def _safe_int(text: Any, default: int = 0) -> int:
    try:
        return int(str(text).strip())
    except Exception:  # noqa: BLE001
        return default


def _pane_looks_like_shell(*, pane_id: str) -> bool:
    cmd = _tmux_current_command_for_pane(pane_id=pane_id)
    return cmd in {"", "zsh", "bash", "sh", "fish", "pwsh", "powershell"}


def _wait_for_shell_input_ready_in_pane(*, pane_id: str, timeout_seconds: float = 20.0) -> bool:
    """Wait until shell process and shell input loop are both ready in pane."""
    shell_cmds = {"zsh", "bash", "sh", "fish", "pwsh", "powershell", "nu"}
    deadline = time.monotonic() + max(timeout_seconds, 1.0)

    # 1) Wait until pane current command is a known shell.
    while time.monotonic() < deadline:
        current = _tmux_current_command_for_pane(pane_id=pane_id)
        if current in shell_cmds:
            break
        time.sleep(0.25)
    else:
        return False

    try:
        wait_for_pane_quiet(
            pane_id=pane_id,
            timeout_seconds=4.0,
            stable_checks=2,
            poll_interval=0.3,
        )
    except Exception:  # noqa: BLE001
        pass

    # 2) Probe input loop: Enter should produce pane output change while still in shell.
    attempts = 0
    while attempts < 4 and time.monotonic() < deadline:
        attempts += 1
        try:
            before = capture_pane_text(pane_id=pane_id, start_line=-180)
        except subprocess.CalledProcessError:
            time.sleep(0.25)
            continue
        send_pane_text(pane_id=pane_id, text="", press_enter=True, delay_seconds=0.0)
        probe_deadline = min(deadline, time.monotonic() + 2.2)
        while time.monotonic() < probe_deadline:
            try:
                after = capture_pane_text(pane_id=pane_id, start_line=-180)
            except subprocess.CalledProcessError:
                time.sleep(0.2)
                continue
            current = _tmux_current_command_for_pane(pane_id=pane_id)
            if current in shell_cmds and after != before:
                try:
                    wait_for_pane_quiet(
                        pane_id=pane_id,
                        timeout_seconds=2.5,
                        stable_checks=2,
                        poll_interval=0.3,
                    )
                except Exception:  # noqa: BLE001
                    pass
                return True
            time.sleep(0.2)
    return False


def _pane_agent_appears_ready(*, pane_id: str, agent: str) -> bool:
    """Fast readiness probe used before deciding whether a relaunch is required."""
    normalized_agent = str(agent).strip().lower()
    if not normalized_agent:
        return False
    current = _tmux_current_command_for_pane(pane_id=pane_id)
    if current == normalized_agent:
        return True
    return _wait_for_agent_ready(
        pane_id=pane_id,
        agent=normalized_agent,
        timeout_seconds=1.6,
    )


def _extract_resume_ids_for_agent(*, text: str, agent: str) -> list[str]:
    """Extract runtime session ids from explicit agent resume commands."""
    normalized = _normalize_terminal_text_for_markers(text)
    name = str(agent).strip().lower()
    if not name:
        return []
    if name == "codex":
        pattern = re.compile(r"(?im)\bcodex\s+resume\s+([A-Za-z0-9][A-Za-z0-9._:-]{5,})")
    elif name == "claude":
        pattern = re.compile(r"(?im)\bclaude\s+--resume\s+([A-Za-z0-9][A-Za-z0-9._:-]{5,})")
    elif name == "gemini":
        pattern = re.compile(r"(?im)\bgemini\s+(?:--resume|resume)\s+([A-Za-z0-9][A-Za-z0-9._:-]{5,})")
    else:
        pattern = re.compile(
            rf"(?im)\b{re.escape(name)}\s+(?:--resume|resume)\s+([A-Za-z0-9][A-Za-z0-9._:-]{{5,}})"
        )
    tokens = [str(match).strip().strip(",.;") for match in pattern.findall(normalized)]
    return [token for token in tokens if _looks_like_runtime_session_id(token=token, agent=name)]


def _looks_like_runtime_session_id(*, token: str, agent: str) -> bool:
    """Validate extracted runtime id tokens to avoid placeholder/guide text false positives."""
    value = str(token).strip().strip(",.;")
    if not value:
        return False
    lowered = value.lower()
    blocked = {"id", "session", "runtime", "resume", "command", "conversation", "chat"}
    if lowered in blocked:
        return False
    name = str(agent).strip().lower()
    if name == "codex":
        # Codex resume id is UUID in current CLI behavior.
        return bool(
            re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                value,
            )
        )
    if len(value) < 8:
        return False
    return True


def _read_log_tail_text(*, path: Path, max_bytes: int = 600_000) -> str:
    """Read tail of a log file as utf-8 (best effort)."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return ""
            read_from = max(0, size - max(1, int(max_bytes)))
            handle.seek(read_from, os.SEEK_SET)
            return handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _resolve_runtime_session_id_for_agent(
    *,
    state: dict[str, Any],
    agent: str,
    pane_id: str,
    sessions: list[str],
    cwd: Path,
) -> str:
    """Best-effort runtime session id recovery from state/snapshot/live pane/logs."""
    name = str(agent).strip().lower()
    if not name:
        return ""

    # 1) state.json direct fields.
    if name == str((state.get("controller", {}) or {}).get("agent", "")).strip().lower():
        direct = str((state.get("controller", {}) or {}).get("runtime_session_id", "")).strip()
        if direct:
            return direct
    else:
        direct = str(((state.get("agents", {}) or {}).get(name, {}) or {}).get("runtime_session_id", "")).strip()
        if direct:
            return direct

    # 2) snapshot runtime_sessions cache.
    tmux_state = state.get("tmux", {}) if isinstance(state.get("tmux", {}), dict) else {}
    snapshot = tmux_state.get("layout_snapshot", {}) if isinstance(tmux_state, dict) else {}
    runtime_sessions = snapshot.get("runtime_sessions", {}) if isinstance(snapshot, dict) else {}
    if isinstance(runtime_sessions, dict):
        controller = runtime_sessions.get("controller", {}) if isinstance(runtime_sessions.get("controller"), dict) else {}
        if name == str(controller.get("agent", "")).strip().lower():
            cached = str(controller.get("runtime_session_id", "")).strip()
            if cached:
                return cached
        agents_raw = runtime_sessions.get("agents", [])
        if isinstance(agents_raw, list):
            for item in reversed(agents_raw):
                if not isinstance(item, dict):
                    continue
                if str(item.get("agent", "")).strip().lower() != name:
                    continue
                cached = str(item.get("runtime_session_id", "")).strip()
                if cached:
                    return cached

    # 3) current pane content.
    target_pane = str(pane_id).strip()
    if target_pane:
        try:
            shot = capture_pane_text(pane_id=target_pane, start_line=-320)
        except subprocess.CalledProcessError:
            shot = ""
        if shot:
            ids = _extract_resume_ids_for_agent(text=shot, agent=name)
            if ids:
                return ids[-1]
            generic = [
                token
                for token in _extract_runtime_session_ids(shot)
                if _looks_like_runtime_session_id(token=token, agent=name)
            ]
            if generic:
                return generic[-1]

    # 4) pane logs by session/pane and recent session logs.
    seen_logs: set[Path] = set()
    unique_sessions: list[str] = []
    for raw in sessions:
        sid = str(raw).strip()
        if sid and sid not in unique_sessions:
            unique_sessions.append(sid)
    safe_pane = target_pane.replace("%", "pane-")
    for sid in unique_sessions:
        log_dir = cwd / ".ai-collab" / "logs" / sid
        if not log_dir.exists():
            continue
        preferred = log_dir / f"{safe_pane}.log" if safe_pane else None
        candidates: list[Path] = []
        if preferred is not None and preferred.exists():
            candidates.append(preferred)
        candidates.extend(
            sorted(
                [p for p in log_dir.glob("pane-*.log") if p.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:12]
        )
        for log_file in candidates:
            if log_file in seen_logs:
                continue
            seen_logs.add(log_file)
            text = _read_log_tail_text(path=log_file)
            if not text:
                continue
            ids = _extract_resume_ids_for_agent(text=text, agent=name)
            if ids:
                return ids[-1]
            generic = [
                token
                for token in _extract_runtime_session_ids(text)
                if _looks_like_runtime_session_id(token=token, agent=name)
            ]
            if generic:
                return generic[-1]
    return ""


def _spawn_resume_controller_pane(*, session: str, cwd: Path) -> str:
    shell = os.environ.get("SHELL", "zsh")
    pane = subprocess.run(
        [
            "tmux",
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            session,
            "-n",
            "ai-collab-resume",
            "-c",
            str(cwd),
            shell,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if pane.returncode != 0 or not pane.stdout.strip():
        raise TmuxWorkspaceError((pane.stderr or "").strip() or "failed to create resume controller pane")
    return pane.stdout.strip()


def _enable_resume_pane_logging(*, session: str, cwd: Path, pane_id: str) -> None:
    """Enable tmux pipe-pane logging for resumed pane."""
    log_dir = pane_logs_dir(cwd=cwd, session=session)
    log_path = log_dir / f"{pane_id.replace('%', 'pane-')}.log"
    command = f"cat >> {shlex.quote(str(log_path))}"
    subprocess.run(
        ["tmux", "pipe-pane", "-o", "-t", pane_id, command],
        capture_output=True,
        text=True,
        check=False,
    )


def _restore_window_from_snapshot(
    *,
    window_target: str,
    cwd: Path,
    seed_pane_id: str,
    pane_specs: list[dict[str, Any]],
) -> dict[str, str]:
    """Best-effort restore one window's pane count/titles and return sub-agent pane map."""
    preferred: dict[str, str] = {}
    specs = [item for item in pane_specs if isinstance(item, dict)]
    if not specs:
        return preferred
    ordered_specs = sorted(specs, key=lambda item: (_safe_int(item.get("top")), _safe_int(item.get("left"))))

    seed_idx = 0
    for idx, item in enumerate(ordered_specs):
        if str(item.get("title", "")).strip() == "ai-collab:controller":
            seed_idx = idx
            break
    seed_spec = ordered_specs[seed_idx]

    subprocess.run(
        ["tmux", "select-pane", "-t", seed_pane_id, "-T", str(seed_spec.get("title", "")).strip() or ""],
        capture_output=True,
        text=True,
        check=False,
    )
    maybe_agent = _agent_from_subagent_title(str(seed_spec.get("title", "")))
    if maybe_agent:
        preferred.setdefault(maybe_agent, seed_pane_id)

    remaining = [item for i, item in enumerate(ordered_specs) if i != seed_idx]
    anchor_pane = seed_pane_id
    prev_spec = seed_spec
    for spec in remaining:
        split_dir = "-h"
        if _safe_int(spec.get("top")) > _safe_int(prev_spec.get("top")):
            split_dir = "-v"
        pane = subprocess.run(
            [
                "tmux",
                "split-window",
                "-d",
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                anchor_pane,
                split_dir,
                "-p",
                "50",
                "-c",
                str(cwd),
                os.environ.get("SHELL", "zsh"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if pane.returncode != 0 or not pane.stdout.strip():
            continue
        pane_id = pane.stdout.strip()
        title = str(spec.get("title", "")).strip()
        if title:
            subprocess.run(
                ["tmux", "select-pane", "-t", pane_id, "-T", title],
                capture_output=True,
                text=True,
                check=False,
            )
        _enable_resume_pane_logging(session=window_target.split(":", 1)[0], cwd=cwd, pane_id=pane_id)
        maybe_agent = _agent_from_subagent_title(title)
        if maybe_agent:
            preferred.setdefault(maybe_agent, pane_id)
        anchor_pane = pane_id
        prev_spec = spec
    return preferred


def _restore_tmux_layout_from_snapshot(
    *,
    session: str,
    cwd: Path,
    controller_pane: str,
    snapshot: dict[str, Any],
) -> dict[str, str]:
    """Best-effort rebuild tmux windows/panes from saved snapshot and return sub-agent pane map."""
    preferred: dict[str, str] = {}
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return preferred
    windows_raw = snapshot.get("windows", [])
    windows = [item for item in windows_raw if isinstance(item, dict)]
    if not windows:
        return preferred

    controller_window = None
    for item in windows:
        panes = item.get("panes", [])
        if any(str(p.get("title", "")).strip() == "ai-collab:controller" for p in panes if isinstance(p, dict)):
            controller_window = item
            break
    if controller_window is None:
        controller_window = next((item for item in windows if str(item.get("active", "")).strip() == "1"), windows[0])

    controller_name = str(controller_window.get("name", "")).strip()
    if controller_name:
        subprocess.run(
            ["tmux", "rename-window", "-t", f"{session}:0", controller_name],
            capture_output=True,
            text=True,
            check=False,
        )
    preferred.update(
        _restore_window_from_snapshot(
            window_target=f"{session}:0",
            cwd=cwd,
            seed_pane_id=controller_pane,
            pane_specs=controller_window.get("panes", []),
        )
    )

    others = [item for item in windows if item is not controller_window]
    for item in others:
        window_name = str(item.get("name", "")).strip() or "ai-collab-resume"
        pane = subprocess.run(
            [
                "tmux",
                "new-window",
                "-d",
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                session,
                "-n",
                window_name,
                "-c",
                str(cwd),
                os.environ.get("SHELL", "zsh"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if pane.returncode != 0 or not pane.stdout.strip():
            continue
        seed_pane = pane.stdout.strip()
        _enable_resume_pane_logging(session=session, cwd=cwd, pane_id=seed_pane)
        window_target = f"{session}:{window_name}"
        preferred.update(
            _restore_window_from_snapshot(
                window_target=window_target,
                cwd=cwd,
                seed_pane_id=seed_pane,
                pane_specs=item.get("panes", []),
            )
        )
    return preferred


def _build_resume_subagent_standby_prompt(*, lang: str, controller_agent: str, run_id: str) -> str:
    if lang == "zh-CN":
        return (
            f"你已恢复为子Agent（run_id={run_id}）。当前进入待命状态。"
            f"不要主动开始新任务，等待主控 {controller_agent} 的下一条明确指令。"
            "收到主控指令后，先复述目标与边界，再执行。"
        )
    return (
        f"You are resumed as sub-agent (run_id={run_id}). Enter standby now. "
        f"Do not start new work until controller {controller_agent} gives explicit next instruction. "
        "When instruction arrives, restate scope/boundaries first, then execute."
    )


def _build_resume_controller_summary_prompt(
    *,
    lang: str,
    run_id: str,
    workspace: Path,
    previous_session: str,
    recovered_session: str,
    phase: str,
    phase_detail: str,
    controller_runtime_session_id: str,
    pending_lines: str,
    restored_subagents: list[dict[str, Any]],
) -> str:
    subs = []
    for item in restored_subagents:
        agent = str(item.get("agent", "")).strip()
        pane = str(item.get("pane_id", "")).strip()
        status = str(item.get("status", "")).strip() or "unknown"
        resumed = "yes" if bool(item.get("runtime_session_restored")) else "no"
        subs.append(f"- {agent} | pane={pane} | status={status} | runtime_restored={resumed}")
    sub_lines = "\n".join(subs) if subs else "- none"
    if lang == "zh-CN":
        return (
            f"恢复运行：{run_id}\n"
            f"工作区：{workspace}\n"
            f"旧 tmux session：{previous_session or '-'}\n"
            f"当前 tmux session：{recovered_session}\n"
            f"主控 runtime session id：{controller_runtime_session_id or '-'}\n"
            f"当前阶段：{phase or '-'} ({phase_detail or '-'})\n"
            "已恢复子控：\n"
            f"{sub_lines}\n"
            "未完成步骤：\n"
            f"{pending_lines}\n"
            "下一步请先做：\n"
            "1) 向用户简要汇报：当前做到哪里、哪些子控已就绪。\n"
            "2) 问用户：继续原计划 / 调整计划 / 提出新想法。\n"
            "3) 若继续原计划，优先处理 pending steps，并继续用 tmux-watch 动态超时监控。"
        )
    return (
        f"Resume run: {run_id}\n"
        f"Workspace: {workspace}\n"
        f"Previous tmux session: {previous_session or '-'}\n"
        f"Recovered tmux session: {recovered_session}\n"
        f"Controller runtime session id: {controller_runtime_session_id or '-'}\n"
        f"Current phase: {phase or '-'} ({phase_detail or '-'})\n"
        "Restored sub-agents:\n"
        f"{sub_lines}\n"
        "Pending steps:\n"
        f"{pending_lines}\n"
        "Do this first:\n"
        "1) Brief user on current progress and ready sub-agents.\n"
        "2) Ask user: continue original plan / adjust plan / provide new idea.\n"
        "3) If continuing, execute pending steps first and keep using tmux-watch with dynamic timeout."
    )


def _spawn_resume_subagent_pane(*, session: str, cwd: Path, controller_pane: str, agent: str) -> str:
    """Spawn one sub-agent pane under controller pane in standard ai-collab layout."""
    prefix = "ai-collab:subagent:"
    shell = os.environ.get("SHELL", "zsh")
    panes_output = subprocess.run(
        ["tmux", "list-panes", "-t", controller_pane, "-F", "#{pane_id}|#{pane_title}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if panes_output.returncode != 0:
        raise TmuxWorkspaceError((panes_output.stderr or "").strip() or "failed to list panes for resume")
    rows = [line for line in panes_output.stdout.splitlines() if line.strip()]
    sub_panes: list[str] = []
    for line in rows:
        pane_id, pane_title = (line.split("|", 1) + [""])[:2]
        if pane_title.startswith(prefix):
            sub_panes.append(pane_id.strip())
    if len(sub_panes) >= 3:
        raise TmuxWorkspaceError("Maximum 3 sub-agent panes reached during resume")

    if not sub_panes:
        target_pane = controller_pane
        split_args = ["-v", "-p", "50"]
    else:
        target_pane = sub_panes[-1]
        split_args = ["-h", "-p", "50"]

    pane = subprocess.run(
        [
            "tmux",
            "split-window",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            target_pane,
            *split_args,
            "-c",
            str(cwd),
            shell,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if pane.returncode != 0 or not pane.stdout.strip():
        raise TmuxWorkspaceError((pane.stderr or "").strip() or "failed to create resume sub-agent pane")
    pane_id = pane.stdout.strip()
    subprocess.run(
        ["tmux", "select-pane", "-t", pane_id, "-T", f"{prefix}{agent}"],
        capture_output=True,
        text=True,
        check=False,
    )
    _enable_resume_pane_logging(session=session, cwd=cwd, pane_id=pane_id)
    return pane_id


def _restore_subagent_panes_on_resume(
    *,
    store: RunStateStore,
    state: dict[str, Any],
    session: str,
    controller_agent: str,
    controller_pane: str,
    cwd: Path,
    preferred_agent_panes: Optional[dict[str, str]] = None,
    runtime_lookup_sessions: Optional[list[str]] = None,
    inject_standby_prompt: bool = False,
    lang: str = "en-US",
) -> list[dict[str, Any]]:
    """Restore sub-agent panes and resume runtime sessions where possible."""
    restored: list[dict[str, Any]] = []
    agents_state = state.get("agents", {})
    if not isinstance(agents_state, dict):
        return restored
    done_values = {"done", "complete", "completed", "accepted"}
    for agent in sorted([str(name).strip() for name in agents_state.keys() if str(name).strip()]):
        if agent == controller_agent:
            continue
        details = agents_state.get(agent, {})
        if not isinstance(details, dict):
            continue
        runtime_session_id = str(details.get("runtime_session_id", "")).strip()
        if not runtime_session_id:
            runtime_session_id = _resolve_runtime_session_id_for_agent(
                state=state,
                agent=agent,
                pane_id=str(details.get("pane_id", "")).strip(),
                sessions=runtime_lookup_sessions or [session],
                cwd=cwd,
            )
            if runtime_session_id:
                store.set_agent_runtime_session_id(agent=agent, runtime_session_id=runtime_session_id)
        status = str(details.get("status", "")).strip().lower()
        if status in done_values and not runtime_session_id:
            continue

        saved_pane = str(details.get("pane_id", "")).strip()
        preferred_pane = ""
        if isinstance(preferred_agent_panes, dict):
            preferred_pane = str(preferred_agent_panes.get(agent, "")).strip()
        if preferred_pane:
            saved_pane = preferred_pane
        pane_exists = bool(saved_pane and _tmux_pane_exists_in_session(session=session, pane_id=saved_pane))
        created_new_pane = False
        pane_id = saved_pane
        if not pane_exists:
            pane_id = _spawn_resume_subagent_pane(
                session=session,
                cwd=cwd,
                controller_pane=controller_pane,
                agent=agent,
            )
            created_new_pane = True
            tickets_raw = details.get("step_tickets", [])
            tickets = tickets_raw if isinstance(tickets_raw, list) else []
            store.bind_agent(agent=agent, pane_id=pane_id, step_tickets=tickets)

        launch_command = ""
        runtime_session_restored = False
        launch_ready = False
        if created_new_pane:
            launch_command, runtime_session_restored, launch_ready = _launch_agent_in_pane_with_wait(
                pane_id=pane_id,
                agent=agent,
                runtime_session_id=runtime_session_id,
            )
        elif _pane_agent_appears_ready(pane_id=pane_id, agent=agent):
            launch_ready = True
        else:
            launch_command, runtime_session_restored, launch_ready = _launch_agent_in_pane_with_wait(
                pane_id=pane_id,
                agent=agent,
                runtime_session_id=runtime_session_id,
            )

        standby_prompt_injected = False
        if inject_standby_prompt and launch_ready:
            standby_prompt = _build_resume_subagent_standby_prompt(
                lang=lang,
                controller_agent=controller_agent,
                run_id=store.run_id,
            )
            standby_prompt_injected = _inject_prompt_to_pane(
                pane_id=pane_id,
                text=standby_prompt,
                agent=agent,
            )

        restored.append(
            {
                "agent": agent,
                "pane_id": pane_id,
                "status": status or "unknown",
                "created_new_pane": created_new_pane,
                "runtime_session_id": runtime_session_id,
                "runtime_session_restored": runtime_session_restored,
                "launch_command": launch_command,
                "launch_ready": launch_ready,
                "standby_prompt_injected": standby_prompt_injected,
            }
        )
    return restored


@resume.command(name="list")
@click.option("--cwd", "-w", default=".", show_default=True, help="Workspace root containing .ai-collab/runs")
@click.option("--limit", "-n", type=int, default=20, show_default=True, help="Max runs to show")
@click.option("--detail", "-d", is_flag=True, help="Show wide columns (session/controller/entry prompt)")
@click.option(
    "--columns",
    "-c",
    help=(
        "Comma-separated columns. Available: id,name,status,sx,phase,mode,pending,created,updated,active,"
        "session,controller,prompt,label,run_id"
        ",workspace,cwd"
    ),
)
@click.option("--json-output", "-j", is_flag=True, help="Print result as JSON")
def resume_list(cwd: str, limit: int, detail: bool, columns: Optional[str], json_output: bool) -> None:
    """List resumable orchestration runs."""
    root = Path(cwd).expanduser().resolve()
    runs = RunStateStore.list_runs(cwd=root, limit=max(1, int(limit)))
    if runs:
        _refresh_runs_controller_progress_from_live_panes(cwd=root, runs=runs, source="resume_list")
        runs = RunStateStore.list_runs(cwd=root, limit=max(1, int(limit)))
    if json_output:
        click.echo(json.dumps(runs, ensure_ascii=False, indent=2))
        return
    if not runs:
        console.print("[yellow]No run state found under .ai-collab/runs[/yellow]")
        return
    column_spec = {
        "id": ("id", {"style": "cyan", "no_wrap": True, "min_width": 8, "max_width": 10}),
        "run_id": ("run_id", {"style": "cyan", "no_wrap": True, "min_width": 18, "max_width": 30}),
        "name": ("name", {"style": "white", "no_wrap": False, "overflow": "fold", "min_width": 10}),
        "label": ("label", {"style": "white", "no_wrap": False, "overflow": "fold", "min_width": 10}),
        "status": ("status", {"style": "green", "no_wrap": True, "min_width": 7, "max_width": 10}),
        "sx": ("steps", {"style": "blue", "no_wrap": True}),
        "steps": ("steps", {"style": "blue", "no_wrap": True}),
        "phase": ("phase", {"style": "blue", "no_wrap": False, "overflow": "fold", "min_width": 10, "max_width": 24}),
        "mode": ("mode", {"style": "magenta", "no_wrap": True, "min_width": 4, "max_width": 7}),
        "pending": ("pending", {"style": "yellow", "justify": "right", "no_wrap": True, "min_width": 2, "max_width": 7}),
        "created": ("created", {"style": "yellow", "no_wrap": True, "min_width": 9, "max_width": 15}),
        "updated": ("updated", {"style": "yellow", "no_wrap": True, "min_width": 9, "max_width": 15}),
        "active": ("active", {"style": "yellow", "no_wrap": True, "min_width": 9, "max_width": 15}),
        "session": ("session", {"style": "magenta", "no_wrap": False, "overflow": "fold", "max_width": 18}),
        "controller": ("controller", {"style": "white", "no_wrap": False, "overflow": "fold", "max_width": 16}),
        "prompt": ("entry_prompt", {"style": "white", "no_wrap": True, "overflow": "ellipsis", "min_width": 10, "max_width": 20}),
        "workspace": ("workspace", {"style": "white", "no_wrap": False, "overflow": "fold", "min_width": 14, "max_width": 30}),
        "cwd": ("workspace", {"style": "white", "no_wrap": False, "overflow": "fold", "min_width": 14, "max_width": 30}),
    }
    default_columns = ["id", "name", "status", "steps", "mode", "prompt", "created", "updated"]
    detail_additions = ["active", "session", "workspace", "controller", "prompt", "phase"]
    selected_columns = default_columns + detail_additions if detail else list(default_columns)
    if columns:
        requested = [part.strip().lower() for part in str(columns).split(",") if part.strip()]
        unknown = [part for part in requested if part not in column_spec]
        if unknown:
            raise click.ClickException(f"unknown columns: {', '.join(unknown)}")
        selected_columns = requested

    table = Table(title=f"Resumable Runs ({len(runs)})")
    for key in selected_columns:
        header, options = column_spec[key]
        table.add_column(header, **options)
    for item in runs:
        controller = f"{item.get('controller_agent', '')}:{item.get('controller_pane', '')}".strip(":") or "-"
        values = {
            "id": str(item.get("short_id", "")),
            "run_id": str(item.get("run_id", "")),
            "name": str(item.get("name", "")).strip() or str(item.get("short_id", "")).strip() or "-",
            "label": str(item.get("label", "")).strip() or "-",
            "status": str(item.get("status", "")),
            "sx": _format_steps_triad(item),
            "steps": _format_steps_triad(item),
            "phase": str(item.get("phase", "")),
            "mode": str(item.get("mode", "")),
            "pending": str(item.get("pending_count", 0)),
            "created": _humanize_age(str(item.get("created_at", ""))),
            "updated": _humanize_age(str(item.get("updated_at", ""))),
            "active": _humanize_age(str(item.get("last_active_at", ""))),
            "session": str(item.get("session", "")),
            "controller": controller,
            "prompt": _truncate_prompt_preview_for_table(str(item.get("entry_prompt_preview", "")).strip()),
            "workspace": str(item.get("workspace", "")).strip() or "-",
        }
        table.add_row(*[values[key] for key in selected_columns])
    console.print(table)


@resume.command(name="prune")
@click.option("--cwd", "-w", default=".", show_default=True, help="Workspace root containing .ai-collab/runs")
@click.option(
    "--keep-run",
    "-k",
    multiple=True,
    help="Keep one run by query (run_id / short_id / label). Can be used multiple times.",
)
@click.option("--keep-session", "-s", help="Keep all runs under this tmux session name")
@click.option(
    "--keep-current-session/--no-keep-current-session",
    default=True,
    show_default=True,
    help="Keep all runs for current attached tmux session",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--json-output", "-j", is_flag=True, help="Print prune result as JSON")
def resume_prune(
    cwd: str,
    keep_run: tuple[str, ...],
    keep_session: Optional[str],
    keep_current_session: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Delete old run records while keeping current/selected run(s)."""
    root = Path(cwd).expanduser().resolve()
    runs_root = root / ".ai-collab" / "runs"
    if not runs_root.exists():
        console.print("[yellow]No run state found under .ai-collab/runs[/yellow]")
        return

    runs = RunStateStore.list_runs(cwd=root, limit=100000)
    if not runs:
        console.print("[yellow]No run state found under .ai-collab/runs[/yellow]")
        return

    keep_ids: set[str] = set()
    for query in keep_run:
        keep_ids.add(_resolve_run_query(cwd=root, query=query))

    session_name = ""
    if keep_current_session:
        session_name = _detect_tmux_session_name(preferred=keep_session)
    elif keep_session:
        session_name = str(keep_session).strip()
    if session_name:
        for item in runs:
            if str(item.get("session", "")).strip() == session_name:
                run_id = str(item.get("run_id", "")).strip()
                if run_id:
                    keep_ids.add(run_id)

    kept_latest_fallback = False
    if not keep_ids and not keep_run and keep_current_session:
        fallback = str(runs[0].get("run_id", "")).strip()
        if fallback:
            keep_ids.add(fallback)
            kept_latest_fallback = True

    if not keep_ids:
        raise click.ClickException(
            "no keep target resolved; pass --keep-run or --keep-session "
            "(or run inside tmux and keep-current-session)"
        )

    run_dirs = sorted([item.name for item in runs_root.iterdir() if item.is_dir()])
    to_delete = [name for name in run_dirs if name not in keep_ids]

    if to_delete and not yes:
        if not sys.stdin.isatty():
            raise click.ClickException("refusing prune in non-interactive mode without --yes")
        confirmed = Confirm.ask(f"Delete {len(to_delete)} run(s)?", default=False)
        if not confirmed:
            console.print("[yellow]prune cancelled[/yellow]")
            return

    deleted: list[str] = []
    for run_id in to_delete:
        run_dir = runs_root / run_id
        if run_dir.exists() and run_dir.is_dir():
            shutil.rmtree(run_dir)
            deleted.append(run_id)

    payload = {
        "kept": sorted(keep_ids),
        "deleted": deleted,
        "kept_count": len(keep_ids),
        "deleted_count": len(deleted),
        "session_kept": session_name,
        "fallback_keep_latest": kept_latest_fallback,
    }
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(
            f"[green]prune done[/green] kept={payload['kept_count']} deleted={payload['deleted_count']} "
            f"session={session_name or '-'}"
        )
        if kept_latest_fallback:
            console.print("[yellow]No active tmux session detected; kept latest run as fallback.[/yellow]")


@resume.command(name="show")
@click.argument("run_id", required=True)
@click.option("--cwd", "-w", default=".", show_default=True, help="Workspace root containing .ai-collab/runs")
@click.option("--json-output", "-j", is_flag=True, help="Print result as JSON")
def resume_show(run_id: str, cwd: str, json_output: bool) -> None:
    """Show one run state detail."""
    root = Path(cwd).expanduser().resolve()
    resolved_run_id = _resolve_run_query(cwd=root, query=run_id)
    store = RunStateStore.load(cwd=root, run_id=resolved_run_id)
    if store is None:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise SystemExit(2)
    _sync_controller_progress_from_live_pane(run_store=store, source="resume_show")
    state = store.snapshot()
    pending = _resume_pending_steps(state)
    if json_output:
        payload = {"state": state, "pending_steps": pending}
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    controller = state.get("controller", {})
    tmux_state = state.get("tmux", {})
    layout_history = tmux_state.get("layout_history", []) if isinstance(tmux_state, dict) else []
    console.print(f"[bold]run_id[/bold]: {state.get('run_id', resolved_run_id)}")
    console.print(f"[bold]short_id[/bold]: {RunStateStore.short_id(str(state.get('run_id', resolved_run_id)))}")
    console.print(f"[bold]label[/bold]: {state.get('label', '')}")
    console.print(f"[bold]mode[/bold]: {state.get('mode', '')}")
    console.print(f"[bold]workspace[/bold]: {state.get('workspace', '')}")
    console.print(f"[bold]session[/bold]: {state.get('session', '')}")
    console.print(f"[bold]controller[/bold]: {controller.get('agent', '')} @ {controller.get('pane_id', '')}")
    console.print(f"[bold]controller_runtime_session_id[/bold]: {controller.get('runtime_session_id', '')}")
    console.print(f"[bold]phase[/bold]: {state.get('phase', '')} ({state.get('phase_detail', '')})")
    console.print(f"[bold]entry_prompt[/bold]: {state.get('entry_prompt', '')}")
    console.print(f"[bold]layout_updates[/bold]: {len(layout_history)}")
    console.print(f"[bold]updated_at[/bold]: {state.get('updated_at', '')}")
    if pending:
        console.print("[bold yellow]pending steps:[/bold yellow]")
        for sid, agent, status in pending:
            console.print(f"- {sid} | {agent or '-'} | {status}")
    else:
        console.print("[green]No pending steps in state snapshot.[/green]")


@resume.command(name="rename")
@click.argument("run_id", required=True)
@click.argument("name", required=True)
@click.option("--cwd", "-w", default=".", show_default=True, help="Workspace root containing .ai-collab/runs")
def resume_rename(run_id: str, name: str, cwd: str) -> None:
    """Assign a readable label for one run."""
    root = Path(cwd).expanduser().resolve()
    resolved_run_id = _resolve_run_query(cwd=root, query=run_id)
    store = RunStateStore.load(cwd=root, run_id=resolved_run_id)
    if store is None:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise SystemExit(2)
    label = str(name).strip()
    if not label:
        console.print("[red]Name cannot be empty.[/red]")
        raise SystemExit(2)
    store.set_label(label=label)
    store.append_event(
        event_type="run_renamed",
        source="resume",
        payload={"label": label},
    )
    console.print(f"[green]renamed[/green] {resolved_run_id} -> {label}")


@resume.command(name="recover")
@click.argument("run_id", required=True)
@click.option("--cwd", "-w", default=".", show_default=True, help="Workspace root containing .ai-collab/runs")
@click.option("--session", "-s", help="Override tmux session name used for recovery")
@click.option("-a/-A", "--attach/--no-attach", default=True, show_default=False, help="Attach tmux session after recovery")
@click.option("--json-output", "-j", is_flag=True, help="Print recovery result as JSON")
def resume_recover(run_id: str, cwd: str, session: Optional[str], attach: bool, json_output: bool) -> None:
    """Recover controller session from persisted run state."""
    if shutil.which("tmux") is None:
        console.print("[red]tmux not found in PATH[/red]")
        raise SystemExit(2)
    root = Path(cwd).expanduser().resolve()
    resolved_run_id = _resolve_run_query(cwd=root, query=run_id)
    store = RunStateStore.load(cwd=root, run_id=resolved_run_id)
    if store is None:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise SystemExit(2)

    state = store.snapshot()
    controller = state.get("controller", {})
    controller_agent = str(controller.get("agent", "")).strip() or "codex"
    controller_runtime_session_id = str(controller.get("runtime_session_id", "")).strip()
    lang = "zh-CN" if _system_prefers_zh_locale() else "en-US"
    previous_session = str(state.get("session", "")).strip()
    controller_pane = str(controller.get("pane_id", "")).strip()
    explicit_session = str(session or "").strip()
    pane_session = _tmux_resolve_session_for_pane(pane_id=controller_pane) if controller_pane else ""
    auto_session = _detect_tmux_session_name()
    runtime_lookup_sessions = [explicit_session, pane_session, previous_session, auto_session]
    if not controller_runtime_session_id:
        controller_runtime_session_id = _resolve_runtime_session_id_for_agent(
            state=state,
            agent=controller_agent,
            pane_id=controller_pane,
            sessions=runtime_lookup_sessions,
            cwd=root,
        )
        if controller_runtime_session_id:
            store.set_controller_runtime_session_id(runtime_session_id=controller_runtime_session_id)
    target_session = str(
        explicit_session or pane_session or previous_session or auto_session or f"ai-collab-{resolved_run_id[:8]}"
    ).strip()
    if not target_session:
        target_session = f"ai-collab-{resolved_run_id[:8]}"

    created_new_session = False
    created_new_pane = False
    launch_command = ""
    runtime_session_restored = False
    launch_ready = False
    preferred_agent_panes: dict[str, str] = {}
    if not _tmux_session_exists(target_session):
        controller_pane = create_controller_workspace(
            session=target_session,
            cwd=root,
            controller=controller_agent,
            reset=False,
            autorun=False,
        )
        created_new_session = True
        created_new_pane = True
        tmux_state = state.get("tmux", {}) if isinstance(state.get("tmux", {}), dict) else {}
        snapshot = tmux_state.get("layout_snapshot", {}) if isinstance(tmux_state, dict) else {}
        preferred_agent_panes = _restore_tmux_layout_from_snapshot(
            session=target_session,
            cwd=root,
            controller_pane=controller_pane,
            snapshot=snapshot if isinstance(snapshot, dict) else {},
        )
    elif not _tmux_pane_exists_in_session(session=target_session, pane_id=controller_pane):
        controller_pane = _spawn_resume_controller_pane(
            session=target_session,
            cwd=root,
        )
        created_new_pane = True

    if created_new_pane:
        launch_command, runtime_session_restored, launch_ready = _launch_agent_in_pane_with_wait(
            pane_id=controller_pane,
            agent=controller_agent,
            runtime_session_id=controller_runtime_session_id,
        )
    elif _pane_agent_appears_ready(pane_id=controller_pane, agent=controller_agent):
        launch_ready = True
    else:
        launch_command, runtime_session_restored, launch_ready = _launch_agent_in_pane_with_wait(
            pane_id=controller_pane,
            agent=controller_agent,
            runtime_session_id=controller_runtime_session_id,
        )

    restored_subagents = _restore_subagent_panes_on_resume(
        store=store,
        state=state,
        session=target_session,
        controller_agent=controller_agent,
        controller_pane=controller_pane,
        cwd=root,
        preferred_agent_panes=preferred_agent_panes,
        runtime_lookup_sessions=runtime_lookup_sessions + [target_session],
        inject_standby_prompt=created_new_session,
        lang=lang,
    )

    pending = _resume_pending_steps(state)
    pending_lines = "\n".join([f"- {sid} | {agent or '-'} | {status}" for sid, agent, status in pending]) or "- none"
    prompt = _build_resume_controller_summary_prompt(
        lang=lang,
        run_id=resolved_run_id,
        workspace=root,
        previous_session=previous_session,
        recovered_session=target_session,
        phase=str(state.get("phase", "")).strip(),
        phase_detail=str(state.get("phase_detail", "")).strip(),
        controller_runtime_session_id=controller_runtime_session_id,
        pending_lines=pending_lines,
        restored_subagents=restored_subagents,
    )
    briefing = _write_briefing_file(
        cwd=root,
        role="controller-resume",
        agent=controller_agent,
        text=prompt,
    )
    dispatch = _build_prompt_dispatch_message(
        lang=lang,
        path=briefing,
        role="controller-resume",
        agent=controller_agent,
    )
    injected = False
    if launch_ready:
        injected = _inject_prompt_to_pane(
            pane_id=controller_pane,
            text=dispatch,
            agent=controller_agent,
        )

    store.rebind_controller(session=target_session, pane_id=controller_pane)
    store.set_mode(mode="tmux")
    store.set_workspace(workspace=str(root))
    store.set_entry_prompt(text=dispatch)
    store.set_agent_status(agent=controller_agent, status="running", detail="resumed")
    store.set_phase(
        phase="resumed",
        detail=f"{target_session}:{controller_pane}",
        source="resume",
    )
    _record_tmux_layout_snapshot(
        run_store=store,
        session=target_session,
        reason="resume_recover",
    )
    store.append_event(
        event_type="run_resumed",
        source="resume",
        agent=controller_agent,
        payload={
            "previous_session": previous_session,
            "session": target_session,
            "controller_pane": controller_pane,
            "created_new_session": created_new_session,
            "created_new_pane": created_new_pane,
            "launch_command": launch_command,
            "runtime_session_id": controller_runtime_session_id,
            "runtime_session_restored": runtime_session_restored,
            "launch_ready": launch_ready,
            "prompt_injected": injected,
            "restored_subagents": restored_subagents,
        },
    )

    payload = {
        "run_id": resolved_run_id,
        "session": target_session,
        "controller_agent": controller_agent,
        "controller_pane": controller_pane,
        "created_new_session": created_new_session,
        "created_new_pane": created_new_pane,
        "launch_command": launch_command,
        "runtime_session_id": controller_runtime_session_id,
        "runtime_session_restored": runtime_session_restored,
        "launch_ready": launch_ready,
        "prompt_file": str(briefing),
        "prompt_injected": injected,
        "restored_subagent_count": len(restored_subagents),
        "restored_subagents": restored_subagents,
        "pending_steps": pending,
    }
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(
            f"[green]resume recovered[/green] run={run_id} session={target_session} pane={controller_pane} "
            f"pending={len(pending)}"
        )
        console.print(f"[dim]prompt file: {briefing}[/dim]")

    if attach:
        attach_session(session=target_session)


@main.command()
@click.option("--session", "-s", default="ai-collab", help="tmux session name")
@click.option("--cwd", "-w", default=".", help="Workspace directory to open in panes")
@click.option(
    "--controller",
    "-c",
    type=click.Choice(["codex", "claude", "gemini"]),
    help="Controller agent for top pane (default: current_controller)",
)
@click.option(
    "--layout",
    "-l",
    type=click.Choice(["stacked", "tabbed"]),
    default="stacked",
    show_default=True,
    help="stacked: top controller + 3 bottom panes; tabbed: top/bottom + agent tabs",
)
@click.option(
    "--task-hint",
    "-t",
    default="Describe your task once and split into design/implement/review subtasks.",
    help="A hint shown in each pane",
)
@click.option("--autorun-agents", "-a", is_flag=True, help="Auto-launch codex/claude/gemini REPL in panes")
@click.option("--reset", "-r", is_flag=True, help="Kill existing session with same name and recreate")
@click.option("--detached", "-d", is_flag=True, help="Create session without attaching")
@click.pass_context
def monitor(
    ctx: click.Context,
    session: str,
    cwd: str,
    controller: Optional[str],
    layout: str,
    task_hint: str,
    autorun_agents: bool,
    reset: bool,
    detached: bool,
) -> None:
    """Start a visual tmux workspace for multi-agent collaboration."""
    config = ctx.obj["config"]
    chosen_controller = controller or config.current_controller
    workspace = Path(cwd).expanduser().resolve()

    try:
        create_tmux_workspace(
            session=session,
            cwd=workspace,
            controller=chosen_controller,
            layout=layout,
            autorun_agents=autorun_agents,
            reset=reset,
            task_hint=task_hint,
        )
    except TmuxWorkspaceError as exc:
        console.print(f"[red]tmux workspace error:[/red] {exc}")
        raise SystemExit(2)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]tmux command failed:[/red] {exc}")
        raise SystemExit(exc.returncode or 1)

    console.print(
        f"[green]✅ tmux workspace ready[/green] session={session} layout={layout} controller={chosen_controller}"
    )
    console.print("Tips: Ctrl-b z (zoom pane), Ctrl-b w (window list), Ctrl-b d (detach)")

    if not detached:
        subprocess.run(["tmux", "attach-session", "-t", session], check=False)


@main.command(name="tmux-status")
@click.option("--json-output", "-j", is_flag=True, help="Print tmux status as JSON")
def tmux_status(json_output: bool) -> None:
    """Show current tmux session/window/pane binding info."""
    if shutil.which("tmux") is None:
        console.print("[red]tmux not found in PATH[/red]")
        raise SystemExit(2)

    session = ""
    window_index = ""
    pane_id = ""
    pane_cmd = ""
    current = subprocess.run(
        ["tmux", "display-message", "-p", "#S\t#{window_index}\t#{pane_id}\t#{pane_current_command}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if current.returncode == 0 and current.stdout.strip():
        session, window_index, pane_id, pane_cmd = current.stdout.strip().split("\t", 3)
    else:
        # Fallback for shells without active tmux client binding.
        sessions = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if sessions.returncode != 0:
            console.print("[yellow]Not in an active tmux client context[/yellow]")
            raise SystemExit(1)
        attached: list[str] = []
        all_sessions: list[str] = []
        for line in sessions.stdout.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0].strip():
                continue
            name = parts[0].strip()
            all_sessions.append(name)
            if len(parts) > 1 and parts[1].strip() == "1":
                attached.append(name)
        session = attached[0] if attached else (all_sessions[0] if all_sessions else "")
        if not session:
            console.print("[yellow]Not in an active tmux client context[/yellow]")
            raise SystemExit(1)
        fallback_panes = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-t",
                session,
                "-F",
                "#{window_index}\t#{pane_id}\t#{pane_active}\t#{pane_current_command}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if fallback_panes.returncode != 0 or not fallback_panes.stdout.strip():
            console.print("[yellow]Not in an active tmux client context[/yellow]")
            raise SystemExit(1)
        first_row = None
        active_row = None
        for line in fallback_panes.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            row = (parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip())
            if not first_row:
                first_row = row
            if row[2] == "1":
                active_row = row
                break
        chosen = active_row or first_row
        if not chosen:
            console.print("[yellow]Not in an active tmux client context[/yellow]")
            raise SystemExit(1)
        window_index, pane_id, _active, pane_cmd = chosen

    panes = subprocess.run(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session}:{window_index}",
            "-F",
            "#{pane_id}\t#{pane_active}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}\t#{pane_current_command}\t#{pane_title}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    pane_rows: list[dict[str, str]] = []
    if panes.returncode == 0:
        for line in panes.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 8:
                continue
            pane_rows.append(
                {
                    "pane_id": parts[0],
                    "active": parts[1],
                    "left": parts[2],
                    "top": parts[3],
                    "width": parts[4],
                    "height": parts[5],
                    "command": parts[6],
                    "title": parts[7],
                }
            )

    payload = {
        "session": session,
        "window_index": window_index,
        "current_pane": pane_id,
        "current_command": pane_cmd,
        "panes": pane_rows,
    }
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    console.print(f"[bold]tmux[/bold] session={session} window={window_index} pane={pane_id} cmd={pane_cmd}")
    for row in pane_rows:
        marker = "*" if row["active"] == "1" else " "
        console.print(
            f" {marker} {row['pane_id']} left={row['left']} top={row['top']} w={row['width']} h={row['height']} cmd={row['command']} title={row['title']}"
        )


@main.command(name="tmux-close-pane")
@click.option("--pane-id", "-p", required=True, help="Pane id to close, e.g. %11")
def tmux_close_pane(pane_id: str) -> None:
    """Close a specific tmux pane safely."""
    if shutil.which("tmux") is None:
        console.print("[red]tmux not found in PATH[/red]")
        raise SystemExit(2)
    target_session = _tmux_resolve_session_for_pane(pane_id=pane_id)
    run_store: Optional[RunStateStore] = None
    if target_session:
        run_store = _find_active_run_store_for_session(cwd=Path.cwd(), session=target_session)
    closed_agent = ""
    if run_store is not None:
        snap = run_store.snapshot()
        controller = snap.get("controller", {}) if isinstance(snap.get("controller", {}), dict) else {}
        if str(controller.get("pane_id", "")).strip() == str(pane_id).strip():
            closed_agent = str(controller.get("agent", "")).strip() or "controller"
        else:
            agents = snap.get("agents", {}) if isinstance(snap.get("agents", {}), dict) else {}
            for name, details in agents.items():
                if not isinstance(details, dict):
                    continue
                if str(details.get("pane_id", "")).strip() == str(pane_id).strip():
                    closed_agent = str(name).strip()
                    break
    result = subprocess.run(
        ["tmux", "kill-pane", "-t", pane_id],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or "").strip() or "unknown tmux error"
        console.print(f"[red]tmux-close-pane failed:[/red] {err}")
        raise SystemExit(result.returncode)
    if run_store is not None and target_session:
        if closed_agent:
            run_store.set_agent_status(agent=closed_agent, status="closed", detail="pane_closed")
        run_store.append_event(
            event_type="pane_closed",
            source="controller_cmd",
            agent=closed_agent,
            payload={"pane_id": pane_id, "session": target_session},
        )
        _record_tmux_layout_snapshot(
            run_store=run_store,
            session=target_session,
            reason="controller_close_pane",
        )
    console.print(f"[green]closed pane[/green] {pane_id}")


@main.command(name="tmux-capture")
@click.option("--pane-id", "-p", help="Target pane id (default: current pane)")
@click.option("--lines", "-n", type=int, default=180, show_default=True, help="Tail lines to capture")
def tmux_capture(pane_id: Optional[str], lines: int) -> None:
    """Capture pane output tail for debugging via ai-collab wrapper."""
    if shutil.which("tmux") is None:
        console.print("[red]tmux not found in PATH[/red]")
        raise SystemExit(2)
    target = pane_id
    if not target:
        cur = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if cur.returncode != 0 or not cur.stdout.strip():
            console.print("[red]No active tmux pane context[/red]")
            raise SystemExit(2)
        target = cur.stdout.strip()
    count = max(20, min(int(lines), 2000))
    out = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", target, "-S", f"-{count}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        err = (out.stderr or "").strip() or "unknown tmux error"
        console.print(f"[red]tmux-capture failed:[/red] {err}")
        raise SystemExit(out.returncode)
    print(out.stdout, end="")


def _classify_watch_issue(text: str) -> str:
    """Best-effort classification for stuck/error states from pane output."""
    lower = text.lower()
    if not lower.strip():
        return ""
    if "model_capacity_exhausted" in lower or ("429" in lower and "model" in lower):
        return "model_capacity_exhausted"
    if "currently experiencing high demand" in lower or (
        "keep trying" in lower and "switch to gemini-3-flash-preview" in lower
    ):
        return "model_capacity_exhausted"
    if "model not found" in lower or "invalid model" in lower:
        return "model_unavailable"
    if "permission denied" in lower or "approval required" in lower or "requires elevated permissions" in lower:
        return "permission_blocked"
    if "connection error" in lower or "failed to connect" in lower or "network" in lower:
        return "network_error"
    if "timed out" in lower or "timeout" in lower:
        return "upstream_timeout"
    return ""


def _contains_completion_marker(text: str) -> bool:
    """Return True only when completion marker appears as a standalone output line."""
    normalized = _normalize_terminal_text_for_markers(text)
    return bool(COMPLETION_MARKER_LINE_RE.search(normalized))


def _completion_marker_count(text: str) -> int:
    """Count standalone completion markers in terminal text."""
    normalized = _normalize_terminal_text_for_markers(text)
    return len(COMPLETION_MARKER_LINE_RE.findall(normalized))


def _completion_event_signature(event: dict[str, Any]) -> str:
    """Stable signature for deduplicating parsed completion events."""
    try:
        return json.dumps(event, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(event)


def _watch_status_suggestion(status: str, reason: str) -> str:
    if status == "completed":
        return "Sub-agent finished. Ask user whether to close pane and continue."
    if status == "pane_unavailable":
        return "Pane is unavailable; restart sub-agent or rebind pane id."
    if status == "error":
        if reason in {"model_capacity_exhausted", "model_unavailable"}:
            return "Fallback to backup model/agent, then retry."
        if reason == "permission_blocked":
            return "Request elevation or adjust permission mode, then retry."
        if reason == "network_error":
            return "Retry with backoff; if repeated, switch provider/agent."
        return "Check pane logs and retry monitoring."
    if status == "timeout":
        if reason == "still_running":
            return "Increase timeout and monitor again."
        if reason == "idle_no_progress":
            return "Sub-agent may be stuck; nudge with a scoped follow-up prompt or restart."
        return "Monitor again or switch fallback agent if repeated."
    return "Continue monitoring."


@main.command(name="tmux-watch")
@click.option("--pane-id", "-p", help="Target pane id (default: current pane)")
@click.option("--timeout-seconds", "-t", type=float, default=30.0, show_default=True, help="Watch timeout in seconds")
@click.option("--poll-seconds", "-i", type=float, default=1.0, show_default=True, help="Polling interval in seconds")
@click.option("--capture-lines", "-n", type=int, default=220, show_default=True, help="Tail lines captured each poll")
@click.option("--json-output", "-j", is_flag=True, help="Print watch result as JSON")
def tmux_watch(
    pane_id: Optional[str],
    timeout_seconds: float,
    poll_seconds: float,
    capture_lines: int,
    json_output: bool,
) -> None:
    """Watch one pane until completion/timeout and return structured execution status."""
    if shutil.which("tmux") is None:
        console.print("[red]tmux not found in PATH[/red]")
        raise SystemExit(2)
    target = pane_id
    if not target:
        cur = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if cur.returncode != 0 or not cur.stdout.strip():
            console.print("[red]No active tmux pane context[/red]")
            raise SystemExit(2)
        target = cur.stdout.strip()

    timeout = max(float(timeout_seconds), 1.0)
    interval = max(float(poll_seconds), 0.2)
    count = max(120, min(int(capture_lines), 4000))

    start = time.monotonic()
    last_change = start
    last_tail = ""
    seeded = False
    status = "running"
    reason = ""
    completion_source = ""
    completion_event: dict[str, Any] = {}
    seen_event_signatures: set[str] = set()
    seen_marker_count = 0
    active_issue = ""
    active_issue_since = 0.0
    issue_grace_seconds = max(4.0, min(12.0, timeout * 0.35))

    while time.monotonic() - start < timeout:
        shot = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", target, "-S", f"-{count}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shot.returncode != 0:
            status = "pane_unavailable"
            reason = (shot.stderr or "").strip() or "pane_unavailable"
            break

        tail = shot.stdout[-12000:]
        prev_tail = last_tail
        seeded_this_round = False
        if not seeded:
            seeded = True
            seeded_this_round = True
            delta = tail
            seen_marker_count = _completion_marker_count(tail)
            for evt in _extract_ai_collab_events(tail):
                seen_event_signatures.add(_completion_event_signature(evt))
        elif tail.startswith(prev_tail):
            delta = tail[len(prev_tail):]
        else:
            delta = tail

        if tail != prev_tail:
            last_change = time.monotonic()
        last_tail = tail

        if not seeded_this_round:
            parsed_events = _extract_ai_collab_events(delta)
            for evt in parsed_events:
                signature = _completion_event_signature(evt)
                if signature in seen_event_signatures:
                    continue
                seen_event_signatures.add(signature)
                evt_type = str(evt.get("type", "")).strip().lower()
                if evt_type in {"subagent_complete", "task_complete"}:
                    status = "completed"
                    reason = "structured_event"
                    completion_source = "ai_collab_event"
                    completion_event = evt
                    break
            if status == "completed":
                break

            marker_count = _completion_marker_count(tail)
            if marker_count > seen_marker_count:
                status = "completed"
                reason = "completion_marker"
                completion_source = "legacy_marker"
                break
            seen_marker_count = max(seen_marker_count, marker_count)

        now_tick = time.monotonic()
        idle_now = now_tick - last_change
        issue = _classify_watch_issue(delta) or _classify_watch_issue(tail)
        if issue:
            if issue != active_issue:
                active_issue = issue
                active_issue_since = now_tick
            elif (
                active_issue_since > 0
                and now_tick - active_issue_since >= issue_grace_seconds
                and idle_now >= min(issue_grace_seconds, 6.0)
            ):
                status = "error"
                reason = issue
                break
        else:
            active_issue = ""
            active_issue_since = 0.0

        time.sleep(interval)

    elapsed = time.monotonic() - start
    idle = time.monotonic() - last_change

    if status == "running":
        if active_issue and idle >= min(issue_grace_seconds, 6.0):
            status = "error"
            reason = active_issue
        else:
            status = "timeout"
            reason = "idle_no_progress" if idle >= max(timeout * 0.6, 8.0) else "still_running"

    payload: dict[str, Any] = {
        "pane_id": target,
        "status": status,
        "reason": reason,
        "completion_source": completion_source,
        "elapsed_seconds": round(elapsed, 2),
        "idle_seconds": round(idle, 2),
        "suggestion": _watch_status_suggestion(status, reason),
    }
    if completion_event:
        payload["completion_event"] = completion_event

    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(
            f"[bold]watch[/bold] pane={payload['pane_id']} status={payload['status']} "
            f"reason={payload['reason']} elapsed={payload['elapsed_seconds']}s idle={payload['idle_seconds']}s"
        )
        console.print(f"suggestion: {payload['suggestion']}")

    if status in {"pane_unavailable", "error"}:
        raise SystemExit(1)


@main.command()
@click.option("--agent", "-a", type=click.Choice(["codex", "claude", "gemini"]), required=True, help="Agent CLI to launch")
@click.option("--agent-cmd", "-x", help="Override launch command, e.g. 'gemini --model gemini-3.1-pro-preview'")
@click.option("--model", "-m", help="Model option for gemini when --agent-cmd is not provided")
@click.option("--session", "-s", help="tmux session name; default auto-detect current/attached session")
@click.option("--window-name", "-n", help="tmux window name")
@click.option("--tmux-layout", "-l", type=click.Choice(["window", "split"]), default="window", show_default=True, help="window: new tmux window; split: split current/target pane")
@click.option("--split-policy", "-P", type=click.Choice(["manual", "controller-bottom"]), default="manual", show_default=True, help="split placement policy")
@click.option("--split-direction", "-D", type=click.Choice(["vertical", "horizontal"]), default="vertical", show_default=True, help="split direction when --tmux-layout split")
@click.option("--split-percent", "-z", type=int, default=35, show_default=True, help="size percent for new split pane")
@click.option("--split-target-pane", "-T", help="target pane id to split from (default current/active pane)")
@click.option("--controller-pane", "-c", help="controller pane id for controller-bottom policy")
@click.option("--controller-height-percent", "-H", type=int, default=50, show_default=True, help="controller top-pane height in percent for controller-bottom policy")
@click.option("--shell", "-S", help="shell command for new pane/window")
@click.option("--repo-root", "-r", default=".", show_default=True, help="repository root to cd into")
@click.option("--prompt-file", "-f", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="prompt file content sent to agent")
@click.option("--prompt", "-p", help="inline prompt text sent to agent")
@click.option("--no-prompt", "-N", is_flag=True, help="Launch agent only without sending prompt text")
@click.option("--prompt-mode", "-M", type=click.Choice(["auto", "paste", "type"]), default="auto", show_default=True, help="prompt injection mode")
@click.option(
    "--completion-action",
    "-k",
    type=click.Choice(["ask", "keep", "close", "none"]),
    help="Sub-agent completion policy: ask user / keep pane / auto close / disable watcher",
)
@click.option("--completion-timeout", "-K", type=float, default=21600.0, show_default=True, help="Completion watcher timeout in seconds (0 means no timeout)")
@click.option(
    "--completion-notify-mode",
    "-y",
    type=click.Choice(["status", "input", "both", "none"]),
    default="input",
    show_default=True,
    help="How completion watcher notifies controller pane",
)
@click.option(
    "-J/-j",
    "--ask-launch-options/--no-ask-launch-options",
    default=True,
    show_default=False,
    help="Prompt for completion policy before spawning a sub-agent when running interactively",
)
@click.option("--wait-shell-timeout", "-W", type=float, default=20.0, show_default=True)
@click.option("--wait-agent-timeout", "-A", type=float, default=120.0, show_default=True)
@click.option("--capture-lines", "-L", type=int, default=120, show_default=True)
@click.option("--shell-settle-delay", "-e", type=float, default=2.0, show_default=True)
@click.option("--shell-idle-quiet-for", "-q", type=float, default=1.5, show_default=True)
@click.option("--shell-probe-timeout", "-b", type=float, default=12.0, show_default=True, help="Max wait for shell echo probe before first command")
@click.option("--agent-idle-quiet-for", "-g", type=float, default=1.5, show_default=True)
@click.option("--agent-min-runtime", "-R", type=float, default=2.0, show_default=True)
@click.option("--startup-pattern", "-u", help="Override agent-ready regex (forwarded to handoff script)")
@click.option("--enter-delay", "-E", type=float, default=0.6, show_default=True)
@click.option("--verbose", "-v", is_flag=True, help="print step-by-step progress logs")
def handoff(
    agent: str,
    agent_cmd: Optional[str],
    model: Optional[str],
    session: Optional[str],
    window_name: Optional[str],
    tmux_layout: str,
    split_policy: str,
    split_direction: str,
    split_percent: int,
    split_target_pane: Optional[str],
    controller_pane: Optional[str],
    controller_height_percent: int,
    shell: Optional[str],
    repo_root: str,
    prompt_file: Optional[Path],
    prompt: Optional[str],
    no_prompt: bool,
    prompt_mode: str,
    completion_action: Optional[str],
    completion_timeout: float,
    completion_notify_mode: str,
    ask_launch_options: bool,
    wait_shell_timeout: float,
    wait_agent_timeout: float,
    capture_lines: int,
    shell_settle_delay: float,
    shell_idle_quiet_for: float,
    shell_probe_timeout: float,
    agent_idle_quiet_for: float,
    agent_min_runtime: float,
    startup_pattern: Optional[str],
    enter_delay: float,
    verbose: bool,
) -> None:
    """Run one-click tmux handoff for codex/claude/gemini with window/split layout."""
    source = _resolve_orchestrator_skill_source()
    script = source / "scripts" / "tmux_agent_handoff.py" if source else None
    if not script or not script.exists():
        console.print("[red]handoff script not found. Reinstall ai-collab-orchestrator skill first.[/red]")
        raise SystemExit(2)

    selected_completion_action = completion_action
    if selected_completion_action is None:
        if ask_launch_options and sys.stdin.isatty():
            selected_completion_action = Prompt.ask(
                "Sub-agent completion policy",
                choices=["ask", "keep", "close", "none"],
                default="ask",
            )
        else:
            selected_completion_action = "ask"

    cmd: list[str] = [
        sys.executable,
        str(script),
        "--agent",
        agent,
        "--repo-root",
        str(Path(repo_root).expanduser().resolve()),
        "--tmux-layout",
        tmux_layout,
        "--split-policy",
        split_policy,
        "--split-direction",
        split_direction,
        "--split-percent",
        str(split_percent),
        "--prompt-mode",
        prompt_mode,
        "--wait-shell-timeout",
        str(wait_shell_timeout),
        "--wait-agent-timeout",
        str(wait_agent_timeout),
        "--capture-lines",
        str(capture_lines),
        "--completion-action",
        str(selected_completion_action),
        "--completion-timeout",
        str(max(0.0, completion_timeout)),
        "--completion-notify-mode",
        completion_notify_mode,
        "--shell-settle-delay",
        str(shell_settle_delay),
        "--shell-idle-quiet-for",
        str(shell_idle_quiet_for),
        "--shell-probe-timeout",
        str(max(1.0, shell_probe_timeout)),
        "--agent-idle-quiet-for",
        str(agent_idle_quiet_for),
        "--agent-min-runtime",
        str(agent_min_runtime),
        "--enter-delay",
        str(enter_delay),
    ]
    if startup_pattern:
        cmd.extend(["--startup-pattern", startup_pattern])
    if agent_cmd:
        cmd.extend(["--agent-cmd", agent_cmd])
    elif model:
        cmd.extend(["--model", model])
    if session:
        cmd.extend(["--session", session])
    if window_name:
        cmd.extend(["--window-name", window_name])
    if split_target_pane:
        cmd.extend(["--split-target-pane", split_target_pane])
    if controller_pane:
        cmd.extend(["--controller-pane", controller_pane])
    if controller_height_percent:
        cmd.extend(["--controller-height-percent", str(controller_height_percent)])
    if shell:
        cmd.extend(["--shell", shell])
    if no_prompt:
        cmd.append("--no-prompt")
    elif prompt_file:
        cmd.extend(["--prompt-file", str(prompt_file.expanduser().resolve())])
    elif prompt:
        cmd.extend(["--prompt", prompt])
    else:
        cmd.append("--no-prompt")
    if verbose:
        cmd.append("--verbose")

    result = subprocess.run(cmd, check=False)
    if result.returncode == 0 and os.environ.get("AI_COLLAB_ACTIVE") == "1":
        current_session = _detect_tmux_session_name(preferred=session)
        if current_session:
            store = _find_active_run_store_for_session(
                cwd=Path(repo_root).expanduser().resolve(),
                session=current_session,
                controller_pane=str(controller_pane or "").strip(),
            )
            if store is not None:
                ctrl_pane = str(controller_pane or "").strip()
                if not ctrl_pane:
                    snap = store.snapshot()
                    ctrl = snap.get("controller", {}) if isinstance(snap.get("controller", {}), dict) else {}
                    ctrl_pane = str(ctrl.get("pane_id", "")).strip()
                if ctrl_pane:
                    try:
                        ctrl_text = capture_pane_text(pane_id=ctrl_pane, start_line=-320)
                    except subprocess.CalledProcessError:
                        ctrl_text = ""
                    _sync_controller_progress_from_text(
                        run_store=store,
                        text=ctrl_text,
                        source="controller_marker",
                    )
                current = store.snapshot()
                tmux_state = current.get("tmux", {}) if isinstance(current.get("tmux", {}), dict) else {}
                before_snapshot = (
                    tmux_state.get("layout_snapshot", {}) if isinstance(tmux_state.get("layout_snapshot", {}), dict) else {}
                )
                before_panes = _snapshot_pane_ids(before_snapshot)
                store.append_event(
                    event_type="controller_handoff_command",
                    source="controller_cmd",
                    agent=agent,
                    payload={
                        "layout": tmux_layout,
                        "split_policy": split_policy,
                        "agent_cmd": bool(agent_cmd),
                        "model": model or "",
                    },
                )
                _record_tmux_layout_snapshot(
                    run_store=store,
                    session=current_session,
                    reason="controller_handoff_command",
                )
                latest = store.snapshot()
                latest_tmux = latest.get("tmux", {}) if isinstance(latest.get("tmux", {}), dict) else {}
                after_snapshot = (
                    latest_tmux.get("layout_snapshot", {})
                    if isinstance(latest_tmux.get("layout_snapshot", {}), dict)
                    else {}
                )
                after_panes = _snapshot_pane_ids(after_snapshot)
                new_panes = sorted(after_panes - before_panes)
                spawned_pane = new_panes[-1] if new_panes else ""
                if spawned_pane:
                    store.bind_agent(agent=agent, pane_id=spawned_pane, step_tickets=[])
                    runtime_id = _resolve_runtime_session_id_for_agent(
                        state=store.snapshot(),
                        agent=agent,
                        pane_id=spawned_pane,
                        sessions=[current_session],
                        cwd=Path(repo_root).expanduser().resolve(),
                    )
                    if runtime_id:
                        store.set_agent_runtime_session_id(agent=agent, runtime_session_id=runtime_id)
                else:
                    store.set_agent_status(agent=agent, status="running", detail="handoff_launched")
                    store.set_phase(
                        phase="subagent_spawned",
                        detail=f"{agent}:unknown",
                        source="controller_cmd",
                    )
                store.append_event(
                    event_type="subagent_spawned",
                    source="controller_cmd",
                    agent=agent,
                    payload={
                        "pane_id": spawned_pane,
                        "layout": tmux_layout,
                        "step_ids": [],
                    },
                )
    raise SystemExit(result.returncode)


@main.command(name="tmux-open")
@click.option("-a", "--agent", type=click.Choice(["codex", "claude", "gemini"]), required=True, help="Agent to launch")
@click.option("-x", "--agent-cmd", help="Override launch command")
@click.option("-m", "--model", help="Model for gemini when --agent-cmd is not set")
@click.option("-s", "--session", help="tmux session (default auto-detect current)")
@click.option("-l", "--layout", type=click.Choice(["split", "window"]), default="split", show_default=True, help="tmux layout")
@click.option("-c", "--controller-pane", help="Controller pane id for split controller-bottom policy")
@click.option("-n", "--window-name", help="Window name")
@click.option("-r", "--repo-root", default=".", show_default=True, help="Repository root")
@click.option("-p", "--prompt", help="Inline prompt")
@click.option("-f", "--prompt-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Prompt file")
@click.option("-k", "--completion", type=click.Choice(["ask", "keep", "close", "none"]), default="ask", show_default=True, help="Completion policy")
@click.option(
    "-N",
    "--notify",
    type=click.Choice(["input", "status", "both", "none"]),
    default="input",
    show_default=True,
    help="Completion notify mode",
)
def tmux_open(
    agent: str,
    agent_cmd: Optional[str],
    model: Optional[str],
    session: Optional[str],
    layout: str,
    controller_pane: Optional[str],
    window_name: Optional[str],
    repo_root: str,
    prompt: Optional[str],
    prompt_file: Optional[Path],
    completion: str,
    notify: str,
) -> None:
    """Short wrapper for `ai-collab handoff` with sane tmux defaults."""
    if prompt and prompt_file:
        console.print("[red]Use either --prompt or --prompt-file, not both.[/red]")
        raise SystemExit(2)

    cmd: list[str] = [
        sys.executable,
        "-m",
        "ai_collab.cli",
        "handoff",
        "--agent",
        agent,
        "--tmux-layout",
        layout,
        "--repo-root",
        str(Path(repo_root).expanduser().resolve()),
        "--completion-action",
        completion,
        "--completion-notify-mode",
        notify,
        "--no-ask-launch-options",
    ]
    if layout == "split":
        cmd.extend(["--split-policy", "controller-bottom"])
    if session:
        cmd.extend(["--session", session])
    if controller_pane:
        cmd.extend(["--controller-pane", controller_pane])
    if window_name:
        cmd.extend(["--window-name", window_name])
    if agent_cmd:
        cmd.extend(["--agent-cmd", agent_cmd])
    elif model:
        cmd.extend(["--model", model])
    if prompt_file:
        cmd.extend(["--prompt-file", str(prompt_file.expanduser().resolve())])
    elif prompt:
        cmd.extend(["--prompt", prompt])
    else:
        cmd.append("--no-prompt")

    result = subprocess.run(cmd, check=False)
    raise SystemExit(result.returncode)


@main.command(name="tmux-close-test")
@click.option("-C", "--controller", type=click.Choice(["codex", "claude", "gemini"]), default="codex", show_default=True, help="Controller agent")
@click.option("-S", "--subagent", type=click.Choice(["codex", "claude", "gemini"]), default="codex", show_default=True, help="Sub-agent")
@click.option("-d", "--duration", type=int, default=90, show_default=True, help="Sub-agent target duration seconds")
@click.option("-t", "--watch1", type=int, default=60, show_default=True, help="First watch timeout seconds")
@click.option("-r", "--watch2", type=int, default=45, show_default=True, help="Second watch timeout seconds")
@click.option("-s", "--session", help="tmux session (default auto-detect current)")
@click.option("-w", "--window-name", default="controller-close-test", show_default=True, help="Controller window name")
@click.option("--repo-root", "-R", default=".", show_default=True, help="Repository root")
def tmux_close_test(
    controller: str,
    subagent: str,
    duration: int,
    watch1: int,
    watch2: int,
    session: Optional[str],
    window_name: str,
    repo_root: str,
) -> None:
    """One-command setup for controller close-choice workflow test."""
    root = Path(repo_root).expanduser().resolve()
    seconds = max(5, int(duration))
    t1 = max(5, int(watch1))
    t2 = max(5, int(watch2))

    sub_cmd = (
        "codex --dangerously-bypass-approvals-and-sandbox"
        if subagent == "codex"
        else subagent
    )
    prompt = (
        f"你是主控Agent（{controller}）。直接执行，不要--help，不要读源码。\\n"
        "只使用 ai-collab tmux-status/handoff/tmux-watch/tmux-capture/tmux-close-pane。\\n"
        "步骤：\\n"
        "1) 用 ai-collab tmux-status --json-output 取 CTRL_PANE。\\n"
        f"2) 启动子控：ai-collab handoff --agent {subagent} --agent-cmd '{sub_cmd}' "
        "--tmux-layout split --split-policy controller-bottom --controller-pane <CTRL_PANE> "
        f"--repo-root {root} --prompt '子控只做一件事：先执行 sleep {seconds}，"
        "然后输出 SUBTASK_RESULT: done-after-sleep 和 === TASK_COMPLETE ===。禁止额外任务。' "
        "--completion-action ask --completion-timeout 900 --completion-notify-mode input --no-ask-launch-options。\\n"
        "3) 解析 SUB_PANE。\\n"
        f"4) 先监控 {t1}s：ai-collab tmux-watch --pane-id <SUB_PANE> --timeout-seconds {t1} --json-output。\\n"
        f"5) 若 timeout/still_running，再监控 {t2}s：ai-collab tmux-watch --pane-id <SUB_PANE> --timeout-seconds {t2} --json-output。\\n"
        "6) 用 ai-collab tmux-capture --pane-id <SUB_PANE> --lines 260 验收：必须同时包含 SUBTASK_RESULT: done-after-sleep 和 === TASK_COMPLETE ===。\\n"
        "7) 询问用户：\\n是否关闭已完成子控窗口？\\n1. 关闭窗口\\n2. 保留窗口\\n"
        "8) 若用户输入1：执行 ai-collab tmux-close-pane --pane-id <SUB_PANE> 并输出 [CTRL] close-done <SUB_PANE>。\\n"
        "9) 若用户输入2：输出 [CTRL] keep-done <SUB_PANE>。\\n"
        "10) 最后一行输出 CONTROLLER_CLOSE_CHOICE_TEST_DONE。"
    )
    prompt_file = _write_briefing_file(
        cwd=root,
        role="controller-close-test",
        agent=controller,
        text=prompt,
    )

    cmd: list[str] = [
        sys.executable,
        "-m",
        "ai_collab.cli",
        "tmux-open",
        "--agent",
        controller,
        "--layout",
        "window",
        "--window-name",
        window_name,
        "--repo-root",
        str(root),
        "--prompt-file",
        str(prompt_file),
        "--completion",
        "none",
    ]
    if controller == "codex":
        cmd.extend(["--agent-cmd", "codex --dangerously-bypass-approvals-and-sandbox"])
    if session:
        cmd.extend(["--session", session])

    console.print(f"[dim]controller test prompt: {prompt_file}[/dim]")
    result = subprocess.run(cmd, check=False)
    raise SystemExit(result.returncode)


@main.command(name="relay-smoke")
@click.option("--agent", "-a", type=click.Choice(["codex", "claude", "gemini"]), default="claude", show_default=True, help="Sub-agent to validate")
@click.option("--controller-agent", "-c", type=click.Choice(["codex", "claude", "gemini"]), default="codex", show_default=True, help="Controller agent label for run binding")
@click.option("--timeout-seconds", "-t", type=int, default=180, show_default=True, help="Max wait for completion")
@click.option("--cwd", "-w", default=".", show_default=True, help="Workspace root for .ai-collab run files")
@click.option("-k/-K", "--keep-pane/--auto-close-pane", default=True, show_default=False, help="Keep spawned sub-agent pane after test")
@click.option("-u/-U", "--require-step-done/--allow-missing-step-done", default=True, show_default=False, help="Require step_done event to pass")
def relay_smoke(
    agent: str,
    controller_agent: str,
    timeout_seconds: int,
    cwd: str,
    keep_pane: bool,
    require_step_done: bool,
) -> None:
    """Run structured relay smoke test in current tmux controller pane."""
    if shutil.which("tmux") is None:
        console.print("[red]tmux not found in PATH[/red]")
        raise SystemExit(2)
    current = subprocess.run(
        ["tmux", "display-message", "-p", "#S\t#{pane_id}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if current.returncode != 0 or not current.stdout.strip():
        console.print("[red]No active tmux client context for relay-smoke[/red]")
        raise SystemExit(2)
    session, controller_pane = current.stdout.strip().split("\t", 1)
    root = Path(cwd).expanduser().resolve()

    run_store = RunStateStore.create(
        cwd=root,
        session=session,
        controller_agent=controller_agent,
        controller_pane=controller_pane,
    )
    run_store.set_mode(mode="tmux")
    steps = [
        {
            "id": "S1",
            "role": "event-smoke",
            "selected_model": "default",
            "reason": "validate structured completion relay",
        }
    ]
    pane_id = _spawn_subagent_with_prompt(
        session=session,
        controller_pane=controller_pane,
        controller=controller_agent,
        agent=agent,
        task="这是一条系统回执测试任务：不要实现代码。请按要求输出 AI_COLLAB_EVENT step_done + subagent_complete。",
        steps=steps,
        cwd=root,
        lang="zh-CN",
        run_store=run_store,
    )
    console.print(f"[dim]run_id: {run_store.run_id}[/dim]")
    console.print(f"[dim]subagent_pane: {pane_id}[/dim]")

    deadline = time.time() + max(timeout_seconds, 10)
    final_status = "running"
    while time.time() < deadline:
        try:
            state = json.loads(run_store.paths.state_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
            continue
        final_status = str(state.get("agents", {}).get(agent, {}).get("status", "running"))
        if final_status in {"completed", "timeout_hard"}:
            break
        time.sleep(2.0)

    state = json.loads(run_store.paths.state_file.read_text(encoding="utf-8"))
    step_status = str(state.get("steps", {}).get("S1", {}).get("status", "unknown"))
    console.print(f"[bold]final_agent_status[/bold]: {final_status}")
    console.print(f"[bold]final_step_status[/bold]: {step_status}")
    console.print(f"[dim]run_dir: {run_store.paths.run_dir}[/dim]")

    if not keep_pane:
        subprocess.run(["tmux", "kill-pane", "-t", pane_id], check=False)

    if final_status != "completed":
        raise SystemExit(1)
    if require_step_done and step_status != "done":
        console.print("[red]relay-smoke failed:[/red] sub-agent completed without step_done event.")
        raise SystemExit(1)


def _resolve_provider_execution(
    config: Config,
    provider: str,
    task: str,
    *,
    complexity: str = "default",
) -> tuple[Optional[str], Optional[int]]:
    """Resolve provider CLI and timeout with model selection fallback."""
    provider_config = config.providers.get(provider)
    if not provider_config:
        return None, None
    selected_cli = provider_config.cli
    try:
        selected_cli = ModelSelector(config).select_model(provider, task, complexity).cli
    except Exception:
        selected_cli = provider_config.cli
    return selected_cli, provider_config.timeout


def _direct_route_context(
    *,
    provider: str,
    result: Any | None,
    controller_plan: Optional[dict[str, Any]] = None,
    interactive: bool = False,
    extra_context: Optional[dict[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    """Build route key and execution context for unified direct runtime."""
    controller_plan = controller_plan if isinstance(controller_plan, dict) else None
    workflow_blueprint = ""
    session_preset = ""
    if controller_plan:
        workflow_blueprint = str(controller_plan.get("workflow_blueprint", "") or "").strip()
        session_preset = str(controller_plan.get("session_preset", "") or "").strip()
    if result is not None:
        if not workflow_blueprint:
            workflow_blueprint = str(getattr(result, "workflow_blueprint", "") or "").strip()
        if not session_preset:
            session_preset = str(getattr(result, "session_preset", "") or "").strip()

    context = {
        "controller": provider,
        "project_categories": ", ".join(getattr(result, "project_categories", []) or []),
        "auto_skills": ", ".join(getattr(result, "suggested_skills", []) or []),
        "intent": getattr(result, "intent", "") or "",
        "workflow_engine": getattr(result, "workflow_engine", "") or "",
        "session_preset": session_preset,
        "workflow_blueprint": workflow_blueprint,
        "interactive": interactive,
    }
    if controller_plan:
        context["controller_plan"] = json.dumps(controller_plan, ensure_ascii=False)
    if extra_context:
        for key, value in extra_context.items():
            if value is not None:
                context[key] = value
    route_key = workflow_blueprint or session_preset
    return route_key, context


def _execute_direct_runtime(
    *,
    config: Config,
    provider: str,
    task: str,
    result: Any | None = None,
    controller_plan: Optional[dict[str, Any]] = None,
    cwd: Path | str | None = None,
    interactive: bool = False,
    task_payload: Optional[str] = None,
    extra_context: Optional[dict[str, Any]] = None,
) -> int:
    """Unified direct runtime for single-agent and multi-agent execution."""
    _set_last_direct_runtime_error("")
    runtime_lang = _resolve_runtime_language(cli_lang=None, config_lang=config.ui_language)
    if bool(getattr(result, "need_collaboration", False)):
        merged_extra_context = dict(extra_context or {})
        merged_extra_context["live_output"] = True
        route_key, context = _direct_route_context(
            provider=provider,
            result=result,
            controller_plan=controller_plan,
            interactive=interactive,
            extra_context=merged_extra_context,
        )
        _print_runtime_overview(
            title=_auto_msg(runtime_lang, "direct_runtime_title"),
            lang=runtime_lang,
            mode="direct",
            provider=provider,
            task=task,
            result=result,
            controller_plan=controller_plan,
        )
        previous_cwd = Path.cwd()
        try:
            if cwd is not None:
                os.chdir(Path(cwd).expanduser())
            workflow_manager = WorkflowManager(config)
            results = workflow_manager.execute_workflow(route_key, task, context)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]direct runtime failed:[/red] {exc}")
            _print_direct_result_summary(
                lang=runtime_lang,
                status="failed",
                provider=provider,
                exit_code=1,
                reason=str(exc),
            )
            return 1
        finally:
            if cwd is not None:
                os.chdir(previous_cwd)
        summary = results.get("_summary", {}) if isinstance(results, dict) else {}
        status = str(summary.get("status", "completed"))
        _print_direct_result_summary(
            lang=runtime_lang,
            status=status,
            provider=provider,
            summary=summary if isinstance(summary, dict) else None,
        )
        return 0 if status not in {"failed", "aborted_by_user"} else 1

    selected_cli, timeout = _resolve_provider_execution(config, provider, task, complexity="default")
    if not selected_cli:
        return 2

    payload = task_payload if task_payload is not None else task
    auto_skills = getattr(result, "suggested_skills", []) if result is not None else []
    if task_payload is None and auto_skills:
        payload = (
            f"Auto-trigger skills (apply if available): {', '.join(auto_skills)}\n\n"
            f"Task: {task}"
        )
    _print_runtime_overview(
        title=_auto_msg(runtime_lang, "direct_runtime_title"),
        lang=runtime_lang,
        mode="direct",
        provider=provider,
        task=task,
        result=result,
    )
    return _safe_execute(
        selected_cli,
        payload,
        timeout=timeout,
        cwd=cwd,
        provider=provider,
        lang=runtime_lang,
    )


def _safe_execute(
    cli: str,
    task: str,
    timeout: Optional[int] = None,
    *,
    cwd: Path | str | None = None,
    provider: str = "",
    lang: str = "en-US",
) -> int:
    """Execute provider CLI safely with shell=False."""
    if cli.strip().startswith("codex ") and "--skip-git-repo-check" not in cli:
        cli = f"{cli} --skip-git-repo-check"
    try:
        cmd_parts = shlex.split(cli)
    except ValueError as exc:
        console.print(f"[red]Invalid provider CLI: {exc}[/red]")
        return 2
    cmd_parts = resolve_subprocess_command(cmd_parts)
    line_prefix = build_live_output_prefix(provider or (cmd_parts[0] if cmd_parts else "agent"), "direct")

    previous_cwd = Path.cwd()
    try:
        _set_last_direct_runtime_error("")
        if cwd is not None:
            os.chdir(Path(cwd).expanduser())
        try:
            result = _run_command_live_pipe(
                cmd_parts + [task],
                timeout=timeout,
                line_prefix=line_prefix,
            )
        except (OSError, ValueError) as exc:
            console.print(f"[dim]live direct stream unavailable, falling back to buffered execution: {exc}[/dim]")
            result = subprocess.run(
                cmd_parts + [task],
                shell=False,
                timeout=timeout,
            )
        status = "completed" if result.returncode == 0 else "failed"
        reason = ""
        if result.returncode != 0:
            reason = _summarize_runtime_failure_text(getattr(result, "stderr", "") or getattr(result, "stdout", ""))
            if not reason:
                reason = f"provider exited with code {result.returncode}"
        _set_last_direct_runtime_error(reason)
        _print_direct_result_summary(
            lang=lang,
            status=status,
            provider=provider or (cmd_parts[0] if cmd_parts else "agent"),
            exit_code=result.returncode,
            reason=reason,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        timeout_text = f"{timeout}s" if timeout is not None else "the configured timeout"
        console.print(f"[red]Provider command timed out after {timeout_text}.[/red]")
        _print_direct_result_summary(
            lang=lang,
            status="timeout",
            provider=provider or (cmd_parts[0] if cmd_parts else "agent"),
            exit_code=124,
            reason=timeout_text,
        )
        return 124
    except FileNotFoundError:
        console.print("[red]Provider command not found. Check your PATH and provider CLI installation.[/red]")
        _print_direct_result_summary(
            lang=lang,
            status="failed",
            provider=provider or (cmd_parts[0] if cmd_parts else "agent"),
            exit_code=127,
            reason="provider command not found",
        )
        return 127
    except PermissionError as exc:
        console.print(f"[red]Provider command is not executable: {exc}[/red]")
        _print_direct_result_summary(
            lang=lang,
            status="failed",
            provider=provider or (cmd_parts[0] if cmd_parts else "agent"),
            exit_code=126,
            reason=str(exc),
        )
        return 126
    finally:
        if cwd is not None:
            os.chdir(previous_cwd)


def _tmux_agent_startup_command(
    agent: str,
    *,
    selected_cli: str = "",
    model: str = "",
    profile: str = "",
) -> str:
    """Build interactive startup command for tmux panes."""
    raw_cli = str(selected_cli or "").strip()
    model_id = str(model or "").strip()
    profile_key = str(profile or "").strip()

    if raw_cli:
        try:
            parts = shlex.split(raw_cli)
        except ValueError:
            parts = raw_cli.split()
        if agent == "codex" and parts:
            converted: list[str] = []
            idx = 0
            while idx < len(parts):
                part = parts[idx]
                if idx == 1 and part == "exec":
                    idx += 1
                    continue
                if part == "--thinking" and idx + 1 < len(parts):
                    converted.extend(["-c", f'model_reasoning_effort="{parts[idx + 1]}"'])
                    idx += 2
                    continue
                if part.startswith("--thinking="):
                    converted.extend(["-c", f'model_reasoning_effort="{part.split("=", 1)[1]}"'])
                    idx += 1
                    continue
                converted.append(part)
                idx += 1
            return " ".join(converted)
        return raw_cli

    if agent == "codex":
        parts = ["codex"]
        if model_id and model_id.lower() != "unknown":
            parts.extend(["--model", model_id])
        if profile_key:
            parts.extend(["-c", f'model_reasoning_effort="{profile_key}"'])
        return " ".join(parts)

    if agent == "claude":
        if model_id and model_id.lower() != "unknown":
            return f"claude --model {shlex.quote(model_id)}"
        return "claude"

    if agent == "gemini":
        if model_id and model_id.lower() not in {"unknown", "gemini-cli-auto"}:
            return f"gemini --model {shlex.quote(model_id)}"
        return "gemini"

    return agent


def _provider_profiles(
    provider: str,
    provider_config,
    lang: str = "en-US",
    discovered_models: Optional[list[str]] = None,
) -> Tuple[list[tuple[str, str]], str, str]:
    """Return selectable model strategy options and recommended default."""
    models = provider_config.models or {}
    if provider == "codex":
        levels = models.get("thinking_levels", {})
        options = []
        default_desc = {
            "low": _msg(lang, "codex_low_desc"),
            "medium": _msg(lang, "codex_medium_desc"),
            "high": _msg(lang, "codex_high_desc"),
        }
        for key in ("low", "medium", "high"):
            if key in levels:
                if lang == "zh-CN":
                    desc = default_desc.get(key, "")
                else:
                    desc = levels[key].get("description", "") or default_desc.get(key, "")
                options.append((key, f"{key}: {desc}".strip(": ")))
        if not options:
            options = [("high", "high")]
        configured = str(models.get("default_thinking", "high")).strip()
        recommended = configured if any(key == configured for key, _ in options) else "high"
        return options, recommended, _msg(lang, "source_fallback")

    if provider == "claude":
        options = [("default", f"default ({models.get('default', 'claude-sonnet-4-6')})")]
        for key in ("cost_effective", "powerful"):
            cfg = models.get(key, {})
            if isinstance(cfg, dict) and cfg.get("model"):
                options.append((key, f"{key} ({cfg.get('model')})"))
        catalog = models.get("catalog_profiles", {})
        if not isinstance(catalog, dict):
            catalog = {}
        source = _msg(lang, "source_fallback")
        for model_name in discovered_models or []:
            key = f"catalog_{_sanitize_model_key(model_name)}"
            if key not in catalog:
                catalog[key] = {
                    "model": model_name,
                    "flag": f"--model {model_name}",
                    "description": f"catalog ({model_name})",
                }
        if discovered_models:
            source = _msg(lang, "source_slash")
        if catalog:
            models["catalog_profiles"] = catalog
            for key in sorted(catalog.keys()):
                cfg = catalog.get(key, {})
                model_name = cfg.get("model")
                if model_name:
                    options.append((key, f"{key} ({model_name})"))
        configured = str(provider_config.model_selection or "default").strip()
        if not any(k == configured for k, _ in options):
            configured = "cost_effective" if any(k == "cost_effective" for k, _ in options) else "default"
        return options, configured, source

    if provider == "gemini":
        options = [("auto", f"auto ({_msg(lang, 'gemini_auto_desc')})")]
        for key, cfg in models.items():
            if key in {"auto_route_default", "default", "catalog_profiles"}:
                continue
            if isinstance(cfg, dict) and cfg.get("model"):
                options.append((key, f"{key} ({cfg.get('model')})"))
        catalog = models.get("catalog_profiles", {})
        if not isinstance(catalog, dict):
            catalog = {}
        source = _msg(lang, "source_fallback")
        for model_name in discovered_models or []:
            key = f"catalog_{_sanitize_model_key(model_name)}"
            if key not in catalog:
                catalog[key] = {
                    "model": model_name,
                    "flag": f"--model {model_name}",
                    "description": f"catalog ({model_name})",
                }
        if discovered_models:
            source = _msg(lang, "source_slash")
        if catalog:
            models["catalog_profiles"] = catalog
            for key in sorted(catalog.keys()):
                cfg = catalog.get(key, {})
                model_name = cfg.get("model")
                if model_name:
                    options.append((key, f"{key} ({model_name})"))
        if provider_config.model_selection and any(k == provider_config.model_selection for k, _ in options):
            recommended = str(provider_config.model_selection)
        else:
            recommended = "powerful" if any(k == "powerful" for k, _ in options) else "auto"
        return options, recommended, source

    return [("default", "default")], "default", _msg(lang, "source_fallback")


def _ensure_profile_enabled(provider_config, profile_key: str) -> None:
    models = provider_config.models or {}
    raw = models.get("enabled_profiles", [])
    if not isinstance(raw, list):
        raw = []
    if profile_key and profile_key not in raw:
        raw.append(profile_key)
    models["enabled_profiles"] = raw
    provider_config.models = models


def _apply_provider_profile_choice(provider: str, provider_config, profile_key: str) -> None:
    """Apply chosen profile/thinking to provider config."""
    models = provider_config.models or {}
    _ensure_profile_enabled(provider_config, profile_key)

    if provider == "codex":
        provider_config.models["default_thinking"] = profile_key if profile_key in {"low", "medium", "high"} else "high"
        provider_config.model_selection = "default"
        return

    if provider == "gemini":
        if profile_key == "auto":
            provider_config.models["auto_route_default"] = True
            provider_config.model_selection = "default"
        else:
            provider_config.models["auto_route_default"] = False
            provider_config.model_selection = profile_key
            cfg = models.get(profile_key, {})
            if isinstance(cfg, dict) and cfg.get("model"):
                provider_config.models["default"] = cfg["model"]
        return

    if provider == "claude":
        provider_config.model_selection = profile_key
        cfg = models.get(profile_key, {})
        if isinstance(cfg, dict) and cfg.get("model"):
            provider_config.models["default"] = cfg["model"]
        return


def _role_label(item: dict, lang: str) -> str:
    return item["zh"] if lang == "zh-CN" else item["en"]


def _default_profile_label(provider: str, profile_key: str, options: list[tuple[str, str]]) -> str:
    if provider == "codex" and profile_key in {"low", "medium", "high"}:
        return f"gpt-5.4, {profile_key}"
    for key, label in options:
        if key == profile_key:
            return label
    return profile_key


def _auto_orchestration_enabled(auto_cfg: dict) -> bool:
    if "enabled" in auto_cfg:
        return bool(auto_cfg.get("enabled"))
    if "auto_orchestration_enabled" in auto_cfg:
        return bool(auto_cfg.get("auto_orchestration_enabled"))
    return True


def _set_auto_orchestration(auto_cfg: dict, enabled: bool) -> dict:
    updated = dict(auto_cfg)
    updated["enabled"] = bool(enabled)
    # Keep legacy key for backward compatibility with older skills/clients.
    updated["auto_orchestration_enabled"] = bool(enabled)
    return updated


AUTO_COLLAB_I18N = {
    "en-US": {
        "start": "🤝 Starting Collaborative Workflow",
        "workflow": "Route",
        "primary": "Primary",
        "reviewers": "Reviewers",
        "project_categories": "Project Categories",
        "auto_skills": "Auto Skills",
        "plan_title": "Orchestration Plan",
        "mode": "Mode",
        "selected_agents": "Selected Agents",
        "available_agents": "Available Agents",
        "role_assignment": "Role Assignment",
        "tmux_ready": "tmux live orchestration ready",
        "tmux_fallback": "tmux mode unavailable, falling back to direct execution.",
        "tmux_required_abort": "tmux mode was explicitly requested but launch failed. Aborting instead of direct fallback.",
        "tmux_required_unavailable": "tmux mode was explicitly requested, but current orchestration result cannot launch tmux (non-multi-agent or empty plan).",
        "tmux_failed": "Failed to launch tmux controller workspace:",
        "choose_action": "Collaboration detected. Choose action",
        "opt_execute": "Run collaboration workflow",
        "opt_plan": "Show plan only (dry-run)",
        "opt_single": "Run single-provider mode",
        "opt_cancel": "Cancel",
        "opt_tmux": "Launch visual tmux collaboration",
        "single_mode": "Single AI mode - executing with {provider}",
        "direct_runtime_title": "Direct Runtime",
        "direct_result_title": "Direct Result",
        "single_runtime_title": "Single Runtime",
        "status_label": "Status",
        "workflow_label": "Workflow",
        "provider_label": "Provider",
        "phases_label": "Phases",
        "skipped_label": "Skipped",
        "exit_code_label": "Exit Code",
        "reason_label": "Reason",
        "result_completed": "completed",
        "result_completed_with_skips": "completed with skips",
        "result_failed": "failed",
        "result_aborted_by_user": "aborted by user",
        "result_timeout": "timed out",
        "suggested_skills": "Suggested Skills",
        "single_continue": "Single-provider execution. Continue?",
        "controller_title": "Controller task briefing:",
        "subagent_title": "Sub-agent task briefing:",
        "brief_user_task": "User task",
        "brief_roles": "Your roles",
        "brief_assigned_roles": "Assigned roles",
        "brief_delegate": "Coordinate sub-agents and merge results.",
        "brief_end": "End with: === TASK_COMPLETE ===",
        "brief_plan_pending": "Pending delegation plan (spawn sub-agents only when needed):",
        "brief_return": "Return concise outputs for each role.",
        "wizard_provider": "Choose controller agent",
        "wizard_mode": "Choose execution mode",
        "wizard_task": "Enter task",
        "brief_saved": "Briefing file saved: {path}",
        "controller_doc_saved": "Controller prompt doc saved: {path}",
        "controller_doc_title": "Controller Prompt Draft",
        "controller_doc_send": "Send this prompt to controller now?",
        "controller_doc_editor_missing": "No editor found (set $EDITOR or install nano/vim).",
        "controller_doc_opened": "Opened in editor: {editor}",
        "controller_doc_open_failed": "Failed to open editor ({editor}): {error}",
        "controller_doc_action": "Prompt document action",
        "controller_doc_opt_send": "Send prompt",
        "controller_doc_opt_edit": "Edit prompt",
        "controller_doc_opt_cancel": "Cancel",
        "controller_plan_title": "Controller Plan JSON",
        "controller_plan_failed": "Controller-first planning failed. Falling back to built-in plan.",
        "controller_plan_confirm": "Approve this controller plan?",
        "controller_plan_skip": "Controller plan not approved. Aborting.",
        "controller_plan_request_failed": "Failed to request controller plan: {error}",
        "controller_plan_fallback_confirm": "Controller planning failed. Continue with built-in fallback plan?",
        "controller_plan_fallback_abort": "Fallback plan declined. Aborting.",
        "controller_plan_generating": "Generating orchestration plan from controller AI...",
        "controller_plan_adjust": "Adjust model/roles/persona/skills before approval?",
        "controller_plan_adjusted": "Applied orchestration adjustment notes from: {path}",
        "available_agents_only": "Available Agents",
        "tmux_logs": "Pane logs: {path}",
        "tmux_session_renamed": "Session '{old}' is active; using '{new}' to preserve existing run.",
        "prompt_inject_failed": "Prompt injection may have failed for {agent} (pane={pane}). Check pane/logs and resend if needed.",
        "watcher_skipped": "Handoff watcher skipped because controller prompt was not injected successfully.",
    },
    "zh-CN": {
        "start": "🤝 启动多 AI 协作流程",
        "workflow": "编排路由",
        "primary": "主导 Agent",
        "reviewers": "审查 Agent",
        "project_categories": "项目分类",
        "auto_skills": "自动技能",
        "plan_title": "编排计划",
        "mode": "执行模式",
        "selected_agents": "已选 Agent",
        "available_agents": "可用 Agent",
        "role_assignment": "角色分工",
        "tmux_ready": "tmux 协作会话已就绪",
        "tmux_fallback": "tmux 模式不可用，回退到直接执行。",
        "tmux_required_abort": "你已显式选择 tmux，但启动失败；已停止执行，不再回退到 direct。",
        "tmux_required_unavailable": "你已显式选择 tmux，但当前编排结果不满足 tmux 启动条件（非多 Agent 或计划为空）。",
        "tmux_failed": "启动 tmux 主控工作区失败：",
        "choose_action": "检测到协作任务，选择动作",
        "opt_execute": "执行协作流程",
        "opt_plan": "仅查看计划（dry-run）",
        "opt_single": "单 Agent 执行",
        "opt_cancel": "取消",
        "opt_tmux": "启动 tmux 可视化协作",
        "single_mode": "单 Agent 模式 - 使用 {provider} 执行",
        "direct_runtime_title": "Direct 运行",
        "direct_result_title": "Direct 结果",
        "single_runtime_title": "单 Agent 运行",
        "status_label": "状态",
        "workflow_label": "工作流",
        "provider_label": "Provider",
        "phases_label": "阶段",
        "skipped_label": "跳过",
        "exit_code_label": "退出码",
        "reason_label": "原因",
        "result_completed": "已完成",
        "result_completed_with_skips": "已完成（含跳过）",
        "result_failed": "失败",
        "result_aborted_by_user": "用户中止",
        "result_timeout": "超时",
        "suggested_skills": "建议技能",
        "single_continue": "单 Agent 执行，是否继续？",
        "controller_title": "主控任务简报：",
        "subagent_title": "子 Agent 任务简报：",
        "brief_user_task": "用户任务",
        "brief_roles": "你的角色",
        "brief_assigned_roles": "分配角色",
        "brief_delegate": "按需创建子 Agent 并汇总结果。",
        "brief_end": "结束标记：=== TASK_COMPLETE ===",
        "brief_plan_pending": "待分配计划（仅在需要时再创建子窗格）：",
        "brief_return": "按角色返回精简结果。",
        "wizard_provider": "请选择主控 Agent",
        "wizard_mode": "请选择执行模式",
        "wizard_task": "请输入任务",
        "brief_saved": "简报文件已写入: {path}",
        "controller_doc_saved": "主控提示词文档已写入: {path}",
        "controller_doc_title": "主控 Prompt 草案",
        "controller_doc_send": "是否将该提示词发送给主控 Agent？",
        "controller_doc_editor_missing": "未找到编辑器（请设置 $EDITOR 或安装 nano/vim）。",
        "controller_doc_opened": "已打开编辑器: {editor}",
        "controller_doc_open_failed": "打开编辑器失败 ({editor}): {error}",
        "controller_doc_action": "提示词文档操作",
        "controller_doc_opt_send": "发送提示词",
        "controller_doc_opt_edit": "编辑提示词",
        "controller_doc_opt_cancel": "取消",
        "controller_plan_title": "主控计划 JSON",
        "controller_plan_failed": "主控先规划失败，回退到内置分工。",
        "controller_plan_confirm": "是否同意该主控计划？",
        "controller_plan_skip": "未同意主控计划，流程已取消。",
        "controller_plan_request_failed": "请求主控计划失败: {error}",
        "controller_plan_fallback_confirm": "主控先规划失败，是否继续使用内置回退方案？",
        "controller_plan_fallback_abort": "你已拒绝回退方案，流程已取消。",
        "controller_plan_generating": "正在请求主控 AI 生成编排计划...",
        "controller_plan_adjust": "在确认前是否调整模型/分工/persona/skills？",
        "controller_plan_adjusted": "已应用编排调整备注: {path}",
        "available_agents_only": "可用 Agent",
        "tmux_logs": "窗格日志: {path}",
        "tmux_session_renamed": "检测到会话 '{old}' 正在运行，为保留历史会话改用 '{new}'。",
        "prompt_inject_failed": "向 {agent} 注入提示词可能失败（pane={pane}），请检查窗格/日志后重发。",
        "watcher_skipped": "由于主控提示词注入失败，已跳过自动交接监听器。",
    },
}


def _auto_msg(lang: str, key: str, **kwargs: str) -> str:
    table = AUTO_COLLAB_I18N.get(lang, AUTO_COLLAB_I18N["en-US"])
    text = table.get(key, AUTO_COLLAB_I18N["en-US"].get(key, key))
    return text.format(**kwargs)


def _result_workflow_label(result: Any) -> str:
    blueprint = str(getattr(result, "workflow_blueprint", "") or "").strip()
    session_preset = str(getattr(result, "session_preset", "") or "").strip()
    if blueprint and session_preset:
        return f"{blueprint} [{session_preset}]"
    if blueprint:
        return blueprint
    return session_preset


def _set_last_direct_runtime_error(message: str) -> None:
    global _LAST_DIRECT_RUNTIME_ERROR
    _LAST_DIRECT_RUNTIME_ERROR = str(message or "").strip()


def _last_direct_runtime_error() -> str:
    return _LAST_DIRECT_RUNTIME_ERROR


def _summarize_runtime_failure_text(text: str, *, limit: int = 280) -> str:
    cleaned_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = ANSI_ESCAPE_RE.sub("", raw_line).strip()
        line = LIVE_PREFIX_RE.sub("", line).strip()
        if line:
            cleaned_lines.append(line)
    if not cleaned_lines:
        return ""
    summary = " | ".join(cleaned_lines[-3:])
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "…"


def _print_runtime_overview(
    *,
    title: str,
    lang: str,
    mode: str,
    provider: str,
    task: str,
    result: Any | None = None,
    controller_plan: Optional[dict[str, Any]] = None,
) -> None:
    """Print a tmux-aligned runtime summary before execution starts."""
    rows = [
        (_auto_msg(lang, "mode"), mode),
        (_auto_msg(lang, "primary"), provider),
    ]
    if result is not None:
        workflow_label = _result_workflow_label(result)
        if workflow_label:
            rows.append((_auto_msg(lang, "workflow"), workflow_label))
        reviewers = getattr(result, "reviewers", None) or []
        if reviewers:
            rows.append((_auto_msg(lang, "reviewers"), ", ".join(reviewers)))
        categories = getattr(result, "project_categories", None) or []
        if categories:
            rows.append((_auto_msg(lang, "project_categories"), ", ".join(categories)))
        skills = getattr(result, "suggested_skills", None) or []
        if skills:
            rows.append((_auto_msg(lang, "auto_skills"), ", ".join(skills)))

    lines = [f"task: {task}"]
    if controller_plan:
        steps = controller_plan.get("steps", [])
        if isinstance(steps, list) and steps:
            lines.append(f"approved_steps: {len(steps)}")
    console.print()
    console.print(render_tmux_block(title, rows=rows, lines=lines))


def _runtime_result_text(lang: str, status: str) -> str:
    normalized = str(status or "").strip().lower() or "completed"
    return _auto_msg(lang, f"result_{normalized}")


def _print_direct_result_summary(
    *,
    lang: str,
    status: str,
    provider: str,
    summary: Optional[dict[str, Any]] = None,
    exit_code: Optional[int] = None,
    reason: str = "",
) -> None:
    """Print a tmux-style completion block for direct runtime."""
    rows = [
        (_auto_msg(lang, "status_label"), _runtime_result_text(lang, status)),
        (_auto_msg(lang, "provider_label"), provider),
    ]
    lines: list[str] = []
    if summary:
        workflow = str(summary.get("workflow", "")).strip()
        if workflow:
            rows.append((_auto_msg(lang, "workflow_label"), workflow))
        total = int(summary.get("total_phases", 0) or 0)
        completed = int(summary.get("completed_phases", 0) or 0)
        if total > 0:
            rows.append((_auto_msg(lang, "phases_label"), f"{completed}/{total}"))
        skipped = int(summary.get("skipped_phases", 0) or 0)
        if skipped > 0:
            rows.append((_auto_msg(lang, "skipped_label"), str(skipped)))
        for key in ("workflow_engine", "session_preset", "workflow_blueprint"):
            value = str(summary.get(key, "")).strip()
            if value:
                lines.append(f"{key}: {value}")
        if not reason:
            failure_phase = str(summary.get("failure_phase", "")).strip()
            failure_reason = _summarize_runtime_failure_text(summary.get("failure_reason", ""))
            if failure_phase and failure_reason:
                reason = f"{failure_phase}: {failure_reason}"
            elif failure_reason:
                reason = failure_reason
    if exit_code is not None:
        rows.append((_auto_msg(lang, "exit_code_label"), str(exit_code)))
    if reason:
        rows.append((_auto_msg(lang, "reason_label"), reason))
    _set_last_direct_runtime_error(reason)
    console.print()
    console.print(render_tmux_block(_auto_msg(lang, "direct_result_title"), rows=rows, lines=lines))


def _ask_text_input(prompt: str, *, questionary_module, default_value: str = "") -> str:
    """Prompt a free-form text value in TUI/text mode."""
    if questionary_module:
        value = questionary_module.text(prompt, default=default_value).ask()
        if value is None:
            raise click.Abort()
        return str(value).strip()
    return Prompt.ask(prompt, default=default_value).strip()


def _collect_runner_inputs(
    *,
    args,
    provider_prefix: Optional[str],
    default_provider: str,
    default_mode: str,
    providers: list[str],
    lang: str,
    decision_ui,
) -> tuple[str, str, str]:
    """
    Collect provider/mode/task.

    If task is provided in CLI args, reuse it; otherwise enter interactive 3-step flow.
    """
    raw_task_positional = " ".join(getattr(args, "task", [])).strip()
    raw_task_option = str(getattr(args, "prompt", "") or "").strip()
    if raw_task_positional and raw_task_option:
        raise SystemExit("Use either positional task or --prompt, not both.")
    raw_task = raw_task_option or raw_task_positional
    provider = provider_prefix or args.provider or default_provider
    mode = str(getattr(args, "execution_mode", "") or default_mode)

    if raw_task:
        return provider, mode, raw_task

    if not sys.stdin.isatty():
        raise SystemExit("Task is required in non-interactive mode.")

    provider_choices = [(name, _provider_display_plain(name)) for name in providers]
    provider = _select_decision(
        _auto_msg(lang, "wizard_provider"),
        provider_choices,
        questionary_module=decision_ui,
        default_value=provider,
        provider=provider,
    )
    mode = _select_decision(
        _auto_msg(lang, "wizard_mode"),
        [
            ("tmux", "tmux"),
            ("auto", "auto"),
            ("direct", "direct"),
        ],
        questionary_module=decision_ui,
        default_value=default_mode if default_mode in {"tmux", "auto", "direct"} else "tmux",
        provider=provider,
    )
    raw_task = _ask_text_input(_auto_msg(lang, "wizard_task"), questionary_module=decision_ui, default_value="")
    if not raw_task:
        raise SystemExit("Task cannot be empty.")
    return provider, mode, raw_task


def _write_briefing_file(*, cwd: Path, role: str, agent: str, text: str) -> Path:
    """Persist generated briefing text for traceability and manual fallback."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = cwd / ".ai-collab" / "briefings"
    folder.mkdir(parents=True, exist_ok=True)
    safe_agent = re.sub(r"[^a-zA-Z0-9_-]", "-", agent) or "agent"
    safe_role = re.sub(r"[^a-zA-Z0-9_-]", "-", role) or "role"
    path = folder / f"{timestamp}-{safe_agent}-{safe_role}.txt"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _write_controller_prompt_file(*, cwd: Path, controller: str, text: str) -> Path:
    """Write controller prompt draft for optional manual edits."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = cwd / ".ai-collab" / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{timestamp}-{controller}-controller-prompt.md"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _build_prompt_dispatch_message(*, lang: str, path: Path, role: str, agent: str) -> str:
    """Build a short prompt that asks agent to read briefing file."""
    if lang == "zh-CN":
        return f"读取并执行任务文件：{path}"
    return f"Read and execute task file: {path}"


def _resolve_editor_command() -> Optional[list[str]]:
    """Resolve preferred editor command."""
    candidates: list[str] = []
    editor_raw = os.environ.get("EDITOR", "").strip()
    if editor_raw:
        candidates.append(editor_raw)
    candidates.extend(["nano", "vim", "vi"])

    for candidate in candidates:
        try:
            parts = shlex.split(candidate)
        except ValueError:
            continue
        if parts and shutil.which(parts[0]):
            return parts
    return None


def _open_file_in_editor(*, path: Path, lang: str) -> bool:
    """Open file in user editor and return whether it succeeded."""
    editor_cmd = _resolve_editor_command()
    if not editor_cmd:
        console.print(f"[yellow]{_auto_msg(lang, 'controller_doc_editor_missing')}[/yellow]")
        return False
    try:
        subprocess.run([*editor_cmd, str(path)], check=False)
        console.print(
            f"[dim]{_auto_msg(lang, 'controller_doc_opened', editor=' '.join(editor_cmd))}[/dim]"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"[yellow]{_auto_msg(lang, 'controller_doc_open_failed', editor=' '.join(editor_cmd), error=str(exc))}[/yellow]"
        )
        return False


def _resolve_v2_prompt_defaults(config: Optional[Config]) -> tuple[str, str]:
    """Resolve V2 prompt defaults without breaking legacy runtime defaults."""
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


def _build_v2_steps_json(
    *,
    blueprint_key: str,
    role_leads: dict[str, str],
    controller: str,
    lang: str,
) -> str:
    """Build a JSON representation of the blueprint stages for the prompt example."""
    try:
        blueprint = resolve_workflow_blueprint(blueprint_key)
    except KeyError:
        return "[]"

    is_zh = lang == "zh-CN"
    steps = []

    # Map blueprint agent IDs to actual agent names from role_leads
    agent_map = {
        "codex": role_leads.get("implementation", controller),
        "gemini": role_leads.get("architecture", controller),
        "claude": role_leads.get("testing", controller),
    }

    for idx, stage in enumerate(blueprint.stages, 1):
        owner = agent_map.get(stage.default_agent, controller) if stage.default_agent else controller

        steps.append({
            "id": f"S{idx}",
            "owner": owner,
            "goal": stage.goal,
            "input": "..." if not is_zh else "...",
            "output": ", ".join(stage.outputs) if stage.outputs else "...",
            "done_when": f"Complete {stage.key} with required outputs" if not is_zh else f"完成 {stage.key} 并产出必要输出",
            "eta_minutes": stage.timebox_minutes or 15,
            "responsibility_stage": stage.responsibility_stage,
            "artifact_type": stage.allowed_artifacts[0] if stage.allowed_artifacts else (stage.outputs[0] if stage.outputs else "none"),
            "boundary": stage.boundary,
            "timebox_minutes": stage.timebox_minutes or 15,
        })

    return json.dumps(steps, indent=4, ensure_ascii=False)


def _build_controller_prompt_document(
    *,
    task: str,
    controller: str,
    result,
    config: Config,
    lang: str,
) -> str:
    """Build the long-form controller prompt document for tmux mode."""
    is_zh = lang == "zh-CN"
    available = result.available_agents or []
    plan = result.orchestration_plan or []

    auto_cfg = config.auto_collaboration or {}
    persona_phase_map = auto_cfg.get("persona_phase_map", {}) if isinstance(auto_cfg, dict) else {}
    persona_skill_map = auto_cfg.get("persona_skill_map", {}) if isinstance(auto_cfg, dict) else {}
    role_leads = resolve_collaboration_role_leads(config)
    architecture_lead = role_leads.get("architecture", "gemini")
    implementation_lead = role_leads.get("implementation", "codex")
    testing_lead = role_leads.get("testing", "claude")
    session_preset, workflow_blueprint = _resolve_v2_prompt_defaults(config)

    roster_lines: list[str] = []
    for item in available:
        roster_lines.append(
            "- {agent}: model={model}, profile={profile}, strengths={strengths}".format(
                agent=item.get("agent", ""),
                model=item.get("selected_model", ""),
                profile=item.get("model_profile", ""),
                strengths=item.get("strengths", ""),
            )
        )
    roster_text = "\n".join(roster_lines) if roster_lines else "- (none)"

    plan_lines: list[str] = []
    for idx, step in enumerate(plan, 1):
        plan_lines.append(
            f"{idx}. role={step.get('role', '')}, agent={step.get('agent', '')}, model={step.get('selected_model', '')}, reason={step.get('reason', '')}"
        )
    plan_text = "\n".join(plan_lines) if plan_lines else "1. role=implementation, agent={0}".format(controller)

    persona_phase_lines: list[str] = []
    for phase_name, persona_name in persona_phase_map.items():
        persona_phase_lines.append(f"- {phase_name} -> {persona_name}")
    persona_phase_text = "\n".join(persona_phase_lines) if persona_phase_lines else "- (none)"

    persona_skill_lines: list[str] = []
    for persona_name, skills in persona_skill_map.items():
        joined = ", ".join(skills) if isinstance(skills, list) else str(skills)
        persona_skill_lines.append(f"- {persona_name}: {joined}")
    persona_skill_text = "\n".join(persona_skill_lines) if persona_skill_lines else "- (none)"
    policy_lines = [
        f"- {'方案选项 / 技术骨架 / 架构取舍' if is_zh else 'Options / technical skeleton / architecture trade-offs'}: {architecture_lead}",
        f"- {'主实现 / 跨文件编码 / 问题修复' if is_zh else 'Main implementation / cross-file coding / bug fixing'}: {implementation_lead}",
        f"- {'验收 / 回归测试 / 质量审查 / 补充修改' if is_zh else 'Acceptance / regression testing / quality review / follow-up fixes'}: {testing_lead}",
    ]
    policy_text = "\n".join(policy_lines)

    # Generate dynamic steps JSON based on the selected blueprint
    dynamic_steps_json = _build_v2_steps_json(
        blueprint_key=workflow_blueprint,
        role_leads=role_leads,
        controller=controller,
        lang=lang,
    )

    if is_zh:
        return f"""# 主控 Agent 执行文档（可编辑）

你是主控 Agent：`{controller}`。请严格根据下列配置进行编排，不要猜测不存在的 Agent 或模型。

## 用户任务
{task}

## 可用 Agent 与模型（来自配置）
{roster_text}

## 预设 Persona（来自配置）
### phase -> persona
{persona_phase_text}

### persona -> skills
{persona_skill_text}

## 建议角色分配（来自系统初始规划）
{plan_text}

## 当前协作偏好（优先遵守）
{policy_text}
- 不要因为当前 controller 是 {controller} 就默认把所有编码步骤都交给 {controller}；只有在任务明显不需要某个角色时，才可以省略该角色。

## 你的输出要求（第一步）
请先输出一个 JSON（只输出 JSON，不要额外解释），结构如下：
```json
{{
  "plan_version": "1.0",
  "workflow_engine": "v2",
  "session_preset": "{session_preset}",
  "workflow_blueprint": "{workflow_blueprint}",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "{architecture_lead}", "model": "unknown", "persona": "options-architect", "why": "负责方案选项、技术骨架与架构取舍" }},
    {{"name": "{implementation_lead}", "model": "unknown", "persona": "implementation-lead", "why": "负责主实现与跨文件修改" }},
    {{"name": "{testing_lead}", "model": "unknown", "persona": "quality-reviewer", "why": "负责验收、测试设计与补充修补" }}
  ],
  "steps": {dynamic_steps_json},
  "approval_question": "是否同意该计划？"
}}
```

## 执行协议（第二步）
1. 在用户明确同意计划前，不要开始执行步骤。
2. 用户同意后，按 `steps` 顺序逐步执行。
3. 子 Agent 调度必须在 tmux 可视窗格中进行，禁止在主控后台 shell 里直接调用 claude/gemini。
4. 需要切换执行者时，输出 `HANDOFF_TO: <agent>` 或 `SPAWN_AGENT: <agent>` 以触发可视窗格。
5. 禁止使用 `--help` / `-h` / `--version` 或自定义探活脚本检查 Agent；直接执行当前步骤。
6. 若命令遇到权限/审批拦截，先输出 `NEED_ELEVATION: <command> | reason=<error>`，等待用户处理，不得静默降级。
7. 每步完成后输出：
   - `STEP_DONE: <id>`
   - `HANDOFF_TO: <next_owner>`
   - 简短结果摘要
8. 全部结束后输出 `=== TASK_COMPLETE ===`。
9. 如果 step 含有 `responsibility_stage` / `artifact_type` / `boundary` / `timebox_minutes`，必须按这些字段理解步骤边界。
10. collect 阶段只负责现状采集；validate 阶段只负责验收与风险识别；超出边界的问题要交回 correct 阶段。
"""

    return f"""# Controller Execution Doc (Editable)

You are the controller agent: `{controller}`. Use only the configured agents/models below.

## User Task
{task}

## Available Agents and Models (from config)
{roster_text}

## Preset Personas (from config)
### phase -> persona
{persona_phase_text}

### persona -> skills
{persona_skill_text}

## Suggested Initial Role Plan (system draft)
{plan_text}

## Current Collaboration Preference (prefer this split)
{policy_text}
- Do not assign every coding step to {controller} just because the current controller is {controller}; only omit a role when the task genuinely does not need it.

## Output Requirement (Step 1)
First, return JSON only (no extra explanation) using this schema:
```json
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
  "steps": {dynamic_steps_json},
  "approval_question": "Do you approve this plan?"
}}
```

## Execution Protocol (Step 2)
1. Do not execute steps before user approval.
2. After approval, execute steps in order.
3. Sub-agent execution must stay visible in tmux panes. Do not run claude/gemini through hidden background shell commands in controller pane.
4. When switching owner, output `HANDOFF_TO: <agent>` or `SPAWN_AGENT: <agent>` to trigger visible panes.
5. Do not run provider probes such as `--help` / `-h` / `--version` or custom health scripts before execution; execute assigned steps directly.
6. If any command is blocked by permissions/approval, output `NEED_ELEVATION: <command> | reason=<error>` and wait; do not silently downgrade.
7. After each step output:
   - `STEP_DONE: <id>`
   - `HANDOFF_TO: <next_owner>`
   - short result summary
8. End with `=== TASK_COMPLETE ===`.
9. If a step includes `responsibility_stage` / `artifact_type` / `boundary` / `timebox_minutes`, treat those fields as binding step boundaries.
10. Collect is for evidence, validate is for acceptance/risk, and bounded issues should be handed back to a correct stage.
"""


def _prepare_controller_prompt_document(
    *,
    task: str,
    controller: str,
    result,
    config: Config,
    lang: str,
    decision_ui,
    interactive: bool,
    edit_prompt: bool,
    prompt_text_override: Optional[str] = None,
) -> Optional[str]:
    """Generate/edit/confirm controller prompt doc. Return final prompt or None if canceled."""
    prompt_text = prompt_text_override or _build_controller_prompt_document(
        task=task,
        controller=controller,
        result=result,
        config=config,
        lang=lang,
    )
    prompt_file = _write_controller_prompt_file(
        cwd=Path.cwd(),
        controller=controller,
        text=prompt_text,
    )
    console.print(f"[dim]{_auto_msg(lang, 'controller_doc_saved', path=str(prompt_file))}[/dim]")

    if interactive and edit_prompt:
        _open_file_in_editor(path=prompt_file, lang=lang)

    if interactive:
        while True:
            action = _select_decision(
                _auto_msg(lang, "controller_doc_action"),
                [
                    ("send", _auto_msg(lang, "controller_doc_opt_send")),
                    ("edit", _auto_msg(lang, "controller_doc_opt_edit")),
                    ("cancel", _auto_msg(lang, "controller_doc_opt_cancel")),
                ],
                questionary_module=decision_ui,
                default_value="send",
                provider=controller,
            )
            if action == "cancel":
                return None
            if action == "edit":
                _open_file_in_editor(path=prompt_file, lang=lang)
                continue
            break

    return prompt_file.read_text(encoding="utf-8").strip()


def _build_controller_planning_request(
    *,
    task: str,
    controller: str,
    result,
    config: Config,
    lang: str,
) -> str:
    """Build a single message asking controller to return JSON plan only."""
    is_zh = lang == "zh-CN"
    available = result.available_agents or []
    auto_cfg = config.auto_collaboration or {}
    persona_phase_map = auto_cfg.get("persona_phase_map", {}) if isinstance(auto_cfg, dict) else {}
    persona_skill_map = auto_cfg.get("persona_skill_map", {}) if isinstance(auto_cfg, dict) else {}
    role_leads = resolve_collaboration_role_leads(config)
    architecture_lead = role_leads.get("architecture", "gemini")
    implementation_lead = role_leads.get("implementation", "codex")
    testing_lead = role_leads.get("testing", "claude")
    session_preset, workflow_blueprint = _resolve_v2_prompt_defaults(config)

    roster_lines: list[str] = []
    for item in available:
        roster_lines.append(
            "- {agent}: model={model}, profile={profile}, strengths={strengths}".format(
                agent=item.get("agent", ""),
                model=item.get("selected_model", ""),
                profile=item.get("model_profile", ""),
                strengths=item.get("strengths", ""),
            )
        )
    roster_text = "\n".join(roster_lines) if roster_lines else "- (none)"

    persona_phase_lines = [f"- {phase}: {persona}" for phase, persona in persona_phase_map.items()]
    persona_skill_lines = [
        f"- {persona}: {', '.join(skills) if isinstance(skills, list) else skills}"
        for persona, skills in persona_skill_map.items()
    ]
    persona_phase_text = "\n".join(persona_phase_lines) if persona_phase_lines else "- (none)"
    persona_skill_text = "\n".join(persona_skill_lines) if persona_skill_lines else "- (none)"
    policy_text = "\n".join(
        [
            f"- {'方案选项 / 技术骨架 / 架构取舍' if is_zh else 'Options / technical skeleton / architecture trade-offs'}：{architecture_lead}",
            f"- {'主实现 / 跨文件编码 / 问题修复' if is_zh else 'Main implementation / cross-file coding / bug fixing'}：{implementation_lead}",
            f"- {'验收 / 回归测试 / 质量审查 / 补充修改' if is_zh else 'Acceptance / regression testing / quality review / follow-up fixes'}：{testing_lead}",
        ]
    )

    if is_zh:
        return f"""你是主控 Agent：{controller}。
请只根据以下配置生成执行计划，不要编造不存在的 Agent 或模型。

用户任务:
{task}

可用 Agent 与模型:
{roster_text}

persona_phase_map:
{persona_phase_text}

persona_skill_map:
{persona_skill_text}

当前协作偏好（优先遵守）:
{policy_text}
- 不要因为当前 controller 是 {controller} 就默认把所有编码步骤都交给 {controller}；只有在任务明显不需要某个角色时，才可以省略该角色。

只返回 JSON，不要 markdown，不要解释。字段要求:
{{
  "plan_version": "1.0",
  "workflow_engine": "v2",
  "session_preset": "{session_preset}",
  "workflow_blueprint": "{workflow_blueprint}",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "{architecture_lead}", "model": "unknown", "persona": "options-architect", "why": "负责方案选项、技术骨架与架构取舍" }},
    {{"name": "{implementation_lead}", "model": "unknown", "persona": "implementation-lead", "why": "负责主实现与跨文件修改" }},
    {{"name": "{testing_lead}", "model": "unknown", "persona": "quality-reviewer", "why": "负责验收、测试设计与补充修补" }}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "{architecture_lead}",
      "goal": "收集现状并明确方案方向",
      "input": "用户任务 + 配置",
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
  "approval_question": "是否同意该计划？"
}}

额外约束（必须写入计划并执行）:
- workflow_engine 固定为 `v2`；session_preset 与 workflow_blueprint 必须和当前任务匹配。
- responsibility_stage 必须使用阶段职责，而不是直接写 Agent 名称；取值只能是 collect / model / plan / artifact / execute / validate / correct / deliver。
- 如果任务需要 mockup / contract / skeleton，可新增 artifact 阶段；如果 validate 发现边界内问题，可新增 correct 阶段。
- 子 Agent 必须在 tmux 可视窗格执行，禁止后台 shell 调用 claude/gemini。
- 交接时必须输出 `HANDOFF_TO: <agent>` 或 `SPAWN_AGENT: <agent>`。
- 禁止先运行 `--help` / `-h` / `--version` 或任何探活脚本；必须直接执行分配步骤。
- 禁止读取 `cli.py` / `SKILL.md` / 搜索源码来确认参数；直接使用命令合同。
- 若要求真实子 Agent 测试，禁止使用 `--agent-cmd` shell 模拟（例如 sleep/echo）。
- 若命令被权限/审批拦截，先输出 `NEED_ELEVATION: <command> | reason=<error>` 并等待，不得静默降级。

ai-collab 命令合同（直接使用）:
- `ai-collab tmux-status --json-output`
- `ai-collab handoff --agent <gemini|claude|codex> --tmux-layout split --split-policy controller-bottom --controller-pane <pane_id> --repo-root <repo> --prompt '<任务>' --completion-action keep --no-ask-launch-options`
- `ai-collab tmux-watch --pane-id <pane_id> --timeout-seconds <n> --json-output`
- `ai-collab tmux-close-pane --pane-id <pane_id>`

监控与故障处理策略（必须执行）:
- 先短超时监控；若 `timeout/still_running`，按回退序列重试（例如 30s -> 60s -> 90s）。
- 若 `tmux-watch` 返回 `error/model_capacity_exhausted`：优先切换该 Agent 的备选模型并重试；仍失败再切换备选 Agent。
- 若 `error/network_error`：先退避重试（例如 10s/20s/40s）；连续失败再切模型或切 Agent。
- 若子 Agent 已完成部分步骤，重派时只继续未完成步骤，不得整任务重做。
"""

    return f"""You are the controller agent: {controller}.
Use only the configuration below. Do not invent unavailable agents/models.

User task:
{task}

Available agents and models:
{roster_text}

persona_phase_map:
{persona_phase_text}

persona_skill_map:
{persona_skill_text}

Current collaboration preference (prefer this split):
{policy_text}
- Do not assign every coding step to {controller} just because the current controller is {controller}; only omit a role when the task genuinely does not need it.

Return JSON only (no markdown, no explanation) with this schema:
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
      "goal": "collect context and define the technical direction",
      "input": "user task + config",
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
      "goal": "deliver the main implementation",
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
      "goal": "run acceptance and follow-up fixes",
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
  "approval_question": "Do you approve this plan?"
}}

Mandatory constraints:
- workflow_engine must stay `v2`, and session_preset / workflow_blueprint must be a sensible fit for the task.
- responsibility_stage must describe stage intent, not an agent name; allowed values are collect / model / plan / artifact / execute / validate / correct / deliver.
- Add an artifact stage when the task needs mockup / contract / skeleton work, and add a correct stage when validation finds bounded issues.
- Sub-agents must run in visible tmux panes. Do not call claude/gemini via hidden background shell commands.
- On handoff, output `HANDOFF_TO: <agent>` or `SPAWN_AGENT: <agent>`.
- Do not run probe commands such as `--help` / `-h` / `--version` or ad-hoc health scripts before execution.
- Do not read `cli.py` / `SKILL.md` / source search results to discover parameters; use the command contract directly.
- If real sub-agent validation is required, do not use `--agent-cmd` shell simulation (`sleep/echo`).
- If any command is blocked by permission/approval, output `NEED_ELEVATION: <command> | reason=<error>` and wait (no silent downgrade).

ai-collab command contract (use directly):
- `ai-collab tmux-status --json-output`
- `ai-collab handoff --agent <gemini|claude|codex> --tmux-layout split --split-policy controller-bottom --controller-pane <pane_id> --repo-root <repo> --prompt '<task>' --completion-action keep --no-ask-launch-options`
- `ai-collab tmux-watch --pane-id <pane_id> --timeout-seconds <n> --json-output`
- `ai-collab tmux-close-pane --pane-id <pane_id>`

Monitoring and failure policy (mandatory):
- Start with short watch timeout; if `timeout/still_running`, retry with backoff sequence (for example 30s -> 60s -> 90s).
- If `tmux-watch` returns `error/model_capacity_exhausted`: switch to the same agent's backup model first; if still failing, switch to backup agent.
- If `error/network_error`: retry with backoff first (for example 10s/20s/40s); only then switch model/agent.
- If sub-agent already completed some steps, re-dispatch only unfinished steps (no full-task redo).
"""


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """Extract first JSON object from arbitrary text."""
    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _controller_plan_schema() -> dict[str, Any]:
    """Structured output schema for controller planning."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "plan_version": {"type": "string"},
            "workflow_engine": {"type": ["string", "null"]},
            "session_preset": {"type": ["string", "null"]},
            "workflow_blueprint": {"type": ["string", "null"]},
            "controller": {"type": "string"},
            "requires_multi_agent": {"type": "boolean"},
            "agents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "model": {"type": "string"},
                        "persona": {"type": "string"},
                        "why": {"type": "string"},
                    },
                    "required": ["name", "model", "persona", "why"],
                },
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "owner": {"type": "string"},
                        "goal": {"type": "string"},
                        "input": {"type": "string"},
                        "output": {"type": "string"},
                        "done_when": {"type": "string"},
                        "eta_minutes": {"type": "integer"},
                        "responsibility_stage": {"type": ["string", "null"]},
                        "artifact_type": {"type": ["string", "null"]},
                        "boundary": {"type": ["string", "null"]},
                        "timebox_minutes": {"type": ["integer", "null"]},
                    },
                    "required": [
                        "id",
                        "owner",
                        "goal",
                        "input",
                        "output",
                        "done_when",
                        "eta_minutes",
                        "responsibility_stage",
                        "artifact_type",
                        "boundary",
                        "timebox_minutes",
                    ],
                },
            },
            "approval_question": {"type": "string"},
        },
        "required": [
            "plan_version",
            "workflow_engine",
            "session_preset",
            "workflow_blueprint",
            "controller",
            "requires_multi_agent",
            "agents",
            "steps",
            "approval_question",
        ],
    }


def _drop_args(parts: list[str], names: tuple[str, ...], takes_value: bool) -> list[str]:
    """Remove matching option tokens from a CLI argv list."""
    cleaned: list[str] = []
    idx = 0
    while idx < len(parts):
        token = parts[idx]
        if token in names:
            idx += 1
            if takes_value and idx < len(parts) and not parts[idx].startswith("-"):
                idx += 1
            continue
        if any(token.startswith(f"{name}=") for name in names):
            idx += 1
            continue
        cleaned.append(token)
        idx += 1
    return cleaned


def _build_controller_plan_schema_text() -> str:
    """Serialize planner schema for providers that accept inline JSON schema."""
    return json.dumps(_controller_plan_schema(), ensure_ascii=False, separators=(",", ":"))


def _set_or_append_arg(parts: list[str], names: tuple[str, ...], value: Optional[str] = None) -> list[str]:
    """Replace first matching CLI option or append it when absent."""
    updated = list(parts)
    for idx, token in enumerate(updated):
        if token in names:
            if value is None:
                return updated
            if idx + 1 >= len(updated):
                updated.append(value)
            elif updated[idx + 1].startswith("-"):
                updated.insert(idx + 1, value)
            else:
                updated[idx + 1] = value
            return updated
        for name in names:
            prefix = f"{name}="
            if token.startswith(prefix):
                if value is None:
                    return updated
                updated[idx] = f"{prefix}{value}"
                return updated
    updated.append(names[0])
    if value is not None:
        updated.append(value)
    return updated


def _build_controller_planner_command(
    *,
    provider_cli: str,
    controller: str,
    prompt_text: str,
    schema_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> list[str]:
    """Build provider-specific non-interactive planner command."""
    parts = shlex.split(provider_cli)
    controller_name = str(controller).strip().lower()

    if controller_name == "codex":
        converted_parts: list[str] = []
        idx = 0
        while idx < len(parts):
            part = parts[idx]
            if part == "--thinking" and idx + 1 < len(parts):
                converted_parts.extend(["-c", f'model_reasoning_effort="{parts[idx + 1]}"'])
                idx += 2
                continue
            if part.startswith("--thinking="):
                converted_parts.extend(["-c", f'model_reasoning_effort="{part.split("=", 1)[1]}"'])
                idx += 1
                continue
            converted_parts.append(part)
            idx += 1
        parts = converted_parts
        parts = _drop_args(parts, ("--output-schema", "-o", "--output-last-message"), takes_value=True)
        if parts and parts[0] == "codex" and (len(parts) == 1 or parts[1] != "exec"):
            parts.insert(1, "exec")
        if "--skip-git-repo-check" not in parts:
            parts.append("--skip-git-repo-check")
        if schema_path:
            parts.extend(["--output-schema", schema_path])
        if output_path:
            parts.extend(["--output-last-message", output_path])
        return parts + [prompt_text]

    if controller_name == "claude":
        parts = _drop_args(parts, ("-c", "--continue", "--fork-session"), takes_value=False)
        parts = _drop_args(parts, ("-r", "--resume", "--session-id"), takes_value=True)
        parts = _set_or_append_arg(parts, ("-p", "--print"), None)
        parts = _set_or_append_arg(parts, ("--output-format",), "json")
        parts = _set_or_append_arg(parts, ("--permission-mode",), "plan")
        parts = _set_or_append_arg(parts, ("--json-schema",), _build_controller_plan_schema_text())
        return parts + [prompt_text]

    if controller_name == "gemini":
        parts = _drop_args(parts, ("-p", "--prompt", "-i", "--prompt-interactive", "-r", "--resume"), takes_value=True)
        parts = _drop_args(parts, ("-y", "--yolo"), takes_value=False)
        parts = _set_or_append_arg(parts, ("-o", "--output-format"), "json")
        parts = _set_or_append_arg(parts, ("--approval-mode",), "plan")
        return parts + ["-p", prompt_text]

    return parts + [prompt_text]


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists() and source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_literal(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value: {type(value)!r}")


def _dump_simple_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []

    def _table_key(key: str) -> str:
        return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)

    def _emit_table(table: dict[str, Any], prefix: tuple[str, ...] = ()) -> None:
        scalar_items = [(key, value) for key, value in table.items() if not isinstance(value, dict)]
        nested_items = [(key, value) for key, value in table.items() if isinstance(value, dict)]
        if prefix:
            lines.append(f"[{'.'.join(_table_key(part) for part in prefix)}]")
        for key, value in scalar_items:
            lines.append(f"{key} = {_toml_literal(value)}")
        if scalar_items and nested_items:
            lines.append("")
        for index, (key, value) in enumerate(nested_items):
            next_prefix = prefix + (key,)
            _emit_table(value, next_prefix)
            if index != len(nested_items) - 1:
                lines.append("")

    _emit_table(data)
    return "\n".join(lines).strip() + "\n"


def _write_minimal_codex_planner_config(*, source_home: Path, isolated_home: Path, workdir: Path) -> None:
    source_config = source_home / "config.toml"
    destination = isolated_home / "config.toml"
    if not source_config.exists():
        return

    try:
        raw = tomllib.loads(source_config.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        _copy_if_exists(source_config, destination)
        return

    provider_name = str(raw.get("model_provider") or "").strip()
    provider_table = raw.get("model_providers", {})
    if not provider_name and isinstance(provider_table, dict) and provider_table:
        provider_name = str(next(iter(provider_table.keys())))

    sanitized: dict[str, Any] = {}
    for key in ("model_provider", "model", "model_reasoning_effort", "disable_response_storage"):
        if key in raw:
            sanitized[key] = raw[key]

    if provider_name and isinstance(provider_table, dict):
        provider_config = provider_table.get(provider_name)
        if isinstance(provider_config, dict):
            sanitized["model_providers"] = {provider_name: provider_config}

    resolved_workdir = str(workdir.expanduser().resolve())
    project_table = raw.get("projects", {})
    if isinstance(project_table, dict):
        project_config = project_table.get(resolved_workdir)
        if isinstance(project_config, dict):
            sanitized["projects"] = {resolved_workdir: project_config}
        else:
            sanitized["projects"] = {resolved_workdir: {"trust_level": "trusted"}}
    else:
        sanitized["projects"] = {resolved_workdir: {"trust_level": "trusted"}}

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_dump_simple_toml(sanitized), encoding="utf-8")


def _build_controller_planner_env(*, controller: str, temp_dir: str) -> dict[str, str]:
    env = dict(os.environ)
    controller_name = str(controller).strip().lower()
    if controller_name != "codex":
        return env

    source_home = Path.home() / ".codex"
    isolated_home = Path(temp_dir) / "codex-home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    _write_minimal_codex_planner_config(source_home=source_home, isolated_home=isolated_home, workdir=Path.cwd())
    _copy_if_exists(source_home / "auth.json", isolated_home / "auth.json")
    _copy_if_exists(source_home / "version.json", isolated_home / "version.json")
    _copy_if_exists(source_home / ".codex-global-state.json", isolated_home / ".codex-global-state.json")
    env["CODEX_HOME"] = str(isolated_home)
    env["OTEL_SDK_DISABLED"] = "true"
    env["OTEL_TRACES_EXPORTER"] = "none"
    env["OTEL_METRICS_EXPORTER"] = "none"
    env["OTEL_LOGS_EXPORTER"] = "none"
    return env


def _looks_like_controller_plan(payload: Any) -> bool:
    """Whether payload already matches the controller plan shape."""
    if not isinstance(payload, dict):
        return False
    required_keys = {
        "plan_version",
        "controller",
        "requires_multi_agent",
        "agents",
        "steps",
        "approval_question",
    }
    return required_keys.issubset(payload.keys()) and isinstance(payload.get("steps"), list)


def _extract_controller_plan_payload(payload: Any) -> Optional[dict[str, Any]]:
    """Find controller plan in direct or wrapped JSON/text payloads."""
    if _looks_like_controller_plan(payload):
        return payload
    if isinstance(payload, str):
        nested = _extract_json_object(payload)
        if nested is not None:
            return _extract_controller_plan_payload(nested)
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _extract_controller_plan_payload(item)
            if found:
                return found
        return None
    if isinstance(payload, dict):
        for value in payload.values():
            found = _extract_controller_plan_payload(value)
            if found:
                return found
    return None


def _extract_controller_plan_from_jsonl(output_text: str) -> Optional[dict[str, Any]]:
    """Best-effort extraction from Codex `--json` event stream."""
    for raw_line in str(output_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        item = payload.get("item") if isinstance(payload, dict) else None
        if isinstance(item, dict):
            item_type = str(item.get("type", "")).strip().lower()
            if item_type in {"agent_message", "assistant_message"}:
                found = _extract_controller_plan_payload(item.get("text"))
                if found:
                    return found

        if isinstance(payload, dict):
            event_type = str(payload.get("type", "")).strip().lower()
            role = str(payload.get("role", "")).strip().lower()
            if event_type in {"assistant_message", "agent_message"} or role in {"assistant", "agent"}:
                found = _extract_controller_plan_payload(payload.get("text"))
                if found:
                    return found
    return None


def _extract_codex_jsonl_error(output_text: str) -> Optional[str]:
    """Extract the most meaningful failure message from Codex `--json` events."""
    last_error: Optional[str] = None
    for raw_line in str(output_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        event_type = str(payload.get("type", "")).strip().lower()
        if event_type == "turn.failed":
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                message = str(error_payload.get("message") or "").strip()
                if message:
                    return message
            message = str(payload.get("message") or "").strip()
            if message:
                return message
        if event_type == "error":
            message = str(payload.get("message") or "").strip()
            if message and not message.lower().startswith("reconnecting..."):
                last_error = message
    return last_error


def _build_codex_json_fallback_command(cmd_parts: list[str]) -> list[str]:
    """Switch a Codex planner command from last-message file mode to JSONL mode."""
    fallback = _drop_args(list(cmd_parts), ("-o", "--output-last-message"), takes_value=True)
    if "--json" not in fallback:
        fallback.append("--json")
    return fallback


def _codex_empty_last_message_warning(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return "no last agent message" in normalized and "empty content" in normalized


def _request_controller_plan(
    *,
    config: Config,
    controller: str,
    prompt_text: str,
    progress_callback: Optional[Callable[[str, dict[str, Any]], None]] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
    """Ask controller model for orchestration plan JSON."""
    provider_config = config.providers.get(controller)
    if not provider_config:
        return None, f"Unknown provider: {controller}"

    controller_name = str(controller).strip().lower()
    with tempfile.TemporaryDirectory(prefix="ai-collab-plan-") as temp_dir:
        schema_path: Optional[str] = None
        output_path: Optional[str] = None
        if controller_name == "codex":
            schema_path = str(Path(temp_dir) / "controller-plan-schema.json")
            output_path = str(Path(temp_dir) / "controller-plan-output.json")
            Path(schema_path).write_text(_build_controller_plan_schema_text(), encoding="utf-8")

        provider_cli = provider_config.cli
        try:
            provider_cli = ModelSelector(config).select_model(controller, prompt_text, "default").cli
        except Exception:
            provider_cli = provider_config.cli

        try:
            cmd_parts = _build_controller_planner_command(
                provider_cli=provider_cli,
                controller=controller,
                prompt_text=prompt_text,
                schema_path=schema_path,
                output_path=output_path,
            )
        except ValueError as exc:
            return None, f"Invalid provider CLI: {exc}"
        cmd_parts = resolve_subprocess_command(cmd_parts)

        try:
            planner_env = _build_controller_planner_env(controller=controller, temp_dir=temp_dir)
            if progress_callback is not None:
                progress_callback(
                    "command_started",
                    {
                        "command_preview": " ".join(cmd_parts[:8]) + (" ..." if len(cmd_parts) > 8 else ""),
                        "controller": controller,
                    },
                )
            if progress_callback is None and cancel_requested is None:
                result = subprocess.run(
                    cmd_parts,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=provider_config.timeout,
                    env=planner_env,
                )
            else:
                process = subprocess.Popen(
                    cmd_parts,
                    shell=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=planner_env,
                    bufsize=1,
                )
                stdout_chunks: list[str] = []
                stderr_chunks: list[str] = []
                stream_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

                def _reader(stream, stream_name: str, sink: list[str]) -> None:  # noqa: ANN001
                    try:
                        if stream is None:
                            return
                        for line in iter(stream.readline, ""):
                            sink.append(line)
                            stream_queue.put((stream_name, line))
                    finally:
                        with contextlib.suppress(Exception):
                            if stream is not None:
                                stream.close()
                        stream_queue.put((stream_name, None))

                stdout_thread = threading.Thread(
                    target=_reader,
                    args=(process.stdout, "stdout", stdout_chunks),
                    daemon=True,
                )
                stderr_thread = threading.Thread(
                    target=_reader,
                    args=(process.stderr, "stderr", stderr_chunks),
                    daemon=True,
                )
                stdout_thread.start()
                stderr_thread.start()
                start_time = time.time()
                seen_command_echo = False
                while True:
                    drained = False
                    while True:
                        try:
                            stream_name, line = stream_queue.get_nowait()
                        except queue.Empty:
                            break
                        drained = True
                        if line is None:
                            continue
                        if progress_callback is None:
                            continue
                        preview = line.strip()
                        if not preview:
                            continue
                        if (
                            controller_name == "codex"
                            and not seen_command_echo
                            and preview == "codex"
                        ):
                            seen_command_echo = True
                            continue
                        progress_callback(
                            "command_output",
                            {"stream": stream_name, "text": preview},
                        )
                    if cancel_requested is not None and cancel_requested():
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                        stdout_thread.join(timeout=1)
                        stderr_thread.join(timeout=1)
                        return None, "Planning canceled by user"
                    if process.poll() is not None:
                        stdout_thread.join(timeout=1)
                        stderr_thread.join(timeout=1)
                        stdout_text = "".join(stdout_chunks)
                        stderr_text = "".join(stderr_chunks)
                        result = subprocess.CompletedProcess(
                            args=cmd_parts,
                            returncode=process.returncode,
                            stdout=stdout_text,
                            stderr=stderr_text,
                        )
                        break
                    if time.time() - start_time > provider_config.timeout:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                        stdout_thread.join(timeout=1)
                        stderr_thread.join(timeout=1)
                        return None, f"Timeout after {provider_config.timeout}s"
                    time.sleep(0.05 if drained else 0.1)
        except FileNotFoundError:
            executable = cmd_parts[0] if cmd_parts else controller
            return None, f"Provider command not found: {executable}"
        except PermissionError as exc:
            executable = cmd_parts[0] if cmd_parts else controller
            return None, f"Provider command is not executable: {executable} ({exc})"
        except subprocess.TimeoutExpired:
            return None, f"Timeout after {provider_config.timeout}s"

        payload_candidates: list[Any] = []
        if output_path:
            output_file = Path(output_path)
            if output_file.exists():
                output_text = output_file.read_text(encoding="utf-8").strip()
                if output_text:
                    payload_candidates.append(output_text)

        combined_output = f"{result.stdout}\n{result.stderr}".strip()
        stripped_output = combined_output.lstrip()
        if combined_output and (
            controller_name != "codex"
            or (
                stripped_output.startswith("{")
                and _extract_controller_plan_payload(combined_output) is not None
            )
        ):
            payload_candidates.append(combined_output)

        for candidate in payload_candidates:
            plan = _extract_controller_plan_payload(candidate)
            if plan:
                return plan, None

        should_try_codex_fallback = controller_name == "codex" and (
            result.returncode == 0 or _codex_empty_last_message_warning(result.stderr or result.stdout or "")
        )
        if should_try_codex_fallback:
            fallback_cmd = _build_codex_json_fallback_command(cmd_parts)
            try:
                fallback_result = subprocess.run(
                    fallback_cmd,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=provider_config.timeout,
                    env=planner_env,
                )
            except FileNotFoundError:
                executable = fallback_cmd[0] if fallback_cmd else controller
                return None, f"Provider command not found: {executable}"
            except PermissionError as exc:
                executable = fallback_cmd[0] if fallback_cmd else controller
                return None, f"Provider command is not executable: {executable} ({exc})"
            except subprocess.TimeoutExpired:
                return None, f"Timeout after {provider_config.timeout}s"

            jsonl_plan = _extract_controller_plan_from_jsonl(fallback_result.stdout)
            if jsonl_plan:
                return jsonl_plan, None
            fallback_error = _extract_codex_jsonl_error(fallback_result.stdout)
            if fallback_error:
                return None, fallback_error

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip()
            lines = [line.strip() for line in error_text.splitlines() if line.strip()]
            ignored_prefixes = (
                "OpenAI Codex v",
                "Claude Code",
                "--------",
                "workdir:",
                "model:",
                "provider:",
                "approval:",
                "sandbox:",
                "reasoning effort:",
                "reasoning summaries:",
                "session id:",
                "user",
                "mcp startup:",
                "mcp:",
                "codex",
                "tokens used",
            )
            meaningful = [line for line in lines if not line.startswith(ignored_prefixes)]
            summary = meaningful[-1] if meaningful else (lines[-1] if lines else f"exit code {result.returncode}")
            return None, summary

    return None, "Controller output does not contain valid JSON object"


def _build_controller_execution_prompt(
    *,
    plan: dict[str, Any],
    lang: str,
    adjustment_notes: str = "",
) -> str:
    """Build execution prompt for approved controller plan."""
    serialized = json.dumps(plan, indent=2, ensure_ascii=False)
    notes_block = adjustment_notes.strip()
    command_contract_zh = """固定命令合同（直接使用，不要再读代码/文档猜参数）:
- 查看 tmux 绑定: `ai-collab tmux-status --json-output`
- 拉起真实子 Agent（下半屏）: `ai-collab handoff --agent <gemini|claude|codex> --tmux-layout split --split-policy controller-bottom --controller-pane <pane_id> --repo-root <repo> --prompt '<任务>' --completion-action keep --no-ask-launch-options`
- 监控子 Agent: `ai-collab tmux-watch --pane-id <pane_id> --timeout-seconds <n> --json-output`
- 关闭子 pane: `ai-collab tmux-close-pane --pane-id <pane_id>`
"""
    command_contract_en = """Command contract (use directly; do not read code/docs to guess params):
- tmux binding: `ai-collab tmux-status --json-output`
- spawn real sub-agent (bottom split): `ai-collab handoff --agent <gemini|claude|codex> --tmux-layout split --split-policy controller-bottom --controller-pane <pane_id> --repo-root <repo> --prompt '<task>' --completion-action keep --no-ask-launch-options`
- monitor sub-agent: `ai-collab tmux-watch --pane-id <pane_id> --timeout-seconds <n> --json-output`
- close sub pane: `ai-collab tmux-close-pane --pane-id <pane_id>`
"""
    if lang == "zh-CN":
        extra = ""
        if notes_block:
            extra = f"\n用户对编排的调整备注（必须遵循）:\n{notes_block}\n"
        return f"""以下是已获用户确认的执行计划 JSON，请严格执行。

{serialized}
{extra}

执行要求:
1. 严格按 steps 顺序执行。
2. 子 Agent 必须在 tmux 可视窗格执行，禁止后台 shell 调用 claude/gemini。
3. 每步结束输出 `STEP_DONE: <id>` 与简短结果。
4. 交接下一位时输出 `HANDOFF_TO: <agent>` 或 `SPAWN_AGENT: <agent>`。
5. 禁止运行 `--help` / `-h` / `--version`、禁止读取 `cli.py` / `SKILL.md` / 搜索源码来确认参数。
6. 若用户要求“真实子 Agent”，禁止使用 `--agent-cmd` shell 模拟（如 `sleep/echo`）。
7. 监控超时参数必须动态调整，不得固定为同一个值。
8. 若命令被权限/审批拦截，立即输出 `NEED_ELEVATION: <command> | reason=<error>`，等待用户处理。
9. 全部完成输出 `=== TASK_COMPLETE ===`。
10. 如果 step 含有 `responsibility_stage` / `artifact_type` / `boundary` / `timebox_minutes`，必须按这些字段理解步骤边界。
11. 不得在 collect 阶段直接进入大规模实现；collect 的目标是收集现状与证据。
12. 不得在 validate 阶段擅自重设方案；若发现边界内问题，交回 correct 阶段或显式请求用户确认。

{command_contract_zh}
"""
    extra = ""
    if notes_block:
        extra = f"\nUser adjustment notes for orchestration (must follow):\n{notes_block}\n"
    return f"""This approved execution plan JSON has been confirmed by the user. Execute strictly by it.

{serialized}
{extra}

Execution rules:
1. Follow steps in order.
2. Run sub-agents in visible tmux panes only. Do not call claude/gemini via hidden background shell commands.
3. After each step output `STEP_DONE: <id>` with short summary.
4. When handing off, output `HANDOFF_TO: <agent>` or `SPAWN_AGENT: <agent>`.
5. Do not run probe commands (`--help` / `-h` / `--version`) and do not read `cli.py`/`SKILL.md` to discover params.
6. If user asked for real sub-agent validation, do not use `--agent-cmd` shell simulation (`sleep/echo`).
7. Adjust monitor timeout dynamically from runtime status; do not keep one fixed timeout value.
8. If blocked by permission/approval, output `NEED_ELEVATION: <command> | reason=<error>` and wait.
9. Finish with `=== TASK_COMPLETE ===`.
10. If a step includes `responsibility_stage` / `artifact_type` / `boundary` / `timebox_minutes`, treat those fields as binding execution boundaries.
11. Do not jump into large-scale implementation during a collect stage; collect is for facts and evidence.
12. Do not silently reset the solution direction during validate; hand bounded issues back to a correct stage or explicitly escalate.

{command_contract_en}
"""


def _render_controller_plan(plan: dict[str, Any], *, lang: str) -> str:
    """Render controller plan JSON into user-facing summary text."""
    is_zh = lang == "zh-CN"
    lines: list[str] = []

    def _string_value(value: Any) -> str:
        return "" if value is None else str(value).strip()

    controller = _string_value(plan.get("controller")) or "(unknown)"
    workflow_engine = _string_value(plan.get("workflow_engine"))
    session_preset = _string_value(plan.get("session_preset"))
    workflow_blueprint = _string_value(plan.get("workflow_blueprint"))
    requires_multi = bool(plan.get("requires_multi_agent", False))
    agents = plan.get("agents", [])
    steps = plan.get("steps", [])
    approval_q = str(plan.get("approval_question", "")).strip()

    if is_zh:
        lines.append(f"主控: {controller}")
        if workflow_engine:
            lines.append(f"工作流引擎: {workflow_engine}")
        if session_preset:
            lines.append(f"会话预设: {session_preset}")
        if workflow_blueprint:
            lines.append(f"蓝图: {workflow_blueprint}")
        lines.append(f"是否多 Agent: {'是' if requires_multi else '否'}")
        lines.append("")
        lines.append("Agent 编排:")
    else:
        lines.append(f"Controller: {controller}")
        if workflow_engine:
            lines.append(f"Workflow engine: {workflow_engine}")
        if session_preset:
            lines.append(f"Session preset: {session_preset}")
        if workflow_blueprint:
            lines.append(f"Blueprint: {workflow_blueprint}")
        lines.append(f"Requires multi-agent: {'yes' if requires_multi else 'no'}")
        lines.append("")
        lines.append("Agent Assignment:")

    if isinstance(agents, list) and agents:
        for item in agents:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- {name}: model={model}, persona={persona}, why={why}".format(
                    name=item.get("name", ""),
                    model=item.get("model", ""),
                    persona=item.get("persona", ""),
                    why=item.get("why", ""),
                )
            )
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("Steps:")
    if isinstance(steps, list) and steps:
        for idx, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                continue
            sid = step.get("id", f"S{idx}")
            owner = step.get("owner", "")
            goal = step.get("goal", "")
            done_when = step.get("done_when", "")
            stage = _string_value(step.get("responsibility_stage"))
            artifact_type = _string_value(step.get("artifact_type"))
            timebox_minutes = step.get("timebox_minutes")
            lines.append(f"{idx}. [{sid}] {owner} - {goal}")
            if stage or artifact_type or timebox_minutes:
                meta_bits = []
                if stage:
                    meta_bits.append(f"stage={stage}")
                if artifact_type:
                    meta_bits.append(f"artifact={artifact_type}")
                if isinstance(timebox_minutes, int):
                    meta_bits.append(f"timebox={timebox_minutes}m")
                if meta_bits:
                    lines.append(f"   {' · '.join(meta_bits)}")
            if done_when:
                lines.append(f"   done_when: {done_when}")
    else:
        lines.append("1. (none)")

    if approval_q:
        lines.append("")
        lines.append(f"approval_question: {approval_q}")

    return "\n".join(lines).strip()


def _write_orchestration_adjustment_file(*, cwd: Path, controller: str, text: str) -> Path:
    """Write editable orchestration summary doc for user adjustments."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = cwd / ".ai-collab" / "orchestration"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{timestamp}-{controller}-orchestration.md"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _show_controller_plan(plan: dict[str, Any], *, lang: str) -> None:
    """Render controller JSON plan for user review."""
    console.print()
    console.print(
        render_tmux_block(
            _auto_msg(lang, "controller_plan_title"),
            lines=_render_controller_plan(plan, lang=lang).splitlines(),
        )
    )


def _controller_plan_to_tmux_payload(plan: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert approved controller JSON plan into tmux orchestration payload."""
    if not isinstance(plan, dict) or not bool(plan.get("requires_multi_agent", False)):
        return None
    steps_raw = plan.get("steps", [])
    if not isinstance(steps_raw, list) or not steps_raw:
        return None

    agent_models: dict[str, str] = {}
    agents_raw = plan.get("agents", [])
    if isinstance(agents_raw, list):
        for item in agents_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            model = str(item.get("model", "")).strip()
            if name:
                agent_models[name] = model

    orchestration_plan: list[dict[str, str]] = []
    selected_agents: list[str] = []
    for idx, item in enumerate(steps_raw, 1):
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner", "")).strip()
        if not owner:
            continue
        role = str(item.get("goal", "")).strip() or str(item.get("id", f"S{idx}")).strip() or f"S{idx}"
        orchestration_plan.append(
            {
                "role": role,
                "agent": owner,
                "selected_model": agent_models.get(owner, ""),
                "selected_cli": "",
                "profile": "controller-plan",
                "reason": "controller-plan",
            }
        )
        if owner not in selected_agents:
            selected_agents.append(owner)

    if len(selected_agents) <= 1 or not orchestration_plan:
        return None
    return {
        "execution_mode": "multi-agent",
        "orchestration_plan": orchestration_plan,
        "selected_agents": selected_agents,
    }


def _result_for_tmux_launch(result, controller_plan: Optional[dict[str, Any]]):
    """Prefer approved controller multi-agent plan when preparing tmux launch."""
    payload = _controller_plan_to_tmux_payload(controller_plan or {})
    if not payload:
        return result
    if hasattr(result, "model_copy"):
        try:
            return result.model_copy(update=payload)
        except Exception:  # noqa: BLE001
            pass
    if is_dataclass(result):
        try:
            allowed = set(getattr(result, "__dataclass_fields__", {}).keys())
            return replace(result, **{key: value for key, value in payload.items() if key in allowed})
        except Exception:  # noqa: BLE001
            pass
    if hasattr(result, "__dict__"):
        try:
            merged = dict(vars(result))
            merged.update(payload)
            return SimpleNamespace(**merged)
        except Exception:  # noqa: BLE001
            pass
    return result


def _wait_for_agent_ready(*, pane_id: str, agent: str, timeout_seconds: float = 25.0) -> bool:
    """Wait until pane output contains a known ready marker for the selected agent."""
    markers = {
        "codex": [
            "openai codex",
            "tip: use /skills",
            "gpt-5",
            "do you trust the contents of this directory",
            "press enter to continue",
        ],
        "claude": [
            "claude code",
            'try "create a util',
            "ctrl+t to hide tasks",
            "/ide for",
            "enter to confirm",
        ],
        "gemini": ["gemini"],
    }
    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    expected = markers.get(agent, [])
    codex_trust_confirmed = False
    claude_trust_confirmed = False
    while time.monotonic() < deadline:
        try:
            snapshot = capture_pane_text(pane_id=pane_id, start_line=-200)
        except subprocess.CalledProcessError:
            time.sleep(0.5)
            continue
        lower = snapshot.lower()
        if agent == "codex":
            has_trust_gate = (
                "do you trust the contents of this directory" in lower
                or "press enter to continue" in lower
                or "yes, continue" in lower
            )
            if has_trust_gate and not codex_trust_confirmed:
                codex_trust_confirmed = True
                send_pane_text(pane_id=pane_id, text="", press_enter=True, delay_seconds=0.0)
                time.sleep(0.6)
                continue
        if agent == "claude":
            has_trust_gate = (
                "yes, i trust this folder" in lower
                or ("enter to confirm" in lower and "security guide" in lower)
                or ("claude code'll be able to read" in lower and "yes, i trust this folder" in lower)
            )
            if has_trust_gate and not claude_trust_confirmed:
                claude_trust_confirmed = True
                # Claude trust gate may default cursor on "No, exit"; explicitly choose option 1.
                send_pane_text(pane_id=pane_id, text="1", press_enter=True, delay_seconds=0.0)
                time.sleep(0.8)
                continue
        if any(token in lower for token in expected):
            return True
        time.sleep(0.5)
    return False


def _prompt_probe(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if len(candidate) >= 8:
            normalized = re.sub(r"\s+", " ", candidate.lower())
            if ":" in normalized:
                prefix = normalized.split(":", 1)[0].strip()
                if len(prefix) >= 8:
                    return prefix[:48]
            return normalized[:48]
    fallback = text.strip()
    normalized = re.sub(r"\s+", " ", fallback.lower()) if fallback else ""
    if ":" in normalized:
        prefix = normalized.split(":", 1)[0].strip()
        if len(prefix) >= 8:
            return prefix[:48]
    return normalized[:48]


def _pane_contains_probe(*, pane_id: str, probe: str) -> bool:
    if not probe:
        return True
    try:
        snapshot = capture_pane_text(pane_id=pane_id, start_line=-260)
    except subprocess.CalledProcessError:
        return False
    normalized = re.sub(r"\s+", " ", snapshot.lower())
    return probe in normalized


def _relay_to_controller_input_enabled() -> bool:
    """Whether relay watcher should inject status text into controller input."""
    value = os.environ.get("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _relay_to_controller_status_enabled() -> bool:
    """Whether relay watcher should show status via tmux status line message."""
    value = os.environ.get("AI_COLLAB_RELAY_STATUS_MESSAGE", "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _controller_ask_close_on_complete_enabled() -> bool:
    """Whether relay should force controller to ask user about closing completed panes."""
    value = os.environ.get("AI_COLLAB_CONTROLLER_ASK_CLOSE_ON_COMPLETE", "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _controller_close_prompt_to_input_enabled() -> bool:
    """Whether close-confirmation prompt should be injected into controller input box."""
    value = os.environ.get("AI_COLLAB_CONTROLLER_CLOSE_PROMPT_TO_INPUT", "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _notify_controller_to_confirm_subagent_close(
    *,
    controller_pane: str,
    agent: str,
    pane_id: str,
) -> None:
    """Tell controller to ask user whether to close a completed sub-agent pane first."""
    if not _controller_ask_close_on_complete_enabled():
        return
    msg = (
        "[ai-collab control] Sub-agent "
        f"{agent} (pane {pane_id}) completed. "
        "First ask user whether to close this completed agent pane, wait for user answer, then continue."
    )
    subprocess.run(
        ["tmux", "display-message", "-t", controller_pane, msg],
        check=False,
        capture_output=True,
        text=True,
    )
    if _controller_close_prompt_to_input_enabled():
        send_pane_text(
            pane_id=controller_pane,
            text=msg,
            press_enter=True,
            delay_seconds=0.0,
        )
        # Some chat UIs treat first Enter as input commit but not submit.
        send_pane_text(
            pane_id=controller_pane,
            text="",
            press_enter=True,
            delay_seconds=0.12,
        )


def _resolve_dispatch_typing_char_delay() -> float:
    """Resolve character delay for short dispatch typing."""
    raw = os.environ.get("AI_COLLAB_DISPATCH_TYPE_CHAR_DELAY_SECONDS", "").strip()
    if not raw:
        return 0.015
    try:
        parsed = float(raw)
    except ValueError:
        return 0.015
    if parsed < 0:
        return 0.015
    return min(parsed, 0.2)


def _tmux_events_log_path(*, cwd: Path, session: str) -> Path:
    """Path to relay events log for a tmux session."""
    folder = pane_logs_dir(cwd=cwd, session=session)
    return folder / "events.log"


def _emit_relay_event(
    *,
    cwd: Path,
    session: str,
    controller_pane: str,
    message: str,
    run_store: Optional[RunStateStore] = None,
    event_type: str = "relay_message",
    source: str = "relay",
    agent: str = "",
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Persist relay events and optionally inject them to controller input."""
    event_log = _tmux_events_log_path(cwd=cwd, session=session)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_log.parent.mkdir(parents=True, exist_ok=True)
    with event_log.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")

    if run_store is not None:
        run_store.append_event(
            event_type=event_type,
            source=source,
            agent=agent,
            payload=payload or {"message": message},
        )
        if event_type in {"step_done", "subagent_complete", "subagent_hard_timeout", "subagent_error_detected"}:
            run_store.set_phase(
                phase="monitoring",
                detail=f"{event_type}:{agent or 'controller'}",
                source=source,
            )
        if event_type in {
            "subagent_spawned",
            "subagent_complete",
            "subagent_complete_legacy",
            "subagent_hard_timeout",
            "subagent_error_detected",
            "handoff_request",
            "handoff_request_legacy",
        }:
            _record_tmux_layout_snapshot(
                run_store=run_store,
                session=session,
                reason=f"event:{event_type}",
            )

    if _relay_to_controller_status_enabled():
        subprocess.run(
            ["tmux", "display-message", "-t", controller_pane, message],
            check=False,
            capture_output=True,
            text=True,
        )

    if _relay_to_controller_input_enabled():
        send_pane_text(
            pane_id=controller_pane,
            text=message,
            delay_seconds=0.0,
        )


def _resolve_prompt_injection_delay(agent: str) -> float:
    """Resolve prompt injection warmup delay in seconds."""
    defaults = {
        "codex": 1.2,
        "claude": 2.0,
        "gemini": 2.0,
    }
    base = defaults.get(agent, 1.5)
    raw = os.environ.get("AI_COLLAB_PROMPT_INJECT_DELAY_SECONDS", "").strip()
    if not raw:
        return base
    try:
        parsed = float(raw)
    except ValueError:
        return base
    if parsed < 0:
        return base
    return parsed


def _resolve_agent_ready_timeout(agent: str) -> float:
    """Resolve readiness wait timeout in seconds."""
    defaults = {
        "codex": 15.0,
        "claude": 25.0,
        "gemini": 25.0,
    }
    base = defaults.get(agent, 8.0)
    raw = os.environ.get("AI_COLLAB_AGENT_READY_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return base
    try:
        parsed = float(raw)
    except ValueError:
        return base
    if parsed <= 0:
        return base
    return parsed


def _inject_prompt_to_pane(*, pane_id: str, text: str, agent: str) -> bool:
    """
    Inject a prompt to an interactive pane.

    Prefer single-block paste to avoid partial line submissions.
    """
    probe = _prompt_probe(text)
    ready_timeout = _resolve_agent_ready_timeout(agent)
    # Gemini occasionally drops first injected block during startup transitions.
    # Keep retry only for Gemini to avoid duplicate dispatch in codex/claude.
    max_attempts = 2 if agent == "gemini" else 1
    for attempt in range(max_attempts):
        ready = _wait_for_agent_ready(
            pane_id=pane_id,
            agent=agent,
            timeout_seconds=ready_timeout,
        )
        settle_delay = _resolve_prompt_injection_delay(agent)
        if not ready:
            # Never inject prompt to shell fallback when target CLI is not ready.
            if attempt < max_attempts - 1:
                time.sleep(max(0.6, min(settle_delay, 1.2)))
                continue
            return False
        if settle_delay > 0:
            time.sleep(settle_delay)
        wait_for_pane_quiet(
            pane_id=pane_id,
            timeout_seconds=5.0,
            stable_checks=2,
            poll_interval=0.5,
        )
        lines = text.splitlines()
        use_literal_send = len(lines) <= 6 and len(text) <= 700
        try:
            if use_literal_send:
                type_pane_text(
                    pane_id=pane_id,
                    text=text,
                    char_delay_seconds=_resolve_dispatch_typing_char_delay(),
                    press_enter=True,
                    delay_seconds=0.0,
                )
                # Some interactive CLIs keep first Enter as input commit but not submit.
                send_pane_text(
                    pane_id=pane_id,
                    text="",
                    press_enter=True,
                    delay_seconds=0.15,
                )
            else:
                paste_pane_text(
                    pane_id=pane_id,
                    text=text,
                    press_enter=True,
                    delay_seconds=0.2,
                )
        except subprocess.CalledProcessError:
            # Fallback for environments where buffer paste is unavailable.
            send_pane_text(
                pane_id=pane_id,
                text=text,
                press_enter=True,
                delay_seconds=0.2,
            )
        time.sleep(0.8)
        if _pane_contains_probe(pane_id=pane_id, probe=probe):
            return True
        time.sleep(0.6)
    return False


def _extract_handoff_targets(text: str) -> list[str]:
    """Extract handoff markers from live terminal lines."""
    targets: list[str] = []
    normalized = _normalize_terminal_text_for_markers(text)
    pattern = re.compile(
        r"(?mi)^\s*(?:HANDOFF_TO|SPAWN_AGENT)\s*:\s*([a-zA-Z0-9_-]+)\b"
    )
    for match in pattern.findall(normalized):
        token = str(match).strip().lower()
        if token and not token.startswith("<"):
            targets.append(token)
    return targets


def _extract_step_done_ids(text: str) -> list[str]:
    """Extract STEP_DONE markers from live terminal lines."""
    step_ids: list[str] = []
    normalized = _normalize_terminal_text_for_markers(text)
    pattern = re.compile(r"(?mi)^\s*STEP_DONE\s*:\s*([A-Za-z0-9_.-]+)\b")
    for match in pattern.findall(normalized):
        token = str(match).strip()
        if token and not token.startswith("<"):
            step_ids.append(token)
    return step_ids


def _extract_step_start_ids(text: str) -> list[str]:
    """Extract step-start markers from live terminal lines."""
    step_ids: list[str] = []
    normalized = _normalize_terminal_text_for_markers(text)
    patterns = [
        re.compile(r"(?mi)^\s*STEP_START\s*:\s*([A-Za-z0-9_.-]+)\b"),
        re.compile(r"(?mi)^\s*(S[0-9][A-Za-z0-9_.-]*)_START\b"),
    ]
    for pattern in patterns:
        for match in pattern.findall(normalized):
            token = str(match).strip()
            if token and not token.startswith("<") and token not in step_ids:
                step_ids.append(token)
    return step_ids


def _extract_runtime_session_ids(text: str) -> list[str]:
    """Best-effort extraction for agent runtime session/conversation IDs."""
    normalized = _normalize_terminal_text_for_markers(text)
    ids: list[str] = []
    patterns = [
        re.compile(
            r"(?im)\b(?:session|conversation|chat)(?:\s*_?\s*id)?\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9._:-]{5,})"
        ),
        re.compile(r"(?im)\bresume\s+([A-Za-z0-9][A-Za-z0-9._:-]{5,})"),
    ]
    for pattern in patterns:
        for match in pattern.findall(normalized):
            token = str(match).strip().strip(",.;")
            if not token:
                continue
            if token not in ids:
                ids.append(token)
    return ids


def _capture_tmux_layout_snapshot(*, session: str, preview_lines: int = 6) -> dict[str, Any]:
    """Capture tmux window/pane topology plus light pane content preview."""
    if shutil.which("tmux") is None:
        return {"session": session, "available": False, "reason": "tmux_missing"}
    windows_cmd = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_index}\t#{window_name}\t#{window_active}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if windows_cmd.returncode != 0:
        return {
            "session": session,
            "available": False,
            "reason": (windows_cmd.stderr or "").strip() or "list_windows_failed",
        }
    windows: list[dict[str, Any]] = []
    for line in windows_cmd.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        index, name, active = parts[0].strip(), parts[1].strip(), parts[2].strip()
        pane_cmd = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-t",
                f"{session}:{index}",
                "-F",
                "#{pane_id}\t#{pane_active}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}\t#{pane_current_command}\t#{pane_title}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        panes: list[dict[str, Any]] = []
        if pane_cmd.returncode == 0:
            for row in pane_cmd.stdout.splitlines():
                cols = row.split("\t")
                if len(cols) < 8:
                    continue
                pane_id = cols[0].strip()
                preview = ""
                if preview_lines > 0:
                    preview_cmd = subprocess.run(
                        ["tmux", "capture-pane", "-p", "-J", "-t", pane_id, "-S", f"-{max(1, int(preview_lines))}"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if preview_cmd.returncode == 0:
                        preview_rows = [row.strip() for row in preview_cmd.stdout.splitlines() if row.strip()]
                        preview = " | ".join(preview_rows[-min(3, len(preview_rows)):])[:420]
                panes.append(
                    {
                        "pane_id": pane_id,
                        "active": cols[1].strip(),
                        "left": cols[2].strip(),
                        "top": cols[3].strip(),
                        "width": cols[4].strip(),
                        "height": cols[5].strip(),
                        "command": cols[6].strip(),
                        "title": cols[7].strip(),
                        "preview": preview,
                    }
                )
        windows.append(
            {
                "index": index,
                "name": name,
                "active": active,
                "panes": panes,
            }
        )
    return {"session": session, "available": True, "windows": windows}


def _snapshot_pane_ids(snapshot: dict[str, Any]) -> set[str]:
    """Collect all pane ids from a tmux layout snapshot payload."""
    pane_ids: set[str] = set()
    windows = snapshot.get("windows", []) if isinstance(snapshot, dict) else []
    if not isinstance(windows, list):
        return pane_ids
    for window in windows:
        if not isinstance(window, dict):
            continue
        panes = window.get("panes", [])
        if not isinstance(panes, list):
            continue
        for pane in panes:
            if not isinstance(pane, dict):
                continue
            pane_id = str(pane.get("pane_id", "")).strip()
            if pane_id:
                pane_ids.add(pane_id)
    return pane_ids


def _sync_controller_progress_from_text(*, run_store: RunStateStore, text: str, source: str = "controller_marker") -> None:
    """Sync STEP_START/STEP_DONE markers from controller output into run steps."""
    raw = str(text or "")
    if not raw:
        return
    snap = run_store.snapshot()
    controller = snap.get("controller", {}) if isinstance(snap.get("controller", {}), dict) else {}
    controller_agent = str(controller.get("agent", "")).strip() or "controller"
    steps = snap.get("steps", {}) if isinstance(snap.get("steps", {}), dict) else {}
    done_values = {"done", "complete", "completed", "accepted"}

    for step_id in _extract_step_start_ids(raw):
        current = steps.get(step_id, {}) if isinstance(steps.get(step_id, {}), dict) else {}
        status = str(current.get("status", "")).strip().lower()
        if status in done_values or status in {"running", "in_progress", "assigned"}:
            continue
        run_store.set_step_status(step_id=step_id, status="running", agent=controller_agent)
        run_store.set_phase(phase="step_started", detail=f"{step_id}:running", source=source)
        run_store.append_event(
            event_type="step_started",
            source=source,
            agent=controller_agent,
            payload={"step_id": step_id},
        )
        steps[step_id] = {"status": "running"}

    for step_id in _extract_step_done_ids(raw):
        current = steps.get(step_id, {}) if isinstance(steps.get(step_id, {}), dict) else {}
        status = str(current.get("status", "")).strip().lower()
        if status in done_values:
            continue
        run_store.set_step_status(step_id=step_id, status="done", agent=controller_agent)
        run_store.append_event(
            event_type="step_done",
            source=source,
            agent=controller_agent,
            payload={"step_id": step_id},
        )
        steps[step_id] = {"status": "done"}


def _sync_controller_progress_from_live_pane(
    *,
    run_store: RunStateStore,
    source: str = "controller_marker",
    start_line: int = -320,
) -> None:
    """Best-effort sync STEP_* markers by capturing current controller pane text."""
    snap = run_store.snapshot()
    controller = snap.get("controller", {}) if isinstance(snap.get("controller", {}), dict) else {}
    pane_id = str(controller.get("pane_id", "")).strip()
    if not pane_id:
        return
    try:
        snapshot = capture_pane_text(pane_id=pane_id, start_line=int(start_line))
    except subprocess.CalledProcessError:
        return
    for runtime_id in _extract_runtime_session_ids(snapshot):
        run_store.set_controller_runtime_session_id(runtime_session_id=runtime_id)
    _sync_controller_progress_from_text(run_store=run_store, text=snapshot, source=source)


def _refresh_runs_controller_progress_from_live_panes(
    *,
    cwd: Path,
    runs: list[dict[str, Any]],
    source: str = "resume_list",
) -> None:
    """Refresh resumable runs by syncing controller markers from live pane text."""
    for item in runs:
        run_id = str(item.get("run_id", "")).strip() if isinstance(item, dict) else ""
        if not run_id:
            continue
        status = str(item.get("status", "")).strip().lower() if isinstance(item, dict) else ""
        if status == "completed":
            continue
        store = RunStateStore.load(cwd=cwd, run_id=run_id)
        if store is None:
            continue
        _sync_controller_progress_from_live_pane(run_store=store, source=source)


def _find_active_run_store_for_session(
    *,
    cwd: Path,
    session: str,
    controller_pane: str = "",
) -> Optional[RunStateStore]:
    """Find latest run store bound to a tmux session (optionally controller pane)."""
    target_session = str(session).strip()
    if not target_session:
        return None
    runs = RunStateStore.list_runs(cwd=cwd, limit=200)
    pane_target = str(controller_pane).strip()
    for item in runs:
        if str(item.get("session", "")).strip() != target_session:
            continue
        run_id = str(item.get("run_id", "")).strip()
        if not run_id:
            continue
        store = RunStateStore.load(cwd=cwd, run_id=run_id)
        if store is None:
            continue
        if not pane_target:
            return store
        snap = store.snapshot()
        pane = str((snap.get("controller", {}) or {}).get("pane_id", "")).strip()
        if pane == pane_target:
            return store
    return None


def _sync_runtime_session_ids_from_snapshot(*, run_store: RunStateStore, snapshot: dict[str, Any]) -> None:
    """Best-effort sync runtime session ids by scanning live pane output."""
    windows = snapshot.get("windows", []) if isinstance(snapshot, dict) else []
    if not isinstance(windows, list):
        return
    for window in windows:
        if not isinstance(window, dict):
            continue
        panes = window.get("panes", [])
        if not isinstance(panes, list):
            continue
        for pane in panes:
            if not isinstance(pane, dict):
                continue
            pane_id = str(pane.get("pane_id", "")).strip()
            if not pane_id:
                continue
            title = str(pane.get("title", "")).strip()
            agent = ""
            if title == "ai-collab:controller":
                controller = run_store.snapshot().get("controller", {})
                agent = str((controller or {}).get("agent", "")).strip()
            elif title.startswith("ai-collab:subagent:"):
                agent = title.split("ai-collab:subagent:", 1)[1].strip().lower()
            if not agent:
                continue
            shot = subprocess.run(
                ["tmux", "capture-pane", "-p", "-J", "-t", pane_id, "-S", "-220"],
                capture_output=True,
                text=True,
                check=False,
            )
            if shot.returncode != 0:
                continue
            ids = _extract_runtime_session_ids(shot.stdout or "")
            if not ids:
                continue
            runtime_id = ids[-1]
            controller = run_store.snapshot().get("controller", {})
            controller_agent = str((controller or {}).get("agent", "")).strip().lower()
            if agent == controller_agent:
                run_store.set_controller_runtime_session_id(runtime_session_id=runtime_id)
            else:
                run_store.set_agent_runtime_session_id(agent=agent, runtime_session_id=runtime_id)


def _enrich_snapshot_with_runtime_sessions(*, run_store: RunStateStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach runtime session metadata to layout snapshot for resume diagnostics."""
    snap = run_store.snapshot()
    controller = snap.get("controller", {}) if isinstance(snap.get("controller", {}), dict) else {}
    agents = snap.get("agents", {}) if isinstance(snap.get("agents", {}), dict) else {}
    runtime_payload = {
        "controller": {
            "agent": str(controller.get("agent", "")).strip(),
            "pane_id": str(controller.get("pane_id", "")).strip(),
            "runtime_session_id": str(controller.get("runtime_session_id", "")).strip(),
        },
        "agents": [
            {
                "agent": str(name).strip(),
                "pane_id": str((details or {}).get("pane_id", "")).strip(),
                "runtime_session_id": str((details or {}).get("runtime_session_id", "")).strip(),
            }
            for name, details in agents.items()
            if isinstance(details, dict)
        ],
        "workspace": str(snap.get("workspace", "")).strip(),
    }
    merged = dict(snapshot)
    merged["runtime_sessions"] = runtime_payload
    return merged


def _record_tmux_layout_snapshot(*, run_store: Optional[RunStateStore], session: str, reason: str) -> None:
    """Store tmux snapshot diff into run state whenever topology/content changes."""
    if run_store is None:
        return
    snapshot = _capture_tmux_layout_snapshot(session=session, preview_lines=6)
    try:
        _sync_runtime_session_ids_from_snapshot(run_store=run_store, snapshot=snapshot)
    except Exception:  # noqa: BLE001
        pass
    snapshot = _enrich_snapshot_with_runtime_sessions(run_store=run_store, snapshot=snapshot)
    changed = run_store.update_tmux_layout_snapshot(
        session=session,
        snapshot=snapshot,
        reason=reason,
    )
    if changed:
        windows = snapshot.get("windows", []) if isinstance(snapshot, dict) else []
        pane_count = 0
        if isinstance(windows, list):
            pane_count = sum(len(item.get("panes", [])) for item in windows if isinstance(item, dict))
        run_store.append_event(
            event_type="tmux_layout_changed",
            source="tmux",
            payload={
                "reason": reason,
                "window_count": len(windows) if isinstance(windows, list) else 0,
                "pane_count": pane_count,
            },
        )


def _extract_ai_collab_events(text: str) -> list[dict[str, Any]]:
    """Extract structured AI_COLLAB_EVENT JSON payloads from terminal output."""
    events: list[dict[str, Any]] = []
    normalized = _normalize_terminal_text_for_markers(text)
    lines = normalized.splitlines()
    prefix = re.compile(r"(?i)^\s*AI_COLLAB_EVENT\s*:?\s*(.*)$")
    marker_prefix = re.compile(r"(?i)^\s*(?:AI_COLLAB_EVENT|STEP_DONE|HANDOFF_TO|SPAWN_AGENT|RESULT)\s*:")

    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        match = prefix.match(raw)
        if not match:
            idx += 1
            continue

        suffix = match.group(1).strip()
        brace_pos = suffix.find("{")
        if brace_pos < 0:
            idx += 1
            continue

        payload = suffix[brace_pos:].strip()
        parsed: Optional[dict[str, Any]] = None
        consumed = 0

        for look_ahead in range(0, 8):
            try:
                candidate = json.loads(payload)
            except json.JSONDecodeError:
                candidate = None
            if isinstance(candidate, dict):
                parsed = candidate
                consumed = look_ahead
                break
            next_idx = idx + look_ahead + 1
            if next_idx >= len(lines):
                break
            next_line = lines[next_idx]
            if marker_prefix.match(next_line):
                break
            payload += next_line.strip()

        if parsed is not None:
            events.append(parsed)
            idx += consumed + 1
            continue
        idx += 1
    return events


def _build_step_tickets(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Assign deterministic step ids plus run-scoped nonces for completion validation."""
    tickets: list[dict[str, str]] = []
    for idx, step in enumerate(steps, 1):
        step_id = str(step.get("id", "")).strip() or f"S{idx}"
        step["id"] = step_id
        tickets.append(
            {
                "step_id": step_id,
                "nonce": uuid4().hex[:12],
            }
        )
    return tickets


def _resolve_subagent_timeout_seconds(kind: str) -> float:
    """Resolve soft/hard timeout for sub-agent status waiting."""
    defaults = {
        "soft": 180.0,
        "hard": 480.0,
    }
    key = "AI_COLLAB_SUBAGENT_SOFT_TIMEOUT_SECONDS" if kind == "soft" else "AI_COLLAB_SUBAGENT_HARD_TIMEOUT_SECONDS"
    base = defaults[kind]
    raw = os.environ.get(key, "").strip()
    if not raw:
        return base
    try:
        value = float(raw)
    except ValueError:
        return base
    if value <= 0:
        return base
    return value


def _normalize_terminal_text_for_markers(text: str) -> str:
    """Normalize terminal output so marker parsing survives ANSI/carriage updates."""
    normalized = text.replace("\r", "\n")
    normalized = ANSI_ESCAPE_RE.sub("", normalized)
    return normalized


def _build_subagent_prompt(
    *,
    task: str,
    steps: list[dict],
    lang: str,
    controller: str,
    run_id: str,
    step_tickets: list[dict[str, str]],
) -> str:
    assigned_lines = [
        "- {step_id} {role}: model={model}, reason={reason}".format(
            step_id=f"[{step.get('id', f'S{idx}')}]",
            role=step.get("role", ""),
            model=step.get("selected_model", ""),
            reason=step.get("reason", ""),
        )
        for idx, step in enumerate(steps, 1)
    ]
    ticket_lines = [
        "- {step_id}: nonce={nonce}".format(
            step_id=ticket.get("step_id", ""),
            nonce=ticket.get("nonce", ""),
        )
        for ticket in step_tickets
    ]
    if lang == "zh-CN":
        return (
            f"{_auto_msg(lang, 'subagent_title')}\n"
            f"- {_auto_msg(lang, 'brief_user_task')}: {task}\n"
            f"- {_auto_msg(lang, 'brief_assigned_roles')}:\n"
            + "\n".join(assigned_lines)
            + f"\n- {_auto_msg(lang, 'brief_return')}\n"
            + "\n执行规则（必须遵守）:\n"
            + "- 收到任务后直接执行，不要问用户“是否继续/要不要我继续实现”。\n"
            + "- 若信息不完整，使用最小可行默认值并继续推进，同时注明假设。\n"
            + "- 禁止先运行 `--help` / `-h` / `--version` 或健康检查脚本探活，直接执行分配步骤。\n"
            + "- 若命令被权限/审批拦截，输出 `NEED_ELEVATION: <command> | reason=<error>` 并等待。\n"
            + "- 本次运行 run_id: "
            + run_id
            + "\n"
            + "- 本次 step nonce 对照:\n"
            + ("\n".join(ticket_lines) if ticket_lines else "- (none)")
            + "\n"
            + "- 完成后必须输出结构化事件（每行一条，严格 JSON）:\n"
            + '- AI_COLLAB_EVENT: {"type":"step_done","run_id":"'
            + run_id
            + '","step_id":"<step_id>","nonce":"<nonce>","status":"ok","summary":"<三行内摘要>"}\n'
            + '- AI_COLLAB_EVENT: {"type":"subagent_complete","run_id":"'
            + run_id
            + '","agent":"<agent>","status":"ok"}\n'
            + "- 同时保留以下兼容标记（逐行输出）:\n"
            + "- STEP_DONE: <step_id>\n"
            + f"- HANDOFF_TO: {controller}\n"
            + "- RESULT: <三行内结果摘要>\n"
            + "- === SUBAGENT_COMPLETE ===\n"
            + f"- {_auto_msg(lang, 'brief_end')}"
        )
    return (
        f"{_auto_msg(lang, 'subagent_title')}\n"
        f"- {_auto_msg(lang, 'brief_user_task')}: {task}\n"
        f"- {_auto_msg(lang, 'brief_assigned_roles')}:\n"
        + "\n".join(assigned_lines)
        + f"\n- {_auto_msg(lang, 'brief_return')}\n"
        + "\nExecution rules (must follow):\n"
        + "- Execute immediately after receiving task. Do not ask user \"should I continue?\".\n"
        + "- If information is missing, choose minimal viable defaults, note assumptions, and continue.\n"
        + "- Do not run `--help` / `-h` / `--version` or health-check scripts before execution.\n"
        + "- If command execution is blocked by permission/approval, output `NEED_ELEVATION: <command> | reason=<error>` and wait.\n"
        + "- Current run_id: "
        + run_id
        + "\n"
        + "- Step nonce map:\n"
        + ("\n".join(ticket_lines) if ticket_lines else "- (none)")
        + "\n"
        + "- After finishing, emit structured events (one JSON line per event):\n"
        + '- AI_COLLAB_EVENT: {"type":"step_done","run_id":"'
        + run_id
        + '","step_id":"<step_id>","nonce":"<nonce>","status":"ok","summary":"<3-line summary>"}\n'
        + '- AI_COLLAB_EVENT: {"type":"subagent_complete","run_id":"'
        + run_id
        + '","agent":"<agent>","status":"ok"}\n'
        + "- Keep compatibility markers as well:\n"
        + "- STEP_DONE: <step_id>\n"
        + f"- HANDOFF_TO: {controller}\n"
        + "- RESULT: <summary within 3 lines>\n"
        + "- === SUBAGENT_COMPLETE ===\n"
        + f"- {_auto_msg(lang, 'brief_end')}"
    )


def _start_subagent_status_relay(
    *,
    session: str,
    cwd: Path,
    subagent_pane: str,
    controller_pane: str,
    agent: str,
    run_store: Optional[RunStateStore] = None,
    expected_step_nonces: Optional[dict[str, str]] = None,
) -> None:
    """Relay sub-agent completion markers back to controller pane."""
    expected_nonces = expected_step_nonces or {}
    soft_timeout = _resolve_subagent_timeout_seconds("soft")
    hard_timeout = max(_resolve_subagent_timeout_seconds("hard"), soft_timeout + 30.0)

    def _runner() -> None:
        seen_steps: set[str] = set()
        seen_handoffs: set[str] = set()
        seen_structured: set[str] = set()
        unchanged = 0
        last_tail = ""
        seeded = False
        last_progress = time.monotonic()
        soft_timeout_emitted = False
        active_issue = ""
        active_issue_since = 0.0
        issue_grace_seconds = max(8.0, min(20.0, soft_timeout * 0.35))

        if run_store is not None:
            run_store.set_agent_status(agent=agent, status="running")
            run_store.set_phase(phase="monitoring", detail=f"watching:{agent}", source="relay")
            run_store.append_event(
                event_type="subagent_started",
                source="relay",
                agent=agent,
                payload={"pane_id": subagent_pane},
            )
        while True:
            try:
                snapshot = capture_pane_text(pane_id=subagent_pane, start_line=-260)
            except subprocess.CalledProcessError:
                unchanged += 1
                if unchanged >= 8:
                    if run_store is not None:
                        run_store.set_agent_status(agent=agent, status="pane_unavailable")
                    return
                time.sleep(1.0)
                continue

            tail = snapshot[-5000:]
            if not seeded:
                seeded = True
                last_tail = tail
                time.sleep(1.0)
                continue
            delta = tail
            if tail.startswith(last_tail):
                delta = tail[len(last_tail):]
            if tail == last_tail:
                unchanged += 1
            else:
                unchanged = 0
                last_tail = tail
                last_progress = time.monotonic()

                parsed_structured = _extract_ai_collab_events(delta)
                for event in parsed_structured:
                    evt_type = str(event.get("type", "")).strip().lower()
                    evt_run = str(event.get("run_id", "")).strip()
                    evt_step = str(event.get("step_id", "")).strip()
                    evt_nonce = str(event.get("nonce", "")).strip()
                    evt_session_id = str(
                        event.get("session_id")
                        or event.get("runtime_session_id")
                        or event.get("conversation_id")
                        or ""
                    ).strip()
                    if run_store is not None and evt_session_id:
                        run_store.set_agent_runtime_session_id(agent=agent, runtime_session_id=evt_session_id)
                    evt_key = f"{evt_type}|{evt_run}|{evt_step}|{evt_nonce}"
                    if evt_key in seen_structured:
                        continue
                    seen_structured.add(evt_key)

                    if run_store is not None and evt_run and evt_run != run_store.run_id:
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} ignored mismatched run_id event: {evt_run}",
                            run_store=run_store,
                            event_type="subagent_event_rejected",
                            source="relay",
                            agent=agent,
                            payload={"reason": "run_id_mismatch", "event": event},
                        )
                        continue

                    if evt_type == "step_done":
                        expected_nonce = expected_nonces.get(evt_step, "")
                        if expected_nonce and evt_nonce != expected_nonce:
                            _emit_relay_event(
                                cwd=cwd,
                                session=session,
                                controller_pane=controller_pane,
                                message=f"[ai-collab relay] {agent} rejected step_done nonce mismatch for {evt_step}",
                                run_store=run_store,
                                event_type="subagent_event_rejected",
                                source="relay",
                                agent=agent,
                                payload={"reason": "nonce_mismatch", "event": event},
                            )
                            continue
                        if evt_step:
                            seen_steps.add(evt_step)
                            if run_store is not None:
                                run_store.set_step_status(
                                    step_id=evt_step,
                                    status="done",
                                    agent=agent,
                                    nonce=evt_nonce or expected_nonce,
                                    summary=str(event.get("summary", "")).strip(),
                                )
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} step done -> {evt_step}",
                            run_store=run_store,
                            event_type="step_done",
                            source="subagent_event",
                            agent=agent,
                            payload=event,
                        )
                        continue

                    if evt_type in {"subagent_complete", "task_complete"}:
                        if run_store is not None:
                            run_store.set_agent_status(agent=agent, status="completed")
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} reported completion.",
                            run_store=run_store,
                            event_type="subagent_complete",
                            source="subagent_event",
                            agent=agent,
                            payload=event,
                        )
                        _notify_controller_to_confirm_subagent_close(
                            controller_pane=controller_pane,
                            agent=agent,
                            pane_id=subagent_pane,
                        )
                        return

                    if evt_type in {"handoff_to", "spawn_agent"}:
                        target = str(event.get("target", "")).strip().lower()
                        if target and target not in seen_handoffs:
                            seen_handoffs.add(target)
                            _emit_relay_event(
                                cwd=cwd,
                                session=session,
                                controller_pane=controller_pane,
                                message=f"[ai-collab relay] {agent} requested handoff -> {target}",
                                run_store=run_store,
                                event_type="handoff_request",
                                source="subagent_event",
                                agent=agent,
                                payload=event,
                            )

                # Legacy marker compatibility (only parse new delta to reduce false positives).
                for step_id in _extract_step_done_ids(delta):
                    sid = step_id.strip()
                    if sid and sid not in seen_steps:
                        seen_steps.add(sid)
                        if run_store is not None:
                            run_store.set_step_status(step_id=sid, status="done", agent=agent)
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} step done -> {sid}",
                            run_store=run_store,
                            event_type="step_done_legacy",
                            source="legacy_marker",
                            agent=agent,
                            payload={"step_id": sid},
                        )
                for target in _extract_handoff_targets(delta):
                    next_agent = target.strip().lower()
                    if next_agent and next_agent not in seen_handoffs:
                        seen_handoffs.add(next_agent)
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} requested handoff -> {next_agent}",
                            run_store=run_store,
                            event_type="handoff_request_legacy",
                            source="legacy_marker",
                            agent=agent,
                            payload={"target": next_agent},
                        )
                if _contains_completion_marker(delta):
                    if run_store is not None:
                        run_store.set_agent_status(agent=agent, status="completed")
                    _emit_relay_event(
                        cwd=cwd,
                        session=session,
                        controller_pane=controller_pane,
                        message=f"[ai-collab relay] {agent} reported completion.",
                        run_store=run_store,
                        event_type="subagent_complete_legacy",
                        source="legacy_marker",
                        agent=agent,
                    )
                    _notify_controller_to_confirm_subagent_close(
                        controller_pane=controller_pane,
                        agent=agent,
                        pane_id=subagent_pane,
                    )
                    return
            issue_now = time.monotonic()
            idle_now = issue_now - last_progress
            if run_store is not None:
                for runtime_id in _extract_runtime_session_ids(delta):
                    run_store.set_agent_runtime_session_id(agent=agent, runtime_session_id=runtime_id)
            issue = _classify_watch_issue(delta) or _classify_watch_issue(tail)
            if issue:
                if issue != active_issue:
                    active_issue = issue
                    active_issue_since = issue_now
                elif (
                    active_issue_since > 0
                    and issue_now - active_issue_since >= issue_grace_seconds
                    and idle_now >= min(issue_grace_seconds, 10.0)
                ):
                    if run_store is not None:
                        run_store.set_agent_status(agent=agent, status=f"error_{issue}", detail=issue)
                    _emit_relay_event(
                        cwd=cwd,
                        session=session,
                        controller_pane=controller_pane,
                        message=f"[ai-collab relay] {agent} error detected: {issue}.",
                        run_store=run_store,
                        event_type="subagent_error_detected",
                        source="relay_issue",
                        agent=agent,
                        payload={
                            "reason": issue,
                            "idle_seconds": int(idle_now),
                            "issue_persisted_seconds": int(issue_now - active_issue_since),
                        },
                    )
                    return
            else:
                active_issue = ""
                active_issue_since = 0.0
            now = time.monotonic()
            idle_for = now - last_progress
            if not soft_timeout_emitted and idle_for >= soft_timeout:
                soft_timeout_emitted = True
                if run_store is not None:
                    run_store.set_agent_status(agent=agent, status="waiting_timeout_soft")
                _emit_relay_event(
                    cwd=cwd,
                    session=session,
                    controller_pane=controller_pane,
                    message=f"[ai-collab relay] {agent} still running (soft-timeout={int(soft_timeout)}s).",
                    run_store=run_store,
                    event_type="subagent_soft_timeout",
                    source="relay_timeout",
                    agent=agent,
                    payload={"idle_seconds": int(idle_for), "soft_timeout_seconds": int(soft_timeout)},
                )
            if idle_for >= hard_timeout:
                if run_store is not None:
                    run_store.set_agent_status(agent=agent, status="timeout_hard")
                _emit_relay_event(
                    cwd=cwd,
                    session=session,
                    controller_pane=controller_pane,
                    message=f"[ai-collab relay] {agent} timed out (hard-timeout={int(hard_timeout)}s).",
                    run_store=run_store,
                    event_type="subagent_hard_timeout",
                    source="relay_timeout",
                    agent=agent,
                    payload={"idle_seconds": int(idle_for), "hard_timeout_seconds": int(hard_timeout)},
                )
                return
            time.sleep(1.0)

    threading.Thread(target=_runner, name=f"ai-collab-subagent-relay-{agent}", daemon=True).start()


def _spawn_subagent_with_prompt(
    *,
    session: str,
    controller_pane: str,
    controller: str,
    agent: str,
    task: str,
    steps: list[dict],
    cwd: Path,
    lang: str,
    run_store: Optional[RunStateStore] = None,
) -> str:
    roles = ", ".join(step.get("role", "") for step in steps if step.get("role"))
    task_desc = f"roles: {roles}" if roles else "collaboration role"
    step_tickets = _build_step_tickets(steps)
    primary_step = steps[0] if steps else {}
    pane_id = spawn_subagent_pane(
        session=session,
        controller_pane=controller_pane,
        agent=agent,
        cwd=cwd,
        task_description=task_desc,
        agent_cmd=_tmux_agent_startup_command(
            agent,
            selected_cli=str(primary_step.get("selected_cli", "")).strip(),
            model=str(primary_step.get("selected_model", "")).strip(),
            profile=str(primary_step.get("profile", "")).strip(),
        ),
    )
    if run_store is not None:
        run_store.bind_agent(agent=agent, pane_id=pane_id, step_tickets=step_tickets)
        run_store.set_phase(
            phase="subagent_spawned",
            detail=f"{agent}:{pane_id}",
            source="controller",
        )
        run_store.append_event(
            event_type="subagent_spawned",
            source="controller",
            agent=agent,
            payload={
                "pane_id": pane_id,
                "step_ids": [ticket.get("step_id", "") for ticket in step_tickets],
            },
        )
        _record_tmux_layout_snapshot(
            run_store=run_store,
            session=session,
            reason=f"spawn:{agent}",
        )
    sub_prompt = _build_subagent_prompt(
        task=task,
        steps=steps,
        lang=lang,
        controller=controller,
        run_id=run_store.run_id if run_store is not None else "unknown",
        step_tickets=step_tickets,
    )
    briefing_file = _write_briefing_file(
        cwd=cwd,
        role="subagent",
        agent=agent,
        text=sub_prompt,
    )
    console.print(f"[dim]{_auto_msg(lang, 'brief_saved', path=str(briefing_file))}[/dim]")
    dispatch_text = _build_prompt_dispatch_message(
        lang=lang,
        path=briefing_file,
        role="subagent",
        agent=agent,
    )
    injected = _inject_prompt_to_pane(
        pane_id=pane_id,
        text=dispatch_text,
        agent=agent,
    )
    if not injected:
        console.print(
            f"[yellow]{_auto_msg(lang, 'prompt_inject_failed', agent=agent, pane=pane_id)}[/yellow]"
        )
    _start_subagent_status_relay(
        session=session,
        cwd=cwd,
        subagent_pane=pane_id,
        controller_pane=controller_pane,
        agent=agent,
        run_store=run_store,
        expected_step_nonces={ticket.get("step_id", ""): ticket.get("nonce", "") for ticket in step_tickets},
    )
    return pane_id


def _start_handoff_watcher(
    *,
    session: str,
    controller_pane: str,
    controller: str,
    task: str,
    agent_roles: dict[str, list[dict]],
    cwd: Path,
    lang: str,
    run_store: Optional[RunStateStore] = None,
) -> None:
    """
    Watch controller output and auto-spawn sub-agent panes on handoff markers.

    Markers:
    - HANDOFF_TO: <agent>
    - SPAWN_AGENT: <agent>
    """
    if not agent_roles:
        return

    canonical: dict[str, str] = {name.lower(): name for name in agent_roles.keys()}
    spawned: set[str] = set()

    def _runner() -> None:
        unchanged = 0
        last_tail = ""
        seeded = False
        while True:
            try:
                snapshot = capture_pane_text(pane_id=controller_pane, start_line=-260)
            except subprocess.CalledProcessError:
                unchanged += 1
                if unchanged >= 8:
                    return
                time.sleep(1.0)
                continue

            tail = snapshot[-5000:]
            if not seeded:
                seeded = True
                last_tail = tail
                time.sleep(1.0)
                continue
            if tail == last_tail:
                unchanged += 1
            else:
                unchanged = 0
                delta = tail[len(last_tail):] if tail.startswith(last_tail) else tail
                last_tail = tail
                if run_store is not None:
                    for runtime_id in _extract_runtime_session_ids(delta):
                        run_store.set_controller_runtime_session_id(runtime_session_id=runtime_id)
                    _sync_controller_progress_from_text(
                        run_store=run_store,
                        text=delta,
                        source="controller_marker",
                    )
                for match in _extract_handoff_targets(tail):
                    key = match.lower()
                    agent = canonical.get(key)
                    if not agent or agent == controller or agent in spawned:
                        continue
                    try:
                        _spawn_subagent_with_prompt(
                            session=session,
                            controller_pane=controller_pane,
                            controller=controller,
                            agent=agent,
                            task=task,
                            steps=agent_roles.get(agent, []),
                            cwd=cwd,
                            lang=lang,
                            run_store=run_store,
                        )
                        spawned.add(agent)
                    except Exception as exc:  # noqa: BLE001
                        console.print(f"[yellow]handoff watcher spawn failed for {agent}: {exc}[/yellow]")
            if unchanged >= 120:
                return
            time.sleep(1.0)

    threading.Thread(target=_runner, name="ai-collab-handoff-watcher", daemon=True).start()


def _print_orchestration_plan(result, *, lang: str) -> None:
    available = getattr(result, "available_agents", None) or []
    plan = getattr(result, "orchestration_plan", None) or []
    if not available and not plan:
        return

    rows = [
        (_auto_msg(lang, "mode"), str(getattr(result, "execution_mode", "single-agent"))),
    ]
    selected_agents = getattr(result, "selected_agents", None) or []
    if selected_agents:
        rows.append((_auto_msg(lang, "selected_agents"), ", ".join(selected_agents)))

    lines: list[str] = []
    if available:
        lines.append(f"{_auto_msg(lang, 'available_agents')}:")
        for item in available:
            agent = item.get("agent", "")
            model = item.get("selected_model", "")
            profile = item.get("model_profile", "")
            strengths = item.get("strengths", "")
            lines.append(f"- {agent}: model={model} profile={profile} strengths={strengths}")

    if plan:
        lines.append(f"{_auto_msg(lang, 'role_assignment')}:")
        for step in plan:
            role = step.get("role", "")
            agent = step.get("agent", "")
            model = step.get("selected_model", "")
            reason = step.get("reason", "")
            lines.append(f"- {role} -> {agent} ({model}) [{reason}]")

    console.print()
    console.print(render_tmux_block(_auto_msg(lang, "plan_title"), rows=rows, lines=lines))


def _print_available_agents(result, *, lang: str) -> None:
    """Print available agents without showing pre-generated role assignment."""
    available = result.available_agents or []
    if not available:
        return
    lines: list[str] = []
    for item in available:
        agent = item.get("agent", "")
        model = item.get("selected_model", "")
        profile = item.get("model_profile", "")
        strengths = item.get("strengths", "")
        lines.append(f"- {agent}: model={model} profile={profile} strengths={strengths}")
    console.print()
    console.print(render_tmux_block(_auto_msg(lang, "available_agents_only"), lines=lines))


def _can_launch_tmux(result) -> bool:
    if shutil.which("tmux") is None:
        return False
    return bool(
        getattr(result, "execution_mode", "single-agent") == "multi-agent"
        and (getattr(result, "orchestration_plan", None) or [])
    )


def _tmux_session_exists(session: str) -> bool:
    if shutil.which("tmux") is None:
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _resolve_tmux_session_name(preferred: str) -> str:
    if not preferred or not _tmux_session_exists(preferred):
        return preferred
    stamp = datetime.now().strftime("%H%M%S")
    candidate = f"{preferred}-{stamp}"
    index = 2
    while _tmux_session_exists(candidate):
        candidate = f"{preferred}-{stamp}-{index}"
        index += 1
    return candidate


def _launch_tmux_orchestration(
    *,
    task: str,
    controller: str,
    result,
    session: str = "ai-collab-live",
    lang: str = "en-US",
    prewarm_subagents: bool = False,
    controller_prompt_override: Optional[str] = None,
    tmux_target: str = "session",
) -> bool:
    if not _can_launch_tmux(result):
        return False

    available_agents = list(getattr(result, "available_agents", None) or [])
    cwd = Path.cwd()
    use_inline = tmux_target == "inline"
    if tmux_target == "auto":
        use_inline = bool(os.environ.get("TMUX"))
    if use_inline and not os.environ.get("TMUX"):
        use_inline = False

    if use_inline:
        try:
            controller_info = next(
                (
                    item for item in available_agents
                    if str(item.get("agent", "")).strip() == controller
                ),
                {},
            )
            resolved_session, controller_pane = create_inline_controller_workspace(
                cwd=cwd,
                controller=controller,
                autorun=True,
                agent_cmd=_tmux_agent_startup_command(
                    controller,
                    selected_cli=str(controller_info.get("selected_cli", "")).strip(),
                    model=str(controller_info.get("selected_model", "")).strip(),
                    profile=str(controller_info.get("model_profile", "")).strip(),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{_auto_msg(lang, 'tmux_failed')}[/red] {exc}")
            return False
    else:
        resolved_session = _resolve_tmux_session_name(session)
        if resolved_session != session:
            console.print(
                f"[yellow]{_auto_msg(lang, 'tmux_session_renamed', old=session, new=resolved_session)}[/yellow]"
            )
        try:
            controller_info = next(
                (
                    item for item in available_agents
                    if str(item.get("agent", "")).strip() == controller
                ),
                {},
            )
            controller_pane = create_controller_workspace(
                session=resolved_session,
                cwd=cwd,
                controller=controller,
                reset=False,
                autorun=True,
                agent_cmd=_tmux_agent_startup_command(
                    controller,
                    selected_cli=str(controller_info.get("selected_cli", "")).strip(),
                    model=str(controller_info.get("selected_model", "")).strip(),
                    profile=str(controller_info.get("model_profile", "")).strip(),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{_auto_msg(lang, 'tmux_failed')}[/red] {exc}")
            return False

    plan = list(result.orchestration_plan or [])
    controller_roles = [item.get("role", "") for item in plan if item.get("agent") == controller]
    pending_lines = []
    for step in plan:
        agent = str(step.get("agent", "")).strip()
        if not agent or agent == controller:
            continue
        pending_lines.append(
            f"- {agent}: {step.get('role', '')} (model={step.get('selected_model', '')})"
        )

    controller_prompt = controller_prompt_override
    if not controller_prompt and controller_roles:
        generated_prompt = (
            f"{_auto_msg(lang, 'controller_title')}\n"
            f"- {_auto_msg(lang, 'brief_user_task')}: {task}\n"
            f"- {_auto_msg(lang, 'brief_roles')}: {', '.join(controller_roles)}\n"
            f"- {_auto_msg(lang, 'brief_delegate')}\n"
            f"- {_auto_msg(lang, 'brief_end')}"
        )
        if pending_lines:
            generated_prompt += (
                f"\n- {_auto_msg(lang, 'brief_plan_pending')}\n" + "\n".join(pending_lines)
            )
        controller_prompt = generated_prompt

    controller_prompt_ready = True
    entry_prompt_text = ""
    if controller_prompt:
        briefing_file = _write_briefing_file(
            cwd=cwd,
            role="controller",
            agent=controller,
            text=controller_prompt,
        )
        console.print(f"[dim]{_auto_msg(lang, 'brief_saved', path=str(briefing_file))}[/dim]")
        dispatch_text = _build_prompt_dispatch_message(
            lang=lang,
            path=briefing_file,
            role="controller",
            agent=controller,
        )
        entry_prompt_text = dispatch_text
        injected = _inject_prompt_to_pane(
            pane_id=controller_pane,
            text=dispatch_text,
            agent=controller,
        )
        if not injected:
            console.print(
                f"[yellow]{_auto_msg(lang, 'prompt_inject_failed', agent=controller, pane=controller_pane)}[/yellow]"
            )
            controller_prompt_ready = False

    run_store = RunStateStore.create(
        cwd=cwd,
        session=resolved_session,
        controller_agent=controller,
        controller_pane=controller_pane,
    )
    run_store.set_mode(mode="tmux")
    run_store.set_entry_prompt(text=entry_prompt_text or controller_prompt or task)
    run_store.set_phase(
        phase="controller_started",
        detail=f"{controller}:{controller_pane}",
        source="controller",
    )
    run_store.append_event(
        event_type="run_started",
        source="controller",
        agent=controller,
        payload={
            "task": task,
            "entry_prompt_preview": (entry_prompt_text or controller_prompt or task)[:240],
            "execution_mode": "tmux",
            "tmux_target": tmux_target,
            "prewarm_subagents": prewarm_subagents,
        },
    )
    _record_tmux_layout_snapshot(
        run_store=run_store,
        session=resolved_session,
        reason="run_started",
    )
    console.print()
    console.print(
        render_tmux_block(
            _auto_msg(lang, "tmux_ready"),
            rows=[("session", resolved_session), ("run_id", run_store.run_id)],
            lines=[_auto_msg(lang, "tmux_logs", path=str(pane_logs_dir(cwd=cwd, session=resolved_session)))],
        )
    )

    agent_roles: dict[str, list[dict]] = {}
    for step in plan:
        agent = str(step.get("agent", "")).strip()
        if not agent or agent == controller:
            continue
        agent_roles.setdefault(agent, []).append(step)

    if prewarm_subagents:
        for agent, steps in agent_roles.items():
            _spawn_subagent_with_prompt(
                session=resolved_session,
                controller_pane=controller_pane,
                agent=agent,
                task=task,
                steps=steps,
                cwd=cwd,
                lang=lang,
                controller=controller,
                run_store=run_store,
            )
    else:
        if controller_prompt_ready:
            _start_handoff_watcher(
                session=resolved_session,
                controller_pane=controller_pane,
                controller=controller,
                task=task,
                agent_roles=agent_roles,
                cwd=cwd,
                lang=lang,
                run_store=run_store,
            )
        else:
            console.print(f"[yellow]{_auto_msg(lang, 'watcher_skipped')}[/yellow]")

    if not use_inline:
        attach_session(session=resolved_session)
    return True


def _resolve_orchestrator_skill_source() -> Optional[Path]:
    """Resolve install source directory for ai-collab-orchestrator skill."""
    candidates = [
        # Packaged source for GitHub/PyPI distribution.
        Path(__file__).parent / "skills" / "ai-collab-orchestrator",
        # Local development fallback.
        Path(__file__).parent.parent / ".claude" / "skills" / "ai-collab-orchestrator",
    ]
    for candidate in candidates:
        if (candidate / "SKILL.md").exists():
            return candidate
    return None


def _install_ai_collab_skills(enabled_providers: list[str], lang: str) -> None:
    """
    Install ai-collab-orchestrator skill links for enabled agents.
    """
    import shutil

    skill_source = _resolve_orchestrator_skill_source()
    if not skill_source:
        console.print(f"[yellow]{'警告: ai-collab-orchestrator skill 不存在' if lang == 'zh-CN' else 'Warning: ai-collab-orchestrator skill not found'}[/yellow]")
        return

    installed_count = 0

    # Claude skills
    claude_skills_dir = Path.home() / ".claude" / "skills"
    if "claude" in enabled_providers:
        claude_skills_dir.mkdir(parents=True, exist_ok=True)
        target = claude_skills_dir / "ai-collab-orchestrator"

        if target.exists():
            if target.is_symlink():
                target.unlink()
            else:
                shutil.rmtree(target)

        target.symlink_to(skill_source)
        console.print(f"  ✓ Claude: {target}")
        installed_count += 1

    # cc-switch mirror (if present)
    cc_switch_dir = Path.home() / ".cc-switch" / "skills"
    if cc_switch_dir.exists():
        target = cc_switch_dir / "ai-collab-orchestrator"

        if target.exists():
            if target.is_symlink():
                target.unlink()
            else:
                shutil.rmtree(target)

        shutil.copytree(skill_source, target, dirs_exist_ok=True)
        console.print(f"  ✓ cc-switch: {target}")
        installed_count += 1

    # Codex skills
    codex_skills_dir = Path.home() / ".codex" / "skills"
    if "codex" in enabled_providers:
        codex_skills_dir.mkdir(parents=True, exist_ok=True)
        target = codex_skills_dir / "ai-collab-orchestrator"

        if target.exists():
            if target.is_symlink():
                target.unlink()
            else:
                shutil.rmtree(target)

        target.symlink_to(skill_source)
        console.print(f"  ✓ Codex: {target}")
        installed_count += 1

    # Gemini skills
    gemini_skills_dir = Path.home() / ".gemini" / "skills"
    if "gemini" in enabled_providers:
        gemini_skills_dir.mkdir(parents=True, exist_ok=True)
        target = gemini_skills_dir / "ai-collab-orchestrator"

        if target.exists():
            if target.is_symlink():
                target.unlink()
            else:
                shutil.rmtree(target)

        target.symlink_to(skill_source)
        console.print(f"  ✓ Gemini: {target}")
        installed_count += 1

    if installed_count > 0:
        console.print(f"\n[green]✓ {'已安装 ai-collab-orchestrator skill 到' if lang == 'zh-CN' else 'Installed ai-collab-orchestrator skill to'} {installed_count} {'个 Agent' if lang == 'zh-CN' else 'agents'}[/green]")
    else:
        console.print(f"[yellow]{'未安装任何 skill' if lang == 'zh-CN' else 'No skills installed'}[/yellow]")




def _run_init_wizard(config_obj: Config, *, ui_mode: str = "text") -> None:
    """Interactive setup: Language -> Agents -> Controller -> Responsibility Map."""
    questionary = None
    if ui_mode == "tui":
        import questionary as _questionary

        questionary = _questionary

    # Step 1: select UI language.
    lang_default = _resolve_runtime_language(cli_lang=None, config_lang=config_obj.ui_language)
    if questionary:
        lang = questionary.select(
            _msg(lang_default, "language_prompt"),
            choices=[
                questionary.Choice("English (en-US)", value="en-US"),
                questionary.Choice("中文 (zh-CN)", value="zh-CN"),
            ],
            style=_questionary_style(questionary),
        ).ask()
        if not lang:
            raise click.Abort()
    else:
        lang = Prompt.ask(
            _msg(lang_default, "language_prompt"),
            choices=["en-US", "zh-CN"],
            default=lang_default,
        )
    config_obj.ui_language = lang

    console.print(f"\n[bold]{'🧭 初始化向导' if lang == 'zh-CN' else '🧭 Init Wizard'}[/bold]")
    console.print(f"{'配置主控与协作策略' if lang == 'zh-CN' else 'Configure controller and collaboration strategy'}\n")

    # Step 2: detect local agent availability.
    os_name = detect_os_name()
    runtime = detect_provider_status(config_obj.providers, os_name=os_name)
    console.print(f"{'检测到的系统' if lang == 'zh-CN' else 'Detected OS'}: [cyan]{_format_os_name(os_name)}[/cyan]")

    table = Table(title="可用的 Agents" if lang == "zh-CN" else "Available Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Command", style="white")
    table.add_column("Available", style="yellow")
    table.add_column("Path", style="dim")
    for name in ["codex", "claude", "gemini"]:
        if name not in config_obj.providers:
            continue
        status = runtime.get(name)
        available = _msg(lang, "yes_label") if status and status.available else _msg(lang, "no_label")
        path = status.resolved_path if status else ""
        command = status.executable if status else ""
        table.add_row(_provider_display_rich(name, include_brand=True), command, available, path)
    console.print(table)

    # Step 3: enable agents.
    console.print(f"\n[bold]{'选择启用的 Agents' if lang == 'zh-CN' else 'Select enabled Agents'}[/bold]")
    enabled_providers: list[str] = []
    for name in ["codex", "claude", "gemini"]:
        provider = config_obj.providers.get(name)
        if not provider:
            continue
        available = bool(runtime.get(name) and runtime[name].available)
        prompt = f"{'启用' if lang == 'zh-CN' else 'Enable'} {_provider_display_plain(name)}?"
        if not available:
            prompt += f" ({'命令未找到' if lang == 'zh-CN' else 'command not found'})"
        use_it = _ask_yes_no(
            prompt,
            lang=lang,
            questionary_module=questionary,
            default_yes=bool(provider.enabled and available),
            provider=name,
        )
        provider.enabled = bool(use_it and available)
        if provider.enabled:
            enabled_providers.append(name)

    if not enabled_providers:
        fallback = next((name for name in ["codex", "claude", "gemini"] if runtime.get(name) and runtime[name].available), None)
        if fallback is None:
            fallback = "codex" if "codex" in config_obj.providers else next(iter(config_obj.providers))
        config_obj.providers[fallback].enabled = True
        enabled_providers = [fallback]
        console.print(f"[yellow]{'未选择任何 Agent，已启用' if lang == 'zh-CN' else 'No agent selected, enabled'} {_provider_display_plain(fallback)}[/yellow]")

    # Step 4: run quick command availability checks (no provider CLI probe).
    console.print(f"\n[bold]{'检查 Agent 命令可用性' if lang == 'zh-CN' else 'Checking agent command availability'}[/bold]")
    failed_agents = []
    for agent_name in enabled_providers:
        console.print(f"  {_provider_display_plain(agent_name)}...", end="")
        health_ok, health_msg = _quick_health_check(agent_name)
        if health_ok:
            console.print(" [green]✓[/green]")
        else:
            console.print(f" [red]✗ {health_msg}[/red]")
            failed_agents.append((agent_name, health_msg))

    if failed_agents:
        console.print(f"\n[yellow]{'警告：部分 Agent 命令不可用' if lang == 'zh-CN' else 'Warning: Some agent commands are unavailable'}[/yellow]")
        for agent_name, error_msg in failed_agents:
            console.print(f"  • {_provider_display_plain(agent_name)}: {error_msg}")

        continue_anyway = _ask_yes_no(
            "是否继续？" if lang == "zh-CN" else "Continue anyway?",
            lang=lang,
            questionary_module=questionary,
            default_yes=False,
        )
        if not continue_anyway:
            console.print(f"[red]{'初始化已取消' if lang == 'zh-CN' else 'Initialization cancelled'}[/red]")
            return

    # Step 5: select controller.
    console.print(f"\n[bold]{'选择主控 Agent' if lang == 'zh-CN' else 'Select Controller Agent'}[/bold]")
    controller_default = (
        config_obj.current_controller if config_obj.current_controller in enabled_providers else enabled_providers[0]
    )
    controller = _select_decision(
        "主控:" if lang == "zh-CN" else "Controller:",
        [(name, _provider_display_plain(name)) for name in enabled_providers],
        questionary_module=questionary,
        default_value=controller_default,
        provider=controller_default,
    )
    config_obj.current_controller = controller

    # Step 6: show default responsibility map.
    console.print(f"\n✓ {'主控' if lang == 'zh-CN' else 'Controller'}: {_provider_display_plain(controller)}")
    console.print(f"\n[bold]{'默认职责分配 (Three brains, one system)' if lang == 'zh-CN' else 'Default Responsibility Map (Three brains, one system)'}[/bold]\n")

    # Render role ownership summary.
    console.print(f"  🔴 [cyan]Codex[/cyan]")
    console.print(f"     {'擅长: 代码实现深度' if lang == 'zh-CN' else 'Expertise: Code implementation depth'}")
    console.print(f"     {'• 后端 API、前端组件、算法实现' if lang == 'zh-CN' else '• Backend API, frontend components, algorithms'}")
    console.print(f"     {'负责: 代码实现、Develop 阶段' if lang == 'zh-CN' else 'Responsible: Code implementation, Develop phase'}\n")

    console.print(f"  🟡 [cyan]Gemini[/cyan]")
    console.print(f"     {'擅长: 生态广度与安全' if lang == 'zh-CN' else 'Expertise: Ecosystem breadth & security'}")
    console.print(f"     {'• 开源方案、UI/UX 设计、安全审查' if lang == 'zh-CN' else '• Open source, UI/UX design, security audit'}")
    console.print(f"     {'负责: 技术调研、Discover 阶段' if lang == 'zh-CN' else 'Responsible: Research, Discover phase'}\n")

    console.print(f"  🔵 [cyan]Claude[/cyan]")
    console.print(f"     {'擅长: 综合分析与质量把关' if lang == 'zh-CN' else 'Expertise: Analysis & quality gate'}")
    console.print(f"     {'• 代码审查、权衡利弊、最终决策' if lang == 'zh-CN' else '• Code review, trade-offs, final decisions'}")
    console.print(f"     {'负责: 质量审查、Define/Deliver 阶段' if lang == 'zh-CN' else 'Responsible: Quality review, Define/Deliver phases'}\n")

    # Step 7: confirm default assignment map.
    use_default_allocation = _ask_yes_no(
        "使用默认职责分配？" if lang == "zh-CN" else "Use default responsibility map?",
        lang=lang,
        questionary_module=questionary,
        default_yes=True,
    )

    assignment_map: dict[str, dict[str, str]] = {}
    if use_default_allocation:
        for item in WORK_ALLOCATION_ITEMS:
            selected_agent = item["agent"] if item["agent"] in enabled_providers else enabled_providers[0]
            assignment_map[item["key"]] = {"agent": selected_agent, "profile": item["profile"]}
    else:
        console.print(f"\n[bold]{'自定义职责分配' if lang == 'zh-CN' else 'Custom Responsibility Map'}[/bold]")
        for index, item in enumerate(WORK_ALLOCATION_ITEMS, start=1):
            role_name = _role_label(item, lang)
            default_agent = item["agent"] if item["agent"] in enabled_providers else enabled_providers[0]

            selected_agent = _select_decision(
                f"{index}. {role_name}:",
                [(name, _provider_display_plain(name)) for name in enabled_providers],
                questionary_module=questionary,
                default_value=default_agent,
            )
            assignment_map[item["key"]] = {"agent": selected_agent, "profile": item["profile"]}

    # Step 8: persist assignment configuration.
    auto_cfg = _set_auto_orchestration(dict(config_obj.auto_collaboration or {}), True)
    auto_cfg["assignments"] = assignment_map
    auto_cfg["consensus_threshold"] = 0.75
    config_obj.auto_collaboration = auto_cfg

    # Step 9: install orchestrator skills for enabled agents.
    console.print(f"\n[bold]{'安装 Skills' if lang == 'zh-CN' else 'Installing Skills'}[/bold]")
    _install_ai_collab_skills(enabled_providers, lang)

    # Step 10: print completion summary.
    console.print(f"\n[green]✓ {'配置已保存' if lang == 'zh-CN' else 'Configuration saved'}[/green]")
    console.print(f"\n{'主控' if lang == 'zh-CN' else 'Controller'}: {_provider_display_plain(controller)}")
    console.print(f"{'职责分配' if lang == 'zh-CN' else 'Responsibility map'}: {'默认' if use_default_allocation else '自定义' if lang == 'zh-CN' else 'Default' if use_default_allocation else 'Custom'}")
    console.print(f"\n{'现在可以使用' if lang == 'zh-CN' else 'Now you can use'}:")
    console.print(f"  ai-collab \"{'实现用户登录功能' if lang == 'zh-CN' else 'implement user login'}\"")

    auto_cfg = _set_auto_orchestration(dict(config_obj.auto_collaboration or {}), True)
    auto_cfg["consensus_threshold"] = 0.75
    auto_cfg["assignment_map"] = assignment_map
    auto_cfg["role_allocation"] = {
        "code_patterns": assignment_map.get("code_patterns", {}).get("agent", "codex"),
        "ecosystem_breadth": assignment_map.get("ecosystem_research", {}).get("agent", "gemini"),
        "synthesis": assignment_map.get("synthesis", {}).get("agent", "claude"),
    }
    auto_cfg["phase_routing"] = {
        "discover": assignment_map.get("discover", {}).get("agent", "gemini"),
        "define": assignment_map.get("define", {}).get("agent", "claude"),
        "develop": assignment_map.get("develop", {}).get("agent", "codex"),
        "deliver": assignment_map.get("deliver", {}).get("agent", "claude"),
    }
    auto_cfg["persona_auto_assign"] = True
    auto_cfg["persona_phase_map"] = {
        "discover": "research-analyst",
        "define": "requirements-architect",
        "develop": "implementation-engineer",
        "deliver": "quality-auditor",
    }
    auto_cfg["persona_skill_map"] = {
        "research-analyst": ["ecosystem-research", "alternatives-matrix"],
        "requirements-architect": ["scope-control", "tradeoff-analysis"],
        "implementation-engineer": ["feature-implementation", "integration-check"],
        "quality-auditor": ["code-review", "risk-review"],
        "security-auditor": ["security-review", "owasp-checklist"],
    }
    auto_cfg["phase_completion_criteria"] = {
        "default": {"min_output_chars": 30, "must_succeed": True},
        "discover": {"min_output_chars": 80},
        "define": {"min_output_chars": 60},
        "develop": {"min_output_chars": 80},
        "deliver": {"min_output_chars": 60},
    }
    auto_cfg["escalation_policy"] = {
        "max_retries": 1,
        "takeover_agent": "codex",
        "takeover_after_failures": 2,
        "ask_user_on_repeated_failure": True,
        "stop_on_failure": True,
    }
    config_obj.auto_collaboration = auto_cfg

    # Select controller for legacy init flow.
    console.print(f"\n[bold]{_msg(lang, 'step_controller')}[/bold]")
    controller_default = (
        config_obj.current_controller if config_obj.current_controller in enabled_providers else enabled_providers[0]
    )
    controller = _select_decision(
        _msg(lang, "controller_prompt"),
        [(name, _provider_display_plain(name)) for name in enabled_providers],
        questionary_module=questionary,
        default_value=controller_default,
        provider=controller_default,
    )
    config_obj.current_controller = controller

    # Optional demo run.
    console.print(f"\n[bold]{_msg(lang, 'step_demo')}[/bold]")
    run_demo = _ask_yes_no(
        _msg(lang, "run_demo_prompt"),
        lang=lang,
        questionary_module=questionary,
        default_yes=False,
    )
    if run_demo:
        # Prefer questionary text input for consistent terminal encoding behavior.
        try:
            demo_prompt = questionary.text(
                _msg(lang, "demo_task_prompt"),
                default=_msg(lang, "demo_task_default")
            ).ask()
            if demo_prompt is None:  # User cancelled input.
                console.print("[yellow]Demo 已取消[/yellow]")
                return
        except Exception as e:
            console.print(f"[red]输入错误: {e}[/red]")
            console.print("[yellow]跳过 demo 测试[/yellow]")
            return
        demo_session = "ai-collab-demo"
        try:
            create_tmux_workspace(
                session=demo_session,
                cwd=Path.cwd(),
                controller=config_obj.current_controller,
                layout="stacked",
                autorun_agents=True,
                reset=True,
                task_hint=demo_prompt,
            )
            console.print(f"[green]{_msg(lang, 'demo_ready', session=demo_session)}[/green]")
            console.print(_msg(lang, "demo_attach", session=demo_session))
            console.print(f"\n{_msg(lang, 'demo_paste')}")
            console.print(
                f"ai-collab --provider {config_obj.current_controller} "
                f"\"{demo_prompt}\""
            )
            attach_now = _ask_yes_no(
                _msg(lang, "demo_attach_now"),
                lang=lang,
                questionary_module=questionary,
                default_yes=True,
            )
            if attach_now:
                subprocess.run(["tmux", "attach-session", "-t", demo_session], check=False)
        except TmuxWorkspaceError as exc:
            console.print(f"[red]tmux workspace error:[/red] {exc}")
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]tmux command failed:[/red] {exc}")

    console.print(f"\n[green]{_msg(lang, 'wizard_done')}[/green]")



def runner_main(argv: Optional[list[str]] = None, *, prog_name: str = "ai-collab") -> None:
    """Entry point for task-runner mode."""
    config = Config.load()
    providers = set(config.providers.keys())

    raw_args = list(argv) if argv is not None else sys.argv[1:]
    provider_prefix = None

    # Backward compatibility: <runner> codex "task..."
    if raw_args and raw_args[0] in providers and "--provider" not in raw_args and "-p" not in raw_args:
        provider_prefix = raw_args[0]
        raw_args = raw_args[1:]

    parser = argparse.ArgumentParser(prog=prog_name, description="Auto-detect and run collaboration workflow")
    parser.add_argument("task", nargs="*", help="Task description")
    parser.add_argument("-p", "--provider", choices=sorted(providers), help="Current controller/provider")
    parser.add_argument("--controller", dest="provider", choices=sorted(providers), help="Alias of --provider")
    parser.add_argument("--prompt", help="Task text alias of positional [task...]")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Only print the plan, do not execute")
    parser.add_argument("-o", "--output", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("-l", "--lang", choices=sorted(I18N.keys()), help="Force UI language for this run")
    parser.add_argument("-u", "--ui-mode", choices=["auto", "tui", "text"], default="auto", help="Decision UI mode")
    parser.add_argument(
        "-x",
        "--execution-mode",
        choices=["auto", "direct", "tmux"],
        default=None,
        help="Execution mode for collaboration workflow",
    )
    parser.add_argument(
        "--mode",
        dest="execution_mode",
        choices=["auto", "direct", "tmux"],
        help="Alias of --execution-mode",
    )
    parser.add_argument(
        "-W",
        "--tmux-prewarm-subagents",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Pre-create sub-agent panes when entering tmux mode",
    )
    parser.add_argument(
        "-t",
        "--tmux-target",
        choices=["auto", "session", "inline"],
        default="auto",
        help="tmux launch target: new session or inline panes in current tmux window",
    )
    parser.add_argument(
        "-i",
        "--auto-install-deps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto install missing TUI dependencies",
    )
    parser.add_argument(
        "-I",
        "--interactive-decisions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ask for decisions before execution",
    )
    parser.add_argument(
        "-a",
        "--allow-nested",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=f"Allow running {prog_name} inside an existing ai-collab tmux session",
    )
    parser.add_argument(
        "-e",
        "--edit-controller-prompt",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Open editable controller prompt doc before tmux launch",
    )
    parser.add_argument(
        "-c",
        "--controller-first",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Let controller produce JSON plan first before execution",
    )

    args = parser.parse_args(raw_args)
    configured_mode = str(getattr(config, "runtime_mode", "auto") or "auto").strip().lower()
    default_mode = configured_mode if configured_mode in {"direct", "tmux"} else "auto"

    if os.environ.get("AI_COLLAB_ACTIVE") == "1" and not bool(args.allow_nested):
        role = os.environ.get("AI_COLLAB_ROLE", "agent")
        console.print(
            "[yellow]Nested orchestration is disabled in active ai-collab session "
            f"(role={role}). Run the task directly in current agent, or pass --allow-nested.[/yellow]"
        )
        return

    provider = provider_prefix or args.provider or config.current_controller
    lang = _resolve_runtime_language(cli_lang=args.lang, config_lang=config.ui_language)
    mode_requested_via_args = bool(getattr(args, "execution_mode", None))
    decision_ui = None
    if args.interactive_decisions and sys.stdin.isatty():
        decision_ui = _pick_ui_backend(
            args.ui_mode,
            auto_install_deps=bool(args.auto_install_deps),
            lang=lang,
        )
    task_from_cli = " ".join(getattr(args, "task", [])).strip()
    prompted_for_inputs = not bool(task_from_cli) and bool(args.interactive_decisions and sys.stdin.isatty())
    provider, mode, task = _collect_runner_inputs(
        args=args,
        provider_prefix=provider_prefix,
        default_provider=provider,
        default_mode=default_mode,
        providers=sorted(providers),
        lang=lang,
        decision_ui=decision_ui,
    )
    args.execution_mode = mode
    mode_selected_explicitly = mode_requested_via_args or prompted_for_inputs

    detector = CollaborationDetector(config)
    result = detector.detect(task, provider)

    if args.output == "json":
        payload = {
            "provider": provider,
            "task": task,
            "result": result.model_dump(),
        }
        console.print(json.dumps(payload, indent=2, ensure_ascii=False))

    if result.need_collaboration:
        _print_runtime_overview(
            title=_auto_msg(lang, "start"),
            lang=lang,
            mode=str(args.execution_mode or "auto"),
            provider=result.primary or provider,
            task=task,
            result=result,
        )

        interactive_session = bool(args.interactive_decisions and sys.stdin.isatty())
        auto_cfg = config.auto_collaboration or {}
        default_controller_first = bool(auto_cfg.get("controller_first", True))
        if args.controller_first is None and mode_selected_explicitly and args.execution_mode == "tmux":
            default_controller_first = False
        controller_first_enabled = (
            default_controller_first if args.controller_first is None else bool(args.controller_first)
        )
        if controller_first_enabled:
            _print_available_agents(result, lang=lang)
        else:
            _print_orchestration_plan(result, lang=lang)

        controller_plan: Optional[dict[str, Any]] = None
        controller_plan_checked = False
        controller_plan_rejected = False
        controller_plan_adjustment_notes = ""

        def ensure_controller_plan() -> Optional[dict[str, Any]]:
            nonlocal controller_plan, controller_plan_checked, controller_plan_rejected, controller_plan_adjustment_notes
            if controller_plan_checked:
                return controller_plan
            controller_plan_checked = True
            if not controller_first_enabled:
                return None
            planning_request = _build_controller_planning_request(
                task=task,
                controller=provider,
                result=result,
                config=config,
                lang=lang,
            )
            with console.status(_auto_msg(lang, "controller_plan_generating"), spinner="dots"):
                plan_result = _request_controller_plan(
                    config=config,
                    controller=provider,
                    prompt_text=planning_request,
                )
            if isinstance(plan_result, tuple):
                plan, plan_error = plan_result
            else:
                plan, plan_error = plan_result, None
            if not plan:
                console.print(f"[yellow]{_auto_msg(lang, 'controller_plan_failed')}[/yellow]")
                if plan_error:
                    console.print(
                        f"[yellow]{_auto_msg(lang, 'controller_plan_request_failed', error=plan_error)}[/yellow]"
                    )
                if interactive_session:
                    continue_fallback = _ask_yes_no(
                        _auto_msg(lang, "controller_plan_fallback_confirm"),
                        lang=lang,
                        questionary_module=decision_ui,
                        default_yes=True,
                        provider=provider,
                    )
                    if not continue_fallback:
                        controller_plan_rejected = True
                        console.print(f"[yellow]{_auto_msg(lang, 'controller_plan_fallback_abort')}[/yellow]")
                return None
            _show_controller_plan(plan, lang=lang)
            if interactive_session:
                adjust_before_approve = _ask_yes_no(
                    _auto_msg(lang, "controller_plan_adjust"),
                    lang=lang,
                    questionary_module=decision_ui,
                    default_yes=False,
                    provider=provider,
                )
                if adjust_before_approve:
                    doc_text = _render_controller_plan(plan, lang=lang)
                    adjust_file = _write_orchestration_adjustment_file(
                        cwd=Path.cwd(),
                        controller=provider,
                        text=doc_text,
                    )
                    _open_file_in_editor(path=adjust_file, lang=lang)
                    controller_plan_adjustment_notes = adjust_file.read_text(encoding="utf-8").strip()
                    console.print(
                        f"[dim]{_auto_msg(lang, 'controller_plan_adjusted', path=str(adjust_file))}[/dim]"
                    )
                question = str(plan.get("approval_question", "")).strip() or _auto_msg(lang, "controller_plan_confirm")
                if lang == "zh-CN" and question.lower().strip() in {
                    "do you approve this plan?",
                    "approve this controller plan?",
                }:
                    question = _auto_msg(lang, "controller_plan_confirm")
                approved = _ask_yes_no(
                    question,
                    lang=lang,
                    questionary_module=decision_ui,
                    default_yes=True,
                    provider=provider,
                )
                if not approved:
                    controller_plan_rejected = True
                    console.print(f"[yellow]{_auto_msg(lang, 'controller_plan_skip')}[/yellow]")
                    return None
            controller_plan = plan
            return controller_plan

        prepared_controller_prompt: Optional[str] = None
        prompt_prepared = False

        def ensure_controller_prompt() -> Optional[str]:
            nonlocal prepared_controller_prompt, prompt_prepared
            if prompt_prepared:
                return prepared_controller_prompt
            prompt_prepared = True
            prompt_override: Optional[str] = None
            plan = ensure_controller_plan()
            if controller_plan_rejected:
                return None
            if plan:
                prompt_override = _build_controller_execution_prompt(
                    plan=plan,
                    lang=lang,
                    adjustment_notes=controller_plan_adjustment_notes,
                )
            default_edit = False
            edit_prompt = default_edit if args.edit_controller_prompt is None else bool(args.edit_controller_prompt)
            prepared_controller_prompt = _prepare_controller_prompt_document(
                task=task,
                controller=provider,
                result=result,
                config=config,
                lang=lang,
                decision_ui=decision_ui,
                interactive=interactive_session,
                edit_prompt=edit_prompt,
                prompt_text_override=prompt_override,
            )
            return prepared_controller_prompt

        if args.dry_run:
            if controller_first_enabled:
                plan = ensure_controller_plan()
                if controller_plan_rejected:
                    return
                if plan:
                    return
            prompt = _build_controller_prompt_document(
                task=task,
                controller=provider,
                result=result,
                config=config,
                lang=lang,
            )
            console.print(f"\n[bold cyan]{_auto_msg(lang, 'controller_doc_title')}[/bold cyan]")
            console.print(prompt)
            return

        skip_action_menu = prompted_for_inputs and args.execution_mode in {"tmux", "direct"}
        if decision_ui is not None and not skip_action_menu:
            options = [
                ("execute", _auto_msg(lang, "opt_execute")),
                ("plan", _auto_msg(lang, "opt_plan")),
                ("single", _auto_msg(lang, "opt_single")),
                ("cancel", _auto_msg(lang, "opt_cancel")),
            ]
            if _can_launch_tmux(result):
                options.insert(1, ("tmux", _auto_msg(lang, "opt_tmux")))
            action = _select_decision(
                _auto_msg(lang, "choose_action"),
                options,
                questionary_module=decision_ui,
            )
            if action == "cancel":
                return
            if action == "plan":
                prompt = _build_controller_prompt_document(
                    task=task,
                    controller=provider,
                    result=result,
                    config=config,
                    lang=lang,
                )
                console.print(f"\n[bold cyan]{_auto_msg(lang, 'controller_doc_title')}[/bold cyan]")
                console.print(prompt)
                return
            if action == "tmux":
                controller_prompt_text = ensure_controller_prompt()
                if controller_prompt_text is None:
                    return
                launch_result = _result_for_tmux_launch(result, controller_plan)
                if _launch_tmux_orchestration(
                    task=task,
                    controller=provider,
                    result=launch_result,
                    lang=lang,
                    prewarm_subagents=bool(args.tmux_prewarm_subagents),
                    controller_prompt_override=controller_prompt_text,
                    tmux_target=str(args.tmux_target),
                ):
                    return
                console.print(f"[red]{_auto_msg(lang, 'tmux_required_abort')}[/red]")
                return
            if action == "single":
                result = result.model_copy(update={"need_collaboration": False})

        if controller_first_enabled and not controller_plan_checked:
            ensure_controller_plan()
            if controller_plan_rejected:
                return

        launch_result = _result_for_tmux_launch(result, controller_plan)
        can_tmux = _can_launch_tmux(launch_result)
        if args.execution_mode in {"auto", "tmux"} and can_tmux:
            if args.execution_mode == "tmux" or (args.execution_mode == "auto" and not decision_ui):
                controller_prompt_text = ensure_controller_prompt()
                if controller_prompt_text is None:
                    return
                if _launch_tmux_orchestration(
                    task=task,
                    controller=provider,
                    result=launch_result,
                    lang=lang,
                    prewarm_subagents=bool(args.tmux_prewarm_subagents),
                    controller_prompt_override=controller_prompt_text,
                    tmux_target=str(args.tmux_target),
                ):
                    return
                if args.execution_mode == "tmux":
                    console.print(f"[red]{_auto_msg(lang, 'tmux_required_abort')}[/red]")
                    return
                console.print(f"[yellow]{_auto_msg(lang, 'tmux_fallback')}[/yellow]")
        elif args.execution_mode == "tmux":
            console.print(f"[red]{_auto_msg(lang, 'tmux_required_unavailable')}[/red]")
            return

        exit_code = _execute_direct_runtime(
            config=config,
            provider=provider,
            task=task,
            result=result,
            controller_plan=controller_plan,
            interactive=bool(args.interactive_decisions and sys.stdin.isatty()),
        )
        if exit_code != 0:
            raise SystemExit(exit_code)
        return

    rows = [(_auto_msg(lang, "primary"), provider)]
    lines = [_auto_msg(lang, "single_mode", provider=provider)]
    if result.suggested_skills:
        rows.append((_auto_msg(lang, "suggested_skills"), ", ".join(result.suggested_skills)))
    console.print()
    console.print(render_tmux_block(_auto_msg(lang, "single_runtime_title"), rows=rows, lines=lines))

    if args.dry_run:
        return

    if decision_ui is not None:
        action = _select_decision(
            _auto_msg(lang, "single_continue"),
            [
                ("execute", _auto_msg(lang, "opt_execute")),
                ("cancel", _auto_msg(lang, "opt_cancel")),
            ],
            questionary_module=decision_ui,
        )
        if action != "execute":
            return

    exit_code = _execute_direct_runtime(
        config=config,
        provider=provider,
        task=task,
        result=result,
        interactive=bool(args.interactive_decisions and sys.stdin.isatty()),
    )
    if exit_code != 0:
        raise SystemExit(exit_code)



def model_select_main() -> None:
    """Entry point for ai-collab model-select subcommand."""
    config = Config.load()

    parser = argparse.ArgumentParser(
        prog="ai-collab model-select", description="Select best model for provider/task"
    )
    parser.add_argument("provider", choices=sorted(config.providers.keys()))
    parser.add_argument("task", nargs="+")
    parser.add_argument("-c", "--complexity", choices=["default", "low", "medium", "high"], default="default")
    parser.add_argument("-o", "--output", choices=["text", "json"], default="text")
    parser.add_argument("-x", "--execute", action="store_true", help="Execute provider command with selected model")
    parser.add_argument("-u", "--ui-mode", choices=["auto", "tui", "text"], default="auto", help="Decision UI mode")
    parser.add_argument(
        "-i",
        "--auto-install-deps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto install missing TUI dependencies",
    )
    parser.add_argument(
        "-d",
        "--interactive-decisions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ask for complexity/execute confirmation in interactive mode",
    )

    args = parser.parse_args(sys.argv[1:])

    task = " ".join(args.task).strip()
    decision_ui = None
    if args.interactive_decisions and sys.stdin.isatty():
        decision_ui = _pick_ui_backend(
            args.ui_mode,
            auto_install_deps=bool(args.auto_install_deps),
            lang=config.ui_language,
        )

    complexity = args.complexity
    if decision_ui is not None:
        complexity = _select_decision(
            "Select complexity",
            [
                ("default", "Use provider default"),
                ("low", "Low complexity"),
                ("medium", "Medium complexity"),
                ("high", "High complexity"),
            ],
            questionary_module=decision_ui,
        )

    selector = ModelSelector(config)
    result = selector.select_model(args.provider, task, complexity)

    payload = {
        "provider": args.provider,
        "model": result.model,
        "cli": result.cli,
        "description": result.description,
        "thinking": result.thinking,
    }

    if args.output == "json":
        console.print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        console.print("\n[bold cyan]Model Selection[/bold cyan]")
        for key, value in payload.items():
            console.print(f"{key}: {value}")

    should_execute = bool(args.execute)
    if should_execute and decision_ui is not None:
        action = _select_decision(
            "Execute selected provider command now?",
            [
                ("yes", "Execute"),
                ("no", "Skip"),
            ],
            questionary_module=decision_ui,
        )
        should_execute = action == "yes"

    if should_execute:
        console.print(f"\n[dim]Executing via selected CLI...[/dim]")
        exit_code = _safe_execute(result.cli, task, provider=args.provider, lang=config.ui_language)
        if exit_code != 0:
            raise SystemExit(exit_code)


def _print_project_help() -> None:
    """Print unified help for the single ai-collab command."""
    console.print(
        "Usage:\n"
        "  ai-collab [OPTIONS] [task...]\n"
        "  ai-collab run [runner-options] [task...]\n"
        "  ai-collab <command> [args...]\n\n"
        "Options:\n"
        "  -h, --help     Show this message and exit.\n"
        "  -V, --version  Show version and exit.\n\n"
        "Runner options (see full list with `ai-collab run --help`):\n"
        "  ai-collab run --help\n\n"
        "Management commands:\n"
        "  init, status, config, detect, list, monitor, tmux-status, tmux-capture,\n"
        "  tmux-watch, tmux-close-pane, relay-smoke, handoff, tmux-open,\n"
        "  tmux-close-test, resume, select, ux-lab, ux-lab-v3\n\n"
        "Examples:\n"
        "  ai-collab \"implement JWT auth with review\"\n"
        "  ai-collab --execution-mode tmux --tmux-target inline \"deliver fullstack feature\"\n"
        "  ai-collab resume <run_id>\n"
        "  ai-collab detect \"design API contract\" --output json\n"
        "  ai-collab ux-lab\n"
        "  ai-collab ux-lab-v3\n"
    , markup=False, highlight=False)


def _should_offer_startup_update(args: list[str]) -> bool:
    if not args:
        return True
    command = str(args[0]).strip().lower()
    if command in {"-h", "--help", "help", "--version", "-v", "-V", "init"}:
        return False
    if command in {"config", "settings", "run"}:
        return True
    admin_only = {
        "detect", "handoff", "list", "monitor", "relay-smoke", "resume", "select",
        "status", "tmux-capture", "tmux-close-pane", "tmux-close-test", "tmux-open",
        "tmux-status", "tmux-watch", "ux-lab", "ux-lab-v3",
    }
    return command not in admin_only


def _prompt_update_message(lang: str, *, local_version: str, remote_version: str) -> str:
    if lang == "zh-CN":
        return f"检测到 PyPI 新版本 {remote_version}（当前 {local_version}）。是否先更新 ai-collab？"
    return f"PyPI has a newer ai-collab {remote_version} (current {local_version}). Update before continuing?"


def _maybe_offer_startup_update(args: list[str]) -> bool:
    if not _should_offer_startup_update(args):
        return False

    config = Config.load()
    application = getattr(config, "application", {}) or {}
    if not bool(application.get("auto_check_updates", True)):
        return False

    result = check_pypi_update(local_version=AI_COLLAB_VERSION)
    if result.status != "behind" or not result.remote_version:
        return False

    lang = config.ui_language if config.ui_language in I18N else "en-US"
    question = _prompt_update_message(lang, local_version=result.local_version, remote_version=result.remote_version)
    if not Confirm.ask(question, default=True):
        return False

    console.print("[cyan]Updating ai-collab via pip...[/cyan]" if lang == "en-US" else "[cyan]正在通过 pip 更新 ai-collab...[/cyan]")
    updated = run_self_update()
    if updated:
        console.print("[green]Update completed. Please rerun your command.[/green]" if lang == "en-US" else "[green]更新完成，请重新运行刚才的命令。[/green]")
        return True

    console.print("[yellow]Update failed, continuing with current version.[/yellow]" if lang == "en-US" else "[yellow]更新失败，将继续使用当前版本。[/yellow]")
    return False


def _rewrite_resume_shortcut_args(args: list[str]) -> list[str]:
    """Support `ai-collab resume <run_id>` as shortcut for `resume recover`."""
    if not args or str(args[0]).strip().lower() != "resume":
        return args
    if len(args) < 2:
        return args
    second = str(args[1]).strip()
    if not second:
        return args
    known = {"list", "prune", "show", "rename", "recover", "help"}
    if second.startswith("-") or second.lower() in known:
        return args
    return ["resume", "recover", *args[1:]]


def _entry_prompt_copy(lang: str) -> dict[str, Any]:
    return {
        "en-US": {
            "title": "ai-collab",
            "hint": "Choose a common entry flow.",
            "note": "Guided mode keeps the default terminal entry lightweight before you drop into a deeper surface.",
            "items": [
                ("1", "Start task", "Open the formal launcher for a new task."),
                ("2", "Open config", "Adjust long-term defaults and personal preferences."),
                ("3", "Run init", "Revisit bootstrap defaults from the beginning."),
            ],
            "quit": "Quit",
            "footer_text": "Type a number · Enter confirm · q quit",
            "footer_live": "↑/↓ move · Enter confirm · q quit · Esc cancel",
        },
        "zh-CN": {
            "title": "ai-collab",
            "hint": "选择一个常用入口。",
            "note": "引导模式先保持终端入口轻量，再按需要进入更深一层的操作界面。",
            "items": [
                ("1", "开始新任务", "进入正式 Launcher，开始一次新的任务流程。"),
                ("2", "打开配置", "调整长期默认项与个人偏好。"),
                ("3", "重新初始化", "从头重新确认启动默认值。"),
            ],
            "quit": "退出",
            "footer_text": "输入数字 · Enter 确认 · q 退出",
            "footer_live": "↑/↓ 移动 · Enter 确认 · q 退出 · Esc 取消",
        },
    }[lang]


def _entry_prompt_fragments(config_obj: Config, *, pointed_value: str = "1") -> list[tuple[str, str]]:
    from ai_collab.entry_prompt import _entry_prompt_fragments as _impl

    return _impl(config_obj, pointed_value=pointed_value)

def _render_entry_prompt_screen(
    config_obj: Config,
    *,
    console_obj: Console,
    clear_screen: bool,
    pointed_value: str | None = None,
    live: bool = False,
) -> list[tuple[str, str, str]]:
    from ai_collab.entry_prompt import _render_entry_prompt_screen as _impl

    return _impl(
        config_obj,
        console_obj=console_obj,
        clear_screen=clear_screen,
        pointed_value=pointed_value,
        live=live,
    )

def _select_entry_prompt_with_prompt_toolkit(
    config_obj: Config,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from ai_collab.entry_prompt import _select_entry_prompt_with_prompt_toolkit as _impl

    return _impl(config_obj, console_obj=console_obj, clear_screen=clear_screen)

def run_entry_prompt(
    config_obj: Config,
    *,
    input_fn: Callable[..., str] | None = None,
    selector_fn: Callable[..., str] | None = None,
    console_obj: Console | None = None,
    clear_screen: bool = True,
) -> None:
    """Thin guided entry aligned with init/config prompt style."""
    from ai_collab.entry_prompt import run_entry_prompt as _impl

    console_obj = console_obj or console
    return _impl(
        config_obj,
        input_fn=input_fn,
        selector_fn=selector_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
        dispatch_command=lambda args: main.main(args=args, prog_name="ai-collab", standalone_mode=True),
        cwd=Path.cwd(),
    )

def project_main() -> None:
    """Unified project entrypoint for ai-collab."""
    args = sys.argv[1:]
    admin_commands = {
        "config",
        "detect",
        "handoff",
        "init",
        "launch",
        "list",
        "monitor",
        "relay-smoke",
        "resume",
        "select",
        "settings",
        "status",
        "tmux-capture",
        "tmux-close-pane",
        "tmux-close-test",
        "tmux-open",
        "tmux-status",
        "tmux-watch",
        "ux-lab",
        "ux-lab-v3",
    }

    if args and args[0] in {"-h", "--help", "help"}:
        _print_project_help()
        return

    if args and args[0] in {"--version", "-V"}:
        main.main(args=["--version"], prog_name="ai-collab", standalone_mode=True)
        return

    args = _rewrite_resume_shortcut_args(args)

    if _maybe_offer_startup_update(args):
        return

    if not args:
        if not sys.stdin.isatty():
            _print_project_help()
            console.print(
                "\nNon-interactive shell detected. Use `ai-collab run <task>` "
                "or start `ai-collab` from an interactive terminal.",
                style="dim",
                markup=False,
                highlight=False,
            )
            return
        config_obj = Config.load()
        if str(getattr(config_obj, "entry_surface", "guided") or "guided") == "guided":
            run_entry_prompt(config_obj)
            return
        runner_main(argv=[], prog_name="ai-collab")
        return

    if args and args[0] in admin_commands:
        main.main(args=args, prog_name="ai-collab", standalone_mode=True)
        return

    if args and args[0] == "run":
        runner_main(argv=args[1:], prog_name="ai-collab run")
        return

    runner_main(argv=args, prog_name="ai-collab")


if __name__ == "__main__":
    project_main()
