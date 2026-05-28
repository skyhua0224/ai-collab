"""Workflow V2 registry for preset-driven, stage-based orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ResponsibilityStage = Literal[
    "collect",
    "model",
    "plan",
    "artifact",
    "execute",
    "validate",
    "correct",
    "deliver",
]


@dataclass(frozen=True)
class WorkflowStageV2:
    """A single stage in the V2 stage-based workflow model."""

    key: str
    responsibility_stage: ResponsibilityStage
    goal: str
    default_agent: str | None = None
    outputs: tuple[str, ...] = ()
    allowed_artifacts: tuple[str, ...] = ()
    timebox_minutes: int | None = None
    boundary: str = "stage"


@dataclass(frozen=True)
class WorkflowBlueprintV2:
    """Internal workflow blueprint for V2 orchestration."""

    key: str
    description: str
    stages: tuple[WorkflowStageV2, ...]
    supports_correction: bool = True


@dataclass(frozen=True)
class SessionPresetDefinition:
    """User-facing session preset that maps to a V2 workflow blueprint."""

    key: str
    label: str
    description: str
    workflow_key: str
    preferred_artifacts: tuple[str, ...] = field(default_factory=tuple)
    default_optimization_goal: str = "balanced"
    user_visible: bool = True


def builtin_workflow_blueprints() -> dict[str, WorkflowBlueprintV2]:
    """Return the built-in V2 workflow blueprints."""
    return {
        "delivery-loop": WorkflowBlueprintV2(
            key="delivery-loop",
            description="Default delivery loop for implementation-oriented work.",
            stages=(
                WorkflowStageV2("collect-context", "collect", "Collect facts and current context", default_agent="codex", outputs=("evidence-pack",), timebox_minutes=15),
                WorkflowStageV2("model-system", "model", "Build a working model of the current system/problem", default_agent="gemini", outputs=("problem-model",), timebox_minutes=20),
                WorkflowStageV2("choose-approach", "plan", "Choose an approach and boundaries", default_agent="gemini", outputs=("execution-direction",), timebox_minutes=15),
                WorkflowStageV2("execute-change", "execute", "Implement the requested change", default_agent="codex", outputs=("code-change",), timebox_minutes=45),
                WorkflowStageV2("validate-result", "validate", "Verify behavior, quality, and regressions", default_agent="claude", outputs=("validation-report",), timebox_minutes=20),
                WorkflowStageV2("correct-drift", "correct", "Correct drift, scope expansion, or bounded issues", default_agent="codex", outputs=("corrected-state",), timebox_minutes=15),
                WorkflowStageV2("deliver-outcome", "deliver", "Summarize and hand off the final result", outputs=("delivery-summary",), timebox_minutes=10),
            ),
        ),
        "design-led-loop": WorkflowBlueprintV2(
            key="design-led-loop",
            description="Design-first loop for UI, interaction, and high-uncertainty product work.",
            stages=(
                WorkflowStageV2("collect-context", "collect", "Collect current UI, constraints, and neighboring patterns", default_agent="codex", outputs=("evidence-pack",), timebox_minutes=15),
                WorkflowStageV2("model-problem", "model", "Model interaction structure and constraints", default_agent="gemini", outputs=("interaction-model",), timebox_minutes=20),
                WorkflowStageV2("choose-design-direction", "plan", "Choose the design and implementation direction", default_agent="gemini", outputs=("design-direction",), timebox_minutes=20),
                WorkflowStageV2("produce-artifacts", "artifact", "Produce design artifacts before implementation", default_agent="gemini", outputs=("artifact-pack",), allowed_artifacts=("contract", "mockup", "skeleton"), timebox_minutes=30),
                WorkflowStageV2("execute-change", "execute", "Implement the approved design", default_agent="codex", outputs=("code-change",), timebox_minutes=45),
                WorkflowStageV2("validate-result", "validate", "Validate UX, regressions, and edge cases", default_agent="claude", outputs=("validation-report",), timebox_minutes=20),
                WorkflowStageV2("correct-drift", "correct", "Correct bounded issues without changing approved direction", default_agent="codex", outputs=("corrected-state",), timebox_minutes=15),
                WorkflowStageV2("deliver-outcome", "deliver", "Summarize and hand off the final result", outputs=("delivery-summary",), timebox_minutes=10),
            ),
        ),
        "diagnose-loop": WorkflowBlueprintV2(
            key="diagnose-loop",
            description="Diagnosis-first loop for debugging, performance, and incident analysis.",
            stages=(
                WorkflowStageV2("collect-evidence", "collect", "Collect logs, configs, reproduction steps, and symptoms", default_agent="codex", outputs=("evidence-pack",), timebox_minutes=20),
                WorkflowStageV2("model-failure", "model", "Build the root-cause model and hypothesis tree", default_agent="gemini", outputs=("diagnosis-model",), timebox_minutes=20),
                WorkflowStageV2("choose-experiment", "plan", "Choose the next experiment or fix direction", default_agent="gemini", outputs=("experiment-plan",), timebox_minutes=15),
                WorkflowStageV2("run-fix-or-experiment", "execute", "Run the targeted fix or experiment", default_agent="codex", outputs=("fix-or-experiment-result",), timebox_minutes=30),
                WorkflowStageV2("verify-recovery", "validate", "Verify stability and residual risk", default_agent="claude", outputs=("verification-report",), timebox_minutes=20),
                WorkflowStageV2("correct-drift", "correct", "Correct scope drift, blind retry loops, or overreach", outputs=("corrected-state",), timebox_minutes=10),
                WorkflowStageV2("deliver-outcome", "deliver", "Summarize diagnosis and next actions", outputs=("delivery-summary",), timebox_minutes=10),
            ),
            supports_correction=True,
        ),
        "research-loop": WorkflowBlueprintV2(
            key="research-loop",
            description="Research and synthesis loop for options, comparisons, and direction setting.",
            stages=(
                WorkflowStageV2("collect-sources", "collect", "Collect internal and external reference material", default_agent="codex", outputs=("source-pack",), timebox_minutes=20),
                WorkflowStageV2("model-landscape", "model", "Model the option space and decision axes", default_agent="gemini", outputs=("option-model",), timebox_minutes=25),
                WorkflowStageV2("choose-direction", "plan", "Recommend a direction or decision framework", default_agent="gemini", outputs=("decision-framework",), timebox_minutes=20),
                WorkflowStageV2("deliver-outcome", "deliver", "Deliver the synthesized recommendation", outputs=("delivery-summary",), timebox_minutes=10),
            ),
        ),
        "validation-loop": WorkflowBlueprintV2(
            key="validation-loop",
            description="Validation-first loop for acceptance, review, and bounded follow-up fixes.",
            stages=(
                WorkflowStageV2("collect-target", "collect", "Collect the change scope and expected behavior", default_agent="codex", outputs=("review-target",), timebox_minutes=10),
                WorkflowStageV2("validate-result", "validate", "Review behavior, regressions, and risks", default_agent="claude", outputs=("validation-report",), timebox_minutes=20),
                WorkflowStageV2("correct-drift", "correct", "Apply bounded fixes or escalate", default_agent="codex", outputs=("corrected-state",), timebox_minutes=15),
                WorkflowStageV2("deliver-outcome", "deliver", "Publish acceptance result or escalation summary", outputs=("delivery-summary",), timebox_minutes=10),
            ),
        ),
        "document-loop": WorkflowBlueprintV2(
            key="document-loop",
            description="Documentation and reporting loop based on content type rather than a fixed agent chain.",
            stages=(
                WorkflowStageV2("collect-material", "collect", "Collect implementation facts, prior notes, and source material", default_agent="codex", outputs=("source-pack",), timebox_minutes=15),
                WorkflowStageV2("model-structure", "model", "Choose structure and message hierarchy", default_agent="gemini", outputs=("doc-structure",), timebox_minutes=20),
                WorkflowStageV2("choose-writing-direction", "plan", "Choose voice, scope, and target artifact", default_agent="gemini", outputs=("doc-direction",), timebox_minutes=15),
                WorkflowStageV2("deliver-document", "deliver", "Write and land the final document artifact", default_agent="codex", outputs=("document-artifact",), timebox_minutes=20),
            ),
        ),
    }


def builtin_session_presets() -> dict[str, SessionPresetDefinition]:
    """Return user-facing built-in session presets."""
    return {
        "auto": SessionPresetDefinition(
            key="auto",
            label="自动路由",
            description="Use the system's default stage-based delivery loop.",
            workflow_key="delivery-loop",
        ),
        "quick-delivery": SessionPresetDefinition(
            key="quick-delivery",
            label="快速实现",
            description="Bias toward the shortest route to a working result.",
            workflow_key="delivery-loop",
            default_optimization_goal="speed-first",
        ),
        "design-first": SessionPresetDefinition(
            key="design-first",
            label="精致设计",
            description="Bias toward design clarity and explicit intermediate artifacts.",
            workflow_key="design-led-loop",
            preferred_artifacts=("contract", "mockup"),
            default_optimization_goal="quality-first",
        ),
        "debug-priority": SessionPresetDefinition(
            key="debug-priority",
            label="调试优先",
            description="Collect evidence, model the issue, and only then fix.",
            workflow_key="diagnose-loop",
            default_optimization_goal="balanced",
        ),
        "research-priority": SessionPresetDefinition(
            key="research-priority",
            label="研究优先",
            description="Bias toward synthesis, options, and decision support.",
            workflow_key="research-loop",
            default_optimization_goal="quality-first",
        ),
        "validation-first": SessionPresetDefinition(
            key="validation-first",
            label="验证优先",
            description="Bias toward acceptance, audit, and bounded follow-up fixes.",
            workflow_key="validation-loop",
            default_optimization_goal="quality-first",
        ),
        "document-first": SessionPresetDefinition(
            key="document-first",
            label="文档优先",
            description="Bias toward documentation structure and final deliverable quality.",
            workflow_key="document-loop",
            default_optimization_goal="quality-first",
        ),
    }


def resolve_workflow_blueprint(key: str) -> WorkflowBlueprintV2:
    """Resolve a built-in V2 workflow blueprint."""
    blueprints = builtin_workflow_blueprints()
    try:
        return blueprints[key]
    except KeyError as exc:
        raise KeyError(f"Unknown workflow v2 blueprint: {key}") from exc


def resolve_session_preset(key: str) -> SessionPresetDefinition:
    """Resolve a built-in session preset."""
    presets = builtin_session_presets()
    try:
        return presets[key]
    except KeyError as exc:
        raise KeyError(f"Unknown session preset: {key}") from exc


def find_session_preset_for_workflow_blueprint(
    workflow_blueprint: str,
    *,
    preferred: str | None = None,
) -> str | None:
    """Find a matching session preset key for a built-in workflow blueprint."""
    resolve_workflow_blueprint(workflow_blueprint)

    requested = str(preferred or "").strip()
    if requested:
        try:
            preset = resolve_session_preset(requested)
        except KeyError:
            pass
        else:
            if preset.workflow_key == workflow_blueprint:
                return requested

    for key, preset in builtin_session_presets().items():
        if preset.workflow_key == workflow_blueprint:
            return key
    return None


__all__ = [
    "ResponsibilityStage",
    "SessionPresetDefinition",
    "WorkflowBlueprintV2",
    "WorkflowStageV2",
    "builtin_session_presets",
    "builtin_workflow_blueprints",
    "find_session_preset_for_workflow_blueprint",
    "resolve_session_preset",
    "resolve_workflow_blueprint",
]
