"""
Orchestration planning for controller-first multi-agent execution.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from ai_collab.core.config import Config, resolve_collaboration_role_leads
from ai_collab.core.selector import ModelSelectionResult, ModelSelector
from ai_collab.core.workflow_v2 import builtin_session_presets, resolve_session_preset

ROLE_CAPABILITY_HINTS: Dict[str, List[str]] = {
    "tech-selection": ["architecture", "reasoning", "research", "ecosystem"],
    "frontend-build": ["frontend", "visual-design", "html-css", "implementation"],
    "backend-build": ["backend", "implementation", "integration", "debugging"],
    "implementation": ["implementation", "integration", "backend"],
    "ecosystem-research": ["research", "ecosystem", "documentation"],
    "quality-review": ["code-review", "security", "reasoning", "documentation"],
    "testing": ["testing", "debugging", "code-review"],
}

ROLE_ASSIGNMENT_KEYS: Dict[str, List[str]] = {
    "tech-selection": ["define", "synthesis", "code_patterns"],
    "frontend-build": ["discover", "ecosystem_research", "develop"],
    "backend-build": ["develop", "code_patterns"],
    "implementation": ["develop", "code_patterns"],
    "ecosystem-research": ["discover", "ecosystem_research"],
    "quality-review": ["deliver", "synthesis"],
    "testing": ["develop", "deliver"],
}

ROLE_COMPLEXITY: Dict[str, str] = {
    "tech-selection": "high",
    "frontend-build": "medium",
    "backend-build": "high",
    "implementation": "medium",
    "ecosystem-research": "default",
    "quality-review": "high",
    "testing": "medium",
}
ROLE_POLICY_INTENTS: Dict[str, str] = {
    "tech-selection": "architecture",
    "frontend-build": "implementation",
    "backend-build": "implementation",
    "implementation": "implementation",
    "ecosystem-research": "research",
    "quality-review": "testing",
    "testing": "testing",
}

PHASE_ROLE_MAP: Dict[str, str] = {
    "discover": "ecosystem-research",
    "define": "tech-selection",
    "develop": "implementation",
    "deliver": "quality-review",
}

SMALL_BOUNDED_TASK_CUES = (
    "hello",
    "demo",
    "example",
    "sample",
    "print",
    "typo",
    "rename",
    "format",
    "lint",
    "comment",
    "小改",
    "微调",
    "一行",
    "一句",
    "示例",
    "错别字",
    "改名",
    "重命名",
    "格式",
    "注释",
)


class OrchestrationPlanner:
    """Builds controller-visible agent roster and role assignments."""

    def __init__(self, config: Config):
        self.config = config
        self.selector = ModelSelector(config)

    def build_plan(
        self,
        *,
        task: str,
        current_provider: str,
        intent: Optional[str] = None,
        trigger_name: Optional[str] = None,
        session_preset: Optional[str] = None,
    ) -> Dict[str, object]:
        available_agents = self._available_agents(task)
        resolved_session_preset = self._resolve_session_preset_key(session_preset)
        workflow_blueprint = self._resolve_workflow_blueprint_key(resolved_session_preset)
        workflow_engine = self._workflow_engine()
        roles = self._plan_roles(
            task=task,
            intent=intent,
            trigger_name=trigger_name,
            available_agents=available_agents,
        )

        steps: List[Dict[str, str]] = []
        for role in roles:
            step = self._assign_role(
                role=role,
                task=task,
                current_provider=current_provider,
                available_agents=available_agents,
            )
            if step:
                steps.append(step)

        selected_agents: List[str] = []
        for step in steps:
            agent = step.get("agent", "")
            if agent and agent not in selected_agents:
                selected_agents.append(agent)

        mode = "multi-agent" if len(selected_agents) > 1 else "single-agent"
        return {
            "mode": mode,
            "capabilities": [],
            "available_agents": available_agents,
            "selected_agents": selected_agents,
            "workflow_engine": workflow_engine,
            "session_preset": resolved_session_preset,
            "workflow_blueprint": workflow_blueprint,
            "orchestration_plan": steps,
        }

    def _workflow_engine(self) -> str:
        auto_cfg = self.config.auto_collaboration or {}
        value = str(auto_cfg.get("workflow_engine", "v2")).strip() or "v2"
        return value

    def _resolve_session_preset_key(self, session_preset: Optional[str]) -> str:
        requested = str(session_preset or "").strip()
        if requested:
            try:
                resolve_session_preset(requested)
                return requested
            except KeyError:
                pass

        auto_cfg = self.config.auto_collaboration or {}
        configured = str(auto_cfg.get("default_session_preset", "auto")).strip() or "auto"
        if configured in builtin_session_presets():
            return configured
        return "auto"

    def _resolve_workflow_blueprint_key(self, session_preset: str) -> str:
        return resolve_session_preset(session_preset).workflow_key

    def _available_agents(self, task: str) -> List[Dict[str, str]]:
        agents: List[Dict[str, str]] = []
        for name, provider in self.config.providers.items():
            if not provider.enabled:
                continue

            complexity = "default"
            if name == "codex":
                complexity = "high"
            selection = self._safe_select_model(name, task, complexity)
            agents.append(
                {
                    "agent": name,
                    "selected_model": selection.model,
                    "selected_cli": selection.cli,
                    "model_profile": self._default_profile_name(name),
                    "strengths": ", ".join(provider.strengths),
                }
            )
        return agents

    def _default_profile_name(self, provider: str) -> str:
        provider_cfg = self.config.providers.get(provider)
        if not provider_cfg:
            return "default"
        models = provider_cfg.models or {}
        if provider == "codex":
            return str(models.get("default_thinking", "high"))
        mode = str(provider_cfg.model_selection or "default").strip()
        return mode or "default"

    def _plan_roles(
        self,
        *,
        task: str,
        intent: Optional[str],
        trigger_name: Optional[str],
        available_agents: List[Dict[str, str]],
    ) -> List[str]:
        roles: List[str] = []
        small_bounded_task = self._is_small_bounded_task(task)
        enabled_agents = {item.get("agent", "") for item in available_agents if item.get("agent")}
        configured_defaults = self._configured_default_roles(enabled_agents=enabled_agents)

        if not task.strip():
            roles.extend(configured_defaults)

        if trigger_name == "fullstack-superapp":
            roles.extend(["tech-selection", "frontend-build", "backend-build", "quality-review"])
        elif trigger_name == "architecture":
            roles.extend(["tech-selection", "implementation", "quality-review"])
        elif trigger_name == "visual-design":
            roles.extend(["frontend-build", "quality-review"])
        elif trigger_name == "research":
            roles.extend(["ecosystem-research", "tech-selection", "quality-review"])
        elif trigger_name == "testing":
            roles.extend(["implementation", "testing", "quality-review"])
        else:
            if intent == "research":
                roles.append("ecosystem-research")
            if intent == "architecture":
                roles.append("tech-selection")
            roles.append("implementation")
            if intent in {"implementation", "debug", "testing", "security"} and not small_bounded_task:
                roles.append("quality-review")

        if not roles:
            roles.extend(configured_defaults)

        if not roles:
            roles.append("implementation")
            if len(enabled_agents) > 1 and not small_bounded_task:
                roles.append("quality-review")
        elif (
            "implementation" in roles
            and "quality-review" not in roles
            and len(enabled_agents) > 1
            and not small_bounded_task
        ):
            roles.append("quality-review")

        deduped: List[str] = []
        seen = set()
        for role in roles:
            if role in seen:
                continue
            deduped.append(role)
            seen.add(role)
        return deduped

    def _is_small_bounded_task(self, task: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(task or "").strip())
        if not normalized:
            return False

        lower = normalized.lower()
        if re.fullmatch(r"[\W_]+", lower):
            return True
        if re.fullmatch(r"\d+(?:[.,]\d+)?", lower):
            return True
        if any(cue in lower for cue in SMALL_BOUNDED_TASK_CUES):
            return True

        ascii_tokens = re.findall(r"[a-z0-9]+", lower)
        if ascii_tokens and len(ascii_tokens) <= 2 and len(lower) <= 12:
            return True
        return False

    def _configured_default_roles(self, *, enabled_agents: Set[str]) -> List[str]:
        auto_cfg = self.config.auto_collaboration or {}
        assignment_map = self._assignment_map()
        phase_routing = auto_cfg.get("phase_routing", {})

        roles: List[str] = []
        for phase in ("discover", "define", "develop", "deliver"):
            routed_agent = ""
            assignment = assignment_map.get(phase, {})
            if isinstance(assignment, dict):
                routed_agent = str(assignment.get("agent", "")).strip()
            if not routed_agent and isinstance(phase_routing, dict):
                routed_agent = str(phase_routing.get(phase, "")).strip()
            if routed_agent and routed_agent in enabled_agents:
                roles.append(PHASE_ROLE_MAP[phase])

        if roles:
            return roles

        legacy_role_keys = {
            "ecosystem_research": "ecosystem-research",
            "synthesis": "quality-review",
            "code_patterns": "implementation",
            "discover": "ecosystem-research",
            "define": "tech-selection",
            "develop": "implementation",
            "deliver": "quality-review",
        }
        for key, mapped in legacy_role_keys.items():
            assignment = assignment_map.get(key, {})
            if not isinstance(assignment, dict):
                continue
            routed_agent = str(assignment.get("agent", "")).strip()
            if routed_agent and routed_agent in enabled_agents:
                roles.append(mapped)

        return roles

    def _assign_role(
        self,
        *,
        role: str,
        task: str,
        current_provider: str,
        available_agents: List[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        enabled_agents = {item["agent"] for item in available_agents}
        assignment_map = self._assignment_map()

        assigned_profile = ""
        assigned_by = ""
        chosen_agent = ""
        for key in ROLE_ASSIGNMENT_KEYS.get(role, []):
            route = assignment_map.get(key, {})
            if not isinstance(route, dict):
                continue
            candidate_agent = str(route.get("agent", "")).strip()
            if candidate_agent and candidate_agent in enabled_agents:
                chosen_agent = candidate_agent
                assigned_profile = str(route.get("profile", "")).strip()
                assigned_by = f"assignment_map.{key}"
                break

        if not chosen_agent:
            preferred_agent = self._preferred_agent_for_role(role=role, enabled_agents=enabled_agents)
            if preferred_agent:
                chosen_agent = preferred_agent
                assigned_by = "routing_policy"

        if not chosen_agent:
            chosen_agent = self._best_agent_by_strength(
                role=role,
                current_provider=current_provider,
                enabled_agents=enabled_agents,
            )
            assigned_by = "strengths"

        if not chosen_agent:
            return None

        selection = self._select_model_for_role(
            agent=chosen_agent,
            role=role,
            task=task,
        )
        return {
            "role": role,
            "agent": chosen_agent,
            "selected_model": selection.model,
            "selected_cli": selection.cli,
            "profile": assigned_profile or self._default_profile_name(chosen_agent),
            "reason": assigned_by,
        }

    def _assignment_map(self) -> Dict[str, Dict[str, str]]:
        auto_cfg = self.config.auto_collaboration or {}
        assignment_map = auto_cfg.get("assignment_map", {})
        if isinstance(assignment_map, dict) and assignment_map:
            return assignment_map
        legacy = auto_cfg.get("assignments", {})
        if isinstance(legacy, dict):
            return legacy
        return {}

    def _best_agent_by_strength(
        self,
        *,
        role: str,
        current_provider: str,
        enabled_agents: Set[str],
    ) -> str:
        desired = set(ROLE_CAPABILITY_HINTS.get(role, []))
        best_agent = ""
        best_score = -1

        for agent, provider_cfg in self.config.providers.items():
            if not provider_cfg.enabled or agent not in enabled_agents:
                continue
            strengths = set(provider_cfg.strengths or [])
            score = len(desired.intersection(strengths)) * 3
            if agent == current_provider:
                score += 1
            if role == "quality-review" and "code-review" in strengths:
                score += 2
            if role == "testing" and "code-review" in strengths:
                score += 2
            if role == "backend-build" and "backend" in strengths:
                score += 2
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

    def _preferred_agent_for_role(self, *, role: str, enabled_agents: Set[str]) -> str:
        intent = ROLE_POLICY_INTENTS.get(role, "")
        if not intent:
            return ""
        leads = resolve_collaboration_role_leads(self.config)
        candidate = str(leads.get(intent, "")).strip()
        if candidate in enabled_agents:
            return candidate
        return ""

    def _select_model_for_role(self, *, agent: str, role: str, task: str) -> ModelSelectionResult:
        complexity = ROLE_COMPLEXITY.get(role, "default")
        if agent != "codex":
            complexity = "default"
        return self._safe_select_model(agent, task, complexity)

    def _safe_select_model(self, agent: str, task: str, complexity: str) -> ModelSelectionResult:
        provider_cfg = self.config.providers.get(agent)
        if not provider_cfg:
            return ModelSelectionResult(cli="", model="unknown", description="Provider not configured")

        try:
            return self.selector.select_model(agent, task, complexity)
        except Exception:
            fallback_model = "default"
            if provider_cfg.models and isinstance(provider_cfg.models, dict):
                if agent == "codex":
                    fallback_model = "gpt-5.4"
                else:
                    fallback_model = str(provider_cfg.models.get("default", "default"))
            return ModelSelectionResult(
                cli=provider_cfg.cli,
                model=fallback_model,
                description="Fallback model selection (missing profile config)",
            )
