# AI Collaboration System / 智能协作系统

A terminal-first multi-agent orchestration framework for `Codex`, `Claude`, and `Gemini`.

[![CI](https://img.shields.io/github/actions/workflow/status/skyhua0224/ai-collab/ci.yml?branch=main)](https://github.com/skyhua0224/ai-collab/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-collab)](https://pypi.org/project/ai-collab/)
[![Python](https://img.shields.io/pypi/pyversions/ai-collab)](https://pypi.org/project/ai-collab/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

This framework orchestrates planning, implementation, review, and delivery across specialized models with built-in observability, replayability, and graceful degradation.

[中文文档](./README.md)

## Why It Matters

1. **Controller-first flow** – Plan before execution
2. **Config-driven routing** – Roles and models are not hardcoded
3. **Visible collaboration** – tmux panes and logs for real-time and post-run review
4. **Explicit fallback** – Predictable behavior on provider or permission failures

## Single-Command Interface

The project exposes one command: `ai-collab`.

1. **Run tasks**: `ai-collab "<task>"`
2. **Admin actions**: `ai-collab <subcommand>` (`init`, `status`, `config`, etc.)

Show runner options:

```bash
ai-collab run --help
```

## Installation

### Install from Source

```bash
git clone https://github.com/skyhua0224/ai-collab.git
cd ai-collab
python3 -m pip install -e .
```

### Install from PyPI

```bash
pip install ai-collab
```

## Quick Start

### 1. Initialize

```bash
ai-collab init
ai-collab status
```

### 2. Run a Task

```bash
ai-collab "Design and implement an authenticated REST API with test and release notes"
```

### 3. Force Visual tmux Collaboration

```bash
ai-collab \
  --provider codex \
  --execution-mode tmux \
  --tmux-target inline \
  --tmux-prewarm-subagents \
  "Implement a minimal frontend-backend feature and complete review handoff"
```

## Common Subcommands

| Command | Purpose |
|---------|---------|
| `ai-collab init` | Initialize config templates |
| `ai-collab status` | Inspect active config and provider availability |
| `ai-collab detect` | Generate orchestration suggestions without execution |
| `ai-collab monitor` | Launch tmux workspace manually |
| `ai-collab config` | Manage configuration |
| `ai-collab select` | Choose model strategy by complexity |

## Observability and Troubleshooting

Log directory:

```text
.ai-collab/logs/<session>/
```

Common diagnostics:

```bash
tail -f .ai-collab/logs/<session>/*.log
ai-collab detect "<task>" --output json
ai-collab --dry-run --output json "<task>"
```

## Documentation

1. [Quick Start](./QUICKSTART.md)
2. [Usage Guide](./docs/USAGE.md)
3. [Release Guide](./docs/RELEASE.md)

## Development Verification

```bash
pytest -q
python3 -m build
python3 -m twine check dist/*
```

## License

[MIT](./LICENSE)
