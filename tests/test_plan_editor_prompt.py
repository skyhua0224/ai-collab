from __future__ import annotations

from pathlib import Path

from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result


def _sample_result() -> UxLabV3Result:
    return UxLabV3Result(
        status="planned",
        workspace=Path("/tmp/project"),
        controller="gemini",
        task="验证 ai-collab 编排编辑",
        lang="zh-CN",
        planner_mode="live",
        plan=[
            LabPlanItem("S1", "总体规划", "gemini", 3, "有完整规划"),
            LabPlanItem("S2", "执行验证", "claude", 5, "拿到验证结果"),
        ],
        controller_plan={
            "plan_version": "1.0",
            "controller": "gemini",
            "requires_multi_agent": True,
            "approval_question": "是否开始执行？",
            "agents": [
                {
                    "name": "gemini",
                    "model": "gemini-2.5-pro",
                    "persona": "controller",
                    "why": "负责总体规划",
                },
                {
                    "name": "claude",
                    "model": "claude-sonnet-4-6",
                    "persona": "collaborator",
                    "why": "负责执行验证",
                },
            ],
            "steps": [
                {
                    "id": "S1",
                    "owner": "gemini",
                    "goal": "总体规划",
                    "done_when": "有完整规划",
                    "eta_minutes": 3,
                },
                {
                    "id": "S2",
                    "owner": "claude",
                    "goal": "执行验证",
                    "done_when": "拿到验证结果",
                    "eta_minutes": 5,
                },
            ],
        },
    )


def test_plan_draft_insert_move_delete_and_apply_back() -> None:
    from ai_collab.plan_editor_prompt import (
        apply_plan_draft_to_result,
        insert_step_after,
        move_step,
        plan_draft_from_result,
        rename_task,
        update_step,
    )

    result = _sample_result()
    draft = plan_draft_from_result(result)

    rename_task(draft, "新的编排任务")
    insert_step_after(
        draft,
        index=0,
        owner="codex",
        title="实现修复",
        eta_minutes=8,
        done_when="提交实现结果",
    )
    move_step(draft, index=1, direction=1)
    update_step(
        draft,
        index=2,
        title="实现修复并收尾",
        owner="codex",
        eta_minutes=9,
        done_when="提交实现结果并收尾",
    )

    updated = apply_plan_draft_to_result(draft, result)

    assert updated.task == "新的编排任务"
    assert [item.sx for item in updated.plan] == ["S1", "S2", "S3"]
    assert [item.title for item in updated.plan] == ["总体规划", "执行验证", "实现修复并收尾"]
    assert [item.agent for item in updated.plan] == ["gemini", "claude", "codex"]
    assert updated.controller_plan is not None
    assert [step["id"] for step in updated.controller_plan["steps"]] == ["S1", "S2", "S3"]
    assert [step["owner"] for step in updated.controller_plan["steps"]] == ["gemini", "claude", "codex"]
    assert updated.controller_plan["agents"][0]["model"] == "gemini-2.5-pro"
    assert updated.controller_plan["agents"][1]["model"] == "claude-sonnet-4-6"
    assert updated.controller_plan["agents"][2]["model"] == "unknown"


def test_plan_draft_prevents_deleting_last_step() -> None:
    from ai_collab.plan_editor_prompt import delete_step, plan_draft_from_result

    result = _sample_result()
    result.plan = [result.plan[0]]
    result.controller_plan = {
        **(result.controller_plan or {}),
        "steps": [
            {
                "id": "S1",
                "owner": "gemini",
                "goal": "总体规划",
                "done_when": "有完整规划",
                "eta_minutes": 3,
            }
        ],
    }
    draft = plan_draft_from_result(result)

    deleted = delete_step(draft, index=0)

    assert deleted is False
    assert [step.id for step in draft.steps] == ["S1"]


def test_execution_targets_include_disabled_future_modes(monkeypatch) -> None:
    from ai_collab.core.config import Config
    from ai_collab.launch_prompt import LaunchPromptState
    from ai_collab.plan_editor_prompt import build_execution_targets

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.runtime_mode = "tmux"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/ai-collab"),
        from_entry=True,
    )
    monkeypatch.setattr("ai_collab.plan_editor_prompt.shutil.which", lambda _name: "/opt/homebrew/bin/tmux")

    targets = build_execution_targets(state, _sample_result())

    assert [target.key for target in targets] == ["tmux", "iterm2", "console", "gui", "save"]
    assert [target.enabled for target in targets] == [True, False, False, False, True]
    assert all(target.badge == "Coming Soon" for target in targets[1:4])


def test_execution_targets_disable_tmux_for_non_multi_agent_plan(monkeypatch) -> None:
    from ai_collab.core.config import Config
    from ai_collab.launch_prompt import LaunchPromptState
    from ai_collab.plan_editor_prompt import build_execution_targets

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.runtime_mode = "tmux"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/ai-collab"),
        from_entry=True,
    )
    monkeypatch.setattr("ai_collab.plan_editor_prompt.shutil.which", lambda _name: "/opt/homebrew/bin/tmux")

    result = UxLabV3Result(
        status="planned",
        workspace=Path("/tmp/project"),
        controller="codex",
        task="单 Agent 计划",
        lang="zh-CN",
        planner_mode="live",
        plan=[LabPlanItem("S1", "只由主控执行", "codex", 5, "返回结果")],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": False,
            "steps": [{"id": "S1", "owner": "codex", "goal": "只由主控执行", "done_when": "返回结果", "eta_minutes": 5}],
        },
    )

    targets = build_execution_targets(state, result)

    assert [target.key for target in targets] == ["tmux", "iterm2", "console", "gui", "save"]
    assert [target.enabled for target in targets] == [False, False, False, False, True]
    assert "多 Agent" in targets[0].description
