"""Formal settings TUI for ai-collab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai_collab.core.config import Config


@dataclass
class SettingsFormData:
    ui_language: str
    controller: str
    entry_surface: str
    runtime_mode: str
    providers: dict[str, bool]
    auto_collaboration_enabled: bool


def resolve_settings_defaults(config: Config) -> SettingsFormData:
    auto_cfg = config.auto_collaboration or {}
    return SettingsFormData(
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


def apply_settings_form(config: Config, form: SettingsFormData) -> None:
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


class SettingsApp:  # pragma: no cover - interactive UI wrapper
    def __init__(self, initial: SettingsFormData):
        self.initial = initial

    def run(self) -> Optional[SettingsFormData]:
        try:
            from textual.app import App, ComposeResult
            from textual.binding import Binding
            from textual.containers import VerticalScroll
            from textual.widgets import Checkbox, Footer, Header, Select, Static
        except ImportError:
            return self.initial

        initial = self.initial

        class _SettingsApp(App[Optional[SettingsFormData]]):
            BINDINGS = [
                Binding("ctrl+s", "save", "Save"),
                Binding("escape", "cancel", "Cancel"),
            ]

            CSS = """
            Screen {
              layout: vertical;
            }

            #settings-body {
              padding: 1 2;
            }

            Select, Checkbox {
              margin: 1 0;
            }

            .muted {
              color: $text-muted;
            }
            """

            def compose(self) -> ComposeResult:
                yield Header(show_clock=False)
                with VerticalScroll(id="settings-body"):
                    yield Static("ai-collab Settings")
                    yield Static("Single-page keyboard-first settings. Ctrl+S saves, Esc cancels.", classes="muted")
                    yield Static("Display language", classes="muted")
                    yield Select(
                        options=[("English (en-US)", "en-US"), ("中文 (zh-CN)", "zh-CN")],
                        value=initial.ui_language,
                        allow_blank=False,
                        id="language",
                    )
                    yield Static("Default controller", classes="muted")
                    yield Select(
                        options=[("Codex", "codex"), ("Claude", "claude"), ("Gemini", "gemini")],
                        value=initial.controller,
                        allow_blank=False,
                        id="controller",
                    )
                    yield Static("Entry surface", classes="muted")
                    yield Select(
                        options=[("Guided launcher", "guided"), ("Command-first", "command")],
                        value=initial.entry_surface,
                        allow_blank=False,
                        id="entry-surface",
                    )
                    yield Static("Runtime mode", classes="muted")
                    yield Select(
                        options=[("tmux runtime", "tmux"), ("direct runtime", "direct")],
                        value=initial.runtime_mode,
                        allow_blank=False,
                        id="runtime-mode",
                    )
                    yield Static("Enabled providers", classes="muted")
                    yield Checkbox("Codex", value=initial.providers.get("codex", True), id="provider-codex")
                    yield Checkbox("Claude", value=initial.providers.get("claude", True), id="provider-claude")
                    yield Checkbox("Gemini", value=initial.providers.get("gemini", True), id="provider-gemini")
                    yield Static("Collaboration", classes="muted")
                    yield Checkbox(
                        "Enable auto collaboration",
                        value=initial.auto_collaboration_enabled,
                        id="auto-collaboration",
                    )
                yield Footer()

            def _collect(self) -> SettingsFormData:
                return SettingsFormData(
                    ui_language=str(self.query_one("#language", Select).value or initial.ui_language),
                    controller=str(self.query_one("#controller", Select).value or initial.controller),
                    entry_surface=str(self.query_one("#entry-surface", Select).value or initial.entry_surface),
                    runtime_mode=str(self.query_one("#runtime-mode", Select).value or initial.runtime_mode),
                    providers={
                        "codex": bool(self.query_one("#provider-codex", Checkbox).value),
                        "claude": bool(self.query_one("#provider-claude", Checkbox).value),
                        "gemini": bool(self.query_one("#provider-gemini", Checkbox).value),
                    },
                    auto_collaboration_enabled=bool(self.query_one("#auto-collaboration", Checkbox).value),
                )

            def action_save(self) -> None:
                self.exit(result=self._collect())

            def action_cancel(self) -> None:
                self.exit(result=None)

        return _SettingsApp().run()


def run_settings_tui(config: Config) -> None:
    result = SettingsApp(resolve_settings_defaults(config)).run()
    if isinstance(result, SettingsFormData):
        apply_settings_form(config, result)

