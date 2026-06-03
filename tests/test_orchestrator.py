from ai_collab.core.config import Config
from ai_collab.core.orchestrator import OrchestrationPlanner


def test_orchestrator_prefers_product_role_policy_for_default_config() -> None:
    config = Config.create_default()
    planner = OrchestrationPlanner(config)

    plan = planner.build_plan(
        task="制作一个贪吃蛇小游戏",
        current_provider="codex",
        intent="architecture",
    )

    assignments = {step["role"]: step["agent"] for step in plan["orchestration_plan"]}

    assert assignments["tech-selection"] == "gemini"
    assert assignments["implementation"] == "codex"
    assert assignments["quality-review"] == "claude"


def test_orchestrator_uses_v2_metadata_by_default() -> None:
    config = Config.create_default()
    planner = OrchestrationPlanner(config)

    plan = planner.build_plan(
        task="实现一个管理端模块",
        current_provider="codex",
        intent="implementation",
    )

    assert plan["workflow_engine"] == "v2"
    assert plan["session_preset"] == "auto"
    assert plan["workflow_blueprint"] == "delivery-loop"


def test_orchestrator_can_override_session_preset_per_run() -> None:
    config = Config.create_default()
    planner = OrchestrationPlanner(config)

    plan = planner.build_plan(
        task="做一个更精致的贪吃蛇小游戏",
        current_provider="codex",
        intent="implementation",
        session_preset="design-first",
    )

    assert plan["session_preset"] == "design-first"
    assert plan["workflow_blueprint"] == "design-led-loop"


def test_orchestrator_keeps_small_bounded_task_single_agent() -> None:
    config = Config.create_default()
    planner = OrchestrationPlanner(config)

    plan = planner.build_plan(
        task="fix typo in README",
        current_provider="codex",
        intent="implementation",
    )

    roles = {step["role"] for step in plan["orchestration_plan"]}
    assert roles == {"implementation"}
    assert plan["mode"] == "single-agent"
