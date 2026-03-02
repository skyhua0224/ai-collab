---
name: ai-collab-orchestrator
description: ALWAYS use at conversation start. Read ~/.ai-collab/config.json, respect auto_collaboration.enabled (fallback auto_orchestration_enabled), then produce explicit multi-agent plan from configured providers/models before execution.
---

# ai-collab-orchestrator

Controller-first multi-agent orchestration for Codex, Claude, and Gemini.

## Start-of-conversation contract

At the start of every conversation:

1. Read `~/.ai-collab/config.json`.
2. Determine orchestration switch:
   - Preferred key: `auto_collaboration.enabled`
   - Legacy fallback: `auto_collaboration.auto_orchestration_enabled`
   - If both missing, treat as enabled.
3. If disabled, run in solo mode.
4. If enabled, you are the Controller and must create an explicit plan before coding.

## Controller workflow (must follow)

### Step 1: enumerate real agent capacity from config

Use `providers.*` from config and include:

- enabled/disabled status
- strengths
- model strategy (Codex thinking level, Claude/Gemini profile)
- current controller

Do not guess capabilities not present in config.

### Step 2: build an explicit orchestration plan

Use:

```bash
ai-collab detect "<task>" --provider <controller> --output json
```

Read and use these fields in the result:

- `available_agents`
- `orchestration_plan`
- `selected_agents`
- `execution_mode`

If multi-agent is required, state role-by-role assignment before execution.

### Step 3: choose execution mode

- If user wants visible multi-agent collaboration, or plan includes multiple agents:
  - Prefer live tmux mode:

```bash
auto-collab --provider <controller> --execution-mode tmux "<task>"
```

- If task is simple/single-agent:

```bash
auto-collab --provider <controller> --execution-mode direct "<task>"
```

### Step 4: task boundary for each sub-agent

For each assigned role, include:

- role name
- expected output
- completion marker: `=== TASK_COMPLETE ===`

Sub-agent must not expand scope unless controller asks.

## Sub-agent contract

When called by controller:

1. Only do assigned role.
2. Return concise output for that role.
3. End with `=== TASK_COMPLETE ===`.
4. Wait for controller's next instruction.

## Tiny todo fullstack test case

User task:

`实现一个极小的待办功能，有前端后端，后端使用轻量框架保存数据`

Expected planner behavior:

1. Detect frontend + backend + persistence requirements.
2. Generate role plan similar to:
   - `tech-selection`
   - `frontend-build`
   - `backend-build`
   - `quality-review`
3. Select agents/models from config (not hardcoded defaults).
4. If multiple agents are selected, launch tmux collaboration mode so user can watch the live agent panes.

## Failure handling

If any selected agent command is unavailable:

1. Report which provider is unavailable.
2. Re-plan using remaining enabled providers.
3. Keep role plan explicit and continue.

## Provider invocation policy

Default orchestration behavior:

1. Do not run preflight probes (`--help`, `-h`, `--version`, ad-hoc health scripts) for codex/claude/gemini.
2. Execute the assigned step directly through the planned visible workflow (tmux panes for multi-agent mode).
3. If a command is blocked by permissions/approval/sandbox, emit:
   - `NEED_ELEVATION: <command> | reason=<error>`
   - then wait for user action (no silent downgrade).
4. Only run provider diagnostics when the user explicitly asks for troubleshooting, or after repeated execution failures that block progress.
5. Treat Gemini `429 MODEL_CAPACITY_EXHAUSTED` as capacity limitation, not as "provider not called".

## tmux dispatch pattern (required)

Use the same dispatch pattern for `codex`, `claude`, and `gemini`:

1. Create pane first.
2. Wait for shell to be ready.
3. Send provider command by `tmux send-keys ... C-m`.

Do NOT rely on `split-window ... "zsh -lc '<long command>'"` as the default orchestration path.

Fill-in template (Method 1):

```bash
pane_id=$(tmux split-window -v -p <percent> -P -F '#{pane_id}')
tmux send-keys -t "$pane_id" '<provider command with args>' C-m
```

Example:

```bash
pane_id=$(tmux split-window -v -p 35 -P -F '#{pane_id}')
tmux send-keys -t "$pane_id" 'gemini -o text --approval-mode yolo --model gemini-3.1-pro-preview "仅回复 OK" || gemini -o text --approval-mode yolo --model gemini-3-flash-preview "仅回复 OK"' C-m
```

## Permission and visibility policy (must follow)

1. If a provider command fails due permission/sandbox/approval (for example "requires elevated permissions", "approval required", "not allowed in current sandbox"), do NOT silently downgrade.
2. Explicitly ask for elevation/approval and explain which command needs it.
3. In tmux mode, sub-agent execution must be visible in panes:
   - Do not call claude/gemini via hidden background shell commands from controller.
   - Use pane handoff markers (`HANDOFF_TO: <agent>` / `SPAWN_AGENT: <agent>`) so the orchestrator can open visible panes.
   - After outputting a handoff marker, wait for relay/status result; do not mark delegated step complete due temporary no-output.
4. If elevation is denied, then fallback with a clear note of what was skipped.
