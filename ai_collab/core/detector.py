"""
Collaboration detection module.
Detects if a task needs multi-AI collaboration.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ai_collab.core.config import Config
from ai_collab.core.orchestrator import OrchestrationPlanner
from ai_collab.core.profiler import ProjectProfiler


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


INTENT_KEYWORDS = {
    "documentation": ["blog", "博客", "文档", "README", "文章", "总结", "复盘", "writeup", "notes"],
    "design": ["ui", "界面", "设计", "mockup", "原型", "layout", "视觉", "交互"],
    "architecture": ["architecture", "架构", "方案", "重构", "refactor", "design pattern"],
    "implementation": ["implement", "实现", "开发", "build", "feature", "编码", "落地"],
    "debug": ["debug", "调试", "修复", "fix", "bug", "crash", "错误", "问题"],
    "security": ["security", "安全", "漏洞", "audit", "证书", "认证", "owasp"],
    "research": ["research", "调研", "探索", "对比", "evaluate", "benchmark", "study"],
    "testing": ["test", "测试", "tdd", "coverage", "验证", "回归"],
    "gameplay": ["unity", "unreal", "ue", "renpy", "game", "游戏", "关卡", "战斗", "状态机"],
}

TRIGGER_PRIORITY = {
    "fullstack-superapp": 16,
    "mobile-native": 14,
    "macos-native": 14,
    "game-dev": 14,
    "systems-tooling": 12,
    "security-audit": 8,
    "debugging": 8,
    "testing": 8,
    "visual-design": 6,
    "implementation": 4,
    "docs-writing": 4,
    "research": 4,
    "architecture": 0,
}

CATEGORY_PRIORITY = {
    "superapp-fullstack": 100,
    "mobile-native": 95,
    "macos-swift": 90,
    "game-dev": 85,
    "systems-tooling": 70,
    "docs-text": 50,
}


class CollaborationResult(BaseModel):
    """Result of collaboration detection."""

    need_collaboration: bool
    trigger: Optional[str] = None
    description: Optional[str] = None
    primary: Optional[str] = None
    reviewers: List[str] = Field(default_factory=list)
    workflow_name: Optional[str] = None
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

        profile = ProjectProfiler().detect()
        categories = list(profile.categories)
        enabled_categories = auto_cfg.get("enabled_project_categories", [])
        if isinstance(enabled_categories, list) and enabled_categories:
            filtered = [item for item in categories if item in enabled_categories]
            categories = filtered if filtered else list(enabled_categories)

        intent = self._infer_intent(task)
        trigger, matched_patterns = self._select_trigger(task, intent, categories)
        planner = OrchestrationPlanner(self.config)
        plan = planner.build_plan(
            task=task,
            current_provider=current_provider,
            intent=intent,
            trigger_name=trigger.get("name") if trigger else None,
        )
        if trigger and self._should_promote_to_fullstack(trigger=trigger, orchestration_plan=plan.get("orchestration_plan", [])):
            promoted = self._get_trigger_by_name("fullstack-superapp")
            if promoted:
                trigger = promoted

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

            fallback_workflow = self._fallback_workflow_name(plan)
            workflow_name = (
                str(selected_trigger.get("workflow", "")).strip()
                if selected_trigger
                else fallback_workflow
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
                need_collaboration=bool(workflow_name),
                trigger=selected_trigger.get("name", "planner-derived") if selected_trigger else "planner-derived",
                description=selected_trigger.get("description", "Planner-derived multi-agent orchestration")
                if selected_trigger
                else "Planner-derived multi-agent orchestration",
                primary=primary,
                reviewers=reviewers,
                workflow_name=workflow_name,
                workflow=self.config.workflows.get(workflow_name, {}),
                consensus_threshold=auto_cfg.get("consensus_threshold", 0.75),
                intent=intent,
                matched_patterns=matched_patterns,
                project_categories=categories,
                suggested_skills=self._suggest_skills(selected_trigger.get("name") if selected_trigger else None, categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
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
            fallback_workflow = self._fallback_workflow_name(plan)
            primary = self._plan_primary_agent(plan, current_provider)
            reviewers = [item for item in plan.get("selected_agents", []) if item != primary]
            return CollaborationResult(
                need_collaboration=bool(fallback_workflow),
                trigger="planner-derived" if fallback_workflow else None,
                description="Planner-derived multi-agent orchestration",
                primary=primary,
                reviewers=reviewers,
                workflow_name=fallback_workflow,
                workflow=self.config.workflows.get(fallback_workflow, {}),
                consensus_threshold=auto_cfg.get("consensus_threshold", 0.75),
                intent=intent,
                matched_patterns=matched_patterns,
                project_categories=categories,
                suggested_skills=self._suggest_skills(None, categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
            )

        if not trigger:
            return CollaborationResult(
                need_collaboration=False,
                intent=intent,
                project_categories=categories,
                suggested_skills=self._suggest_skills(None, categories),
                available_agents=plan.get("available_agents", []),
                orchestration_plan=plan.get("orchestration_plan", []),
                selected_agents=plan.get("selected_agents", []),
                execution_mode=str(plan.get("mode", "single-agent")),
            )

        workflow_name = trigger.get("workflow", "")
        workflow = self.config.workflows.get(workflow_name, {})

        return CollaborationResult(
            need_collaboration=True,
            trigger=trigger.get("name", ""),
            description=trigger.get("description", ""),
            primary=trigger.get("primary", current_provider),
            reviewers=trigger.get("reviewers", []),
            workflow_name=workflow_name,
            workflow=workflow,
            consensus_threshold=auto_cfg.get("consensus_threshold", 0.75),
            intent=intent,
            matched_patterns=matched_patterns,
            project_categories=categories,
            suggested_skills=self._suggest_skills(trigger.get("name"), categories),
            available_agents=plan.get("available_agents", []),
            orchestration_plan=plan.get("orchestration_plan", []),
            selected_agents=plan.get("selected_agents", []),
            execution_mode=str(plan.get("mode", "single-agent")),
        )

    def _is_auto_collaboration_enabled(self, auto_cfg: Dict) -> bool:
        if "enabled" in auto_cfg:
            return bool(auto_cfg.get("enabled"))
        if "auto_orchestration_enabled" in auto_cfg:
            return bool(auto_cfg.get("auto_orchestration_enabled"))
        return True

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

    def _fallback_workflow_name(self, plan: Dict[str, object]) -> str:
        steps = plan.get("orchestration_plan", [])
        roles = set()
        if isinstance(steps, list):
            roles = {str(step.get("role", "")) for step in steps if isinstance(step, dict)}

        if {"frontend-build", "backend-build"}.issubset(roles) and "full-stack" in self.config.workflows:
            return "full-stack"
        if "code-review" in self.config.workflows:
            return "code-review"
        workflows = list(self.config.workflows.keys())
        return workflows[0] if workflows else ""

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
        task: str,
        intent: Optional[str],
        categories: List[str],
    ) -> Tuple[Optional[Dict], List[str]]:
        triggers = self.config.auto_collaboration.get("triggers", [])
        task_lower = task.lower()

        candidates: List[Tuple[int, Dict, List[str]]] = []
        for trigger in triggers:
            patterns = trigger.get("patterns", [])
            matched = [p for p in patterns if p.lower() in task_lower]
            if not matched:
                continue

            score = sum(len(p) for p in matched)
            score += len(matched) * 10
            trigger_name = trigger.get("name", "")
            score += TRIGGER_PRIORITY.get(trigger_name, 0)

            # Keep intent guidance without overriding stronger domain triggers.
            if intent and trigger_name == self._intent_trigger_map().get(intent):
                score += 8

            candidates.append((score, trigger, matched))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            _, best_trigger, best_patterns = candidates[0]
            return best_trigger, best_patterns

        # No direct keyword match. Fall back to intent + project category mapping.
        fallback_name = self._trigger_name_from_profile_intent(intent, categories)
        if not fallback_name and intent:
            fallback_name = self._intent_trigger_map().get(intent)

        if not fallback_name:
            return None, []

        for trigger in triggers:
            if trigger.get("name") == fallback_name:
                return trigger, []

        return None, []

    def _infer_intent(self, task: str) -> Optional[str]:
        task_lower = task.lower()
        best_intent: Optional[str] = None
        best_score = 0

        for intent, keywords in INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in task_lower)
            if score > best_score:
                best_score = score
                best_intent = intent

        return best_intent

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

        lang = str(getattr(self.config, "ui_language", "en-US"))
        is_zh = lang == "zh-CN"

        if is_zh:
            prompt = f"""
🤝 检测到多 AI 协作任务

任务类型: {result.trigger} - {result.description}
用户请求: {task}

工作流: {result.workflow_name}
{workflow.get('description', '')}

执行步骤:
"""
        else:
            prompt = f"""
🤝 Multi-AI Collaboration Detected

Task Type: {result.trigger} - {result.description}
User Request: {task}

Workflow: {result.workflow_name}
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

Quality Gate Threshold: {result.consensus_threshold * 100}%

Start collaboration workflow?
- Enter 'yes' or 'y' to start
- Enter 'no' or 'n' to cancel (current AI handles alone)
"""

        return prompt
