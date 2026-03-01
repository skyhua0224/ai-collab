"""
Local runtime environment detection for provider CLIs.
"""

from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping

from ai_collab.core.config import ProviderConfig


@dataclass
class ProviderRuntimeStatus:
    """Runtime status for a provider command."""

    provider: str
    executable: str
    available: bool
    resolved_path: str = ""
    version: str = ""


def detect_os_name(system_name: str | None = None) -> str:
    """Return normalized OS name: windows/linux/macos/unknown."""
    raw = (system_name or platform.system()).strip().lower()
    if raw.startswith("darwin"):
        return "macos"
    if raw.startswith("linux"):
        return "linux"
    if raw.startswith("win"):
        return "windows"
    return "unknown"


def resolve_executable(cli: str, *, os_name: str | None = None) -> str:
    """Extract executable token from provider CLI string."""
    normalized_os = detect_os_name(os_name)
    posix = normalized_os != "windows"
    try:
        parts = shlex.split(cli, posix=posix)
    except ValueError:
        parts = cli.strip().split()
    return parts[0] if parts else ""


def _read_version(executable: str) -> str:
    """Read provider version with a short timeout."""
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""

    text = (result.stdout or result.stderr or "").strip()
    if not text:
        return ""
    return text.splitlines()[0].strip()


def detect_provider_status(
    providers: Mapping[str, ProviderConfig],
    *,
    os_name: str | None = None,
) -> dict[str, ProviderRuntimeStatus]:
    """Detect local availability for each provider CLI."""
    normalized_os = detect_os_name(os_name)
    statuses: dict[str, ProviderRuntimeStatus] = {}
    for provider_name, provider_cfg in providers.items():
        exe = resolve_executable(provider_cfg.cli, os_name=normalized_os)
        resolved = shutil.which(exe) if exe else None
        available = bool(resolved)
        statuses[provider_name] = ProviderRuntimeStatus(
            provider=provider_name,
            executable=exe,
            available=available,
            resolved_path=resolved or "",
            version=_read_version(exe) if available else "",
        )
    return statuses

