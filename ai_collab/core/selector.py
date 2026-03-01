"""
Model selection module.
Selects the best model for a provider and task.
"""

from typing import Optional
from pydantic import BaseModel

from ai_collab.core.config import Config


class ModelSelectionResult(BaseModel):
    """Result of model selection."""
    cli: str
    model: str
    description: str
    thinking: Optional[str] = None
    flag: Optional[str] = None


class ModelSelector:
    """Selects the best model for a provider and task."""

    def __init__(self, config: Config):
        self.config = config

    def _enabled_profiles(self, models: dict, available: list[str]) -> list[str]:
        """Return configured enabled profiles filtered by available keys."""
        raw = models.get("enabled_profiles", [])
        if not isinstance(raw, list) or not raw:
            return list(available)
        enabled = [item for item in raw if item in available]
        return enabled or list(available)

    def _catalog_profiles(self, models: dict) -> dict:
        raw = models.get("catalog_profiles", {})
        if not isinstance(raw, dict):
            return {}
        valid: dict = {}
        for key, value in raw.items():
            if isinstance(value, dict) and value.get("model"):
                valid[key] = value
        return valid

    def select_model(
        self, provider: str, task: str, complexity: str = "default"
    ) -> ModelSelectionResult:
        """
        Select the best model for a provider and task.

        Args:
            provider: AI provider (claude/codex/gemini)
            task: Task description
            complexity: Task complexity (low/medium/high/default)

        Returns:
            ModelSelectionResult with selected model details
        """
        provider_config = self.config.providers.get(provider)

        if not provider_config:
            raise ValueError(f"Unknown provider: {provider}")

        base_cli = provider_config.cli
        models = provider_config.models
        selection_mode = provider_config.model_selection

        # Codex: thinking level selection
        if provider == "codex":
            return self._select_codex_model(base_cli, models, complexity)

        # Claude: cost/power selection
        elif provider == "claude":
            return self._select_claude_model(base_cli, models, selection_mode)

        # Gemini: cost/power selection
        elif provider == "gemini":
            return self._select_gemini_model(base_cli, models, complexity, selection_mode)

        return ModelSelectionResult(
            cli=base_cli,
            model="unknown",
            description="Not configured",
        )

    def _select_codex_model(
        self, base_cli: str, models: dict, complexity: str
    ) -> ModelSelectionResult:
        """Select Codex model based on thinking level."""
        thinking_levels = models.get("thinking_levels", {})
        enabled_levels = self._enabled_profiles(models, list(thinking_levels.keys()))
        if not enabled_levels:
            enabled_levels = ["high"] if "high" in thinking_levels else list(thinking_levels.keys())

        if complexity == "default":
            configured = str(models.get("default_thinking", "high")).strip()
            thinking = configured if configured in enabled_levels else enabled_levels[0]
            level = thinking_levels.get(thinking, thinking_levels.get("high", {}))
        else:
            requested = complexity if complexity in enabled_levels else None
            if requested is None:
                configured = str(models.get("default_thinking", "high")).strip()
                requested = configured if configured in enabled_levels else enabled_levels[0]
            level = thinking_levels.get(requested, thinking_levels.get("high", {}))
            thinking = requested

        flag = level.get("flag", "")
        cli = f"{base_cli} {flag}".strip()

        return ModelSelectionResult(
            cli=cli,
            model="gpt-5.3-codex",
            thinking=thinking,
            description=level.get("description", ""),
        )

    def _select_claude_model(
        self, base_cli: str, models: dict, selection_mode: str
    ) -> ModelSelectionResult:
        """Select Claude model."""
        if selection_mode == "ask_user":
            return ModelSelectionResult(
                cli=base_cli,
                model="ask_user",
                description="User selection required",
            )

        catalog_profiles = self._catalog_profiles(models)
        available_profiles = ["default", "cost_effective", "powerful", *catalog_profiles.keys()]
        enabled_profiles = self._enabled_profiles(models, available_profiles)
        chosen_mode = selection_mode if selection_mode in enabled_profiles else enabled_profiles[0]

        if chosen_mode in {"cost_effective", "powerful"} or chosen_mode in catalog_profiles:
            selected = catalog_profiles.get(chosen_mode, models.get(chosen_mode, {}))
            model_name = selected.get("model", models.get("default", "claude-sonnet-4-6"))
            flag = selected.get("flag", "")
            cli = f"{base_cli} {flag}".strip()
            return ModelSelectionResult(
                cli=cli,
                model=model_name,
                flag=flag or None,
                description=selected.get("description", f"{chosen_mode}: {model_name}"),
            )

        default_model = models.get("default", "claude-sonnet-4-6")
        default_flag = ""
        for mode_key in ("cost_effective", "powerful", *catalog_profiles.keys()):
            mode_cfg = catalog_profiles.get(mode_key, models.get(mode_key, {}))
            if mode_cfg.get("model") == default_model:
                default_flag = mode_cfg.get("flag", "")
                break

        cli = f"{base_cli} {default_flag}".strip()
        return ModelSelectionResult(
            cli=cli,
            model=default_model,
            flag=default_flag or None,
            description=f"Default: {default_model}",
        )

    def _select_gemini_model(
        self, base_cli: str, models: dict, complexity: str, selection_mode: str
    ) -> ModelSelectionResult:
        """Select Gemini model."""
        auto_route_default = bool(models.get("auto_route_default", True))
        catalog_profiles = self._catalog_profiles(models)
        available_profiles = ["auto", "cost_effective", "powerful", *catalog_profiles.keys()]
        enabled_profiles = self._enabled_profiles(models, available_profiles)

        if complexity in {"default", "auto"}:
            if selection_mode in enabled_profiles and selection_mode != "auto":
                model_config = catalog_profiles.get(selection_mode, models.get(selection_mode, {}))
                model_name = model_config.get("model", "gemini-cli-auto")
                flag = model_config.get("flag", "")
                cli = f"{base_cli} {flag}".strip()
                return ModelSelectionResult(
                    cli=cli,
                    model=model_name,
                    flag=flag or None,
                    description=model_config.get("description", f"{selection_mode}: {model_name}"),
                )
            if auto_route_default and "auto" in enabled_profiles:
                return ModelSelectionResult(
                    cli=base_cli,
                    model="gemini-cli-auto",
                    description="Gemini CLI decides model automatically",
                )

            fallback_mode = next(
                (item for item in ("powerful", "cost_effective") if item in enabled_profiles),
                "powerful",
            )
            if fallback_mode == "powerful" and fallback_mode not in enabled_profiles:
                fallback_mode = next((item for item in enabled_profiles if item != "auto"), "powerful")
            model_config = catalog_profiles.get(fallback_mode, models.get(fallback_mode, {}))
            model_name = model_config.get("model", "gemini-3.1-pro-preview")
            flag = model_config.get("flag", "")
            cli = f"{base_cli} {flag}".strip()
            return ModelSelectionResult(
                cli=cli,
                model=model_name,
                flag=flag or None,
                description=model_config.get("description", f"{fallback_mode}: {model_name}"),
            )

        if complexity in ["low", "cost_effective"]:
            target = "cost_effective"
        else:
            target = "powerful"

        if target not in enabled_profiles:
            target = next(
                (item for item in ("cost_effective", "powerful") if item in enabled_profiles),
                target,
            )
            if target not in enabled_profiles:
                target = next((item for item in enabled_profiles if item != "auto"), target)

        model_config = catalog_profiles.get(target, models.get(target, {}))
        if target == "cost_effective":
            model_name = model_config.get("model", "gemini-3-flash-preview")
        elif target == "powerful":
            model_name = model_config.get("model", "gemini-3.1-pro-preview")
        else:
            model_name = model_config.get("model", "gemini-cli-auto")

        flag = model_config.get("flag", "")
        cli = f"{base_cli} {flag}".strip()

        return ModelSelectionResult(
            cli=cli,
            model=model_name,
            flag=flag or None,
            description=model_config.get("description", ""),
        )

    def interactive_selection(self, provider: str, task: str) -> ModelSelectionResult:
        """Interactive model selection."""
        from rich.console import Console
        from rich.prompt import Prompt

        console = Console()
        provider_config = self.config.providers.get(provider)

        if not provider_config:
            raise ValueError(f"Unknown provider: {provider}")

        models = provider_config.models

        console.print(f"\n[bold]🤖 {provider.upper()} Model Selection[/bold]")
        console.print(f"Task: {task}")
        console.print("=" * 60)

        if provider == "claude":
            default_model = str(models.get("default", "claude-sonnet-4-6"))
            cost_model = str((models.get("cost_effective", {}) or {}).get("model", "claude-haiku-4-5"))
            powerful_model = str((models.get("powerful", {}) or {}).get("model", "claude-opus-4-6"))
            console.print("\nAvailable models:")
            console.print(f"1. {default_model} (default)")
            console.print(f"2. {cost_model} (cost-effective)")
            console.print(f"3. {powerful_model} (powerful)")

            choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="1")

            if choice == "2":
                return ModelSelectionResult(
                    cli=f"{provider_config.cli} --model {cost_model}",
                    model=cost_model,
                    flag=f"--model {cost_model}",
                    description="Cost-effective mode",
                )
            if choice == "3":
                return ModelSelectionResult(
                    cli=f"{provider_config.cli} --model {powerful_model}",
                    model=powerful_model,
                    flag=f"--model {powerful_model}",
                    description="Powerful mode",
                )
            return ModelSelectionResult(
                cli=f"{provider_config.cli} --model {default_model}",
                model=default_model,
                flag=f"--model {default_model}",
                description="Default mode",
            )

        elif provider == "codex":
            console.print("\nThinking level:")
            console.print("1. low - Simple tasks (formatting, simple changes)")
            console.print("2. medium - Medium tasks (feature implementation, refactoring)")
            console.print("3. high - Complex tasks (architecture, complex logic) [Recommended]")

            choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="3")

            thinking_map = {"1": "low", "2": "medium", "3": "high"}
            thinking = thinking_map[choice]

            return self.select_model("codex", task, thinking)

        elif provider == "gemini":
            powerful_model = str((models.get("powerful", {}) or {}).get("model", "gemini-3.1-pro-preview"))
            cost_model = str((models.get("cost_effective", {}) or {}).get("model", "gemini-3-flash-preview"))
            console.print("\nAvailable models:")
            console.print(f"1. {cost_model} (cost-effective)")
            console.print(f"2. {powerful_model} (powerful) [Recommended]")

            choice = Prompt.ask("Choose", choices=["1", "2"], default="2")

            complexity = "low" if choice == "1" else "high"
            return self.select_model("gemini", task, complexity)

        return ModelSelectionResult(
            cli=provider_config.cli,
            model="unknown",
            description="Not configured",
        )
