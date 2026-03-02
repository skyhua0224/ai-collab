"""Tests for tmux workspace helpers."""

from __future__ import annotations

from pathlib import Path

from ai_collab.core import tmux_workspace


def test_send_pane_text_handles_dash_prefixed_lines(monkeypatch) -> None:
    """Lines that start with '-' must be passed after '--' to avoid tmux flag parsing."""
    calls: list[list[str]] = []

    monkeypatch.setattr(tmux_workspace, "_run_tmux", lambda args: calls.append(args))
    monkeypatch.setattr(tmux_workspace.time, "sleep", lambda _s: None)

    tmux_workspace.send_pane_text(
        pane_id="%1",
        text="- first line\nnormal line",
        delay_seconds=0.0,
    )

    assert calls[0] == ["send-keys", "-t", "%1", "-l", "--", "- first line"]
    assert calls[1] == ["send-keys", "-t", "%1", "C-m"]
    assert calls[2] == ["send-keys", "-t", "%1", "-l", "--", "normal line"]
    assert calls[3] == ["send-keys", "-t", "%1", "C-m"]


def test_paste_pane_text_uses_tmux_buffer(monkeypatch) -> None:
    """Block injection should use tmux buffer + single enter to submit once."""
    calls: list[list[str]] = []

    monkeypatch.setattr(tmux_workspace, "_run_tmux", lambda args: calls.append(args))
    monkeypatch.setattr(tmux_workspace.time, "sleep", lambda _s: None)
    monkeypatch.delenv("AI_COLLAB_BRACKETED_PASTE", raising=False)

    tmux_workspace.paste_pane_text(
        pane_id="%1",
        text="line a\nline b\nline c",
        delay_seconds=0.0,
    )

    assert calls[0][0] == "load-buffer"
    assert calls[1][:3] == ["paste-buffer", "-d", "-b"]
    assert calls[1][-2:] == ["-t", "%1"]
    assert calls[2] == ["send-keys", "-t", "%1", "C-m"]


def test_type_pane_text_sends_characters_then_enter(monkeypatch) -> None:
    """Character typing path should avoid bulk paste and finish with Enter."""
    calls: list[list[str]] = []

    monkeypatch.setattr(tmux_workspace, "_run_tmux", lambda args: calls.append(args))
    monkeypatch.setattr(tmux_workspace.time, "sleep", lambda _s: None)

    tmux_workspace.type_pane_text(
        pane_id="%1",
        text="ab",
        char_delay_seconds=0.0,
        delay_seconds=0.0,
    )

    assert calls[0] == ["send-keys", "-t", "%1", "-l", "--", "a"]
    assert calls[1] == ["send-keys", "-t", "%1", "-l", "--", "b"]
    assert calls[2] == ["send-keys", "-t", "%1", "C-m"]


def test_paste_pane_text_supports_bracketed_mode_via_env(monkeypatch) -> None:
    """Bracketed paste remains available when explicitly enabled by env var."""
    calls: list[list[str]] = []

    monkeypatch.setattr(tmux_workspace, "_run_tmux", lambda args: calls.append(args))
    monkeypatch.setattr(tmux_workspace.time, "sleep", lambda _s: None)
    monkeypatch.setenv("AI_COLLAB_BRACKETED_PASTE", "1")

    tmux_workspace.paste_pane_text(
        pane_id="%1",
        text="line a\nline b\nline c",
        delay_seconds=0.0,
    )

    assert calls[0][0] == "load-buffer"
    assert calls[1][:4] == ["paste-buffer", "-d", "-p", "-b"]
    assert calls[1][-2:] == ["-t", "%1"]
    assert calls[2] == ["send-keys", "-t", "%1", "C-m"]


def test_pane_logs_dir_is_created(tmp_path) -> None:
    """Pane log directory helper should create and return expected path."""
    path = tmux_workspace.pane_logs_dir(cwd=tmp_path, session="ai-collab-live")

    assert path == Path(tmp_path) / ".ai-collab" / "logs" / "ai-collab-live"
    assert path.is_dir()


def test_spawn_subagent_uses_marked_subagent_panes(monkeypatch, tmp_path) -> None:
    """Sub-agent split should track ai-collab pane titles, not all panes in window."""
    tmux_cmds: list[list[str]] = []
    capture_calls: list[list[str]] = []

    def fake_capture(args: list[str]) -> str:
        capture_calls.append(args)
        if args[:3] == ["list-panes", "-t", "%1"]:
            return "\n".join(
                [
                    "%1|ai-collab:controller",
                    "%2|editor-pane",
                    "%3|ai-collab:subagent:gemini",
                ]
            )
        if args and args[0] == "split-window":
            return "%4"
        raise AssertionError(f"unexpected tmux capture args: {args}")

    monkeypatch.setattr(tmux_workspace, "_run_tmux_capture", fake_capture)
    monkeypatch.setattr(tmux_workspace, "_run_tmux", lambda args: tmux_cmds.append(args))
    monkeypatch.setattr(tmux_workspace, "wait_for_pane_quiet", lambda **_kwargs: True)
    monkeypatch.setattr(tmux_workspace, "send_pane_text", lambda **_kwargs: None)
    monkeypatch.setattr(tmux_workspace, "_dispatch_delay_seconds", lambda: 0.0)
    monkeypatch.setattr(tmux_workspace, "_subagent_script", lambda **_kwargs: "echo hi; exec $SHELL")

    pane_id = tmux_workspace.spawn_subagent_pane(
        session="dev-session",
        controller_pane="%1",
        agent="claude",
        cwd=tmp_path,
        task_description="review",
    )

    assert pane_id == "%4"
    split_cmd = next(cmd for cmd in capture_calls if cmd and cmd[0] == "split-window")
    assert split_cmd[split_cmd.index("-t") + 1] == "%3"
    assert "-h" in split_cmd
