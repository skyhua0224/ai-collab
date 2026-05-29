"""
Configuration management for AI Collaboration System.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field

from ai_collab.core.workflow_v2 import resolve_session_preset


class ProviderConfig(BaseModel):
    """Provider configuration."""

    cli: str
    enabled: bool = True
    timeout: int = 120
    strengths: list[str] = Field(default_factory=list)
    models: Dict[str, Any] = Field(default_factory=dict)
    model_selection: str = "default"


class QualityGateConfig(BaseModel):
    """Quality gate configuration."""

    enabled: bool = True
    threshold: int = 75


ALL_PROVIDER_KEYS = ("codex", "claude", "gemini")
DEFAULT_COLLABORATION_PRESET = "auto-route"
DEFAULT_SESSION_PRESET = "auto"
DEFAULT_WORKFLOW_ENGINE = "v2"
DEFAULT_COST_BIAS = "balanced"
DEFAULT_PRICING_MODE = "disabled"
DEFAULT_BILLING_MODE = "unconfigured"
DEFAULT_QUOTA_WINDOW = "none"
DEFAULT_RELATIVE_COST_TIER = "standard"
DEFAULT_QUOTA_STRATEGY = "balanced"
DEFAULT_CROSS_PROVIDER_FALLBACK = "same-provider-first"
TRIGGER_DEFAULT_SESSION_PRESET_MAP = {
    "visual-design": "design-first",
    "architecture": "research-priority",
    "implementation": "auto",
    "fullstack-superapp": "design-first",
    "macos-native": "auto",
    "mobile-native": "auto",
    "systems-tooling": "auto",
    "game-dev": "design-first",
    "debugging": "debug-priority",
    "security-audit": "validation-first",
    "research": "research-priority",
    "testing": "validation-first",
    "docs-writing": "document-first",
}
RECOMMENDED_INTENT_PREFERENCES = {
    "implementation": ["codex", "claude", "gemini"],
    "codebase_understanding": ["claude", "codex", "gemini"],
    "research": ["gemini", "claude", "codex"],
    "architecture": ["gemini", "claude", "codex"],
    "testing": ["claude", "codex", "gemini"],
    "multimodal": ["gemini", "claude", "codex"],
}
COLLABORATION_PRESET_ROLE_LEADS = {
    "auto-route": {
        "research": "gemini",
        "architecture": "gemini",
        "implementation": "codex",
        "testing": "claude",
    },
    "coding-lead": {
        "research": "gemini",
        "architecture": "gemini",
        "implementation": "codex",
        "testing": "claude",
    },
    "architecture-lead": {
        "research": "gemini",
        "architecture": "claude",
        "implementation": "codex",
        "testing": "claude",
    },
    "debug-lead": {
        "research": "gemini",
        "architecture": "codex",
        "implementation": "codex",
        "testing": "claude",
    },
    "design-lead": {
        "research": "gemini",
        "architecture": "gemini",
        "implementation": "codex",
        "testing": "claude",
    },
    "research-lead": {
        "research": "gemini",
        "architecture": "gemini",
        "implementation": "codex",
        "testing": "claude",
    },
    "custom": {
        "research": "gemini",
        "architecture": "gemini",
        "implementation": "codex",
        "testing": "claude",
    },
}


def default_routing_config() -> Dict[str, Any]:
    return {
        "mode": "recommended",
        "cost_bias": DEFAULT_COST_BIAS,
        "intent_preferences": copy.deepcopy(RECOMMENDED_INTENT_PREFERENCES),
    }


def default_economics_config() -> Dict[str, Any]:
    return {
        "pricing_mode": DEFAULT_PRICING_MODE,
        "quota_strategy": DEFAULT_QUOTA_STRATEGY,
        "cross_provider_fallback": DEFAULT_CROSS_PROVIDER_FALLBACK,
        "providers": {
            provider: {
                "billing_mode": DEFAULT_BILLING_MODE,
                "quota_window": DEFAULT_QUOTA_WINDOW,
                "relative_cost_tier": DEFAULT_RELATIVE_COST_TIER,
            }
            for provider in ALL_PROVIDER_KEYS
        },
    }


def default_application_config() -> Dict[str, Any]:
    return {
        "auto_check_updates": True,
    }


def default_auto_collaboration_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "auto_orchestration_enabled": True,
        "preset": DEFAULT_COLLABORATION_PRESET,
        "default_session_preset": DEFAULT_SESSION_PRESET,
        "workflow_engine": DEFAULT_WORKFLOW_ENGINE,
        "persona_auto_assign": True,
        "persona_phase_map": {
            "discover": "research-analyst",
            "define": "requirements-architect",
            "develop": "implementation-engineer",
            "deliver": "quality-auditor",
        },
        "persona_skill_map": {
            "research-analyst": ["ecosystem-research", "alternatives-matrix"],
            "requirements-architect": ["scope-control", "tradeoff-analysis"],
            "implementation-engineer": ["feature-implementation", "integration-check"],
            "quality-auditor": ["code-review", "risk-review"],
            "security-auditor": ["security-review", "owasp-checklist"],
        },
        "phase_completion_criteria": {
            "default": {"min_output_chars": 30, "must_succeed": True},
            "discover": {"min_output_chars": 80},
            "define": {"min_output_chars": 60},
            "develop": {"min_output_chars": 80},
            "deliver": {"min_output_chars": 60},
        },
        "escalation_policy": {
            "max_retries": 1,
            "takeover_agent": "codex",
            "takeover_after_failures": 2,
            "ask_user_on_repeated_failure": True,
            "stop_on_failure": True,
        },
        "triggers": [],
    }


def normalize_intent_preferences(preferences: Dict[str, Any] | None) -> Dict[str, list[str]]:
    normalized: Dict[str, list[str]] = {}
    raw = preferences or {}
    for intent, recommended in RECOMMENDED_INTENT_PREFERENCES.items():
        items = raw.get(intent, []) if isinstance(raw, dict) else []
        ordered: list[str] = []
        if isinstance(items, list):
            for item in items:
                name = str(item).strip()
                if name in ALL_PROVIDER_KEYS and name not in ordered:
                    ordered.append(name)
        for name in recommended:
            if name not in ordered:
                ordered.append(name)
        normalized[intent] = ordered
    return normalized


def normalize_routing_config(routing: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(routing or {})
    cost_bias = str(raw.get("cost_bias", DEFAULT_COST_BIAS)).strip() or DEFAULT_COST_BIAS
    if cost_bias not in {"balanced", "quality-first", "cost-first"}:
        cost_bias = DEFAULT_COST_BIAS
    mode = str(raw.get("mode", "recommended")).strip() or "recommended"
    if mode not in {"recommended", "custom"}:
        mode = "recommended"
    return {
        "mode": mode,
        "cost_bias": cost_bias,
        "intent_preferences": normalize_intent_preferences(raw.get("intent_preferences")),
    }


def resolve_collaboration_role_leads(config: "Config | None") -> Dict[str, str]:
    auto_cfg = getattr(config, "auto_collaboration", {}) if config is not None else {}
    preset = str(auto_cfg.get("preset", DEFAULT_COLLABORATION_PRESET)).strip() or DEFAULT_COLLABORATION_PRESET
    resolved_preset = (
        preset if preset in COLLABORATION_PRESET_ROLE_LEADS else DEFAULT_COLLABORATION_PRESET
    )
    leads = dict(COLLABORATION_PRESET_ROLE_LEADS[resolved_preset])

    raw_routing = getattr(config, "routing", None) if config is not None else None
    routing = normalize_routing_config(raw_routing)
    intent_preferences = routing.get("intent_preferences", {})

    for intent in ("research", "architecture", "implementation", "testing"):
        ordered = intent_preferences.get(intent, [])
        if isinstance(ordered, list):
            for name in ordered:
                if name in ALL_PROVIDER_KEYS:
                    leads[intent] = name
                    break

    return leads


def normalize_economics_config(economics: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(economics or {})
    pricing_mode = str(raw.get("pricing_mode", DEFAULT_PRICING_MODE)).strip() or DEFAULT_PRICING_MODE
    if pricing_mode not in {"disabled", "official-reference", "custom-reference"}:
        pricing_mode = DEFAULT_PRICING_MODE

    quota_strategy = str(raw.get("quota_strategy", DEFAULT_QUOTA_STRATEGY)).strip() or DEFAULT_QUOTA_STRATEGY
    if quota_strategy not in {"balanced", "prefer-included-quota", "preserve-included-quota"}:
        quota_strategy = DEFAULT_QUOTA_STRATEGY

    cross_provider_fallback = str(raw.get("cross_provider_fallback", DEFAULT_CROSS_PROVIDER_FALLBACK)).strip() or DEFAULT_CROSS_PROVIDER_FALLBACK
    if cross_provider_fallback not in {"same-provider-first", "same-capability", "allow-any"}:
        cross_provider_fallback = DEFAULT_CROSS_PROVIDER_FALLBACK

    providers_raw = raw.get("providers", {}) if isinstance(raw.get("providers", {}), dict) else {}
    providers: Dict[str, Dict[str, str]] = {}
    for provider in ALL_PROVIDER_KEYS:
        provider_raw = providers_raw.get(provider, {}) if isinstance(providers_raw.get(provider, {}), dict) else {}
        billing_mode = str(provider_raw.get("billing_mode", DEFAULT_BILLING_MODE)).strip() or DEFAULT_BILLING_MODE
        if billing_mode not in {"unconfigured", "official-api", "subscription-quota", "custom-priced"}:
            billing_mode = DEFAULT_BILLING_MODE
        quota_window = str(provider_raw.get("quota_window", DEFAULT_QUOTA_WINDOW)).strip() or DEFAULT_QUOTA_WINDOW
        if quota_window not in {"none", "daily", "monthly"}:
            quota_window = DEFAULT_QUOTA_WINDOW
        relative_cost_tier = str(provider_raw.get("relative_cost_tier", DEFAULT_RELATIVE_COST_TIER)).strip() or DEFAULT_RELATIVE_COST_TIER
        if relative_cost_tier not in {"lower", "standard", "higher"}:
            relative_cost_tier = DEFAULT_RELATIVE_COST_TIER
        providers[provider] = {
            "billing_mode": billing_mode,
            "quota_window": quota_window,
            "relative_cost_tier": relative_cost_tier,
        }
    return {
        "pricing_mode": pricing_mode,
        "quota_strategy": quota_strategy,
        "cross_provider_fallback": cross_provider_fallback,
        "providers": providers,
    }


def normalize_application_config(application: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(application or {})
    return {
        "auto_check_updates": bool(raw.get("auto_check_updates", True)),
    }


class Config(BaseModel):
    """Main configuration."""

    version: str = "1.0"
    ui_language: str = "en-US"
    entry_surface: str = "guided"
    runtime_mode: str = "tmux"
    current_controller: str = "claude"
    providers: Dict[str, ProviderConfig]
    delegation_strategy: str = "auto"
    quality_gate: QualityGateConfig
    routing: Dict[str, Any] = Field(default_factory=default_routing_config)
    economics: Dict[str, Any] = Field(default_factory=default_economics_config)
    application: Dict[str, Any] = Field(default_factory=default_application_config)
    auto_collaboration: Dict[str, Any] = Field(default_factory=default_auto_collaboration_config)

    @property
    def quality_gate_enabled(self) -> bool:
        """Check if quality gate is enabled."""
        return self.quality_gate.enabled

    @classmethod
    def get_config_dir(cls) -> Path:
        """Get configuration directory."""
        return Path.home() / ".ai-collab"

    @classmethod
    def get_config_file(cls) -> Path:
        """Get configuration file path."""
        return cls.get_config_dir() / "config.json"

    @classmethod
    def _template_dir(cls) -> Path:
        return Path(__file__).parent.parent.parent / "config"

    @classmethod
    def _load_templates(cls) -> dict:
        template_dir = cls._template_dir()
        config_template = template_dir / "config.template.json"

        cfg = {}

        if config_template.exists():
            with open(config_template) as f:
                cfg = json.load(f)

        return cfg

    @classmethod
    def _merge_missing_dict(cls, target: dict, template: dict) -> bool:
        changed = False
        for key, value in template.items():
            if key not in target:
                target[key] = copy.deepcopy(value)
                changed = True
            elif isinstance(target[key], dict) and isinstance(value, dict):
                changed = cls._merge_missing_dict(target[key], value) or changed
        return changed

    @classmethod
    def _merge_missing_triggers(cls, target_auto: dict, template_auto: dict) -> bool:
        changed = False
        existing = target_auto.get("triggers", []) or []
        existing_by_name = {
            str(item.get("name")): item
            for item in existing
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        }
        for trigger in template_auto.get("triggers", []) or []:
            name = trigger.get("name")
            if not name:
                continue
            if name not in existing_by_name:
                existing.append(copy.deepcopy(trigger))
                changed = True
                continue
            current = existing_by_name[name]
            if isinstance(current, dict):
                changed = cls._merge_missing_dict(current, trigger) or changed
        for item in existing:
            if isinstance(item, dict):
                changed = cls._upgrade_trigger_v2_fields(item) or changed
        target_auto["triggers"] = existing
        return changed

    @classmethod
    def _upgrade_trigger_v2_fields(cls, trigger: dict) -> bool:
        changed = False
        name = str(trigger.get("name", "")).strip()
        workflow = str(trigger.get("workflow", "")).strip()
        legacy_workflow = str(trigger.get("legacy_workflow", "")).strip()

        session_preset = str(trigger.get("session_preset", "")).strip()
        if not session_preset:
            mapped = TRIGGER_DEFAULT_SESSION_PRESET_MAP.get(name, "")
            if mapped:
                trigger["session_preset"] = mapped
                session_preset = mapped
                changed = True

        workflow_blueprint = str(trigger.get("workflow_blueprint", "")).strip()
        if not workflow_blueprint:
            if session_preset:
                try:
                    workflow_blueprint = resolve_session_preset(session_preset).workflow_key
                except KeyError:
                    workflow_blueprint = ""
            if workflow_blueprint:
                trigger["workflow_blueprint"] = workflow_blueprint
                changed = True

        if workflow:
            trigger.pop("workflow", None)
            changed = True
        if legacy_workflow:
            trigger.pop("legacy_workflow", None)
            changed = True

        return changed

    @classmethod
    def _apply_template_defaults(cls, data: dict) -> tuple[dict, bool]:
        template_cfg = cls._load_templates()
        if not template_cfg:
            return data, False

        changed = False

        # Merge root defaults except sections handled below.
        for key, value in template_cfg.items():
            if key in {"providers", "quality_gate", "economics", "application", "auto_collaboration"}:
                continue
            if key not in data:
                data[key] = copy.deepcopy(value)
                changed = True

        # Merge provider defaults.
        providers = data.setdefault("providers", {})
        template_providers = template_cfg.get("providers", {})
        for provider_name, provider_template in template_providers.items():
            if provider_name not in providers:
                providers[provider_name] = copy.deepcopy(provider_template)
                changed = True
            elif isinstance(providers[provider_name], dict):
                changed = cls._merge_missing_dict(providers[provider_name], provider_template) or changed

        # Merge quality gate defaults.
        quality_gate = data.setdefault("quality_gate", {})
        changed = cls._merge_missing_dict(quality_gate, template_cfg.get("quality_gate", {})) or changed

        routing_cfg = normalize_routing_config(data.get("routing"))
        if data.get("routing") != routing_cfg:
            data["routing"] = routing_cfg
            changed = True

        economics_cfg = normalize_economics_config(data.get("economics"))
        if data.get("economics") != economics_cfg:
            data["economics"] = economics_cfg
            changed = True

        application_cfg = normalize_application_config(data.get("application"))
        if data.get("application") != application_cfg:
            data["application"] = application_cfg
            changed = True

        # Merge collaboration defaults and triggers.
        auto_cfg = data.setdefault("auto_collaboration", {})
        template_auto = template_cfg.get("auto_collaboration", {})

        # Keep canonical and legacy enable flags aligned.
        if "enabled" not in auto_cfg and "auto_orchestration_enabled" in auto_cfg:
            auto_cfg["enabled"] = bool(auto_cfg.get("auto_orchestration_enabled"))
            changed = True
        if "enabled" in auto_cfg and "auto_orchestration_enabled" not in auto_cfg:
            auto_cfg["auto_orchestration_enabled"] = bool(auto_cfg.get("enabled"))
            changed = True

        if "preset" not in auto_cfg:
            auto_cfg["preset"] = DEFAULT_COLLABORATION_PRESET
            changed = True
        if "default_session_preset" not in auto_cfg:
            auto_cfg["default_session_preset"] = DEFAULT_SESSION_PRESET
            changed = True
        if "workflow_engine" not in auto_cfg:
            auto_cfg["workflow_engine"] = DEFAULT_WORKFLOW_ENGINE
            changed = True

        # Merge non-trigger keys.
        for key, value in template_auto.items():
            if key == "triggers":
                continue
            if key not in auto_cfg:
                auto_cfg[key] = copy.deepcopy(value)
                changed = True
            elif isinstance(auto_cfg[key], dict) and isinstance(value, dict):
                changed = cls._merge_missing_dict(auto_cfg[key], value) or changed

        # Merge triggers by name.
        changed = cls._merge_missing_triggers(auto_cfg, template_auto) or changed
        for trigger in auto_cfg.get("triggers", []) or []:
            if isinstance(trigger, dict):
                changed = cls._upgrade_trigger_v2_fields(trigger) or changed

        if "workflows" in data:
            data.pop("workflows", None)
            changed = True

        # Migrate deprecated Codex model and reasoning defaults.
        codex_cfg = providers.get("codex", {})
        codex_models = codex_cfg.get("models", {}) if isinstance(codex_cfg, dict) else {}
        thinking_levels = codex_models.get("thinking_levels", {}) if isinstance(codex_models, dict) else {}
        for level_name in ("low", "medium", "high", "xhigh"):
            level_cfg = thinking_levels.get(level_name, {})
            flag = level_cfg.get("flag", "")
            if isinstance(flag, str) and "--thinking-budget" in flag:
                thinking_levels[level_name]["flag"] = flag.replace("--thinking-budget", "--thinking")
                changed = True

        codex_cli = codex_cfg.get("cli", "") if isinstance(codex_cfg, dict) else ""
        if isinstance(codex_cli, str) and "gpt-5.4" not in codex_cli and "gpt-5.3-codex" in codex_cli:
            codex_cfg["cli"] = codex_cli.replace("gpt-5.3-codex", "gpt-5.4")
            changed = True

        if isinstance(codex_models, dict):
            default_model = str(codex_models.get("default_model", "")).strip()
            if not default_model or default_model == "gpt-5.3-codex":
                codex_models["default_model"] = "gpt-5.4"
                changed = True

            enabled_profiles = codex_models.get("enabled_profiles", [])
            if isinstance(enabled_profiles, list) and "xhigh" not in enabled_profiles:
                enabled_profiles.append("xhigh")
                codex_models["enabled_profiles"] = enabled_profiles
                changed = True

        # Normalize outdated Gemini aliases.
        gemini_cfg = providers.get("gemini", {})
        gemini_models = gemini_cfg.get("models", {})
        if "auto_route_default" not in gemini_models:
            gemini_models["auto_route_default"] = True
            changed = True

        rename_map = {
            "3-flash-preview": "gemini-3-flash-preview",
            "3.1-pro-preview": "gemini-3.1-pro-preview",
        }
        for profile_name in ("cost_effective", "powerful"):
            profile = gemini_models.get(profile_name, {})
            model_name = profile.get("model", "")
            if isinstance(model_name, str) and model_name in rename_map:
                profile["model"] = rename_map[model_name]
                changed = True

            flag = profile.get("flag", "")
            if isinstance(flag, str):
                for old_name, new_name in rename_map.items():
                    token = f"--model {old_name}"
                    if token in flag:
                        profile["flag"] = flag.replace(token, f"--model {new_name}")
                        changed = True

        # Normalize Claude model IDs to canonical names.
        claude_cfg = providers.get("claude", {})
        claude_models = claude_cfg.get("models", {})
        claude_rename = {
            "sonnet-4.6": "claude-sonnet-4-6",
            "sonnet-4-6": "claude-sonnet-4-6",
            "haiku-4.5": "claude-haiku-4-5",
            "haiku-4-5": "claude-haiku-4-5",
            "opus-4.6": "claude-opus-4-6",
            "opus-4-6": "claude-opus-4-6",
        }

        default_model = claude_models.get("default", "")
        if isinstance(default_model, str) and default_model in claude_rename:
            claude_models["default"] = claude_rename[default_model]
            changed = True

        for profile_name in ("cost_effective", "powerful"):
            profile = claude_models.get(profile_name, {})
            model_name = profile.get("model", "")
            if isinstance(model_name, str) and model_name in claude_rename:
                profile["model"] = claude_rename[model_name]
                changed = True

            flag = profile.get("flag", "")
            if isinstance(flag, str):
                for old_name, new_name in claude_rename.items():
                    token = f"--model {old_name}"
                    if token in flag:
                        profile["flag"] = flag.replace(token, f"--model {new_name}")
                        changed = True

        # Prefer deterministic Gemini default profile.
        if isinstance(gemini_cfg, dict):
            gemini_selection = str(gemini_cfg.get("model_selection", "default")).strip()
            if gemini_selection == "default":
                gemini_cfg["model_selection"] = "powerful"
                changed = True
            if gemini_models.get("auto_route_default") is True and gemini_cfg.get("model_selection") in {"powerful", "cost_effective"}:
                gemini_models["auto_route_default"] = False
                changed = True

        return data, changed

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file."""
        config_file = cls.get_config_file()

        # First-time setup: initialize from templates.
        if not config_file.exists():
            return cls.initialize()

        with open(config_file) as f:
            data = json.load(f)

        # Merge template updates for existing users.
        data, changed = cls._apply_template_defaults(data)

        config = cls(**data)
        if changed:
            try:
                config.save()
            except PermissionError:
                pass

        return config

    @classmethod
    def create_default(cls) -> "Config":
        """Create built-in minimal defaults (fallback)."""
        return cls(
            version="1.0",
            ui_language="en-US",
            entry_surface="guided",
            runtime_mode="tmux",
            current_controller="claude",
            providers={
                "claude": ProviderConfig(
                    cli="claude",
                    enabled=True,
                    timeout=120,
                    strengths=["reasoning", "code-review", "architecture", "documentation", "security", "testing"],
                    models={
                        "default": "claude-sonnet-4-6",
                        "enabled_profiles": ["default", "cost_effective", "powerful"],
                        "cost_effective": {
                            "model": "claude-haiku-4-5",
                            "flag": "--model claude-haiku-4-5",
                            "description": "Fast triage and lightweight review",
                        },
                        "powerful": {
                            "model": "claude-opus-4-6",
                            "flag": "--model claude-opus-4-6",
                            "description": "Complex architecture and deep audits",
                        },
                    },
                    model_selection="default",
                ),
                "codex": ProviderConfig(
                    cli="codex exec --model gpt-5.4",
                    enabled=True,
                    timeout=300,
                    strengths=["implementation", "testing", "debugging", "integration", "backend"],
                    models={
                        "default_model": "gpt-5.4",
                        "default_thinking": "high",
                        "enabled_profiles": ["low", "medium", "high", "xhigh"],
                        "thinking_levels": {
                            "low": {
                                "model": "gpt-5.4",
                                "flag": "--thinking low",
                                "description": "Simple tasks (formatting, small edits)",
                            },
                            "medium": {
                                "model": "gpt-5.4",
                                "flag": "--thinking medium",
                                "description": "Feature implementation and refactoring",
                            },
                            "high": {
                                "model": "gpt-5.5",
                                "flag": "--thinking high",
                                "description": "Complex architecture and multi-module logic",
                            },
                            "xhigh": {
                                "model": "gpt-5.5",
                                "flag": "--thinking xhigh",
                                "description": "Deepest reasoning for hard planning, architecture, and cross-file refactors",
                            },
                        },
                    },
                    model_selection="default",
                ),
                "gemini": ProviderConfig(
                    cli="gemini -o text --approval-mode yolo",
                    enabled=True,
                    timeout=600,
                    strengths=["visual-design", "html-css", "research", "ecosystem", "frontend", "architecture"],
                    models={
                        "auto_route_default": False,
                        "enabled_profiles": ["auto", "cost_effective", "powerful"],
                        "cost_effective": {
                            "model": "gemini-3-flash-preview",
                            "flag": "--model gemini-3-flash-preview",
                            "description": "Fast classification and lightweight design",
                        },
                        "powerful": {
                            "model": "gemini-3.1-pro-preview",
                            "flag": "--model gemini-3.1-pro-preview",
                            "description": "High-quality visual design and synthesis",
                        },
                    },
                    model_selection="powerful",
                ),
            },
            delegation_strategy="auto",
            quality_gate=QualityGateConfig(enabled=True, threshold=75),
            routing=default_routing_config(),
            economics=default_economics_config(),
            application=default_application_config(),
            auto_collaboration=default_auto_collaboration_config(),
        )

    def save(self) -> None:
        """Save configuration to file."""
        config_dir = self.get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = self.get_config_file()
        data = self.model_dump()

        with open(config_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def initialize(cls) -> "Config":
        """Initialize configuration with defaults from templates."""
        config_dir = cls.get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        template_cfg = cls._load_templates()

        if template_cfg:
            data = copy.deepcopy(template_cfg)
            data, _ = cls._apply_template_defaults(data)
            config = cls(**data)
        else:
            config = cls.create_default()

        config.save()
        return config

    def interactive_config(self) -> None:
        """Interactive configuration."""
        from rich.console import Console
        from rich.prompt import Confirm, Prompt

        console = Console()

        console.print("\n[bold]🔧 AI Configuration[/bold]")
        console.print("=" * 60)

        # UI language
        console.print("\n[bold]1. UI Language:[/bold]")
        console.print(f"   Current: {self.ui_language}")
        lang = Prompt.ask(
            "   Change to",
            choices=["en-US", "zh-CN"],
            default=self.ui_language if self.ui_language in {"en-US", "zh-CN"} else "en-US",
        )
        self.ui_language = lang

        # Current controller
        console.print("\n[bold]2. Current Controller:[/bold]")
        console.print(f"   Current: {self.current_controller}")
        choice = Prompt.ask(
            "   Change to",
            choices=["claude", "codex", "gemini"],
            default=self.current_controller,
        )
        self.current_controller = choice

        # Delegation strategy
        console.print("\n[bold]3. Delegation Strategy:[/bold]")
        console.print(f"   Current: {self.delegation_strategy}")
        strategy = Prompt.ask(
            "   Choose",
            choices=["auto", "manual", "always-self"],
            default=self.delegation_strategy,
        )
        self.delegation_strategy = strategy

        # Quality gate
        console.print("\n[bold]4. Quality Gate:[/bold]")
        self.quality_gate.enabled = Confirm.ask(
            "   Enable quality gate?",
            default=self.quality_gate.enabled,
        )

        if self.quality_gate.enabled:
            threshold = Prompt.ask(
                "   Threshold (0-100)",
                default=str(self.quality_gate.threshold),
            )
            self.quality_gate.threshold = int(threshold)

        self.save()
