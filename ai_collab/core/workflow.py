"""Workflow management module."""

from __future__ import annotations

import copy
import shlex
import subprocess
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field

from ai_collab.core.config import Config


DEFAULT_PERSONA_PHASE_MAP = {
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


class WorkflowPhase(BaseModel):
    """Workflow phase definition."""

    agent: str
    action: str
    output: str
    timeout: Optional[int] = None
    skills: list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    """Workflow definition."""

    name: str
    description: str
    phases: list[WorkflowPhase]


class WorkflowManager:
    """Manages workflow execution."""

    def __init__(self, config: Config):
        self.config = config

    def execute_workflow(
        self,
        workflow_name: str,
        task: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a workflow with persona routing, completion gates, and escalation policy."""
        workflow_data = self.config.workflows.get(workflow_name)
        if not workflow_data:
            raise ValueError(f"Workflow not found: {workflow_name}")

        workflow = Workflow(
            name=workflow_name,
            description=workflow_data.get("description", ""),
            phases=[WorkflowPhase(**phase) for phase in workflow_data.get("phases", [])],
        )
        results: Dict[str, Any] = {}
        summary: Dict[str, Any] = {
            "status": "completed",
            "workflow": workflow_name,
            "total_phases": len(workflow.phases),
            "completed_phases": 0,
            "skipped_phases": 0,
        }

        for index, phase in enumerate(workflow.phases, 1):
            resolved_phase = self._resolve_phase_plan(phase, context)
            print(f"\n{'=' * 60}")
            print(f"Phase {index}/{len(workflow.phases)}: {resolved_phase['action']}")
            print(f"Agent: {resolved_phase['agent']}")
            print(f"Persona: {resolved_phase['persona']}")
            if resolved_phase["active_skills"]:
                print(f"Skills: {', '.join(resolved_phase['active_skills'])}")
            print(f"{'=' * 60}\n")

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
                print(f"↻ Retry {attempts}/{max_retries} for {resolved_phase['action']} due to: {error_text}")
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

        print(f"⚠️ Escalation trigger={trigger}. Taking over with {takeover_agent}.")
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
            cmd = cli_parts + [prompt]
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

        print(f"🤖 Invoking {agent}...")
        print(f"⏱️  Timeout: {timeout}s")

        try:
            result = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                print(f"✅ {agent} completed successfully")
                return {
                    "success": True,
                    "output": result.stdout,
                    "agent": agent,
                    "action": resolved_phase["action"],
                    "persona": resolved_phase["persona"],
                    "active_skills": resolved_phase["active_skills"],
                }

            print(f"❌ {agent} failed: {result.stderr}")
            return {
                "success": False,
                "error": result.stderr,
                "agent": agent,
                "action": resolved_phase["action"],
                "persona": resolved_phase["persona"],
                "active_skills": resolved_phase["active_skills"],
                "failure_type": "command_failed",
            }
        except subprocess.TimeoutExpired:
            print(f"⏰ {agent} timed out after {timeout}s")
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
            return False, result.get("error", "execution failed")

        criteria = self._completion_criteria(phase_key)
        output = str(result.get("output", "")).strip()
        min_output_chars = max(0, int(criteria.get("min_output_chars", 0)))
        if min_output_chars and len(output) < min_output_chars:
            return False, f"Output too short ({len(output)} < {min_output_chars})"

        required_tokens = self._normalize_skill_input(criteria.get("must_include", []))
        lower_output = output.lower()
        missing = [token for token in required_tokens if token.lower() not in lower_output]
        if missing:
            return False, f"Missing required tokens: {', '.join(missing)}"

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

        prompt = (
            f"\nPhase '{resolved_phase['action']}' failed {len(failure_history)} times for task '{task}'.\n"
            "Choose action [retry/takeover/skip/abort] (default: abort): "
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
        """List all available workflows."""
        workflows = []
        for name, workflow_data in self.config.workflows.items():
            workflows.append(
                {
                    "name": name,
                    "description": workflow_data.get("description", ""),
                    "phases": len(workflow_data.get("phases", [])),
                }
            )
        return workflows
