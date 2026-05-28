# ai-collab UX Lab V3 Plan

## Positioning

V3 is a parallel experiment, not a replacement for the current `ux-lab` V1 flow.

Goal:

- Keep `ux-lab` as V1 for comparison
- Add `ux-lab-v3` as a cleaner controller-first TUI
- Fix the structural problems in V1 instead of polishing the same interaction model

## Core Design Changes

### 1. Persistent Bottom Command Bar

- One global command/input bar always exists at the bottom
- Most interactions happen through that bar
- Task editing remains a dedicated multiline editor, but the bottom bar still stays visible

### 2. No Button Grid UI

- Remove action-button grids from workspace/controller/review flows
- Use keyboard-first interaction:
  - `Up` / `Down` for selection
  - `Left` / `Right` for controller or agent switching
  - `Enter` to accept
  - slash commands in the bottom bar for edits

### 3. Narrow-Screen Safe Layout

- No deeply nested `Frame + Frame + Button + RadioList` layout
- Review screen switches between:
  - split view on wide terminals
  - stacked view on narrow terminals
- No `Window too small...` fallback should appear in normal use

### 4. Cleaner Information Hierarchy

- Banner becomes compact and brand-led, not oversized
- Controller selection shows one current selection, not repeated labels
- Workspace screen uses one logic path:
  - filter known folders
  - accept highlighted result
  - paste full path
  - `/new <path>` to create

### 5. Real Planning by Default

- `ux-lab-v3` defaults to `planner-mode=live`
- Mock mode stays available only for local UI testing
- Controller planning failure must stop and show retry/back options
- No implicit fallback to built-in delegation

## Screen Model

### Workspace

- Main content: current directory + candidate list
- Bottom bar:
  - empty Enter => accept highlighted/current workspace
  - filter text => filter and accept highlighted
  - full path => use path
  - `/new <path>` => create folder

### Controller

- Main content: three controller cards
- Bottom bar:
  - optional typed agent name
  - Enter accepts current selection

### Task

- Main content: multiline task editor
- Bottom bar:
  - `/plan`
  - `/nano`
  - `/vim`
  - `/back`

### Planning

- Main content: spinner + live status log
- Bottom bar:
  - read-only hint

### Review

- Main content:
  - task list
  - selected task detail
- Bottom bar commands:
  - `/title ...`
  - `/done ...`
  - `/eta 12`
  - `/agent codex`
  - `/create ...`
  - `/delete`
  - `/send`
  - `/task`

### Error

- Main content: planner error summary
- Bottom bar:
  - `/retry`
  - `/task`

## Command Entry

- `ai-collab ux-lab` => keep current V1
- `ai-collab ux-lab-v3` => new experiment

## Validation

```bash
pytest -q tests/test_ux_lab.py tests/test_ux_lab_v3.py
```

```bash
ai-collab ux-lab-v3
```

```bash
ai-collab ux-lab-v3 --planner-mode mock
```

```bash
ai-collab ux-lab-v3 --non-interactive --planner-mode live --controller codex --task "test real controller JSON"
```
