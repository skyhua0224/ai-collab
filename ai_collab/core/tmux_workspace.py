"""
Dynamic tmux workspace for controller + sub-agents.

Design:
- Start with only controller pane (full screen)
- Controller dynamically spawns sub-agent panes when needed
- Max 3 sub-agent panes in parallel (bottom half)
- Controller always stays on top
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4
from pathlib import Path
from typing import Optional

AGENTS = ["codex", "claude", "gemini"]
CONTROLLER_PANE_TITLE = "ai-collab:controller"
SUBAGENT_PANE_TITLE_PREFIX = "ai-collab:subagent:"


class TmuxWorkspaceError(RuntimeError):
    """Raised when tmux workspace creation fails."""


def _run_tmux(args: list[str]) -> None:
    subprocess.run(["tmux", *args], check=True)


def _run_tmux_capture(args: list[str]) -> str:
    result = subprocess.run(
        ["tmux", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _session_exists(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _interactive_cmd(agent: str) -> str:
    return {
        "codex": "codex",
        "claude": "claude",
        "gemini": "gemini",
    }.get(agent, agent)


def _interactive_shell() -> str:
    """Return interactive shell executable for pane bootstrap."""
    return os.environ.get("SHELL", "zsh")


def _dispatch_delay_seconds() -> float:
    """Delay before command dispatch to avoid racing shell startup."""
    raw = os.environ.get("AI_COLLAB_PANE_DISPATCH_DELAY_SECONDS", "").strip()
    if not raw:
        return 0.6
    try:
        value = float(raw)
    except ValueError:
        return 0.6
    if value < 0:
        return 0.6
    return min(value, 5.0)


def _dispatch_agent_command(*, pane_id: str, command: str) -> None:
    """
    Method-1 dispatch: open shell pane first, then send command.

    This avoids missing input when provider CLI starts slower than injected text.
    """
    wait_for_pane_quiet(
        pane_id=pane_id,
        timeout_seconds=4.0,
        stable_checks=1,
        poll_interval=0.2,
    )
    send_pane_text(
        pane_id=pane_id,
        text=command,
        press_enter=True,
        delay_seconds=_dispatch_delay_seconds(),
    )


def _set_pane_title(*, pane_id: str, title: str) -> None:
    _run_tmux(["select-pane", "-t", pane_id, "-T", title])


def current_tmux_pane_id() -> str:
    """Return current tmux pane id (for inline mode)."""
    return _run_tmux_capture(["display-message", "-p", "#{pane_id}"])


def current_tmux_session_name(*, pane_id: Optional[str] = None) -> str:
    """Return tmux session name for a pane (or current pane)."""
    args = ["display-message", "-p", "#{session_name}"]
    if pane_id:
        args.extend(["-t", pane_id])
    return _run_tmux_capture(args)


def pane_logs_dir(*, cwd: Path, session: str) -> Path:
    """Return and create the tmux pane log directory for a session."""
    folder = cwd / ".ai-collab" / "logs" / session
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _pane_log_path(*, cwd: Path, session: str, pane_id: str) -> Path:
    safe_pane = pane_id.replace("%", "pane-")
    folder = pane_logs_dir(cwd=cwd, session=session)
    return folder / f"{safe_pane}.log"


def _enable_pane_logging(*, pane_id: str, cwd: Path, session: str) -> None:
    """Stream pane output to log file for audit and replay."""
    log_path = _pane_log_path(cwd=cwd, session=session, pane_id=pane_id)
    command = f"cat >> {shlex.quote(str(log_path))}"
    _run_tmux(["pipe-pane", "-o", "-t", pane_id, command])


def create_controller_workspace(
    *,
    session: str,
    cwd: Path,
    controller: str,
    reset: bool = False,
    autorun: bool = True,
) -> str:
    """
    Create a tmux workspace with only the controller pane.

    Returns the controller pane ID.
    """
    if shutil.which("tmux") is None:
        raise TmuxWorkspaceError("tmux not found in PATH")

    if controller not in AGENTS:
        raise TmuxWorkspaceError(f"unsupported controller: {controller}")

    if _session_exists(session):
        if not reset:
            raise TmuxWorkspaceError(
                f"session '{session}' already exists. Use reset=True or choose another session"
            )
        _run_tmux(["kill-session", "-t", session])

    cwd = cwd.resolve()

    # Create session and controller pane.
    controller_pane = _run_tmux_capture(
        [
            "new-session",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            "-s",
            session,
            "-c",
            str(cwd),
            "-n",
            "ai-collab",
            _interactive_shell(),
        ]
    )

    # Enable mouse support.
    _run_tmux(["set", "-t", session, "mouse", "on"])

    # Configure controller pane.
    _enable_pane_logging(
        pane_id=controller_pane,
        cwd=cwd,
        session=session,
    )
    _set_pane_title(pane_id=controller_pane, title=CONTROLLER_PANE_TITLE)
    if autorun:
        _dispatch_agent_command(
            pane_id=controller_pane,
            command=_controller_script(
                agent=controller,
                cwd=cwd,
                autorun=True,
            ),
        )
    return controller_pane


def create_inline_controller_workspace(
    *,
    cwd: Path,
    controller: str,
    parent_pane: Optional[str] = None,
    autorun: bool = True,
    split_percent: int = 45,
) -> tuple[str, str]:
    """
    Create controller pane inline inside current tmux window.

    Returns tuple: (session_name, controller_pane_id).
    """
    if shutil.which("tmux") is None:
        raise TmuxWorkspaceError("tmux not found in PATH")

    if controller not in AGENTS:
        raise TmuxWorkspaceError(f"unsupported controller: {controller}")

    anchor = parent_pane or current_tmux_pane_id()
    session = current_tmux_session_name(pane_id=anchor)
    pct = min(max(split_percent, 20), 80)
    cwd = cwd.resolve()

    controller_pane = _run_tmux_capture(
        [
            "split-window",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            anchor,
            "-v",
            "-p",
            str(pct),
            "-c",
            str(cwd),
            _interactive_shell(),
        ]
    )

    _enable_pane_logging(
        pane_id=controller_pane,
        cwd=cwd,
        session=session,
    )
    _set_pane_title(pane_id=controller_pane, title=CONTROLLER_PANE_TITLE)
    if autorun:
        _dispatch_agent_command(
            pane_id=controller_pane,
            command=_controller_script(
                agent=controller,
                cwd=cwd,
                autorun=True,
            ),
        )
    return session, controller_pane


def _controller_script(*, agent: str, cwd: Path, autorun: bool) -> str:
    """Generate startup command for controller pane."""
    base = "export AI_COLLAB_ACTIVE=1; export AI_COLLAB_ROLE=controller"

    if autorun:
        cmd = _interactive_cmd(agent)
        return (
            f"{base}; "
            f"if command -v {shlex.quote(cmd)} >/dev/null 2>&1; then "
            f"{cmd}; "
            "else "
            f"echo 'Command not found: {cmd}'; "
            "fi"
        )
    return base


def spawn_subagent_pane(
    *,
    session: str,
    controller_pane: str,
    agent: str,
    cwd: Path,
    task_description: str = "",
) -> str:
    """
    Spawn a sub-agent pane below the controller.

    Returns the new pane ID.
    """
    if agent not in AGENTS:
        raise TmuxWorkspaceError(f"unsupported agent: {agent}")

    panes_output = _run_tmux_capture(
        [
            "list-panes",
            "-t",
            controller_pane,
            "-F",
            "#{pane_id}|#{pane_title}",
        ]
    )
    rows = [line for line in panes_output.strip().split("\n") if line]
    subagent_panes: list[str] = []
    for line in rows:
        pane_id, pane_title = (line.split("|", 1) + [""])[:2]
        if pane_title.startswith(SUBAGENT_PANE_TITLE_PREFIX):
            subagent_panes.append(pane_id)

    if len(subagent_panes) >= 3:
        raise TmuxWorkspaceError("Maximum 3 sub-agent panes reached")

    if not subagent_panes:
        target_pane = controller_pane
        split_args = ["-v", "-p", "50"]
    else:
        target_pane = subagent_panes[-1]
        split_args = ["-h", "-p", "50"]

    new_pane = _run_tmux_capture(
        [
            "split-window",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            target_pane,
            *split_args,
            "-c",
            str(cwd),
            _interactive_shell(),
        ]
    )

    # Configure sub-agent pane.
    _enable_pane_logging(
        pane_id=new_pane,
        cwd=cwd,
        session=session,
    )
    _set_pane_title(
        pane_id=new_pane,
        title=f"{SUBAGENT_PANE_TITLE_PREFIX}{agent}",
    )
    _dispatch_agent_command(
        pane_id=new_pane,
        command=_subagent_script(
            agent=agent,
            cwd=cwd,
            task_description=task_description,
        ),
    )
    return new_pane


def _subagent_script(*, agent: str, cwd: Path, task_description: str) -> str:
    """Generate startup command for sub-agent pane."""
    cmd = _interactive_cmd(agent)
    return (
        f"export AI_COLLAB_ACTIVE=1; export AI_COLLAB_ROLE=subagent; export AI_COLLAB_TASK={shlex.quote(task_description)}; "
        f"if command -v {shlex.quote(cmd)} >/dev/null 2>&1; then "
        f"{cmd}; "
        "else "
        f"echo 'Command not found: {cmd}'; "
        "fi"
    )


def close_subagent_pane(*, pane_id: str) -> None:
    """Close a sub-agent pane."""
    _run_tmux(["kill-pane", "-t", pane_id])


def send_pane_text(*, pane_id: str, text: str, press_enter: bool = True, delay_seconds: float = 0.0) -> None:
    """
    Send text to a pane as literal key presses.

    Use small delay when an interactive CLI needs time to initialize.
    """
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    if text:
        for line in text.splitlines():
            _run_tmux(["send-keys", "-t", pane_id, "-l", "--", line])
            _run_tmux(["send-keys", "-t", pane_id, "C-m"])
        if text.endswith("\n"):
            _run_tmux(["send-keys", "-t", pane_id, "C-m"])
    elif press_enter:
        _run_tmux(["send-keys", "-t", pane_id, "C-m"])


def type_pane_text(
    *,
    pane_id: str,
    text: str,
    press_enter: bool = True,
    char_delay_seconds: float = 0.015,
    delay_seconds: float = 0.0,
) -> None:
    """
    Type text into a pane character-by-character.

    Useful for interactive chat CLIs that treat instant line injection as pasted text.
    """
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    if text:
        delay = max(0.0, char_delay_seconds)
        for char in text:
            if char == "\n":
                _run_tmux(["send-keys", "-t", pane_id, "C-m"])
            else:
                _run_tmux(["send-keys", "-t", pane_id, "-l", "--", char])
            if delay > 0:
                time.sleep(delay)
        if press_enter:
            _run_tmux(["send-keys", "-t", pane_id, "C-m"])
    elif press_enter:
        _run_tmux(["send-keys", "-t", pane_id, "C-m"])


def paste_pane_text(*, pane_id: str, text: str, press_enter: bool = True, delay_seconds: float = 0.0) -> None:
    """
    Send text to a pane as one block using tmux paste-buffer.

    Useful for chat UIs where line-by-line Enter can submit partial prompts.
    """
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    if not text:
        if press_enter:
            _run_tmux(["send-keys", "-t", pane_id, "C-m"])
        return

    buffer_name = f"ai-collab-{uuid4().hex}"
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(text)
            temp_path = handle.name
        _run_tmux(["load-buffer", "-b", buffer_name, temp_path])
        paste_args = ["paste-buffer", "-d", "-b", buffer_name, "-t", pane_id]
        bracketed = os.environ.get("AI_COLLAB_BRACKETED_PASTE", "").strip().lower()
        if bracketed in {"1", "true", "yes", "on"}:
            paste_args.insert(2, "-p")
        _run_tmux(paste_args)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

    if press_enter:
        _run_tmux(["send-keys", "-t", pane_id, "C-m"])


def capture_pane_text(*, pane_id: str, start_line: int = -200) -> str:
    """Capture pane text for readiness checks and debugging."""
    return _run_tmux_capture(["capture-pane", "-p", "-S", str(start_line), "-t", pane_id])


def wait_for_pane_quiet(
    *,
    pane_id: str,
    timeout_seconds: float = 15.0,
    stable_checks: int = 3,
    poll_interval: float = 0.4,
) -> bool:
    """
    Wait until pane output stops changing for a few polls.

    This reduces race conditions when injecting prompts into interactive CLIs.
    """
    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    last_tail = ""
    stable = 0
    error_count = 0
    while time.monotonic() < deadline:
        try:
            snapshot = capture_pane_text(pane_id=pane_id, start_line=-200)
        except subprocess.CalledProcessError:
            error_count += 1
            if error_count >= 3:
                return False
            time.sleep(poll_interval)
            continue
        error_count = 0
        tail = snapshot[-1200:]
        if tail and tail == last_tail:
            stable += 1
            if stable >= max(stable_checks, 1):
                return True
        else:
            stable = 0
            last_tail = tail
        time.sleep(poll_interval)
    return False


def list_panes(*, session: str) -> list[dict[str, str]]:
    """
    List all panes in a session.

    Returns list of dicts with keys: pane_id, pane_index, pane_width, pane_height
    """
    output = _run_tmux_capture(
        [
            "list-panes",
            "-t",
            session,
            "-F",
            "#{pane_id}|#{pane_index}|#{pane_width}|#{pane_height}",
        ]
    )

    panes = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        pane_id, pane_index, pane_width, pane_height = line.split("|")
        panes.append({
            "pane_id": pane_id,
            "pane_index": pane_index,
            "pane_width": pane_width,
            "pane_height": pane_height,
        })

    return panes


def attach_session(*, session: str) -> None:
    """Attach to a tmux session."""
    subprocess.run(["tmux", "attach-session", "-t", session])


# Legacy compatibility wrapper.
def create_tmux_workspace(
    *,
    session: str,
    cwd: Path,
    controller: str,
    layout: str = "dynamic",
    autorun_agents: bool = True,
    reset: bool = False,
    task_hint: str = "",
) -> None:
    """
    Create a tmux workspace (legacy interface).

    Now only creates controller pane. Sub-agents are spawned dynamically.
    """
    controller_pane = create_controller_workspace(
        session=session,
        cwd=cwd,
        controller=controller,
        reset=reset,
        autorun=True,
    )

    # Store controller pane ID on the tmux session.
    _run_tmux(["set", "-t", session, "@controller_pane", controller_pane])
