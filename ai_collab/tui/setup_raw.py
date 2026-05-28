"""Non-framework terminal setup flow for ai-collab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import click
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from ai_collab.core.config import Config
from ai_collab.tui.setup import (
    CONTROLLER_LABELS,
    ENTRY_SURFACE_LABELS,
    RUNTIME_MODE_LABELS,
    SetupFormData,
    _build_provider_state,
    _default_backup_provider,
    _resolve_provider_profile,
    apply_setup_form,
    build_setup_summary,
    resolve_setup_defaults,
    resolve_setup_step_titles,
)


RawInputFn = Callable[[str], str]
SCREEN_ORDER = [
    "language",
    "controller",
    "providers_profile",
    "runtime",
    "entry",
    "collaboration",
    "review",
]
SCREEN_PROGRESS = {
    "language": 1,
    "controller": 2,
    "providers_profile": 3,
    "providers_backup": 3,
    "runtime": 4,
    "entry": 5,
    "collaboration": 6,
    "review": 7,
}


@dataclass
class RawSetupState:
    form: SetupFormData
    provider_profile: str
    backup_provider: str

    @classmethod
    def from_config(cls, config: Config) -> "RawSetupState":
        form = resolve_setup_defaults(config)
        provider_profile, backup_provider = _resolve_provider_profile(form)
        form.providers = _build_provider_state(form.controller, provider_profile, backup_provider)
        return cls(form=form, provider_profile=provider_profile, backup_provider=backup_provider)


@dataclass(frozen=True)
class RawScreenSpec:
    screen_id: str
    title: str
    subtitle: str
    options: list[tuple[str, str]]
    default_value: str


def _sync_provider_state(state: RawSetupState) -> None:
    if state.provider_profile == "backup" and state.backup_provider == state.form.controller:
        state.backup_provider = _default_backup_provider(state.form.controller)
    state.form.providers = _build_provider_state(
        state.form.controller,
        state.provider_profile,
        state.backup_provider,
    )


def _resolve_screen_spec(state: RawSetupState, screen_id: str) -> RawScreenSpec:
    titles = resolve_setup_step_titles(state.form.ui_language)
    title_map = {
        "language": titles[0],
        "controller": titles[1],
        "providers_profile": titles[2],
        "providers_backup": f"{titles[2]} · Helper",
        "runtime": titles[3],
        "entry": titles[4],
        "collaboration": titles[5],
        "review": titles[6],
    }
    if screen_id == "language":
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Pick the display language for terminal UI and onboarding copy.",
            options=[("1", "English (en-US)"), ("2", "中文 (zh-CN)")],
            default_value="1" if state.form.ui_language == "en-US" else "2",
        )
    if screen_id == "controller":
        mapping = {"codex": "1", "claude": "2", "gemini": "3"}
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Choose the default lead controller for future launches.",
            options=[("1", "Codex"), ("2", "Claude"), ("3", "Gemini")],
            default_value=mapping.get(state.form.controller, "1"),
        )
    if screen_id == "providers_profile":
        mapping = {"solo": "1", "backup": "2", "full": "3"}
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Decide how many providers stay enabled after init.",
            options=[
                ("1", "Only the controller"),
                ("2", "Controller + one helper"),
                ("3", "Enable all three"),
            ],
            default_value=mapping.get(state.provider_profile, "1"),
        )
    if screen_id == "providers_backup":
        candidates = [
            name for name in ("codex", "claude", "gemini") if name != state.form.controller
        ]
        options = [(str(index + 1), CONTROLLER_LABELS[name]) for index, name in enumerate(candidates)]
        default_value = str(candidates.index(state.backup_provider) + 1) if state.backup_provider in candidates else "1"
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Pick the single helper provider that stays available beside the controller.",
            options=options,
            default_value=default_value,
        )
    if screen_id == "runtime":
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Choose the default execution backend for longer sessions.",
            options=[
                ("1", "tmux runtime · safer for long sessions"),
                ("2", "direct runtime · lighter but more fragile"),
            ],
            default_value="1" if state.form.runtime_mode == "tmux" else "2",
        )
    if screen_id == "entry":
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Choose how ai-collab should open after init.",
            options=[
                ("1", "Guided launcher · recommended"),
                ("2", "Command-first · minimal"),
            ],
            default_value="1" if state.form.entry_surface == "guided" else "2",
        )
    if screen_id == "collaboration":
        return RawScreenSpec(
            screen_id=screen_id,
            title=title_map[screen_id],
            subtitle="Set the default collaboration posture for new sessions.",
            options=[
                ("1", "Enable auto collaboration"),
                ("2", "Keep collaboration manual"),
            ],
            default_value="1" if state.form.auto_collaboration_enabled else "2",
        )
    return RawScreenSpec(
        screen_id=screen_id,
        title=title_map[screen_id],
        subtitle="Review the draft config before saving.",
        options=[("1", "Save and finish"), ("2", "Go back one step")],
        default_value="1",
    )


def render_raw_setup_screen(config_or_state: Config | RawSetupState, *, screen_id: str = "language") -> str:
    state = config_or_state if isinstance(config_or_state, RawSetupState) else RawSetupState.from_config(config_or_state)
    spec = _resolve_screen_spec(state, screen_id)
    progress = SCREEN_PROGRESS[screen_id]
    console = Console(record=True, force_terminal=False, color_system=None, width=100)
    option_lines = [f"{value}. {label}" for value, label in spec.options]
    option_block = Panel(
        "\n".join(option_lines),
        title=f"Step {progress}/7 · {spec.title}",
        border_style="cyan",
        padding=(1, 2),
    )
    summary_block = Panel(
        build_setup_summary(state.form),
        title="Current draft",
        border_style="magenta",
        padding=(1, 2),
    )
    header = Panel(
        Group(
            Text("ai-collab raw setup", style="bold cyan"),
            Text("No Textual. Sequential pages with number-based choices.", style="dim"),
        ),
        border_style="blue",
    )
    footer = Text("Type a number and press Enter. Use b to go back, q to quit.", style="dim")
    console.print(header)
    console.print(Text(spec.subtitle))
    console.print(option_block)
    console.print(summary_block)
    console.print(footer)
    return console.export_text()


def _ask_choice(
    state: RawSetupState,
    screen_id: str,
    *,
    input_fn,
    console_obj: Console,
    clear_screen: bool,
    allow_back: bool,
) -> str:
    if clear_screen:
        console_obj.clear()
    console_obj.print(render_raw_setup_screen(state, screen_id=screen_id))
    spec = _resolve_screen_spec(state, screen_id)
    valid_choices = [value for value, _ in spec.options]
    if allow_back:
        valid_choices.append("b")
    valid_choices.append("q")
    return input_fn(
        f"Select [{'/'.join(valid_choices)}]",
        choices=valid_choices,
        default=spec.default_value,
    )


def run_setup_raw(
    config: Config,
    *,
    input_fn=Prompt.ask,
    console_obj: Console | None = None,
    clear_screen: bool = True,
) -> None:
    console_obj = console_obj or Console()
    state = RawSetupState.from_config(config)
    history: list[str] = []
    screen_id = "language"

    while True:
        choice = _ask_choice(
            state,
            screen_id,
            input_fn=input_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
            allow_back=bool(history),
        )
        if choice == "q":
            raise click.Abort()
        if choice == "b":
            if history:
                screen_id = history.pop()
            continue

        previous = screen_id
        if screen_id == "language":
            state.form.ui_language = "en-US" if choice == "1" else "zh-CN"
            screen_id = "controller"
        elif screen_id == "controller":
            state.form.controller = {"1": "codex", "2": "claude", "3": "gemini"}[choice]
            _sync_provider_state(state)
            screen_id = "providers_profile"
        elif screen_id == "providers_profile":
            state.provider_profile = {"1": "solo", "2": "backup", "3": "full"}[choice]
            _sync_provider_state(state)
            screen_id = "providers_backup" if state.provider_profile == "backup" else "runtime"
        elif screen_id == "providers_backup":
            candidates = [
                name for name in ("codex", "claude", "gemini") if name != state.form.controller
            ]
            state.backup_provider = candidates[int(choice) - 1]
            _sync_provider_state(state)
            screen_id = "runtime"
        elif screen_id == "runtime":
            state.form.runtime_mode = "tmux" if choice == "1" else "direct"
            screen_id = "entry"
        elif screen_id == "entry":
            state.form.entry_surface = "guided" if choice == "1" else "command"
            screen_id = "collaboration"
        elif screen_id == "collaboration":
            state.form.auto_collaboration_enabled = choice == "1"
            screen_id = "review"
        else:
            if choice == "1":
                apply_setup_form(config, state.form)
                return
            screen_id = history.pop() if history else "collaboration"
            continue

        history.append(previous)
