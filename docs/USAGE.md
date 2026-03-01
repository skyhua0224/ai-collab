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
```

## 2) Admin Subcommands

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
ai-collab monitor --controller codex --session ai-collab-live
```

## 3) Runner Mode Patterns

### Interactive default

```bash
ai-collab
```

### Direct execution

```bash
ai-collab --provider codex --execution-mode direct "Build audit logging and retention policy checks"
```

### tmux execution (inline panes)

```bash
ai-collab \
  --provider codex \
  --execution-mode tmux \
  --tmux-target inline \
  --tmux-prewarm-subagents \
  --controller-first \
  "Deliver a full-stack feature with implementation and review handoff"
```

### Plan-only mode

```bash
ai-collab --dry-run --output json "your task"
```

## 4) High-Value Runner Flags

1. `--execution-mode {auto,direct,tmux}`
2. `--tmux-target {auto,session,inline}`
3. `--tmux-prewarm-subagents | --no-tmux-prewarm-subagents`
4. `--controller-first | --no-controller-first`
5. `--interactive-decisions | --no-interactive-decisions`
6. `--allow-nested | --no-allow-nested`
7. `--output {text,json}`
8. `--lang {en-US,zh-CN}`
9. `--ui-mode {auto,tui,text}`

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
2. `config/workflows.template.json`

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
