"""Service layer for the formal launcher flow."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Optional, Sequence

from ai_collab.core.config import Config
from ai_collab.core.detector import CollaborationDetector, CollaborationResult
from ai_collab.core.selector import ModelSelector
from ai_collab.ux_lab_v3 import (
    DEFAULT_AGENTS,
    LabPlanItem,
    UxLabV3Result,
    build_mock_plan_v3,
    export_launch_bundle_v3,
    map_controller_plan_to_items,
    resolve_v3_language,
)

PlanningProgressCallback = Callable[[str, dict[str, Any]], None]
CancelCheck = Callable[[], bool]


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _step_title_from_payload(step: dict[str, Any], *, fallback: str) -> str:
    goal = _normalize_text(step.get("goal"))
    output_text = _normalize_text(step.get("output"))
    return goal or output_text or fallback


def _is_placeholder_step_title(title: str, step_id: str, *, lang: str) -> bool:
    normalized = _normalize_text(title).lower()
    step_token = _normalize_text(step_id).lower()
    if not normalized:
        return True
    if normalized == step_token:
        return True
    if re.fullmatch(r"s\d+", normalized):
        return True
    if re.fullmatch(r"step\s*\d+", normalized):
        return True
    generic_tokens = {"plan", "task", "test", "planning", "步骤", "计划", "任务", "测试"}
    if normalized in generic_tokens:
        return True
    if lang == "zh-CN" and len(normalized) <= 2 and normalized in {"计划", "测试", "任务"}:
        return True
    return False


def _is_placeholder_done_when(done_when: str, title: str, *, lang: str) -> bool:
    normalized = _normalize_text(done_when)
    if not normalized:
        return True
    lower = normalized.lower()
    title_lower = _normalize_text(title).lower()
    generic_matches = {
        "json plan returned",
        "json ready",
        "return plan",
        "provide a checkable result",
    }
    if lower in generic_matches:
        return True
    if lang == "zh-CN":
        if normalized == f"完成 {title} 并给出可检查结果。":
            return True
        if "可检查结果" in normalized and title_lower in {"s1", "s2", "s3", "计划", "测试", "任务"}:
            return True
    else:
        if normalized == f"Complete {title} and provide a checkable result.":
            return True
    return False


def _is_placeholder_approval_question(question: str, task: str, *, lang: str) -> bool:
    normalized = _normalize_text(question)
    if not normalized:
        return True
    lower = normalized.lower()
    generic = {
        "是否执行？",
        "是否执行?",
        "proceed?",
        "should ai-collab execute this plan?",
    }
    if normalized in generic or lower in generic:
        return True
    task_text = _normalize_text(task)
    if task_text and task_text not in normalized:
        if lang == "zh-CN" and normalized in {"是否开始执行？", "是否开始执行", "确认执行吗？"}:
            return True
    return False


def detect_controller_plan_quality_issues(*, controller_plan: Optional[dict[str, Any]], task: str, lang: str) -> list[str]:
    if not isinstance(controller_plan, dict):
        return ["empty-plan"]

    issues: list[str] = []
    steps = controller_plan.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return ["missing-steps"]

    owners: list[str] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            issues.append(f"invalid-step-{index}")
            continue
        step_id = _normalize_text(step.get("id")) or f"S{index}"
        owner = _normalize_text(step.get("owner")).lower() or "codex"
        title = _step_title_from_payload(step, fallback=step_id)
        done_when = _normalize_text(step.get("done_when"))
        owners.append(owner)
        if _is_placeholder_step_title(title, step_id, lang=lang):
            issues.append(f"placeholder-title:{step_id}")
        if _is_placeholder_done_when(done_when, title, lang=lang):
            issues.append(f"placeholder-done:{step_id}")

    if _is_placeholder_approval_question(_normalize_text(controller_plan.get("approval_question")), task, lang=lang):
        issues.append("placeholder-approval")

    requires_multi = bool(controller_plan.get("requires_multi_agent", False))
    unique_owners = {owner for owner in owners if owner}
    if requires_multi and (len(unique_owners) < 2 or len(steps) < 2):
        issues.append("fake-multi-agent")

    return issues


def build_quality_retry_prompt(*, base_prompt: str, issues: Sequence[str], task: str, lang: str) -> str:
    if lang == "zh-CN":
        return (
            f"{base_prompt}\n\n"
            "上一版 JSON 计划质量不合格，请重新生成，并严格修正这些问题：\n"
            f"- 命中的问题：{', '.join(issues)}\n"
            "- 不要返回占位标题，例如 S1、步骤1、计划、任务、测试。\n"
            "- 每个步骤标题都必须是有任务语义的完整短句。\n"
            "- done_when 必须具体可验收，不能再写“完成 S1 并给出可检查结果”。\n"
            f"- approval_question 必须明确提到任务“{task}”，不能只写“是否执行？”。\n"
            "- 如果 requires_multi_agent=true，则至少生成 2 个步骤，并且至少 2 个 Agent 真正拥有步骤。\n"
            "- 最终仍然只输出 JSON 对象本身，不要解释。"
        )
    return (
        f"{base_prompt}\n\n"
        "The previous JSON plan was too generic. Regenerate it and fix these issues:\n"
        f"- Triggered issues: {', '.join(issues)}\n"
        "- Do not use placeholder step titles such as S1, Step 1, Plan, Task, or Test.\n"
        "- Every step title must be a concrete task sentence.\n"
        "- done_when must be specific and verifiable, not template text.\n"
        f"- approval_question must explicitly mention the task '{task}', not only 'Proceed?'\n"
        "- If requires_multi_agent=true, produce at least 2 steps with at least 2 agents actually owning steps.\n"
        "- Return only the JSON object."
    )


def hydrate_controller_plan_models(*, config: Config, task: str, controller_plan: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(controller_plan, dict):
        return controller_plan
    agents = controller_plan.get("agents", [])
    if not isinstance(agents, list):
        return controller_plan
    selector = ModelSelector(config)
    for item in agents:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        model = str(item.get("model", "")).strip()
        if not name or (model and model.lower() != "unknown"):
            continue
        try:
            selected = selector.select_model(name, task, "default")
        except Exception:  # noqa: BLE001
            continue
        resolved_model = str(selected.model or "").strip()
        if resolved_model:
            item["model"] = resolved_model
    return controller_plan


def _single_agent_step_goal(*, task: str, lang: str) -> str:
    normalized = _normalize_text(task)
    lower = normalized.lower()
    if lower in {"1", "1.", "1。", "hello", "hi", "hey", "ok", "okay", "test", "sb"}:
        return "直接响应用户输入" if lang == "zh-CN" else "Respond directly to the user's prompt"
    return normalized or ("完成当前任务" if lang == "zh-CN" else "Complete the task")


def _single_agent_done_when(*, task: str, lang: str) -> str:
    normalized = _normalize_text(task)
    if lang == "zh-CN":
        if normalized:
            return f"直接完成“{normalized}”并给出可检查结果。"
        return "直接完成当前任务并给出可检查结果。"
    if normalized:
        return f"Directly complete '{normalized}' and provide a checkable result."
    return "Directly complete the task and provide a checkable result."


def _single_agent_approval_question(*, task: str, lang: str) -> str:
    normalized = _normalize_text(task)
    if lang == "zh-CN":
        return f"是否按单 Agent 方式直接执行“{normalized or '当前任务'}”？"
    return f"Execute '{normalized or 'this task'}' as a single-agent task?"


def _single_agent_controller_plan(
    *,
    config: Config,
    controller: str,
    task: str,
    lang: str,
    detection: Optional[CollaborationResult] = None,
) -> dict[str, Any]:
    selector = ModelSelector(config)
    model = "unknown"
    try:
        model = str(selector.select_model(controller, task, "default").model or "unknown")
    except Exception:  # noqa: BLE001
        pass

    return {
        "plan_version": "1.0",
        "controller": controller,
        "requires_multi_agent": False,
        "workflow_engine": str(getattr(detection, "workflow_engine", "") or "v2"),
        "session_preset": str(getattr(detection, "session_preset", "") or "auto"),
        "workflow_blueprint": str(getattr(detection, "workflow_blueprint", "") or "delivery-loop"),
        "agents": [
            {
                "name": controller,
                "model": model,
                "persona": "implementation-engineer",
                "why": "single-agent task",
            }
        ],
        "steps": [
            {
                "id": "S1",
                "owner": controller,
                "goal": _single_agent_step_goal(task=task, lang=lang),
                "input": _normalize_text(task),
                "output": "direct-response",
                "done_when": _single_agent_done_when(task=task, lang=lang),
                "eta_minutes": 8,
            }
        ],
        "approval_question": _single_agent_approval_question(task=task, lang=lang),
    }


def resolve_task_text(*, task: Optional[str], task_file: Optional[Path]) -> str:
    if task_file is not None:
        return Path(task_file).expanduser().read_text(encoding="utf-8").strip()
    return str(task or "").strip()


def enabled_agents(config: Config) -> list[str]:
    providers = getattr(config, "providers", {}) or {}
    enabled = [name for name, provider in providers.items() if getattr(provider, "enabled", False)]
    if not enabled:
        return list(DEFAULT_AGENTS)
    ordered = [agent for agent in DEFAULT_AGENTS if agent in enabled]
    for agent in enabled:
        if agent not in ordered:
            ordered.append(agent)
    return ordered


def resolve_controller(controller: Optional[str], current_controller: str, available_agents: Sequence[str]) -> str:
    chosen = str(controller or current_controller or "").strip()
    if chosen in available_agents:
        return chosen
    return available_agents[0] if available_agents else "codex"


def request_live_plan_details(
    *,
    config: Config,
    controller: str,
    task: str,
    workspace: Path,
    lang: str,
    request_plan: Optional[Callable[..., tuple[Optional[dict[str, Any]], Optional[str]]]] = None,
    progress_callback: PlanningProgressCallback | None = None,
    cancel_requested: CancelCheck | None = None,
) -> tuple[Optional[list[LabPlanItem]], Optional[dict[str, Any]], Optional[str]]:
    from ai_collab.ux_lab_v3 import build_planner_prompt

    request_callable = request_plan
    if request_callable is None:
        from ai_collab import cli as cli_module

        request_callable = None

    prompt_text = build_planner_prompt(task=task, controller=controller, workspace=workspace, lang=lang, config=config)
    if progress_callback is not None:
        progress_callback(
            "prompt_ready",
            {
                "controller": controller,
                "workspace": str(workspace),
                "prompt_text": prompt_text,
            },
        )

    plan_payload: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    current_prompt = prompt_text

    for attempt in range(2):
        if request_callable is None:
            from ai_collab import cli as cli_module

            plan_payload, error = cli_module._request_controller_plan(
                config=config,
                controller=controller,
                prompt_text=current_prompt,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
            )
        else:
            plan_payload, error = request_callable(
                config=config,
                controller=controller,
                prompt_text=current_prompt,
            )

        if progress_callback is not None:
            if error:
                progress_callback("request_failed", {"error": error})
            else:
                progress_callback(
                    "json_received",
                    {
                        "step_count": len(plan_payload.get("steps", [])) if isinstance(plan_payload, dict) else 0,
                        "controller_plan": plan_payload if isinstance(plan_payload, dict) else None,
                    },
                )

        if error:
            return None, None, error
        if not isinstance(plan_payload, dict):
            return None, None, "Controller returned empty planning payload"

        plan_payload = hydrate_controller_plan_models(
            config=config,
            task=task,
            controller_plan=plan_payload,
        )
        issues = detect_controller_plan_quality_issues(
            controller_plan=plan_payload,
            task=task,
            lang=lang,
        )
        if not issues:
            try:
                items = map_controller_plan_to_items(plan_payload, lang=lang)
                if progress_callback is not None:
                    progress_callback("steps_mapped", {"step_count": len(items)})
                return items, plan_payload, None
            except ValueError as exc:
                return None, plan_payload, str(exc)
        if attempt == 0:
            current_prompt = build_quality_retry_prompt(
                base_prompt=prompt_text,
                issues=issues,
                task=task,
                lang=lang,
            )
            continue
        issue_label = "、".join(issues) if lang == "zh-CN" else ", ".join(issues)
        return None, plan_payload, (
            f"主控连续两次返回占位式计划，请稍后重试或切换主控。问题：{issue_label}"
            if lang == "zh-CN"
            else f"Controller returned a low-quality placeholder plan twice. Issues: {issue_label}"
        )

    return None, plan_payload, "Controller returned empty planning payload"


def request_live_plan(
    *,
    config: Config,
    controller: str,
    task: str,
    workspace: Path,
    lang: str,
    request_plan: Optional[Callable[..., tuple[Optional[dict[str, Any]], Optional[str]]]] = None,
) -> tuple[Optional[list[LabPlanItem]], Optional[str]]:
    items, _controller_plan, error = request_live_plan_details(
        config=config,
        controller=controller,
        task=task,
        workspace=workspace,
        lang=lang,
        request_plan=request_plan,
    )
    return items, error


def run_launcher_flow(
    *,
    config: Config,
    cwd: Path,
    workspace: Optional[Path] = None,
    controller: Optional[str] = None,
    task: Optional[str] = None,
    task_file: Optional[Path] = None,
    skip_review: bool = False,
    planner_mode: str = "live",
    output_bundle: Optional[Path] = None,
    progress_callback: PlanningProgressCallback | None = None,
    cancel_requested: CancelCheck | None = None,
) -> UxLabV3Result:
    lang = resolve_v3_language(getattr(config, "ui_language", "en-US"))
    resolved_task = resolve_task_text(task=task, task_file=task_file)
    resolved_workspace = Path(workspace or cwd).expanduser().resolve()
    available = enabled_agents(config)
    resolved_controller = resolve_controller(controller, config.current_controller, available)
    mode = planner_mode if planner_mode in {"live", "mock"} else "live"
    detection: Optional[CollaborationResult] = None
    try:
        detection = CollaborationDetector(config).detect(resolved_task, resolved_controller)
    except Exception:  # noqa: BLE001
        detection = None

    if detection is not None and not detection.need_collaboration:
        controller_plan = _single_agent_controller_plan(
            config=config,
            controller=resolved_controller,
            task=resolved_task,
            lang=lang,
            detection=detection,
        )
        plan = map_controller_plan_to_items(controller_plan, lang=lang)
        error = None
    elif mode == "mock":
        plan = build_mock_plan_v3(resolved_task, resolved_controller, lang, available_agents=available)
        controller_plan = None
        error = None
    else:
        plan, controller_plan, error = request_live_plan_details(
            config=config,
            controller=resolved_controller,
            task=resolved_task,
            workspace=resolved_workspace,
            lang=lang,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )

    if error:
        return UxLabV3Result(
            status="error",
            workspace=resolved_workspace,
            controller=resolved_controller,
            task=resolved_task,
            lang=lang,
            planner_mode=mode,
            plan=[],
            error_message=error,
            controller_plan=controller_plan,
        )

    assert plan is not None
    bundle_path = None
    status = "planned"
    if skip_review:
        bundle_path = export_launch_bundle_v3(
            workspace=resolved_workspace,
            controller=resolved_controller,
            task=resolved_task,
            lang=lang,
            planner_mode=mode,
            plan=plan,
            output_path=output_bundle,
            controller_plan=controller_plan,
        )
        status = "sent"

    return UxLabV3Result(
        status=status,
        workspace=resolved_workspace,
        controller=resolved_controller,
        task=resolved_task,
        lang=lang,
        planner_mode=mode,
        plan=plan,
        bundle_path=bundle_path,
        controller_plan=controller_plan,
    )
