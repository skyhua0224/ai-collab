"""Editable orchestration draft helpers for thin launch flow."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result


SUPPORTED_OWNERS = ("codex", "claude", "gemini")


@dataclass
class PlanDraftStep:
    id: str
    title: str
    owner: str
    eta_minutes: int
    done_when: str


@dataclass
class PlanDraft:
    workspace: Path
    controller: str
    task: str
    lang: str
    planner_mode: str
    steps: list[PlanDraftStep]
    source_controller_plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionTargetOption:
    key: str
    label: str
    description: str
    enabled: bool
    badge: str = ""


def _normalize_owner(owner: str | None, *, default: str = "codex") -> str:
    candidate = str(owner or "").strip().lower()
    if candidate in SUPPORTED_OWNERS:
        return candidate
    return default


def _safe_eta(value: Any, *, default: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _agent_entries_by_name(controller_plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(controller_plan, dict):
        return {}
    entries = controller_plan.get("agents", [])
    if not isinstance(entries, list):
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        name = _normalize_owner(item.get("name"), default="")
        if name:
            mapping[name] = deepcopy(item)
    return mapping


def _renumber_steps(steps: list[PlanDraftStep]) -> None:
    for index, step in enumerate(steps, start=1):
        step.id = f"S{index}"


def plan_draft_from_result(result: UxLabV3Result) -> PlanDraft:
    steps = [
        PlanDraftStep(
            id=str(item.sx),
            title=str(item.title),
            owner=_normalize_owner(item.agent, default=result.controller),
            eta_minutes=_safe_eta(item.eta_minutes, default=5),
            done_when=str(item.done_when),
        )
        for item in result.plan
    ]
    if not steps:
        steps = [
            PlanDraftStep(
                id="S1",
                title=result.task or "Untitled step",
                owner=_normalize_owner(result.controller),
                eta_minutes=5,
                done_when=result.task or "Return a usable result.",
            )
        ]
    _renumber_steps(steps)
    return PlanDraft(
        workspace=result.workspace,
        controller=_normalize_owner(result.controller),
        task=result.task,
        lang=result.lang,
        planner_mode=result.planner_mode,
        steps=steps,
        source_controller_plan=deepcopy(result.controller_plan),
    )


def rename_task(draft: PlanDraft, task: str) -> None:
    draft.task = str(task or "").strip()


def update_step(
    draft: PlanDraft,
    *,
    index: int,
    title: str | None = None,
    owner: str | None = None,
    eta_minutes: int | None = None,
    done_when: str | None = None,
) -> None:
    step = draft.steps[index]
    if title is not None:
        step.title = str(title).strip() or step.title
    if owner is not None:
        step.owner = _normalize_owner(owner, default=step.owner)
    if eta_minutes is not None:
        step.eta_minutes = _safe_eta(eta_minutes, default=step.eta_minutes)
    if done_when is not None:
        step.done_when = str(done_when).strip() or step.done_when


def insert_step_after(
    draft: PlanDraft,
    *,
    index: int,
    owner: str,
    title: str,
    eta_minutes: int = 5,
    done_when: str = "",
) -> int:
    step = PlanDraftStep(
        id="",
        title=str(title).strip() or "New step",
        owner=_normalize_owner(owner, default=draft.controller),
        eta_minutes=_safe_eta(eta_minutes, default=5),
        done_when=str(done_when).strip() or (str(title).strip() or "New step"),
    )
    insert_at = max(0, min(len(draft.steps), index + 1))
    draft.steps.insert(insert_at, step)
    _renumber_steps(draft.steps)
    return insert_at


def delete_step(draft: PlanDraft, *, index: int) -> bool:
    if len(draft.steps) <= 1:
        return False
    draft.steps.pop(index)
    _renumber_steps(draft.steps)
    return True


def move_step(draft: PlanDraft, *, index: int, direction: int) -> int:
    if not draft.steps:
        return 0
    target = max(0, min(len(draft.steps) - 1, index + direction))
    if target == index:
        return index
    step = draft.steps.pop(index)
    draft.steps.insert(target, step)
    _renumber_steps(draft.steps)
    return target


def _build_controller_plan(draft: PlanDraft) -> dict[str, Any]:
    source = deepcopy(draft.source_controller_plan) if isinstance(draft.source_controller_plan, dict) else {}
    source.setdefault("plan_version", "1.0")
    source["controller"] = draft.controller
    source["requires_multi_agent"] = len({step.owner for step in draft.steps}) > 1

    agent_lookup = _agent_entries_by_name(draft.source_controller_plan)
    ordered_agents: list[str] = []
    for step in draft.steps:
        if step.owner not in ordered_agents:
            ordered_agents.append(step.owner)
    if draft.controller in ordered_agents:
        ordered_agents = [draft.controller, *[name for name in ordered_agents if name != draft.controller]]

    agents: list[dict[str, Any]] = []
    for name in ordered_agents:
        existing = deepcopy(agent_lookup.get(name, {}))
        agents.append(
            {
                "name": name,
                "model": str(existing.get("model", "")).strip() or "unknown",
                "persona": str(existing.get("persona", "")).strip() or ("controller" if name == draft.controller else "collaborator"),
                "why": str(existing.get("why", "")).strip(),
            }
        )
    source["agents"] = agents
    source["steps"] = [
        {
            "id": step.id,
            "owner": step.owner,
            "goal": step.title,
            "input": draft.task,
            "output": step.title,
            "done_when": step.done_when,
            "eta_minutes": _safe_eta(step.eta_minutes, default=5),
        }
        for step in draft.steps
    ]
    source.setdefault("approval_question", "")
    return source


def apply_plan_draft_to_result(draft: PlanDraft, source_result: UxLabV3Result) -> UxLabV3Result:
    controller_plan = _build_controller_plan(draft)
    return UxLabV3Result(
        status="planned",
        workspace=draft.workspace,
        controller=draft.controller,
        task=draft.task,
        lang=draft.lang,
        planner_mode=draft.planner_mode,
        plan=[
            LabPlanItem(
                step.id,
                step.title,
                step.owner,
                _safe_eta(step.eta_minutes, default=5),
                step.done_when,
            )
            for step in draft.steps
        ],
        bundle_path=source_result.bundle_path,
        error_message=source_result.error_message,
        controller_plan=controller_plan,
    )


def build_execution_targets(state: Any) -> list[ExecutionTargetOption]:
    lang = getattr(getattr(state, "config", None), "ui_language", "en-US")
    zh = lang == "zh-CN"
    return [
        ExecutionTargetOption(
            key="tmux",
            label="tmux runtime",
            description="使用现有 tmux 编排链立即开始任务。" if zh else "Start the task through the current tmux orchestration chain.",
            enabled=True,
        ),
        ExecutionTargetOption(
            key="iterm2",
            label="iTerm2 多窗口" if zh else "iTerm2 multi-window",
            description="保留为未来多窗口执行目标。" if zh else "Reserved for a future multi-window execution target.",
            enabled=False,
            badge="Coming Soon",
        ),
        ExecutionTargetOption(
            key="console",
            label="Session Console",
            description="保留为未来独立会话控制台。" if zh else "Reserved for the future standalone session console.",
            enabled=False,
            badge="Coming Soon",
        ),
        ExecutionTargetOption(
            key="gui",
            label="GUI",
            description="保留为未来 GUI 执行外壳。" if zh else "Reserved for the future GUI execution shell.",
            enabled=False,
            badge="Coming Soon",
        ),
        ExecutionTargetOption(
            key="save",
            label="仅保存启动包" if zh else "Save startup bundle only",
            description="只写入启动包，稍后再执行。" if zh else "Only write the startup bundle and run it later.",
            enabled=True,
        ),
    ]


__all__ = [
    "ExecutionTargetOption",
    "PlanDraft",
    "PlanDraftStep",
    "apply_plan_draft_to_result",
    "build_execution_targets",
    "delete_step",
    "insert_step_after",
    "move_step",
    "plan_draft_from_result",
    "rename_task",
    "update_step",
]
