"""Workflow management module."""

from __future__ import annotations

import codecs
import copy
import errno
import os
import pty
import queue
import select
import shlex
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field

from ai_collab.core.config import Config
from ai_collab.core.selector import ModelSelector
from ai_collab.core.environment import resolve_subprocess_command
from ai_collab.core.workflow_v2 import (
    builtin_session_presets,
    find_session_preset_for_workflow_blueprint,
    resolve_session_preset,
    resolve_workflow_blueprint,
)


DEFAULT_PERSONA_PHASE_MAP = {
    "collect": "research-analyst",
    "model": "requirements-architect",
    "plan": "requirements-architect",
    "artifact": "frontend-designer",
    "execute": "implementation-engineer",
    "validate": "quality-auditor",
    "correct": "implementation-engineer",
    "deliver": "quality-auditor",
    "discover": "research-analyst",
    "define": "requirements-architect",
    "develop": "implementation-engineer",
    "deliver": "quality-auditor",
    "design": "frontend-designer",
    "review": "quality-auditor",
    "audit": "security-auditor",
    "debug": "debugger",
    "test": "test-engineer",
}

DEFAULT_PERSONA_SKILL_MAP = {
    "research-analyst": ["ecosystem-research", "alternatives-matrix"],
    "requirements-architect": ["scope-control", "tradeoff-analysis"],
    "implementation-engineer": ["feature-implementation", "integration-check"],
    "quality-auditor": ["code-review", "risk-review"],
    "frontend-designer": ["frontend-mockup-designer", "responsive-layout"],
    "security-auditor": ["security-review", "owasp-checklist"],
    "debugger": ["systematic-debugging", "trace-analysis"],
    "test-engineer": ["tests-first", "coverage-validation"],
}

DEFAULT_PHASE_COMPLETION_CRITERIA = {
    "default": {"min_output_chars": 30, "must_succeed": True},
    "collect": {"min_output_chars": 80},
    "model": {"min_output_chars": 80},
    "plan": {"min_output_chars": 60},
    "artifact": {"min_output_chars": 60},
    "execute": {"min_output_chars": 80},
    "validate": {"min_output_chars": 60},
    "correct": {"min_output_chars": 60},
    "deliver": {"min_output_chars": 60},
    "discover": {"min_output_chars": 80},
    "define": {"min_output_chars": 60},
    "develop": {"min_output_chars": 80},
    "deliver": {"min_output_chars": 60},
}

DEFAULT_ESCALATION_POLICY = {
    "max_retries": 1,
    "takeover_agent": "codex",
    "takeover_after_failures": 2,
    "ask_user_on_repeated_failure": True,
    "stop_on_failure": True,
}

WORKFLOW_I18N = {
    "en-US": {
        "phase_title": "Phase {index}/{total} · {action}",
        "phase_agent": "Agent: {agent} · Persona: {persona}",
        "phase_skills": "Skills: {skills}",
        "phase_attempt": "Attempt {attempt}",
        "phase_start": "Start execution",
        "invoking": "Invoking {agent}",
        "timeout": "Timeout {timeout}s",
        "success": "{agent} completed",
        "failed": "{agent} failed",
        "failed_detail": "Error output:",
        "timeout_failed": "{agent} timed out after {timeout}s",
        "retry": "Retry {attempt}/{attempt_limit} · {action} · reason: {error}",
        "takeover": "Escalation trigger={trigger}. Taking over with {agent}.",
        "failure_prompt": (
            "\nPhase '{action}' failed {count} times for task '{task}'.\n"
            "Choose action [retry/takeover/skip/abort] (default: abort): "
        ),
        "execution_failed": "execution failed",
        "output_too_short": "Output too short ({current} < {minimum})",
        "missing_required_tokens": "Missing required tokens: {tokens}",
    },
    "zh-CN": {
        "phase_title": "阶段 {index}/{total} · {action}",
        "phase_agent": "代理: {agent} · 角色: {persona}",
        "phase_skills": "技能: {skills}",
        "phase_attempt": "第 {attempt} 次尝试",
        "phase_start": "开始执行",
        "invoking": "调用 {agent}",
        "timeout": "超时 {timeout}s",
        "success": "{agent} 已完成",
        "failed": "{agent} 执行失败",
        "failed_detail": "错误输出:",
        "timeout_failed": "{agent} 执行超时（{timeout}s）",
        "retry": "准备重试 {attempt}/{attempt_limit} · {action} · 原因: {error}",
        "takeover": "触发接管: {trigger}，改由 {agent} 执行。",
        "failure_prompt": (
            "\n阶段 '{action}' 在任务 '{task}' 上已失败 {count} 次。\n"
            "选择后续动作 [retry/takeover/skip/abort]（默认: abort）: "
        ),
        "execution_failed": "执行失败",
        "output_too_short": "输出过短（{current} < {minimum}）",
        "missing_required_tokens": "缺少必需标记: {tokens}",
    },
}

V2_INTENT_PRESET_MAP = {
    "design": "design-first",
    "documentation": "auto",
    "research": "research-priority",
    "architecture": "research-priority",
    "implementation": "auto",
    "debug": "debug-priority",
    "security": "auto",
    "testing": "auto",
    "gameplay": "design-first",
}


def _run_command_live(
    cmd: list[str],
    *,
    timeout: int | None,
    line_prefix: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run provider command with a PTY when possible so output streams live like tmux."""
    if os.name != "posix":
        return _run_command_live_pipe(cmd, timeout=timeout, line_prefix=line_prefix)
    return _run_command_live_pty(cmd, timeout=timeout, line_prefix=line_prefix)


def _emit_stream_text(text: str, *, target: Any, line_prefix: str, at_line_start: bool) -> bool:
    """Render provider output with a stable prefix so system status and model output stay separated."""
    if not text:
        return at_line_start
    segments = text.splitlines(keepends=True)
    for segment in segments:
        if at_line_start and line_prefix:
            target.write(line_prefix)
        target.write(segment)
        at_line_start = segment.endswith(("\n", "\r"))
    target.flush()
    return at_line_start


def _run_command_live_pipe(
    cmd: list[str],
    *,
    timeout: int | None,
    line_prefix: str = "",
) -> subprocess.CompletedProcess[str]:
    """Fallback live runner for non-POSIX environments."""
    process = subprocess.Popen(
        cmd,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stream_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def _reader(stream, stream_name: str, sink: list[str]) -> None:  # noqa: ANN001
        try:
            if stream is None:
                return
            for line in iter(stream.readline, ""):
                sink.append(line)
                stream_queue.put((stream_name, line))
        finally:
            if stream is not None:
                stream.close()
            stream_queue.put((stream_name, None))

    stdout_thread = threading.Thread(target=_reader, args=(process.stdout, "stdout", stdout_chunks), daemon=True)
    stderr_thread = threading.Thread(target=_reader, args=(process.stderr, "stderr", stderr_chunks), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    start_time = time.time()
    stdout_line_start = True
    stderr_line_start = True

    while True:
        while True:
            try:
                stream_name, line = stream_queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                continue
            target = sys.stderr if stream_name == "stderr" else sys.stdout
            if stream_name == "stderr":
                stderr_line_start = _emit_stream_text(
                    line,
                    target=target,
                    line_prefix=line_prefix,
                    at_line_start=stderr_line_start,
                )
            else:
                stdout_line_start = _emit_stream_text(
                    line,
                    target=target,
                    line_prefix=line_prefix,
                    at_line_start=stdout_line_start,
                )
        if process.poll() is not None:
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            if not stdout_line_start:
                sys.stdout.write("\n")
                sys.stdout.flush()
            if not stderr_line_start:
                sys.stderr.write("\n")
                sys.stderr.flush()
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=process.returncode,
                stdout="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
            )
        if timeout is not None and time.time() - start_time > timeout:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            if not stdout_line_start:
                sys.stdout.write("\n")
                sys.stdout.flush()
            if not stderr_line_start:
                sys.stderr.write("\n")
                sys.stderr.flush()
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=timeout,
                output="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
            )
        time.sleep(0.05)


def _run_command_live_pty(
    cmd: list[str],
    *,
    timeout: int | None,
    line_prefix: str = "",
) -> subprocess.CompletedProcess[str]:
    """POSIX live runner using PTY so provider CLIs behave like interactive panes."""
    master_fd, slave_fd = pty.openpty()
    process = None
    output_chunks: list[bytes] = []
    decoder = codecs.getincrementaldecoder(getattr(sys.stdout, "encoding", None) or "utf-8")("replace")
    start_time = time.time()
    line_start = True
    try:
        process = subprocess.Popen(
            cmd,
            shell=False,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    finally:
        os.close(slave_fd)

    try:
        while True:
            if timeout is not None and time.time() - start_time > timeout:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                text_output = b"".join(output_chunks).decode("utf-8", errors="replace")
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=text_output)

            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        chunk = b""
                    else:
                        raise
                if chunk:
                    output_chunks.append(chunk)
                    rendered = decoder.decode(chunk)
                    if rendered:
                        line_start = _emit_stream_text(
                            rendered,
                            target=sys.stdout,
                            line_prefix=line_prefix,
                            at_line_start=line_start,
                        )
            if process.poll() is not None and not ready:
                break

        trailing = decoder.decode(b"", final=True)
        if trailing:
            line_start = _emit_stream_text(
                trailing,
                target=sys.stdout,
                line_prefix=line_prefix,
                at_line_start=line_start,
            )
        if not line_start:
            sys.stdout.write("\n")
            sys.stdout.flush()
        text_output = b"".join(output_chunks).decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=process.returncode,
            stdout=text_output,
            stderr="",
        )
    finally:
        os.close(master_fd)


class WorkflowPhase(BaseModel):
    """Workflow phase definition."""

    agent: str
    action: str
    output: str
    timeout: Optional[int] = None
    skills: list[str] = Field(default_factory=list)
    responsibility_stage: str = ""
    artifact_type: str = ""
    allowed_artifacts: list[str] = Field(default_factory=list)
    boundary: str = ""
    timebox_minutes: Optional[int] = None
    goal: str = ""


class Workflow(BaseModel):
    """Workflow definition."""

    name: str
    description: str
    phases: list[WorkflowPhase]


class WorkflowManager:
    """Manages workflow execution."""

    def __init__(self, config: Config):
        self.config = config
        self.selector = ModelSelector(config)

    def _ui_language(self) -> str:
        """Return supported UI language for workflow runtime messages."""
        lang = str(getattr(self.config, "ui_language", "en-US") or "en-US").strip()
        return lang if lang in WORKFLOW_I18N else "en-US"

    def _wf_msg(self, key: str, **kwargs: Any) -> str:
        """Resolve localized workflow message."""
        lang = self._ui_language()
        template = WORKFLOW_I18N.get(lang, WORKFLOW_I18N["en-US"]).get(key, key)
        return template.format(**kwargs)

    def _print_phase_banner(self, *, index: int, total: int, resolved_phase: Dict[str, Any]) -> None:
        """Render a compact phase banner before provider output starts."""
        print()
        print(f"┌─ {self._wf_msg('phase_title', index=index, total=total, action=resolved_phase['action'])}")
        print(f"│ {self._wf_msg('phase_agent', agent=resolved_phase['agent'], persona=resolved_phase['persona'])}")
        if resolved_phase["active_skills"]:
            print(f"│ {self._wf_msg('phase_skills', skills=', '.join(resolved_phase['active_skills']))}")
        print(f"└─ {self._wf_msg('phase_start')}")

    def _print_status_line(self, message: str, *, marker: str = "├─") -> None:
        """Print a compact workflow status line."""
        print(f"{marker} {message}")

    def _print_buffered_detail(self, text: str) -> None:
        """Render captured stderr/stdout as indented body text."""
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        for line in cleaned.splitlines():
            print(f"│ {line}")

    def execute_workflow(
        self,
        route_key: str,
        task: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a V2 route using stage-based orchestration."""
        route_key = str(route_key or "").strip()
        execution = self._resolve_execution_target(route_key=route_key, context=context)
        workflow = execution["workflow"]
        results: Dict[str, Any] = {}
        summary: Dict[str, Any] = {
            "status": "completed",
            "workflow": workflow.name,
            "requested_route": route_key,
            "total_phases": len(workflow.phases),
            "completed_phases": 0,
            "skipped_phases": 0,
        }
        summary.update(execution["summary_meta"])

        for index, phase in enumerate(workflow.phases, 1):
            resolved_phase = self._resolve_phase_plan(phase, context)
            self._print_phase_banner(index=index, total=len(workflow.phases), resolved_phase=resolved_phase)

            phase_result = self._execute_phase_with_policy(
                resolved_phase=resolved_phase,
                task=task,
                context=context,
                previous_results=results,
            )
            results[f"phase_{index}"] = phase_result

            if phase_result.get("status") == "skipped_by_user":
                summary["skipped_phases"] += 1
                continue

            if phase_result.get("success"):
                summary["completed_phases"] += 1
                continue

            if phase_result.get("status") == "aborted_by_user":
                summary["status"] = "aborted_by_user"
                break

            if self._escalation_policy().get("stop_on_failure", True):
                summary["status"] = "failed"
                break

        if summary["status"] == "completed" and summary["skipped_phases"] > 0:
            summary["status"] = "completed_with_skips"
        results["_summary"] = summary
        return results

    def _resolve_execution_target(
        self,
        *,
        route_key: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve the V2 target route and build executable stages."""
        v2_target = self._resolve_v2_target(route_key=route_key, context=context)
        workflow = self._build_v2_compat_workflow(v2_target["workflow_blueprint"])
        return {
            "workflow": workflow,
            "summary_meta": {
                "workflow_engine": "v2",
                "session_preset": v2_target["session_preset"],
                "workflow_blueprint": v2_target["workflow_blueprint"],
                "compatibility_mode": v2_target["compatibility_mode"],
            },
        }

    def _workflow_engine(self, context: Dict[str, Any]) -> str:
        _ = context
        return "v2"

    def _resolve_v2_target(
        self,
        *,
        route_key: str,
        context: Dict[str, Any],
    ) -> Dict[str, str]:
        workflow_blueprint = str(context.get("workflow_blueprint", "")).strip()
        if not workflow_blueprint and route_key and self._is_v2_blueprint(route_key):
            workflow_blueprint = route_key
        if workflow_blueprint:
            requested_preset = str(context.get("session_preset", "")).strip()
            resolve_workflow_blueprint(workflow_blueprint)
            preset = find_session_preset_for_workflow_blueprint(
                workflow_blueprint,
                preferred=requested_preset,
            ) or requested_preset
            return {
                "session_preset": preset,
                "workflow_blueprint": workflow_blueprint,
                "compatibility_mode": "direct-v2-blueprint",
            }

        session_preset = str(context.get("session_preset", "")).strip()
        if not session_preset and route_key:
            try:
                resolve_session_preset(route_key)
                session_preset = route_key
            except KeyError:
                session_preset = ""
        if session_preset:
            workflow_blueprint = resolve_session_preset(session_preset).workflow_key
            return {
                "session_preset": session_preset,
                "workflow_blueprint": workflow_blueprint,
                "compatibility_mode": "direct-v2-preset",
            }

        if route_key:
            raise ValueError(f"Unknown workflow route: {route_key}")

        intent = str(context.get("intent", "")).strip().lower()
        preset = V2_INTENT_PRESET_MAP.get(intent, self._default_session_preset())
        workflow_blueprint = resolve_session_preset(preset).workflow_key
        return {
            "session_preset": preset,
            "workflow_blueprint": workflow_blueprint,
            "compatibility_mode": "intent-routed-v2",
        }

    def _default_session_preset(self) -> str:
        auto_cfg = self.config.auto_collaboration or {}
        configured = str(auto_cfg.get("default_session_preset", "auto")).strip() or "auto"
        try:
            resolve_session_preset(configured)
            return configured
        except KeyError:
            return "auto"

    def _build_v2_compat_workflow(self, workflow_blueprint: str) -> Workflow:
        """Translate a V2 blueprint into executable phases using the existing runner."""
        blueprint = resolve_workflow_blueprint(workflow_blueprint)
        phases = [
            WorkflowPhase(
                agent=stage.default_agent or self.config.current_controller,
                action=f"{stage.responsibility_stage}:{stage.key}",
                output=stage.outputs[0] if stage.outputs else stage.goal,
                timeout=(int(stage.timebox_minutes) * 60) if stage.timebox_minutes else None,
                skills=[],
                responsibility_stage=stage.responsibility_stage,
                artifact_type=stage.outputs[0] if stage.outputs else "",
                allowed_artifacts=list(stage.allowed_artifacts),
                boundary=stage.boundary,
                timebox_minutes=stage.timebox_minutes,
                goal=stage.goal,
            )
            for stage in blueprint.stages
        ]
        return Workflow(
            name=workflow_blueprint,
            description=blueprint.description,
            phases=phases,
        )

    def _is_v2_blueprint(self, key: str) -> bool:
        candidate = str(key or "").strip()
        if not candidate:
            return False
        try:
            resolve_workflow_blueprint(candidate)
            return True
        except KeyError:
            return False

    def _resolve_phase_plan(self, phase: WorkflowPhase, context: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve phase owner, persona, and active skills with config overrides."""
        auto_cfg = dict(self.config.auto_collaboration or {})
        phase_key = self._normalize_phase_key(phase.action)

        assignment_map = auto_cfg.get("assignment_map", {})
        phase_routing = auto_cfg.get("phase_routing", {})
        assignment = assignment_map.get(phase_key, {}) if isinstance(assignment_map, dict) else {}

        preferred_agent = phase.agent
        if isinstance(phase_routing, dict) and phase_key in phase_routing:
            preferred_agent = str(phase_routing[phase_key])
        if isinstance(assignment, dict) and assignment.get("agent"):
            preferred_agent = str(assignment.get("agent"))
        if preferred_agent not in self.config.providers:
            preferred_agent = phase.agent

        profile = ""
        if isinstance(assignment, dict):
            profile = str(assignment.get("profile", "")).strip()

        phase_skills = self._normalize_skill_input(phase.skills)
        auto_skills = self._normalize_skill_input(context.get("auto_skills", []))
        merged_for_persona = self._dedupe_skills(phase_skills + auto_skills)
        persona, persona_skills = self._resolve_persona(phase_key, phase.action, merged_for_persona)
        active_skills = self._dedupe_skills(phase_skills + auto_skills + persona_skills)

        return {
            "agent": preferred_agent,
            "profile": profile,
            "action": phase.action,
            "output": phase.output,
            "timeout": phase.timeout,
            "phase_key": phase_key,
            "persona": persona,
            "active_skills": active_skills,
            "goal": phase.goal,
            "responsibility_stage": phase.responsibility_stage,
            "artifact_type": phase.artifact_type,
            "allowed_artifacts": list(phase.allowed_artifacts),
            "boundary": phase.boundary,
            "timebox_minutes": phase.timebox_minutes,
        }

    def _execute_phase_with_policy(
        self,
        resolved_phase: Dict[str, Any],
        task: str,
        context: Dict[str, Any],
        previous_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute phase with retries, takeover, and optional user escalation."""
        policy = self._escalation_policy()
        max_retries = max(0, int(policy.get("max_retries", 0)))
        takeover_after_failures = max(1, int(policy.get("takeover_after_failures", 2)))
        failure_history: list[Dict[str, Any]] = []

        attempts = 0
        while attempts < max_retries + 1:
            attempts += 1
            attempt_result = self._execute_phase_once(
                resolved_phase=resolved_phase,
                task=task,
                context=context,
                previous_results=previous_results,
                attempt=attempts,
            )
            attempt_result["attempts"] = attempts

            completion_ok, completion_reason = self._check_completion(
                phase_key=str(resolved_phase["phase_key"]),
                result=attempt_result,
            )
            if completion_ok:
                attempt_result["completion"] = "pass"
                return attempt_result

            failure_type = attempt_result.get("failure_type", "quality_fail")
            if not attempt_result.get("success"):
                error_text = attempt_result.get("error", "unknown error")
            else:
                failure_type = "quality_fail"
                error_text = completion_reason

            failure_history.append(
                {
                    "attempt": attempts,
                    "agent": resolved_phase["agent"],
                    "failure_type": failure_type,
                    "error": error_text,
                }
            )

            if attempts < max_retries + 1:
                self._print_status_line(
                    self._wf_msg(
                        "retry",
                        attempt=attempts + 1,
                        attempt_limit=max_retries + 1,
                        action=resolved_phase["action"],
                        error=error_text,
                    )
                )
                continue

        if (
            len(failure_history) >= takeover_after_failures
            and resolved_phase["agent"] != str(policy.get("takeover_agent", "codex"))
        ):
            takeover = self._attempt_takeover(
                resolved_phase=resolved_phase,
                task=task,
                context=context,
                previous_results=previous_results,
                trigger=failure_history[-1]["failure_type"],
            )
            if takeover is not None:
                takeover["attempts"] = attempts
                takeover["failure_history"] = failure_history
                return takeover

        decision = self._ask_user_on_failure(resolved_phase, failure_history, context, task)
        if decision == "skip":
            return {
                "success": False,
                "status": "skipped_by_user",
                "agent": resolved_phase["agent"],
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "attempts": attempts,
                "failure_history": failure_history,
            }
        if decision == "abort":
            return {
                "success": False,
                "status": "aborted_by_user",
                "agent": resolved_phase["agent"],
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "attempts": attempts,
                "failure_history": failure_history,
            }
        if decision == "takeover":
            takeover = self._attempt_takeover(
                resolved_phase=resolved_phase,
                task=task,
                context=context,
                previous_results=previous_results,
                trigger="manual_takeover",
            )
            if takeover is not None:
                takeover["attempts"] = attempts
                takeover["failure_history"] = failure_history
                takeover["user_decision"] = decision
                return takeover

        return {
            "success": False,
            "status": "failed",
            "agent": resolved_phase["agent"],
            "action": resolved_phase["action"],
            "persona": resolved_phase["persona"],
            "active_skills": resolved_phase["active_skills"],
            "attempts": attempts,
            "failure_history": failure_history,
            "error": failure_history[-1]["error"] if failure_history else "unknown error",
        }

    def _attempt_takeover(
        self,
        resolved_phase: Dict[str, Any],
        task: str,
        context: Dict[str, Any],
        previous_results: Dict[str, Any],
        trigger: str,
    ) -> Optional[Dict[str, Any]]:
        """Let configured controller take over failing phase."""
        takeover_agent = str(self._escalation_policy().get("takeover_agent", "codex"))
        if takeover_agent not in self.config.providers:
            return None

        takeover_phase = copy.deepcopy(resolved_phase)
        takeover_phase["agent"] = takeover_agent
        takeover_phase["persona"] = "implementation-engineer" if takeover_agent == "codex" else takeover_phase["persona"]
        takeover_phase["active_skills"] = self._dedupe_skills(
            takeover_phase["active_skills"] + DEFAULT_PERSONA_SKILL_MAP.get(takeover_phase["persona"], [])
        )

        self._print_status_line(self._wf_msg("takeover", trigger=trigger, agent=takeover_agent), marker="⚠")
        result = self._execute_phase_once(
            resolved_phase=takeover_phase,
            task=task,
            context=context,
            previous_results=previous_results,
            attempt=1,
        )
        completion_ok, reason = self._check_completion(str(takeover_phase["phase_key"]), result)
        if not completion_ok:
            result["success"] = False
            result["error"] = reason
            result["failure_type"] = "quality_fail"

        if result.get("success"):
            result["taken_over"] = True
            result["taken_over_from"] = resolved_phase["agent"]
            result["takeover_trigger"] = trigger
            return result
        return None

    def _execute_phase_once(
        self,
        resolved_phase: Dict[str, Any],
        task: str,
        context: Dict[str, Any],
        previous_results: Dict[str, Any],
        attempt: int,
    ) -> Dict[str, Any]:
        """Execute phase once."""
        agent = str(resolved_phase["agent"])
        provider_config = self.config.providers.get(agent)
        if not provider_config:
            return {
                "success": False,
                "error": f"Unknown provider: {agent}",
                "agent": agent,
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "failure_type": "config_error",
            }

        timeout = resolved_phase.get("timeout") or provider_config.timeout
        prompt = self._build_phase_prompt(
            resolved_phase=resolved_phase,
            task=task,
            context=context,
            previous_results=previous_results,
            attempt=attempt,
        )

        cli = self._build_phase_cli(agent=agent, profile=str(resolved_phase.get("profile", "")).strip())
        try:
            cli_parts = shlex.split(cli)
            cmd = resolve_subprocess_command(cli_parts) + [prompt]
        except ValueError as exc:
            return {
                "success": False,
                "error": f"Invalid provider CLI: {exc}",
                "agent": agent,
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "failure_type": "config_error",
            }

        self._print_status_line(self._wf_msg("phase_attempt", attempt=attempt))
        self._print_status_line(self._wf_msg("invoking", agent=agent))
        self._print_status_line(self._wf_msg("timeout", timeout=timeout))

        try:
            live_output = bool(context.get("live_output", False))
            if bool(context.get("live_output", False)):
                result = _run_command_live(cmd, timeout=timeout, line_prefix="│ ")
            else:
                result = subprocess.run(
                    cmd,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            if result.returncode == 0:
                self._print_status_line(self._wf_msg("success", agent=agent), marker="╰─")
                return {
                    "success": True,
                    "output": result.stdout,
                    "agent": agent,
                    "action": resolved_phase["action"],
                    "persona": resolved_phase["persona"],
                    "active_skills": resolved_phase["active_skills"],
                }

            self._print_status_line(self._wf_msg("failed", agent=agent), marker="╰─")
            error_text = result.stderr or result.stdout or self._wf_msg("execution_failed")
            if not live_output:
                self._print_status_line(self._wf_msg("failed_detail"), marker="│")
                self._print_buffered_detail(error_text)
            return {
                "success": False,
                "error": error_text,
                "agent": agent,
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "failure_type": "command_failed",
            }
        except subprocess.TimeoutExpired:
            self._print_status_line(self._wf_msg("timeout_failed", agent=agent, timeout=timeout), marker="╰─")
            return {
                "success": False,
                "error": f"Timeout after {timeout}s",
                "agent": agent,
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "failure_type": "timeout",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Provider executable not found for: {agent}",
                "agent": agent,
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "failure_type": "missing_executable",
            }

    def _build_phase_prompt(
        self,
        resolved_phase: Dict[str, Any],
        task: str,
        context: Dict[str, Any],
        previous_results: Dict[str, Any],
        attempt: int,
    ) -> str:
        """Build prompt for a phase."""
        prompt = f"""
Task: {task}

Phase: {resolved_phase['phase_key']} ({resolved_phase['action']})
Attempt: {attempt}
Persona: {resolved_phase['persona']}
Your role: {resolved_phase['action']}
Expected output: {resolved_phase['output']}
"""
        responsibility_stage = str(resolved_phase.get("responsibility_stage", "")).strip()
        goal = str(resolved_phase.get("goal", "")).strip()
        artifact_type = str(resolved_phase.get("artifact_type", "")).strip()
        allowed_artifacts = self._normalize_skill_input(resolved_phase.get("allowed_artifacts", []))
        boundary = str(resolved_phase.get("boundary", "")).strip()
        timebox_minutes = resolved_phase.get("timebox_minutes")
        if responsibility_stage:
            prompt += f"Responsibility stage: {responsibility_stage}\n"
        if goal:
            prompt += f"Stage goal: {goal}\n"
        if artifact_type:
            prompt += f"Artifact type: {artifact_type}\n"
        if allowed_artifacts:
            prompt += f"Allowed artifacts: {', '.join(allowed_artifacts)}\n"
        if boundary:
            prompt += f"Boundary: {boundary}\n"
        if isinstance(timebox_minutes, int) and timebox_minutes > 0:
            prompt += f"Timebox minutes: {timebox_minutes}\n"
        if resolved_phase["active_skills"]:
            prompt += (
                "\nAuto-trigger skills (apply if available): "
                f"{', '.join(resolved_phase['active_skills'])}\n"
            )

        criteria = self._completion_criteria(str(resolved_phase["phase_key"]))
        min_chars = int(criteria.get("min_output_chars", 0))
        must_include = self._normalize_skill_input(criteria.get("must_include", []))
        prompt += "\nCompletion criteria:\n"
        prompt += f"- Minimum output chars: {min_chars}\n"
        if must_include:
            prompt += f"- Must include keywords: {', '.join(must_include)}\n"

        project_categories = context.get("project_categories", "")
        if project_categories:
            prompt += f"Project categories: {project_categories}\n"

        intent = context.get("intent", "")
        if intent:
            prompt += f"Detected intent: {intent}\n"

        if previous_results:
            prompt += "\nPrevious phase results:\n"
            for phase_name, result in previous_results.items():
                if phase_name.startswith("_"):
                    continue
                if result.get("success"):
                    prompt += f"\n{phase_name}:\n{result.get('output', '')}\n"

        if context:
            prompt += "\nAdditional context:\n"
            for key, value in context.items():
                prompt += f"{key}: {value}\n"

        return prompt

    def _build_phase_cli(self, agent: str, profile: str) -> str:
        """Build provider CLI for a phase, applying selected profile when possible."""
        provider_config = self.config.providers[agent]
        cli = provider_config.cli
        if agent == "codex":
            complexity = profile or "default"
            selected = self.selector.select_model(agent, "", complexity)
            return self._with_codex_repo_flag(agent, selected.cli)
        if not profile:
            return self._with_codex_repo_flag(agent, cli)

        models = provider_config.models or {}
        profile_cfg = {}
        if agent == "codex":
            profile_cfg = (models.get("thinking_levels", {}) or {}).get(profile, {})
        else:
            catalog = models.get("catalog_profiles", {})
            if isinstance(catalog, dict) and profile in catalog:
                profile_cfg = catalog.get(profile, {})
            else:
                profile_cfg = models.get(profile, {})

        if not isinstance(profile_cfg, dict):
            return self._with_codex_repo_flag(agent, cli)

        flag = str(profile_cfg.get("flag", "")).strip()
        if not flag or flag in cli:
            resolved = cli
        else:
            resolved = f"{cli} {flag}".strip()
        return self._with_codex_repo_flag(agent, resolved)

    def _with_codex_repo_flag(self, agent: str, cli: str) -> str:
        """Codex requires trusted git repo by default; auto-bypass in non-repo dirs."""
        if agent != "codex":
            return cli
        if "--skip-git-repo-check" in cli:
            return cli
        return f"{cli} --skip-git-repo-check".strip()

    def _resolve_persona(
        self,
        phase_key: str,
        action: str,
        skills: list[str],
    ) -> Tuple[str, list[str]]:
        """Resolve persona from phase/action and skills."""
        auto_cfg = dict(self.config.auto_collaboration or {})
        if not bool(auto_cfg.get("persona_auto_assign", True)):
            return "generalist", []

        phase_map = dict(DEFAULT_PERSONA_PHASE_MAP)
        custom_phase_map = auto_cfg.get("persona_phase_map", {})
        if isinstance(custom_phase_map, dict):
            phase_map.update({str(k): str(v) for k, v in custom_phase_map.items()})

        skill_map = dict(DEFAULT_PERSONA_SKILL_MAP)
        custom_skill_map = auto_cfg.get("persona_skill_map", {})
        if isinstance(custom_skill_map, dict):
            for persona, mapped in custom_skill_map.items():
                skill_map[str(persona)] = self._normalize_skill_input(mapped)

        persona = phase_map.get(phase_key) or phase_map.get(action.lower(), "")
        if not persona:
            best_persona = ""
            best_score = -1
            skill_set = set(skills)
            for candidate, mapped_skills in skill_map.items():
                overlap = len(skill_set.intersection(set(mapped_skills)))
                if overlap > best_score:
                    best_persona = candidate
                    best_score = overlap
            persona = best_persona or "generalist"

        return persona, self._normalize_skill_input(skill_map.get(persona, []))

    def _completion_criteria(self, phase_key: str) -> Dict[str, Any]:
        """Load completion criteria with defaults."""
        auto_cfg = dict(self.config.auto_collaboration or {})
        configured = auto_cfg.get("phase_completion_criteria", {})
        merged = copy.deepcopy(DEFAULT_PHASE_COMPLETION_CRITERIA)
        if isinstance(configured, dict):
            default_cfg = configured.get("default", {})
            if isinstance(default_cfg, dict):
                merged["default"].update(default_cfg)
            if phase_key in configured and isinstance(configured.get(phase_key), dict):
                merged.setdefault(phase_key, {})
                merged[phase_key].update(configured[phase_key])
        phase_cfg = copy.deepcopy(merged.get("default", {}))
        phase_cfg.update(merged.get(phase_key, {}))
        return phase_cfg

    def _check_completion(self, phase_key: str, result: Dict[str, Any]) -> Tuple[bool, str]:
        """Evaluate phase completion criteria."""
        if not result.get("success"):
            return False, result.get("error", self._wf_msg("execution_failed"))

        criteria = self._completion_criteria(phase_key)
        output = str(result.get("output", "")).strip()
        min_output_chars = max(0, int(criteria.get("min_output_chars", 0)))
        if min_output_chars and len(output) < min_output_chars:
            return False, self._wf_msg("output_too_short", current=len(output), minimum=min_output_chars)

        required_tokens = self._normalize_skill_input(criteria.get("must_include", []))
        lower_output = output.lower()
        missing = [token for token in required_tokens if token.lower() not in lower_output]
        if missing:
            return False, self._wf_msg("missing_required_tokens", tokens=", ".join(missing))

        return True, "ok"

    def _ask_user_on_failure(
        self,
        resolved_phase: Dict[str, Any],
        failure_history: list[Dict[str, Any]],
        context: Dict[str, Any],
        task: str,
    ) -> Optional[str]:
        """Ask user how to proceed when repeated failures happen."""
        policy = self._escalation_policy()
        if not bool(policy.get("ask_user_on_repeated_failure", True)):
            return None
        if not bool(context.get("interactive", False)):
            return None
        if not failure_history:
            return None

        prompt = self._wf_msg(
            "failure_prompt",
            action=resolved_phase["action"],
            count=len(failure_history),
            task=task,
        )
        response = input(prompt).strip().lower()  # noqa: PLW2901
        if response in {"retry", "takeover", "skip", "abort"}:
            return response
        return "abort"

    def _escalation_policy(self) -> Dict[str, Any]:
        """Load escalation policy with defaults."""
        auto_cfg = dict(self.config.auto_collaboration or {})
        policy = copy.deepcopy(DEFAULT_ESCALATION_POLICY)
        configured = auto_cfg.get("escalation_policy", {})
        if isinstance(configured, dict):
            policy.update(configured)
        return policy

    def _normalize_phase_key(self, action: str) -> str:
        """Normalize phase key from action text."""
        lowered = action.strip().lower()
        for key in ("collect", "model", "plan", "artifact", "execute", "validate", "correct", "deliver"):
            if key in lowered:
                return key
        for key in ("discover", "define", "develop", "deliver"):
            if key in lowered:
                return key
        for key in ("design", "review", "audit", "debug", "test", "implement"):
            if key in lowered:
                return key
        return lowered

    def _normalize_skill_input(self, raw: Any) -> list[str]:
        """Normalize skill input from list/string."""
        if raw is None:
            return []
        if isinstance(raw, str):
            return [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(raw, list):
            output = []
            for item in raw:
                item_str = str(item).strip()
                if item_str:
                    output.append(item_str)
            return output
        return [str(raw).strip()] if str(raw).strip() else []

    def _dedupe_skills(self, skills: list[str]) -> list[str]:
        """Deduplicate skills preserving order."""
        deduped: list[str] = []
        seen = set()
        for skill in skills:
            normalized = str(skill).strip()
            if not normalized or normalized in seen:
                continue
            deduped.append(normalized)
            seen.add(normalized)
        return deduped

    def list_workflows(self) -> list[Dict[str, Any]]:
        """List built-in V2 session presets."""
        return [
            {
                "name": key,
                "description": preset.description,
                "workflow_blueprint": preset.workflow_key,
            }
            for key, preset in builtin_session_presets().items()
        ]
