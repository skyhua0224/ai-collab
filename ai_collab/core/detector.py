"""
Collaboration detection module.
Detects if a task needs multi-AI collaboration.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ai_collab.core.config import Config
from ai_collab.core.orchestrator import OrchestrationPlanner
from ai_collab.core.profiler import ProjectProfiler
from ai_collab.core.workflow_v2 import (
    find_session_preset_for_workflow_blueprint,
    resolve_session_preset,
    resolve_workflow_blueprint,
)


DEFAULT_INTENT_TRIGGER_MAP = {
    "design": "visual-design",
    "architecture": "architecture",
    "implementation": "implementation",
    "debug": "debugging",
    "security": "security-audit",
    "research": "research",
    "testing": "testing",
    "documentation": "docs-writing",
    "gameplay": "game-dev",
}


DEFAULT_PROFILE_TRIGGER_MAP = {
    "docs-text": {
        "default": "docs-writing",
        "research": "research",
    },
    "superapp-fullstack": {
        "default": "fullstack-superapp",
        "design": "visual-design",
        "implementation": "implementation",
        "architecture": "architecture",
    },
    "macos-swift": {
        "default": "macos-native",
        "debug": "debugging",
    },
    "mobile-native": {
        "default": "mobile-native",
        "debug": "debugging",
    },
    "systems-tooling": {
        "default": "systems-tooling",
        "debug": "debugging",
        "testing": "testing",
    },
    "game-dev": {
        "default": "game-dev",
        "design": "visual-design",
        "implementation": "implementation",
        "gameplay": "game-dev",
    },
}


DEFAULT_PROFILE_SKILLS = {
    "docs-text": ["documentation", "research", "review"],
    "superapp-fullstack": ["frontend-design", "code-review", "integration"],
    "macos-swift": ["swift-native", "debugging", "code-review"],
    "mobile-native": ["mobile-native", "debugging", "security-review"],
    "systems-tooling": ["bash-python-node-rust", "testing", "code-review"],
    "game-dev": ["game-design", "performance", "code-review"],
}


CATEGORY_PRIORITY = {
    "superapp-fullstack": 100,
    "mobile-native": 95,
    "macos-swift": 90,
    "game-dev": 85,
    "systems-tooling": 70,
    "docs-text": 50,
}


TRIGGER_SESSION_PRESET_MAP = {
    "visual-design": "design-first",
    "fullstack-superapp": "design-first",
    "game-dev": "design-first",
    "debugging": "debug-priority",
    "research": "research-priority",
    "architecture": "research-priority",
    "testing": "validation-first",
    "security-audit": "validation-first",
    "docs-writing": "document-first",
}

LOW_SIGNAL_TASK_LITERALS = {
    "1",
    "1.",
    "1。",  # noqa: RUF001
    "hello",
    "hi",
    "hey",
    "ok",
    "okay",
    "test",
    "sb",
    "?",
    "？",  # noqa: RUF001
    ".",
    "..",
    "...",
}


class CollaborationResult(BaseModel):
    """Result of collaboration detection."""

    need_collaboration: bool
    trigger: Optional[str] = None
    description: Optional[str] = None
    primary: Optional[str] = None
    reviewers: List[str] = Field(default_factory=list)
    workflow: Dict = Field(default_factory=dict)
    consensus_threshold: float = 0.75
    intent: Optional[str] = None
    matched_patterns: List[str] = Field(default_factory=list)
    project_categories: List[str] = Field(default_factory=list)
    suggested_skills: List[str] = Field(default_factory=list)
    available_agents: List[Dict[str, str]] = Field(default_factory=list)
    orchestration_plan: List[Dict[str, str]] = Field(default_factory=list)
    selected_agents: List[str] = Field(default_factory=list)
    execution_mode: str = "single-agent"
    workflow_engine: str = "v2"
    session_preset: Optional[str] = None
    workflow_blueprint: Optional[str] = None
    compatibility_mode: Optional[str] = None
    responsibility_stages: List[str] = Field(default_factory=list)


class CollaborationDetector:
    """Detects if a task needs multi-AI collaboration."""

    def __init__(self, config: Config):
        self.config = config

    def detect(self, task: str, current_provider: str) -> CollaborationResult:
        """
        Detect if a task needs collaboration.

        Args:
            task: User's task description
            current_provider: Current AI provider

        Returns:
            CollaborationResult with detection details
        """
        auto_cfg = self.config.auto_collaboration or {}
        if not self._is_auto_collaboration_enabled(auto_cfg):
            return CollaborationResult(need_collaboration=False)
        if self._is_low_signal_task(task):
            return CollaborationResult(need_collaboration=False)

        profile = ProjectProfiler().detect()
        categories = list(profile.categories)
        enabled_categories = auto_cfg.get("enabled_project_categories", [])
        if isinstance(enabled_categories, list) and enabled_categories:
            filtered = [item for item in categories if item in enabled_categories]
            categories = filtered if filtered else list(enabled_categories)

        planner = OrchestrationPlanner(self.config)
        seed_plan = planner.build_plan(
            task=task,
            current_provider=current_provider,
            intent=None,
            trigger_name=None,
        )
        intent = self._infer_intent(
            orchestration_plan=seed_plan.get("orchestration_plan", []),
            categories=categories,
        )
        trigger, matched_patterns = self._select_trigger(
            intent=intent,
            categories=categories,
            orchestration_plan=seed_plan.get("orchestration_plan", []),
        )
        resolved_session_preset = self._choose_session_preset(
            plan=seed_plan,
            trigger=trigger,
            trigger_name=trigger.get("name") if trigger else None,
            intent=intent,
            categories=categories,
        )
        plan = seed_plan
        if intent or trigger or resolved_session_preset != str(seed_plan.get("session_preset", "")).strip():
            refined = planner.build_plan(
                task=task,
                current_provider=current_provider,
                intent=intent,
                trigger_name=trigger.get("name") if trigger else None,
                session_preset=resolved_session_preset,
            )
            if refined.get("orchestration_plan"):
                plan = refined
        if trigger and self._should_promote_to_fullstack(trigger=trigger, orchestration_plan=plan.get("orchestration_plan", [])):
            promoted = self._get_trigger_by_name("fullstack-superapp")
            if promoted:
                trigger = promoted
                promoted_session_preset = self._choose_session_preset(
                    plan=plan,
                    trigger=promoted,
                    trigger_name=promoted.get("name"),
                    intent=intent,
                    categories=categories,
                )
                if promoted_session_preset != str(plan.get("session_preset", "")).strip():
                    promoted_plan = planner.build_plan(
                        task=task,
                        current_provider=current_provider,
                        intent=intent,
                        trigger_name=promoted.get("name"),
                        session_preset=promoted_session_preset,
                    )
                    if promoted_plan.get("orchestration_plan"):
                        plan = promoted_plan

        planner_first = bool(auto_cfg.get("planner_first", True))
        if planner_first and self._is_planner_multi_agent(plan):
            selected_trigger = trigger
            if not selected_trigger:
                inferred_trigger_name = self._infer_trigger_from_plan(
                    intent=intent,
                    categories=categories,
                    orchestration_plan=plan.get("orchestration_plan", []),
                )
                if inferred_trigger_name:
                    selected_trigger = self._get_trigger_by_name(inferred_trigger_name)

            route_meta = self._resolve_route_metadata(
                plan=plan,
                trigger=selected_trigger,
                trigger_name=selected_trigger.get("name") if selected_trigger else None,
                intent=intent,
                categories=categories,
            )
            primary_from_plan = self._plan_primary_agent(plan, current_provider)
            primary = (
                str(selected_trigger.get("primary", primary_from_plan)).strip()
                if selected_trigger
                else primary_from_plan
            )
            reviewers = (
                [str(item) for item in selected_trigger.get("reviewers", [])]
                if selected_trigger and selected_trigger.get("reviewers")
                else [item for item in plan.get("selected_agents", []) if item != primary]
            )

            return CollaborationResult(
                need_collaboration=bool(route_meta["workflow_blueprint"] or route_meta["workflow"]),
                trigger=selected_trigger.get("name", "planner-derived") if selected_trigger else "planner-derived",
                description=selected_trigger.get("description", "Planner-derived multi-agent orchestration")
                if selected_trigger
                else "Planner-derived multi-agent orchestration",
                primary=primary,
                reviewers=reviewers,
                workflow=route_meta["workflow"],
                consensus_threshold=auto_cfg.get("consensus_threshold", 0.75),
                intent=intent,
                matched_patterns=matched_patterns,
                project_categories=categories,
                suggested_skills=self._suggest_skills(selected_trigger.get("name") if selected_trigger else None, categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
                workflow_engine=str(route_meta["workflow_engine"]),
                session_preset=route_meta["session_preset"],
                workflow_blueprint=route_meta["workflow_blueprint"],
                compatibility_mode=route_meta["compatibility_mode"],
                responsibility_stages=list(route_meta["responsibility_stages"]),
            )

        if not trigger:
            inferred_trigger_name = self._infer_trigger_from_plan(
                intent=intent,
                categories=categories,
                orchestration_plan=plan.get("orchestration_plan", []),
            )
            if inferred_trigger_name:
                trigger = self._get_trigger_by_name(inferred_trigger_name)

        if not trigger and self._is_planner_multi_agent(plan):
            route_meta = self._resolve_route_metadata(
                plan=plan,
                trigger=None,
                trigger_name=None,
                intent=intent,
                categories=categories,
            )
            primary = self._plan_primary_agent(plan, current_provider)
            reviewers = [item for item in plan.get("selected_agents", []) if item != primary]
            return CollaborationResult(
                need_collaboration=bool(route_meta["workflow_blueprint"] or route_meta["workflow"]),
                trigger="planner-derived",
                description="Planner-derived multi-agent orchestration",
                primary=primary,
                reviewers=reviewers,
                workflow=route_meta["workflow"],
                consensus_threshold=auto_cfg.get("consensus_threshold", 0.75),
                intent=intent,
                matched_patterns=matched_patterns,
                project_categories=categories,
                suggested_skills=self._suggest_skills(None, categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
                workflow_engine=str(route_meta["workflow_engine"]),
                session_preset=route_meta["session_preset"],
                workflow_blueprint=route_meta["workflow_blueprint"],
                compatibility_mode=route_meta["compatibility_mode"],
                responsibility_stages=list(route_meta["responsibility_stages"]),
            )

        if not trigger:
            route_meta = self._resolve_route_metadata(
                plan=plan,
                trigger=None,
                trigger_name=None,
                intent=intent,
                categories=categories,
            )
            return CollaborationResult(
                need_collaboration=False,
                intent=intent,
                project_categories=categories,
                suggested_skills=self._suggest_skills(None, categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
                workflow_engine=str(route_meta["workflow_engine"]),
                session_preset=route_meta["session_preset"],
                workflow_blueprint=route_meta["workflow_blueprint"],
                compatibility_mode=route_meta["compatibility_mode"],
                responsibility_stages=list(route_meta["responsibility_stages"]),
            )

        if not self._is_planner_multi_agent(plan):
            route_meta = self._resolve_route_metadata(
                plan=plan,
                trigger=trigger,
                trigger_name=trigger.get("name"),
                intent=intent,
                categories=categories,
            )
            return CollaborationResult(
                need_collaboration=False,
                trigger=trigger.get("name", ""),
                description=trigger.get("description", ""),
                intent=intent,
                project_categories=categories,
                suggested_skills=self._suggest_skills(trigger.get("name"), categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
                workflow_engine=str(route_meta["workflow_engine"]),
                session_preset=route_meta["session_preset"],
                workflow_blueprint=route_meta["workflow_blueprint"],
                compatibility_mode=route_meta["compatibility_mode"],
                responsibility_stages=list(route_meta["responsibility_stages"]),
            )

        route_meta = self._resolve_route_metadata(
            plan=plan,
            trigger=trigger,
            trigger_name=trigger.get("name"),
            intent=intent,
            categories=categories,
        )

        return CollaborationResult(
            need_collaboration=True,
            trigger=trigger.get("name", ""),
            description=trigger.get("description", ""),
            primary=trigger.get("primary", current_provider),
            reviewers=trigger.get("reviewers", []),
            workflow=route_meta["workflow"],
            consensus_threshold=auto_cfg.get("consensus_threshold", 0.75),
            intent=intent,
            matched_patterns=matched_patterns,
            project_categories=categories,
            suggested_skills=self._suggest_skills(trigger.get("name"), categories),
            available_agents=plan.get("available_agents", []),
            orchestration_plan=plan.get("orchestration_plan", []),
            selected_agents=plan.get("selected_agents", []),
            execution_mode=str(plan.get("mode", "single-agent")),
            workflow_engine=str(route_meta["workflow_engine"]),
            session_preset=route_meta["session_preset"],
            workflow_blueprint=route_meta["workflow_blueprint"],
            compatibility_mode=route_meta["compatibility_mode"],
            responsibility_stages=list(route_meta["responsibility_stages"]),
        )

    def _is_auto_collaboration_enabled(self, auto_cfg: Dict) -> bool:
        if "enabled" in auto_cfg:
            return bool(auto_cfg.get("enabled"))
        if "auto_orchestration_enabled" in auto_cfg:
            return bool(auto_cfg.get("auto_orchestration_enabled"))
        return True

    def _is_low_signal_task(self, task: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(task or "").strip())
        if not normalized:
            return False

        lower = normalized.lower()
        if lower in LOW_SIGNAL_TASK_LITERALS:
            return True
        if re.fullmatch(r"[\W_]+", lower):
            return True
        if re.fullmatch(r"\d+(?:[.,]\d+)?", lower):
            return True

        ascii_tokens = re.findall(r"[a-z0-9]+", lower)
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        token_count = len(ascii_tokens) + len(cjk_chars)
        if token_count > 1:
            return False

        token = ascii_tokens[0] if ascii_tokens else "".join(cjk_chars)
        return bool(token) and len(token) <= 3

    def _is_planner_multi_agent(self, plan: Dict[str, object]) -> bool:
        mode = str(plan.get("mode", "single-agent"))
        if mode == "multi-agent":
            return True
        selected = plan.get("selected_agents", [])
        if isinstance(selected, list):
            return len(selected) > 1
        return False

    def _plan_primary_agent(self, plan: Dict[str, object], current_provider: str) -> str:
        steps = plan.get("orchestration_plan", [])
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and step.get("agent"):
                    return str(step.get("agent"))
        return current_provider

    def _trigger_session_preset(self, trigger: Optional[Dict]) -> str:
        if not isinstance(trigger, dict):
            return ""
        return str(trigger.get("session_preset", "")).strip()

    def _trigger_workflow_blueprint(self, trigger: Optional[Dict]) -> str:
        if not isinstance(trigger, dict):
            return ""
        return str(trigger.get("workflow_blueprint", "")).strip()

    def _choose_session_preset(
        self,
        *,
        plan: Dict[str, object],
        trigger: Optional[Dict],
        trigger_name: Optional[str],
        intent: Optional[str],
        categories: List[str],
    ) -> str:
        explicit = self._trigger_session_preset(trigger)
        if explicit:
            try:
                resolve_session_preset(explicit)
                return explicit
            except KeyError:
                pass

        requested = str(plan.get("session_preset", "")).strip()
        if requested and requested != "auto":
            try:
                resolve_session_preset(requested)
                return requested
            except KeyError:
                pass

        if trigger_name:
            mapped = TRIGGER_SESSION_PRESET_MAP.get(trigger_name)
            if mapped:
                return mapped

        if "docs-text" in categories:
            return "document-first"
        if any(category in {"superapp-fullstack", "game-dev"} for category in categories):
            return "design-first"

        intent_map = {
            "design": "design-first",
            "architecture": "research-priority",
            "research": "research-priority",
            "debug": "debug-priority",
            "testing": "validation-first",
            "documentation": "document-first",
        }
        if intent:
            mapped = intent_map.get(intent)
            if mapped:
                return mapped

        return requested or "auto"

    def _resolve_route_metadata(
        self,
        *,
        plan: Dict[str, object],
        trigger: Optional[Dict],
        trigger_name: Optional[str],
        intent: Optional[str],
        categories: List[str],
    ) -> Dict[str, object]:
        workflow_engine = str(plan.get("workflow_engine", "v2")).strip() or "v2"
        session_preset = self._choose_session_preset(
            plan=plan,
            trigger=trigger,
            trigger_name=trigger_name,
            intent=intent,
            categories=categories,
        )
        trigger_blueprint = self._trigger_workflow_blueprint(trigger)
        plan_blueprint = str(plan.get("workflow_blueprint", "")).strip()
        workflow_blueprint = trigger_blueprint or plan_blueprint

        blueprint_source = ""
        if workflow_blueprint:
            try:
                resolve_workflow_blueprint(workflow_blueprint)
                blueprint_source = "blueprint"
            except KeyError:
                workflow_blueprint = ""

        if not workflow_blueprint:
            try:
                workflow_blueprint = resolve_session_preset(session_preset).workflow_key
                blueprint_source = "preset" if self._trigger_session_preset(trigger) or str(plan.get("session_preset", "")).strip() else "planner"
            except KeyError:
                workflow_blueprint = ""

        if workflow_blueprint:
            matched_session_preset = find_session_preset_for_workflow_blueprint(
                workflow_blueprint,
                preferred=session_preset,
            )
            if matched_session_preset:
                session_preset = matched_session_preset
            blueprint = resolve_workflow_blueprint(workflow_blueprint)
            responsibility_stages = [stage.responsibility_stage for stage in blueprint.stages]
            workflow_preview = {
                "description": blueprint.description,
                "phases": [
                    {
                        "agent": stage.default_agent or "",
                        "action": stage.responsibility_stage,
                        "output": stage.outputs[0] if stage.outputs else stage.goal,
                    }
                    for stage in blueprint.stages
                ],
            }
        else:
            responsibility_stages = []
            workflow_preview = {}

        if workflow_engine != "v2":
            compatibility_mode = "planner-v2"
        elif blueprint_source == "blueprint":
            compatibility_mode = "direct-v2-blueprint"
        elif blueprint_source == "preset":
            compatibility_mode = "direct-v2-preset"
        else:
            compatibility_mode = "planner-v2"

        return {
            "workflow_engine": workflow_engine,
            "session_preset": session_preset,
            "workflow_blueprint": workflow_blueprint or None,
            "compatibility_mode": compatibility_mode,
            "responsibility_stages": responsibility_stages,
            "workflow": workflow_preview,
        }

    def _get_trigger_by_name(self, name: str) -> Optional[Dict]:
        triggers = self.config.auto_collaboration.get("triggers", [])
        for trigger in triggers:
            if trigger.get("name") == name:
                return trigger
        return None

    def _infer_trigger_from_plan(
        self,
        *,
        intent: Optional[str],
        categories: List[str],
        orchestration_plan: List[Dict[str, str]],
    ) -> Optional[str]:
        roles = {item.get("role", "") for item in orchestration_plan}
        if {"frontend-build", "backend-build"}.issubset(roles):
            return "fullstack-superapp"
        if "tech-selection" in roles:
            return "architecture"
        fallback_name = self._trigger_name_from_profile_intent(intent, categories)
        if fallback_name:
            return fallback_name
        if intent:
            return self._intent_trigger_map().get(intent)
        return None

    def _should_promote_to_fullstack(self, *, trigger: Dict, orchestration_plan: List[Dict[str, str]]) -> bool:
        if trigger.get("name") != "implementation":
            return False
        roles = {item.get("role", "") for item in orchestration_plan}
        return {"frontend-build", "backend-build"}.issubset(roles)

    def _select_trigger(
        self,
        *,
        intent: Optional[str],
        categories: List[str],
        orchestration_plan: List[Dict[str, str]],
    ) -> Tuple[Optional[Dict], List[str]]:
        candidate_names: List[str] = []
        plan_based = self._infer_trigger_from_plan(
            intent=intent,
            categories=categories,
            orchestration_plan=orchestration_plan,
        )
        if plan_based:
            candidate_names.append(plan_based)

        profile_based = self._trigger_name_from_profile_intent(intent, categories)
        if profile_based:
            candidate_names.append(profile_based)

        if intent:
            mapped = self._intent_trigger_map().get(intent)
            if mapped:
                candidate_names.append(mapped)

        seen = set()
        for name in candidate_names:
            if not name or name in seen:
                continue
            seen.add(name)
            trigger = self._get_trigger_by_name(name)
            if trigger:
                return trigger, []

        return None, []

    def _infer_intent(
        self,
        *,
        orchestration_plan: List[Dict[str, str]],
        categories: List[str],
    ) -> Optional[str]:
        roles = {str(item.get("role", "")).strip() for item in orchestration_plan if isinstance(item, dict)}
        if "testing" in roles:
            return "testing"
        if {"frontend-build", "backend-build"}.issubset(roles):
            return "implementation"
        if "tech-selection" in roles and "implementation" not in roles:
            return "architecture"
        if "ecosystem-research" in roles and "implementation" not in roles:
            return "research"
        if "quality-review" in roles and "implementation" in roles:
            return "implementation"
        if "implementation" in roles:
            return "implementation"

        fallback_trigger = self._trigger_name_from_profile_intent(None, categories)
        return self._intent_from_trigger_name(fallback_trigger)

    def _intent_from_trigger_name(self, trigger_name: Optional[str]) -> Optional[str]:
        reverse_map = {
            "visual-design": "design",
            "architecture": "architecture",
            "implementation": "implementation",
            "debugging": "debug",
            "security-audit": "security",
            "research": "research",
            "testing": "testing",
            "docs-writing": "documentation",
            "game-dev": "gameplay",
            "fullstack-superapp": "implementation",
            "macos-native": "implementation",
            "mobile-native": "implementation",
            "systems-tooling": "implementation",
        }
        if not trigger_name:
            return None
        return reverse_map.get(trigger_name)

    def _intent_trigger_map(self) -> Dict[str, str]:
        auto_cfg = self.config.auto_collaboration or {}
        custom = auto_cfg.get("intent_trigger_map", {})
        merged = dict(DEFAULT_INTENT_TRIGGER_MAP)
        merged.update(custom)
        return merged

    def _profile_trigger_map(self) -> Dict[str, Dict[str, str]]:
        auto_cfg = self.config.auto_collaboration or {}
        custom = auto_cfg.get("profile_trigger_map", {})

        merged = {key: dict(value) for key, value in DEFAULT_PROFILE_TRIGGER_MAP.items()}
        for category, mapping in custom.items():
            merged.setdefault(category, {})
            merged[category].update(mapping)
        return merged

    def _trigger_name_from_profile_intent(
        self,
        intent: Optional[str],
        categories: List[str],
    ) -> Optional[str]:
        profile_map = self._profile_trigger_map()
        sorted_categories = sorted(
            categories,
            key=lambda c: CATEGORY_PRIORITY.get(c, 0),
            reverse=True,
        )
        for category in sorted_categories:
            category_rules = profile_map.get(category, {})
            if intent and intent in category_rules:
                return category_rules[intent]
            if "default" in category_rules:
                return category_rules["default"]

        return None

    def _suggest_skills(self, trigger_name: Optional[str], categories: List[str]) -> List[str]:
        auto_cfg = self.config.auto_collaboration or {}
        trigger_skill_map = auto_cfg.get("skill_map", {})
        profile_skill_map = auto_cfg.get("profile_skill_map", {})

        skills: List[str] = []
        if trigger_name:
            skills.extend(trigger_skill_map.get(trigger_name, []))

        for category in categories:
            if category in profile_skill_map:
                skills.extend(profile_skill_map.get(category, []))
            else:
                skills.extend(DEFAULT_PROFILE_SKILLS.get(category, []))

        # Deduplicate while preserving order.
        deduped: List[str] = []
        seen = set()
        for skill in skills:
            if skill not in seen:
                deduped.append(skill)
                seen.add(skill)

        return deduped

    def generate_prompt(
        self,
        task: str,
        result: CollaborationResult,
        current_agent: str,
    ) -> str:
        """Generate collaboration prompt."""
        if not result.need_collaboration:
            return ""

        workflow = result.workflow
        phases = workflow.get("phases", [])
        workflow_label = result.workflow_blueprint or result.session_preset or "(none)"

        lang = str(getattr(self.config, "ui_language", "en-US"))
        is_zh = lang == "zh-CN"

        if is_zh:
            prompt = f"""
🤝 检测到多 AI 协作任务

任务类型: {result.trigger} - {result.description}
用户请求: {task}

编排路由: {workflow_label}
{workflow.get('description', '')}

执行步骤:
"""
        else:
            prompt = f"""
🤝 Multi-AI Collaboration Detected

Task Type: {result.trigger} - {result.description}
User Request: {task}

Route: {workflow_label}
{workflow.get('description', '')}

Execution Steps:
"""

        for i, phase in enumerate(phases, 1):
            agent = phase.get("agent", "")
            action = phase.get("action", "")
            output = phase.get("output", "")
            marker = "👉" if agent == current_agent else "  "
            if is_zh:
                prompt += f"{marker} {i}. {action.upper()} ({agent}): {output}\n"
            else:
                prompt += f"{marker} {i}. {action.upper()} ({agent}): {output}\n"

        categories = ", ".join(result.project_categories) or "(none)"
        skills = ", ".join(result.suggested_skills) or "(none)"

        if is_zh:
            prompt += f"""
当前 AI: {current_agent}
主导 AI: {result.primary}
审查者: {', '.join(result.reviewers)}
项目分类: {categories}
自动技能: {skills}
执行模式: {result.execution_mode}
已选 Agent: {', '.join(result.selected_agents) if result.selected_agents else '(none)'}
会话预设: {result.session_preset or '(none)'}
蓝图: {result.workflow_blueprint or '(none)'}

质量门阈值: {result.consensus_threshold * 100}%

是否开始协作流程？
- 输入 'yes' 或 'y' 开始
- 输入 'no' 或 'n' 取消（当前 AI 单独处理）
"""
        else:
            prompt += f"""
Current AI: {current_agent}
Primary AI: {result.primary}
Reviewers: {', '.join(result.reviewers)}
Project Categories: {categories}
Auto Skills: {skills}
Execution Mode: {result.execution_mode}
Selected Agents: {', '.join(result.selected_agents) if result.selected_agents else '(none)'}
Session Preset: {result.session_preset or '(none)'}
Blueprint: {result.workflow_blueprint or '(none)'}

Quality Gate Threshold: {result.consensus_threshold * 100}%

Start collaboration workflow?
- Enter 'yes' or 'y' to start
- Enter 'no' or 'n' to cancel (current AI handles alone)
"""

        return prompt
