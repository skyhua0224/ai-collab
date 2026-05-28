"""PyPI update check helpers for ai-collab."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
import sys
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ai_collab import __version__ as AI_COLLAB_VERSION

PYPI_PACKAGE_NAME = "ai-collab"
PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
_VERSION_RE = re.compile(r"^(?P<release>\d+(?:\.\d+){0,2})(?:(?P<sep>\.?)(?P<stage>dev|a|b|rc)(?P<num>\d+)?)?$")
_STAGE_ORDER = {"dev": -1, "a": 0, "b": 1, "rc": 2, "final": 3}


@dataclass(frozen=True)
class UpdateCheckResult:
    package_name: str
    local_version: str
    remote_version: str | None
    status: str
    detail: str = ""


@dataclass(frozen=True)
class _ParsedVersion:
    release: tuple[int, int, int]
    stage: str
    stage_num: int


def _parse_version(value: str) -> _ParsedVersion:
    raw = str(value or "").strip()
    match = _VERSION_RE.match(raw)
    if not match:
        raise ValueError(f"Unsupported version format: {value}")

    release_parts = [int(part) for part in match.group("release").split(".")]
    while len(release_parts) < 3:
        release_parts.append(0)
    stage = match.group("stage") or "final"
    stage_num = int(match.group("num") or 0)
    return _ParsedVersion(release=tuple(release_parts[:3]), stage=stage, stage_num=stage_num)


def compare_versions(local_version: str, remote_version: str) -> int:
    local = _parse_version(local_version)
    remote = _parse_version(remote_version)
    if local.release != remote.release:
        return -1 if local.release < remote.release else 1
    local_stage = (_STAGE_ORDER[local.stage], local.stage_num)
    remote_stage = (_STAGE_ORDER[remote.stage], remote.stage_num)
    if local_stage == remote_stage:
        return 0
    return -1 if local_stage < remote_stage else 1


def fetch_pypi_version(package_name: str = PYPI_PACKAGE_NAME, *, timeout: float = 2.0) -> str:
    url = PYPI_JSON_URL.format(package=quote(package_name))
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"ai-collab/{AI_COLLAB_VERSION}",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    info = payload.get("info", {}) if isinstance(payload, dict) else {}
    version = str(info.get("version", "")).strip()
    if not version:
        raise ValueError(f"PyPI response for {package_name} did not include a version")
    return version


def check_pypi_update(
    *,
    package_name: str = PYPI_PACKAGE_NAME,
    local_version: str = AI_COLLAB_VERSION,
    fetcher: Callable[..., str] = fetch_pypi_version,
) -> UpdateCheckResult:
    try:
        remote_version = fetcher(package_name=package_name)
    except HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(
                package_name=package_name,
                local_version=local_version,
                remote_version=None,
                status="unpublished",
                detail="Package not published on PyPI.",
            )
        return UpdateCheckResult(
            package_name=package_name,
            local_version=local_version,
            remote_version=None,
            status="unavailable",
            detail=f"HTTP {exc.code}",
        )
    except (URLError, OSError, ValueError) as exc:
        return UpdateCheckResult(
            package_name=package_name,
            local_version=local_version,
            remote_version=None,
            status="unavailable",
            detail=str(exc),
        )

    try:
        comparison = compare_versions(local_version, remote_version)
    except ValueError as exc:
        return UpdateCheckResult(
            package_name=package_name,
            local_version=local_version,
            remote_version=remote_version,
            status="unavailable",
            detail=str(exc),
        )

    if comparison < 0:
        return UpdateCheckResult(
            package_name=package_name,
            local_version=local_version,
            remote_version=remote_version,
            status="behind",
            detail="A newer release exists on PyPI.",
        )
    if comparison > 0:
        return UpdateCheckResult(
            package_name=package_name,
            local_version=local_version,
            remote_version=remote_version,
            status="ahead",
            detail="Local build is ahead of PyPI.",
        )
    return UpdateCheckResult(
        package_name=package_name,
        local_version=local_version,
        remote_version=remote_version,
        status="equal",
        detail="Local version matches PyPI.",
    )


def run_self_update(
    *,
    package_name: str = PYPI_PACKAGE_NAME,
    python_executable: str = sys.executable,
) -> bool:
    command = [python_executable, "-m", "pip", "install", "--upgrade", package_name]
    result = subprocess.run(command, check=False)
    return result.returncode == 0
