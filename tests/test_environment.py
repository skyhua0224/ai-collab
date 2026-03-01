"""Tests for local runtime environment detection."""

from ai_collab.core.config import Config
from ai_collab.core.environment import detect_os_name, detect_provider_status, resolve_executable


def test_detect_os_name_variants():
    assert detect_os_name("Darwin") == "macos"
    assert detect_os_name("Linux") == "linux"
    assert detect_os_name("Windows") == "windows"
    assert detect_os_name("SomethingElse") == "unknown"


def test_resolve_executable_from_cli():
    assert resolve_executable("codex exec --model gpt-5.3-codex") == "codex"
    assert resolve_executable("claude --model opus-4.6") == "claude"
    assert resolve_executable("gemini -o text --approval-mode yolo") == "gemini"


def test_detect_provider_status_shape():
    cfg = Config.create_default()
    statuses = detect_provider_status(cfg.providers)

    assert "codex" in statuses
    assert "claude" in statuses
    assert "gemini" in statuses
    assert isinstance(statuses["codex"].available, bool)
    assert statuses["codex"].provider == "codex"
