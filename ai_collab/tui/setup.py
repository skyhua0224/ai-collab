"""Formal setup TUI for ai-collab initialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai_collab.core.config import Config


LANGUAGE_LABELS = {
    "en-US": "English (en-US)",
    "zh-CN": "中文 (zh-CN)",
}

CONTROLLER_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "gemini": "Gemini CLI",
}

ENTRY_SURFACE_LABELS = {
    "guided": "Guided launcher",
    "command": "Command-first",
}

RUNTIME_MODE_LABELS = {
    "tmux": "tmux runtime",
    "direct": "direct runtime",
}

SETUP_STEP_TITLES = {
    "en-US": ["Language", "Controller", "Providers", "Runtime", "Entry", "Collaboration", "Review"],
    "zh-CN": ["语言", "主控", "提供方", "运行方式", "入口", "协作", "确认"],
}

SETUP_STEP_IDS = ("language", "controller", "providers", "runtime", "entry", "collaboration", "review")


@dataclass
class SetupFormData:
    ui_language: str
    controller: str
    entry_surface: str
    runtime_mode: str
    providers: dict[str, bool]
    auto_collaboration_enabled: bool


def resolve_setup_defaults(config: Config) -> SetupFormData:
    auto_cfg = config.auto_collaboration or {}
    return SetupFormData(
        ui_language=config.ui_language if config.ui_language in {"en-US", "zh-CN"} else "en-US",
        controller=config.current_controller,
        entry_surface=getattr(config, "entry_surface", "guided") or "guided",
        runtime_mode=getattr(config, "runtime_mode", "tmux") or "tmux",
        providers={
            name: bool(provider.enabled)
            for name, provider in config.providers.items()
            if name in {"codex", "claude", "gemini"}
        },
        auto_collaboration_enabled=bool(
            auto_cfg.get("enabled", auto_cfg.get("auto_orchestration_enabled", True))
        ),
    )


def resolve_setup_step_titles(language: str) -> list[str]:
    return list(SETUP_STEP_TITLES.get(language, SETUP_STEP_TITLES["en-US"]))


def _resolve_provider_profile(form: SetupFormData) -> tuple[str, str]:
    enabled = [name for name, flag in form.providers.items() if flag]
    backups = [name for name in enabled if name != form.controller]
    all_enabled = all(form.providers.get(name, False) for name in ("codex", "claude", "gemini"))
    if all_enabled:
        return "full", backups[0] if backups else _default_backup_provider(form.controller)
    if backups:
        return "backup", backups[0]
    return "solo", _default_backup_provider(form.controller)


def _default_backup_provider(controller: str) -> str:
    for name in ("codex", "claude", "gemini"):
        if name != controller:
            return name
    return "codex"


def _build_provider_state(controller: str, profile: str, backup_provider: str) -> dict[str, bool]:
    providers = {"codex": False, "claude": False, "gemini": False}
    providers[controller] = True
    if profile == "full":
        for name in providers:
            providers[name] = True
    elif profile == "backup" and backup_provider in providers:
        providers[backup_provider] = True
    return providers


def build_setup_summary(form: SetupFormData) -> str:
    providers = [
        CONTROLLER_LABELS.get(name, name.title())
        for name, enabled in form.providers.items()
        if enabled
    ]
    if not providers:
        providers = [CONTROLLER_LABELS.get(form.controller, form.controller.title())]

    lines = [
        f"Language: {LANGUAGE_LABELS.get(form.ui_language, form.ui_language)}",
        f"Controller: {CONTROLLER_LABELS.get(form.controller, form.controller.title())}",
        f"Entry: {ENTRY_SURFACE_LABELS.get(form.entry_surface, form.entry_surface)}",
        f"Runtime: {RUNTIME_MODE_LABELS.get(form.runtime_mode, form.runtime_mode)}",
        f"Providers: {', '.join(providers)}",
        f"Auto collaboration: {'Enabled' if form.auto_collaboration_enabled else 'Disabled'}",
    ]
    return "\n".join(lines)


def apply_setup_form(config: Config, form: SetupFormData) -> None:
    config.ui_language = form.ui_language if form.ui_language in {"en-US", "zh-CN"} else "en-US"
    config.entry_surface = form.entry_surface if form.entry_surface in {"guided", "command"} else "guided"
    config.runtime_mode = form.runtime_mode if form.runtime_mode in {"tmux", "direct"} else "tmux"

    enabled_providers = [name for name, enabled in form.providers.items() if enabled and name in config.providers]
    if not enabled_providers:
        fallback = form.controller if form.controller in config.providers else "codex"
        enabled_providers = [fallback]

    for name, provider in config.providers.items():
        provider.enabled = name in enabled_providers

    config.current_controller = form.controller if form.controller in enabled_providers else enabled_providers[0]

    auto_cfg = dict(config.auto_collaboration or {})
    enabled = bool(form.auto_collaboration_enabled)
    auto_cfg["enabled"] = enabled
    auto_cfg["auto_orchestration_enabled"] = enabled
    config.auto_collaboration = auto_cfg


try:  # pragma: no cover - import guard for environments without textual
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.screen import Screen
    from textual.widgets import ContentSwitcher, OptionList, Static
    from textual.widgets.option_list import Option
except ImportError:  # pragma: no cover
    App = None  # type: ignore[assignment]
    ComposeResult = object  # type: ignore[assignment]
    Binding = object  # type: ignore[assignment]
    ContentSwitcher = OptionList = Static = Option = object  # type: ignore[assignment]
    Screen = object  # type: ignore[assignment]
    on = None  # type: ignore[assignment]


if App is not None:

    class SetupTextualApp(App[Optional[SetupFormData]]):  # pragma: no cover - exercised via integration tests
        BINDINGS = [
            Binding("b", "previous_step", "Back"),
            Binding("ctrl+s", "save", "Save"),
            Binding("escape", "cancel", "Cancel"),
        ]

        CSS = """
        Screen {
          layout: vertical;
          background: $surface;
        }

        #setup-shell {
          padding: 1 2;
          height: 1fr;
        }

        #hero {
          height: auto;
          border: round $primary;
          padding: 1 2;
          margin-bottom: 1;
        }

        #hero-title {
          text-style: bold;
        }

        #hero-subtitle, #progress, #step-subtitle, #hints {
          color: $text-muted;
        }

        #progress {
          margin-top: 1;
        }

        #step-title {
          text-style: bold;
          margin-top: 1;
        }

        #step-subtitle {
          margin-top: 1;
          margin-bottom: 1;
        }

        .panel {
          border: round $primary;
          padding: 1 2;
          height: auto;
        }

        #setup-steps {
          height: auto;
          margin-bottom: 1;
        }

        #summary {
          border: round $panel;
          padding: 1 2;
          margin-top: 1;
          height: auto;
        }

        #review-summary {
          border: round $panel;
          padding: 1;
          margin-bottom: 1;
          min-height: 8;
        }

        #backup-label {
          margin-top: 1;
          color: $text-muted;
        }

        OptionList {
          margin-top: 1;
        }

        #hints {
          border-top: solid $panel;
          margin-top: 1;
          padding-top: 1;
        }
        """

        def __init__(self, initial: SetupFormData):
            super().__init__()
            self.initial = initial
            self.current_step = 0
            self.ui_language = initial.ui_language
            self.controller = initial.controller
            self.runtime_mode = initial.runtime_mode
            self.entry_surface = initial.entry_surface
            self.auto_collaboration_enabled = initial.auto_collaboration_enabled
            self.provider_profile, self.backup_provider = _resolve_provider_profile(initial)

        def compose(self) -> ComposeResult:
            with Vertical(id="setup-shell"):
                with Vertical(id="hero"):
                    yield Static("ai-collab Setup", id="hero-title")
                    yield Static(
                        "One decision per screen. Use ↑/↓ to move and Enter to confirm.",
                        id="hero-subtitle",
                    )
                yield Static("", id="progress")
                yield Static("", id="step-title")
                yield Static("", id="step-subtitle")
                with ContentSwitcher(initial="step-language", id="setup-steps"):
                    with Vertical(id="step-language", classes="panel"):
                        yield OptionList(
                            Option("English (en-US)", id="language-en-US"),
                            Option("中文 (zh-CN)", id="language-zh-CN"),
                            id="language-options",
                        )
                    with Vertical(id="step-controller", classes="panel"):
                        yield OptionList(
                            Option("Codex", id="controller-codex"),
                            Option("Claude", id="controller-claude"),
                            Option("Gemini", id="controller-gemini"),
                            id="controller-options",
                        )
                    with Vertical(id="step-providers", classes="panel"):
                        yield OptionList(
                            Option("Only the controller", id="providers-solo"),
                            Option("Controller + one helper", id="providers-backup"),
                            Option("Enable all three", id="providers-full"),
                            id="providers-profile",
                        )
                        yield Static("Backup provider", id="backup-label")
                        yield OptionList(id="backup-provider")
                    with Vertical(id="step-runtime", classes="panel"):
                        yield OptionList(
                            Option("tmux runtime · safer for long sessions", id="runtime-tmux"),
                            Option("direct runtime · lighter but less stable", id="runtime-direct"),
                            id="runtime-options",
                        )
                    with Vertical(id="step-entry", classes="panel"):
                        yield OptionList(
                            Option("Guided launcher · recommended for daily use", id="entry-guided"),
                            Option("Command-first · minimal and explicit", id="entry-command"),
                            id="entry-options",
                        )
                    with Vertical(id="step-collaboration", classes="panel"):
                        yield OptionList(
                            Option("Enable auto collaboration", id="collaboration-enabled"),
                            Option("Keep collaboration manual", id="collaboration-disabled"),
                            id="collaboration-options",
                        )
                    with Vertical(id="step-review", classes="panel"):
                        yield Static("", id="review-summary")
                        yield OptionList(
                            Option("Save and finish", id="review-save"),
                            Option("Go back one step", id="review-back"),
                            id="review-actions",
                        )
                yield Static("", id="summary")
                yield Static("", id="hints")

        def on_mount(self) -> None:
            self._refresh_view()
            self._focus_current_step()

        def _step_subtitle(self, step_id: str) -> str:
            subtitles = {
                "language": "Pick the display language for the terminal UI.",
                "controller": "Choose the main controller that leads future runs.",
                "providers": "Choose how many providers stay visible after init.",
                "runtime": "Pick the default execution backend for long sessions.",
                "entry": "Choose how ai-collab opens by default after init.",
                "collaboration": "Decide whether automatic collaboration starts enabled.",
                "review": "Review the generated defaults before writing the config.",
            }
            return subtitles[step_id]

        def _collect(self) -> SetupFormData:
            return SetupFormData(
                ui_language=self.ui_language,
                controller=self.controller,
                entry_surface=self.entry_surface,
                runtime_mode=self.runtime_mode,
                providers=_build_provider_state(self.controller, self.provider_profile, self.backup_provider),
                auto_collaboration_enabled=self.auto_collaboration_enabled,
            )

        def _set_highlight(self, widget_id: str, option_id: str) -> None:
            option_list = self.query_one(widget_id, OptionList)
            for index, option in enumerate(option_list.options):
                if option.id == option_id:
                    option_list.highlighted = index
                    break

        def _set_backup_options(self) -> None:
            backup_list = self.query_one("#backup-provider", OptionList)
            candidates = [
                name for name in ("codex", "claude", "gemini") if name != self.controller
            ]
            if self.backup_provider not in candidates:
                self.backup_provider = candidates[0]
            backup_list.clear_options()
            backup_list.add_options(
                [Option(CONTROLLER_LABELS[name], id=f"backup-{name}") for name in candidates]
            )
            self._set_highlight("#backup-provider", f"backup-{self.backup_provider}")
            show_backup = self.provider_profile == "backup"
            self.query_one("#backup-label", Static).display = show_backup
            backup_list.display = show_backup

        def _refresh_view(self) -> None:
            step_id = SETUP_STEP_IDS[self.current_step]
            titles = resolve_setup_step_titles(self.ui_language)
            form = self._collect()
            self.query_one("#setup-steps", ContentSwitcher).current = f"step-{step_id}"
            self.query_one("#progress", Static).update(
                f"Step {self.current_step + 1}/{len(SETUP_STEP_IDS)} · {titles[self.current_step]}"
            )
            self.query_one("#step-title", Static).update(titles[self.current_step])
            self.query_one("#step-subtitle", Static).update(self._step_subtitle(step_id))
            self.query_one("#summary", Static).update(build_setup_summary(form))
            self.query_one("#review-summary", Static).update(build_setup_summary(form))
            self.query_one("#hints", Static).update(
                "↑/↓ move · Enter confirm · b back · Ctrl+S save · Esc cancel"
            )
            self._set_highlight("#language-options", f"language-{self.ui_language}")
            self._set_highlight("#controller-options", f"controller-{self.controller}")
            self._set_highlight("#providers-profile", f"providers-{self.provider_profile}")
            self._set_backup_options()
            self._set_highlight("#runtime-options", f"runtime-{self.runtime_mode}")
            self._set_highlight("#entry-options", f"entry-{self.entry_surface}")
            self._set_highlight(
                "#collaboration-options",
                "collaboration-enabled" if self.auto_collaboration_enabled else "collaboration-disabled",
            )
            self._set_highlight("#review-actions", "review-save")

        def _focus_current_step(self) -> None:
            focus_map = {
                "language": "#language-options",
                "controller": "#controller-options",
                "providers": "#providers-profile",
                "runtime": "#runtime-options",
                "entry": "#entry-options",
                "collaboration": "#collaboration-options",
                "review": "#review-actions",
            }
            self.query_one(focus_map[SETUP_STEP_IDS[self.current_step]]).focus()

        def _set_step(self, step_index: int) -> None:
            self.current_step = max(0, min(step_index, len(SETUP_STEP_IDS) - 1))
            self._refresh_view()
            self._focus_current_step()

        def action_previous_step(self) -> None:
            self._set_step(self.current_step - 1)

        def action_save(self) -> None:
            self.exit(result=self._collect())

        def action_cancel(self) -> None:
            self.exit(result=None)

        @on(OptionList.OptionSelected, "#language-options")
        def _on_language_selected(self, event: OptionList.OptionSelected) -> None:
            self.ui_language = str(event.option_id).removeprefix("language-")
            self._set_step(1)

        @on(OptionList.OptionSelected, "#controller-options")
        def _on_controller_selected(self, event: OptionList.OptionSelected) -> None:
            self.controller = str(event.option_id).removeprefix("controller-")
            if self.backup_provider == self.controller:
                self.backup_provider = _default_backup_provider(self.controller)
            self._set_step(2)

        @on(OptionList.OptionSelected, "#providers-profile")
        def _on_provider_profile_selected(self, event: OptionList.OptionSelected) -> None:
            self.provider_profile = str(event.option_id).removeprefix("providers-")
            self._refresh_view()
            if self.provider_profile == "backup":
                self.query_one("#backup-provider", OptionList).focus()
            else:
                self._set_step(3)

        @on(OptionList.OptionSelected, "#backup-provider")
        def _on_backup_provider_selected(self, event: OptionList.OptionSelected) -> None:
            self.backup_provider = str(event.option_id).removeprefix("backup-")
            self._set_step(3)

        @on(OptionList.OptionSelected, "#runtime-options")
        def _on_runtime_selected(self, event: OptionList.OptionSelected) -> None:
            self.runtime_mode = str(event.option_id).removeprefix("runtime-")
            self._set_step(4)

        @on(OptionList.OptionSelected, "#entry-options")
        def _on_entry_selected(self, event: OptionList.OptionSelected) -> None:
            self.entry_surface = str(event.option_id).removeprefix("entry-")
            self._set_step(5)

        @on(OptionList.OptionSelected, "#collaboration-options")
        def _on_collaboration_selected(self, event: OptionList.OptionSelected) -> None:
            self.auto_collaboration_enabled = event.option_id == "collaboration-enabled"
            self._set_step(6)

        @on(OptionList.OptionSelected, "#review-actions")
        def _on_review_selected(self, event: OptionList.OptionSelected) -> None:
            if event.option_id == "review-save":
                self.action_save()
            else:
                self.action_previous_step()

else:

    class SetupTextualApp:  # pragma: no cover - lightweight fallback for environments without textual
        def __init__(self, initial: SetupFormData):
            self.initial = initial

        def run(self) -> Optional[SetupFormData]:
            return self.initial


class SetupWizardApp:  # pragma: no cover - interactive shell wrapper
    """Thin wrapper so CLI can launch a formal setup TUI without keeping UI code in cli.py."""

    def __init__(self, initial: SetupFormData):
        self.initial = initial

    def run(self) -> Optional[SetupFormData]:
        return SetupTextualApp(self.initial).run()



def run_setup_tui(config: Config) -> None:
    result = SetupWizardApp(resolve_setup_defaults(config)).run()
    if isinstance(result, SetupFormData):
        apply_setup_form(config, result)
