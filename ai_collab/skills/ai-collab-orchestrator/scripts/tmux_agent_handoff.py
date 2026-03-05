#!/usr/bin/env python3
"""One-click tmux agent handoff launcher.

Flow:
1) Reuse current tmux session (or explicit session)
2) Create a new visible window
3) Wait for shell ready
4) cd to repository root
5) launch agent (claude/gemini/codex/custom)
6) wait for agent startup
7) paste prompt text and send Enter
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


KNOWN_SHELLS = {"zsh", "bash", "sh", "fish", "pwsh", "powershell", "nu"}
STARTUP_PATTERNS = {
    "gemini": re.compile(
        r"Type your message(?:\s+or\s+@path/to/file)?|"
        r"Logged in with Google|"
        r"/model(?:\s+Auto)?|"
        r"shift\+tab to accept edits",
        re.IGNORECASE,
    ),
    "claude": re.compile(r"Claude Code|/model|ctrl\+t|Try \"", re.IGNORECASE),
    "codex": re.compile(r"%\s+left|@filename|OpenAI Codex", re.IGNORECASE),
}
COMPLETION_MARKER_PATTERN = re.compile(r"(?mi)^\s*===\s*(?:SUBAGENT_COMPLETE|TASK_COMPLETE)\s*===\s*$")
COMPLETION_EVENT_PATTERN = re.compile(
    r'(?mi)AI_COLLAB_EVENT\s*:?\s*\{[^\n]*"type"\s*:\s*"(?:subagent_complete|task_complete)"[^\n]*\}'
)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\].*?\x1b\\")


class TmuxError(RuntimeError):
    pass


@dataclass
class CmdResult:
    code: int
    out: str
    err: str


@dataclass
class PaneInfo:
    pane_id: str
    left: int
    top: int
    width: int
    height: int


def run_cmd(cmd: list[str], stdin: str | None = None, check: bool = True) -> CmdResult:
    proc = subprocess.run(
        cmd,
        input=stdin,
        text=True,
        capture_output=True,
    )
    res = CmdResult(proc.returncode, proc.stdout, proc.stderr)
    if check and proc.returncode != 0:
        raise TmuxError(f"Command failed: {' '.join(cmd)}\n{res.err.strip()}")
    return res


def tmux(args: list[str], stdin: str | None = None, check: bool = True) -> CmdResult:
    return run_cmd(["tmux", *args], stdin=stdin, check=check)


def _fallback_attached_session() -> str | None:
    sessions = tmux(["list-sessions", "-F", "#{session_name}\t#{session_attached}"], check=False)
    if sessions.code != 0:
        return None
    attached: list[str] = []
    all_names: list[str] = []
    for line in sessions.out.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        name = parts[0].strip()
        all_names.append(name)
        if len(parts) > 1 and parts[1].strip() == "1":
            attached.append(name)
    if attached:
        return attached[0]
    if all_names:
        return all_names[0]
    return None


def detect_session(explicit: str | None) -> str:
    if explicit:
        return explicit

    current = tmux(["display-message", "-p", "#S"], check=False)
    if current.code == 0 and current.out.strip():
        return current.out.strip()

    fallback = _fallback_attached_session()
    if fallback:
        return fallback
    raise TmuxError("No tmux session detected. Pass --session explicitly.")


def detect_current_pane() -> str | None:
    current = tmux(["display-message", "-p", "#{pane_id}"], check=False)
    if current.code == 0 and current.out.strip():
        return current.out.strip()
    session = _fallback_attached_session()
    if not session:
        return None
    panes = tmux(
        [
            "list-panes",
            "-t",
            session,
            "-F",
            "#{pane_id}\t#{pane_active}",
        ],
        check=False,
    )
    if panes.code != 0:
        return None
    first_pane = ""
    for line in panes.out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        pane_id, active = parts[0].strip(), parts[1].strip()
        if not first_pane and pane_id:
            first_pane = pane_id
        if pane_id and active == "1":
            return pane_id
    return first_pane or None


def pane_window_id(pane_id: str) -> str:
    out = tmux(["display-message", "-p", "-t", pane_id, "#{window_id}"]).out.strip()
    if not out:
        raise TmuxError(f"Unable to resolve window for pane {pane_id}")
    return out


def list_panes(window_id: str) -> list[PaneInfo]:
    result = tmux(["list-panes", "-t", window_id, "-F", "#{pane_id}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}"])
    panes: list[PaneInfo] = []
    for line in result.out.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        pane_id, left, top, width, height = parts
        try:
            panes.append(PaneInfo(pane_id=pane_id, left=int(left), top=int(top), width=int(width), height=int(height)))
        except ValueError:
            continue
    if not panes:
        raise TmuxError(f"No panes found in window {window_id}")
    return panes


def get_window_option(window_id: str, option: str) -> str | None:
    result = tmux(["show-options", "-w", "-t", window_id, "-v", option], check=False)
    if result.code != 0:
        return None
    value = result.out.strip()
    return value or None


def set_window_option(window_id: str, option: str, value: str) -> None:
    tmux(["set-option", "-w", "-t", window_id, option, value])


def split_with_controller_bottom_policy(
    *,
    session: str,
    shell: str,
    split_target_pane: str | None,
    controller_pane_arg: str | None,
    controller_height_percent: int,
) -> tuple[CmdResult, str]:
    current_pane = detect_current_pane()
    base_pane = controller_pane_arg or split_target_pane or current_pane
    if not base_pane:
        raise TmuxError("Split policy 'controller-bottom' requires current pane context or --controller-pane/--split-target-pane.")

    window_id = pane_window_id(base_pane)
    configured = get_window_option(window_id, "@ai_collab_controller_pane")
    panes = list_panes(window_id)
    pane_ids = {p.pane_id for p in panes}

    controller_pane = controller_pane_arg or configured or base_pane
    if controller_pane not in pane_ids:
        controller_pane = base_pane
    set_window_option(window_id, "@ai_collab_controller_pane", controller_pane)

    subagents = [p for p in panes if p.pane_id != controller_pane]
    if not subagents:
        created = tmux([
            "split-window",
            "-v",
            "-p",
            str(max(10, min(90, 100 - controller_height_percent))),
            "-P",
            "-F",
            "#{window_id}\t#{pane_id}",
            "-t",
            controller_pane,
            shell,
        ])
    else:
        # Keep expanding from the right-most bottom pane, then rebalance all bottom panes.
        target = sorted(subagents, key=lambda p: (p.left, p.width))[-1].pane_id
        created = tmux([
            "split-window",
            "-h",
            "-p",
            "50",
            "-P",
            "-F",
            "#{window_id}\t#{pane_id}",
            "-t",
            target,
            shell,
        ])

    tmux(["select-pane", "-t", controller_pane], check=False)
    set_window_option(window_id, "main-pane-height", f"{max(20, min(80, controller_height_percent))}%")
    tmux(["select-layout", "-t", window_id, "main-horizontal"], check=False)
    return created, controller_pane


def detect_repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    cwd = Path.cwd()
    git_root = run_cmd(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], check=False)
    if git_root.code == 0 and git_root.out.strip():
        return Path(git_root.out.strip()).resolve()
    return cwd.resolve()


def choose_shell(explicit: str | None) -> str:
    if explicit:
        return explicit
    if platform.system() == "Windows":
        return "pwsh"
    return os.path.basename(os.environ.get("SHELL", "zsh")) or "zsh"


def command_basename(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.strip().split()
    if not parts:
        return ""
    return os.path.basename(parts[0]).lower()


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def cd_command(shell: str, repo_root: Path) -> str:
    lower = shell.lower()
    if lower.startswith("pwsh") or lower.startswith("powershell"):
        return f"Set-Location -Path {ps_quote(str(repo_root))}"
    return f"cd {shlex.quote(str(repo_root))}"


def pane_current_command(pane_id: str) -> str:
    return tmux(["display-message", "-p", "-t", pane_id, "#{pane_current_command}"]).out.strip().lower()


def capture_pane(pane_id: str, lines: int = 120) -> str:
    return tmux(["capture-pane", "-p", "-J", "-t", pane_id, "-S", f"-{lines}"]).out


def normalize_terminal_text(text: str) -> str:
    normalized = text.replace("\r", "\n")
    return ANSI_ESCAPE_RE.sub("", normalized)


def completion_seen(text: str) -> bool:
    normalized = normalize_terminal_text(text)
    if COMPLETION_MARKER_PATTERN.search(normalized):
        return True
    if COMPLETION_EVENT_PATTERN.search(normalized):
        return True
    return False


def completion_counts(text: str) -> tuple[int, int]:
    """Return (legacy_marker_count, structured_event_count) for completion signals."""
    normalized = normalize_terminal_text(text)
    marker_count = len(COMPLETION_MARKER_PATTERN.findall(normalized))
    event_count = len(COMPLETION_EVENT_PATTERN.findall(normalized))
    return marker_count, event_count


def wait_until(predicate, timeout: float, interval: float = 0.25, desc: str = "condition") -> None:
    start = time.time()
    while True:
        if predicate():
            return
        if time.time() - start > timeout:
            raise TmuxError(f"Timeout waiting for {desc} ({timeout}s)")
        time.sleep(interval)


def wait_for_pane_idle(
    pane_id: str,
    timeout: float,
    quiet_for: float,
    capture_lines: int,
    interval: float = 0.2,
) -> None:
    start = time.time()
    last = capture_pane(pane_id, capture_lines)
    last_change = start
    while True:
        now = time.time()
        if now - start > timeout:
            raise TmuxError(f"Timeout waiting for pane idle ({timeout}s)")
        cur = capture_pane(pane_id, capture_lines)
        if cur != last:
            last = cur
            last_change = now
        elif now - last_change >= quiet_for:
            return
        time.sleep(interval)


def wait_for_shell_input_ready(
    *,
    pane_id: str,
    shell_cmd_names: set[str],
    timeout: float,
    capture_lines: int,
) -> None:
    """
    Verify shell input loop is alive without injecting command text.

    Strategy:
    - Press Enter
    - Require pane output change while current command remains a shell
    """
    deadline = time.time() + max(timeout, 1.0)
    attempts = 0
    while time.time() < deadline and attempts < 4:
        attempts += 1
        before = normalize_terminal_text(capture_pane(pane_id, capture_lines))
        send_enter(pane_id)

        def _seen() -> bool:
            out = normalize_terminal_text(capture_pane(pane_id, capture_lines))
            cmd = pane_current_command(pane_id)
            return out != before and cmd in shell_cmd_names

        remaining = max(0.6, min(2.2, deadline - time.time()))
        try:
            wait_until(_seen, timeout=remaining, interval=0.2, desc="shell input-ready enter")
            return
        except TmuxError:
            time.sleep(0.25)
            continue
    raise TmuxError("Timeout waiting for shell input-ready enter")


def wait_for_agent_ready(
    pane_id: str,
    expected_cmd: str,
    startup_pattern: re.Pattern[str] | None,
    shell_cmd_names: set[str],
    timeout: float,
    capture_lines: int,
    idle_quiet_for: float,
    min_runtime: float,
) -> None:
    start = time.time()
    last = capture_pane(pane_id, capture_lines)
    last_change = start
    while True:
        now = time.time()
        if now - start > timeout:
            raise TmuxError(f"Timeout waiting for agent startup ({timeout}s)")
        out = capture_pane(pane_id, capture_lines)
        if out != last:
            last = out
            last_change = now
        cmd = pane_current_command(pane_id)
        pattern_hit = bool(startup_pattern.search(out)) if startup_pattern else False
        process_running = bool(expected_cmd) and expected_cmd in cmd
        idle = (now - last_change) >= idle_quiet_for

        if pattern_hit:
            return
        if process_running and idle and (now - start) >= min_runtime:
            return
        # Some interactive CLIs (notably Gemini in terminal UI mode) still report shell
        # as pane_current_command while their UI is fully active. Avoid premature failure.
        time.sleep(0.2)


def send_literal(pane_id: str, text: str) -> None:
    if not text:
        return
    sent = tmux(["send-keys", "-t", pane_id, "-l", text], check=False)
    if sent.code == 0:
        return
    # Fallback for panes/clients where send-keys -l is rejected in transient UI modes.
    buffer_name = f"handoff-literal-{int(time.time() * 1000)}"
    tmux(["load-buffer", "-b", buffer_name, "-"], stdin=text)
    paste = tmux(["paste-buffer", "-t", pane_id, "-b", buffer_name], check=False)
    tmux(["delete-buffer", "-b", buffer_name], check=False)
    if paste.code != 0:
        raise TmuxError(f"Failed to inject text into pane {pane_id}: {sent.err.strip() or paste.err.strip()}")


def send_enter(pane_id: str) -> None:
    tmux(["send-keys", "-t", pane_id, "C-m"])


def send_controller_notice(controller_pane: str | None, message: str, mode: str) -> None:
    if not controller_pane or mode == "none":
        return
    if mode in {"status", "both"}:
        tmux(["display-message", "-t", controller_pane, message], check=False)
    if mode in {"input", "both"}:
        send_literal(controller_pane, message)
        send_enter(controller_pane)
        # Some interactive UIs need a second Enter to actually submit.
        time.sleep(0.12)
        send_enter(controller_pane)


def wait_for_completion(
    *,
    pane_id: str,
    timeout_seconds: float,
    poll_interval: float,
    capture_lines: int,
) -> str:
    start = time.time()
    seeded = False
    last_tail = ""
    seen_markers = 0
    seen_events = 0
    while True:
        if timeout_seconds > 0 and time.time() - start >= timeout_seconds:
            return "timeout"
        snapshot_result = tmux(
            ["capture-pane", "-p", "-J", "-t", pane_id, "-S", f"-{max(120, capture_lines)}"],
            check=False,
        )
        if snapshot_result.code != 0:
            return "pane_unavailable"
        tail = snapshot_result.out[-12000:]
        if not seeded:
            seeded = True
            last_tail = tail
            seen_markers, seen_events = completion_counts(tail)
            time.sleep(poll_interval)
            continue
        if tail.startswith(last_tail):
            delta = tail[len(last_tail) :]
            if completion_seen(delta):
                return "completed"
        else:
            delta = tail
            cur_markers, cur_events = completion_counts(tail)
            if cur_markers > seen_markers or cur_events > seen_events:
                return "completed"
            seen_markers = max(seen_markers, cur_markers)
            seen_events = max(seen_events, cur_events)
        last_tail = tail
        time.sleep(poll_interval)


def spawn_completion_watcher(
    *,
    script_path: Path,
    pane_id: str,
    controller_pane: str | None,
    agent: str,
    completion_action: str,
    completion_timeout: float,
    completion_poll: float,
    capture_lines: int,
    notify_mode: str,
) -> None:
    cmd = [
        sys.executable,
        str(script_path),
        "--watch-mode",
        "--watch-pane-id",
        pane_id,
        "--watch-agent",
        agent,
        "--completion-action",
        completion_action,
        "--completion-timeout",
        str(max(0.0, completion_timeout)),
        "--completion-poll",
        str(max(0.2, completion_poll)),
        "--capture-lines",
        str(max(120, capture_lines)),
        "--completion-notify-mode",
        notify_mode,
    ]
    if controller_pane:
        cmd.extend(["--watch-controller-pane", controller_pane])
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def send_text_and_enter(
    pane_id: str,
    text: str,
    enter_delay: float = 0.0,
    chunk_size: int = 0,
    chunk_delay: float = 0.0,
) -> None:
    if chunk_size > 0:
        type_in_chunks(pane_id, text, chunk_size=chunk_size, chunk_delay=chunk_delay)
    else:
        send_literal(pane_id, text)
    if enter_delay > 0:
        time.sleep(enter_delay)
    send_enter(pane_id)


def type_in_chunks(pane_id: str, text: str, chunk_size: int, chunk_delay: float) -> None:
    if chunk_size <= 0:
        send_literal(pane_id, text)
        return
    for idx in range(0, len(text), chunk_size):
        send_literal(pane_id, text[idx : idx + chunk_size])
        if chunk_delay > 0:
            time.sleep(chunk_delay)


def normalized_probe(text: str, length: int = 20) -> str:
    compact = "".join(text.split())
    return compact[:length]


def pane_contains_probe(pane_id: str, probe: str, capture_lines: int) -> bool:
    if not probe:
        return True
    out = capture_pane(pane_id, capture_lines)
    compact = "".join(out.split())
    return probe in compact


def inject_prompt(
    pane_id: str,
    prompt_text: str,
    mode: str,
    chunk_size: int,
    chunk_delay: float,
) -> None:
    if mode == "type":
        if chunk_size > 0:
            type_in_chunks(pane_id, prompt_text, chunk_size=chunk_size, chunk_delay=chunk_delay)
        else:
            send_literal(pane_id, prompt_text)
        return
    tmux(["load-buffer", "-b", "agent-prompt", "-"], stdin=prompt_text)
    tmux(["paste-buffer", "-t", pane_id, "-b", "agent-prompt"])
    tmux(["delete-buffer", "-b", "agent-prompt"], check=False)


def make_agent_command(agent: str, agent_cmd: str | None, model: str | None) -> str:
    if agent_cmd:
        return agent_cmd
    if agent == "gemini" and model:
        return f"gemini --model {shlex.quote(model)}"
    return agent


def load_prompt(args: argparse.Namespace) -> str | None:
    if args.no_prompt:
        return None
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="One-click tmux agent launcher + prompt handoff")
    parser.add_argument("--agent", choices=["claude", "gemini", "codex"])
    parser.add_argument("--agent-cmd", help="Override launch command, e.g. 'gemini --model gemini-3.1-pro-preview'")
    parser.add_argument("--model", help="Model for gemini when --agent-cmd is not provided")
    parser.add_argument("--session", help="tmux session name; default auto-detect current/attached session")
    parser.add_argument("--window-name", help="tmux window name")
    parser.add_argument("--tmux-layout", choices=["window", "split"], default="window", help="launch in a new tmux window or split pane")
    parser.add_argument("--split-policy", choices=["manual", "controller-bottom"], default="manual", help="split placement policy")
    parser.add_argument("--split-direction", choices=["vertical", "horizontal"], default="vertical", help="split direction when --tmux-layout split")
    parser.add_argument("--split-percent", type=int, default=35, help="size percent for new split pane")
    parser.add_argument("--split-target-pane", help="target pane id to split from (default current/active pane)")
    parser.add_argument("--controller-pane", help="controller pane id for controller-bottom policy")
    parser.add_argument("--controller-height-percent", type=int, default=50, help="controller top-pane height in percent for controller-bottom policy")
    parser.add_argument("--shell", help="shell command to start in new window (default zsh/pwsh)")
    parser.add_argument("--repo-root", help="repository root to cd into before launching agent")
    parser.add_argument("--prompt-file", help="text file sent to agent after startup")
    parser.add_argument("--prompt", help="inline prompt text sent to agent after startup")
    parser.add_argument("--no-prompt", action="store_true", help="launch agent only, do not send prompt")
    parser.add_argument("--wait-shell-timeout", type=float, default=20.0)
    parser.add_argument("--wait-agent-timeout", type=float, default=90.0)
    parser.add_argument("--wait-exec-timeout", type=float, default=30.0)
    parser.add_argument("--exec-pattern", help="regex pattern considered as execution signal after Enter")
    parser.add_argument("--startup-pattern", help="override startup ready regex for the selected agent")
    parser.add_argument("--capture-lines", type=int, default=120)
    parser.add_argument("--shell-settle-delay", type=float, default=1.5, help="extra delay after shell process detected")
    parser.add_argument("--shell-idle-timeout", type=float, default=20.0, help="max time waiting for shell pane to become idle")
    parser.add_argument("--shell-idle-quiet-for", type=float, default=1.2, help="required quiet duration before first command")
    parser.add_argument("--shell-probe-timeout", type=float, default=12.0, help="max seconds waiting for shell probe echo")
    parser.add_argument("--agent-idle-quiet-for", type=float, default=1.2, help="quiet duration used for fallback agent-ready detection")
    parser.add_argument("--agent-min-runtime", type=float, default=1.5, help="minimum seconds before fallback agent-ready can pass")
    parser.add_argument("--post-agent-ready-delay", type=float, default=1.2, help="extra delay after startup prompt appears")
    parser.add_argument("--enter-delay", type=float, default=0.4, help="delay in seconds between prompt paste and Enter")
    parser.add_argument("--prompt-mode", choices=["auto", "paste", "type"], default="auto", help="prompt injection mode")
    parser.add_argument("--prompt-echo-timeout", type=float, default=2.0, help="max seconds waiting prompt text to appear before Enter")
    parser.add_argument("--cmd-chunk-size", type=int, default=0, help="command typing chunk size (0 for one-shot)")
    parser.add_argument("--cmd-chunk-delay", type=float, default=0.05, help="delay in seconds between command chunks")
    parser.add_argument("--chunk-size", type=int, default=0, help="prompt typing chunk size (0 for one-shot)")
    parser.add_argument("--chunk-delay", type=float, default=0.12, help="delay in seconds between prompt chunks")
    parser.add_argument(
        "--completion-action",
        choices=["none", "ask", "keep", "close"],
        default="ask",
        help="post-completion pane policy: ask user, keep pane, or auto-close pane",
    )
    parser.add_argument(
        "--completion-timeout",
        type=float,
        default=21600.0,
        help="completion watcher timeout seconds (0 means no timeout)",
    )
    parser.add_argument(
        "--completion-poll",
        type=float,
        default=1.0,
        help="completion watcher polling interval seconds",
    )
    parser.add_argument(
        "--completion-notify-mode",
        choices=["status", "input", "both", "none"],
        default="input",
        help="how completion watcher notifies controller pane",
    )
    parser.add_argument("--watch-mode", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--watch-pane-id", help=argparse.SUPPRESS)
    parser.add_argument("--watch-controller-pane", help=argparse.SUPPRESS)
    parser.add_argument("--watch-agent", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help="print step-by-step progress logs")

    args = parser.parse_args()

    def log_step(name: str) -> None:
        if args.verbose:
            print(f"STEP={name}", flush=True)

    if args.watch_mode:
        if not args.watch_pane_id:
            print("STATUS=ERROR\nERROR=watch mode requires --watch-pane-id", file=sys.stderr)
            return 1
        watched_agent = args.watch_agent or "sub-agent"
        result = wait_for_completion(
            pane_id=args.watch_pane_id,
            timeout_seconds=max(0.0, args.completion_timeout),
            poll_interval=max(0.2, args.completion_poll),
            capture_lines=max(120, args.capture_lines),
        )
        controller_pane = (args.watch_controller_pane or "").strip() or None
        notify_mode = args.completion_notify_mode

        if result == "completed":
            if args.completion_action == "close":
                tmux(["kill-pane", "-t", args.watch_pane_id], check=False)
                send_controller_notice(
                    controller_pane,
                    f"[ai-collab control] Sub-agent {watched_agent} completed and pane {args.watch_pane_id} was auto-closed.",
                    notify_mode,
                )
            elif args.completion_action == "keep":
                send_controller_notice(
                    controller_pane,
                    f"[ai-collab control] Sub-agent {watched_agent} completed. Pane {args.watch_pane_id} is kept open.",
                    notify_mode,
                )
            elif args.completion_action == "ask":
                send_controller_notice(
                    controller_pane,
                    f"[ai-collab control] Sub-agent {watched_agent} (pane {args.watch_pane_id}) completed. Ask user now: close this pane? (yes/no), then continue.",
                    "status" if notify_mode == "none" else notify_mode,
                )
            return 0

        send_controller_notice(
            controller_pane,
            f"[ai-collab control] Completion watcher ended for {watched_agent} pane {args.watch_pane_id}: {result}.",
            "status" if notify_mode == "none" else notify_mode,
        )
        return 1

    try:
        if not args.agent:
            raise TmuxError("--agent is required unless --watch-mode is enabled")
        session = detect_session(args.session)
        repo_root = detect_repo_root(args.repo_root)
        shell = choose_shell(args.shell)
        expected_shell_cmd = command_basename(shell)
        prompt_text = load_prompt(args)
        agent_cmd = make_agent_command(args.agent, args.agent_cmd, args.model)
        window_name = args.window_name or f"{args.agent}-handoff"
        split_percent = max(10, min(90, int(args.split_percent)))
        origin_pane = detect_current_pane()
        inferred_controller_pane = args.controller_pane or args.split_target_pane or origin_pane

        if args.tmux_layout == "window":
            created = tmux([
                "new-window",
                "-P",
                "-F",
                "#{window_id}\t#{pane_id}",
                "-t",
                f"{session}:",
                "-n",
                window_name,
                shell,
            ])
        else:
            if args.split_policy == "controller-bottom":
                created, controller_pane = split_with_controller_bottom_policy(
                    session=session,
                    shell=shell,
                    split_target_pane=args.split_target_pane,
                    controller_pane_arg=args.controller_pane,
                    controller_height_percent=args.controller_height_percent,
                )
                inferred_controller_pane = controller_pane
            else:
                split_flag = "-v" if args.split_direction == "vertical" else "-h"
                target_pane = args.split_target_pane or detect_current_pane()
                if not target_pane:
                    raise TmuxError("Split mode requires current tmux pane context or explicit --split-target-pane.")
                created = tmux([
                    "split-window",
                    split_flag,
                    "-p",
                    str(split_percent),
                    "-P",
                    "-F",
                    "#{window_id}\t#{pane_id}",
                    "-t",
                    target_pane,
                    shell,
                ])
                inferred_controller_pane = args.controller_pane or target_pane
        parts = created.out.strip().split("\t")
        if len(parts) != 2:
            raise TmuxError(f"Unexpected tmux new-window output: {created.out!r}")
        window_id, pane_id = parts
        tmux(["select-window", "-t", window_id], check=False)
        tmux(["select-pane", "-t", pane_id], check=False)
        log_step(f"WINDOW_CREATED {window_id} {pane_id}")

        wait_until(
            lambda: bool(pane_current_command(pane_id)),
            timeout=args.wait_shell_timeout,
            desc="shell ready",
        )
        actual_shell_cmd = pane_current_command(pane_id)
        shell_cmd_names = set(KNOWN_SHELLS)
        if expected_shell_cmd:
            shell_cmd_names.add(expected_shell_cmd)
        if actual_shell_cmd:
            shell_cmd_names.add(actual_shell_cmd)
        if args.shell_settle_delay > 0:
            time.sleep(args.shell_settle_delay)
        wait_for_pane_idle(
            pane_id,
            timeout=args.shell_idle_timeout,
            quiet_for=args.shell_idle_quiet_for,
            capture_lines=args.capture_lines,
        )
        log_step("SHELL_PROCESS_READY")

        wait_for_shell_input_ready(
            pane_id=pane_id,
            shell_cmd_names=shell_cmd_names,
            timeout=max(1.0, args.shell_probe_timeout),
            capture_lines=args.capture_lines,
        )
        wait_for_pane_idle(
            pane_id,
            timeout=max(2.0, args.shell_idle_timeout),
            quiet_for=max(0.6, min(args.shell_idle_quiet_for, 1.2)),
            capture_lines=args.capture_lines,
        )
        log_step("SHELL_INPUT_READY")

        # Shell is stable now; switch to repo root.
        send_text_and_enter(
            pane_id,
            cd_command(shell, repo_root),
            chunk_size=args.cmd_chunk_size,
            chunk_delay=args.cmd_chunk_delay,
        )
        log_step("CD_READY")

        # Launch agent.
        send_text_and_enter(
            pane_id,
            agent_cmd,
            chunk_size=args.cmd_chunk_size,
            chunk_delay=args.cmd_chunk_delay,
        )
        log_step("AGENT_COMMAND_SENT")

        expected_cmd = shlex.split(agent_cmd)[0].lower()
        expected_cmd = os.path.basename(expected_cmd)
        startup_pattern = re.compile(args.startup_pattern, re.IGNORECASE) if args.startup_pattern else STARTUP_PATTERNS.get(args.agent)

        wait_for_agent_ready(
            pane_id=pane_id,
            expected_cmd=expected_cmd,
            startup_pattern=startup_pattern,
            shell_cmd_names=shell_cmd_names,
            timeout=args.wait_agent_timeout,
            capture_lines=args.capture_lines,
            idle_quiet_for=args.agent_idle_quiet_for,
            min_runtime=args.agent_min_runtime,
        )
        if args.post_agent_ready_delay > 0:
            time.sleep(args.post_agent_ready_delay)
            wait_for_agent_ready(
                pane_id=pane_id,
                expected_cmd=expected_cmd,
                startup_pattern=startup_pattern,
                shell_cmd_names=shell_cmd_names,
                timeout=args.wait_agent_timeout,
                capture_lines=args.capture_lines,
                idle_quiet_for=args.agent_idle_quiet_for,
                min_runtime=args.agent_min_runtime,
            )
        log_step("AGENT_READY")

        if prompt_text:
            # Required 2-step behavior: send text first, then Enter.
            mode = args.prompt_mode
            if mode == "auto":
                mode = "paste" if args.agent == "gemini" else "type"
            inject_prompt(
                pane_id,
                prompt_text,
                mode=mode,
                chunk_size=args.chunk_size,
                chunk_delay=args.chunk_delay,
            )

            probe = normalized_probe(prompt_text)
            seen = not bool(probe)
            if probe:
                try:
                    wait_until(
                        lambda: pane_contains_probe(pane_id, probe, args.capture_lines),
                        timeout=args.prompt_echo_timeout,
                        interval=0.2,
                        desc="prompt echoed in agent input",
                    )
                    seen = True
                except TmuxError:
                    seen = False

            retry_on_miss = args.agent == "gemini"
            if probe and not seen and retry_on_miss:
                # Retry once for Gemini where transient input buffering is common.
                inject_prompt(
                    pane_id,
                    prompt_text,
                    mode="type",
                    chunk_size=args.chunk_size if args.chunk_size > 0 else 24,
                    chunk_delay=args.chunk_delay if args.chunk_size > 0 else 0.03,
                )
                try:
                    wait_until(
                        lambda: pane_contains_probe(pane_id, probe, args.capture_lines),
                        timeout=args.prompt_echo_timeout,
                        interval=0.2,
                        desc="prompt echoed in agent input after retry",
                    )
                    seen = True
                except TmuxError:
                    seen = False
            send_text_and_enter(pane_id, "", enter_delay=args.enter_delay)
            log_step("PROMPT_SENT_AND_ENTERED")
            if args.verbose and probe and not seen:
                if not retry_on_miss:
                    log_step("PROMPT_RETRY_SKIPPED")
                log_step("PROMPT_ECHO_NOT_CONFIRMED")

            pattern = re.compile(args.exec_pattern) if args.exec_pattern else None
            if pattern:
                before = time.time()

                def saw_exec_signal() -> bool:
                    out = capture_pane(pane_id, args.capture_lines)
                    return bool(pattern.search(out))

                wait_until(saw_exec_signal, timeout=args.wait_exec_timeout, desc="execution signal")
                _ = before

        if args.completion_action != "none":
            spawn_completion_watcher(
                script_path=Path(__file__).resolve(),
                pane_id=pane_id,
                controller_pane=inferred_controller_pane,
                agent=args.agent,
                completion_action=args.completion_action,
                completion_timeout=args.completion_timeout,
                completion_poll=args.completion_poll,
                capture_lines=args.capture_lines,
                notify_mode=args.completion_notify_mode,
            )
            log_step("COMPLETION_WATCHER_STARTED")

        print(f"SESSION={session}")
        print(f"WINDOW_ID={window_id}")
        print(f"PANE_ID={pane_id}")
        print(f"CONTROLLER_PANE={inferred_controller_pane or ''}")
        print(f"TMUX_LAYOUT={args.tmux_layout}")
        print(f"SPLIT_POLICY={args.split_policy}")
        print(f"COMPLETION_ACTION={args.completion_action}")
        print(f"REPO_ROOT={repo_root}")
        print(f"AGENT_CMD={agent_cmd}")
        print("STATUS=OK")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"STATUS=ERROR\nERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
