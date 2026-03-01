"""
Orchestration planning for controller-first multi-agent execution.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from ai_collab.core.config import Config
from ai_collab.core.selector import ModelSelectionResult, ModelSelector

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

TASK_CAPABILITIES: Dict[str, List[str]] = {
    "frontend": [
        "frontend",
        "ui",
        "web",
        "html",
        "css",
        "react",
        "vue",
        "页面",
        "前端",
        "界面",
    ],
    "backend": [
        "backend",
        "api",
        "server",
        "service",
        "spring",
        "flask",
        "fastapi",
        "express",
        "后端",
    ],
    "persistence": [
        "database",
        "db",
        "sqlite",
        "mysql",
        "postgres",
        "redis",
        "存储",
        "持久化",
        "保存数据",
    ],
    "architecture": [
        "architecture",
        "design",
        "framework",
        "tech stack",
        "选型",
        "技术选型",
        "架构",
        "方案",
        "框架",
    ],
    "research": [
        "research",
        "benchmark",
        "study",
        "调研",
        "对比",
        "探索",
    ],
    "testing": [
        "test",
        "tdd",
        "coverage",
        "测试",
        "回归",
    ],
}


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
    ) -> Dict[str, object]:
        available_agents = self._available_agents(task)
        capabilities = self._infer_capabilities(task)
        roles = self._plan_roles(capabilities=capabilities, intent=intent, trigger_name=trigger_name)

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
            "capabilities": sorted(capabilities),
            "available_agents": available_agents,
            "selected_agents": selected_agents,
            "orchestration_plan": steps,
        }

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

    def _infer_capabilities(self, task: str) -> Set[str]:
        task_lower = task.lower()
        capabilities: Set[str] = set()
        for capability, keywords in TASK_CAPABILITIES.items():
            if any(keyword.lower() in task_lower for keyword in keywords):
                capabilities.add(capability)
        return capabilities

    def _plan_roles(
        self,
        *,
        capabilities: Set[str],
        intent: Optional[str],
        trigger_name: Optional[str],
    ) -> List[str]:
        roles: List[str] = []

        if "frontend" in capabilities and ("backend" in capabilities or "persistence" in capabilities):
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
            if intent in {"implementation", "debug", "testing", "security"}:
                roles.append("quality-review")

        deduped: List[str] = []
        seen = set()
        for role in roles:
            if role in seen:
                continue
            deduped.append(role)
            seen.add(role)
        return deduped

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
            if role == "backend-build" and "backend" in strengths:
                score += 2
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

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
                    fallback_model = "gpt-5.3-codex"
                else:
                    fallback_model = str(provider_cfg.models.get("default", "default"))
            return ModelSelectionResult(
                cli=provider_cfg.cli,
                model=fallback_model,
                description="Fallback model selection (missing profile config)",
            )
