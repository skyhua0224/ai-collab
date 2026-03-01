"""
Configuration management for AI Collaboration System.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field


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


class Config(BaseModel):
    """Main configuration."""

    version: str = "1.0"
    ui_language: str = "en-US"
    current_controller: str = "claude"
    providers: Dict[str, ProviderConfig]
    delegation_strategy: str = "auto"
    quality_gate: QualityGateConfig
    workflows: Dict[str, Any] = Field(default_factory=dict)
    auto_collaboration: Dict[str, Any] = Field(default_factory=dict)

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
    def get_workflows_file(cls) -> Path:
        """Get workflows file path."""
        return cls.get_config_dir() / "workflows.json"

    @classmethod
    def _template_dir(cls) -> Path:
        return Path(__file__).parent.parent.parent / "config"

    @classmethod
    def _load_templates(cls) -> tuple[dict, dict]:
        template_dir = cls._template_dir()
        config_template = template_dir / "config.template.json"
        workflows_template = template_dir / "workflows.template.json"

        cfg = {}
        wf = {}

        if config_template.exists():
            with open(config_template) as f:
                cfg = json.load(f)

        if workflows_template.exists():
            with open(workflows_template) as f:
                wf = json.load(f)

        return cfg, wf

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
        existing_names = {item.get("name") for item in existing if isinstance(item, dict)}
        for trigger in template_auto.get("triggers", []) or []:
            name = trigger.get("name")
            if name and name not in existing_names:
                existing.append(copy.deepcopy(trigger))
                existing_names.add(name)
                changed = True
        target_auto["triggers"] = existing
        return changed

    @classmethod
    def _apply_template_defaults(cls, data: dict) -> tuple[dict, bool]:
        template_cfg, template_workflows = cls._load_templates()
        if not template_cfg:
            return data, False

        changed = False

        # Merge root defaults except sections handled below.
        for key, value in template_cfg.items():
            if key in {"providers", "quality_gate", "auto_collaboration"}:
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

        # Merge workflows by name.
        workflows = data.setdefault("workflows", {}) or {}
        for workflow_name, workflow_template in template_workflows.items():
            if workflow_name not in workflows:
                workflows[workflow_name] = copy.deepcopy(workflow_template)
                changed = True
        data["workflows"] = workflows

        # Migrate deprecated codex flag names.
        codex_cfg = providers.get("codex", {})
        thinking_levels = codex_cfg.get("models", {}).get("thinking_levels", {})
        for level_name in ("low", "medium", "high"):
            level_cfg = thinking_levels.get(level_name, {})
            flag = level_cfg.get("flag", "")
            if isinstance(flag, str) and "--thinking-budget" in flag:
                thinking_levels[level_name]["flag"] = flag.replace("--thinking-budget", "--thinking")
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

        # Load workflow overrides if present.
        workflows_file = cls.get_workflows_file()
        if workflows_file.exists():
            with open(workflows_file) as f:
                data["workflows"] = json.load(f)
        else:
            data.setdefault("workflows", {})

        # Merge template updates for existing users.
        data, changed = cls._apply_template_defaults(data)

        config = cls(**data)
        if changed:
            config.save()

        return config

    @classmethod
    def create_default(cls) -> "Config":
        """Create built-in minimal defaults (fallback)."""
        return cls(
            version="1.0",
            ui_language="en-US",
            current_controller="claude",
            providers={
                "claude": ProviderConfig(
                    cli="claude",
                    enabled=True,
                    timeout=120,
                    strengths=["reasoning", "code-review", "architecture", "documentation"],
                ),
                "codex": ProviderConfig(
                    cli="codex exec --model gpt-5.3-codex",
                    enabled=True,
                    timeout=300,
                    strengths=["implementation", "testing", "debugging", "integration"],
                ),
                "gemini": ProviderConfig(
                    cli="gemini -o text --approval-mode yolo",
                    enabled=True,
                    timeout=600,
                    strengths=["visual-design", "html-css", "research", "ecosystem"],
                ),
            },
            delegation_strategy="auto",
            quality_gate=QualityGateConfig(enabled=True, threshold=75),
            workflows={},
            auto_collaboration={
                "enabled": True,
                "auto_orchestration_enabled": True,
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
            },
        )

    def save(self) -> None:
        """Save configuration to file."""
        config_dir = self.get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = self.get_config_file()
        data = self.model_dump()
        workflows = data.pop("workflows", {})

        with open(config_file, "w") as f:
            json.dump(data, f, indent=2)

        workflows_file = self.get_workflows_file()
        with open(workflows_file, "w") as f:
            json.dump(workflows, f, indent=2)

    @classmethod
    def initialize(cls) -> "Config":
        """Initialize configuration with defaults from templates."""
        config_dir = cls.get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        template_cfg, template_workflows = cls._load_templates()

        if template_cfg:
            data = copy.deepcopy(template_cfg)
            data["workflows"] = copy.deepcopy(template_workflows)
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
