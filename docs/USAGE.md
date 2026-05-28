# Usage Guide

This guide covers production usage patterns for the unified `ai-collab` command.

## 1) Command Model

`ai-collab` operates in two modes:

1. **Runner mode**: `ai-collab "<task>"`
2. **Admin mode**: `ai-collab <subcommand>`

Runner option reference:

```bash
ai-collab run --help
```

Admin command reference:

```bash
ai-collab --help
ai-collab <subcommand> --help
```

## 2) Admin Subcommands

Quick list (all support `--help`; optioned commands support short+long flags):

1. `init`
2. `status`
3. `config`
4. `detect`
5. `select`
6. `list`
7. `monitor`
8. `tmux-status`
9. `tmux-capture`
10. `tmux-watch`
11. `tmux-close-pane`
12. `handoff`
13. `tmux-open`
14. `tmux-close-test`
15. `relay-smoke`
16. `resume`

### Initialize

```bash
ai-collab init
```

### Status

```bash
ai-collab status
```

### Detect only (no execution)

```bash
ai-collab detect "Implement OAuth2 token rotation and review rollout risks" --provider codex --output json
```

### Model strategy selection

```bash
ai-collab select codex "Implement distributed lock retry strategy" --complexity high
```

### List workflows

```bash
ai-collab list
```

### Launch tmux workspace manually

```bash
ai-collab monitor -c codex -s ai-collab-live
```

### Launch one sub-agent quickly (short wrapper)

```bash
ai-collab tmux-open -a gemini -c %1 -p "Implement only API contract draft"
```

### Start one-command close-choice workflow test

```bash
ai-collab tmux-close-test -C codex -S claude -d 90 -t 60 -r 45
```

### Resume and recover orchestration runs

```bash
ai-collab resume list -w . -n 20
ai-collab resume show <run_id> -w .
ai-collab resume rename <run_id> "phase1-hotfix"
ai-collab resume recover <run_id> -w . -A
```

Resume state includes:

1. Controller/sub-agent pane bindings and runtime session ids (when detectable from terminal output).
2. Pending step checklist and phase history.
3. tmux topology/content snapshots (captured when topology/event changes).

## 3) Runner Mode Patterns

### Interactive default

```bash
ai-collab
```

### Direct execution

```bash
ai-collab -p codex -x direct "Build audit logging and retention policy checks"
```

### tmux execution (inline panes)

```bash
ai-collab \
  -p codex \
  -x tmux \
  -t inline \
  -W \
  -c \
  "Deliver a full-stack feature with implementation and review handoff"
```

### Plan-only mode

```bash
ai-collab -d -o json "your task"
```

## 4) High-Value Runner Flags

1. `-x, --execution-mode {auto,direct,tmux}`
2. `-t, --tmux-target {auto,session,inline}`
3. `-W, --tmux-prewarm-subagents | --no-tmux-prewarm-subagents`
4. `-c, --controller-first | --no-controller-first`
5. `-I, --interactive-decisions | --no-interactive-decisions`
6. `-a, --allow-nested | --no-allow-nested`
7. `-o, --output {text,json}`
8. `-l, --lang {en-US,zh-CN}`
9. `-u, --ui-mode {auto,tui,text}`

## 5) Configuration Conventions

Configuration path:

```text
~/.ai-collab/config.json
```

Key fields:

1. `current_controller`
2. `providers.<name>.enabled`
3. `providers.<name>.models`
4. `auto_collaboration.enabled`
5. `auto_collaboration.assignment_map`

Template files:

1. `config/config.template.json`

## 6) Logs and Diagnostics

Runtime logs:

```text
.ai-collab/logs/<session>/
```

Typical files:

1. `events.log`
2. `pane-*.log`

Tail logs:

```bash
tail -f .ai-collab/logs/<session>/*.log
```

## 7) Troubleshooting

### Provider unavailable

```bash
which codex claude gemini
ai-collab status
```

### Unexpected single-agent run

```bash
ai-collab detect "<task>" --output json
ai-collab --dry-run --output json "<task>"
```

### tmux not launching

```bash
which tmux
ai-collab --execution-mode tmux --tmux-target session "<task>"
```

### Language not applied

```bash
ai-collab config get ui_language
ai-collab --lang zh-CN "<task>"
```

## 8) Recommended Operational Flow

1. Use `detect` for large or ambiguous tasks.
2. Use `--dry-run` before long-running orchestration.
3. Prefer `tmux + inline` when manual intervention may be needed.
4. Keep logs for postmortem and routing optimization.
