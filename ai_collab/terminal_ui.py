"""Shared terminal chrome helpers aligned with tmux-style output."""

from __future__ import annotations

from typing import Iterable, Sequence


def compact_label(value: str, *, max_length: int = 18) -> str:
    """Clamp noisy labels so live stream prefixes stay readable."""
    normalized = " ".join(str(value or "").strip().split())
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 1:
        return normalized[:max_length]
    return normalized[: max_length - 1] + "…"


def build_live_output_prefix(agent: str, phase_key: str = "") -> str:
    """Build a tmux-like identity prefix for streamed provider output."""
    owner = compact_label(agent or "agent", max_length=10)
    phase = compact_label(phase_key, max_length=12)
    lane = owner if not phase else f"{owner}/{phase}"
    return f"│ {lane} │ "


def render_tmux_block(
    title: str,
    *,
    rows: Sequence[tuple[str, str]] | None = None,
    lines: Iterable[str] | None = None,
    close: bool = True,
) -> str:
    """Render a compact tmux-like status block."""
    output: list[str] = [f"┌─ {title}"]
    for key, value in rows or ():
        normalized = str(value or "").strip()
        if normalized:
            output.append(f"│ {key}: {normalized}")
    for line in lines or ():
        normalized = str(line or "").strip()
        if normalized:
            output.append(f"│ {normalized}")
    if close:
        output.append("└─")
    return "\n".join(output)
