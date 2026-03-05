# tmux Multi-Agent Requirements and Test Flow

Last updated: 2026-03-04

This document records:

1. The exact question groups raised by the user (3 rounds).
2. The required end-to-end test flow and acceptance criteria.

## 1) User Question Log (3 Rounds)

## Round 1: New Problem Exploration

1. How should controller detect sub-agent completion reliably?
2. Should controller pause and wait for user to observe completion, or should completion be detected automatically?
3. Why marker-only detection (for example `TASK COMPLETE`) is unreliable:
4. It can be forgotten after auto-compact.
5. It can be falsely matched from instruction text itself.
6. It consumes controller tokens when polling behavior is inconsistent.
7. How to standardize tmux status checks and wrap long commands into stable short commands?
8. If codex started outside tmux, can ai-collab features still work?
9. If tmux is required, how to re-enter tmux controller mode quickly without losing context?
10. If already inside tmux, how to bind current tmux session id with ai-collab and controller session?
11. After reboot and tmux loss, can ai-collab support resume like `--resume <id>`?
12. If using codex app (not CLI) or other clients without tmux, what is the collaboration fallback?

## Round 2: Architecture and Operability Questions

1. For JSON status signals, is detection done by keyword extraction or file write? How does controller receive it?
2. What does "pause and wait for event" mean exactly? How is timeout handled?
3. Should ai-collab manage this waiting lifecycle end-to-end?
4. What short commands are needed, and how to make them generic across codex, claude, gemini?
5. Is direct mode useful enough, and what is its exact role?
6. How should collaboration work in codex app when tmux is unavailable?
7. Can ai-collab provide fully restorable local state with `--resume <id>`?
8. Should ai-collab provide `resume list` and session rename support for better discoverability?
9. For no-tmux mode, investigate external options and provide a concrete path.

## Round 3: Execution-Truth Validation Questions

1. Which agent and model were used in the test?
2. Did startup ever send input before shell was ready?
3. Did startup ever send input before agent input UI was ready?
4. Did any agent hit `429` errors?
5. If runtime exceeded initial timeout, did controller re-monitor automatically?
6. After sub-agent completion, did ai-collab monitoring auto-collect status and move workflow forward?
7. Correction from user: timeout is not fixed at 30s; first run may use 30s, but next timeout must be adjusted dynamically by controller judgment.

## 2) Required Test Flow (Authoritative)

This is the required validation sequence requested by the user.

1. Open a new tmux window/session.
2. Start controller in the top pane (codex as controller role).
3. Controller must use ai-collab wrapped commands (not raw tmux for business flow).
4. Controller assigns work and spawns sub-agent in lower half pane (1:1 top-bottom split).
5. Sub-agent executes a realistically delayed task (target about 1 minute for testing).
6. Controller monitors sub-agent via ai-collab watch command:
7. First monitor cycle can use 30s timeout.
8. Next timeout values must be decided dynamically by controller (increase/decrease based on status).
9. If unfinished, monitor output must include structured reason (running, idle, error class).
10. If stuck, controller can nudge sub-agent and continue monitoring.
11. If model/provider failure persists, controller must offer fallback options and ask user for decision.
12. On completion, monitoring must report completion quickly.
13. Controller must first ask user whether to close completed sub-agent pane.
14. Then apply user choice (close or keep) and continue workflow.

## 3) Acceptance Criteria

All points below must pass.

1. Readiness order is correct: shell input-ready before command dispatch, agent ready before prompt submit.
2. No pre-ready input race (no early send before shell/agent readiness).
3. Monitoring supports timeout diagnostics with structured reasons.
4. Monitoring supports repeated cycles with controller-chosen timeout values.
5. Completion detection avoids false positives from command echo text.
6. Completion triggers controller close-question step before any unrelated next action.
7. All primary operations are available through ai-collab command surface.

## 4) Notes for Future Validation Runs

1. Record session id, controller pane id, sub-agent pane id, and command logs.
2. Keep monitor outputs as machine-readable JSON for post-run audit.
3. If JSON output contains terminal color codes, normalize ANSI before parsing in test harnesses.
