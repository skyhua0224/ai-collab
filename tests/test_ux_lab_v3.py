import asyncio
import json
from pathlib import Path

import ai_collab.cli as cli
from ai_collab.core.config import Config
from ai_collab.ux_lab_v3 import (
    build_brand_banner,
    build_command_bar_state,
    build_controller_cards,
    export_launch_bundle_v3,
    build_workspace_preview_lines,
    build_workspace_session_lines,
    build_workspace_hint_line,
    build_workspace_summary_lines,
    choose_workspace_layout,
    discover_recent_workspaces,
    derive_workspace_tree_root,
    build_planner_prompt,
    build_review_list_lines,
    build_step_track,
    choose_review_layout,
    interpret_workspace_submission,
    load_workspace_history,
    load_workspace_session_records,
    map_controller_plan_to_items,
    parse_review_command,
    record_workspace_history,
    request_live_plan,
)
from ai_collab.ux_lab_v3 import UxLabV3Result
from textual.widgets import Button, DirectoryTree, Input


def test_build_brand_banner_uses_compact_form_for_narrow_width() -> None:
    banner = build_brand_banner(width=48, lang="zh-CN")

    assert len(banner) <= 2
    assert any("ai-collab" in line.lower() for line in banner)
    assert all(len(line) <= 48 for line in banner)


def test_choose_review_layout_stacks_on_narrow_terminal() -> None:
    assert choose_review_layout(96) == "stack"
    assert choose_review_layout(132) == "split"


def test_choose_workspace_layout_prefers_split_on_medium_terminal() -> None:
    assert choose_workspace_layout(96) == "stack"
    assert choose_workspace_layout(100) == "split"
    assert choose_workspace_layout(132) == "split"


def test_build_brand_banner_restores_ascii_form_for_medium_width() -> None:
    banner = build_brand_banner(width=110, lang="zh-CN")

    assert len(banner) >= 4
    assert any("___" in line or "/ \\" in line for line in banner)
    assert all(len(line) <= 110 for line in banner)


def test_build_workspace_summary_lines_stays_compact_and_keeps_paths_visible() -> None:
    lines = build_workspace_summary_lines(
        cwd=Path("/Users/skyhua/ai-collab"),
        selected=Path("/Users/skyhua/Desktop"),
        mode="tree",
        width=72,
        lang="zh-CN",
    )

    assert 1 <= len(lines) <= 2
    assert any("当前" in line for line in lines)
    assert any("选择" in line for line in lines)
    assert all(len(line) <= 72 for line in lines)


def test_build_workspace_hint_line_varies_by_mode() -> None:
    recent_hint = build_workspace_hint_line(mode="recent", width=72, lang="zh-CN")
    tree_hint = build_workspace_hint_line(mode="tree", width=72, lang="zh-CN")

    assert "Space" in recent_hint
    assert "Space" in tree_hint
    assert len(recent_hint) <= 72
    assert len(tree_hint) <= 72


def test_build_workspace_preview_lines_show_children_and_metadata(tmp_path) -> None:
    selected = tmp_path / "workspace"
    child_dir = selected / "src"
    child_file = selected / "README.md"
    child_dir.mkdir(parents=True)
    child_file.write_text("hello", encoding="utf-8")

    lines = build_workspace_preview_lines(
        selected=selected,
        mode="tree",
        width=80,
        lang="zh-CN",
    )

    joined = "\n".join(lines)
    assert "预览" not in lines[0]
    assert lines[0].startswith("/")
    assert "README.md" in joined
    assert "src/" in joined
    assert "2 项" in joined


def test_load_workspace_session_records_reads_recent_runs_and_task_preview(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    newer = workspace / ".ai-collab" / "runs" / "20260309T120000Z-aaaabbbb"
    older = workspace / ".ai-collab" / "runs" / "20260308T110000Z-ccccdddd"
    newer.mkdir(parents=True)
    older.mkdir(parents=True)

    newer_state = {
        "run_id": "20260309T120000Z-aaaabbbb",
        "workspace": str(workspace.resolve()),
        "created_at": "2026-03-09T12:00:00+00:00",
        "updated_at": "2026-03-09T12:03:00+00:00",
        "phase": "monitoring",
        "phase_detail": "watching:claude",
        "mode": "tmux",
        "session": "ai-collab-live",
        "controller": {"agent": "codex"},
        "agents": {"claude": {"status": "running"}},
        "tmux": {"layout_snapshot": {"available": True}},
    }
    older_state = {
        "run_id": "20260308T110000Z-ccccdddd",
        "workspace": str(workspace.resolve()),
        "created_at": "2026-03-08T11:00:00+00:00",
        "updated_at": "2026-03-08T11:01:00+00:00",
        "phase": "controller_started",
        "mode": "tmux",
        "session": "old-session",
        "controller": {"agent": "gemini"},
        "agents": {},
    }

    (newer / "state.json").write_text(json.dumps(newer_state), encoding="utf-8")
    (older / "state.json").write_text(json.dumps(older_state), encoding="utf-8")
    (newer / "events.jsonl").write_text(
        json.dumps(
            {
                "type": "run_started",
                "payload": {"task": "测试 codex 主控 session 面板渲染是否正常"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    records = load_workspace_session_records(workspace, limit=2)

    assert len(records) == 2
    assert records[0].run_id == "20260309T120000Z-aaaabbbb"
    assert records[0].controller == "codex"
    assert records[0].helper_count == 1
    assert "测试 codex 主控" in records[0].task_preview
    assert records[1].run_id == "20260308T110000Z-ccccdddd"


def test_build_workspace_session_lines_show_resume_candidates_and_empty_state(tmp_path) -> None:
    from ai_collab.core.run_state import RunStateStore

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = RunStateStore.create(
        cwd=workspace,
        session="ai-collab-live",
        controller_agent="codex",
        controller_pane="%1",
    )
    store.set_label(label="nightly-a")
    store.set_entry_prompt(text="测试第一页右侧的 ai-collab session timeline")
    store.bind_agent(agent="gemini", pane_id="%2", step_tickets=[{"step_id": "S1", "nonce": "n1"}])

    lines = build_workspace_session_lines(selected=workspace, width=84, lang="zh-CN")
    joined = "\n".join(lines)

    assert lines[0].startswith("工作区")
    assert "恢复候选" in joined
    assert store.run_id.split("-")[-1] in joined
    assert "nightly-a" in joined
    assert "running" in joined
    assert "ai-collab session timeline" in joined

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    empty_lines = build_workspace_session_lines(selected=empty_dir, width=84, lang="zh-CN", records=[])
    assert "暂无可恢复运行" in "\n".join(empty_lines)


def test_derive_workspace_tree_root_prefers_common_parent() -> None:
    root = derive_workspace_tree_root(
        candidates=[
            Path("/Users/skyhua/ai-collab"),
            Path("/Users/skyhua/Desktop"),
            Path("/Users/skyhua/Documents"),
        ],
        workspace=Path("/Users/skyhua/ai-collab"),
        cwd=Path("/Users/skyhua/ai-collab"),
    )

    assert root == Path("/Users/skyhua")


def test_record_workspace_history_keeps_latest_unique_paths(tmp_path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    third = tmp_path / "three"
    for path in (first, second, third):
        path.mkdir()

    history_path = tmp_path / "workspace-history.json"
    record_workspace_history(first, history_path=history_path, limit=3)
    record_workspace_history(second, history_path=history_path, limit=3)
    record_workspace_history(first, history_path=history_path, limit=3)
    record_workspace_history(third, history_path=history_path, limit=3)

    assert load_workspace_history(history_path=history_path) == [third, first, second]


def test_discover_recent_workspaces_uses_bundle_history_as_fallback(tmp_path) -> None:
    bundle_dir = tmp_path / ".ai-collab" / "ux-lab-v3"
    bundle_dir.mkdir(parents=True)
    history_path = tmp_path / "workspace-history.json"
    older = tmp_path / "older"
    latest = tmp_path / "latest"
    older.mkdir()
    latest.mkdir()
    (bundle_dir / "bundle-1.json").write_text(f'{{"workspace": "{older}"}}', encoding="utf-8")
    (bundle_dir / "bundle-2.json").write_text(f'{{"workspace": "{latest}"}}', encoding="utf-8")

    recent = discover_recent_workspaces(
        workspace=latest,
        cwd=latest,
        candidates=[latest, older],
        history_path=history_path,
        bundle_dir=bundle_dir,
        limit=4,
    )

    assert recent[:2] == [latest, older]


def test_interpret_workspace_submission_supports_new_command() -> None:
    decision = interpret_workspace_submission(
        raw="/new /tmp/ai-collab-v3-lab",
        cwd=Path("/Users/skyhua/ai-collab"),
        selected=Path("/Users/skyhua/ProjectPrinting"),
    )

    assert decision.kind == "create"
    assert decision.path == Path("/tmp/ai-collab-v3-lab")


def test_interpret_workspace_submission_uses_highlighted_folder_for_filter_text() -> None:
    decision = interpret_workspace_submission(
        raw="proj",
        cwd=Path("/Users/skyhua/ai-collab"),
        selected=Path("/Users/skyhua/ProjectPrinting"),
    )

    assert decision.kind == "use"
    assert decision.path == Path("/Users/skyhua/ProjectPrinting")


def test_parse_review_command_understands_core_actions() -> None:
    eta_command = parse_review_command("/eta 18")
    send_command = parse_review_command("/send")

    assert eta_command.action == "eta"
    assert eta_command.value == "18"
    assert send_command.action == "send"


def test_build_controller_cards_marks_only_one_selected_agent() -> None:
    cards = build_controller_cards(selected="codex", lang="zh-CN")

    assert len(cards) == 3
    assert sum(1 for card in cards if card.selected) == 1
    assert cards[0].selected is True
    assert "OpenAI" in cards[0].summary
    assert "Anthropic" in cards[1].summary
    assert "Google" in cards[2].summary
    assert "Gemini CLI" in cards[2].detail


def test_build_command_bar_state_returns_screen_specific_hint_and_clears_value() -> None:
    state = build_command_bar_state(screen="controller", lang="zh-CN")

    assert state.value == ""
    assert "codex" in state.placeholder
    assert "左右键" in state.help_text


def test_build_command_bar_state_workspace_treats_current_as_quick_action_not_mode() -> None:
    state = build_command_bar_state(screen="workspace", lang="zh-CN")

    assert "当前目录 / 最近使用 / 目录树" not in state.help_text
    assert "切换来源" in state.help_text
    assert "Space" in state.help_text
    assert state.placeholder.startswith(":")


def test_build_step_track_marks_current_stage_and_fits_width() -> None:
    lines = build_step_track(screen="review", lang="zh-CN", width=72)

    assert lines
    assert any("05 检查" in line for line in lines)
    assert any("【05 检查】" in line for line in lines)
    assert all(len(line) <= 72 for line in lines)


def test_build_review_list_lines_fit_narrow_width() -> None:
    lines = build_review_list_lines(
        items=[
            map_controller_plan_to_items(
                {
                    "plan_version": "1",
                    "controller": "codex",
                    "requires_multi_agent": True,
                    "agents": [
                        {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "lead"},
                    ],
                    "steps": [
                        {
                            "id": "S1",
                            "owner": "codex",
                            "goal": "这个标题特别长特别长特别长特别长特别长特别长",
                            "input": "用户任务",
                            "output": "计划 JSON",
                            "done_when": "形成 JSON 计划",
                            "eta_minutes": 21,
                        }
                    ],
                    "approval_question": "是否执行？",
                },
                lang="zh-CN",
            )[0]
        ],
        selected_index=0,
        width=44,
    )

    assert lines
    assert all(len(line) <= 44 for line in lines)


def test_build_planner_prompt_mentions_json_and_workspace() -> None:
    prompt = build_planner_prompt(
        task="测试 codex 主控 JSON 规划",
        controller="codex",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="zh-CN",
    )

    assert "JSON" in prompt
    assert "中文" in prompt
    assert "/Users/skyhua/ai-collab" in prompt
    assert "不要运行任何命令" in prompt
    assert "不要读取或搜索工作区文件" in prompt
    assert '"plan_version": "1.0"' in prompt
    assert '"approval_question": "是否执行？"' in prompt


def test_build_planner_prompt_explicitly_guides_role_split() -> None:
    config = Config.create_default()

    prompt = build_planner_prompt(
        task="制作一个贪吃蛇小游戏",
        controller="codex",
        workspace=Path("/Users/skyhua/test_game"),
        lang="zh-CN",
        config=config,
    )

    assert "优先职责边界" in prompt
    assert "方案选项 / 技术骨架 / 架构取舍：Gemini" in prompt
    assert "主实现 / 跨文件编码 / 问题修复：Codex" in prompt
    assert "验收 / 回归测试 / 质量审查 / 补充修改：Claude" in prompt
    assert "不要因为当前 controller 是 codex 就默认把主实现分给 codex" in prompt


def test_build_planner_prompt_includes_v2_workflow_metadata() -> None:
    config = Config.create_default()

    prompt = build_planner_prompt(
        task="制作一个贪吃蛇小游戏",
        controller="codex",
        workspace=Path("/Users/skyhua/test_game"),
        lang="zh-CN",
        config=config,
    )

    assert '"workflow_engine": "v2"' in prompt
    assert '"session_preset": "auto"' in prompt
    assert '"workflow_blueprint": "delivery-loop"' in prompt
    assert '"responsibility_stage": "collect"' in prompt
    assert '"artifact_type": "evidence-pack"' in prompt
    assert '"boundary": "只收集现状，不直接改代码或重设方案"' in prompt
    assert '"timebox_minutes": 15' in prompt


def test_map_controller_plan_to_items_uses_eta_minutes_when_provided() -> None:
    items = map_controller_plan_to_items(
        {
            "plan_version": "1",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [
                {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "lead"},
            ],
            "steps": [
                {
                    "id": "S1",
                    "owner": "codex",
                    "goal": "先做规划",
                    "input": "用户任务",
                    "output": "计划 JSON",
                    "done_when": "形成 JSON 计划",
                    "eta_minutes": 21,
                }
            ],
            "approval_question": "是否执行？",
        },
        lang="zh-CN",
    )

    assert items[0].sx == "S1"
    assert items[0].eta_minutes == 21
    assert items[0].agent == "codex"


def test_request_live_plan_uses_injected_planner_and_does_not_fallback() -> None:
    config = Config.create_default()
    captured = {"prompt": ""}

    def _fake_request(*, config, controller, prompt_text):  # noqa: ANN001, ARG001
        captured["prompt"] = prompt_text
        return (
            {
                "plan_version": "1",
                "controller": controller,
                "requires_multi_agent": True,
                "agents": [
                    {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "lead"},
                ],
                "steps": [
                    {
                        "id": "S1",
                        "owner": "codex",
                        "goal": "Plan",
                        "input": "Task",
                        "output": "Plan",
                        "done_when": "JSON plan returned",
                    }
                ],
                "approval_question": "Send?",
            },
            None,
        )

    items, error = request_live_plan(
        config=config,
        controller="codex",
        task="Test live planning",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="en-US",
        request_plan=_fake_request,
    )

    assert error is None
    assert items is not None
    assert items[0].sx == "S1"
    assert "Test live planning" in captured["prompt"]


def test_request_live_plan_returns_error_without_mock_fallback() -> None:
    config = Config.create_default()

    def _fake_request(*, config, controller, prompt_text):  # noqa: ANN001, ARG001
        return None, "controller failed"

    items, error = request_live_plan(
        config=config,
        controller="codex",
        task="Test live planning",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="en-US",
        request_plan=_fake_request,
    )

    assert items is None
    assert error == "controller failed"


def test_export_launch_bundle_v3_keeps_controller_plan_payload(tmp_path) -> None:
    bundle = export_launch_bundle_v3(
        workspace=tmp_path,
        controller="codex",
        task="测试真实规划导出",
        lang="zh-CN",
        planner_mode="live",
        plan=[],
        output_path=tmp_path / "bundle.json",
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "implementation-engineer", "why": "主控"}],
            "steps": [],
            "approval_question": "是否执行？",
        },
    )

    payload = json.loads(bundle.read_text(encoding="utf-8"))

    assert payload["planner_mode"] == "live"
    assert payload["controller_plan"]["controller"] == "codex"
    assert payload["controller_plan"]["approval_question"] == "是否执行？"


def test_build_planner_prompt_embeds_exact_task_text() -> None:
    prompt = build_planner_prompt(
        task="测试",
        controller="codex",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="zh-CN",
    )

    assert "用户任务:\n测试" in prompt
    assert "最终输出必须直接是 JSON 对象本身" in prompt
    assert '"steps": [' in prompt
    assert '"done_when": "完成现状收集，明确关键约束，并给出可执行方案方向或是否需要进入 artifact 阶段"' in prompt


def test_request_live_plan_details_reports_progress() -> None:
    from ai_collab.tui.launcher_service import request_live_plan_details

    config = Config.create_default()
    events: list[str] = []

    def _fake_request(*, config, controller, prompt_text):  # noqa: ANN001, ARG001
        return (
            {
                "plan_version": "1",
                "controller": controller,
                "requires_multi_agent": True,
                "agents": [
                    {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责拆解与汇总"},
                    {"name": "claude", "model": "claude-sonnet-4-6", "persona": "collaborator", "why": "负责验证输出"},
                ],
                "steps": [
                    {
                        "id": "S1",
                        "owner": "codex",
                        "goal": "明确测试目标与验收项",
                        "input": "测试",
                        "output": "测试清单",
                        "done_when": "至少列出 2 个要验证的检查点，并说明各自如何判断通过",
                    },
                    {
                        "id": "S2",
                        "owner": "claude",
                        "goal": "执行测试并记录结果",
                        "input": "测试清单",
                        "output": "测试结果",
                        "done_when": "每个检查点都有明确的通过/失败结论",
                    },
                ],
                "approval_question": "已生成针对“测试”的验证计划，是否开始执行？",
            },
            None,
        )

    items, controller_plan, error = request_live_plan_details(
        config=config,
        controller="codex",
        task="测试",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="zh-CN",
        request_plan=_fake_request,
        progress_callback=lambda stage, payload: events.append(stage),
    )

    assert error is None
    assert items is not None
    assert controller_plan is not None
    assert events == ["prompt_ready", "json_received", "steps_mapped"]


def test_request_live_plan_details_forwards_cancel_callback(monkeypatch) -> None:
    from ai_collab.tui.launcher_service import request_live_plan_details
    from ai_collab import cli as cli_module

    config = Config.create_default()
    captured: dict[str, object] = {}

    def _fake_request_controller_plan(**kwargs):  # noqa: ANN003
        captured["cancel_requested"] = kwargs.get("cancel_requested")
        return (
            {
                "plan_version": "1",
                "controller": "codex",
                "requires_multi_agent": False,
                "agents": [],
                "steps": [
                    {
                        "id": "S1",
                        "owner": "codex",
                        "goal": "整理验证目标",
                        "input": "测试",
                        "output": "验证清单",
                        "done_when": "输出至少 2 个清晰检查点",
                    }
                ],
                "approval_question": "已生成针对“测试”的单主控计划，是否开始执行？",
            },
            None,
        )

    monkeypatch.setattr(cli_module, "_request_controller_plan", _fake_request_controller_plan)

    sentinel = object()
    _items, _controller_plan, error = request_live_plan_details(
        config=config,
        controller="codex",
        task="测试",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="zh-CN",
        cancel_requested=lambda: sentinel is sentinel,
    )

    assert error is None
    assert callable(captured["cancel_requested"])


def test_request_live_plan_details_retries_placeholder_plan_once() -> None:
    from ai_collab.tui.launcher_service import request_live_plan_details

    config = Config.create_default()
    calls: list[str] = []

    def _fake_request(**kwargs):  # noqa: ANN003
        calls.append(str(kwargs.get("prompt_text", "")))
        if len(calls) == 1:
            return (
                {
                    "plan_version": "1.0",
                    "controller": "codex",
                    "requires_multi_agent": True,
                    "agents": [
                        {"name": "codex", "model": "unknown", "persona": "controller", "why": "负责总体规划"},
                        {"name": "claude", "model": "unknown", "persona": "collaborator", "why": "负责辅助分析"},
                    ],
                    "steps": [
                        {
                            "id": "S1",
                            "owner": "codex",
                            "goal": "S1",
                            "input": "Task",
                            "output": "",
                            "done_when": "完成 S1 并给出可检查结果。",
                            "eta_minutes": 10,
                        }
                    ],
                    "approval_question": "是否执行？",
                },
                None,
            )
        return (
            {
                "plan_version": "1.0",
                "controller": "codex",
                "requires_multi_agent": True,
                "agents": [
                    {"name": "codex", "model": "unknown", "persona": "controller", "why": "负责拆分测试范围与汇总结果"},
                    {"name": "claude", "model": "unknown", "persona": "collaborator", "why": "负责执行功能验证"},
                ],
                "steps": [
                    {
                        "id": "S1",
                        "owner": "codex",
                        "goal": "明确 ai-collab 测试目标与检查点",
                        "input": "测试",
                        "output": "测试清单",
                        "done_when": "输出至少 3 个明确检查点，并说明每项如何验证",
                        "eta_minutes": 4,
                    },
                    {
                        "id": "S2",
                        "owner": "claude",
                        "goal": "执行启动与规划链路验证",
                        "input": "测试清单",
                        "output": "验证结果",
                        "done_when": "明确记录启动、规划、预览三项结果，且每项都有通过/失败结论",
                        "eta_minutes": 8,
                    },
                ],
                "approval_question": "已生成针对“测试”任务的验证计划，是否开始执行？",
            },
            None,
        )

    items, controller_plan, error = request_live_plan_details(
        config=config,
        controller="codex",
        task="测试",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="zh-CN",
        request_plan=_fake_request,
    )

    assert error is None
    assert items is not None
    assert controller_plan is not None
    assert len(calls) == 2
    assert "占位" in calls[1] or "placeholder" in calls[1].lower() or "不要返回" in calls[1]
    assert items[0].title == "明确 ai-collab 测试目标与检查点"


def test_request_live_plan_details_rejects_placeholder_plan_after_retry() -> None:
    from ai_collab.tui.launcher_service import request_live_plan_details

    config = Config.create_default()
    calls = 0

    def _fake_request(**_kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        return (
            {
                "plan_version": "1.0",
                "controller": "codex",
                "requires_multi_agent": True,
                "agents": [
                    {"name": "codex", "model": "unknown", "persona": "controller", "why": "负责总体规划"},
                    {"name": "claude", "model": "unknown", "persona": "collaborator", "why": "负责辅助分析"},
                ],
                "steps": [
                    {
                        "id": "S1",
                        "owner": "codex",
                        "goal": "S1",
                        "input": "Task",
                        "output": "",
                        "done_when": "完成 S1 并给出可检查结果。",
                        "eta_minutes": 10,
                    }
                ],
                "approval_question": "是否执行？",
            },
            None,
        )

    items, controller_plan, error = request_live_plan_details(
        config=config,
        controller="codex",
        task="测试",
        workspace=Path("/Users/skyhua/ai-collab"),
        lang="zh-CN",
        request_plan=_fake_request,
    )

    assert items is None
    assert controller_plan is not None
    assert error is not None
    assert calls == 2
    assert "占位" in error or "generic" in error.lower() or "low-quality" in error.lower()


def test_launch_ux_lab_v3_routes_interactive_mode_to_textual_runner(monkeypatch) -> None:
    import ai_collab.ux_lab_v3 as ux_lab_v3

    captured = {"called": False}

    def _fake_run_textual(**kwargs):  # noqa: ANN003
        captured["called"] = True
        return UxLabV3Result(
            status="cancelled",
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test",
            lang="en-US",
            planner_mode="live",
            plan=[],
        )

    import ai_collab.ux_lab_v3_textual as textual_module

    monkeypatch.setattr(textual_module, "run_textual_ux_lab_v3", _fake_run_textual)

    result = ux_lab_v3.launch_ux_lab_v3(
        config=Config.create_default(),
        cwd=Path("/Users/skyhua/ai-collab"),
        non_interactive=False,
    )

    assert captured["called"] is True
    assert result.status == "cancelled"


def test_textual_workspace_screen_exposes_current_button_and_browse_modes(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module
    from textual.widgets import Button

    history_dir = tmp_path / "recent-workspace"
    history_dir.mkdir()
    history_path = tmp_path / "workspace-history.json"
    record_workspace_history(history_dir, history_path=history_path, limit=5)

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace modes",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
            history_path=history_path,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.workspace_mode == "current"
            assert len(app.query("#workspace-use-current")) == 0
            assert app.query_one("#workspace-tabs")
            assert app.query_one("#workspace-continue", Button)
            assert app.query_one("#workspace-tree", DirectoryTree)
            assert app.query_one("#workspace-preview")
            assert len(app.query("#workspace-confirm")) == 0

    asyncio.run(_run())


def test_textual_workspace_current_mode_requires_confirm_before_advancing(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    cwd = tmp_path / "workspace"
    cwd.mkdir()
    history_path = tmp_path / "workspace-history.json"

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=cwd,
            workspace=cwd,
            controller="codex",
            task="Test workspace current mode confirm",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
            history_path=history_path,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.workspace_mode == "current"
            assert app.screen_name == "workspace"

            app.query_one("#workspace-tabs").focus()
            await pilot.pause()
            assert app.screen_name == "workspace"

            await pilot.press("space")
            await pilot.pause()
            assert app.workspace == cwd.resolve()
            assert app.screen_name == "controller"

    asyncio.run(_run())


def test_textual_workspace_current_panel_click_does_not_auto_advance_but_continue_button_does(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    cwd = tmp_path / "workspace"
    cwd.mkdir()
    history_path = tmp_path / "workspace-history.json"

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=cwd,
            workspace=cwd,
            controller="codex",
            task="Test workspace current mode mouse flow",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
            history_path=history_path,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.screen_name == "workspace"

            await pilot.click("#workspace-current-overview")
            await pilot.pause()
            assert app.screen_name == "workspace"

            await pilot.click("#workspace-continue")
            await pilot.pause()
            assert app.workspace == cwd.resolve()
            assert app.screen_name == "controller"

    asyncio.run(_run())


def test_textual_workspace_screen_space_selects_highlighted_recent_folder(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    history_dir = tmp_path / "recent-workspace"
    history_dir.mkdir()
    history_path = tmp_path / "workspace-history.json"
    record_workspace_history(history_dir, history_path=history_path, limit=5)

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace space select",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
            history_path=history_path,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.workspace_mode == "current"
            app._set_workspace_mode("recent")
            app.recent_workspaces = [history_dir.resolve()]
            app.filtered_recent_workspaces = [history_dir.resolve()]
            app.recent_index = 0
            app._refresh_recent_list()
            app._set_workspace_mode("recent")
            app._refresh_workspace_panel()
            await pilot.press("space")
            await pilot.pause()
            assert app.workspace == history_dir.resolve()
            assert app.screen_name == "controller"

    asyncio.run(_run())


def test_textual_workspace_recent_list_moves_one_step_per_down_press(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module
    from textual.widgets import OptionList

    first = tmp_path / "one"
    second = tmp_path / "two"
    third = tmp_path / "three"
    for path in (first, second, third):
        path.mkdir()

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace recent movement",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.recent_workspaces = [first.resolve(), second.resolve(), third.resolve()]
            app.filtered_recent_workspaces = list(app.recent_workspaces)
            app.recent_index = 0
            app._refresh_recent_list()
            app._set_workspace_mode("recent")
            app._refresh_workspace_panel()

            recent = app.query_one("#workspace-recent-list", OptionList)
            assert recent.highlighted == 0

            await pilot.press("down")
            await pilot.pause()
            recent = app.query_one("#workspace-recent-list", OptionList)
            assert app.recent_index == 1
            assert recent.highlighted == 1

            await pilot.press("down")
            await pilot.pause()
            recent = app.query_one("#workspace-recent-list", OptionList)
            assert app.recent_index == 2
            assert recent.highlighted == 2

    asyncio.run(_run())


def test_textual_workspace_screen_populates_recent_list_on_mount() -> None:
    import ai_collab.ux_lab_v3_textual as textual_module
    from textual.widgets import OptionList

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace recent list mount",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.pause()
            recent = app.query_one("#workspace-recent-list", OptionList)

            assert app.filtered_recent_workspaces
            assert len(recent._options) == len(app.filtered_recent_workspaces)
            assert recent.display is True

    asyncio.run(_run())


def test_textual_workspace_screen_uses_split_layout_and_ascii_brand_on_medium_terminal() -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace medium layout",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            brand = app.query_one("#brand")
            picker = app.query_one("#workspace-picker")
            browser = app.query_one("#workspace-browser")
            preview = app.query_one("#workspace-preview")

            assert brand.region.height >= 4
            assert not picker.has_class("stack")
            assert browser.region.x < preview.region.x

    asyncio.run(_run())


def test_textual_workspace_screen_uses_single_right_inspector_panel() -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace detail panel",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            browser = app.query_one("#workspace-browser")
            inspector = app.query_one("#workspace-inspector")
            preview = app.query_one("#workspace-preview")

            assert browser.region.x < inspector.region.x
            assert len(app.query("#workspace-detail")) == 0
            assert preview.region.x == inspector.region.x
            assert preview.region.height >= 10

    asyncio.run(_run())


def test_textual_workspace_screen_compacts_toolbar_and_keeps_command_bar_visible() -> None:
    import ai_collab.ux_lab_v3_textual as textual_module
    from textual.widgets import Button

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace toolbar layout",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.pause()
            tabs = app.query_one("#workspace-tabs")
            current_path = app.query_one("#workspace-current-path")
            continue_button = app.query_one("#workspace-continue", Button)
            picker = app.query_one("#workspace-picker")
            command_bar = app.query_one("#command-bar", Input)

            assert tabs.region.y == current_path.region.y
            assert current_path.region.y == continue_button.region.y
            assert current_path.region.width >= 18
            assert picker.region.height >= 12
            assert command_bar.display is True

    asyncio.run(_run())


def test_textual_workspace_screen_supports_left_right_tabs_and_colon_command_entry(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    history_dir = tmp_path / "recent-workspace"
    history_dir.mkdir()
    history_path = tmp_path / "workspace-history.json"
    record_workspace_history(history_dir, history_path=history_path, limit=5)

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace key flow",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
            history_path=history_path,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.workspace_mode == "current"
            await pilot.press("right")
            assert app.workspace_mode == "recent"
            await pilot.press("right")
            assert app.workspace_mode == "tree"
            await pilot.press("left")
            assert app.workspace_mode == "recent"
            await pilot.press("left")
            assert app.workspace_mode == "current"
            await pilot.press(":")
            await pilot.pause()
            assert getattr(app.focused, "id", None) == "command-bar"

    asyncio.run(_run())


def test_textual_workspace_screen_uses_panel_titles_and_browser_focus_state(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module

    history_dir = tmp_path / "recent-workspace"
    history_dir.mkdir()

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace panel titles",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            browser = app.query_one("#workspace-browser")
            preview = app.query_one("#workspace-preview")

            assert app.workspace_mode == "current"
            assert str(browser.border_title) == "当前目录"
            assert str(preview.border_title) == "检查器"
            assert not browser.has_class("focused")

            app.recent_workspaces = [history_dir.resolve()]
            app.filtered_recent_workspaces = [history_dir.resolve()]
            app.recent_index = 0
            app._refresh_recent_list()
            app._set_workspace_mode("recent")
            await pilot.pause()
            assert str(browser.border_title) == "最近使用目录 (1)"
            assert browser.has_class("focused")

            app._set_workspace_mode("tree")
            await pilot.pause()
            assert str(browser.border_title) == "目录树"
            assert browser.has_class("focused")

    asyncio.run(_run())


def test_textual_workspace_session_panel_shows_recent_ai_collab_runs(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module
    from textual.widgets import Static

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_dir = workspace / ".ai-collab" / "runs" / "20260309T120000Z-aaaabbbb"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "20260309T120000Z-aaaabbbb",
                "workspace": str(workspace.resolve()),
                "created_at": "2026-03-09T12:00:00+00:00",
                "updated_at": "2026-03-09T12:03:00+00:00",
                "phase": "monitoring",
                "phase_detail": "watching:gemini",
                "mode": "tmux",
                "session": "ai-collab-live",
                "controller": {"agent": "codex"},
                "agents": {"gemini": {"status": "running"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "type": "run_started",
                "payload": {"task": "测试第一页右侧 session 面板"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=workspace,
            workspace=workspace,
            controller="codex",
            task="Test workspace session inspector",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.recent_workspaces = [workspace.resolve()]
            app.filtered_recent_workspaces = [workspace.resolve()]
            app.recent_index = 0
            app._refresh_recent_list()
            app._refresh_workspace_panel()
            await pilot.pause()

            preview = app.query_one("#workspace-preview", Static)
            rendered = str(preview.render())

            assert str(preview.border_title) == "检查器"
            assert "恢复候选" in rendered
            assert "aaaabbbb" in rendered
            assert "running" in rendered
            assert "测试第一页右侧" in rendered

    asyncio.run(_run())


def test_textual_workspace_recent_empty_state_is_visible(tmp_path) -> None:
    import ai_collab.ux_lab_v3_textual as textual_module
    from textual.widgets import OptionList, Static

    async def _run() -> None:
        app = textual_module.UxLabV3TextualApp(
            config=Config.create_default(),
            cwd=Path("/Users/skyhua/ai-collab"),
            workspace=Path("/Users/skyhua/ai-collab"),
            controller="codex",
            task="Test workspace empty state",
            lang="zh-CN",
            skip_review=False,
            planner_mode="mock",
            output_bundle=None,
        )
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app._set_workspace_mode("recent")
            app.recent_workspaces = []
            app.filtered_recent_workspaces = []
            app.recent_index = 0
            app._refresh_recent_list()
            app._refresh_workspace_panel()
            await pilot.pause()

            browser = app.query_one("#workspace-browser")
            recent_list = app.query_one("#workspace-recent-list", OptionList)
            empty_state = app.query_one("#workspace-recent-empty", Static)

            assert str(browser.border_title) == "最近使用目录 (0)"
            assert recent_list.display is False
            assert empty_state.display is True
            assert "暂无最近使用的目录" in str(empty_state.render())

    asyncio.run(_run())


def test_project_main_routes_ux_lab_v3_to_click_main(monkeypatch) -> None:
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "ux-lab-v3", "--help"])

    cli.project_main()

    assert captured["args"] == ["ux-lab-v3", "--help"]


def test_controller_plan_schema_allows_eta_minutes() -> None:
    schema = cli._controller_plan_schema()
    step_properties = schema["properties"]["steps"]["items"]["properties"]

    assert "eta_minutes" in step_properties
