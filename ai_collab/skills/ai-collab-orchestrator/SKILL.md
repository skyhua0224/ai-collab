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

Controller strict-mode additions:

1. In execution phase, do not run `--help` loops to "discover" commands. Build command from known run context and execute directly.
2. If tmux access is blocked (permission/sandbox/approval), immediately output:
   - `NEED_ELEVATION: <command> | reason=<error>`
   - then stop and wait for user decision.
3. If required runtime context is missing (session/pane id), ask once for the missing value; do not probe by repeated help commands.

## One-click launcher (required default)

Use `ai-collab handoff` first instead of manual `tmux send-keys` sequences.

CLI entry:

```bash
ai-collab handoff --agent <codex|claude|gemini> ...
```

Short wrappers (preferred for daily use):

```bash
# Open pane/window with short parameters (defaults: split + controller-bottom + input notify)
ai-collab tmux-open -a <codex|claude|gemini> -c <controller_pane> -p '<task>'

# One-command controller close-choice workflow test (monitor + accept + ask close/keep)
ai-collab tmux-close-test -C codex -S codex -d 90 -t 60 -r 45
```

Behavior (must preserve):

1. Reuse current tmux session (or explicit `--session`).
2. Create a new tmux window (`--tmux-layout window`) or split pane (`--tmux-layout split`).
3. Wait until shell is ready.
4. `cd` into main repository root.
5. Start selected agent (`claude` / `gemini` / `codex`).
6. Wait for agent startup prompt.
7. Paste prompt text, then send `Enter` in a separate action.
8. Optional: wait for execution signal via `--exec-pattern`.

Standard examples:

```bash
# macOS / Linux: new tmux window
ai-collab handoff \
  --agent gemini \
  --model gemini-3.1-pro-preview \
  --tmux-layout window \
  --repo-root "$PWD" \
  --prompt '请读取并执行任务文件：/abs/path/to/task.txt'
```

```bash
# Split mode: top pane controller, bottom pane sub-agent
ai-collab handoff \
  --agent claude \
  --tmux-layout split \
  --split-policy controller-bottom \
  --controller-height-percent 50 \
  --repo-root "$PWD" \
  --prompt '请只做前端可用性复核并给出修正建议'
```

```powershell
# Windows PowerShell (requires tmux available in PATH)
ai-collab handoff `
  --agent codex `
  --tmux-layout split `
  --split-policy controller-bottom `
  --controller-height-percent 50 `
  --repo-root <repo-root> `
  --prompt "请读取并执行任务文件：<task-file-path>"
```

Rules:

1. Default working target is the main repo root, not a random subfolder.
2. For Gemini, prefer explicit model (`gemini-3.1-pro-preview`) instead of implicit auto selection.
3. When user requests visible collaboration, default to `--tmux-layout split --split-policy controller-bottom`.
4. `controller-bottom` policy:
   - first sub-agent: create lower half pane
   - second and later sub-agents: split the lower region horizontally (left/right, then left/middle/right, etc.)
   - keep controller in top pane with `--controller-height-percent 50`
5. For parallel sub-agents, run `ai-collab handoff --tmux-layout split --split-policy controller-bottom` multiple times. Close done panes with `tmux kill-pane -t <pane_id>`.

Completion-policy contract (required):

1. Before spawning a sub-agent, ask user once for completion behavior:
   - `ask`: completion后先询问用户是否关闭 pane（默认）
   - `keep`: 完成后保留 pane
   - `close`: 完成后自动关闭 pane
   - `ask` mode should notify controller first so controller asks user in-chat before closing pane.
2. Encode that choice explicitly in command:

```bash
ai-collab handoff ... --completion-action ask
```

3. If user wants zero-interrupt launch, add:

```bash
ai-collab handoff ... --no-ask-launch-options --completion-action <ask|keep|close|none>
```

Script fallback:

```bash
python3 "$PWD/ai_collab/skills/ai-collab-orchestrator/scripts/tmux_agent_handoff.py" ...
```

> Note: run this command from repository root. On macOS absolute path example:
> `/Users/<you>/ai-collab/ai_collab/skills/ai-collab-orchestrator/scripts/tmux_agent_handoff.py`

## tmux dispatch pattern (manual fallback)

Use the same dispatch pattern for `codex`, `claude`, and `gemini`:

1. Create pane first.
2. Wait for shell to be ready.
3. Send provider command by `tmux send-keys ... C-m`.
4. Wait for provider startup banner and interactive input prompt before sending task content.
5. In interactive mode, send task content in 2 steps:
   - send text
   - send `Enter` as a separate `tmux send-keys` call
6. Treat task as started only after visible execution signal appears (for example step marker, file-read/tool call, or running spinner).

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

Interactive handoff example (required when provider stays in REPL):

```bash
pane_id=$(tmux split-window -v -p 35 -P -F '#{pane_id}')
tmux send-keys -t "$pane_id" 'gemini' C-m
# wait until banner + "Type your message" prompt is visible
tmux send-keys -t "$pane_id" '请读取并执行任务文件：/abs/path/to/task.txt'
tmux send-keys -t "$pane_id" Enter
# verify pane shows execution signal before proceeding
```

## Permission and visibility policy (must follow)

1. If a provider command fails due permission/sandbox/approval (for example "requires elevated permissions", "approval required", "not allowed in current sandbox"), do NOT silently downgrade.
2. Explicitly ask for elevation/approval and explain which command needs it.
3. In tmux mode, sub-agent execution must be visible in panes:
   - Do not call claude/gemini via hidden background shell commands from controller.
   - Use pane handoff markers (`HANDOFF_TO: <agent>` / `SPAWN_AGENT: <agent>`) so the orchestrator can open visible panes.
   - After outputting a handoff marker, wait for relay/status result; do not mark delegated step complete due temporary no-output.
4. If elevation is denied, then fallback with a clear note of what was skipped.
