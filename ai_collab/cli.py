"""
Main CLI entry point for ai-collab.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Any, Optional, Tuple

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationDetector
from ai_collab.core.environment import detect_os_name, detect_provider_status, resolve_executable
from ai_collab.core.selector import ModelSelector
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
    wait_for_pane_quiet,
)
from ai_collab.core.workflow import WorkflowManager

console = Console(force_terminal=True, legacy_windows=False)


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
    Quick health check for a provider by running --version or --help.
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

    # Fast availability probe.
    cmd: list[str]
    if provider == "claude":
        cmd = [executable, "--version"]
    elif provider == "gemini":
        cmd = [executable, "--version"]
    elif provider == "codex":
        cmd = [executable, "--version"]
    else:
        return False, f"Unknown provider: {provider}"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        # Any output indicates the command is reachable.
        if result.returncode == 0 or result.stdout or result.stderr:
            return True, ""
        else:
            return False, "No output from command"
    except subprocess.TimeoutExpired:
        return False, f"Timeout after {timeout_sec}s"
    except OSError as e:
        return False, f"OS error: {e}"


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


@click.group()
@click.version_option(version="0.1.0")
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
        console.print(f"Workflow: {result.workflow_name}")
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
        else:
            console.print(f"[yellow]Unknown config key: {key}[/yellow]")
            console.print("Available keys: auto_orchestration, ui_language")

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
        else:
            console.print(f"[yellow]Unknown config key: {key}[/yellow]")
            console.print("Available keys: auto_orchestration, ui_language")

    else:  # interactive
        config_obj.interactive_config()
        console.print("\n[green]✅ Configuration saved![/green]")


@main.command()
@click.option("--force", "-f", is_flag=True, help="Force reinitialize")
@click.option(
    "--interactive/--non-interactive",
    default=True,
    show_default=True,
    help="Run provider/model setup wizard during init",
)
@click.option(
    "--ui-mode",
    type=click.Choice(["auto", "tui", "text"]),
    default="tui",
    show_default=True,
    help="Wizard interaction mode",
)
@click.option(
    "--auto-install-deps/--no-auto-install-deps",
    default=True,
    show_default=True,
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
            resolved_ui_mode = _resolve_ui_mode(
                ui_mode,
                auto_install_deps=auto_install_deps,
                lang=config_obj.ui_language,
            )
            _run_init_wizard(config_obj, ui_mode=resolved_ui_mode)
            config_obj.save()

    console.print(f"[green]✅ Configuration initialized at {config_dir}[/green]")


@main.command(name="list")
@click.pass_context
def list_workflows(ctx: click.Context) -> None:
    """List all available workflows."""
    config_obj = ctx.obj["config"]

    table = Table(title="Available Workflows")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Phases", style="yellow")

    for name, workflow in config_obj.workflows.items():
        phases = len(workflow.get("phases", []))
        table.add_row(name, workflow.get("description", ""), str(phases))

    console.print(table)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current configuration status."""
    config_obj = ctx.obj["config"]
    lang = config_obj.ui_language if config_obj.ui_language in I18N else "en-US"
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
        suffix = f" | local={local_icon} {local_cmd}"
        if version:
            suffix += f" | {version}"
        console.print(f"  {configured_icon} {name}: {provider.cli}{suffix}")


@main.command()
@click.option("--session", "-s", default="ai-collab", help="tmux session name")
@click.option("--cwd", default=".", help="Workspace directory to open in panes")
@click.option(
    "--controller",
    type=click.Choice(["codex", "claude", "gemini"]),
    help="Controller agent for top pane (default: current_controller)",
)
@click.option(
    "--layout",
    type=click.Choice(["stacked", "tabbed"]),
    default="stacked",
    show_default=True,
    help="stacked: top controller + 3 bottom panes; tabbed: top/bottom + agent tabs",
)
@click.option(
    "--task-hint",
    default="Describe your task once and split into design/implement/review subtasks.",
    help="A hint shown in each pane",
)
@click.option("--autorun-agents", is_flag=True, help="Auto-launch codex/claude/gemini REPL in panes")
@click.option("--reset", is_flag=True, help="Kill existing session with same name and recreate")
@click.option("--detached", is_flag=True, help="Create session without attaching")
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


def _safe_execute(cli: str, task: str, timeout: Optional[int] = None) -> int:
    """Execute provider CLI safely with shell=False."""
    if cli.strip().startswith("codex ") and "--skip-git-repo-check" not in cli:
        cli = f"{cli} --skip-git-repo-check"
    try:
        cmd_parts = shlex.split(cli)
    except ValueError as exc:
        console.print(f"[red]Invalid provider CLI: {exc}[/red]")
        return 2

    try:
        result = subprocess.run(
            cmd_parts + [task],
            shell=False,
            timeout=timeout,
        )
        return result.returncode
    except FileNotFoundError:
        console.print("[red]Provider command not found. Check your PATH and provider CLI installation.[/red]")
        return 127


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
        return f"gpt-5.3-codex, {profile_key}"
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
        "workflow": "Workflow",
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
        "tmux_failed": "Failed to launch tmux controller workspace:",
        "choose_action": "Collaboration detected. Choose action",
        "opt_execute": "Run collaboration workflow",
        "opt_plan": "Show plan only (dry-run)",
        "opt_single": "Run single-provider mode",
        "opt_cancel": "Cancel",
        "opt_tmux": "Launch visual tmux collaboration",
        "single_mode": "Single AI mode - executing with {provider}",
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
    },
    "zh-CN": {
        "start": "🤝 启动多 AI 协作流程",
        "workflow": "工作流",
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
        "tmux_failed": "启动 tmux 主控工作区失败：",
        "choose_action": "检测到协作任务，选择动作",
        "opt_execute": "执行协作流程",
        "opt_plan": "仅查看计划（dry-run）",
        "opt_single": "单 Agent 执行",
        "opt_cancel": "取消",
        "opt_tmux": "启动 tmux 可视化协作",
        "single_mode": "单 Agent 模式 - 使用 {provider} 执行",
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
    },
}


def _auto_msg(lang: str, key: str, **kwargs: str) -> str:
    table = AUTO_COLLAB_I18N.get(lang, AUTO_COLLAB_I18N["en-US"])
    text = table.get(key, AUTO_COLLAB_I18N["en-US"].get(key, key))
    return text.format(**kwargs)


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
    providers: list[str],
    lang: str,
    decision_ui,
) -> tuple[str, str, str]:
    """
    Collect provider/mode/task.

    If task is provided in CLI args, reuse it; otherwise enter interactive 3-step flow.
    """
    raw_task = " ".join(getattr(args, "task", [])).strip()
    provider = provider_prefix or args.provider or default_provider
    mode = str(getattr(args, "execution_mode", "auto"))

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
        default_value="tmux",
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

## 你的输出要求（第一步）
请先输出一个 JSON（只输出 JSON，不要额外解释），结构如下：
```json
{{
  "plan_version": "1.0",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "codex", "model": "gpt-5.3-codex", "persona": "implementation-engineer", "why": "..." }}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "claude",
      "goal": "技术选型",
      "input": "用户任务 + 配置",
      "output": "选型结论",
      "done_when": "给出可执行结论"
    }}
  ],
  "approval_question": "是否同意该计划？"
}}
```

## 执行协议（第二步）
1. 在用户明确同意计划前，不要开始执行步骤。
2. 用户同意后，按 `steps` 顺序逐步执行。
3. 子 Agent 调度必须在 tmux 可视窗格中进行，禁止在主控后台 shell 里直接调用 claude/gemini。
4. 需要切换执行者时，输出 `HANDOFF_TO: <agent>` 或 `SPAWN_AGENT: <agent>` 以触发可视窗格。
5. 若命令遇到权限/审批拦截，先输出 `NEED_ELEVATION: <command> | reason=<error>`，等待用户处理，不得静默降级。
6. 每步完成后输出：
   - `STEP_DONE: <id>`
   - `HANDOFF_TO: <next_owner>`
   - 简短结果摘要
7. 全部结束后输出 `=== TASK_COMPLETE ===`。
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

## Output Requirement (Step 1)
First, return JSON only (no extra explanation) using this schema:
```json
{{
  "plan_version": "1.0",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "codex", "model": "gpt-5.3-codex", "persona": "implementation-engineer", "why": "..."}}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "claude",
      "goal": "tech selection",
      "input": "user task + config",
      "output": "selection conclusion",
      "done_when": "actionable decision is produced"
    }}
  ],
  "approval_question": "Do you approve this plan?"
}}
```

## Execution Protocol (Step 2)
1. Do not execute steps before user approval.
2. After approval, execute steps in order.
3. Sub-agent execution must stay visible in tmux panes. Do not run claude/gemini through hidden background shell commands in controller pane.
4. When switching owner, output `HANDOFF_TO: <agent>` or `SPAWN_AGENT: <agent>` to trigger visible panes.
5. If any command is blocked by permissions/approval, output `NEED_ELEVATION: <command> | reason=<error>` and wait; do not silently downgrade.
6. After each step output:
   - `STEP_DONE: <id>`
   - `HANDOFF_TO: <next_owner>`
   - short result summary
7. End with `=== TASK_COMPLETE ===`.
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

只返回 JSON，不要 markdown，不要解释。字段要求:
{{
  "plan_version": "1.0",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "codex", "model": "gpt-5.3-codex", "persona": "implementation-engineer", "why": "..." }}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "claude",
      "goal": "技术选型",
      "input": "用户任务 + 配置",
      "output": "选型结论",
      "done_when": "给出可执行结论"
    }}
  ],
  "approval_question": "是否同意该计划？"
}}

额外约束（必须写入计划并执行）:
- 子 Agent 必须在 tmux 可视窗格执行，禁止后台 shell 调用 claude/gemini。
- 交接时必须输出 `HANDOFF_TO: <agent>` 或 `SPAWN_AGENT: <agent>`。
- 若命令被权限/审批拦截，先输出 `NEED_ELEVATION: <command> | reason=<error>`。
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

Return JSON only (no markdown, no explanation) with this schema:
{{
  "plan_version": "1.0",
  "controller": "{controller}",
  "requires_multi_agent": true,
  "agents": [
    {{"name": "codex", "model": "gpt-5.3-codex", "persona": "implementation-engineer", "why": "..."}}
  ],
  "steps": [
    {{
      "id": "S1",
      "owner": "claude",
      "goal": "tech selection",
      "input": "user task + config",
      "output": "selection conclusion",
      "done_when": "actionable decision is produced"
    }}
  ],
  "approval_question": "Do you approve this plan?"
}}

Mandatory constraints:
- Sub-agents must run in visible tmux panes. Do not call claude/gemini via hidden background shell commands.
- On handoff, output `HANDOFF_TO: <agent>` or `SPAWN_AGENT: <agent>`.
- If any command is blocked by permission/approval, output `NEED_ELEVATION: <command> | reason=<error>`.
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


def _request_controller_plan(
    *,
    config: Config,
    controller: str,
    prompt_text: str,
) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
    """Ask controller model for orchestration plan JSON."""
    provider_config = config.providers.get(controller)
    if not provider_config:
        return None, f"Unknown provider: {controller}"
    try:
        cmd_parts = shlex.split(provider_config.cli)
    except ValueError as exc:
        return None, f"Invalid provider CLI: {exc}"

    # Keep behavior consistent with direct execution path.
    if cmd_parts and cmd_parts[0] == "codex" and "--skip-git-repo-check" not in cmd_parts:
        cmd_parts.append("--skip-git-repo-check")

    try:
        result = subprocess.run(
            cmd_parts + [prompt_text],
            shell=False,
            capture_output=True,
            text=True,
            timeout=provider_config.timeout,
        )
    except FileNotFoundError:
        executable = cmd_parts[0] if cmd_parts else controller
        return None, f"Provider command not found: {executable}"
    except subprocess.TimeoutExpired:
        return None, f"Timeout after {provider_config.timeout}s"

    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        first_line = error_text.splitlines()[0] if error_text else f"exit code {result.returncode}"
        return None, first_line

    combined_output = f"{result.stdout}\n{result.stderr}".strip()
    if not combined_output:
        return None, "Empty output from controller"

    plan = _extract_json_object(combined_output)
    if not plan:
        return None, "Controller output does not contain valid JSON object"
    return plan, None


def _build_controller_execution_prompt(
    *,
    plan: dict[str, Any],
    lang: str,
    adjustment_notes: str = "",
) -> str:
    """Build execution prompt for approved controller plan."""
    serialized = json.dumps(plan, indent=2, ensure_ascii=False)
    notes_block = adjustment_notes.strip()
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
5. 若命令被权限/审批拦截，输出 `NEED_ELEVATION: <command> | reason=<error>`，等待用户处理。
6. 全部完成输出 `=== TASK_COMPLETE ===`。
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
5. If blocked by permission/approval, output `NEED_ELEVATION: <command> | reason=<error>` and wait.
6. Finish with `=== TASK_COMPLETE ===`.
"""


def _render_controller_plan(plan: dict[str, Any], *, lang: str) -> str:
    """Render controller plan JSON into user-facing summary text."""
    is_zh = lang == "zh-CN"
    lines: list[str] = []

    controller = str(plan.get("controller", "")).strip() or "(unknown)"
    requires_multi = bool(plan.get("requires_multi_agent", False))
    agents = plan.get("agents", [])
    steps = plan.get("steps", [])
    approval_q = str(plan.get("approval_question", "")).strip()

    if is_zh:
        lines.append(f"主控: {controller}")
        lines.append(f"是否多 Agent: {'是' if requires_multi else '否'}")
        lines.append("")
        lines.append("Agent 编排:")
    else:
        lines.append(f"Controller: {controller}")
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
            lines.append(f"{idx}. [{sid}] {owner} - {goal}")
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
    console.print(f"\n[bold cyan]{_auto_msg(lang, 'controller_plan_title')}[/bold cyan]")
    console.print(_render_controller_plan(plan, lang=lang))


def _wait_for_agent_ready(*, pane_id: str, agent: str, timeout_seconds: float = 25.0) -> bool:
    """Wait until pane output contains a known ready marker for the selected agent."""
    markers = {
        "codex": ["openai codex", "tip: use /skills", "gpt-5"],
        "claude": ["claude", "sonnet", "opus"],
        "gemini": ["gemini"],
    }
    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    expected = markers.get(agent, [])
    while time.monotonic() < deadline:
        try:
            snapshot = capture_pane_text(pane_id=pane_id, start_line=-200)
        except subprocess.CalledProcessError:
            time.sleep(0.5)
            continue
        lower = snapshot.lower()
        if any(token in lower for token in expected):
            return True
        time.sleep(0.5)
    return False


def _prompt_probe(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if len(candidate) >= 8:
            return re.sub(r"\s+", " ", candidate.lower())[:72]
    fallback = text.strip()
    return re.sub(r"\s+", " ", fallback.lower())[:72] if fallback else ""


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
    value = os.environ.get("AI_COLLAB_RELAY_TO_CONTROLLER_INPUT", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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
) -> None:
    """Persist relay events and optionally inject them to controller input."""
    event_log = _tmux_events_log_path(cwd=cwd, session=session)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_log.parent.mkdir(parents=True, exist_ok=True)
    with event_log.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")

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


def _inject_prompt_to_pane(*, pane_id: str, text: str, agent: str) -> bool:
    """
    Inject a prompt to an interactive pane.

    Prefer single-block paste to avoid partial line submissions.
    """
    probe = _prompt_probe(text)
    for _attempt in range(3):
        ready = _wait_for_agent_ready(
            pane_id=pane_id,
            agent=agent,
            timeout_seconds=25.0,
        )
        settle_delay = _resolve_prompt_injection_delay(agent)
        if not ready:
            settle_delay = max(settle_delay, 2.5)
        if settle_delay > 0:
            time.sleep(settle_delay)
        wait_for_pane_quiet(
            pane_id=pane_id,
            timeout_seconds=5.0,
            stable_checks=2,
            poll_interval=0.5,
        )
        try:
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


def _build_subagent_prompt(*, task: str, steps: list[dict], lang: str, controller: str) -> str:
    assigned_lines = [
        "- {step_id} {role}: model={model}, reason={reason}".format(
            step_id=f"[{step.get('id', f'S{idx}')}]",
            role=step.get("role", ""),
            model=step.get("selected_model", ""),
            reason=step.get("reason", ""),
        )
        for idx, step in enumerate(steps, 1)
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
            + "- 完成后必须输出以下四行（逐行输出）:\n"
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
        + "- After finishing, output these four lines:\n"
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
) -> None:
    """Relay sub-agent completion markers back to controller pane."""
    step_pattern = re.compile(r"STEP_DONE\s*:\s*([A-Za-z0-9_.-]+)", re.IGNORECASE)
    handoff_pattern = re.compile(r"(?:HANDOFF_TO|SPAWN_AGENT)\s*:\s*([a-zA-Z0-9_-]+)", re.IGNORECASE)
    complete_pattern = re.compile(r"(?:===\s*SUBAGENT_COMPLETE\s*===|===\s*TASK_COMPLETE\s*===)", re.IGNORECASE)

    def _runner() -> None:
        seen_steps: set[str] = set()
        seen_handoffs: set[str] = set()
        unchanged = 0
        last_tail = ""
        while True:
            try:
                snapshot = capture_pane_text(pane_id=subagent_pane, start_line=-260)
            except subprocess.CalledProcessError:
                unchanged += 1
                if unchanged >= 8:
                    return
                time.sleep(1.0)
                continue

            tail = snapshot[-5000:]
            if tail == last_tail:
                unchanged += 1
            else:
                unchanged = 0
                last_tail = tail
                for step_id in step_pattern.findall(tail):
                    sid = step_id.strip()
                    if sid and sid not in seen_steps:
                        seen_steps.add(sid)
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} step done -> {sid}",
                        )
                for target in handoff_pattern.findall(tail):
                    next_agent = target.strip().lower()
                    if next_agent and next_agent not in seen_handoffs:
                        seen_handoffs.add(next_agent)
                        _emit_relay_event(
                            cwd=cwd,
                            session=session,
                            controller_pane=controller_pane,
                            message=f"[ai-collab relay] {agent} requested handoff -> {next_agent}",
                        )
                if complete_pattern.search(tail):
                    _emit_relay_event(
                        cwd=cwd,
                        session=session,
                        controller_pane=controller_pane,
                        message=f"[ai-collab relay] {agent} reported completion.",
                    )
                    return
            if unchanged >= 120:
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
) -> str:
    roles = ", ".join(step.get("role", "") for step in steps if step.get("role"))
    task_desc = f"roles: {roles}" if roles else "collaboration role"
    pane_id = spawn_subagent_pane(
        session=session,
        controller_pane=controller_pane,
        agent=agent,
        cwd=cwd,
        task_description=task_desc,
    )
    sub_prompt = _build_subagent_prompt(
        task=task,
        steps=steps,
        lang=lang,
        controller=controller,
    )
    briefing_file = _write_briefing_file(
        cwd=cwd,
        role="subagent",
        agent=agent,
        text=sub_prompt,
    )
    console.print(f"[dim]{_auto_msg(lang, 'brief_saved', path=str(briefing_file))}[/dim]")
    injected = _inject_prompt_to_pane(
        pane_id=pane_id,
        text=sub_prompt,
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
    handoff_pattern = re.compile(r"(?:HANDOFF_TO|SPAWN_AGENT)\s*:\s*([a-zA-Z0-9_-]+)", re.IGNORECASE)

    def _runner() -> None:
        unchanged = 0
        last_tail = ""
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
            if tail == last_tail:
                unchanged += 1
            else:
                unchanged = 0
                last_tail = tail
                for match in handoff_pattern.findall(tail):
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
                        )
                        spawned.add(agent)
                    except Exception as exc:  # noqa: BLE001
                        console.print(f"[yellow]handoff watcher spawn failed for {agent}: {exc}[/yellow]")
            if unchanged >= 120:
                return
            time.sleep(1.0)

    threading.Thread(target=_runner, name="ai-collab-handoff-watcher", daemon=True).start()


def _print_orchestration_plan(result, *, lang: str) -> None:
    available = result.available_agents or []
    plan = result.orchestration_plan or []
    if not available and not plan:
        return

    console.print(f"\n[bold cyan]{_auto_msg(lang, 'plan_title')}[/bold cyan]")
    console.print(f"{_auto_msg(lang, 'mode')}: {result.execution_mode}")
    if result.selected_agents:
        console.print(f"{_auto_msg(lang, 'selected_agents')}: {', '.join(result.selected_agents)}")

    if available:
        console.print(f"{_auto_msg(lang, 'available_agents')}:")
        for item in available:
            agent = item.get("agent", "")
            model = item.get("selected_model", "")
            profile = item.get("model_profile", "")
            strengths = item.get("strengths", "")
            console.print(f"  - {agent}: model={model} profile={profile} strengths={strengths}")

    if plan:
        console.print(f"{_auto_msg(lang, 'role_assignment')}:")
        for step in plan:
            role = step.get("role", "")
            agent = step.get("agent", "")
            model = step.get("selected_model", "")
            reason = step.get("reason", "")
            console.print(f"  - {role} -> {agent} ({model}) [{reason}]")


def _print_available_agents(result, *, lang: str) -> None:
    """Print available agents without showing pre-generated role assignment."""
    available = result.available_agents or []
    if not available:
        return
    console.print(f"\n[bold cyan]{_auto_msg(lang, 'available_agents_only')}[/bold cyan]")
    for item in available:
        agent = item.get("agent", "")
        model = item.get("selected_model", "")
        profile = item.get("model_profile", "")
        strengths = item.get("strengths", "")
        console.print(f"  - {agent}: model={model} profile={profile} strengths={strengths}")


def _can_launch_tmux(result) -> bool:
    if shutil.which("tmux") is None:
        return False
    return bool(result.execution_mode == "multi-agent" and result.orchestration_plan)


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

    cwd = Path.cwd()
    use_inline = tmux_target == "inline"
    if tmux_target == "auto":
        use_inline = bool(os.environ.get("TMUX"))
    if use_inline and not os.environ.get("TMUX"):
        use_inline = False

    if use_inline:
        try:
            resolved_session, controller_pane = create_inline_controller_workspace(
                cwd=cwd,
                controller=controller,
                autorun=True,
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
            controller_pane = create_controller_workspace(
                session=resolved_session,
                cwd=cwd,
                controller=controller,
                reset=False,
                autorun=True,
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

    if controller_prompt:
        briefing_file = _write_briefing_file(
            cwd=cwd,
            role="controller",
            agent=controller,
            text=controller_prompt,
        )
        console.print(f"[dim]{_auto_msg(lang, 'brief_saved', path=str(briefing_file))}[/dim]")
        injected = _inject_prompt_to_pane(
            pane_id=controller_pane,
            text=controller_prompt,
            agent=controller,
        )
        if not injected:
            console.print(
                f"[yellow]{_auto_msg(lang, 'prompt_inject_failed', agent=controller, pane=controller_pane)}[/yellow]"
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
            )
    else:
        _start_handoff_watcher(
            session=resolved_session,
            controller_pane=controller_pane,
            controller=controller,
            task=task,
            agent_roles=agent_roles,
            cwd=cwd,
            lang=lang,
        )

    log_dir = pane_logs_dir(cwd=cwd, session=resolved_session)
    console.print(f"[green]{_auto_msg(lang, 'tmux_ready')}:[/green] {resolved_session}")
    console.print(f"[dim]{_auto_msg(lang, 'tmux_logs', path=str(log_dir))}[/dim]")
    if not use_inline:
        attach_session(session=resolved_session)
    return True


def _install_ai_collab_skills(enabled_providers: list[str], lang: str) -> None:
    """
    Install ai-collab-orchestrator skill links for enabled agents.
    """
    from pathlib import Path
    import shutil

    # Source directory for the orchestrator skill.
    skill_source = Path(__file__).parent.parent / ".claude" / "skills" / "ai-collab-orchestrator"

    if not skill_source.exists():
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
    lang_default = config_obj.ui_language if config_obj.ui_language in I18N else "en-US"
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

    # Step 4: run quick connectivity checks.
    console.print(f"\n[bold]{'测试 Agent 连通性' if lang == 'zh-CN' else 'Testing agent connectivity'}[/bold]")
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
        console.print(f"\n[yellow]{'警告：部分 Agent 连通性测试失败' if lang == 'zh-CN' else 'Warning: Some agents failed health check'}[/yellow]")
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
    console.print(f"\n[bold]{'默认职责分配 (Three brains, one workflow)' if lang == 'zh-CN' else 'Default Responsibility Map (Three brains, one workflow)'}[/bold]\n")

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
    parser.add_argument("--provider", "-p", choices=sorted(providers), help="Current controller/provider")
    parser.add_argument("--dry-run", action="store_true", help="Only print the plan, do not execute")
    parser.add_argument("--output", "-o", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--lang", choices=sorted(I18N.keys()), help="Force UI language for this run")
    parser.add_argument("--ui-mode", choices=["auto", "tui", "text"], default="auto", help="Decision UI mode")
    parser.add_argument(
        "--execution-mode",
        choices=["auto", "direct", "tmux"],
        default="auto",
        help="Execution mode for collaboration workflow",
    )
    parser.add_argument(
        "--tmux-prewarm-subagents",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Pre-create sub-agent panes when entering tmux mode",
    )
    parser.add_argument(
        "--tmux-target",
        choices=["auto", "session", "inline"],
        default="auto",
        help="tmux launch target: new session or inline panes in current tmux window",
    )
    parser.add_argument(
        "--auto-install-deps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto install missing TUI dependencies",
    )
    parser.add_argument(
        "--interactive-decisions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ask for decisions before execution",
    )
    parser.add_argument(
        "--allow-nested",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=f"Allow running {prog_name} inside an existing ai-collab tmux session",
    )
    parser.add_argument(
        "--edit-controller-prompt",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Open editable controller prompt doc before tmux launch",
    )
    parser.add_argument(
        "--controller-first",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Let controller produce JSON plan first before execution",
    )

    args = parser.parse_args(raw_args)

    if os.environ.get("AI_COLLAB_ACTIVE") == "1" and not bool(args.allow_nested):
        role = os.environ.get("AI_COLLAB_ROLE", "agent")
        console.print(
            "[yellow]Nested orchestration is disabled in active ai-collab session "
            f"(role={role}). Run the task directly in current agent, or pass --allow-nested.[/yellow]"
        )
        return

    provider = provider_prefix or args.provider or config.current_controller
    lang = args.lang or (config.ui_language if config.ui_language in I18N else "en-US")
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
        providers=sorted(providers),
        lang=lang,
        decision_ui=decision_ui,
    )
    args.execution_mode = mode

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
        console.print(f"\n[bold green]{_auto_msg(lang, 'start')}[/bold green]")
        console.print(f"{_auto_msg(lang, 'workflow')}: {result.workflow_name}")
        console.print(f"{_auto_msg(lang, 'primary')}: {result.primary}")
        console.print(f"{_auto_msg(lang, 'reviewers')}: {', '.join(result.reviewers)}")
        if result.project_categories:
            console.print(f"{_auto_msg(lang, 'project_categories')}: {', '.join(result.project_categories)}")
        if result.suggested_skills:
            console.print(f"{_auto_msg(lang, 'auto_skills')}: {', '.join(result.suggested_skills)}")

        interactive_session = bool(args.interactive_decisions and sys.stdin.isatty())
        auto_cfg = config.auto_collaboration or {}
        default_controller_first = bool(auto_cfg.get("controller_first", True))
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
                if _launch_tmux_orchestration(
                    task=task,
                    controller=provider,
                    result=result,
                    lang=lang,
                    prewarm_subagents=bool(args.tmux_prewarm_subagents),
                    controller_prompt_override=controller_prompt_text,
                    tmux_target=str(args.tmux_target),
                ):
                    return
                console.print(f"[yellow]{_auto_msg(lang, 'tmux_fallback')}[/yellow]")
            if action == "single":
                result = result.model_copy(update={"need_collaboration": False})

        if controller_first_enabled and not controller_plan_checked:
            ensure_controller_plan()
            if controller_plan_rejected:
                return

        if args.execution_mode in {"auto", "tmux"} and _can_launch_tmux(result):
            if args.execution_mode == "tmux" or (args.execution_mode == "auto" and not decision_ui):
                controller_prompt_text = ensure_controller_prompt()
                if controller_prompt_text is None:
                    return
                if _launch_tmux_orchestration(
                    task=task,
                    controller=provider,
                    result=result,
                    lang=lang,
                    prewarm_subagents=bool(args.tmux_prewarm_subagents),
                    controller_prompt_override=controller_prompt_text,
                    tmux_target=str(args.tmux_target),
                ):
                    return
                console.print(f"[yellow]{_auto_msg(lang, 'tmux_fallback')}[/yellow]")

        context = {
            "controller": provider,
            "project_categories": ", ".join(result.project_categories),
            "auto_skills": ", ".join(result.suggested_skills),
            "intent": result.intent or "",
            "interactive": bool(args.interactive_decisions and sys.stdin.isatty()),
        }
        if controller_plan:
            context["controller_plan"] = json.dumps(controller_plan, ensure_ascii=False)
        workflow_manager = WorkflowManager(config)
        workflow_manager.execute_workflow(result.workflow_name, task, context)
        return

    console.print(f"\n[yellow]{_auto_msg(lang, 'single_mode', provider=provider)}[/yellow]")
    if result.suggested_skills:
        console.print(f"{_auto_msg(lang, 'suggested_skills')}: {', '.join(result.suggested_skills)}")

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

    provider_config = config.providers.get(provider)
    if provider_config:
        task_with_context = task
        if result.suggested_skills:
            task_with_context = (
                f"Auto-trigger skills (apply if available): {', '.join(result.suggested_skills)}\n\n"
                f"Task: {task}"
            )
        _safe_execute(provider_config.cli, task_with_context, timeout=provider_config.timeout)



def model_select_main() -> None:
    """Entry point for ai-collab model-select subcommand."""
    config = Config.load()

    parser = argparse.ArgumentParser(
        prog="ai-collab model-select", description="Select best model for provider/task"
    )
    parser.add_argument("provider", choices=sorted(config.providers.keys()))
    parser.add_argument("task", nargs="+")
    parser.add_argument("--complexity", "-c", choices=["default", "low", "medium", "high"], default="default")
    parser.add_argument("--output", "-o", choices=["text", "json"], default="text")
    parser.add_argument("--execute", action="store_true", help="Execute provider command with selected model")
    parser.add_argument("--ui-mode", choices=["auto", "tui", "text"], default="auto", help="Decision UI mode")
    parser.add_argument(
        "--auto-install-deps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto install missing TUI dependencies",
    )
    parser.add_argument(
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
        _safe_execute(result.cli, task)


def _print_project_help() -> None:
    """Print unified help for the single ai-collab command."""
    console.print(
        "Usage:\n"
        "  ai-collab [runner-options] [task...]\n"
        "  ai-collab run [runner-options] [task...]\n"
        "  ai-collab <command> [args...]\n\n"
        "Runner options:\n"
        "  ai-collab run --help\n\n"
        "Management commands:\n"
        "  init, status, config, detect, list, monitor, select\n\n"
        "Examples:\n"
        "  ai-collab \"implement JWT auth with review\"\n"
        "  ai-collab --execution-mode tmux --tmux-target inline \"deliver fullstack feature\"\n"
        "  ai-collab detect \"design API contract\" --output json\n"
    , markup=False)


def project_main() -> None:
    """Unified project entrypoint for ai-collab."""
    args = sys.argv[1:]
    admin_commands = {"config", "detect", "init", "list", "monitor", "select", "status"}

    if args and args[0] in {"-h", "--help", "help"}:
        _print_project_help()
        return

    if args and args[0] == "--version":
        main.main(args=["--version"], prog_name="ai-collab", standalone_mode=True)
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
