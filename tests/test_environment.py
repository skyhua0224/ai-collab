"""Tests for local runtime environment detection."""

from pathlib import Path

from ai_collab.core.config import Config
from ai_collab.core.environment import (
    detect_os_name,
    detect_provider_status,
    resolve_executable,
    resolve_subprocess_command,
)


def test_detect_os_name_variants():
    assert detect_os_name("Darwin") == "macos"
    assert detect_os_name("Linux") == "linux"
    assert detect_os_name("Windows") == "windows"
    assert detect_os_name("SomethingElse") == "unknown"


def test_resolve_executable_from_cli():
    assert resolve_executable("codex exec --model gpt-5.4") == "codex"
    assert resolve_executable("claude --model opus-4.6") == "claude"
    assert resolve_executable("gemini -o text --approval-mode yolo") == "gemini"


def test_resolve_subprocess_command_uses_windows_shim(monkeypatch):
    monkeypatch.setattr(
        "ai_collab.core.environment.shutil.which",
        lambda exe: r"C:\Users\me\AppData\Roaming\npm\codex.cmd" if exe == "codex" else None,
    )

    cmd = resolve_subprocess_command(["codex", "exec", "--model", "gpt-5.4"], os_name="windows")

    assert cmd == [r"C:\Users\me\AppData\Roaming\npm\codex.cmd", "exec", "--model", "gpt-5.4"]


def test_resolve_subprocess_command_keeps_non_windows_command(monkeypatch):
    monkeypatch.setattr(
        "ai_collab.core.environment.shutil.which",
        lambda _exe: "/usr/local/bin/codex",
    )

    cmd = resolve_subprocess_command(["codex", "exec"], os_name="Darwin")

    assert cmd == ["codex", "exec"]


def test_detect_provider_status_shape():
    cfg = Config.create_default()
    statuses = detect_provider_status(cfg.providers)

    assert "codex" in statuses
    assert "claude" in statuses
    assert "gemini" in statuses
    assert isinstance(statuses["codex"].available, bool)
    assert statuses["codex"].provider == "codex"


def test_detect_provider_status_reads_codex_model_from_local_config(monkeypatch, tmp_path: Path):
    cfg = Config.create_default()
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")

    monkeypatch.setenv("HOME", str(tmp_path))

    statuses = detect_provider_status(cfg.providers)

    assert statuses["codex"].detected_model == "gpt-5.5"
