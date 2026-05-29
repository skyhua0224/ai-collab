"""Python HTTP adapter for the Web UI."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ai_collab.core.config import Config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _workspace_id(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(path.resolve()).lower()).strip("-")[-24:] or "workspace"


def _display_path(path: Path) -> str:
    home = Path.home().resolve()
    resolved = path.resolve()
    if resolved == home:
        return "~"
    try:
        return f"~{resolved.relative_to(home)}"
    except ValueError:
        return str(resolved)


def _workspace_kind(path: Path) -> str:
    markers = [
        ("rust", "Cargo.toml"),
        ("node", "package.json"),
        ("python", "pyproject.toml"),
        ("docs", "README.md"),
    ]
    for kind, marker in markers:
        if (path / marker).exists():
            return kind
    return "unknown"


def _workspace_summary(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "id": _workspace_id(resolved),
        "name": resolved.name or str(resolved),
        "absolutePath": str(resolved),
        "displayPath": _display_path(resolved),
        "lastOpenedAt": _now_iso(),
        "projectKind": _workspace_kind(resolved),
        "git": {"isRepo": (resolved / ".git").exists()},
        "summary": f"{resolved.name or resolved} · {_workspace_kind(resolved)}",
    }


def _resolve_run_workspace(item: dict[str, Any], workspaces: list[dict[str, Any]], workspace_root: Path) -> dict[str, Any]:
    workspace = item.get("workspace")
    if isinstance(workspace, dict):
        workspace_id = str(workspace.get("id", "")).strip()
        absolute_path = str(workspace.get("absolutePath", "")).strip()
        if workspace_id and absolute_path:
            return workspace

    workspace_id = str(item.get("workspaceId", "")).strip()
    workspace_path = str(item.get("workspacePath", "")).strip()

    if workspace_id:
        by_id = next((entry for entry in workspaces if str(entry.get("id", "")).strip() == workspace_id), None)
        if by_id:
            return by_id

    if workspace_path:
        resolved = Path(workspace_path).expanduser()
        by_path = next((entry for entry in workspaces if str(entry.get("absolutePath", "")).strip() == str(resolved.resolve())), None)
        if by_path:
            return by_path
        if resolved.exists():
            return _workspace_summary(resolved)

    return _workspace_summary(workspace_root)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    payload = handler.rfile.read(length).decode("utf-8")
    return json.loads(payload or "{}")


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _write_sse(handler: BaseHTTPRequestHandler, event: str, payload: Any) -> None:
    body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=_json_default)}\n\n"
    handler.wfile.write(body.encode("utf-8"))
    handler.wfile.flush()


def _clock_now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _format_duration(started_at: str) -> int:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except Exception:
        return 0
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))


def _trim_reply(text: str) -> str:
    cleaned = re.sub(r"```(?:json|markdown|text)?", "", text).strip()
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return "收到。"
    if len(lines) == 1:
        return lines[0]
    return "\n".join(lines[:8]).strip()


def _extract_codex_text(output_text: str) -> str:
    """Pull the assistant's answer out of a provider's JSONL stream.

    Handles codex (`exec --json`) and claude (`--output-format stream-json`); a
    final claude `result` event, when present, is authoritative. Plain-text output
    (e.g. gemini `-o text`) yields "" so the caller can fall back to raw stdout.
    """
    last_text = ""
    result_text = ""
    stream_parts: list[str] = []
    for raw_line in str(output_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type", "")).strip().lower()
        # Claude partial messages: token-level text deltas, so the answer streams as
        # it's generated (thinking/tool deltas are skipped — only spoken text).
        if event_type == "stream_event":
            event = payload.get("event")
            if isinstance(event, dict):
                delta = event.get("delta")
                if isinstance(delta, dict) and str(delta.get("type", "")).lower() == "text_delta":
                    piece = delta.get("text")
                    if isinstance(piece, str) and piece:
                        stream_parts.append(piece)
            continue
        # Codex: events carry the message either nested under `item` or at top level.
        item = payload.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type", "")).strip().lower()
            if item_type in {"agent_message", "assistant_message"}:
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    last_text = text
                continue
        if event_type in {"assistant_message", "agent_message"}:
            text = str(payload.get("text") or payload.get("content") or "").strip()
            if text:
                last_text = text
            continue
        # Claude stream-json: assistant messages hold a list of content blocks; we
        # want the `text` blocks (ignoring `thinking`). The final `result` event
        # repeats the full answer and wins when it's a success.
        if event_type == "assistant":
            message = payload.get("message")
            if isinstance(message, dict):
                parts = [
                    str(block.get("text") or "").strip()
                    for block in (message.get("content") or [])
                    if isinstance(block, dict) and str(block.get("type", "")).lower() == "text" and str(block.get("text") or "").strip()
                ]
                if parts:
                    last_text = "\n".join(parts).strip()
            continue
        if event_type == "result" and not payload.get("is_error"):
            res = payload.get("result")
            if isinstance(res, str) and res.strip():
                result_text = res.strip()
            continue
    # Authoritative when available (final result, then a complete assistant message);
    # otherwise the text accumulated from partial deltas mid-stream.
    return result_text or last_text or "".join(stream_parts).strip()


def _fallback_reply(prompt: str, controller: str) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "收到。"
    return f"收到。当前控制器是 {controller}，我会继续处理：{prompt}"


def _pick_local_folder() -> str | None:
    if sys.platform != "darwin":
        raise RuntimeError("当前只支持 macOS 原生文件夹选择。")
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "选择工作区文件夹")',
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        raise RuntimeError(f"打开文件夹选择器失败：{exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        if re.search(r"User canceled|User cancelled|cancel", message, re.IGNORECASE):
            return None
        raise RuntimeError(message or "打开文件夹选择器失败。")
    return (result.stdout or "").strip().rstrip("/")


def _compact_title(text: str, assistant_text: str = "") -> str:
    """Create a compact conversation title (<=10 CJK chars or short latin phrase)."""
    source = (text or assistant_text or "Chat").strip()
    source = re.sub(r"[`*_#>\[\]()]", "", source)
    source = re.sub(r"^(请|帮我|麻烦|可以|能不能|我要|我想|给我|实现|新建|创建|添加|修复|优化|重构|删除|修改|写一个|做一个)+", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\s+", " ", source).strip(" ，。,.！!？?：:")
    if not source:
        return "新对话"
    if re.search(r"[一-鿿]", source):
        compact = re.sub(r"[\s，。,.！!？?：:；;、/\\]+", "", source)
        return compact[:10] or "新对话"
    words = source.split()
    title = " ".join(words[:4])
    return title[:24] or "New chat"


CONTEXT_TURNS = 6
MAX_HISTORY_CHARS = 2400
MAX_PROMPT_CHARS = 6000


def _build_prompt(messages: list[dict[str, Any]], user_prompt: str) -> str:
    history: list[str] = []
    history_messages = messages
    if messages:
        last = messages[-1]
        if str(last.get("role", "")).strip().lower() == "user" and str(last.get("content", "")).strip() == user_prompt.strip():
            history_messages = messages[:-1]
    remaining = MAX_HISTORY_CHARS
    seen_entries: set[str] = set()
    for message in reversed(history_messages[-CONTEXT_TURNS:]):
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content or "后端调用失败" in content or "timed out after" in content:
            continue
        if role == "user" and content == user_prompt.strip():
            continue
        content = re.sub(r"\s+", " ", content)
        if len(content) > 420:
            content = content[:420] + "…"
        # Drop repeats so the model isn't fed the same turn several times (which
        # otherwise makes it echo/duplicate the conversation in its reply).
        dedup_key = f"{role}:{content}"
        if dedup_key in seen_entries:
            continue
        seen_entries.add(dedup_key)
        entry = f"{'用户' if role == 'user' else '助手'}: {content}"
        if len(entry) > remaining:
            continue
        history.insert(0, entry)
        remaining -= len(entry)
    history_text = "\n".join(history)
    prompt = (
        "你是 ai-collab 的项目内置助手。请直接回答用户问题，简洁、具体，不要输出分析过程。\n"
        f"{history_text}\n"
        f"用户: {user_prompt}\n"
        "助手:"
    )
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[-MAX_PROMPT_CHARS:]
    return prompt


_ROUTE_PATTERNS: list[tuple[str, set[str]]] = [
    (r"前端|页面|ui|界面|样式|css|html|布局|组件|动画|react|vue|tailwind|视觉|按钮|图标|配色|design", {"frontend", "visual-design", "html-css"}),
    (r"调研|研究|搜索|对比|选型|生态|哪个库|哪个框架|research|ecosystem", {"research", "ecosystem"}),
    (r"架构|系统设计|architecture|结构设计|分层", {"architecture"}),
    (r"重构|refactor", {"architecture", "code-review"}),
    (r"评审|审查|review|检查代码|代码质量|code review", {"code-review"}),
    (r"安全|漏洞|security|鉴权|加密|注入|权限|越权", {"security"}),
    (r"文档|注释|readme|document|写说明", {"documentation"}),
    (r"为什么|原理|分析|推理|权衡|解释|讲解|trade-?off", {"reasoning"}),
    (r"测试|单元测试|\btest\b|用例|覆盖率", {"testing"}),
    (r"修复|bug|调试|报错|error|debug|失败|不工作|崩溃|异常", {"debugging"}),
    (r"后端|接口|api|数据库|server|backend|sql|部署|集成", {"backend", "integration"}),
    (r"实现|写一个|做一个|新建|创建|添加|加一个|生成|implement|build|create|开发", {"implementation"}),
]


def _cli_available(cli: str) -> bool:
    """True if the provider's CLI executable is on PATH."""
    parts = shlex.split(cli or "")
    if not parts:
        return False
    return shutil.which(parts[0]) is not None


_PROVIDER_HEALTH: dict[str, tuple[float, bool]] = {}
_PROVIDER_HEALTH_TTL = 300


def _is_provider_unusable_error(text: str) -> bool:
    return (
        "not running in a trusted directory" in text
        or "GEMINI_CLI_TRUST_WORKSPACE" in text
        or "--skip-trust" in text
        or "timed out after" in text
    )


def _provider_ok(config: Config, name: str, *, probe: bool = False, cwd: str | None = None) -> bool:
    provider = config.providers.get(name)
    if not provider or not getattr(provider, "enabled", True) or not _cli_available(getattr(provider, "cli", "")):
        return False
    if not probe:
        return True
    # For non-default routing, verify the CLI can actually answer quickly. A CLI
    # can be installed but unauthenticated/hung; cache the result so routing does
    # not probe on every message.
    cache_key = f"{name}:{getattr(provider, 'cli', '')}:{cwd or ''}"
    now = time.monotonic()
    cached = _PROVIDER_HEALTH.get(cache_key)
    if cached and now - cached[0] < _PROVIDER_HEALTH_TTL:
        return cached[1]
    try:
        cmd = _build_provider_command(config, "请只回复 OK", name)
        if not cmd:
            _PROVIDER_HEALTH[cache_key] = (now, False)
            return False
        work_dir = cwd if cwd and Path(cwd).is_dir() else None
        proc = subprocess.run(cmd, cwd=work_dir, env={**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"}, capture_output=True, text=True, timeout=8, check=False)
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and not _is_provider_unusable_error(output)
    except Exception:
        ok = False
    _PROVIDER_HEALTH[cache_key] = (now, ok)
    return ok


# When the best-fit provider is unavailable, fall through in this order. Putting
# gemini→claude→codex here means a frontend task that can't use gemini lands on
# claude before codex (the user-requested chain), while chitchat still prefers the
# configured default.
_PROVIDER_FALLBACK_ORDER = ["gemini", "claude", "codex"]

# Names/aliases the user might type when they explicitly want a given provider.
_PROVIDER_REQUEST_ALIASES: list[tuple[str, str]] = [
    ("claude", r"claude\s*code|claudecode|claude|anthropic|克劳德|克劳迪"),
    ("gemini", r"gemini|谷歌|双子|bard"),
    ("codex", r"codex|openai|gpt|o1|o3|o4"),
]
# An intent verb near a provider name signals a real request ("用 claude"),
# not an incidental mention ("codex 报错了").
_PROVIDER_REQUEST_INTENT = r"用|改用|换成|换到|切到|切换|使用|让|请|改成|走|调用|use|switch|with|by"


# Wall-clock cap for the (optional) LLM intent judge — kept short so a slow CLI
# can't stall routing; on timeout we fall back to the rule heuristic.
JUDGE_TIMEOUT = float(os.environ.get("AI_COLLAB_INTENT_JUDGE_TIMEOUT", "12"))


def _mentions_provider(config: Config, user_message: str) -> bool:
    """Cheap pre-filter: does the message name a provider at all?

    Routing only spends an LLM judge call when this is true, so ordinary messages
    (the vast majority) cost nothing extra.
    """
    low = (user_message or "").lower()
    return any(name in config.providers and re.search(pattern, low) for name, pattern in _PROVIDER_REQUEST_ALIASES)


def _rule_provider_request(config: Config, user_message: str) -> str | None:
    """Rule heuristic: an intent verb plus a provider name → that provider (earliest)."""
    text = (user_message or "").lower()
    compact = re.sub(r"\s+", "", text)
    # Strong, unambiguous user intent: "用 claude/claudecode". Honor this before
    # the LLM judge, otherwise the default codex judge may overthink it and route
    # to itself (the bad "codex calls claude" loop the user reported).
    if re.search(r"(用|使用|改用|换成|切到|调用|让).{0,12}(claude\s*code|claudecode|claude|anthropic|克劳德|克劳迪)", text) or re.search(r"(用|使用|改用|换成|切到|调用|让).{0,12}(claudecode|claude)", compact):
        return "claude" if "claude" in config.providers else None
    if re.search(r"(用|使用|改用|换成|切到|调用|让).{0,12}(gemini|谷歌|双子|bard)", text):
        return "gemini" if "gemini" in config.providers else None
    if re.search(r"(用|使用|改用|换成|切到|调用|让).{0,12}(codex|openai|gpt)", text):
        return "codex" if "codex" in config.providers else None
    if not re.search(_PROVIDER_REQUEST_INTENT, text):
        return None
    matches: list[tuple[int, str]] = []
    for name, pattern in _PROVIDER_REQUEST_ALIASES:
        if name not in config.providers:
            continue
        found = re.search(pattern, text)
        if found:
            matches.append((found.start(), name))
    if not matches:
        return None
    matches.sort()
    return matches[0][1]


def _judge_provider_with_llm(config: Config, user_message: str) -> str | None:
    """Ask a fast model whether the user is explicitly requesting a provider.

    Returns the provider name, "" when the model judges there's no real request,
    or None when the judge couldn't run (caller then trusts the rule heuristic).
    """
    judge = config.current_controller if _provider_ok(config, config.current_controller) else next(
        (name for name in config.providers if _provider_ok(config, name)), None
    )
    if not judge:
        return None
    options = "、".join(config.providers.keys())
    prompt = (
        "你是模型路由判断器。判断用户是否在明确要求改用某个具体模型来完成任务。\n"
        f"可选模型：{options}。\n"
        "重要：claudecode、Claude Code、Claude 都映射为 claude。若用户说'用/使用/调用/切到/让 Claude/Claude Code/claudecode'，必须回答 claude。\n"
        "若用户明确要求用某个模型，只回答该模型名（小写、一个单词）；"
        "若只是顺带提到或抱怨某模型、并未要求改用，回答 none。不要解释。\n"
        f"用户消息：{user_message}\n回答："
    )
    cmd = _build_provider_command(config, prompt, judge)
    if not cmd:
        return None
    try:
        result = _stream_provider_output(
            cmd,
            cwd=None,
            env={**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"},
            idle_timeout=JUDGE_TIMEOUT,
            max_timeout=JUDGE_TIMEOUT,
        )
    except Exception:
        return None
    if result.timed_out:
        return None
    answer = (_extract_codex_text(result.stdout) or result.stdout or result.stderr or "").strip().lower()
    if not answer:
        return None
    for name in config.providers:
        if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", answer):
            return name
    return ""  # judge answered (e.g. "none") but named no provider → no request


def _explicit_provider_request(config: Config, user_message: str, *, use_llm: bool = True) -> str | None:
    """Provider the user explicitly asked for, judged by an LLM with a rule fallback."""
    # No provider mentioned at all → there's nothing to judge; skip the LLM entirely.
    if not _mentions_provider(config, user_message):
        return None
    rule_choice = _rule_provider_request(config, user_message)
    if not use_llm or rule_choice:
        # Strong explicit phrasing (e.g. "用 claudecode") should win immediately;
        # the LLM judge is only for ambiguous mentions.
        return rule_choice
    verdict = _judge_provider_with_llm(config, user_message)
    if verdict is None:  # judge couldn't run → trust the rule heuristic
        return rule_choice
    return verdict or None  # "" → judged: no explicit request


def _route_controller(config: Config, user_message: str, *, cwd: str | None = None) -> str:
    """Route a message to the best-fit provider.

    Order of preference:
      1. A provider the user explicitly asked for (if it's usable).
      2. The provider whose strengths best match the task.
      3. The global fallback chain (gemini → claude → codex), so e.g. a frontend
         task that can't use gemini falls to claude before codex.
    Chitchat (no task keywords) prefers the configured default controller.
    """
    default = config.current_controller

    # 1) Honor an explicit user request when that provider is actually usable.
    requested = _explicit_provider_request(config, user_message)
    if requested and _provider_ok(config, requested, probe=(requested != default), cwd=cwd):
        return requested

    # 2) Score every enabled provider against the task's intent tags.
    text = (user_message or "").lower()
    triggered: set[str] = set()
    for pattern, tags in _ROUTE_PATTERNS:
        if re.search(pattern, text):
            triggered |= tags

    def fallback_rank(name: str) -> int:
        return _PROVIDER_FALLBACK_ORDER.index(name) if name in _PROVIDER_FALLBACK_ORDER else len(_PROVIDER_FALLBACK_ORDER)

    def score_of(name: str) -> int:
        provider = config.providers[name]
        return len(set(getattr(provider, "strengths", [])) & triggered) if triggered else 0

    enabled = [name for name, provider in config.providers.items() if getattr(provider, "enabled", True)]

    # Best-fit provider: highest strength score. Ties go to the default when there's
    # no task intent (chitchat → codex), otherwise to the global fallback order.
    def chosen_key(name: str) -> tuple[int, int, int]:
        prefer_default = (not triggered) and name == default
        return (-score_of(name), 0 if prefer_default else 1, fallback_rank(name))

    chosen = min(enabled, key=chosen_key) if enabled else default

    # 3) Try the best fit first; once it's unavailable, hand off to the fallback
    #    chain (gemini → claude → codex) rather than a weak secondary score — so a
    #    frontend task with no gemini lands on claude before codex.
    rest = sorted((name for name in enabled if name != chosen), key=fallback_rank)
    candidates = [chosen, *rest]
    if default in config.providers and default not in candidates:
        candidates.append(default)

    for name in candidates:
        # The default is the safe baseline, so accept it on availability alone;
        # other providers are probed to make sure they can actually answer.
        if name == default:
            if _provider_ok(config, name):
                return name
        elif _provider_ok(config, name, probe=True, cwd=cwd):
            return name
    return default


def _build_provider_command(config: Config, prompt: str, controller: str | None = None) -> list[str]:
    controller = controller or config.current_controller
    provider = config.providers.get(controller)
    if not provider:
        return []
    parts = shlex.split(provider.cli)
    if not parts:
        return []

    if controller == "codex":
        if parts[0] == "codex" and (len(parts) == 1 or parts[1] != "exec"):
            parts.insert(1, "exec")
        if "--skip-git-repo-check" not in parts:
            parts.append("--skip-git-repo-check")
        # Allow the agent to create/edit files inside the workspace. Without this,
        # `codex exec` runs in a read-only sandbox and can't write anything.
        sandbox_flags = {"-s", "--sandbox", "--full-auto", "--dangerously-bypass-approvals-and-sandbox"}
        if not sandbox_flags.intersection(parts):
            parts.extend(["--sandbox", "workspace-write"])
        if "--json" not in parts:
            parts.append("--json")
        return parts + [prompt]

    if controller == "claude":
        if "-p" not in parts and "--print" not in parts:
            parts.append("-p")
        # Stream JSONL instead of buffering plain text to the end: claude emits
        # progress events while it thinks, so the user sees activity, the idle
        # watchdog stays satisfied, and we can surface the answer as it lands.
        # (`stream-json` requires `--verbose` in print mode.)
        if "--output-format" not in parts:
            parts.extend(["--output-format", "stream-json"])
        if "--verbose" not in parts:
            parts.append("--verbose")
        # Emit token-level partial events too, so even while generating a large file
        # in a single tool call there's a steady heartbeat — otherwise that silent
        # generation gap can trip the idle watchdog and kill the run mid-write.
        if "--include-partial-messages" not in parts:
            parts.append("--include-partial-messages")
        if "--permission-mode" not in parts and "--dangerously-skip-permissions" not in parts:
            parts.extend(["--permission-mode", "acceptEdits"])
        return parts + [prompt]

    if controller == "gemini":
        if "-p" not in parts and "--prompt" not in parts:
            parts.append("-p")
        if "-o" not in parts and "--output-format" not in parts:
            parts.extend(["-o", "text"])
        return parts + [prompt]

    return parts + [prompt]


# Provider calls (codex/claude/gemini) can legitimately run for minutes when the
# task involves reading large files or generating whole pages, so we never impose a
# short wall-clock timeout. Two guards instead:
#   * max_timeout — a generous overall ceiling (catches a truly stuck process).
#   * idle_timeout — max gap *between output chunks*, applied ONLY after the CLI has
#     produced its first output. This matters because some CLIs (e.g. claude -p)
#     think silently and emit everything at the end; an idle timer that ran from
#     process start would wrongly kill them mid-think. Streaming CLIs (codex --json)
#     still get hang-detection once their output begins.
# Both are overridable via env and per provider (idle_timeout / max_timeout fields).
PROVIDER_IDLE_TIMEOUT = float(os.environ.get("AI_COLLAB_PROVIDER_IDLE_TIMEOUT", "0"))
PROVIDER_MAX_TIMEOUT = float(os.environ.get("AI_COLLAB_PROVIDER_MAX_TIMEOUT", "1800"))


@dataclass
class ProviderRun:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    timeout_reason: str = ""


_ACTIVE_PROVIDER_PROCS: dict[str, subprocess.Popen] = {}
_ACTIVE_PROVIDER_LOCK = threading.RLock()
_CANCELLED_PROVIDER_RUNS: set[str] = set()


def _provider_timeouts(provider: Any) -> tuple[float, float]:
    # Hard ceiling: an explicit `max_timeout`, else the generous default. The legacy
    # per-provider `timeout` is NEVER the ceiling (claude's 120 would cap long tasks).
    explicit_idle = getattr(provider, "idle_timeout", None)
    legacy = getattr(provider, "timeout", None)
    hard = getattr(provider, "max_timeout", None)
    if explicit_idle:
        idle_timeout = float(explicit_idle)
    elif PROVIDER_IDLE_TIMEOUT > 0:
        # A legacy `timeout` may only RAISE the idle window above the safe floor,
        # never lower it — 120s is too short for generating a whole file.
        idle_timeout = max(float(legacy or 0), PROVIDER_IDLE_TIMEOUT)
    else:
        idle_timeout = 0.0  # disabled: only the hard cap can stop a provider
    max_timeout = float(hard) if hard else PROVIDER_MAX_TIMEOUT
    # The hard cap must never be shorter than one idle window.
    return idle_timeout, max(max_timeout, idle_timeout)


def _terminate_process(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except Exception:
        return
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _cancel_provider_run(run_id: str) -> bool:
    with _ACTIVE_PROVIDER_LOCK:
        _CANCELLED_PROVIDER_RUNS.add(run_id)
        proc = _ACTIVE_PROVIDER_PROCS.get(run_id)
    if proc is None or proc.poll() is not None:
        return False
    _terminate_process(proc)
    return True


def _stream_provider_output(
    cmd: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    idle_timeout: float,
    max_timeout: float,
    on_chunk: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> ProviderRun:
    """Run *cmd*, streaming stdout line-by-line and killing it only when it stalls.

    A watchdog thread terminates the process if it produces no output for
    `idle_timeout` seconds or runs longer than `max_timeout` seconds. stdout is
    read in this thread (forwarding each line to `on_chunk`), stderr in a helper
    thread. Returns whatever output was captured plus whether a timeout fired.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if run_id:
        with _ACTIVE_PROVIDER_LOCK:
            _ACTIVE_PROVIDER_PROCS[run_id] = proc
    out_parts: list[str] = []
    err_parts: list[str] = []
    activity = {"at": time.monotonic(), "started": False}
    activity_lock = threading.Lock()
    watchdog = {"timed_out": False, "reason": ""}

    def touch(*, is_output: bool = False) -> None:
        with activity_lock:
            activity["at"] = time.monotonic()
            if is_output:
                activity["started"] = True

    def read_stderr() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            err_parts.append(line)
            touch()  # keeps the process "alive" but doesn't arm the idle gate

    def watch() -> None:
        start = time.monotonic()
        while proc.poll() is None:
            now = time.monotonic()
            with activity_lock:
                idle_for = now - activity["at"]
                started = activity["started"]
            if now - start >= max_timeout:
                watchdog.update(timed_out=True, reason=f"运行超过 {int(max_timeout)} 秒上限")
                _terminate_process(proc)
                return
            # By default, idle timeout is disabled because long Claude/Codex file
            # writes can be legitimately silent for many minutes. If explicitly
            # configured (>0), it applies only after the first real output.
            if idle_timeout > 0 and started and idle_for >= idle_timeout:
                watchdog.update(timed_out=True, reason=f"输出中断超过 {int(idle_timeout)} 秒")
                _terminate_process(proc)
                return
            time.sleep(0.5)

    err_thread = threading.Thread(target=read_stderr, daemon=True)
    watch_thread = threading.Thread(target=watch, daemon=True)
    err_thread.start()
    watch_thread.start()

    if proc.stdout is not None:
        for line in proc.stdout:
            out_parts.append(line)
            touch(is_output=True)
            if on_chunk:
                try:
                    on_chunk(line)
                except Exception:
                    pass

    proc.wait()
    if run_id:
        with _ACTIVE_PROVIDER_LOCK:
            _ACTIVE_PROVIDER_PROCS.pop(run_id, None)
            was_cancelled = run_id in _CANCELLED_PROVIDER_RUNS
    else:
        was_cancelled = False
    err_thread.join(timeout=2)
    watch_thread.join(timeout=2)
    return ProviderRun(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout="".join(out_parts),
        stderr="".join(err_parts),
        timed_out=bool(watchdog["timed_out"]),
        timeout_reason="用户已终止" if was_cancelled else str(watchdog["reason"]),
    )


def _run_provider_reply(
    config: Config,
    messages: list[dict[str, Any]],
    user_prompt: str,
    cwd: str | None = None,
    controller: str | None = None,
    on_delta: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> str:
    prompt = _build_prompt(messages, user_prompt)
    controller = controller or config.current_controller
    provider = config.providers.get(controller)
    work_dir: str | None = None
    if cwd:
        candidate = Path(cwd).expanduser()
        if candidate.is_dir():
            work_dir = str(candidate)
    if not provider:
        raise RuntimeError(f"当前控制器 {controller} 没有可用的 CLI。")
    cmd = _build_provider_command(config, prompt, controller)
    if not cmd:
        raise RuntimeError(f"当前控制器 {controller} 没有可用的 CLI。")

    idle_timeout, max_timeout = _provider_timeouts(provider)
    # Forward newly generated assistant text to `on_delta` as the CLI streams it,
    # so the UI shows progress instead of appearing frozen during long tasks. Some
    # providers (notably Claude Code) can spend a long time inside tool/file writes
    # without producing user-facing text, so non-text stream events also trigger a
    # sparse status heartbeat; the final message overwrites these temporary hints.
    seen = {"text": "", "buffer": "", "last_status_at": 0.0, "status_index": 0}
    progress_messages = [
        "正在分析并准备修改文件…",
        "正在生成文件内容，可能需要几分钟…",
        "仍在执行，请保持此页面打开…",
        "正在等待工具调用完成…",
    ]

    def _provider_activity_hint(line: str) -> str | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        event_type = str(payload.get("type", "")).strip().lower()
        subtype = str(payload.get("subtype", "")).strip().lower()
        if event_type == "system" and subtype == "thinking_tokens":
            tokens = payload.get("estimated_tokens")
            return f"正在思考（约 {tokens} tokens）…" if tokens else "正在思考…"
        if event_type == "assistant":
            message = payload.get("message")
            if isinstance(message, dict):
                blocks = message.get("content") or []
                if any(isinstance(block, dict) and str(block.get("type", "")).lower() == "tool_use" for block in blocks):
                    return "正在调用工具处理文件…"
        if event_type == "stream_event":
            event = payload.get("event")
            if isinstance(event, dict):
                delta = event.get("delta")
                if isinstance(delta, dict):
                    dtype = str(delta.get("type", "")).lower()
                    if dtype in {"input_json_delta", "thinking_delta"}:
                        return progress_messages[seen["status_index"] % len(progress_messages)]
        return None

    def handle_line(line: str) -> None:
        if on_delta is None:
            return
        seen["buffer"] += line
        full = _extract_codex_text(seen["buffer"])
        if full and full != seen["text"]:
            if full.startswith(seen["text"]):
                delta = full[len(seen["text"]):]
            else:
                delta = ("\n\n" if seen["text"] else "") + full
            seen["text"] = full
            if delta:
                on_delta(delta)
            return

        # No user-facing text yet, but the provider is alive. Send a throttled
        # temporary status line so long Claude tool/file work doesn't look frozen.
        # Do NOT emit repeated identical status text: it is meant as a heartbeat,
        # not content to accumulate in the chat transcript.
        hint = _provider_activity_hint(line)
        now = time.monotonic()
        if hint and not seen["text"] and (not seen["last_status_at"] or now - seen["last_status_at"] >= 30):
            seen["last_status_at"] = now
            seen["status_index"] += 1
            on_delta(f"⏳ {hint}\n")

    try:
        result = _stream_provider_output(
            cmd,
            cwd=work_dir,
            env={**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"},
            idle_timeout=idle_timeout,
            max_timeout=max_timeout,
            on_chunk=handle_line if on_delta is not None else None,
            run_id=run_id,
        )
    except Exception as exc:
        raise RuntimeError(f"{controller} 后端调用失败：{exc}") from exc

    text = _extract_codex_text(result.stdout) or (result.stdout or result.stderr or "").strip()
    if result.timed_out:
        if text:
            note = f"\n\n（{_controller_label(controller)} 在{result.timeout_reason}后停止，以上为已生成的部分，可继续让它补完。）"
            return _trim_reply(text) + note
        raise TimeoutError(
            f"{controller} 调用因{result.timeout_reason}停止；如果文件已开始生成，请查看文件变更卡片或继续让它补完。"
        )
    if result.returncode == 0:
        return _trim_reply(text) if text else "收到。"
    error_text = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(error_text or f"{controller} exited with code {result.returncode}")


def _parse_unified_diff(text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    old_ln = 0
    new_ln = 0
    for line in text.splitlines():
        if line.startswith("diff --git"):
            match = re.match(r"diff --git a/(.*) b/(.*)", line)
            path = match.group(2) if match else "file"
            current = {"path": path, "status": "modified", "add": 0, "del": 0, "hunks": []}
            files.append(current)
            continue
        if current is None:
            continue
        if line.startswith("new file"):
            current["status"] = "added"
            continue
        if line.startswith("deleted file"):
            current["status"] = "deleted"
            continue
        if line.startswith("rename "):
            current["status"] = "renamed"
            continue
        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("index "):
            continue
        if line.startswith("@@"):
            match = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            old_ln = int(match.group(1)) if match else 0
            new_ln = int(match.group(2)) if match else 0
            current["hunks"].append({"header": line.strip(), "lines": []})
            continue
        if not current["hunks"]:
            continue
        hunk = current["hunks"][-1]
        if line.startswith("+"):
            hunk["lines"].append({"type": "add", "newLine": new_ln, "content": line[1:]})
            current["add"] += 1
            new_ln += 1
        elif line.startswith("-"):
            hunk["lines"].append({"type": "del", "oldLine": old_ln, "content": line[1:]})
            current["del"] += 1
            old_ln += 1
        elif line.startswith(" "):
            hunk["lines"].append({"type": "context", "oldLine": old_ln, "newLine": new_ln, "content": line[1:]})
            old_ln += 1
            new_ln += 1
    return files


_SNAPSHOT_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "target", ".next", ".cache", ".idea", ".vscode", ".pytest_cache", ".mypy_cache",
    ".omx",
}


def _is_git_repo(workspace_path: str) -> bool:
    return bool(workspace_path) and (Path(workspace_path) / ".git").exists()


def _snapshot_contents(workspace_path: str, limit: int = 1500, max_bytes: int = 200_000) -> dict[str, list[str]]:
    """Map of relative path -> file lines for text files (git-free diffing)."""
    root = Path(workspace_path) if workspace_path else None
    snapshot: dict[str, list[str]] = {}
    if root is None or not root.is_dir():
        return snapshot
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SNAPSHOT_SKIP_DIRS]
        for name in filenames:
            file_path = Path(dirpath) / name
            try:
                if file_path.stat().st_size > max_bytes:
                    continue
                rel = str(file_path.relative_to(root))
                snapshot[rel] = file_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            count += 1
            if count >= limit:
                return snapshot
    return snapshot


def _diff_content_snapshots(
    before: dict[str, list[str]],
    after: dict[str, list[str]],
) -> dict[str, Any]:
    """Build a review projection from two content snapshots using difflib (no git)."""
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        prev = before.get(rel)
        curr = after.get(rel)
        if prev == curr:
            continue
        unified = list(
            difflib.unified_diff(
                prev if prev is not None else [],
                curr if curr is not None else [],
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
                n=3,
            )
        )
        if not unified:
            continue
        status_line = ""
        if prev is None:
            status_line = "new file mode 100644\n"
        elif curr is None:
            status_line = "deleted file mode 100644\n"
        chunks.append(f"diff --git a/{rel} b/{rel}\n{status_line}" + "\n".join(unified))

    files = _parse_unified_diff("\n".join(chunks))
    total_add = sum(item["add"] for item in files)
    total_del = sum(item["del"] for item in files)
    summary = "工作区暂无改动。" if not files else f"{len(files)} 个文件 · +{total_add} -{total_del}"
    return {"baseRef": "—", "headRef": "工作区", "files": files, "summary": summary}


def _build_review_projection(workspace_path: str) -> dict[str, Any]:
    root = Path(workspace_path) if workspace_path else None
    if root is None or not (root / ".git").exists():
        return {"files": [], "summary": "非 Git 仓库，暂无改动。"}
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "HEAD", "--no-color", "--unified=3"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"files": [], "summary": f"读取 diff 失败：{exc}"}
    files = _parse_unified_diff(proc.stdout or "")
    # Include untracked files as fully-added so new work shows up too.
    try:
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        for rel in (untracked.stdout or "").splitlines():
            rel = rel.strip()
            if not rel:
                continue
            file_path = root / rel
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue
            content_lines = content.splitlines()
            files.append(
                {
                    "path": rel,
                    "status": "added",
                    "add": len(content_lines),
                    "del": 0,
                    "hunks": [
                        {
                            "header": f"@@ -0,0 +1,{len(content_lines)} @@",
                            "lines": [
                                {"type": "add", "newLine": index + 1, "content": text}
                                for index, text in enumerate(content_lines[:200])
                            ],
                        }
                    ],
                }
            )
    except Exception:  # noqa: BLE001
        pass
    total_add = sum(item["add"] for item in files)
    total_del = sum(item["del"] for item in files)
    summary = "工作区暂无未提交改动。" if not files else f"{len(files)} 个文件 · +{total_add} -{total_del}"
    return {"baseRef": "HEAD", "headRef": "工作区", "files": files, "summary": summary}


def _controller_label(controller: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "gemini": "Gemini",
    }.get(controller, controller.title() or "AI")


def _message(run_id: str, role: str, actor: str, content: str, *, status: str = "complete") -> dict[str, Any]:
    return {
        "id": f"msg-{int(time.time() * 1000)}-{threading.get_ident()}",
        "runId": run_id,
        "role": role,
        "actor": actor,
        "content": content,
        "createdAt": _now_iso(),
        "status": status,
    }


@dataclass
class RunRecord:
    id: str
    title: str
    objective: str
    workspace: dict[str, Any]
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    final_response: dict[str, Any] | None = None
    terminal: dict[str, Any] | None = None
    review: dict[str, Any] | None = None

    def to_projection(self) -> dict[str, Any]:
        workspace_path = str(self.workspace.get("absolutePath", "")).strip()
        workspace_id = str(self.workspace.get("id", "")).strip()
        if not workspace_id and workspace_path:
            workspace_id = _workspace_id(Path(workspace_path))
        if not workspace_id:
            workspace_id = "workspace"
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": "聊天驱动会话",
            "status": "running",
            "owner": "AI",
            "objective": self.objective,
            "workspaceId": workspace_id,
            "workspacePath": workspace_path,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "durationMs": _format_duration(self.created_at),
            "health": 12,
            "agents": [],
            "timeline": self.timeline,
            "messages": self.messages,
            "approvals": self.approvals,
            "review": self.review,
            "terminal": self.terminal,
            "finalResponse": self.final_response,
        }


class WebApiState:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.state_path = self.workspace_root / ".ai-collab" / "web-state.json"
        self.lock = threading.RLock()
        self.config = Config.load()
        self.settings = {
            "theme": "dark",
            "compactLayout": True,
            "defaultRuntime": "codex",
            "approvalPolicy": "balanced",
            "autoOpenInspector": True,
            "recentWorkspaceLimit": 6,
            "autoRoute": True,
        }
        self.workspaces: list[dict[str, Any]] = []
        self.runs: dict[str, RunRecord] = {}
        self.subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}
        self.reply_jobs: dict[str, threading.Thread] = {}
        # In-memory baseline of workspace file contents per run (non-git change tracking).
        self.content_baselines: dict[str, dict[str, list[str]]] = {}
        self.load()

    def load(self) -> None:
        if not self.state_path.exists():
            self.workspaces = [_workspace_summary(self.workspace_root)]
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            self.workspaces = [_workspace_summary(self.workspace_root)]
            return

        self.workspaces = list(raw.get("workspaces", [])) or [_workspace_summary(self.workspace_root)]
        raw_settings = raw.get("settings", {})
        if isinstance(raw_settings, dict):
            self.settings.update({key: raw_settings.get(key, value) for key, value in self.settings.items()})
        self.runs = {}
        for item in raw.get("runs", []):
            if not isinstance(item, dict):
                continue
            workspace = _resolve_run_workspace(item, self.workspaces, self.workspace_root)
            run = RunRecord(
                id=str(item.get("id", "")).strip(),
                title=str(item.get("title", "")).strip() or "Chat",
                objective=str(item.get("objective", "")).strip(),
                workspace=workspace if isinstance(workspace, dict) else _workspace_summary(self.workspace_root),
                created_at=str(item.get("createdAt", _now_iso())),
                updated_at=str(item.get("updatedAt", _now_iso())),
                messages=list(item.get("messages", [])) if isinstance(item.get("messages", []), list) else [],
                approvals=list(item.get("approvals", [])) if isinstance(item.get("approvals", []), list) else [],
                timeline=list(item.get("timeline", [])) if isinstance(item.get("timeline", []), list) else [],
                final_response=item.get("finalResponse") if isinstance(item.get("finalResponse"), dict) else None,
                terminal=item.get("terminal") if isinstance(item.get("terminal"), dict) else None,
                review=item.get("review") if isinstance(item.get("review"), dict) else None,
            )
            if run.id:
                self.runs[run.id] = run

    def save(self) -> None:
        payload = {
            "workspaces": self.workspaces,
            "settings": self.settings,
            "runs": [run.to_projection() for run in self.runs.values()],
            "savedAt": _now_iso(),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    def add_workspace(self, path: Path) -> dict[str, Any]:
        workspace = _workspace_summary(path)
        self.workspaces = [workspace, *[item for item in self.workspaces if item.get("id") != workspace["id"]]]
        self.save()
        return workspace

    def create_run(self, workspace_path: Path, objective: str) -> RunRecord:
        workspace = self.add_workspace(workspace_path)
        run_id = f"run-{int(time.time())}-{os.getpid()}"
        now = _now_iso()
        run = RunRecord(
            id=run_id,
            title=objective[:24] or "Chat",
            objective=objective,
            workspace=workspace,
            created_at=now,
            updated_at=now,
            messages=[_message(run_id, "user", "You", objective)],
            timeline=[
                {
                    "id": f"tl-{run_id}",
                    "runId": run_id,
                    "time": _clock_now(),
                    "type": "system",
                    "title": "Run 创建",
                    "detail": "已根据首条需求创建会话。",
                    "actor": "ai-collab",
                }
            ],
            terminal={
                "sessionId": f"term-{run_id}",
                "runId": run_id,
                "cwd": str(workspace_path.resolve()),
                "shell": "zsh",
                "status": "idle",
                "lines": [],
            },
        )
        self.runs[run_id] = run
        if not _is_git_repo(str(workspace_path)):
            self.content_baselines[run_id] = _snapshot_contents(str(workspace_path.resolve()))
        self.save()
        return run

    def broadcast(self, run_id: str, event_type: str, payload: Any) -> None:
        listeners = list(self.subscribers.get(run_id, []))
        for listener in listeners:
            try:
                listener.put_nowait({"event": event_type, "payload": payload})
            except queue.Full:
                pass

    def update_run(self, run: RunRecord, event_type: str = "run.updated") -> None:
        run.updated_at = _now_iso()
        self.save()
        self.broadcast(run.id, event_type, run.to_projection())

    def delete_run(self, run_id: str) -> bool:
        with self.lock:
            run = self.runs.pop(run_id, None)
            self.reply_jobs.pop(run_id, None)
        if run is None:
            return False
        self.save()
        return True

    @staticmethod
    def _local_date(iso: Any):
        try:
            return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().date()
        except Exception:
            return None

    def dashboard_summary(self) -> dict[str, Any]:
        runs = list(self.runs.values())
        total_messages = sum(len(run.messages) for run in runs)
        replies = sum(1 for run in runs for message in run.messages if str(message.get("role")) == "assistant")
        pending = sum(1 for run in runs for approval in run.approvals if str(approval.get("status")) == "pending")
        return {
            "sessions": len(runs),
            "messages": total_messages,
            "replies": replies,
            "approvals": pending,
        }

    def dashboard_activity(self, days: int) -> list[dict[str, Any]]:
        days = max(1, min(days, 60))
        buckets: dict[Any, dict[str, int]] = defaultdict(lambda: {"user": 0, "assistant": 0, "terminal": 0})
        for run in self.runs.values():
            for message in run.messages:
                day = self._local_date(message.get("createdAt"))
                role = str(message.get("role", ""))
                if day is not None and role in ("user", "assistant"):
                    buckets[day][role] += 1
            terminal = run.terminal or {}
            for line in terminal.get("lines", []) or []:
                day = self._local_date(line.get("createdAt"))
                if day is not None:
                    buckets[day]["terminal"] += 1
        today = datetime.now().date()
        points: list[dict[str, Any]] = []
        for index in range(days):
            day = today - timedelta(days=days - 1 - index)
            bucket = buckets.get(day, {"user": 0, "assistant": 0, "terminal": 0})
            points.append(
                {
                    "day": day.isoformat(),
                    "review": bucket["user"],
                    "terminal": bucket["terminal"],
                    "agent": bucket["assistant"],
                }
            )
        return points

    def reply_to_run(self, run: RunRecord, user_message: str) -> dict[str, Any]:
        workspace_path = str(run.workspace.get("absolutePath", "")).strip()
        if self.settings.get("autoRoute", True):
            controller = _route_controller(self.config, user_message, cwd=workspace_path)
        else:
            controller = self.config.current_controller
        is_git = _is_git_repo(workspace_path)
        before_sig: dict[str, tuple] = {}
        before_content: dict[str, list[str]] = {}
        if is_git:
            before_sig = {item["path"]: (item.get("add"), item.get("del"), item.get("status")) for item in _build_review_projection(workspace_path).get("files", [])}
        else:
            before_content = _snapshot_contents(workspace_path)
        label = _controller_label(controller)
        assistant_message = _message(run.id, "assistant", label, "", status="streaming")
        assistant_message["model"] = controller
        # Publish the streaming placeholder up front so the UI shows "回复中" while
        # the provider works, then push deltas as they arrive (no 45s cutoff).
        run.messages.append(assistant_message)
        self.broadcast(run.id, "run.updated", {"type": "run.updated", "run": run.to_projection()})

        def on_delta(delta: str) -> None:
            self.broadcast(
                run.id,
                "message.delta",
                {"type": "message.delta", "runId": run.id, "messageId": assistant_message["id"], "delta": delta},
            )

        try:
            # Exclude the just-appended empty placeholder from prompt history.
            assistant_text = _run_provider_reply(
                self.config, run.messages[:-1], user_message, cwd=workspace_path, controller=controller, on_delta=on_delta, run_id=run.id
            )
        except Exception as exc:
            assistant_text = _trim_reply(str(exc))
        with _ACTIVE_PROVIDER_LOCK:
            was_cancelled = run.id in _CANCELLED_PROVIDER_RUNS
            _CANCELLED_PROVIDER_RUNS.discard(run.id)
        if was_cancelled:
            assistant_text = (assistant_text.strip() + "\n\n" if assistant_text.strip() else "") + "（已终止本次回复。）"
        # Detect files this reply created/changed. With git, diff the working tree;
        # otherwise diff file contents captured before/after the reply.
        file_ops: list[dict[str, Any]] = []
        if is_git:
            after_review = _build_review_projection(workspace_path)
            for item in after_review.get("files", []):
                signature = (item.get("add"), item.get("del"), item.get("status"))
                if before_sig.get(item["path"]) != signature:
                    file_ops.append({"path": item["path"], "change": item.get("status", "modified"), "add": item.get("add", 0), "del": item.get("del", 0)})
        else:
            after_content = _snapshot_contents(workspace_path)
            # Per-turn changes (only what this reply touched) → message cards.
            turn_review = _diff_content_snapshots(before_content, after_content)
            for item in turn_review.get("files", []):
                file_ops.append({"path": item["path"], "change": item.get("status", "modified"), "add": item.get("add", 0), "del": item.get("del", 0)})
            # Cumulative session changes (vs the run's baseline) → the DIFF panel.
            baseline = self.content_baselines.get(run.id)
            if baseline is None:
                baseline = before_content
                self.content_baselines[run.id] = baseline
            after_review = _diff_content_snapshots(baseline, after_content)
        if file_ops:
            assistant_message["fileOps"] = file_ops
        run.review = after_review
        # The placeholder is already in run.messages and was streamed via on_delta;
        # finalize it with the authoritative full text (replaces by id on the client).
        assistant_message["content"] = assistant_text
        assistant_message["status"] = "complete"
        self.broadcast(run.id, "message.completed", {"type": "message.completed", "message": assistant_message})
        if file_ops:
            self.broadcast(run.id, "review.updated", {"type": "review.updated", "runId": run.id, "review": after_review})
        run.title = _compact_title(run.objective or user_message, assistant_text)
        run.updated_at = _now_iso()
        self.save()
        self.broadcast(run.id, "run.updated", {"type": "run.updated", "run": run.to_projection()})
        return assistant_message

    def cancel_run(self, run_id: str) -> RunRecord | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        killed = _cancel_provider_run(run_id)
        # Always force any streaming assistant message(s) complete. This is critical
        # for stale UI state: the provider process may have died or the registry may
        # be lost after a backend restart, but the user must still be able to unlock
        # the chat and continue.
        for message in run.messages:
            if str(message.get("role")) == "assistant" and str(message.get("status")) == "streaming":
                if not str(message.get("content") or "").strip():
                    message["content"] = "已终止本次回复。"
                elif "已终止本次回复" not in str(message.get("content") or ""):
                    message["content"] = str(message.get("content") or "").rstrip() + "\n\n（已终止本次回复。）"
                message["status"] = "complete"
                self.broadcast(run.id, "message.completed", {"type": "message.completed", "message": message})
        run.timeline.insert(0, {
            "id": f"tl-{run.id}-{time.time_ns()}",
            "runId": run.id,
            "time": _clock_now(),
            "type": "system",
            "title": "已终止回复" if killed else "终止请求已处理",
            "detail": "用户停止了当前 AI 进程。" if killed else "当前没有正在运行的 AI 进程。",
            "actor": "ai-collab",
        })
        self.update_run(run)
        return run

    def append_user_message(self, run: RunRecord, content: str) -> dict[str, Any]:
        message = _message(run.id, "user", "You", content)
        run.messages.append(message)
        run.timeline.insert(
            0,
            {
                "id": f"tl-{run.id}-{len(run.timeline)}",
                "runId": run.id,
                "time": _clock_now(),
                "type": "system",
                "title": "收到用户消息",
                "detail": content,
                "actor": "ai-collab",
            },
        )
        self.update_run(run)
        return message

    def reply_async(self, run: RunRecord, user_message: str) -> None:
        def worker() -> None:
            self.reply_to_run(run, user_message)
            with self.lock:
                self.reply_jobs.pop(run.id, None)

        thread = threading.Thread(target=worker, daemon=True)
        with self.lock:
            self.reply_jobs[run.id] = thread
        thread.start()


class WebApiHandler(BaseHTTPRequestHandler):
    server_version = "ai-collab-web-api/0.1"

    @property
    def state(self) -> WebApiState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def handle(self) -> None:
        # Clients (SSE streams, aborted fetches) routinely reset the socket;
        # swallow those so they don't spam the console with tracebacks.
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def _run_by_id(self, run_id: str) -> RunRecord | None:
        return self.state.runs.get(run_id)

    def _open_sse(self, run_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        run = self.state.runs[run_id]
        workspace_path = str(run.workspace.get("absolutePath", ""))
        if _is_git_repo(workspace_path):
            run.review = _build_review_projection(workspace_path)
        _write_sse(self, "run.updated", {"type": "run.updated", "run": run.to_projection()})
        listener: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        self.state.subscribers.setdefault(run_id, []).append(listener)
        try:
            while True:
                try:
                    event = listener.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                _write_sse(self, event["event"], event["payload"])
        except (BrokenPipeError, ConnectionResetError, ValueError):
            pass
        finally:
            self.state.subscribers.get(run_id, []).remove(listener)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/runs/") and path.count("/") == 3:
            run_id = path.split("/")[3]
            if not self.state.delete_run(run_id):
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, {"ok": True})
        return _write_json(self, 404, {"message": "Not found"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/ping":
            return _write_json(self, 200, {"ok": True, "time": _now_iso()})
        if path == "/api/workspaces/recent":
            return _write_json(self, 200, self.state.workspaces)
        if path.startswith("/api/workspaces/") and path.endswith("/summary"):
            return _write_json(self, 200, self.state.workspaces[0] if self.state.workspaces else _workspace_summary(self.state.workspace_root))
        if path.startswith("/api/workspaces/") and path.endswith("/tree"):
            return _write_json(self, 200, {"path": str(self.state.workspace_root), "entries": []})
        if path == "/api/runs":
            runs = sorted(self.state.runs.values(), key=lambda item: item.updated_at, reverse=True)
            return _write_json(self, 200, [run.to_projection() for run in runs])
        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return self._open_sse(run_id)
        if path.startswith("/api/runs/") and path.endswith("/messages"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, run.messages)
        if path.startswith("/api/runs/") and path.endswith("/approvals"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, run.approvals)
        if path.startswith("/api/runs/") and (path.endswith("/review") or path.endswith("/diff")):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            workspace_path = str(run.workspace.get("absolutePath", ""))
            if _is_git_repo(workspace_path):
                run.review = _build_review_projection(workspace_path)
            return _write_json(self, 200, run.review or {"files": [], "summary": "暂无改动。"})
        if path.startswith("/api/runs/") and path.endswith("/final-response"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, run.final_response)
        if path.startswith("/api/runs/"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, run.to_projection())
        if path == "/api/dashboard/summary":
            return _write_json(self, 200, self.state.dashboard_summary())
        if path == "/api/dashboard/activity":
            days = int((query.get("days") or ["18"])[0])
            return _write_json(self, 200, self.state.dashboard_activity(days))
        if path == "/api/settings":
            return _write_json(self, 200, self.state.settings)
        return _write_json(self, 404, {"message": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/workspaces/pick":
            try:
                picked = _pick_local_folder()
            except Exception as exc:
                return _write_json(self, 500, {"message": str(exc)})
            if not picked:
                return _write_json(self, 200, {"canceled": True})
            workspace = self.state.add_workspace(Path(picked).expanduser().resolve())
            return _write_json(self, 200, {"canceled": False, "workspace": workspace})
        if path == "/api/workspaces/open":
            body = _read_json(self)
            raw_path = str(body.get("path", "")).strip()
            if not raw_path:
                return _write_json(self, 400, {"message": "path is required"})
            workspace = Path(raw_path).expanduser().resolve()
            self.state.add_workspace(workspace)
            return _write_json(self, 200, _workspace_summary(workspace))
        if path == "/api/runs":
            body = _read_json(self)
            workspace_id = str(body.get("workspaceId", "")).strip()
            objective = str(body.get("objective", "")).strip()
            workspace = next((Path(item["absolutePath"]) for item in self.state.workspaces if item.get("id") == workspace_id), None)
            if workspace is None:
                return _write_json(self, 404, {"message": "Workspace not found"})
            if not objective:
                return _write_json(self, 400, {"message": "Objective is required."})
            run = self.state.create_run(workspace, objective)
            self.state.reply_async(run, objective)
            return _write_json(self, 200, run.to_projection())
        if path.startswith("/api/runs/") and path.endswith("/cancel"):
            run_id = path.split("/")[3]
            run = self.state.cancel_run(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, run.to_projection())
        if path.startswith("/api/runs/") and path.count("/") == 3:
            run_id = path.split("/")[3]
            if not self.state.delete_run(run_id):
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, {"ok": True})
        if path.startswith("/api/runs/") and path.endswith("/messages"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            body = _read_json(self)
            content = str(body.get("content", "")).strip()
            if not content:
                return _write_json(self, 400, {"message": "Message content is required."})
            user_message = self.state.append_user_message(run, content)
            self.state.reply_async(run, content)
            return _write_json(self, 200, {"message": user_message, "run": run.to_projection()})
        if path.startswith("/api/runs/") and path.endswith("/cancel"):
            run_id = path.split("/")[3]
            run = self.state.cancel_run(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            return _write_json(self, 200, run.to_projection())
        if path.startswith("/api/runs/") and path.endswith("/terminal"):
            run_id = path.split("/")[3]
            run = self._run_by_id(run_id)
            if run is None:
                return _write_json(self, 404, {"message": "Run not found"})
            body = _read_json(self)
            cwd = str(body.get("cwd") or run.workspace["absolutePath"]).strip()
            shell = str(body.get("shell") or "zsh").strip()
            run.terminal = {
                "sessionId": f"term-{run.id}",
                "runId": run.id,
                "cwd": cwd,
                "shell": shell,
                "status": "idle",
                "lines": [],
            }
            self.state.save()
            return _write_json(self, 200, run.terminal)
        if path.startswith("/api/terminal/") and path.endswith("/input"):
            session_id = path.split("/")[3]
            body = _read_json(self)
            command = str(body.get("command", "")).strip()
            if not command:
                return _write_json(self, 400, {"message": "command is required"})
            run = next((item for item in self.state.runs.values() if item.terminal and item.terminal.get("sessionId") == session_id), None)
            if run is None:
                return _write_json(self, 404, {"message": "Terminal session not found"})
            run.terminal.setdefault("lines", []).append({"id": f"ln-{time.time_ns()}", "text": command, "kind": "input", "createdAt": _now_iso()})
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=run.terminal.get("cwd") or run.workspace["absolutePath"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                output = (result.stdout or result.stderr or "").strip()
            except Exception as exc:
                output = str(exc)
            if output:
                run.terminal["lines"].append({"id": f"ln-{time.time_ns()}", "text": output, "kind": "output", "createdAt": _now_iso()})
            # A command may have changed files — refresh the diff (git repos only) and push it.
            workspace_path = str(run.workspace.get("absolutePath", ""))
            if _is_git_repo(workspace_path):
                run.review = _build_review_projection(workspace_path)
                self.state.broadcast(run.id, "review.updated", {"type": "review.updated", "runId": run.id, "review": run.review})
            self.state.save()
            return _write_json(self, 200, run.terminal)
        if path.startswith("/api/terminal/") and path.endswith("/kill"):
            session_id = path.split("/")[3]
            run = next((item for item in self.state.runs.values() if item.terminal and item.terminal.get("sessionId") == session_id), None)
            if run is None:
                return _write_json(self, 404, {"message": "Terminal session not found"})
            run.terminal["status"] = "closed"
            self.state.save()
            return _write_json(self, 200, run.terminal)
        if path.startswith("/api/approvals/"):
            return _write_json(self, 404, {"message": "Approvals are not modeled by the Python adapter yet"})
        return _write_json(self, 404, {"message": "Not found"})

    def do_PATCH(self) -> None:  # noqa: N802
        if self.path != "/api/settings":
            return _write_json(self, 404, {"message": "Not found"})
        body = _read_json(self)
        self.state.settings.update({key: body[key] for key in self.state.settings.keys() if key in body})
        self.state.save()
        return _write_json(self, 200, self.state.settings)


def run_web_api(*, workspace_root: Path, port: int = 8787) -> None:
    state = WebApiState(workspace_root)
    server = ThreadingHTTPServer(("127.0.0.1", port), WebApiHandler)
    server.state = state  # type: ignore[attr-defined]
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="ai-collab web api")
    parser.add_argument("--workspace-root", default=".", help="Workspace root for saved web state")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    args = parser.parse_args()
    run_web_api(workspace_root=Path(args.workspace_root), port=args.port)


if __name__ == "__main__":
    main()
