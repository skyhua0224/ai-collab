# ai-collab UX Lab V1 Plan

## Goal

Build a first testable fullscreen TUI flow for `ai-collab` that matches the new product direction without replacing the current default entrypoint yet.

This version is for interaction validation, not final orchestration wiring.

## V1 Entry

- Experimental command: `ai-collab ux-lab`
- Keep current bare `ai-collab` behavior unchanged for now.
- Language follows config `ui_language`.

## V1 Scope

### 1. Fullscreen shell

- Fullscreen TUI via `prompt_toolkit`
- Top ASCII `ai-collab` banner
- Footer with concise hotkeys and state
- No detector/workflow/skills dump in default user flow

### 2. Workspace step

- Show current directory
- Ask whether current directory should be the target workspace
- If not, allow:
  - filtering known folders
  - selecting a discovered folder
  - typing a manual path
  - creating a new folder from typed path

### 3. Controller step

- Display enabled agents from config
- Left/right switches controller
- Selected controller is highlighted with provider color

### 4. Task step

- Multi-line input box
- Paste supported
- `/nano` and `/vim` supported
- External editor content is loaded back into the task box

### 5. Planning step

- Show a compact planning progress state
- V1 planner mode is `mock`
- Mock planner returns localized structured steps with:
  - `SX`
  - title
  - agent
  - ETA
  - done criteria

### 6. Review step

- Render plan table in TUI
- Allow interactive changes:
  - edit selected task fields
  - create task
  - delete task
  - switch assigned agent
- `Send` in V1 exports a launch bundle JSON

### 7. Parameter mode

- `ai-collab ux-lab --non-interactive`
- Prefill via CLI args:
  - `--workspace`
  - `--controller`
  - `--task` or `--task-file`
  - `--skip-review`
- V1 non-interactive mode can build and export a bundle without TUI

## Explicit V1 Non-Goals

- Do not silently fallback to built-in delegation when planner fails
- Do not expose prompt path, briefing path, run id, or tmux log path by default
- Do not replace current production `ai-collab` runner flow yet
- Do not wire the final `Send -> tmux live orchestration` path in V1

## Planner Failure Rule

- Planner failure must stop the flow
- Show retry or exit
- No implicit internal fallback

## Output Artifact

V1 `Send` writes a bundle file under:

`<workspace>/.ai-collab/ux-lab/`

The bundle records:

- language
- workspace
- controller
- raw task
- planner mode
- localized plan items

## Validation Commands

Run focused tests:

```bash
pytest -q tests/test_ux_lab.py
```

Launch the fullscreen lab:

```bash
ai-collab ux-lab
```

Launch with prefills:

```bash
ai-collab ux-lab --controller codex --task "Test the new workspace flow"
```

Run parameter mode without TUI:

```bash
ai-collab ux-lab --non-interactive --controller codex --task "Test planner JSON" --skip-review
```

## Exit Criteria For V1

- Config language changes the UI copy
- User can move from workspace selection to controller to task to plan review
- `/nano` and `/vim` work
- User can edit plan items before send
- `Send` produces a bundle file suitable for the next integration step
