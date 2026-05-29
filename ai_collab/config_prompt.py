"""Thin menu-style config editor aligned with init prompt UX."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import shlex
import sys
from typing import Callable, Literal

import click
from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from ai_collab.core.config import (
    ALL_PROVIDER_KEYS,
    DEFAULT_COLLABORATION_PRESET,
    RECOMMENDED_INTENT_PREFERENCES,
    Config,
    normalize_economics_config,
    normalize_routing_config,
)
from ai_collab.init_prompt import (
    PROVIDER_THEME,
    build_init_banner,
)
from ai_collab.tui.setup import (
    CONTROLLER_LABELS,
    ENTRY_SURFACE_LABELS,
    LANGUAGE_LABELS,
    SetupFormData,
    apply_setup_form,
    resolve_setup_defaults,
)

InputFn = Callable[..., str]
MenuSelectFn = Callable[..., str]
MenuAction = Literal["edit", "save"]
SUPPORTED_LANGS = {"en-US", "zh-CN"}
AGENT_VALUE_MAP = {str(index): provider for index, provider in enumerate(ALL_PROVIDER_KEYS, start=1)}

INTENT_ORDER = (
    "implementation",
    "codebase_understanding",
    "research",
    "architecture",
    "testing",
    "multimodal",
)
PROFILE_LABELS = {
    "default": {"en-US": "Default", "zh-CN": "默认"},
    "powerful": {"en-US": "Powerful", "zh-CN": "质量优先"},
    "cost_effective": {"en-US": "Cost effective", "zh-CN": "成本优先"},
    "auto": {"en-US": "Auto route", "zh-CN": "自动路由"},
    "high": {"en-US": "Deep development", "zh-CN": "深度开发"},
    "medium": {"en-US": "Standard development", "zh-CN": "标准开发"},
    "low": {"en-US": "Quick execution", "zh-CN": "轻量执行"},
    "xhigh": {"en-US": "Max-depth mode", "zh-CN": "攻坚模式"},
}
PRESET_OPTIONS = (
    {
        "key": "auto-route",
        "en-US": "Recommended auto route",
        "zh-CN": "系统推荐自动路由",
        "desc_en-US": "Use built-in recommended routing for common multi-agent coding work.",
        "desc_zh-CN": "使用系统内置推荐路由，覆盖多数常见多 Agent 编码场景。",
    },
    {
        "key": "coding-lead",
        "en-US": "Coding lead",
        "zh-CN": "编码实现优先",
        "desc_en-US": "Bias toward implementation-heavy runs, with Codex leading execution more often.",
        "desc_zh-CN": "更偏向实现落地场景，让 Codex 更常担任执行主力。",
    },
    {
        "key": "architecture-lead",
        "en-US": "Architecture lead",
        "zh-CN": "架构审查优先",
        "desc_en-US": "Bias toward architecture, review, and design-decision workflows.",
        "desc_zh-CN": "更偏向架构、审查与方案权衡类工作流。",
    },
    {
        "key": "debug-lead",
        "en-US": "Debug lead",
        "zh-CN": "调试修复优先",
        "desc_en-US": "Bias toward bug diagnosis, repair, and follow-up verification.",
        "desc_zh-CN": "更偏向问题定位、修复与回归验证。",
    },
    {
        "key": "design-lead",
        "en-US": "Design lead",
        "zh-CN": "设计探索优先",
        "desc_en-US": "Bias toward multimodal design exploration and visual iteration.",
        "desc_zh-CN": "更偏向多模态设计探索、界面与视觉迭代。",
    },
    {
        "key": "research-lead",
        "en-US": "Research lead",
        "zh-CN": "调研分析优先",
        "desc_en-US": "Bias toward search, research breadth, and synthesis-heavy tasks.",
        "desc_zh-CN": "更偏向搜索调研、方案对比与综合整理。",
    },
    {
        "key": "custom",
        "en-US": "Keep advanced custom routing",
        "zh-CN": "保留高级自定义",
        "desc_en-US": "Preserve advanced routing maps without replacing them with a higher-level preset.",
        "desc_zh-CN": "保留已有高级路由映射，不用高层预设覆盖它们。",
    },
)
COST_BIAS_OPTIONS = (
    {
        "key": "balanced",
        "en-US": "Balanced",
        "zh-CN": "平衡",
        "desc_en-US": "When pricing is available, keep quality and cost in a practical middle ground.",
        "desc_zh-CN": "当价格信息可用时，在质量与成本之间保持均衡。",
    },
    {
        "key": "quality-first",
        "en-US": "Quality first",
        "zh-CN": "质量优先",
        "desc_en-US": "Prefer stronger models and deeper review even if estimated cost is higher.",
        "desc_zh-CN": "即使预估成本更高，也优先选择更强模型与更深审查。",
    },
    {
        "key": "cost-first",
        "en-US": "Cost first",
        "zh-CN": "成本优先",
        "desc_en-US": "When pricing is available, prefer lower-cost routes and lighter default profiles first.",
        "desc_zh-CN": "当价格信息可用时，优先选择更省成本的路由与较轻默认档位。",
    },
)
PRICING_MODE_OPTIONS = (
    {
        "key": "disabled",
        "en-US": "Disabled",
        "zh-CN": "未启用",
        "desc_en-US": "Do not use pricing information when picking routes or model defaults.",
        "desc_zh-CN": "不在路由与默认模型选择中使用价格信息。",
    },
    {
        "key": "official-reference",
        "en-US": "Official API reference",
        "zh-CN": "官方 API 参考",
        "desc_en-US": "Use built-in official API pricing as the baseline where applicable.",
        "desc_zh-CN": "在适用场景下使用内置官方 API 价格作为基准。",
    },
    {
        "key": "custom-reference",
        "en-US": "Custom billing reference",
        "zh-CN": "自定义计费参考",
        "desc_en-US": "Use your own billing assumptions such as subscription quota or cheaper custom channels.",
        "desc_zh-CN": "使用你自己的计费假设，例如订阅配额或更便宜的自定义渠道。",
    },
)
BILLING_MODE_OPTIONS = (
    {
        "key": "unconfigured",
        "en-US": "Not configured",
        "zh-CN": "未配置",
        "desc_en-US": "No billing assumption is stored yet for this provider.",
        "desc_zh-CN": "暂未为这个模型提供方 记录计费假设。",
    },
    {
        "key": "official-api",
        "en-US": "Official API",
        "zh-CN": "官方 API",
        "desc_en-US": "Treat this provider as billed by official API pricing.",
        "desc_zh-CN": "将这个模型提供方 视为按官方 API 价格计费。",
    },
    {
        "key": "subscription-quota",
        "en-US": "Subscription / quota",
        "zh-CN": "订阅 / 配额",
        "desc_en-US": "Treat this provider as mainly covered by subscription or quota.",
        "desc_zh-CN": "将这个模型提供方 视为主要由订阅或配额覆盖。",
    },
    {
        "key": "custom-priced",
        "en-US": "Custom price channel",
        "zh-CN": "自定义价格渠道",
        "desc_en-US": "Use your own lower or higher channel cost assumption.",
        "desc_zh-CN": "使用你自己的更低或更高渠道价格假设。",
    },
)
QUOTA_WINDOW_OPTIONS = (
    {
        "key": "none",
        "en-US": "No quota window",
        "zh-CN": "无配额周期",
        "desc_en-US": "No daily or monthly quota reminder is tracked for this provider.",
        "desc_zh-CN": "不为这个模型提供方 记录每日或每月配额周期。",
    },
    {
        "key": "daily",
        "en-US": "Daily quota",
        "zh-CN": "每日配额",
        "desc_en-US": "Use a daily quota mindset when estimating remaining cost pressure.",
        "desc_zh-CN": "在估算剩余成本压力时，按每日配额理解。",
    },
    {
        "key": "monthly",
        "en-US": "Monthly quota",
        "zh-CN": "每月配额",
        "desc_en-US": "Use a monthly quota mindset when estimating remaining cost pressure.",
        "desc_zh-CN": "在估算剩余成本压力时，按每月配额理解。",
    },
)
QUOTA_STRATEGY_OPTIONS = (
    {
        "key": "balanced",
        "en-US": "Balanced",
        "zh-CN": "平衡",
        "desc_en-US": "Use subscription quota when it fits, but do not over-prioritize it.",
        "desc_zh-CN": "在合适时使用订阅配额，但不过度优先它。",
    },
    {
        "key": "prefer-included-quota",
        "en-US": "Prefer included quota",
        "zh-CN": "优先消耗订阅配额",
        "desc_en-US": "Prefer already-paid subscription or quota capacity before pay-as-you-go API cost.",
        "desc_zh-CN": "优先使用已付费的订阅或配额能力，再考虑按量计费 API。",
    },
    {
        "key": "preserve-included-quota",
        "en-US": "Preserve included quota",
        "zh-CN": "保留订阅配额",
        "desc_en-US": "Avoid spending subscription quota too early when you want to save it for later runs.",
        "desc_zh-CN": "当你希望把订阅配额留给之后的任务时，避免过早消耗它。",
    },
)
CROSS_PROVIDER_FALLBACK_OPTIONS = (
    {
        "key": "same-provider-first",
        "en-US": "Same provider first",
        "zh-CN": "优先同提供方降档",
        "desc_en-US": "Try a lighter profile within the same provider before switching providers.",
        "desc_zh-CN": "先尝试在同一提供方内降档，再考虑切换提供方。",
    },
    {
        "key": "same-capability",
        "en-US": "Same capability only",
        "zh-CN": "仅同能力级回退",
        "desc_en-US": "Allow switching providers only when the fallback is still in a similar capability class.",
        "desc_zh-CN": "只有在回退目标仍处于相近能力级别时，才允许切换提供方。",
    },
    {
        "key": "allow-any",
        "en-US": "Allow any fallback",
        "zh-CN": "允许任意回退",
        "desc_en-US": "Allow any cheaper provider fallback when pricing pressure is high enough.",
        "desc_zh-CN": "当价格压力足够高时，允许回退到任何更便宜的提供方。",
    },
)
RELATIVE_COST_OPTIONS = (
    {
        "key": "lower",
        "en-US": "Lower cost",
        "zh-CN": "较低成本",
        "desc_en-US": "Your real channel is cheaper than a typical official baseline.",
        "desc_zh-CN": "你的实际渠道比典型官方基准更便宜。",
    },
    {
        "key": "standard",
        "en-US": "Typical cost",
        "zh-CN": "常规成本",
        "desc_en-US": "Treat this provider as roughly typical cost for its class.",
        "desc_zh-CN": "将这个模型提供方 视为该类别下的大致常规成本。",
    },
    {
        "key": "higher",
        "en-US": "Higher cost",
        "zh-CN": "较高成本",
        "desc_en-US": "Your real channel is more expensive than a typical baseline.",
        "desc_zh-CN": "你的实际渠道比典型基准更贵。",
    },
)
INTENT_META = {
    "implementation": {
        "en-US": "Implementation / coding",
        "zh-CN": "实现 / 编码落地",
    },
    "codebase_understanding": {
        "en-US": "Codebase understanding",
        "zh-CN": "代码库理解",
    },
    "research": {
        "en-US": "Research / search",
        "zh-CN": "调研 / 搜索",
    },
    "architecture": {
        "en-US": "Architecture / planning",
        "zh-CN": "架构 / 方案",
    },
    "testing": {
        "en-US": "Testing / verification",
        "zh-CN": "测试 / 验证",
    },
    "multimodal": {
        "en-US": "Multimodal / design exploration",
        "zh-CN": "多模态 / 设计探索",
    },
}
TEXT = {
    "en-US": {
        "menu_title": "ai-collab config",
        "menu_hint": "Choose a config section first. Frequent defaults stay on top; lower-frequency settings live one level deeper.",
        "menu_note": "Use this menu for long-term defaults and personal habits. System recommendations come first, your preferences can override them here, and Session Console can still override them per run.",
        "group_defaults": "Daily defaults",
        "group_defaults_desc": "Enabled agents, controller, runtime, entry, and collaboration.",
        "group_routing": "Routing & collaboration",
        "group_routing_desc": "Preset and task-type agent preferences.",
        "group_providers": "Models & billing",
        "group_providers_desc": "Model profiles, billing, quota, and price sensitivity.",
        "group_interface": "Application settings",
        "group_interface_desc": "Language, about page, and update preferences.",
        "item_language": "Display language",
        "item_language_desc": "Language used for terminal UI and onboarding copy.",
        "item_agents": "Enabled agents",
        "item_agents_desc": "Which agents stay available in the default collaboration pool.",
        "item_controller": "Default controller",
        "item_controller_desc": "Who leads new runs by default, plans work, and summarizes results.",
        "item_runtime": "Default runtime",
        "item_runtime_desc": "Which backend runs longer multi-agent sessions by default.",
        "item_entry": "Default entry",
        "item_entry_desc": "Which surface ai-collab opens first when you start it.",
        "item_collaboration": "Auto collaboration",
        "item_collaboration_desc": "Whether the controller may delegate to other agents by default.",
        "item_preset": "Collaboration preset",
        "item_preset_desc": "High-level default collaboration style without exposing raw routing maps.",
        "item_intents": "Task-type agent preferences",
        "item_intents_desc": "Choose which agent you prefer first for different kinds of work.",
        "item_agent_preferences": "Agent preferences",
        "item_agent_preferences_desc": "Explain in plain language what Codex, Claude, and Gemini are best used for by default.",
        "item_cost_bias": "Price sensitivity",
        "item_cost_bias_desc": "Choose how strongly billing and price information should influence routing once configured.",
        "item_models": "Agent model preferences",
        "item_models_desc": "Show the actual model ID and current default profile for each agent.",
        "item_economics": "Billing & quota",
        "item_economics_desc": "Set pricing reference, price sensitivity, quota strategy, and provider billing assumptions.",
        "item_pricing_mode": "Pricing reference",
        "item_pricing_mode_desc": "Choose whether ai-collab should use a static official reference or your own custom billing assumptions.",
        "item_provider_billing": "Provider billing setup",
        "item_provider_billing_desc": "Tell ai-collab whether each provider is official API, subscription/quota, or a custom-priced channel for you.",
        "item_quota_strategy": "Quota usage strategy",
        "item_quota_strategy_desc": "Decide whether ai-collab should preserve or prefer already-paid quota when routing is price-sensitive.",
        "item_cross_provider_fallback": "Cross-provider fallback",
        "item_cross_provider_fallback_desc": "Decide whether price-sensitive routing may switch providers, or should stay within the same provider first.",
        "item_about": "About ai-collab",
        "item_about_desc": "Show version, product direction, and a short application overview.",
        "item_updates": "Update settings",
        "item_updates_desc": "Choose whether ai-collab checks for new versions automatically.",
        "item_update_auto": "Automatic update checks",
        "item_update_auto_desc": "Check for new versions on startup; this does not auto-install updates.",
        "item_save": "Save and finish",
        "item_save_desc": "Write ~/.ai-collab/config.json and exit.",
        "value_collaboration_on": "Enabled",
        "value_collaboration_off": "Manual",
        "intent_summary_prefix": "Lead",
        "screen_defaults_title": "Daily defaults",
        "screen_defaults_hint": "Adjust the defaults you are most likely to change often.",
        "screen_defaults_note": "These settings shape how new runs start before any run-time override.",
        "screen_routing_title": "Routing & collaboration",
        "screen_routing_hint": "Adjust long-term routing preferences above the recommended defaults.",
        "screen_routing_note": "Keep one-off experiments for Session Console. This layer is for your long-term defaults.",
        "screen_providers_title": "Models & billing",
        "screen_providers_hint": "Adjust actual model defaults and billing semantics.",
        "screen_providers_note": "Routing answers who should work first. This layer answers which model/profile to use after a provider is chosen, and how billing or quota should influence price-sensitive routing.",
        "screen_interface_title": "Application settings",
        "screen_interface_hint": "Adjust language, about page, and update preferences.",
        "screen_interface_note": "These are application-level settings, not task routing rules.",
        "screen_preset_title": "Collaboration preset",
        "screen_preset_hint": "Choose the default collaboration style for new runs.",
        "screen_intents_title": "Task-type agent preferences",
        "screen_intents_hint": "Pick which intent you want to adjust first.",
        "screen_intents_note": "This is the user-preference layer. System recommendations stay available as fallback order.",
        "screen_intent_agent_title": "Preferred lead agent",
        "screen_intent_agent_hint": "Choose who should be preferred first for this kind of task.",
        "screen_intent_agent_note": "Recommended keeps the built-in order. Picking an agent moves it to the front while keeping the rest as fallback.",
        "screen_agent_preferences_title": "Agent preferences",
        "screen_agent_preferences_hint": "Read the default role split in plain language before you fine-tune routing.",
        "screen_cost_title": "Price sensitivity",
        "screen_cost_hint": "Choose how strongly pricing should influence default routing after billing is configured.",
        "screen_provider_title": "Agent model preferences",
        "screen_provider_hint": "Choose which agent you want to inspect or adjust.",
        "screen_provider_note": "Each entry shows the actual model ID and the current default profile.",
        "screen_provider_profile_title": "Default model profile",
        "screen_provider_profile_hint": "Choose the default profile for this agent.",
        "screen_economics_title": "Billing & quota",
        "screen_economics_hint": "Set billing assumptions, quota strategy, and price sensitivity.",
        "screen_economics_note": "Price-sensitive routing should not blindly switch agents. Start with the same provider first, then follow your fallback policy if needed.",
        "screen_pricing_title": "Pricing reference",
        "screen_pricing_hint": "Choose which baseline ai-collab should use for price-aware decisions.",
        "screen_pricing_note": "Official reference means a static reference baseline, not a live pricing fetch.",
        "screen_billing_provider_title": "Provider billing setup",
        "screen_billing_provider_hint": "Choose which provider billing setup you want to adjust.",
        "screen_billing_provider_note": "Use this to reflect whether you pay via official API, subscription quota, or a custom-priced channel.",
        "screen_billing_mode_title": "Billing mode",
        "screen_billing_mode_hint": "Choose how this provider is primarily billed for you.",
        "screen_quota_title": "Quota window",
        "screen_quota_hint": "Choose the quota cycle if this provider is mainly covered by subscription or quota.",
        "screen_relative_cost_title": "Relative cost",
        "screen_relative_cost_hint": "Choose whether your real channel cost is lower, typical, or higher than the baseline.",
        "screen_quota_strategy_title": "Quota usage strategy",
        "screen_quota_strategy_hint": "Choose whether ai-collab should preserve or prefer included quota when routing is price-sensitive.",
        "screen_fallback_title": "Cross-provider fallback",
        "screen_fallback_hint": "Choose whether price-sensitive routing may change provider or should stay within the same provider first.",
        "screen_about_title": "About ai-collab",
        "screen_about_hint": "Version, product direction, and terminal orchestration positioning.",
        "screen_about_note": "ai-collab is a multi-agent coding orchestrator. It is not a single coding model shell; it coordinates multiple agent CLIs and surfaces their collaboration through terminal-first workflows.",
        "screen_updates_title": "Update settings",
        "screen_updates_hint": "Control how the app checks for new versions.",
        "screen_updates_note": "Manual update execution is not wired into this menu yet. This screen controls update-check behavior only.",
        "recommended": "Recommended",
        "continue": "Continue",
        "back": "Back",
        "quit": "Quit without saving",
        "footer": "Type a number · Enter confirm · q quit",
        "footer_live": "↑/↓ move · Enter confirm · q quit · Esc cancel",
        "footer_back": "Type a number · Enter confirm · b back · q quit",
        "footer_live_back": "↑/↓ move · Enter confirm · b back · q quit · Esc cancel",
        "footer_multi_back": "Type a number to toggle · c continue · b back · q quit",
        "footer_live_multi_back": "↑/↓ move · Enter/Space toggle · c continue · b back · q quit · Esc cancel",
    },
    "zh-CN": {
        "menu_title": "ai-collab config",
        "menu_hint": "先选择一个配置分组。高频默认项放前面，低频设置放到下一层。",
        "menu_note": "这里用于调整长期默认偏好与个人习惯。如果只是某次任务的临时偏好，建议在 Session Console 中修改。系统会先使用推荐值，你可以在这里覆盖。",
        "group_defaults": "常用默认项",
        "group_defaults_desc": "启用 Agent、默认主控、运行方式、默认入口、自动协作。",
        "group_routing": "协作与路由",
        "group_routing_desc": "协作预设与任务类型偏好。",
        "group_providers": "模型与计费",
        "group_providers_desc": "模型档位、计费方式、配额策略与价格敏感度。",
        "group_interface": "应用设置",
        "group_interface_desc": "语言、关于与更新偏好。",
        "item_language": "显示语言",
        "item_language_desc": "终端界面与引导文案的显示语言。",
        "item_agents": "启用 Agent",
        "item_agents_desc": "设置哪些 Agent 在默认协作中保持可用。",
        "item_controller": "默认主控",
        "item_controller_desc": "谁负责默认理解任务、拆分计划并汇总结果。",
        "item_runtime": "默认运行方式",
        "item_runtime_desc": "多 Agent 任务默认使用的运行后端。",
        "item_entry": "默认入口",
        "item_entry_desc": "启动 ai-collab 时优先进入的界面。",
        "item_collaboration": "自动协作",
        "item_collaboration_desc": "新任务是否默认允许主控派发其他 Agent。",
        "item_preset": "协作预设",
        "item_preset_desc": "用高层默认风格表达协作偏好，而不是直接暴露底层路由表。",
        "item_intents": "按任务类型的 Agent 偏好",
        "item_intents_desc": "针对不同任务类型，设置你更希望谁优先处理。",
        "item_agent_preferences": "Agent 偏好",
        "item_agent_preferences_desc": "用人话说明 Codex、Claude 与 Gemini 默认更适合做什么。",
        "item_cost_bias": "价格敏感度",
        "item_cost_bias_desc": "在已配置计费信息后，决定价格信息会多大程度影响路由。",
        "item_models": "各 Agent 的默认模型偏好",
        "item_models_desc": "显示每个 Agent 实际会用的模型 ID 与默认档位。",
        "item_economics": "计费与配额",
        "item_economics_desc": "配置价格参考、价格敏感度、配额策略与各模型提供方计费设定。",
        "item_pricing_mode": "价格参考来源",
        "item_pricing_mode_desc": "决定 ai-collab 是否使用静态官方参考，还是使用你自己的计费假设。",
        "item_provider_billing": "模型提供方计费设定",
        "item_provider_billing_desc": "告诉 ai-collab 这个模型提供方对你来说是官方 API、订阅配额，还是自定义价格渠道。",
        "item_quota_strategy": "配额使用策略",
        "item_quota_strategy_desc": "决定在订阅或配额存在时，ai-collab 更倾向于保留还是优先消耗它。",
        "item_cross_provider_fallback": "跨提供方回退",
        "item_cross_provider_fallback_desc": "决定价格敏感时，是否允许从当前提供方回退到其他提供方。",
        "item_about": "关于 ai-collab",
        "item_about_desc": "查看版本、定位与终端产品方向说明。",
        "item_updates": "更新设置",
        "item_updates_desc": "设置是否自动检查更新，并查看当前更新方式。",
        "item_update_auto": "自动检查更新",
        "item_update_auto_desc": "启动时检查新版本；不会自动替你升级。",
        "item_save": "保存并完成",
        "item_save_desc": "写入 ~/.ai-collab/config.json 并退出。",
        "value_collaboration_on": "启用",
        "value_collaboration_off": "手动",
        "intent_summary_prefix": "优先",
        "screen_defaults_title": "常用默认项",
        "screen_defaults_hint": "调整你最常改的默认设置。",
        "screen_defaults_note": "这些设置决定新会话的起点，之后仍可在运行时临时覆盖。",
        "screen_routing_title": "协作与路由",
        "screen_routing_hint": "调整系统推荐之上的长期路由偏好。",
        "screen_routing_note": "这里是长期默认层，不处理单次任务的临时 override。",
        "screen_providers_title": "模型与计费",
        "screen_providers_hint": "调整实际模型默认值与计费语义。",
        "screen_providers_note": "协作与路由回答的是“先找谁做”；这一层回答的是“选中谁后默认用什么模型，以及计费 / 配额如何影响价格敏感决策”。",
        "screen_interface_title": "应用设置",
        "screen_interface_hint": "调整语言、关于与更新偏好。",
        "screen_interface_note": "这层用于应用自身设置，而不是某次任务的协作策略。",
        "screen_preset_title": "协作预设",
        "screen_preset_hint": "选择新任务默认采用的协作风格。",
        "screen_intents_title": "按任务类型的 Agent 偏好",
        "screen_intents_hint": "先选择你要调整的任务类型。",
        "screen_intents_note": "这里属于用户偏好层。系统推荐顺序仍然保留，作为回退链路。",
        "screen_intent_agent_title": "优先 Agent",
        "screen_intent_agent_hint": "选择这类任务优先交给谁。",
        "screen_intent_agent_note": "选择“系统推荐”会恢复内置顺序；选择某个 Agent 则会把它移到第一位，其余保持推荐回退顺序。",
        "screen_agent_preferences_title": "Agent 偏好",
        "screen_agent_preferences_hint": "先用人话看懂默认分工，再决定是否调整长期路由偏好。",
        "screen_cost_title": "价格敏感度",
        "screen_cost_hint": "在已配置计费信息后，选择价格应多强地影响默认路由。",
        "screen_provider_title": "各 Agent 的默认模型偏好",
        "screen_provider_hint": "先选择你要查看或调整的 Agent。",
        "screen_provider_note": "每项都会显示实际模型 ID，以及当前默认档位。",
        "screen_provider_profile_title": "默认模型档位",
        "screen_provider_profile_hint": "选择这个 Agent 的默认档位。",
        "screen_economics_title": "计费与配额",
        "screen_economics_hint": "设置计费假设、配额策略与价格敏感度。",
        "screen_economics_note": "价格敏感不会直接无脑换 Agent。默认应先尝试同提供方内降档，再按你的回退策略决定是否跨提供方。",
        "screen_pricing_title": "价格参考来源",
        "screen_pricing_hint": "选择 ai-collab 采用哪种价格 / 计费基准。",
        "screen_pricing_note": "“官方参考”只代表静态参考基线，不代表系统会自动联网抓取最新价格。",
        "screen_billing_provider_title": "模型提供方计费设定",
        "screen_billing_provider_hint": "先选择你要调整的模型提供方计费信息。",
        "screen_billing_provider_note": "用这里表达你对这个模型提供方的实际计费方式理解：官方 API、订阅配额，或自定义价格渠道。",
        "screen_billing_mode_title": "计费方式",
        "screen_billing_mode_hint": "选择这个模型提供方对你来说主要按什么方式计费。",
        "screen_quota_title": "配额周期",
        "screen_quota_hint": "如果这个模型提供方主要由订阅或配额覆盖，选择它的周期。",
        "screen_relative_cost_title": "相对成本",
        "screen_relative_cost_hint": "选择你的真实渠道成本相对基准是更低、常规还是更高。",
        "screen_quota_strategy_title": "配额使用策略",
        "screen_quota_strategy_hint": "选择 ai-collab 在价格敏感时应该保留还是优先消耗已付费配额。",
        "screen_fallback_title": "跨提供方回退",
        "screen_fallback_hint": "选择价格敏感时，是否允许从当前提供方回退到其他提供方。",
        "screen_about_title": "关于 ai-collab",
        "screen_about_hint": "版本、定位与终端编排产品方向。",
        "screen_about_note": "ai-collab 是一个多 Agent 编码编排器，不是单一模型的 shell。它负责协调多个 Agent CLI，并以终端优先的方式呈现协作过程。",
        "screen_updates_title": "更新设置",
        "screen_updates_hint": "控制应用如何检查新版本。",
        "screen_updates_note": "这个界面目前只管理更新检查偏好，还没有接入菜单内的一键升级。",
        "recommended": "系统推荐",
        "continue": "继续",
        "back": "返回",
        "quit": "退出且不保存",
        "footer": "输入数字 · Enter 确认 · q 退出",
        "footer_live": "↑/↓ 移动 · Enter 确认 · q 退出 · Esc 取消",
        "footer_back": "输入数字 · Enter 确认 · b 返回 · q 退出",
        "footer_live_back": "↑/↓ 移动 · Enter 确认 · b 返回 · q 退出 · Esc 取消",
        "footer_multi_back": "输入数字切换 · c 继续 · b 返回 · q 退出",
        "footer_live_multi_back": "↑/↓ 移动 · Enter/Space 切换 · c 继续 · b 返回 · q 退出 · Esc 取消",
    },
}


@dataclass
class ConfigMenuState:
    form: SetupFormData
    collaboration_preset: str
    cost_bias: str
    intent_preferences: dict[str, list[str]]
    provider_model_selection: dict[str, str]
    economics_pricing_mode: str
    provider_billing_modes: dict[str, str]
    provider_quota_windows: dict[str, str]
    provider_cost_tiers: dict[str, str]

    @classmethod
    def from_config(cls, config: Config) -> "ConfigMenuState":
        routing = normalize_routing_config(getattr(config, "routing", {}))
        economics = normalize_economics_config(getattr(config, "economics", {}))
        providers_cfg = economics.get("providers", {})
        return cls(
            form=resolve_setup_defaults(config),
            collaboration_preset=_resolve_collaboration_preset(config),
            cost_bias=str(routing.get("cost_bias", "balanced")),
            intent_preferences=dict(routing.get("intent_preferences", {})),
            provider_model_selection={
                provider: _current_provider_profile(provider, config.providers[provider])
                for provider in ALL_PROVIDER_KEYS
                if provider in config.providers
            },
            economics_pricing_mode=str(economics.get("pricing_mode", "disabled")),
            provider_billing_modes={
                provider: str((providers_cfg.get(provider) or {}).get("billing_mode", "unconfigured"))
                for provider in ALL_PROVIDER_KEYS
            },
            provider_quota_windows={
                provider: str((providers_cfg.get(provider) or {}).get("quota_window", "none"))
                for provider in ALL_PROVIDER_KEYS
            },
            provider_cost_tiers={
                provider: str((providers_cfg.get(provider) or {}).get("relative_cost_tier", "standard"))
                for provider in ALL_PROVIDER_KEYS
            },
        )


@dataclass(frozen=True)
class ConfigMenuItem:
    value: str
    label: str
    current: str
    description: str
    action: MenuAction


@dataclass(frozen=True)
class ChoiceOption:
    value: str
    label: str
    description: str = ""
    current: str = ""
    provider: str | None = None


@dataclass(frozen=True)
class ChoiceScreen:
    title: str
    hint: str
    note: str
    options: list[ChoiceOption]
    default_value: str


@dataclass(frozen=True)
class MenuRow:
    value: str
    prefix: str
    label: str
    label_style: str
    current: str = ""
    current_style: str = "fg:#94A3B8"
    description: str = ""
    description_style: str = "fg:#64748B italic"


@dataclass(frozen=True)
class ChoiceRow:
    value: str
    prefix: str
    label: str
    label_style: str
    description: str = ""
    description_style: str = "fg:#64748B italic"


@dataclass(frozen=True)
class MultiChoiceRow:
    value: str
    prefix: str
    marker: str
    marker_style: str
    label: str
    label_style: str
    description: str = ""
    description_style: str = "fg:#64748B italic"



def _lang(value: str | None) -> str:
    return value if value in SUPPORTED_LANGS else "en-US"



def _msg(lang: str, key: str) -> str:
    return TEXT[_lang(lang)][key]



def _prompt_input(prompt: str, *, choices: list[str], default: str) -> str:
    return Prompt.ask(prompt, choices=choices, default=default)



def _entry_label(lang: str, entry_surface: str) -> str:
    mapping = {
        "guided": "Guided launcher" if lang == "en-US" else "引导式启动器",
        "command": "Command-first" if lang == "en-US" else "命令优先",
    }
    return mapping.get(entry_surface, ENTRY_SURFACE_LABELS.get(entry_surface, entry_surface))



def _runtime_label(lang: str, runtime_mode: str) -> str:
    mapping = {
        "tmux": "tmux (stable, recommended)" if lang == "en-US" else "tmux（稳定，推荐）",
        "direct": "direct (lightweight, advanced)" if lang == "en-US" else "direct（轻量，进阶）",
    }
    return mapping.get(runtime_mode, runtime_mode)



def _enabled_agents(form: SetupFormData) -> list[str]:
    enabled = [name for name in ALL_PROVIDER_KEYS if form.providers.get(name, False)]
    return enabled or list(ALL_PROVIDER_KEYS)


def _enabled_agent_values(form: SetupFormData) -> list[str]:
    return [value for value, agent in AGENT_VALUE_MAP.items() if form.providers.get(agent, False)]


def _set_enabled_agents_local(form: SetupFormData, enabled_agents: list[str]) -> None:
    enabled_set = set(enabled_agents) or {ALL_PROVIDER_KEYS[0]}
    form.providers = {name: name in enabled_set for name in ALL_PROVIDER_KEYS}
    if form.controller not in enabled_set:
        form.controller = next(name for name in ALL_PROVIDER_KEYS if name in enabled_set)


def _enabled_agents_label(form: SetupFormData, *, lang: str) -> str:
    providers = [CONTROLLER_LABELS.get(name, name.title()) for name in _enabled_agents(form)]
    return ", ".join(providers)



def _collaboration_label(lang: str, enabled: bool) -> str:
    return _msg(lang, "value_collaboration_on") if enabled else _msg(lang, "value_collaboration_off")



def _resolve_collaboration_preset(config: Config) -> str:
    auto_cfg = dict(config.auto_collaboration or {})
    preset = str(auto_cfg.get("preset", DEFAULT_COLLABORATION_PRESET)).strip() or DEFAULT_COLLABORATION_PRESET
    valid = {item["key"] for item in PRESET_OPTIONS}
    return preset if preset in valid else DEFAULT_COLLABORATION_PRESET



def _preset_label(lang: str, preset: str) -> str:
    for item in PRESET_OPTIONS:
        if item["key"] == preset:
            return str(item[lang])
    return preset



def _cost_bias_label(lang: str, cost_bias: str) -> str:
    for item in COST_BIAS_OPTIONS:
        if item["key"] == cost_bias:
            return str(item[lang])
    return cost_bias



def _pricing_mode_label(lang: str, pricing_mode: str) -> str:
    for item in PRICING_MODE_OPTIONS:
        if item["key"] == pricing_mode:
            return str(item[lang])
    return pricing_mode



def _billing_mode_label(lang: str, billing_mode: str) -> str:
    for item in BILLING_MODE_OPTIONS:
        if item["key"] == billing_mode:
            return str(item[lang])
    return billing_mode



def _quota_window_label(lang: str, quota_window: str) -> str:
    for item in QUOTA_WINDOW_OPTIONS:
        if item["key"] == quota_window:
            return str(item[lang])
    return quota_window



def _relative_cost_label(lang: str, relative_cost_tier: str) -> str:
    for item in RELATIVE_COST_OPTIONS:
        if item["key"] == relative_cost_tier:
            return str(item[lang])
    return relative_cost_tier



def _intent_label(lang: str, intent: str) -> str:
    return str(INTENT_META.get(intent, {}).get(lang, intent))



def _intent_summary(state: ConfigMenuState, *, lang: str) -> str:
    summary_intents = ("implementation", "research", "architecture")
    separator = " · "
    parts: list[str] = []
    for intent in summary_intents:
        order = state.intent_preferences.get(intent, RECOMMENDED_INTENT_PREFERENCES[intent])
        lead = order[0] if order else RECOMMENDED_INTENT_PREFERENCES[intent][0]
        parts.append(f"{_intent_label(lang, intent)} {CONTROLLER_LABELS.get(lead, lead.title())}")
    return separator.join(parts)



def _profile_label(lang: str, profile_key: str) -> str:
    return PROFILE_LABELS.get(profile_key, {}).get(lang, profile_key)



def _current_provider_profile(provider: str, provider_config) -> str:
    models = provider_config.models or {}
    if provider == "codex":
        return str(models.get("default_thinking", "high"))
    if provider == "gemini":
        if models.get("auto_route_default") is True:
            return "auto"
        selection = str(provider_config.model_selection or "").strip()
        return selection if selection and selection != "default" else "powerful"
    selection = str(provider_config.model_selection or "default").strip() or "default"
    return selection



def _provider_profile_options(provider: str, provider_config, *, lang: str) -> list[ChoiceOption]:
    models = provider_config.models or {}
    if provider == "codex":
        order = [item for item in ("high", "medium", "low") if item in (models.get("enabled_profiles") or ["high", "medium", "low"]) or item in (models.get("thinking_levels") or {})]
        thinking_levels = models.get("thinking_levels", {}) if isinstance(models.get("thinking_levels", {}), dict) else {}
        options: list[ChoiceOption] = []
        for index, key in enumerate(order, start=1):
            desc = str((thinking_levels.get(key) or {}).get("description", "")).strip()
            options.append(ChoiceOption(str(index), _profile_label(lang, key), desc, provider=provider))
        return options

    raw_enabled = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw_enabled] if isinstance(raw_enabled, list) else []
    if provider == "claude":
        order = [key for key in ("default", "powerful", "cost_effective") if key in enabled_profiles or key == "default"]
    elif provider == "gemini":
        order = [key for key in ("powerful", "cost_effective", "auto") if key in enabled_profiles or key == "auto"]
    else:
        order = enabled_profiles or ["default"]

    options = []
    for index, key in enumerate(order, start=1):
        cfg = models.get(key, {}) if isinstance(models.get(key, {}), dict) else {}
        desc = str(cfg.get("description", "")).strip()
        model_name = str(cfg.get("model", models.get("default", ""))).strip()
        if key == "default" and not desc and model_name:
            desc = model_name
        elif model_name and desc:
            desc = f"{desc} · {model_name}"
        elif model_name:
            desc = model_name
        options.append(ChoiceOption(str(index), _profile_label(lang, key), desc, provider=provider))
    return options



def _provider_profile_summary(state: ConfigMenuState, *, lang: str) -> str:
    parts: list[str] = []
    for provider in ALL_PROVIDER_KEYS:
        if provider not in state.provider_model_selection:
            continue
        parts.append(f"{CONTROLLER_LABELS[provider]}: {_profile_label(lang, state.provider_model_selection[provider])}")
    return " · ".join(parts)



def _provider_models_summary(state: ConfigMenuState, *, lang: str) -> str:
    count = len([provider for provider in ALL_PROVIDER_KEYS if provider in state.provider_model_selection])
    if lang == "zh-CN":
        return f"{count} 个模型提供方已配置"
    return f"{count} providers configured"



def _configured_billing_count(state: ConfigMenuState) -> int:
    return sum(1 for provider in ALL_PROVIDER_KEYS if state.provider_billing_modes.get(provider, "unconfigured") != "unconfigured")



def _provider_billing_summary(state: ConfigMenuState, provider: str, *, lang: str) -> str:
    billing_mode = state.provider_billing_modes.get(provider, "unconfigured")
    if billing_mode == "unconfigured":
        return _billing_mode_label(lang, billing_mode)

    parts = [_billing_mode_label(lang, billing_mode)]
    if billing_mode == "subscription-quota":
        quota_window = state.provider_quota_windows.get(provider, "none")
        if quota_window != "none":
            parts.append(_quota_window_label(lang, quota_window))
    if state.economics_pricing_mode != "disabled" or billing_mode in {"subscription-quota", "custom-priced"}:
        parts.append(_relative_cost_label(lang, state.provider_cost_tiers.get(provider, "standard")))
    return " · ".join(parts)



def _economics_summary(state: ConfigMenuState, *, lang: str) -> str:
    pricing_mode = state.economics_pricing_mode
    if pricing_mode == "disabled":
        return "Pricing disabled" if lang == "en-US" else "未启用价格感知"
    configured = _configured_billing_count(state)
    if lang == "zh-CN":
        return f"{_pricing_mode_label(lang, pricing_mode)} · {configured} 个模型提供方已配置"
    return f"{_pricing_mode_label(lang, pricing_mode)} · {configured} providers configured"



def _defaults_summary(state: ConfigMenuState, *, lang: str) -> str:
    controller = CONTROLLER_LABELS.get(state.form.controller, state.form.controller.title())
    runtime = _runtime_label(lang, state.form.runtime_mode)
    collaboration = _collaboration_label(lang, state.form.auto_collaboration_enabled)
    if lang == "zh-CN":
        return f"主控 {controller} · {runtime} · 自动协作 {collaboration}"
    return f"Controller {controller} · {runtime} · Collaboration {collaboration}"



def _intent_override_count(state: ConfigMenuState) -> int:
    return sum(
        1
        for intent in INTENT_ORDER
        if state.intent_preferences.get(intent, []) != RECOMMENDED_INTENT_PREFERENCES[intent]
    )



def _routing_summary(state: ConfigMenuState, *, lang: str) -> str:
    preset = _preset_label(lang, state.collaboration_preset)
    overrides = _intent_override_count(state)
    if overrides <= 0:
        return preset
    if lang == "zh-CN":
        return f"{preset} · 已调整 {overrides} 项任务偏好"
    return f"{preset} · {overrides} task preferences adjusted"



def _models_cost_summary(state: ConfigMenuState, *, lang: str) -> str:
    return f"{_provider_models_summary(state, lang=lang)} · {_economics_summary(state, lang=lang)}"



def _interface_summary(state: ConfigMenuState) -> str:
    return LANGUAGE_LABELS.get(state.form.ui_language, state.form.ui_language)



def _build_menu_items(state: ConfigMenuState) -> list[ConfigMenuItem]:
    lang = _lang(state.form.ui_language)
    return [
        ConfigMenuItem("1", _msg(lang, "group_defaults"), _defaults_summary(state, lang=lang), _msg(lang, "group_defaults_desc"), "edit"),
        ConfigMenuItem("2", _msg(lang, "group_routing"), _routing_summary(state, lang=lang), _msg(lang, "group_routing_desc"), "edit"),
        ConfigMenuItem("3", _msg(lang, "group_providers"), _models_cost_summary(state, lang=lang), _msg(lang, "group_providers_desc"), "edit"),
        ConfigMenuItem("4", _msg(lang, "group_interface"), _interface_summary(state), _msg(lang, "group_interface_desc"), "edit"),
        ConfigMenuItem("5", _msg(lang, "item_save"), "", _msg(lang, "item_save_desc"), "save"),
    ]



def _current_style(item: ConfigMenuItem) -> str:
    return "fg:#E2E8F0"



def _build_menu_rows(items: list[ConfigMenuItem], *, pointed_value: str, lang: str) -> list[MenuRow]:
    rows: list[MenuRow] = []
    for item in items:
        is_pointed = item.value == pointed_value
        is_default = item.value == "1"
        label_style = "fg:#7DD3FC bold" if is_pointed else ("fg:#F8FAFC bold" if is_default else "fg:#CBD5E1")
        rows.append(
            MenuRow(
                value=item.value,
                prefix="❯ " if is_pointed else "  ",
                label=f"{item.value}. {item.label}",
                label_style=label_style,
                current=item.current,
                current_style=_current_style(item),
                description=item.description,
            )
        )
    rows.append(
        MenuRow(
            value="q",
            prefix="❯ " if pointed_value == "q" else "  ",
            label=f"q. {_msg(lang, 'quit')}",
            label_style="fg:#7DD3FC bold" if pointed_value == "q" else "fg:#CBD5E1",
        )
    )
    return rows



def render_config_menu_screen(config_or_state: Config | ConfigMenuState) -> str:
    state = config_or_state if isinstance(config_or_state, ConfigMenuState) else ConfigMenuState.from_config(config_or_state)
    lang = _lang(state.form.ui_language)
    items = _build_menu_items(state)
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=140)
    for line in build_init_banner(100):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console.print(Text(line, style=style))
    console.print()
    console.print(Text(_msg(lang, "menu_title"), style="bold"))
    console.print(Text(_msg(lang, "menu_hint"), style="dim"))
    console.print(Text(_msg(lang, "menu_note"), style="dim italic"))
    console.print()
    for index, item in enumerate(items):
        prefix = "›" if index == 0 else " "
        line = f"{prefix} {item.value}. {item.label}"
        if item.current:
            line += f" · {item.current}"
        console.print(line)
        console.print(Text(f"    {item.description}", style="dim italic"))
    console.print(f"  q. {_msg(lang, 'quit')}")
    console.print()
    console.print(Text(_msg(lang, "footer"), style="dim"))
    return buffer.getvalue().rstrip() + "\n"



def _render_menu_header(state: ConfigMenuState, *, console_obj: Console, clear_screen: bool) -> list[ConfigMenuItem]:
    lang = _lang(state.form.ui_language)
    if clear_screen:
        console_obj.clear()
    width = max(72, min(int(console_obj.width), 160)) if console_obj.width else 100
    for line in build_init_banner(width):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console_obj.print(Text(line, style=style))
    console_obj.print()
    console_obj.print(Text(_msg(lang, "menu_title"), style="bold"))
    console_obj.print(Text(_msg(lang, "menu_hint"), style="dim"))
    console_obj.print(Text(_msg(lang, "menu_note"), style="dim italic"))
    console_obj.print()
    return _build_menu_items(state)



def _select_menu_with_prompt_toolkit(
    state: ConfigMenuState,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    items = _render_menu_header(state, console_obj=console_obj, clear_screen=clear_screen)
    lang = _lang(state.form.ui_language)
    values = [item.value for item in items] + ["q"]
    pointed_index = 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens() -> list[tuple[str, str]]:
        rows = _build_menu_rows(items, pointed_value=_current_value(), lang=lang)
        fragments: list[tuple[str, str]] = []
        for row in rows:
            fragments.append(("", row.prefix))
            fragments.append((row.label_style, row.label))
            if row.current:
                fragments.append(("dim", " · "))
                fragments.append((row.current_style, row.current))
            fragments.append(("", "\n"))
            if row.description:
                fragments.append(("", "    "))
                fragments.append((row.description_style, row.description))
                fragments.append(("", "\n"))
        fragments.append(("fg:#64748B", f"\n{_msg(lang, 'footer_live')}"))
        return fragments

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result=_current_value())

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

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



def _ask_menu_choice(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
    selector_fn: MenuSelectFn | None = None,
) -> str:
    items = _render_menu_header(state, console_obj=console_obj, clear_screen=clear_screen) if False else _build_menu_items(state)
    choices = [item.value for item in items] + ["q"]
    if selector_fn is not None:
        return selector_fn(state, items, console_obj=console_obj, clear_screen=clear_screen)
    if input_fn is _prompt_input and sys.stdin.isatty():
        try:
            return _select_menu_with_prompt_toolkit(state, console_obj=console_obj, clear_screen=clear_screen)
        except Exception:
            pass
    if clear_screen:
        console_obj.clear()
    console_obj.print(render_config_menu_screen(state), end="")
    return input_fn("Select", choices=choices, default="1")



def _choice_default_style(option: ChoiceOption, *, is_pointed: bool, is_default: bool) -> str:
    if is_pointed:
        color = PROVIDER_THEME.get(option.provider, "#7DD3FC")
        return f"fg:{color} bold"
    if is_default:
        return "fg:#F8FAFC bold"
    return "fg:#CBD5E1"



def _build_choice_rows(screen: ChoiceScreen, *, lang: str, pointed_value: str, allow_back: bool) -> list[ChoiceRow]:
    rows: list[ChoiceRow] = []
    for option in screen.options:
        is_pointed = option.value == pointed_value
        is_default = option.value == screen.default_value
        rows.append(
            ChoiceRow(
                value=option.value,
                prefix="❯ " if is_pointed else "  ",
                label=option.label,
                label_style=_choice_default_style(option, is_pointed=is_pointed, is_default=is_default),
                description=option.description,
            )
        )
    if allow_back:
        rows.append(
            ChoiceRow(
                value="b",
                prefix="❯ " if pointed_value == "b" else "  ",
                label=_msg(lang, "back"),
                label_style="fg:#7DD3FC bold" if pointed_value == "b" else "fg:#CBD5E1",
            )
        )
    rows.append(
        ChoiceRow(
            value="q",
            prefix="❯ " if pointed_value == "q" else "  ",
            label=_msg(lang, "quit"),
            label_style="fg:#7DD3FC bold" if pointed_value == "q" else "fg:#CBD5E1",
        )
    )
    return rows



def render_choice_screen(screen: ChoiceScreen, *, lang: str, allow_back: bool) -> str:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    for line in build_init_banner(100):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console.print(Text(line, style=style))
    console.print()
    console.print(Text(screen.title, style="bold"))
    console.print(Text(screen.hint, style="dim"))
    if screen.note:
        console.print(Text(screen.note, style="dim italic"))
    console.print()
    for row in _build_choice_rows(screen, lang=lang, pointed_value=screen.default_value, allow_back=allow_back):
        if row.value in {"b", "q"}:
            console.print(f"{row.prefix}{row.label}")
            continue
        console.print(f"{row.prefix}{row.value}. {row.label}")
        if row.description:
            console.print(Text(f"    {row.description}", style="dim italic"))
    console.print()
    console.print(Text(_msg(lang, "footer_back" if allow_back else "footer"), style="dim"))
    return buffer.getvalue().rstrip() + "\n"



def _render_choice_header(screen: ChoiceScreen, *, console_obj: Console, clear_screen: bool) -> None:
    if clear_screen:
        console_obj.clear()
    width = max(72, min(int(console_obj.width), 160)) if console_obj.width else 100
    for line in build_init_banner(width):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console_obj.print(Text(line, style=style))
    console_obj.print()
    console_obj.print(Text(screen.title, style="bold"))
    console_obj.print(Text(screen.hint, style="dim"))
    if screen.note:
        console_obj.print(Text(screen.note, style="dim italic"))
    console_obj.print()



def _select_choice_with_prompt_toolkit(
    screen: ChoiceScreen,
    *,
    lang: str,
    allow_back: bool,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    _render_choice_header(screen, console_obj=console_obj, clear_screen=clear_screen)
    values = [item.value for item in screen.options] + (["b"] if allow_back else []) + ["q"]
    pointed_index = values.index(screen.default_value) if screen.default_value in values else 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens() -> list[tuple[str, str]]:
        rows = _build_choice_rows(screen, lang=lang, pointed_value=_current_value(), allow_back=allow_back)
        fragments: list[tuple[str, str]] = []
        for row in rows:
            fragments.append(("", row.prefix))
            if row.value not in {"b", "q"}:
                fragments.append((row.label_style, f"{row.value}. {row.label}"))
            else:
                fragments.append((row.label_style, row.label))
            fragments.append(("", "\n"))
            if row.description:
                fragments.append(("", "    "))
                fragments.append((row.description_style, row.description))
                fragments.append(("", "\n"))
        fragments.append(("fg:#64748B", f"\n{_msg(lang, 'footer_live_back' if allow_back else 'footer_live')}"))
        return fragments

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result=_current_value())

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

    if allow_back:
        @bindings.add("b", eager=True)
        def _back(event) -> None:
            event.app.exit(result="b")

    for key in tuple(str(number) for number in range(1, min(len(screen.options), 9) + 1)):
        @bindings.add(key, eager=True)
        def _pick(event, key_value=key) -> None:
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



def _ask_screen_choice(
    screen: ChoiceScreen,
    *,
    lang: str,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
    allow_back: bool,
) -> str:
    choices = [item.value for item in screen.options] + (["b"] if allow_back else []) + ["q"]
    default = screen.default_value if screen.default_value in choices else choices[0]
    if input_fn is _prompt_input and sys.stdin.isatty():
        try:
            return _select_choice_with_prompt_toolkit(screen, lang=lang, allow_back=allow_back, console_obj=console_obj, clear_screen=clear_screen)
        except Exception:
            pass
    if clear_screen:
        console_obj.clear()
    console_obj.print(render_choice_screen(screen, lang=lang, allow_back=allow_back), end="")
    return input_fn("Select", choices=choices, default=default)



def _current_basic_step_default(state: ConfigMenuState, step_id: str) -> str:
    if step_id == "language":
        return "1" if state.form.ui_language == "en-US" else "2"
    if step_id == "controller":
        enabled = _enabled_agents(state.form)
        current = state.form.controller if state.form.controller in enabled else enabled[0]
        return str(enabled.index(current) + 1)
    if step_id == "runtime":
        return "1" if state.form.runtime_mode == "tmux" else "2"
    if step_id == "entry":
        return "1" if state.form.entry_surface == "guided" else "2"
    if step_id == "collaboration":
        return "1" if state.form.auto_collaboration_enabled else "2"
    return "1"



def _provider_for_basic_option(step_id: str, state: ConfigMenuState, value: str) -> str | None:
    if step_id == "controller":
        enabled = _enabled_agents(state.form)
        index = int(value) - 1
        if 0 <= index < len(enabled):
            return enabled[index]
    return None



def _provider_capability_desc(lang: str, provider: str) -> str:
    descriptions = {
        "en-US": {
            "codex": "Best for end-to-end implementation, refactors, tests, and parallel agent workflows.",
            "claude": "Best for codebase understanding, editing, debugging, and workflow automation.",
            "gemini": "Best for large context, multimodal input, research, and terminal automation.",
        },
        "zh-CN": {
            "codex": "适合端到端工程执行、重构、测试与并行 Agent 工作流。",
            "claude": "适合代码库理解、编辑、调试与工作流自动化。",
            "gemini": "适合大上下文、多模态输入、搜索调研与终端自动化。",
        },
    }
    return descriptions[_lang(lang)][provider]



def _runtime_screen_note(lang: str, state: ConfigMenuState) -> str:
    agents = _enabled_agents_label(state.form, lang=lang)
    if lang == "zh-CN":
        return f"当前已启用：{agents}。tmux 更适合长期会话、分屏观察与稳定协作；direct 更轻，但更依赖当前终端控制与兼容性。"
    return f"Currently enabled: {agents}. tmux is steadier for long sessions, pane watching, and controller handoff; direct is lighter but depends more on current terminal control and compatibility."



def _basic_choice_screen(state: ConfigMenuState, step_id: str) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    default_value = _current_basic_step_default(state, step_id)

    if step_id == "language":
        return ChoiceScreen(
            title=_msg(lang, "item_language"),
            hint="Choose the language used by config, init, and terminal UI." if lang == "en-US" else "选择 config、init 与终端界面的显示语言。",
            note="This screen switches immediately after selection." if lang == "en-US" else "选择后本界面会立即切换为对应语言。",
            options=[
                ChoiceOption("1", "English (en-US)"),
                ChoiceOption("2", "中文 (zh-CN)"),
            ],
            default_value=default_value,
        )

    if step_id == "controller":
        enabled = _enabled_agents(state.form)
        return ChoiceScreen(
            title=_msg(lang, "item_controller"),
            hint="Choose who leads new runs by default from the enabled agents." if lang == "en-US" else "从已启用的 Agent 中选择谁默认负责理解任务、拆分计划与汇总结果。",
            note="Only enabled agents appear here. You can still change this later in config or Session Console." if lang == "en-US" else "这里只显示已启用的 Agent。之后仍可在 config 或 Session Console 中修改。",
            options=[
                ChoiceOption(
                    str(index),
                    CONTROLLER_LABELS.get(provider, provider.title()),
                    _provider_capability_desc(lang, provider),
                    provider=provider,
                )
                for index, provider in enumerate(enabled, start=1)
            ],
            default_value=default_value,
        )

    if step_id == "runtime":
        return ChoiceScreen(
            title=_msg(lang, "item_runtime"),
            hint="Choose the default backend for longer multi-agent runs." if lang == "en-US" else "选择 ai-collab 默认执行较长多 Agent 任务时使用的运行后端。",
            note=_runtime_screen_note(lang, state),
            options=[
                ChoiceOption(
                    "1",
                    _runtime_label(lang, "tmux"),
                    "Stable for long sessions, pane watching, and controller handoff." if lang == "en-US" else "适合长期会话、分屏观察与主控切换，稳定性更好。",
                ),
                ChoiceOption(
                    "2",
                    _runtime_label(lang, "direct"),
                    "Starts lighter and stays close to the current terminal, but relies more on local terminal behavior." if lang == "en-US" else "更轻、更贴近当前终端，但更依赖本地终端控制与兼容表现。",
                ),
            ],
            default_value=default_value,
        )

    if step_id == "entry":
        return ChoiceScreen(
            title=_msg(lang, "item_entry"),
            hint="Choose which surface ai-collab opens first by default." if lang == "en-US" else "选择 ai-collab 默认优先进入的入口界面。",
            note="This only changes the default landing surface. You can still jump into other entry points with explicit commands." if lang == "en-US" else "这里只决定默认先进入哪里；你仍可通过显式命令进入其他入口。",
            options=[
                ChoiceOption(
                    "1",
                    _entry_label(lang, "guided"),
                    "Open the launcher first so you can check status, choose a task, and then start." if lang == "en-US" else "先进入引导式启动器，适合先看状态、选任务、再启动。",
                ),
                ChoiceOption(
                    "2",
                    _entry_label(lang, "command"),
                    "Stay closer to the classic CLI flow when you already know the command or script you want." if lang == "en-US" else "更接近传统 CLI，用于你已经明确知道要执行哪个命令或脚本。",
                ),
            ],
            default_value=default_value,
        )

    if step_id == "collaboration":
        return ChoiceScreen(
            title=_msg(lang, "item_collaboration"),
            hint="Choose whether new runs let the controller delegate by default." if lang == "en-US" else "决定新任务是否默认允许主控按需派发其他 Agent。",
            note="This is only the default switch for new runs. Session Console can still override it per task." if lang == "en-US" else "这只是新任务的默认开关；进入 Session Console 后仍可按任务临时覆盖。",
            options=[
                ChoiceOption(
                    "1",
                    _collaboration_label(lang, True),
                    "Recommended for normal multi-agent coding sessions." if lang == "en-US" else "适合常见多 Agent 编码会话，主控可按需发起协作。",
                ),
                ChoiceOption(
                    "2",
                    _collaboration_label(lang, False),
                    "Start in a more manual mode when you want to decide collaboration step by step." if lang == "en-US" else "更偏手动控制，适合你希望逐步决定何时发起协作。",
                ),
            ],
            default_value=default_value,
        )

    raise ValueError(f"Unsupported basic step: {step_id}")



def _enabled_agents_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    note = (
        "All agents start enabled. Use Enter / Space to toggle, c to continue, and keep at least one agent enabled. The default controller is always chosen from the enabled pool."
        if lang == "en-US"
        else "默认全部启用。使用 Enter / Space 切换，c 继续，并至少保留一个 Agent。默认主控会始终从已启用 Agent 中选择。"
    )
    return ChoiceScreen(
        title=_msg(lang, "item_agents"),
        hint="Choose which agents stay available in the default collaboration pool." if lang == "en-US" else "选择哪些 Agent 在默认协作池中保持可用。",
        note=note,
        options=[
            ChoiceOption(
                value,
                CONTROLLER_LABELS.get(provider, provider.title()),
                _provider_capability_desc(lang, provider),
                provider=provider,
            )
            for value, provider in AGENT_VALUE_MAP.items()
        ],
        default_value="1",
    )



def _toggle_enabled_agent(form: SetupFormData, value: str) -> None:
    provider = AGENT_VALUE_MAP.get(value)
    if provider is None:
        return
    enabled = set(_enabled_agents(form))
    if provider in enabled:
        if len(enabled) == 1:
            return
        enabled.remove(provider)
    else:
        enabled.add(provider)
    ordered = [name for name in ALL_PROVIDER_KEYS if name in enabled]
    _set_enabled_agents_local(form, ordered)



def _build_enabled_agents_rows(
    screen: ChoiceScreen,
    *,
    lang: str,
    pointed_value: str,
    selected_values: set[str],
    allow_back: bool,
) -> list[MultiChoiceRow]:
    rows: list[MultiChoiceRow] = []
    for option in screen.options:
        is_pointed = option.value == pointed_value
        is_default = option.value == screen.default_value
        is_selected = option.value in selected_values
        provider_color = PROVIDER_THEME.get(option.provider, "#7DD3FC")
        rows.append(
            MultiChoiceRow(
                value=option.value,
                prefix="❯ " if is_pointed else "  ",
                marker="●" if is_selected else "○",
                marker_style=f"fg:{provider_color} bold" if is_selected else "fg:#64748B",
                label=option.label,
                label_style=(
                    f"fg:{provider_color} bold"
                    if is_pointed
                    else ("fg:#F8FAFC bold" if is_default else "fg:#CBD5E1")
                ),
                description=option.description,
            )
        )
    rows.append(
        MultiChoiceRow(
            value="c",
            prefix="❯ " if pointed_value == "c" else "  ",
            marker="",
            marker_style="",
            label=_msg(lang, "continue"),
            label_style="fg:#7DD3FC bold" if pointed_value == "c" else "fg:#CBD5E1",
        )
    )
    if allow_back:
        rows.append(
            MultiChoiceRow(
                value="b",
                prefix="❯ " if pointed_value == "b" else "  ",
                marker="",
                marker_style="",
                label=_msg(lang, "back"),
                label_style="fg:#7DD3FC bold" if pointed_value == "b" else "fg:#CBD5E1",
            )
        )
    rows.append(
        MultiChoiceRow(
            value="q",
            prefix="❯ " if pointed_value == "q" else "  ",
            marker="",
            marker_style="",
            label=_msg(lang, "quit"),
            label_style="fg:#7DD3FC bold" if pointed_value == "q" else "fg:#CBD5E1",
        )
    )
    return rows



def render_enabled_agents_screen(screen: ChoiceScreen, *, lang: str, selected_values: set[str], allow_back: bool) -> str:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    for line in build_init_banner(100):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console.print(Text(line, style=style))
    console.print()
    console.print(Text(screen.title, style="bold"))
    console.print(Text(screen.hint, style="dim"))
    if screen.note:
        console.print(Text(screen.note, style="dim italic"))
    console.print()
    for row in _build_enabled_agents_rows(screen, lang=lang, pointed_value=screen.default_value, selected_values=selected_values, allow_back=allow_back):
        console.print(row.prefix, end="")
        if row.marker:
            console.print(Text(f"{row.marker} ", style=row.marker_style), end="")
        if row.value in {"c", "b", "q"}:
            console.print(Text(row.label, style=row.label_style))
        else:
            console.print(Text(f"{row.value}. {row.label}", style=row.label_style))
        if row.description:
            console.print(Text(f"    {row.description}", style=row.description_style))
    console.print()
    console.print(Text(_msg(lang, "footer_multi_back"), style="dim"))
    return buffer.getvalue().rstrip() + "\n"



def _render_enabled_agents_header(screen: ChoiceScreen, *, console_obj: Console, clear_screen: bool) -> None:
    if clear_screen:
        console_obj.clear()
    width = max(72, min(int(console_obj.width), 160)) if console_obj.width else 100
    for line in build_init_banner(width):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console_obj.print(Text(line, style=style))
    console_obj.print()
    console_obj.print(Text(screen.title, style="bold"))
    console_obj.print(Text(screen.hint, style="dim"))
    if screen.note:
        console_obj.print(Text(screen.note, style="dim italic"))
    console_obj.print()



def _select_enabled_agents_with_prompt_toolkit(
    state: ConfigMenuState,
    screen: ChoiceScreen,
    *,
    lang: str,
    allow_back: bool,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    _render_enabled_agents_header(screen, console_obj=console_obj, clear_screen=clear_screen)
    option_values = [item.value for item in screen.options]
    values = option_values + ["c"] + (["b"] if allow_back else []) + ["q"]
    pointed_index = 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _selected() -> set[str]:
        return set(_enabled_agent_values(state.form))

    def _ordered_selection() -> str:
        return ",".join(value for value in option_values if value in _selected())

    def _tokens() -> list[tuple[str, str]]:
        rows = _build_enabled_agents_rows(
            screen,
            lang=lang,
            pointed_value=_current_value(),
            selected_values=_selected(),
            allow_back=allow_back,
        )
        fragments: list[tuple[str, str]] = []
        for row in rows:
            fragments.append(("", row.prefix))
            if row.marker:
                fragments.append((row.marker_style, f"{row.marker} "))
            label = row.label if row.value in {"c", "b", "q"} else f"{row.value}. {row.label}"
            fragments.append((row.label_style, label))
            fragments.append(("", "\n"))
            if row.description:
                fragments.append(("", "    "))
                fragments.append((row.description_style, row.description))
                fragments.append(("", "\n"))
        fragments.append(("fg:#64748B", f"\n{_msg(lang, 'footer_live_multi_back')}"))
        return fragments

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    @bindings.add(" ", eager=True)
    def _space(event) -> None:
        current = _current_value()
        if current in option_values:
            _toggle_enabled_agent(state.form, current)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        current = _current_value()
        if current == "c":
            event.app.exit(result=_ordered_selection())
            return
        if current in {"b", "q"}:
            event.app.exit(result=current)
            return
        _toggle_enabled_agent(state.form, current)

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

    @bindings.add("c", eager=True)
    def _continue(event) -> None:
        event.app.exit(result=_ordered_selection())

    if allow_back:
        @bindings.add("b", eager=True)
        def _back(event) -> None:
            event.app.exit(result="b")

    for key in tuple(str(number) for number in range(1, min(len(option_values), 9) + 1)):
        @bindings.add(key, eager=True)
        def _pick(event, key_value=key) -> None:
            if key_value not in values:
                return
            nonlocal pointed_index
            pointed_index = values.index(key_value)
            if key_value in option_values:
                _toggle_enabled_agent(state.form, key_value)

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


def _edit_enabled_agents(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    screen = _enabled_agents_screen(state)
    option_values = [item.value for item in screen.options]

    if input_fn is _prompt_input and sys.stdin.isatty():
        try:
            choice = _select_enabled_agents_with_prompt_toolkit(
                state,
                screen,
                lang=lang,
                allow_back=True,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if choice in {"b", "q"}:
                return choice
            return None
        except Exception:
            pass

    while True:
        if clear_screen:
            console_obj.clear()
        console_obj.print(
            render_enabled_agents_screen(
                screen,
                lang=lang,
                selected_values=set(_enabled_agent_values(state.form)),
                allow_back=True,
            ),
            end="",
        )
        choice = input_fn("Select", choices=option_values + ["c", "b", "q"], default="c")
        if choice in {"b", "q"}:
            return choice
        if choice == "c":
            return None
        _toggle_enabled_agent(state.form, choice)



def _apply_basic_choice(state: ConfigMenuState, *, step_id: str, choice: str) -> None:
    if step_id == "language":
        state.form.ui_language = "en-US" if choice == "1" else "zh-CN"
        return
    if step_id == "enabled_agents":
        enabled_agents = [AGENT_VALUE_MAP[value] for value in choice.split(",") if value in AGENT_VALUE_MAP]
        _set_enabled_agents_local(state.form, enabled_agents)
        return
    if step_id == "controller":
        enabled = _enabled_agents(state.form)
        index = max(0, min(len(enabled) - 1, int(choice) - 1))
        state.form.controller = enabled[index]
        return
    if step_id == "runtime":
        state.form.runtime_mode = "tmux" if choice == "1" else "direct"
        return
    if step_id == "entry":
        state.form.entry_surface = "guided" if choice == "1" else "command"
        return
    if step_id == "collaboration":
        state.form.auto_collaboration_enabled = choice == "1"



def _edit_basic_step(
    state: ConfigMenuState,
    *,
    step_id: str,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    if step_id == "enabled_agents":
        return _edit_enabled_agents(
            state,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )

    screen = _basic_choice_screen(state, step_id)
    choice = _ask_screen_choice(
        screen,
        lang=lang,
        input_fn=input_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
        allow_back=True,
    )
    if choice in {"b", "q"}:
        return choice
    _apply_basic_choice(state, step_id=step_id, choice=choice)
    return None



def _preset_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(PRESET_OPTIONS, start=1)
    ]
    default_value = next((str(index) for index, item in enumerate(PRESET_OPTIONS, start=1) if item["key"] == state.collaboration_preset), "1")
    return ChoiceScreen(
        title=_msg(lang, "screen_preset_title"),
        hint=_msg(lang, "screen_preset_hint"),
        note="",
        options=options,
        default_value=default_value,
    )



def _edit_collaboration_preset(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    screen = _preset_screen(state)
    choice = _ask_screen_choice(screen, lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice in {"b", "q"}:
        return choice
    state.collaboration_preset = PRESET_OPTIONS[int(choice) - 1]["key"]
    return None



def _intent_picker_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = []
    for index, intent in enumerate(INTENT_ORDER, start=1):
        order = state.intent_preferences.get(intent, RECOMMENDED_INTENT_PREFERENCES[intent])
        lead = order[0] if order else RECOMMENDED_INTENT_PREFERENCES[intent][0]
        options.append(
            ChoiceOption(
                str(index),
                _intent_label(lang, intent),
                f"{_msg(lang, 'intent_summary_prefix')}: {CONTROLLER_LABELS.get(lead, lead.title())}",
                provider=lead,
            )
        )
    return ChoiceScreen(
        title=_msg(lang, "screen_intents_title"),
        hint=_msg(lang, "screen_intents_hint"),
        note=_msg(lang, "screen_intents_note"),
        options=options,
        default_value="1",
    )



def _intent_agent_screen(state: ConfigMenuState, *, intent: str) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    current_order = state.intent_preferences.get(intent, RECOMMENDED_INTENT_PREFERENCES[intent])
    current_top = current_order[0] if current_order else RECOMMENDED_INTENT_PREFERENCES[intent][0]
    note = _msg(lang, "screen_intent_agent_note")
    options = [ChoiceOption("1", _msg(lang, "recommended"), _order_label(lang, RECOMMENDED_INTENT_PREFERENCES[intent]))]
    for index, provider in enumerate(ALL_PROVIDER_KEYS, start=2):
        reordered = _reordered_intent_preference(intent, provider)
        options.append(
            ChoiceOption(
                str(index),
                CONTROLLER_LABELS[provider],
                _order_label(lang, reordered),
                provider=provider,
            )
        )
    default_value = "1" if current_order == RECOMMENDED_INTENT_PREFERENCES[intent] else str(ALL_PROVIDER_KEYS.index(current_top) + 2)
    return ChoiceScreen(
        title=f"{_msg(lang, 'screen_intent_agent_title')} · {_intent_label(lang, intent)}",
        hint=_msg(lang, "screen_intent_agent_hint"),
        note=note,
        options=options,
        default_value=default_value,
    )



def _reordered_intent_preference(intent: str, provider: str) -> list[str]:
    order = [provider]
    for item in RECOMMENDED_INTENT_PREFERENCES[intent]:
        if item not in order:
            order.append(item)
    return order



def _order_label(lang: str, order: list[str]) -> str:
    separator = " → "
    return separator.join(CONTROLLER_LABELS.get(item, item.title()) for item in order)



def _edit_intent_preferences(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    intent_choice = _ask_screen_choice(_intent_picker_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if intent_choice in {"b", "q"}:
        return intent_choice
    intent = INTENT_ORDER[int(intent_choice) - 1]
    agent_choice = _ask_screen_choice(_intent_agent_screen(state, intent=intent), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if agent_choice in {"b", "q"}:
        return agent_choice
    if agent_choice == "1":
        state.intent_preferences[intent] = list(RECOMMENDED_INTENT_PREFERENCES[intent])
    else:
        provider = ALL_PROVIDER_KEYS[int(agent_choice) - 2]
        state.intent_preferences[intent] = _reordered_intent_preference(intent, provider)
    return None



def _cost_bias_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(COST_BIAS_OPTIONS, start=1)
    ]
    default_value = next((str(index) for index, item in enumerate(COST_BIAS_OPTIONS, start=1) if item["key"] == state.cost_bias), "1")
    return ChoiceScreen(
        title=_msg(lang, "screen_cost_title"),
        hint=_msg(lang, "screen_cost_hint"),
        note="",
        options=options,
        default_value=default_value,
    )



def _edit_cost_bias(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    choice = _ask_screen_choice(_cost_bias_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice in {"b", "q"}:
        return choice
    state.cost_bias = COST_BIAS_OPTIONS[int(choice) - 1]["key"]
    return None



def _provider_picker_screen(state: ConfigMenuState, config: Config) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = []
    for index, provider in enumerate(ALL_PROVIDER_KEYS, start=1):
        if provider not in config.providers:
            continue
        current_key = state.provider_model_selection.get(provider, _current_provider_profile(provider, config.providers[provider]))
        options.append(
            ChoiceOption(
                str(index),
                CONTROLLER_LABELS[provider],
                _profile_label(lang, current_key),
                provider=provider,
            )
        )
    return ChoiceScreen(
        title=_msg(lang, "screen_provider_title"),
        hint=_msg(lang, "screen_provider_hint"),
        note=_msg(lang, "screen_provider_note"),
        options=options,
        default_value="1",
    )



def _provider_profile_screen(state: ConfigMenuState, config: Config, *, provider: str) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = _provider_profile_options(provider, config.providers[provider], lang=lang)
    profile_keys = _provider_profile_keys(provider, config.providers[provider])
    current_key = state.provider_model_selection.get(provider, _current_provider_profile(provider, config.providers[provider]))
    default_value = str(profile_keys.index(current_key) + 1) if current_key in profile_keys else "1"
    return ChoiceScreen(
        title=f"{_msg(lang, 'screen_provider_profile_title')} · {CONTROLLER_LABELS[provider]}",
        hint=_msg(lang, "screen_provider_profile_hint"),
        note="",
        options=options,
        default_value=default_value,
    )



def _provider_profile_keys(provider: str, provider_config) -> list[str]:
    models = provider_config.models or {}
    if provider == "codex":
        enabled = models.get("enabled_profiles", ["high", "medium", "low"])
        enabled_profiles = [str(item) for item in enabled] if isinstance(enabled, list) else ["high", "medium", "low"]
        return [item for item in ("high", "medium", "low") if item in enabled_profiles or item in (models.get("thinking_levels") or {})]
    raw_enabled = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw_enabled] if isinstance(raw_enabled, list) else []
    if provider == "claude":
        return [key for key in ("default", "powerful", "cost_effective") if key in enabled_profiles or key == "default"]
    if provider == "gemini":
        return [key for key in ("powerful", "cost_effective", "auto") if key in enabled_profiles or key == "auto"]
    return enabled_profiles or ["default"]



def _apply_provider_profile_choice(provider: str, provider_config, profile_key: str) -> None:
    models = provider_config.models or {}
    raw = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw] if isinstance(raw, list) else []
    if profile_key and profile_key not in enabled_profiles:
        enabled_profiles.append(profile_key)
        models["enabled_profiles"] = enabled_profiles
        provider_config.models = models

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
            cfg = models.get(profile_key, {}) if isinstance(models.get(profile_key, {}), dict) else {}
            if cfg.get("model"):
                provider_config.models["default"] = cfg["model"]
        return

    provider_config.model_selection = profile_key
    cfg = models.get(profile_key, {}) if isinstance(models.get(profile_key, {}), dict) else {}
    if cfg.get("model"):
        provider_config.models["default"] = cfg["model"]



def _edit_provider_models(
    state: ConfigMenuState,
    config: Config,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    provider_choice = _ask_screen_choice(_provider_picker_screen(state, config), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if provider_choice in {"b", "q"}:
        return provider_choice
    provider = ALL_PROVIDER_KEYS[int(provider_choice) - 1]
    profile_choice = _ask_screen_choice(_provider_profile_screen(state, config, provider=provider), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if profile_choice in {"b", "q"}:
        return profile_choice
    profile_keys = _provider_profile_keys(provider, config.providers[provider])
    state.provider_model_selection[provider] = profile_keys[int(profile_choice) - 1]
    return None



def _pricing_mode_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(PRICING_MODE_OPTIONS, start=1)
    ]
    default_value = next((str(index) for index, item in enumerate(PRICING_MODE_OPTIONS, start=1) if item["key"] == state.economics_pricing_mode), "1")
    return ChoiceScreen(
        title=_msg(lang, "screen_pricing_title"),
        hint=_msg(lang, "screen_pricing_hint"),
        note=_msg(lang, "screen_pricing_note"),
        options=options,
        default_value=default_value,
    )



def _edit_pricing_mode(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    choice = _ask_screen_choice(_pricing_mode_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice in {"b", "q"}:
        return choice
    state.economics_pricing_mode = PRICING_MODE_OPTIONS[int(choice) - 1]["key"]
    return None



def _billing_provider_picker_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), CONTROLLER_LABELS[provider], _provider_billing_summary(state, provider, lang=lang), provider=provider)
        for index, provider in enumerate(ALL_PROVIDER_KEYS, start=1)
    ]
    return ChoiceScreen(
        title=_msg(lang, "screen_billing_provider_title"),
        hint=_msg(lang, "screen_billing_provider_hint"),
        note=_msg(lang, "screen_billing_provider_note"),
        options=options,
        default_value="1",
    )



def _billing_mode_screen(state: ConfigMenuState, *, provider: str) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(BILLING_MODE_OPTIONS, start=1)
    ]
    current = state.provider_billing_modes.get(provider, "unconfigured")
    default_value = next((str(index) for index, item in enumerate(BILLING_MODE_OPTIONS, start=1) if item["key"] == current), "1")
    return ChoiceScreen(
        title=f"{_msg(lang, 'screen_billing_mode_title')} · {CONTROLLER_LABELS[provider]}",
        hint=_msg(lang, "screen_billing_mode_hint"),
        note="",
        options=options,
        default_value=default_value,
    )



def _quota_window_screen(state: ConfigMenuState, *, provider: str) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(QUOTA_WINDOW_OPTIONS, start=1)
    ]
    current = state.provider_quota_windows.get(provider, "none")
    default_value = next((str(index) for index, item in enumerate(QUOTA_WINDOW_OPTIONS, start=1) if item["key"] == current), "1")
    return ChoiceScreen(
        title=f"{_msg(lang, 'screen_quota_title')} · {CONTROLLER_LABELS[provider]}",
        hint=_msg(lang, "screen_quota_hint"),
        note="",
        options=options,
        default_value=default_value,
    )



def _relative_cost_screen(state: ConfigMenuState, *, provider: str) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(RELATIVE_COST_OPTIONS, start=1)
    ]
    current = state.provider_cost_tiers.get(provider, "standard")
    default_value = next((str(index) for index, item in enumerate(RELATIVE_COST_OPTIONS, start=1) if item["key"] == current), "2")
    return ChoiceScreen(
        title=f"{_msg(lang, 'screen_relative_cost_title')} · {CONTROLLER_LABELS[provider]}",
        hint=_msg(lang, "screen_relative_cost_hint"),
        note="",
        options=options,
        default_value=default_value,
    )



def _edit_provider_billing(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    provider_choice = _ask_screen_choice(_billing_provider_picker_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if provider_choice in {"b", "q"}:
        return provider_choice
    provider = ALL_PROVIDER_KEYS[int(provider_choice) - 1]

    mode_choice = _ask_screen_choice(_billing_mode_screen(state, provider=provider), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if mode_choice in {"b", "q"}:
        return mode_choice
    state.provider_billing_modes[provider] = BILLING_MODE_OPTIONS[int(mode_choice) - 1]["key"]

    if state.provider_billing_modes[provider] == "unconfigured":
        state.provider_quota_windows[provider] = "none"
        state.provider_cost_tiers[provider] = "standard"
        return None

    if state.provider_billing_modes[provider] == "subscription-quota":
        quota_choice = _ask_screen_choice(_quota_window_screen(state, provider=provider), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if quota_choice in {"b", "q"}:
            return quota_choice
        state.provider_quota_windows[provider] = QUOTA_WINDOW_OPTIONS[int(quota_choice) - 1]["key"]
    else:
        state.provider_quota_windows[provider] = "none"

    relative_choice = _ask_screen_choice(_relative_cost_screen(state, provider=provider), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if relative_choice in {"b", "q"}:
        return relative_choice
    state.provider_cost_tiers[provider] = RELATIVE_COST_OPTIONS[int(relative_choice) - 1]["key"]
    return None



def _run_economics_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_economics_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        if choice == "1":
            result = _edit_pricing_mode(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _edit_cost_bias(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = _edit_provider_billing(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"



def _with_current(label: str, current: str) -> str:
    return f"{label} · {current}" if current else label



def _defaults_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_defaults_title"),
        hint=_msg(lang, "screen_defaults_hint"),
        note=_msg(lang, "screen_defaults_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_agents"), _enabled_agents_label(state.form, lang=lang)), _msg(lang, "item_agents_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_controller"), CONTROLLER_LABELS.get(state.form.controller, state.form.controller.title())), _msg(lang, "item_controller_desc"), provider=state.form.controller),
            ChoiceOption("3", _with_current(_msg(lang, "item_runtime"), _runtime_label(lang, state.form.runtime_mode)), _msg(lang, "item_runtime_desc")),
            ChoiceOption("4", _with_current(_msg(lang, "item_entry"), _entry_label(lang, state.form.entry_surface)), _msg(lang, "item_entry_desc")),
            ChoiceOption("5", _with_current(_msg(lang, "item_collaboration"), _collaboration_label(lang, state.form.auto_collaboration_enabled)), _msg(lang, "item_collaboration_desc")),
        ],
        default_value="1",
    )



def _routing_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_routing_title"),
        hint=_msg(lang, "screen_routing_hint"),
        note=_msg(lang, "screen_routing_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_preset"), _preset_label(lang, state.collaboration_preset)), _msg(lang, "item_preset_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_intents"), _intent_summary(state, lang=lang)), _msg(lang, "item_intents_desc")),
            ChoiceOption("3", _msg(lang, "item_agent_preferences"), _msg(lang, "item_agent_preferences_desc")),
        ],
        default_value="1",
    )



def _providers_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_providers_title"),
        hint=_msg(lang, "screen_providers_hint"),
        note=_msg(lang, "screen_providers_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_models"), _provider_models_summary(state, lang=lang)), _msg(lang, "item_models_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_economics"), _economics_summary(state, lang=lang)), _msg(lang, "item_economics_desc")),
        ],
        default_value="1",
    )



def _economics_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    billing_overview = _billing_mode_label(lang, "unconfigured") if _configured_billing_count(state) == 0 else (
        f"{_configured_billing_count(state)}/{len(ALL_PROVIDER_KEYS)} configured" if lang == "en-US" else f"{_configured_billing_count(state)}/{len(ALL_PROVIDER_KEYS)} 个模型提供方已配置"
    )
    return ChoiceScreen(
        title=_msg(lang, "screen_economics_title"),
        hint=_msg(lang, "screen_economics_hint"),
        note=_msg(lang, "screen_economics_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_pricing_mode"), _pricing_mode_label(lang, state.economics_pricing_mode)), _msg(lang, "item_pricing_mode_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_cost_bias"), _cost_bias_label(lang, state.cost_bias)), _msg(lang, "item_cost_bias_desc")),
            ChoiceOption("3", _with_current(_msg(lang, "item_provider_billing"), billing_overview), _msg(lang, "item_provider_billing_desc")),
        ],
        default_value="1",
    )



def _interface_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_interface_title"),
        hint=_msg(lang, "screen_interface_hint"),
        note=_msg(lang, "screen_interface_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_language"), LANGUAGE_LABELS.get(state.form.ui_language, state.form.ui_language)), _msg(lang, "item_language_desc")),
        ],
        default_value="1",
    )



def _run_defaults_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_defaults_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        step_map = {"1": "enabled_agents", "2": "controller", "3": "runtime", "4": "entry", "5": "collaboration"}
        result = _edit_basic_step(state, step_id=step_map[choice], input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"



def _run_routing_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_routing_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        if choice == "1":
            result = _edit_collaboration_preset(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _edit_intent_preferences(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = _show_agent_preferences_screen(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"



def _run_providers_section(
    state: ConfigMenuState,
    config: Config,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_providers_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        if choice == "1":
            result = _edit_provider_models(state, config, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = _run_economics_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"



def _run_interface_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_interface_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        result = _edit_basic_step(state, step_id="language", input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"



def _routing_mode(state: ConfigMenuState) -> str:
    if state.cost_bias == "balanced" and all(
        state.intent_preferences.get(intent, []) == RECOMMENDED_INTENT_PREFERENCES[intent]
        for intent in INTENT_ORDER
    ):
        return "recommended"
    return "custom"



def _apply_state_to_config(config: Config, state: ConfigMenuState) -> None:
    apply_setup_form(config, state.form)
    config.routing = {
        "mode": _routing_mode(state),
        "cost_bias": state.cost_bias,
        "intent_preferences": {intent: list(state.intent_preferences[intent]) for intent in INTENT_ORDER},
    }
    config.economics = {
        "pricing_mode": state.economics_pricing_mode,
        "providers": {
            provider: {
                "billing_mode": state.provider_billing_modes.get(provider, "unconfigured"),
                "quota_window": state.provider_quota_windows.get(provider, "none"),
                "relative_cost_tier": state.provider_cost_tiers.get(provider, "standard"),
            }
            for provider in ALL_PROVIDER_KEYS
        },
    }
    auto_cfg = dict(config.auto_collaboration or {})
    auto_cfg["preset"] = state.collaboration_preset
    config.auto_collaboration = auto_cfg
    for provider, profile in state.provider_model_selection.items():
        if provider in config.providers:
            _apply_provider_profile_choice(provider, config.providers[provider], profile)



def run_config_menu_prompt(
    config: Config,
    *,
    input_fn: InputFn = _prompt_input,
    console_obj: Console | None = None,
    clear_screen: bool = True,
    selector_fn: MenuSelectFn | None = None,
) -> bool:
    console_obj = console_obj or Console()
    state = ConfigMenuState.from_config(config)

    while True:
        choice = _ask_menu_choice(
            state,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            selector_fn=selector_fn,
        )
        if choice == "q":
            return False
        if choice == "5":
            _apply_state_to_config(config, state)
            config.save()
            return True

        if choice == "1":
            result = _run_defaults_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _run_routing_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "3":
            result = _run_providers_section(state, config, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "4":
            result = _run_interface_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = None

        if result == "q":
            return False

from ai_collab import __version__ as AI_COLLAB_VERSION
from ai_collab.core.config import normalize_application_config as _normalize_application_config


@dataclass
class ConfigMenuState:
    form: SetupFormData
    collaboration_preset: str
    cost_bias: str
    intent_preferences: dict[str, list[str]]
    provider_model_selection: dict[str, str]
    economics_pricing_mode: str
    quota_strategy: str
    cross_provider_fallback: str
    provider_billing_modes: dict[str, str]
    provider_quota_windows: dict[str, str]
    provider_cost_tiers: dict[str, str]
    application_auto_check_updates: bool

    @classmethod
    def from_config(cls, config: Config) -> "ConfigMenuState":
        routing = normalize_routing_config(getattr(config, "routing", {}))
        economics = normalize_economics_config(getattr(config, "economics", {}))
        application = _normalize_application_config(getattr(config, "application", {}))
        providers_cfg = economics.get("providers", {})
        return cls(
            form=resolve_setup_defaults(config),
            collaboration_preset=_resolve_collaboration_preset(config),
            cost_bias=str(routing.get("cost_bias", "balanced")),
            intent_preferences=dict(routing.get("intent_preferences", {})),
            provider_model_selection={
                provider: _current_provider_profile(provider, config.providers[provider])
                for provider in ALL_PROVIDER_KEYS
                if provider in config.providers
            },
            economics_pricing_mode=str(economics.get("pricing_mode", "disabled")),
            quota_strategy=str(economics.get("quota_strategy", "balanced")),
            cross_provider_fallback=str(economics.get("cross_provider_fallback", "same-provider-first")),
            provider_billing_modes={
                provider: str((providers_cfg.get(provider) or {}).get("billing_mode", "unconfigured"))
                for provider in ALL_PROVIDER_KEYS
            },
            provider_quota_windows={
                provider: str((providers_cfg.get(provider) or {}).get("quota_window", "none"))
                for provider in ALL_PROVIDER_KEYS
            },
            provider_cost_tiers={
                provider: str((providers_cfg.get(provider) or {}).get("relative_cost_tier", "standard"))
                for provider in ALL_PROVIDER_KEYS
            },
            application_auto_check_updates=bool(application.get("auto_check_updates", True)),
        )


def _quota_strategy_label(lang: str, quota_strategy: str) -> str:
    for item in QUOTA_STRATEGY_OPTIONS:
        if item["key"] == quota_strategy:
            return str(item[lang])
    return quota_strategy


def _cross_provider_fallback_label(lang: str, fallback_mode: str) -> str:
    for item in CROSS_PROVIDER_FALLBACK_OPTIONS:
        if item["key"] == fallback_mode:
            return str(item[lang])
    return fallback_mode


def _update_auto_label(lang: str, enabled: bool) -> str:
    if lang == "zh-CN":
        return "自动检查更新" if enabled else "手动检查更新"
    return "Auto-check enabled" if enabled else "Manual checks"


def _replace_or_append_cli_flag(cli: str, flag: str, value: str) -> str:
    try:
        parts = shlex.split(cli)
    except ValueError:
        parts = cli.strip().split()

    cleaned: list[str] = []
    skip_next = False
    for part in parts:
        if skip_next:
            skip_next = False
            continue
        if part == flag:
            skip_next = True
            continue
        if part.startswith(f"{flag}="):
            continue
        cleaned.append(part)

    if value:
        cleaned.extend([flag, value])
    return " ".join(shlex.quote(item) for item in cleaned)


def _provider_model_id(provider: str, provider_config, profile_key: str) -> str:
    models = provider_config.models or {}
    if provider == "codex":
        thinking_levels = models.get("thinking_levels", {}) if isinstance(models.get("thinking_levels", {}), dict) else {}
        level_cfg = thinking_levels.get(profile_key, {}) if isinstance(thinking_levels.get(profile_key, {}), dict) else {}
        default_model = str(models.get("default_model", "gpt-5.4")).strip() or "gpt-5.4"
        return str(level_cfg.get("model") or default_model).strip() or default_model
    if provider == "claude":
        if profile_key in {"powerful", "cost_effective"}:
            cfg = models.get(profile_key, {}) if isinstance(models.get(profile_key, {}), dict) else {}
            model_name = str(cfg.get("model", "")).strip()
            if model_name:
                return model_name
        return str(models.get("default", "claude-sonnet-4-6")).strip() or "claude-sonnet-4-6"
    if provider == "gemini":
        if profile_key == "auto":
            return "gemini-cli-auto"
        cfg = models.get(profile_key, {}) if isinstance(models.get(profile_key, {}), dict) else {}
        if cfg.get("model"):
            return str(cfg.get("model")).strip()
        fallback = "gemini-3.1-pro-preview" if profile_key != "cost_effective" else "gemini-3-flash-preview"
        return str(models.get("default", fallback)).strip() or fallback
    return ""


def _provider_model_summary_line(provider: str, provider_config, profile_key: str, *, lang: str) -> str:
    model_id = _provider_model_id(provider, provider_config, profile_key)
    return f"{model_id} · {_profile_label(lang, profile_key)}"


def _provider_models_summary(state: ConfigMenuState, *, lang: str) -> str:
    count = len([provider for provider in ALL_PROVIDER_KEYS if provider in state.provider_model_selection])
    if lang == "zh-CN":
        return f"{count} 个模型提供方已设定"
    return f"{count} model providers configured"


def _economics_summary(state: ConfigMenuState, *, lang: str) -> str:
    pricing_mode = state.economics_pricing_mode
    configured = _configured_billing_count(state)
    if pricing_mode == "disabled":
        return "Pricing disabled" if lang == "en-US" else "未启用价格感知"
    configured_text = f"{configured}/{len(ALL_PROVIDER_KEYS)} configured" if lang == "en-US" else f"{configured}/{len(ALL_PROVIDER_KEYS)} 已设定"
    return f"{_pricing_mode_label(lang, pricing_mode)} · {configured_text}"


def _app_summary(state: ConfigMenuState, *, lang: str) -> str:
    language = LANGUAGE_LABELS.get(state.form.ui_language, state.form.ui_language)
    update = "自动检查开启" if state.application_auto_check_updates else "手动检查"
    if lang == "en-US":
        update = "Auto-check on" if state.application_auto_check_updates else "Manual checks"
    return f"{language} / {update}"


def _build_menu_items(state: ConfigMenuState) -> list[ConfigMenuItem]:
    lang = _lang(state.form.ui_language)
    return [
        ConfigMenuItem("1", _msg(lang, "group_defaults"), _defaults_summary(state, lang=lang), _msg(lang, "group_defaults_desc"), "edit"),
        ConfigMenuItem("2", _msg(lang, "group_routing"), _routing_summary(state, lang=lang), _msg(lang, "group_routing_desc"), "edit"),
        ConfigMenuItem("3", _msg(lang, "group_providers"), _models_cost_summary(state, lang=lang), _msg(lang, "group_providers_desc"), "edit"),
        ConfigMenuItem("4", _msg(lang, "group_interface"), _app_summary(state, lang=lang), _msg(lang, "group_interface_desc"), "edit"),
        ConfigMenuItem("5", _msg(lang, "item_save"), "", _msg(lang, "item_save_desc"), "save"),
    ]


def _provider_picker_screen(state: ConfigMenuState, config: Config) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = []
    for index, provider in enumerate(ALL_PROVIDER_KEYS, start=1):
        if provider not in config.providers:
            continue
        provider_config = config.providers[provider]
        current_key = state.provider_model_selection.get(provider, _current_provider_profile(provider, provider_config))
        options.append(
            ChoiceOption(
                str(index),
                CONTROLLER_LABELS[provider],
                _provider_model_summary_line(provider, provider_config, current_key, lang=lang),
                provider=provider,
            )
        )
    return ChoiceScreen(
        title=_msg(lang, "screen_provider_title"),
        hint=_msg(lang, "screen_provider_hint"),
        note=_msg(lang, "screen_provider_note"),
        options=options,
        default_value="1",
    )


def _provider_profile_options(provider: str, provider_config, *, lang: str) -> list[ChoiceOption]:
    models = provider_config.models or {}
    if provider == "codex":
        thinking_levels = models.get("thinking_levels", {}) if isinstance(models.get("thinking_levels", {}), dict) else {}
        order = _provider_profile_keys(provider, provider_config)
        options: list[ChoiceOption] = []
        for index, key in enumerate(order, start=1):
            desc_parts = [_provider_model_id(provider, provider_config, key)]
            level_desc = str((thinking_levels.get(key) or {}).get("description", "")).strip()
            if level_desc:
                desc_parts.append(level_desc)
            options.append(ChoiceOption(str(index), _profile_label(lang, key), " · ".join(desc_parts), provider=provider))
        return options

    raw_enabled = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw_enabled] if isinstance(raw_enabled, list) else []
    if provider == "claude":
        order = [key for key in ("default", "powerful", "cost_effective") if key in enabled_profiles or key == "default"]
    elif provider == "gemini":
        order = [key for key in ("powerful", "cost_effective", "auto") if key in enabled_profiles or key == "auto"]
    else:
        order = enabled_profiles or ["default"]

    options = []
    for index, key in enumerate(order, start=1):
        cfg = models.get(key, {}) if isinstance(models.get(key, {}), dict) else {}
        model_name = _provider_model_id(provider, provider_config, key)
        desc = str(cfg.get("description", "")).strip()
        description = model_name if not desc else f"{model_name} · {desc}"
        options.append(ChoiceOption(str(index), _profile_label(lang, key), description, provider=provider))
    return options


def _provider_profile_keys(provider: str, provider_config) -> list[str]:
    models = provider_config.models or {}
    raw_enabled = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw_enabled] if isinstance(raw_enabled, list) else []
    if provider == "codex":
        thinking_levels = models.get("thinking_levels", {}) if isinstance(models.get("thinking_levels", {}), dict) else {}
        ordered = [item for item in enabled_profiles if item in thinking_levels]
        for key in ("low", "medium", "high", "xhigh"):
            if key in thinking_levels and key not in ordered:
                ordered.append(key)
        return ordered or ["high"]
    if provider == "claude":
        return [key for key in ("default", "powerful", "cost_effective") if key in enabled_profiles or key == "default"]
    if provider == "gemini":
        return [key for key in ("powerful", "cost_effective", "auto") if key in enabled_profiles or key == "auto"]
    return enabled_profiles or ["default"]


def _apply_provider_profile_choice(provider: str, provider_config, profile_key: str) -> None:
    models = provider_config.models or {}
    raw = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw] if isinstance(raw, list) else []
    if profile_key and profile_key not in enabled_profiles:
        enabled_profiles.append(profile_key)
        models["enabled_profiles"] = enabled_profiles
        provider_config.models = models

    if provider == "codex":
        provider_config.models["default_model"] = str(provider_config.models.get("default_model", "gpt-5.4") or "gpt-5.4")
        provider_config.models["default_thinking"] = profile_key if profile_key in {"low", "medium", "high", "xhigh"} else "high"
        thinking_levels = provider_config.models.get("thinking_levels", {})
        level_cfg = thinking_levels.get(profile_key, {}) if isinstance(thinking_levels, dict) and isinstance(thinking_levels.get(profile_key, {}), dict) else {}
        selected_model = str(level_cfg.get("model") or provider_config.models["default_model"]).strip()
        if selected_model:
            provider_config.models["default_model"] = selected_model
            provider_config.cli = _replace_or_append_cli_flag(provider_config.cli, "--model", selected_model)
        provider_config.model_selection = "default"
        return

    if provider == "gemini":
        if profile_key == "auto":
            provider_config.models["auto_route_default"] = True
            provider_config.model_selection = "default"
        else:
            provider_config.models["auto_route_default"] = False
            provider_config.model_selection = profile_key
            cfg = models.get(profile_key, {}) if isinstance(models.get(profile_key, {}), dict) else {}
            if cfg.get("model"):
                provider_config.models["default"] = cfg["model"]
        return

    provider_config.model_selection = profile_key
    cfg = models.get(profile_key, {}) if isinstance(models.get(profile_key, {}), dict) else {}
    if cfg.get("model"):
        provider_config.models["default"] = cfg["model"]


def _quota_strategy_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(QUOTA_STRATEGY_OPTIONS, start=1)
    ]
    default_value = next((str(index) for index, item in enumerate(QUOTA_STRATEGY_OPTIONS, start=1) if item["key"] == state.quota_strategy), "1")
    return ChoiceScreen(
        title=_msg(lang, "screen_quota_strategy_title"),
        hint=_msg(lang, "screen_quota_strategy_hint"),
        note="",
        options=options,
        default_value=default_value,
    )


def _cross_provider_fallback_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    options = [
        ChoiceOption(str(index), str(item[lang]), str(item[f"desc_{lang}"]))
        for index, item in enumerate(CROSS_PROVIDER_FALLBACK_OPTIONS, start=1)
    ]
    default_value = next((str(index) for index, item in enumerate(CROSS_PROVIDER_FALLBACK_OPTIONS, start=1) if item["key"] == state.cross_provider_fallback), "1")
    return ChoiceScreen(
        title=_msg(lang, "screen_fallback_title"),
        hint=_msg(lang, "screen_fallback_hint"),
        note="",
        options=options,
        default_value=default_value,
    )


def _edit_quota_strategy(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    choice = _ask_screen_choice(_quota_strategy_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice in {"b", "q"}:
        return choice
    state.quota_strategy = QUOTA_STRATEGY_OPTIONS[int(choice) - 1]["key"]
    return None


def _edit_cross_provider_fallback(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    choice = _ask_screen_choice(_cross_provider_fallback_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice in {"b", "q"}:
        return choice
    state.cross_provider_fallback = CROSS_PROVIDER_FALLBACK_OPTIONS[int(choice) - 1]["key"]
    return None


def _economics_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    billing_overview = (
        "No provider billing configured" if lang == "en-US" else "暂无模型提供方计费设定"
    )
    if _configured_billing_count(state) > 0:
        billing_overview = f"{_configured_billing_count(state)}/{len(ALL_PROVIDER_KEYS)} configured" if lang == "en-US" else f"{_configured_billing_count(state)}/{len(ALL_PROVIDER_KEYS)} 已设定"
    return ChoiceScreen(
        title=_msg(lang, "screen_economics_title"),
        hint=_msg(lang, "screen_economics_hint"),
        note=_msg(lang, "screen_economics_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_pricing_mode"), _pricing_mode_label(lang, state.economics_pricing_mode)), _msg(lang, "item_pricing_mode_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_cost_bias"), _cost_bias_label(lang, state.cost_bias)), _msg(lang, "item_cost_bias_desc")),
            ChoiceOption("3", _with_current(_msg(lang, "item_provider_billing"), billing_overview), _msg(lang, "item_provider_billing_desc")),
            ChoiceOption("4", _with_current(_msg(lang, "item_quota_strategy"), _quota_strategy_label(lang, state.quota_strategy)), _msg(lang, "item_quota_strategy_desc")),
            ChoiceOption("5", _with_current(_msg(lang, "item_cross_provider_fallback"), _cross_provider_fallback_label(lang, state.cross_provider_fallback)), _msg(lang, "item_cross_provider_fallback_desc")),
        ],
        default_value="1",
    )


def _run_economics_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_economics_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        if choice == "1":
            result = _edit_pricing_mode(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _edit_cost_bias(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "3":
            result = _edit_provider_billing(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "4":
            result = _edit_quota_strategy(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = _edit_cross_provider_fallback(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"


def _app_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_interface_title"),
        hint=_msg(lang, "screen_interface_hint"),
        note=_msg(lang, "screen_interface_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_language"), LANGUAGE_LABELS.get(state.form.ui_language, state.form.ui_language)), _msg(lang, "item_language_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_about"), f"v{AI_COLLAB_VERSION}"), _msg(lang, "item_about_desc")),
            ChoiceOption("3", _with_current(_msg(lang, "item_updates"), _update_auto_label(lang, state.application_auto_check_updates)), _msg(lang, "item_updates_desc")),
        ],
        default_value="1",
    )


def _about_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    note_lines = [
        _msg(lang, "screen_about_note"),
        f"Version: {AI_COLLAB_VERSION}" if lang == "en-US" else f"版本：{AI_COLLAB_VERSION}",
    ]
    return ChoiceScreen(
        title=_msg(lang, "screen_about_title"),
        hint=_msg(lang, "screen_about_hint"),
        note="\n".join(note_lines),
        options=[],
        default_value="q",
    )


def _updates_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_updates_title"),
        hint=_msg(lang, "screen_updates_hint"),
        note=_msg(lang, "screen_updates_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_update_auto"), _update_auto_label(lang, state.application_auto_check_updates)), _msg(lang, "item_update_auto_desc")),
        ],
        default_value="1",
    )


def _update_auto_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "item_update_auto"),
        hint=_msg(lang, "item_update_auto_desc"),
        note="",
        options=[
            ChoiceOption("1", "Enabled" if lang == "en-US" else "启用", "Check on startup only." if lang == "en-US" else "仅在启动时检查。"),
            ChoiceOption("2", "Disabled" if lang == "en-US" else "关闭", "You will check manually when needed." if lang == "en-US" else "需要时再手动检查。"),
        ],
        default_value="1" if state.application_auto_check_updates else "2",
    )


def _show_about_screen(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    choice = _ask_screen_choice(_about_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice == "q":
        return "q"
    return None


def _edit_update_auto(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    choice = _ask_screen_choice(_update_auto_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
    if choice in {"b", "q"}:
        return choice
    state.application_auto_check_updates = choice == "1"
    return None


def _run_updates_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_updates_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        result = _edit_update_auto(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"


def _run_app_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_app_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        if choice == "1":
            result = _edit_basic_step(state, step_id="language", input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _show_about_screen(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = _run_updates_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"


def _apply_state_to_config(config: Config, state: ConfigMenuState) -> None:
    apply_setup_form(config, state.form)
    config.routing = {
        "mode": _routing_mode(state),
        "cost_bias": state.cost_bias,
        "intent_preferences": {intent: list(state.intent_preferences[intent]) for intent in INTENT_ORDER},
    }
    config.economics = {
        "pricing_mode": state.economics_pricing_mode,
        "quota_strategy": state.quota_strategy,
        "cross_provider_fallback": state.cross_provider_fallback,
        "providers": {
            provider: {
                "billing_mode": state.provider_billing_modes.get(provider, "unconfigured"),
                "quota_window": state.provider_quota_windows.get(provider, "none"),
                "relative_cost_tier": state.provider_cost_tiers.get(provider, "standard"),
            }
            for provider in ALL_PROVIDER_KEYS
        },
    }
    config.application = {
        "auto_check_updates": state.application_auto_check_updates,
    }
    auto_cfg = dict(config.auto_collaboration or {})
    auto_cfg["preset"] = state.collaboration_preset
    config.auto_collaboration = auto_cfg
    for provider, profile in state.provider_model_selection.items():
        if provider in config.providers:
            _apply_provider_profile_choice(provider, config.providers[provider], profile)


def run_config_menu_prompt(
    config: Config,
    *,
    input_fn: InputFn = _prompt_input,
    console_obj: Console | None = None,
    clear_screen: bool = True,
    selector_fn: MenuSelectFn | None = None,
) -> bool:
    console_obj = console_obj or Console()
    state = ConfigMenuState.from_config(config)

    while True:
        choice = _ask_menu_choice(
            state,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            selector_fn=selector_fn,
        )
        if choice == "q":
            return False
        if choice == "5":
            _apply_state_to_config(config, state)
            config.save()
            return True

        if choice == "1":
            result = _run_defaults_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _run_routing_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "3":
            result = _run_providers_section(state, config, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "4":
            result = _run_app_section(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = None

        if result == "q":
            return False

TEXT["en-US"].update(
    {
        "group_interface_desc": "Language, update behavior, and product overview.",
        "item_updates": "Check updates",
        "item_updates_desc": "Show current version and local update status.",
        "item_update_auto_desc": "Check for a newer version on startup; this never auto-installs updates.",
        "screen_interface_hint": "Adjust language, update behavior, and about page.",
        "screen_interface_note": "Keep application settings flat and lightweight instead of nesting every small preference.",
        "screen_updates_title": "Check updates",
        "screen_updates_hint": "Show local version and current update behavior.",
        "screen_updates_note": "This menu does not fetch remote release metadata yet. For now it shows the current installed version and your local update preference.",
        "item_about_desc": "Open a full-screen introduction page with product positioning and version details.",
    }
)
TEXT["zh-CN"].update(
    {
        "group_interface_desc": "语言、更新与关于。",
        "item_updates": "检查更新",
        "item_updates_desc": "查看当前版本与本地更新状态。",
        "item_update_auto_desc": "启动时检查新版本；不会自动替你安装更新。",
        "screen_interface_hint": "调整语言、更新行为与关于页。",
        "screen_interface_note": "应用设置保持扁平，不为每个小开关再套一层菜单。",
        "screen_updates_title": "检查更新",
        "screen_updates_hint": "查看当前版本与当前更新方式。",
        "screen_updates_note": "当前菜单还没有接入在线版本源；这里先展示本地版本和你的更新偏好。",
        "item_about_desc": "打开全屏介绍页，查看产品定位、版本信息与终端方向。",
    }
)


ABOUT_ASCII = (
    "   █████╗ ██╗        ██████╗ ██████╗ ██╗      █████╗ ██████╗",
    "  ██╔══██╗██║       ██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗",
    "  ███████║██║       ██║     ██║   ██║██║     ███████║██████╔╝",
    "  ██╔══██║██║       ██║     ██║   ██║██║     ██╔══██║██╔══██╗",
    "  ██║  ██║██║██████╗╚██████╗╚██████╔╝███████╗██║  ██║██████╔╝",
    "  ╚═╝  ╚═╝╚═╝╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝",
)


def _runtime_summary_label(lang: str, runtime_mode: str) -> str:
    if runtime_mode == "tmux":
        return "tmux"
    return "direct"


def _localized_profile_description(lang: str, provider: str, profile_key: str, fallback: str = "") -> str:
    mapping = {
        "en-US": {
            ("codex", "low"): "Good for terminal checks, tiny edits, formatting, and quick cleanup.",
            ("codex", "medium"): "Good for routine feature work, refactors, and focused bug fixes.",
            ("codex", "high"): "Good for multi-file implementation, deeper debugging, and integration work.",
            ("codex", "xhigh"): "Best for hard problems, architecture tradeoffs, and long-horizon code changes.",
            ("claude", "default"): "Balanced default for most codebase understanding, editing, and debugging tasks.",
            ("claude", "cost_effective"): "Faster lightweight review and triage for everyday coding support.",
            ("claude", "powerful"): "Stronger review and architecture reasoning for harder repository work.",
            ("gemini", "auto"): "Let Gemini CLI choose the concrete model automatically.",
            ("gemini", "cost_effective"): "Faster classification, research support, and lightweight design exploration.",
            ("gemini", "powerful"): "Higher-quality multimodal exploration, synthesis, and long-context analysis.",
        },
        "zh-CN": {
            ("codex", "low"): "适合终端检查、局部小改、格式整理与快速收尾。",
            ("codex", "medium"): "适合常规功能实现、重构与聚焦型修复。",
            ("codex", "high"): "适合多文件实现、较深调试与集成落地。",
            ("codex", "xhigh"): "适合难题攻坚、架构权衡与长链路改造。",
            ("claude", "default"): "默认均衡档位，适合大多数代码库理解、编辑与调试任务。",
            ("claude", "cost_effective"): "更快的轻量审查与日常分诊，适合常规协作支持。",
            ("claude", "powerful"): "更强的审查与架构推理，适合复杂代码库与深度方案评估。",
            ("gemini", "auto"): "让 Gemini CLI 自行决定具体模型。",
            ("gemini", "cost_effective"): "更快的分类、调研支持与轻量设计探索。",
            ("gemini", "powerful"): "更高质量的多模态探索、综合分析与长上下文整合。",
        },
    }
    return mapping.get(_lang(lang), {}).get((provider, profile_key), fallback)


def _defaults_summary(state: ConfigMenuState, *, lang: str) -> str:
    controller = CONTROLLER_LABELS.get(state.form.controller, state.form.controller.title())
    entry = _entry_label(lang, state.form.entry_surface)
    runtime = _runtime_summary_label(lang, state.form.runtime_mode)
    if lang == "zh-CN":
        return f"主控 {controller} / {runtime} / {entry}"
    return f"Lead {controller} / {runtime} / {entry}"


def _routing_summary(state: ConfigMenuState, *, lang: str) -> str:
    preset = _preset_label(lang, state.collaboration_preset)
    overrides = _intent_override_count(state)
    if overrides <= 0:
        return f"{preset} / {_cost_bias_label(lang, state.cost_bias)}"
    if lang == "zh-CN":
        return f"{preset} / 已调整 {overrides} 项"
    return f"{preset} / {overrides} overrides"


def _models_cost_summary(state: ConfigMenuState, *, lang: str) -> str:
    provider_count = len([provider for provider in ALL_PROVIDER_KEYS if provider in state.provider_model_selection])
    pricing = "Pricing off" if lang == "en-US" else "未启用价格感知"
    if state.economics_pricing_mode != "disabled":
        pricing = _pricing_mode_label(lang, state.economics_pricing_mode)
    if lang == "zh-CN":
        return f"{provider_count} 个模型提供方 / {pricing}"
    return f"{provider_count} providers / {pricing}"


def _interface_summary(state: ConfigMenuState) -> str:
    lang = _lang(state.form.ui_language)
    language = LANGUAGE_LABELS.get(state.form.ui_language, state.form.ui_language)
    update = "自动检查开启" if state.application_auto_check_updates and lang == "zh-CN" else (
        "手动检查" if lang == "zh-CN" else ("Auto-check on" if state.application_auto_check_updates else "Manual checks")
    )
    if lang == "en-US" and state.application_auto_check_updates:
        update = "Auto-check on"
    return f"{language} / {update}"


def render_config_menu_screen(config_or_state: Config | ConfigMenuState) -> str:
    state = config_or_state if isinstance(config_or_state, ConfigMenuState) else ConfigMenuState.from_config(config_or_state)
    lang = _lang(state.form.ui_language)
    items = _build_menu_items(state)
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=140)
    for line in build_init_banner(100):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console.print(Text(line, style=style))
    console.print()
    console.print(Text(_msg(lang, "menu_title"), style="bold"))
    console.print(Text(_msg(lang, "menu_hint"), style="dim"))
    console.print(Text(_msg(lang, "menu_note"), style="dim italic"))
    console.print()
    for index, item in enumerate(items):
        prefix = "›" if index == 0 else " "
        console.print(f"{prefix} {item.value}. {item.label}")
        if item.current:
            console.print(Text(f"    {item.current}", style="grey50"))
        console.print(Text(f"    {item.description}", style="dim italic"))
    console.print(f"  q. {_msg(lang, 'quit')}")
    console.print()
    console.print(Text(_msg(lang, "footer"), style="dim"))
    return buffer.getvalue().rstrip() + "\n"


def _select_menu_with_prompt_toolkit(
    state: ConfigMenuState,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    items = _render_menu_header(state, console_obj=console_obj, clear_screen=clear_screen)
    lang = _lang(state.form.ui_language)
    values = [item.value for item in items] + ["q"]
    pointed_index = 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens() -> list[tuple[str, str]]:
        rows = _build_menu_rows(items, pointed_value=_current_value(), lang=lang)
        fragments: list[tuple[str, str]] = []
        for row in rows:
            fragments.append(("", row.prefix))
            fragments.append((row.label_style, row.label))
            fragments.append(("", "\n"))
            if row.current:
                fragments.append(("", "    "))
                fragments.append((row.current_style, row.current))
                fragments.append(("", "\n"))
            if row.description:
                fragments.append(("", "    "))
                fragments.append((row.description_style, row.description))
                fragments.append(("", "\n"))
        fragments.append(("fg:#64748B", f"\n{_msg(lang, 'footer_live')}"))
        return fragments

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result=_current_value())

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

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


def _provider_profile_options(provider: str, provider_config, *, lang: str) -> list[ChoiceOption]:
    models = provider_config.models or {}
    if provider == "codex":
        thinking_levels = models.get("thinking_levels", {}) if isinstance(models.get("thinking_levels", {}), dict) else {}
        order = _provider_profile_keys(provider, provider_config)
        options: list[ChoiceOption] = []
        for index, key in enumerate(order, start=1):
            model_id = _provider_model_id(provider, provider_config, key)
            description = _localized_profile_description(lang, provider, key, str((thinking_levels.get(key) or {}).get("description", "")).strip())
            options.append(ChoiceOption(str(index), _profile_label(lang, key), f"{model_id} · {description}", provider=provider))
        return options

    raw_enabled = models.get("enabled_profiles", [])
    enabled_profiles = [str(item) for item in raw_enabled] if isinstance(raw_enabled, list) else []
    if provider == "claude":
        order = [key for key in ("default", "powerful", "cost_effective") if key in enabled_profiles or key == "default"]
    elif provider == "gemini":
        order = [key for key in ("powerful", "cost_effective", "auto") if key in enabled_profiles or key == "auto"]
    else:
        order = enabled_profiles or ["default"]

    options = []
    for index, key in enumerate(order, start=1):
        model_name = _provider_model_id(provider, provider_config, key)
        fallback = ""
        cfg = models.get(key, {}) if isinstance(models.get(key, {}), dict) else {}
        if cfg.get("description"):
            fallback = str(cfg.get("description")).strip()
        description = _localized_profile_description(lang, provider, key, fallback)
        options.append(ChoiceOption(str(index), _profile_label(lang, key), f"{model_name} · {description}".strip(" ·"), provider=provider))
    return options


def _app_section_screen(state: ConfigMenuState) -> ChoiceScreen:
    lang = _lang(state.form.ui_language)
    return ChoiceScreen(
        title=_msg(lang, "screen_interface_title"),
        hint=_msg(lang, "screen_interface_hint"),
        note=_msg(lang, "screen_interface_note"),
        options=[
            ChoiceOption("1", _with_current(_msg(lang, "item_language"), LANGUAGE_LABELS.get(state.form.ui_language, state.form.ui_language)), _msg(lang, "item_language_desc")),
            ChoiceOption("2", _with_current(_msg(lang, "item_updates"), f"v{AI_COLLAB_VERSION}"), _msg(lang, "item_updates_desc")),
            ChoiceOption("3", _with_current(_msg(lang, "item_update_auto"), _update_auto_label(lang, state.application_auto_check_updates)), _msg(lang, "item_update_auto_desc")),
            ChoiceOption("4", _with_current(_msg(lang, "item_about"), f"v{AI_COLLAB_VERSION}"), _msg(lang, "item_about_desc")),
        ],
        default_value="1",
    )


def _render_info_page(*, title: str, hint: str, lang: str, sections: list[tuple[str, str]], footer: str) -> str:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    console.print(Text("AI COLLAB", style="bold #7DD3FC"))
    for line in ABOUT_ASCII:
        console.print(Text(line, style="bold #7DD3FC"))
    console.print()
    console.print(Text(title, style="bold"))
    console.print(Text(hint, style="dim"))
    console.print()
    for section_title, section_body in sections:
        console.print(Text(section_title, style="bold"))
        console.print(Text(section_body, style="dim"))
        console.print()
    console.print(Text(footer, style="dim"))
    return buffer.getvalue().rstrip() + "\n"


def _render_update_status_page(state: ConfigMenuState) -> str:
    lang = _lang(state.form.ui_language)
    auto_label = _update_auto_label(lang, state.application_auto_check_updates)
    sections = [
        ("Version" if lang == "en-US" else "当前版本", f"v{AI_COLLAB_VERSION}"),
        ("Update behavior" if lang == "en-US" else "更新方式", auto_label),
        (
            "Status" if lang == "en-US" else "当前状态",
            "Remote release lookup is not wired into this menu yet; use this page as a local status panel for now."
            if lang == "en-US"
            else "这个菜单暂未接入远程版本源；目前先作为本地版本与更新偏好的状态页。",
        ),
    ]
    return _render_info_page(
        title=_msg(lang, "screen_updates_title"),
        hint=_msg(lang, "screen_updates_hint"),
        lang=lang,
        sections=sections,
        footer="Press b to go back · q to quit without saving" if lang == "en-US" else "按 b 返回 · q 退出且不保存",
    )


def _render_about_page(state: ConfigMenuState) -> str:
    lang = _lang(state.form.ui_language)
    sections = [
        (
            "What it is" if lang == "en-US" else "它是什么",
            "A terminal-first multi-agent coding orchestrator that coordinates Codex, Claude Code, Gemini CLI, and future agent CLIs."
            if lang == "en-US"
            else "一个终端优先的多 Agent 编码编排器，用来协调 Codex、Claude Code、Gemini CLI 以及未来更多 Agent CLI。",
        ),
        (
            "What it owns" if lang == "en-US" else "它负责什么",
            "Defaults, routing, runtime choice, session control surfaces, and eventually a standalone Session Console and GUI shell."
            if lang == "en-US"
            else "负责默认配置、协作路由、运行方式、会话控制入口，以及未来独立的 Session Console 与 GUI 外壳。",
        ),
        (
            "Current version" if lang == "en-US" else "当前版本",
            f"v{AI_COLLAB_VERSION}",
        ),
    ]
    return _render_info_page(
        title=_msg(lang, "screen_about_title"),
        hint=_msg(lang, "screen_about_hint"),
        lang=lang,
        sections=sections,
        footer="Press b to go back · q to quit without saving" if lang == "en-US" else "按 b 返回 · q 退出且不保存",
    )


def _show_info_page(page_text: str, *, input_fn: InputFn, console_obj: Console, clear_screen: bool) -> str | None:
    if clear_screen:
        console_obj.clear()
    console_obj.print(page_text, end="")
    return input_fn("Select", choices=["b", "q"], default="b")


def _show_update_status_screen(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    return _show_info_page(_render_update_status_page(state), input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)


def _show_about_screen(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    return _show_info_page(_render_about_page(state), input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)


def _run_app_section(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    while True:
        lang = _lang(state.form.ui_language)
        choice = _ask_screen_choice(_app_section_screen(state), lang=lang, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen, allow_back=True)
        if choice in {"b", "q"}:
            return choice
        if choice == "1":
            result = _edit_basic_step(state, step_id="language", input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "2":
            result = _show_update_status_screen(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        elif choice == "3":
            result = _edit_update_auto(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        else:
            result = _show_about_screen(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"


from ai_collab.core.updates import check_pypi_update


def _update_status_message(lang: str, status: str) -> str:
    messages = {
        "en-US": {
            "ahead": "Local development version is ahead of PyPI.",
            "equal": "Local version matches the latest PyPI release.",
            "behind": "A newer version is available on PyPI.",
            "unpublished": "This package is not published on PyPI yet.",
            "unavailable": "Unable to compare with PyPI right now.",
        },
        "zh-CN": {
            "ahead": "本地开发版本领先于 PyPI。",
            "equal": "本地版本与 PyPI 最新版本一致。",
            "behind": "PyPI 上有更新版本可用。",
            "unpublished": "这个包目前还没有发布到 PyPI。",
            "unavailable": "暂时无法与 PyPI 进行比较。",
        },
    }
    return messages[_lang(lang)].get(status, status)


def render_config_menu_screen(config_or_state: Config | ConfigMenuState) -> str:
    state = config_or_state if isinstance(config_or_state, ConfigMenuState) else ConfigMenuState.from_config(config_or_state)
    lang = _lang(state.form.ui_language)
    items = _build_menu_items(state)
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=140)
    for line in build_init_banner(100):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        console.print(Text(line, style=style))
    console.print()
    console.print(Text(_msg(lang, "menu_title"), style="bold"))
    console.print(Text(_msg(lang, "menu_hint"), style="dim"))
    console.print(Text(_msg(lang, "menu_note"), style="dim italic"))
    console.print()
    for index, item in enumerate(items):
        prefix = "›" if index == 0 else " "
        console.print(f"{prefix} {item.value}. {item.label}")
        console.print(Text(f"    {item.description}", style="dim italic"))
    console.print(f"  q. {_msg(lang, 'quit')}")
    console.print()
    console.print(Text(_msg(lang, "footer"), style="dim"))
    return buffer.getvalue().rstrip() + "\n"


def _select_menu_with_prompt_toolkit(
    state: ConfigMenuState,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    items = _render_menu_header(state, console_obj=console_obj, clear_screen=clear_screen)
    lang = _lang(state.form.ui_language)
    values = [item.value for item in items] + ["q"]
    pointed_index = 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens() -> list[tuple[str, str]]:
        rows = _build_menu_rows(items, pointed_value=_current_value(), lang=lang)
        fragments: list[tuple[str, str]] = []
        for row in rows:
            fragments.append(("", row.prefix))
            fragments.append((row.label_style, row.label))
            fragments.append(("", "\n"))
            if row.description:
                fragments.append(("", "    "))
                fragments.append((row.description_style, row.description))
                fragments.append(("", "\n"))
        fragments.append(("fg:#64748B", f"\n{_msg(lang, 'footer_live')}"))
        return fragments

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result=_current_value())

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

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


def _render_update_status_page(state: ConfigMenuState) -> str:
    lang = _lang(state.form.ui_language)
    auto_label = _update_auto_label(lang, state.application_auto_check_updates)
    result = check_pypi_update(local_version=AI_COLLAB_VERSION)
    remote_version = result.remote_version or ("Not published" if lang == "en-US" else "未发布")
    sections = [
        ("Local version" if lang == "en-US" else "本地版本", result.local_version),
        ("PyPI version" if lang == "en-US" else "PyPI 版本", remote_version),
        ("Update behavior" if lang == "en-US" else "更新方式", auto_label),
        ("Status" if lang == "en-US" else "当前状态", _update_status_message(lang, result.status)),
    ]
    if result.detail:
        sections.append(("Detail" if lang == "en-US" else "说明", result.detail))
    return _render_info_page(
        title=_msg(lang, "screen_updates_title"),
        hint=_msg(lang, "screen_updates_hint"),
        lang=lang,
        sections=sections,
        footer="Press b to go back · q to quit without saving" if lang == "en-US" else "按 b 返回 · q 退出且不保存",
    )

from rich import box as _brand_box
from rich.console import Group as _BrandGroup
from rich.panel import Panel as _BrandPanel
from rich.table import Table as _BrandTable


_BRAND_ASCII_ART = (
    "   █████╗ ██╗        ██████╗ ██████╗ ██╗      █████╗ ██████╗",
    "  ██╔══██╗██║       ██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗",
    "  ███████║██║       ██║     ██║   ██║██║     ███████║██████╔╝",
    "  ██╔══██║██║       ██║     ██║   ██║██║     ██╔══██║██╔══██╗",
    "  ██║  ██║██║██████╗╚██████╗╚██████╔╝███████╗██║  ██║██████╔╝",
    "  ╚═╝  ╚═╝╚═╝╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝",
)


def _brand_footer(lang: str) -> Text:
    return Text(
        "Press b to go back · q to quit without saving"
        if lang == "en-US"
        else "按 b 返回 · q 退出且不保存",
        style="dim",
    )


def _brand_tagline(lang: str) -> str:
    return (
        "Terminal-first multi-agent coding orchestration"
        if lang == "en-US"
        else "终端优先 · 多 Agent 编码编排"
    )


def _brand_page_intro(lang: str, page: str) -> str:
    messages = {
        "about": {
            "en-US": "Positioning, scope, and the terminal product direction.",
            "zh-CN": "版本、定位与终端编排产品方向。",
        },
        "updates": {
            "en-US": "Compare local and PyPI versions, then choose the safest next step.",
            "zh-CN": "对比本地与 PyPI 版本，并给出当前最合适的下一步。",
        },
    }
    return messages[page][_lang(lang)]


def _render_brand_hero(*, lang: str, title: str, subtitle: str, facts: list[tuple[str, str]]) -> _BrandPanel:
    fact_table = _BrandTable.grid(padding=(0, 1))
    fact_table.add_column(style="#94A3B8", justify="right")
    fact_table.add_column(style="bold #E2E8F0")
    for label, value in facts:
        fact_table.add_row(label, value)

    layout = _BrandTable.grid(expand=True)
    layout.add_column(ratio=5)
    layout.add_column(ratio=2, min_width=26)
    layout.add_row(
        _BrandGroup(
            Text("AI COLLAB", style="bold #F8FAFC"),
            Text("\n".join(_BRAND_ASCII_ART), style="bold #60A5FA"),
            Text(_brand_tagline(lang), style="bold #E2E8F0"),
            Text(subtitle, style="dim italic"),
        ),
        fact_table,
    )
    return _BrandPanel(
        layout,
        title=title,
        border_style="#38BDF8",
        box=_brand_box.HEAVY,
        padding=(1, 2),
    )


def _render_bullet_panel(*, title: str, lines: list[str], border_style: str = "#475569") -> _BrandPanel:
    content = _BrandGroup(*[Text(f"• {line}", style="#E2E8F0") for line in lines])
    return _BrandPanel(content, title=title, border_style=border_style, box=_brand_box.ROUNDED, padding=(1, 2))


def _render_kv_panel(*, title: str, rows: list[tuple[str, str]], border_style: str = "#475569") -> _BrandPanel:
    table = _BrandTable.grid(expand=True, padding=(0, 1))
    table.add_column(style="#94A3B8", width=12)
    table.add_column(style="bold #E2E8F0")
    for label, value in rows:
        table.add_row(label, value)
    return _BrandPanel(table, title=title, border_style=border_style, box=_brand_box.ROUNDED, padding=(1, 2))


def _update_next_steps(lang: str, *, status: str, auto_label: str, detail: str | None) -> list[str]:
    key = _lang(lang)
    steps = {
        "ahead": {
            "en-US": [
                "Keep the current local development build; startup update prompts stay suppressed while it is ahead of PyPI.",
                f"Current strategy: {auto_label}.",
            ],
            "zh-CN": [
                "继续使用当前本地开发版本；当本地版本领先于 PyPI 时，启动时不会提示覆盖更新。",
                f"当前策略：{auto_label}。",
            ],
        },
        "equal": {
            "en-US": [
                "No action needed right now; local install already matches the latest PyPI release.",
                f"Current strategy: {auto_label}.",
            ],
            "zh-CN": [
                "当前无需操作；本地安装已与 PyPI 最新发布一致。",
                f"当前策略：{auto_label}。",
            ],
        },
        "behind": {
            "en-US": [
                "Allow the startup prompt to upgrade first, or update manually before the next run.",
                "Manual command: python -m pip install --upgrade ai-collab",
            ],
            "zh-CN": [
                "可以在下次启动时先更新，或在继续使用前手动升级。",
                "手动更新命令：python -m pip install --upgrade ai-collab",
            ],
        },
        "unpublished": {
            "en-US": [
                "PyPI has no published release for this package name yet.",
                f"Current strategy: {auto_label}.",
            ],
            "zh-CN": [
                "PyPI 目前还没有这个包的已发布版本。",
                f"当前策略：{auto_label}。",
            ],
        },
        "unavailable": {
            "en-US": [
                "Keep the local build for now and retry later when network access is available.",
                f"Current strategy: {auto_label}.",
            ],
            "zh-CN": [
                "暂时保留当前本地版本，等网络可用时再重新检查。",
                f"当前策略：{auto_label}。",
            ],
        },
    }.get(status, {
        "en-US": [f"Current strategy: {auto_label}."],
        "zh-CN": [f"当前策略：{auto_label}。"],
    })[key]
    if detail:
        prefix = "Detail" if key == "en-US" else "补充说明"
        steps.append(f"{prefix}：{detail}")
    return steps


def _render_about_page(state: ConfigMenuState):
    lang = _lang(state.form.ui_language)
    title = "ABOUT AI COLLAB" if lang == "en-US" else "关于 AI COLLAB"
    version_label = "Version" if lang == "en-US" else "版本"
    mode_label = "Form" if lang == "en-US" else "形态"
    status_label = "Status" if lang == "en-US" else "状态"
    hero = _render_brand_hero(
        lang=lang,
        title=title,
        subtitle=_brand_page_intro(lang, "about"),
        facts=[
            (version_label, f"v{AI_COLLAB_VERSION}"),
            (mode_label, "Terminal-first" if lang == "en-US" else "终端优先"),
            (status_label, "Active redesign" if lang == "en-US" else "重构进行中"),
        ],
    )
    sections = [
        _render_bullet_panel(
            title="Product positioning" if lang == "en-US" else "产品定位",
            lines=[
                "A multi-agent coding orchestrator instead of another single-agent shell."
                if lang == "en-US"
                else "它不是另一个单 Agent 壳，而是负责把多个 Coding Agent 编排起来。",
                "Coordinates Codex, Claude Code, Gemini CLI, and future agent CLIs."
                if lang == "en-US"
                else "当前协调 Codex、Claude Code、Gemini CLI，以及未来更多 Agent CLI。",
                "Owns defaults, routing, runtime selection, and session control entry points."
                if lang == "en-US"
                else "负责默认配置、协作路由、运行方式与会话控制入口。",
            ],
            border_style="#4F46E5",
        ),
        _render_bullet_panel(
            title="Current focus" if lang == "en-US" else "当前聚焦",
            lines=[
                "Keep init and config thin, direct, and safe to adjust before collaboration begins."
                if lang == "en-US"
                else "把 init 与 config 做成薄 CLI，先解决默认项与启动体验。",
                "Continue maintaining the tmux runtime while reducing setup and controller friction."
                if lang == "en-US"
                else "继续维护 tmux 运行方案，同时减少初始化与主控切换阻力。",
                "Treat Session Console as the future terminal template for the standalone GUI shell."
                if lang == "en-US"
                else "把 Session Console 作为未来独立 GUI 外壳的终端模板。",
            ],
            border_style="#0EA5E9",
        ),
        _render_bullet_panel(
            title="Interface direction" if lang == "en-US" else "界面路线",
            lines=[
                "Default ai-collab entry should move toward a session console rather than a heavy setup wizard."
                if lang == "en-US"
                else "默认入口逐步转向 Session Console，而不是厚重的设置向导。",
                "Init and config remain lightweight surfaces for defaults, trust checks, and preference edits."
                if lang == "en-US"
                else "init 与 config 保持轻量，只负责默认值、信任确认与偏好修改。",
                "GUI will reuse the same orchestration and configuration layers instead of redefining them."
                if lang == "en-US"
                else "未来 GUI 复用同一套编排层与配置层，而不是再造一套逻辑。",
            ],
            border_style="#14B8A6",
        ),
    ]
    return _BrandGroup(hero, *sections, _brand_footer(lang))


def _render_update_status_page(state: ConfigMenuState):
    lang = _lang(state.form.ui_language)
    auto_label = _update_auto_label(lang, state.application_auto_check_updates)
    result = check_pypi_update(local_version=AI_COLLAB_VERSION)
    remote_version = result.remote_version or ("Not published" if lang == "en-US" else "未发布")
    title = "CHECK UPDATES" if lang == "en-US" else "检查更新"
    hero = _render_brand_hero(
        lang=lang,
        title=title,
        subtitle=_brand_page_intro(lang, "updates"),
        facts=[
            (("Local" if lang == "en-US" else "本地"), result.local_version),
            ("PyPI", remote_version),
            (("Policy" if lang == "en-US" else "策略"), auto_label),
        ],
    )
    sections = [
        _render_kv_panel(
            title="Version comparison" if lang == "en-US" else "版本对比",
            rows=[
                (("Local version" if lang == "en-US" else "本地版本"), result.local_version),
                (("PyPI version" if lang == "en-US" else "PyPI 版本"), remote_version),
                (("Status" if lang == "en-US" else "当前状态"), _update_status_message(lang, result.status)),
            ],
            border_style="#4F46E5",
        ),
        _render_kv_panel(
            title="Update policy" if lang == "en-US" else "更新策略",
            rows=[
                (("Auto check" if lang == "en-US" else "自动检查"), auto_label),
                (
                    ("Startup behavior" if lang == "en-US" else "启动行为"),
                    "Prompt before upgrading; never overwrite silently."
                    if lang == "en-US"
                    else "发现新版时先询问；不会静默自动覆盖。",
                ),
                (
                    ("Dev build handling" if lang == "en-US" else "开发版本处理"),
                    "When local version is ahead of PyPI, skip replacement prompts."
                    if lang == "en-US"
                    else "当本地开发版本领先于 PyPI 时，不提示覆盖更新。",
                ),
            ],
            border_style="#0EA5E9",
        ),
        _render_bullet_panel(
            title="Next steps" if lang == "en-US" else "下一步",
            lines=_update_next_steps(lang, status=result.status, auto_label=auto_label, detail=result.detail),
            border_style="#14B8A6",
        ),
    ]
    return _BrandGroup(hero, *sections, _brand_footer(lang))


def _show_info_page(page_text, *, input_fn: InputFn, console_obj: Console, clear_screen: bool) -> str | None:
    if clear_screen:
        console_obj.clear()
    console_obj.print(page_text)
    return input_fn("Select", choices=["b", "q"], default="b")

from ai_collab.core.updates import run_self_update


AI_COLLAB_DEVELOPER = "Skyhua"
AI_COLLAB_GITHUB_URL = "https://github.com/skyhua0224/ai-collab"


@dataclass(frozen=True)
class _CompactPageAction:
    value: str
    label: str


def _render_compact_button_bar(*, actions: list[_CompactPageAction], selected_value: str) -> Text:
    text = Text()
    for index, action in enumerate(actions):
        if index:
            text.append("   ")
        style = "bold #0F172A on #7DD3FC" if action.value == selected_value else "bold #94A3B8"
        text.append(f"[ {action.label} ]", style=style)
    return text


def _renderable_to_ansi(renderable, *, width: int) -> str:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="truecolor", width=width)
    console.print(renderable)
    return buffer.getvalue()


def _compact_page_hint(lang: str, *, shortcuts: str) -> Text:
    prefix = "←/→ 切换 · Enter 确认" if lang == "zh-CN" else "←/→ move · Enter confirm"
    suffix = f" · {shortcuts} · q 退出" if lang == "zh-CN" else f" · {shortcuts} · q quit"
    return Text(prefix + suffix, style="dim")


def _render_compact_page(*, title: str, icon: str, intro: str, rows: list[tuple[str, str]], actions: list[_CompactPageAction], selected_value: str, hint: Text) -> object:
    table = _BrandTable.grid(expand=True, padding=(0, 1))
    table.add_column(style="#94A3B8", width=10)
    table.add_column(style="bold #E2E8F0")
    for label, value in rows:
        table.add_row(label, value)

    content = _BrandGroup(
        Text(f"{icon}  AI COLLAB", style="bold #F8FAFC"),
        Text(intro, style="dim italic"),
        Text(""),
        table,
        Text(""),
        _render_compact_button_bar(actions=actions, selected_value=selected_value),
        hint,
    )
    return _BrandPanel(content, title=title, border_style="#38BDF8", box=_brand_box.HEAVY, padding=(1, 2))


def _select_compact_page_action(
    render_page,
    *,
    actions: list[_CompactPageAction],
    default_value: str,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    values = [action.value for action in actions]
    pointed_index = values.index(default_value) if default_value in values else 0
    width = max(72, min(int(console_obj.width), 140)) if console_obj.width else 120

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens():
        ansi = _renderable_to_ansi(render_page(_current_value()), width=width)
        return list(to_formatted_text(ANSI(ansi)))

    bindings = KeyBindings()

    @bindings.add(Keys.Left, eager=True)
    def _left(event) -> None:
        _move(-1)

    @bindings.add(Keys.Right, eager=True)
    @bindings.add(Keys.Tab, eager=True)
    def _right(event) -> None:
        _move(1)

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

    for action in actions:
        if len(action.value) == 1 and action.value.isprintable():
            @bindings.add(action.value, eager=True)
            def _pick(event, value=action.value) -> None:
                event.app.exit(result=value)

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


def _about_page_actions(lang: str) -> list[_CompactPageAction]:
    return [
        _CompactPageAction("b", "Back" if lang == "en-US" else "返回"),
        _CompactPageAction("u", "Check updates" if lang == "en-US" else "检查更新"),
    ]


def _update_page_actions(lang: str, *, auto_check: bool) -> list[_CompactPageAction]:
    toggle_label = (
        f"Auto-check: {'On' if auto_check else 'Off'}"
        if lang == "en-US"
        else f"自动检查：{'开' if auto_check else '关'}"
    )
    return [
        _CompactPageAction("b", "Back" if lang == "en-US" else "返回"),
        _CompactPageAction("t", toggle_label),
        _CompactPageAction("i", "Update now" if lang == "en-US" else "立即更新"),
    ]


def _agent_preferences_page_actions(lang: str) -> list[_CompactPageAction]:
    return [_CompactPageAction("b", "Back" if lang == "en-US" else "返回")]


def _render_agent_preferences_page(state: ConfigMenuState, *, selected_value: str = "b"):
    lang = _lang(state.form.ui_language)
    title = _msg(lang, "screen_agent_preferences_title")
    intro = (
        "These are the default responsibility tendencies. The controller can still reroute per task, cost, evidence, and availability."
        if lang == "en-US"
        else "这里展示的是默认职责倾向，不是硬编码分工。主控仍会根据任务、成本、现状证据与可用性动态调整。"
    )
    rows = [
        (
            "Codex",
            "Terminal execution, code changes, tests, and evidence collection."
            if lang == "en-US"
            else "终端执行、改代码、跑测试、采集现状。",
        ),
        (
            "Claude",
            "Acceptance checks, extra tests, code review, and risk explanation."
            if lang == "en-US"
            else "验收、补测试、代码审查、风险说明。",
        ),
        (
            "Gemini",
            "Options comparison, front-end mockups, technical direction, and synthesis."
            if lang == "en-US"
            else "方案比较、前端初稿 / mockup、选型与综合分析。",
        ),
    ]
    return _render_compact_page(
        title=title,
        icon="⇄",
        intro=intro,
        rows=rows,
        actions=_agent_preferences_page_actions(lang),
        selected_value=selected_value,
        hint=_compact_page_hint(lang, shortcuts=("b 返回" if lang == "zh-CN" else "b back")),
    )


def _render_about_page(state: ConfigMenuState, *, selected_value: str = "b"):
    lang = _lang(state.form.ui_language)
    title = "About ai-collab" if lang == "en-US" else "关于 ai-collab"
    intro = (
        "A terminal-first multi-agent coding orchestrator for Codex, Claude Code, Gemini CLI, and future agent CLIs."
        if lang == "en-US"
        else "一个终端优先的多 Agent 编码编排器，用来协调 Codex、Claude Code、Gemini CLI 与未来更多 Agent CLI。"
    )
    rows = [
        (("Version" if lang == "en-US" else "版本"), f"v{AI_COLLAB_VERSION}"),
        (("Developer" if lang == "en-US" else "开发者"), AI_COLLAB_DEVELOPER),
        ("GitHub", AI_COLLAB_GITHUB_URL),
    ]
    return _render_compact_page(
        title=title,
        icon="◎",
        intro=intro,
        rows=rows,
        actions=_about_page_actions(lang),
        selected_value=selected_value,
        hint=_compact_page_hint(lang, shortcuts=("b 返回 · u 检查更新" if lang == "zh-CN" else "b back · u updates")),
    )


def _render_update_status_page(state: ConfigMenuState, *, selected_value: str = "b"):
    lang = _lang(state.form.ui_language)
    result = check_pypi_update(local_version=AI_COLLAB_VERSION)
    remote_version = result.remote_version or ("Not published" if lang == "en-US" else "未发布")
    intro = _update_status_message(lang, result.status)
    rows = [
        (("Local version" if lang == "en-US" else "本地版本"), result.local_version),
        (("PyPI version" if lang == "en-US" else "PyPI 版本"), remote_version),
        (("Auto check" if lang == "en-US" else "自动检查"), _update_auto_label(lang, state.application_auto_check_updates)),
    ]
    detail = str(result.detail or "").strip()
    if detail:
        rows.append((("Detail" if lang == "en-US" else "说明"), detail))
    return _render_compact_page(
        title=("Check updates" if lang == "en-US" else "检查更新"),
        icon="⬆",
        intro=intro,
        rows=rows,
        actions=_update_page_actions(lang, auto_check=state.application_auto_check_updates),
        selected_value=selected_value,
        hint=_compact_page_hint(lang, shortcuts=("b 返回 · t 切换 · i 更新" if lang == "zh-CN" else "b back · t toggle · i update")),
    )


def _show_update_status_screen(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    while True:
        actions = _update_page_actions(lang, auto_check=state.application_auto_check_updates)
        if input_fn is _prompt_input and sys.stdin.isatty():
            try:
                choice = _select_compact_page_action(
                    lambda selected: _render_update_status_page(state, selected_value=selected),
                    actions=actions,
                    default_value="b",
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
            except Exception:
                choice = "b"
        else:
            if clear_screen:
                console_obj.clear()
            console_obj.print(_render_update_status_page(state, selected_value="b"))
            choice = input_fn("Select", choices=[action.value for action in actions] + ["q"], default="b")

        if choice == "q":
            return "q"
        if choice == "b":
            return "b"
        if choice == "t":
            state.application_auto_check_updates = not state.application_auto_check_updates
            continue
        console_obj.print("[cyan]Updating ai-collab via pip...[/cyan]" if lang == "en-US" else "[cyan]正在通过 pip 更新 ai-collab...[/cyan]")
        updated = run_self_update()
        if updated:
            console_obj.print("[green]Update completed. Please rerun ai-collab.[/green]" if lang == "en-US" else "[green]更新完成，请重新运行 ai-collab。[/green]")
            return "q"
        console_obj.print("[yellow]Update failed, keeping current version.[/yellow]" if lang == "en-US" else "[yellow]更新失败，继续保留当前版本。[/yellow]")


def _show_agent_preferences_screen(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    actions = _agent_preferences_page_actions(lang)
    if input_fn is _prompt_input and sys.stdin.isatty():
        try:
            return _select_compact_page_action(
                lambda selected: _render_agent_preferences_page(state, selected_value=selected),
                actions=actions,
                default_value="b",
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
        except Exception:
            return "b"

    if clear_screen:
        console_obj.clear()
    console_obj.print(_render_agent_preferences_page(state, selected_value="b"))
    return input_fn("Select", choices=[action.value for action in actions] + ["q"], default="b")


def _show_about_screen(
    state: ConfigMenuState,
    *,
    input_fn: InputFn,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    lang = _lang(state.form.ui_language)
    while True:
        actions = _about_page_actions(lang)
        if input_fn is _prompt_input and sys.stdin.isatty():
            try:
                choice = _select_compact_page_action(
                    lambda selected: _render_about_page(state, selected_value=selected),
                    actions=actions,
                    default_value="b",
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
            except Exception:
                choice = "b"
        else:
            if clear_screen:
                console_obj.clear()
            console_obj.print(_render_about_page(state, selected_value="b"))
            choice = input_fn("Select", choices=[action.value for action in actions] + ["q"], default="b")

        if choice == "q":
            return "q"
        if choice == "b":
            return "b"
        result = _show_update_status_screen(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
        if result == "q":
            return "q"
