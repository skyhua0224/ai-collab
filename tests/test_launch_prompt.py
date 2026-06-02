from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from rich.console import Console

from ai_collab.core.config import Config
from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result


def test_launch_command_uses_thin_prompt_flow_by_default(monkeypatch, tmp_path) -> None:
    import ai_collab.cli as cli

    config = Config.create_default()
    ctx = SimpleNamespace(obj={"config": config})
    captured: dict[str, object] = {"thin": False, "tui": False}

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launch_prompt",
        lambda **kwargs: captured.__setitem__("thin", kwargs) or None,
    )
    monkeypatch.setattr(
        "ai_collab.tui.launcher.run_launcher_tui",
        lambda **kwargs: captured.__setitem__("tui", True),
    )

    cli.launch.callback.__wrapped__(
        ctx,
        workspace=tmp_path,
        controller="codex",
        task="Build thin start flow",
        task_file=None,
        skip_review=False,
        planner_mode="mock",
        output_bundle=tmp_path / "bundle.json",
        non_interactive=False,
    )

    assert captured["tui"] is False
    assert captured["thin"]["config"] is config
    assert captured["thin"]["workspace"] == tmp_path
    assert captured["thin"]["controller"] == "codex"
    assert captured["thin"]["task"] == "Build thin start flow"


def test_render_launch_prompt_screen_uses_direct_task_editor() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, render_launch_prompt_screen

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/ai-collab"),
        from_entry=True,
    )

    output = render_launch_prompt_screen(state)

    assert "步骤 2/5 · 任务草稿" in output
    assert "工作区" in output
    assert "任务草稿" in output
    assert "主控" in output
    assert "规划" in output
    assert "确认" in output
    assert "/nano" in output
    assert "/vim" in output
    assert "/back" in output
    assert "/home" in output
    assert "/quit" in output
    assert "编辑任务内容" not in output
    assert "下一步" not in output
    assert "Textual" not in output



def test_run_launch_prompt_can_save_bundle_via_execution_targets(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["实现新的 thin launcher"])
    menu_choices = iter(["1", "2", "1", "1", "save"])

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launcher_flow",
        lambda **kwargs: UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="zh-CN",
            planner_mode=kwargs["planner_mode"],
            plan=[LabPlanItem("S1", "主控计划", "codex", 8, "返回计划")],
            bundle_path=None,
        ),
    )
    monkeypatch.setattr(
        "ai_collab.launch_prompt.export_launch_bundle_v3",
        lambda **kwargs: tmp_path / "bundle.json",
    )

    def _input(prompt: str, *, default: str = "") -> str:
        return next(answers)

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=tmp_path / "bundle.json",
        input_fn=_input,
        selector_fn=lambda **_: next(menu_choices),
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is not None
    assert result.status == "saved"
    assert result.bundle_path == tmp_path / "bundle.json"
    output = buffer.getvalue()
    assert "步骤 2/5 · 任务草稿" in output
    assert "主控计划" in output
    assert "启动包已保存" in output
    assert "启动包路径" in output


def test_run_launch_prompt_can_start_tmux_from_execution_targets(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["测试启动 tmux"])
    menu_choices = iter(["1", "2", "1", "1", "tmux"])

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launcher_flow",
        lambda **kwargs: UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="zh-CN",
            planner_mode=kwargs["planner_mode"],
            plan=[LabPlanItem("S1", "主控计划", "codex", 8, "返回计划")],
            controller_plan={
                "plan_version": "1.0",
                "controller": "codex",
                "requires_multi_agent": True,
                "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责执行"}],
                "steps": [{"id": "S1", "owner": "codex", "goal": "主控计划", "done_when": "返回计划", "eta_minutes": 8}],
            },
            bundle_path=None,
        ),
    )
    monkeypatch.setattr("ai_collab.cli._result_for_tmux_launch", lambda result, _plan: result)
    monkeypatch.setattr("ai_collab.cli._can_launch_tmux", lambda _result: True)
    monkeypatch.setattr("ai_collab.cli._build_controller_execution_prompt", lambda **_kwargs: "run task")
    monkeypatch.setattr("ai_collab.cli._launch_tmux_orchestration", lambda **_kwargs: True)

    def _input(prompt: str, *, default: str = "") -> str:
        return next(answers)

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=None,
        input_fn=_input,
        selector_fn=lambda **_: next(menu_choices),
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is not None
    assert result.status == "started"
    output = buffer.getvalue()
    assert "任务已启动" in output
    assert "tmux runtime" in output


def test_run_launch_prompt_can_start_direct_from_execution_targets(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    config.runtime_mode = "direct"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["测试启动 direct"])
    menu_choices = iter(["1", "2", "1", "1", "direct", "q"])

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launcher_flow",
        lambda **kwargs: UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="zh-CN",
            planner_mode=kwargs["planner_mode"],
            plan=[LabPlanItem("S1", "主控直接执行", "codex", 8, "返回可检查结果")],
            controller_plan={
                "plan_version": "1.0",
                "controller": "codex",
                "requires_multi_agent": False,
                "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责执行"}],
                "steps": [{"id": "S1", "owner": "codex", "goal": "主控直接执行", "done_when": "返回可检查结果", "eta_minutes": 8}],
            },
            bundle_path=None,
        ),
    )
    monkeypatch.setattr("ai_collab.cli._execute_direct_runtime", lambda **_k: 0)

    def _input(prompt: str, *, default: str = "") -> str:
        return next(answers)

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=None,
        input_fn=_input,
        selector_fn=lambda **_: next(menu_choices),
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is not None
    assert result.status == "started"
    output = buffer.getvalue()
    assert "任务已启动" in output
    assert "直接执行" in output


def test_run_launch_prompt_can_start_multi_agent_direct_from_execution_targets(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    config.runtime_mode = "direct"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["测试启动 multi-agent direct"])
    menu_choices = iter(["1", "2", "1", "1", "direct", "q"])

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launcher_flow",
        lambda **kwargs: UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="zh-CN",
            planner_mode=kwargs["planner_mode"],
            plan=[
                LabPlanItem("S1", "主控规划", "codex", 5, "返回规划"),
                LabPlanItem("S2", "协作验证", "claude", 7, "返回验证结果"),
            ],
            controller_plan={
                "plan_version": "1.0",
                "controller": "codex",
                "workflow_engine": "v2",
                "session_preset": "design-first",
                "workflow_blueprint": "design-led-loop",
                "requires_multi_agent": True,
                "agents": [
                    {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责规划"},
                    {"name": "claude", "model": "claude-sonnet-4-6", "persona": "collaborator", "why": "负责验证"},
                ],
                "steps": [
                    {"id": "S1", "owner": "codex", "goal": "主控规划", "done_when": "返回规划", "eta_minutes": 5},
                    {"id": "S2", "owner": "claude", "goal": "协作验证", "done_when": "返回验证结果", "eta_minutes": 7},
                ],
            },
            bundle_path=None,
        ),
    )
    monkeypatch.setattr("ai_collab.cli._execute_direct_runtime", lambda **_k: 0)

    def _input(prompt: str, *, default: str = "") -> str:
        return next(answers)

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=None,
        input_fn=_input,
        selector_fn=lambda **_: next(menu_choices),
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is not None
    assert result.status == "started"
    output = buffer.getvalue()
    assert "任务已启动" in output
    assert "直接执行" in output


def test_run_launch_prompt_shows_direct_failure_reason(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    config.runtime_mode = "direct"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["测试 direct 失败原因"])
    menu_choices = iter(["1", "2", "1", "1", "direct", "q"])

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launcher_flow",
        lambda **kwargs: UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="zh-CN",
            planner_mode=kwargs["planner_mode"],
            plan=[LabPlanItem("S1", "主控直接执行", "codex", 8, "返回可检查结果")],
            controller_plan={
                "plan_version": "1.0",
                "controller": "codex",
                "requires_multi_agent": False,
                "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责执行"}],
                "steps": [{"id": "S1", "owner": "codex", "goal": "主控直接执行", "done_when": "返回可检查结果", "eta_minutes": 8}],
            },
            bundle_path=None,
        ),
    )

    def _fake_execute(**_kwargs):
        import ai_collab.cli as cli

        cli._set_last_direct_runtime_error("fatal: not a trusted repository")
        return 1

    monkeypatch.setattr("ai_collab.cli._execute_direct_runtime", _fake_execute)

    def _input(prompt: str, *, default: str = "") -> str:
        return next(answers)

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=None,
        input_fn=_input,
        selector_fn=lambda **_: next(menu_choices),
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is None
    assert "直接执行退出码: 1 · fatal: not a trusted repository" in buffer.getvalue()


def test_run_launch_prompt_keeps_review_preview_after_plan_edit(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    planning_calls = {"count": 0}
    review_calls = {"count": 0}
    confirm_calls = {"count": 0}
    plan_editor_actions = iter(["delete", "back"])

    planned_result = UxLabV3Result(
        status="planned",
        workspace=tmp_path,
        controller="codex",
        task="测试编排预览返回",
        lang="zh-CN",
        planner_mode="mock",
        plan=[
            LabPlanItem("S1", "主控计划", "codex", 8, "返回计划"),
            LabPlanItem("S2", "补充回归测试", "claude", 6, "验证返回行为"),
        ],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [
                {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责执行"},
                {"name": "claude", "model": "claude-sonnet-4-6", "persona": "collaborator", "why": "负责验证"},
            ],
            "steps": [
                {"id": "S1", "owner": "codex", "goal": "主控计划", "done_when": "返回计划", "eta_minutes": 8},
                {"id": "S2", "owner": "claude", "goal": "补充回归测试", "done_when": "验证返回行为", "eta_minutes": 6},
            ],
        },
    )

    def _run_planning(**_kwargs):
        planning_calls["count"] += 1
        return planned_result

    def _selector(**kwargs) -> str:
        screen = kwargs.get("screen")
        choices = list(kwargs.get("choices", []))
        if screen == "plan_editor":
            return next(plan_editor_actions)
        if choices == ["1", "2", "3", "b", "h", "q"]:
            review_calls["count"] += 1
            return "2" if review_calls["count"] == 1 else "3"
        if choices == ["1", "b", "h", "q"]:
            confirm_calls["count"] += 1
            if confirm_calls["count"] > 1:
                raise AssertionError("confirm-and-generate screen was shown again after editing the plan")
            return "1"
        if choices == ["1", "2", "b", "h", "q"]:
            return "2"
        if choices == ["1", "2", "3", "h", "q"]:
            return "1"
        raise AssertionError(f"unexpected selector call: screen={screen!r} choices={choices!r}")

    monkeypatch.setattr("ai_collab.launch_prompt._run_planning_with_progress", _run_planning)
    monkeypatch.setattr("ai_collab.launch_prompt.export_launch_bundle_v3", lambda **kwargs: tmp_path / "bundle.json")

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=tmp_path / "bundle.json",
        input_fn=lambda prompt, default="": "测试编排预览返回",
        selector_fn=_selector,
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is not None
    assert result.status == "saved"
    assert planning_calls["count"] == 1
    assert confirm_calls["count"] == 1
    assert review_calls["count"] == 2


def test_run_launch_prompt_keeps_execution_screen_after_tmux_failure(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["测试 tmux 失败后转保存"])
    menu_choices = iter(["1", "2", "1", "1", "tmux", "save"])

    monkeypatch.setattr(
        "ai_collab.launch_prompt.run_launcher_flow",
        lambda **kwargs: UxLabV3Result(
            status="planned",
            workspace=kwargs["workspace"] or kwargs["cwd"],
            controller=kwargs["controller"] or "codex",
            task=kwargs["task"] or "",
            lang="zh-CN",
            planner_mode=kwargs["planner_mode"],
            plan=[LabPlanItem("S1", "主控计划", "codex", 8, "返回计划")],
            controller_plan={
                "plan_version": "1.0",
                "controller": "codex",
                "requires_multi_agent": True,
                "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责执行"}],
                "steps": [{"id": "S1", "owner": "codex", "goal": "主控计划", "done_when": "返回计划", "eta_minutes": 8}],
            },
            bundle_path=None,
        ),
    )
    monkeypatch.setattr("ai_collab.launch_prompt.export_launch_bundle_v3", lambda **kwargs: tmp_path / "bundle.json")
    monkeypatch.setattr("ai_collab.cli._result_for_tmux_launch", lambda result, _plan: result)
    monkeypatch.setattr("ai_collab.cli._can_launch_tmux", lambda _result: True)
    monkeypatch.setattr("ai_collab.cli._build_controller_execution_prompt", lambda **_kwargs: "run task")

    def _launch_failure(**_kwargs) -> bool:
        import ai_collab.cli as cli

        cli.console.print("tmux failure detail")
        return False

    monkeypatch.setattr("ai_collab.cli._launch_tmux_orchestration", _launch_failure)

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=tmp_path / "bundle.json",
        input_fn=lambda prompt, default="": next(answers),
        selector_fn=lambda **_: next(menu_choices),
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert result is not None
    assert result.status == "saved"
    output = buffer.getvalue()
    assert "tmux failure detail" in output
    assert "启动失败" in output



def test_run_launch_prompt_accepts_home_command_from_task_input(tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"

    result = run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="live",
        output_bundle=None,
        input_fn=lambda *_args, **_kwargs: "/home",
        selector_fn=lambda **_: (_ for _ in ()).throw(AssertionError("selector should not run before leaving task input")),
        console_obj=Console(file=StringIO(), force_terminal=False, color_system=None, width=120),
        clear_screen=False,
        from_entry=True,
    )

    assert result == "home"



def test_run_launch_prompt_keeps_ansi_colors_in_terminal_output(monkeypatch, tmp_path) -> None:
    from ai_collab.launch_prompt import run_launch_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="truecolor", width=120, no_color=False)

    run_launch_prompt(
        config=config,
        cwd=tmp_path,
        workspace=tmp_path,
        controller=None,
        task=None,
        task_file=None,
        planner_mode="mock",
        output_bundle=None,
        input_fn=lambda prompt, default="": "/quit",
        selector_fn=lambda **_: "q",
        console_obj=console,
        clear_screen=False,
        from_entry=True,
    )

    assert "\x1b[" in buffer.getvalue()



def test_build_controller_rows_use_provider_colors_and_descriptions() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _build_controller_rows

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=Path("/Users/skyhua/ai-collab"), from_entry=True)
    state.controller = "codex"

    rows = {row.value: row for row in _build_controller_rows(state, pointed_value="2")}

    assert rows["1"].label_style == "#F8FAFC bold"
    assert rows["2"].prefix == "> "
    assert rows["2"].label_style == "#FB923C bold underline"
    assert rows["2"].description_style == "#64748B italic"
    assert "代码库理解" in rows["2"].description


def test_task_command_matching_filters_by_prefix_and_context() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _matching_task_commands

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=Path("/Users/skyhua/ai-collab"), from_entry=True)

    matches = _matching_task_commands(state, "/")

    assert [command for command, _description in matches][:3] == ["/nano", "/vim", "/done"]
    assert any(command == "/home" for command, _description in matches)


def test_task_command_matching_hides_home_outside_entry() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _matching_task_commands

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=Path("/Users/skyhua/ai-collab"), from_entry=False)

    matches = _matching_task_commands(state, "/h")

    assert matches == []


def test_planner_rows_use_controller_theme_for_selected_option() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _planner_rows

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=Path("/Users/skyhua/ai-collab"), from_entry=True)
    state.controller = "claude"

    rows = {row.value: row for row in _planner_rows(state, pointed_value="1")}

    assert rows["1"].label_style == "#FB923C bold underline"


def test_review_screen_renderable_shows_controller_plan_metadata() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/ai-collab"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="claude",
        task="测试真实规划",
        lang="zh-CN",
        planner_mode="live",
        plan=[LabPlanItem("S1", "完成技术选型", "claude", 9, "给出可执行选型结论")],
        controller_plan={
            "plan_version": "1.0",
            "controller": "claude",
            "requires_multi_agent": True,
            "agents": [
                {
                    "name": "claude",
                    "model": "claude-sonnet-4-6",
                    "persona": "requirements-architect",
                    "why": "负责仓库理解与方案收束",
                }
            ],
            "steps": [
                {
                    "id": "S1",
                    "owner": "claude",
                    "goal": "完成技术选型",
                    "input": "用户任务",
                    "output": "选型结论",
                    "done_when": "给出可执行选型结论",
                    "eta_minutes": 9,
                }
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    console.print(_review_screen_renderable(state, result))
    output = buffer.getvalue()

    assert "真实主控 JSON" in output
    assert "claude-sonnet-4-6" in output
    assert "是否执行该计划？" in output


def test_review_screen_renderable_falls_back_to_configured_model_labels_for_unknown() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/ai-collab"),
        from_entry=True,
    )
    state.controller = "codex"
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="测试真实规划",
        lang="zh-CN",
        planner_mode="live",
        plan=[
            LabPlanItem("S1", "完成技术选型", "codex", 9, "给出可执行选型结论"),
            LabPlanItem("S2", "验证结果", "claude", 6, "明确验证结论"),
        ],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [
                {"name": "codex", "model": "unknown", "persona": "controller", "why": "负责规划"},
                {"name": "claude", "model": "unknown", "persona": "collaborator", "why": "负责验证"},
            ],
            "steps": [
                {"id": "S1", "owner": "codex", "goal": "完成技术选型", "done_when": "给出可执行选型结论", "eta_minutes": 9},
                {"id": "S2", "owner": "claude", "goal": "验证结果", "done_when": "明确验证结论", "eta_minutes": 6},
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    console.print(_review_screen_renderable(state, result))
    output = buffer.getvalue()

    assert "gpt-5.5" in output
    assert "claude-sonnet-4-6" in output


def test_review_body_lines_can_scroll_to_later_steps() -> None:
    from ai_collab.launch_prompt import (
        LaunchPromptState,
        _review_body_lines,
        _slice_review_body_lines,
    )
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        plan=[
            LabPlanItem(f"S{index}", f"步骤 {index} 标题", "codex" if index % 2 else "claude", 5 + index, f"步骤 {index} 的验收条件需要足够长，以便在终端里产生换行并测试滚动预览。")
            for index in range(1, 9)
        ],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [
                {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责核心实现"},
                {"name": "claude", "model": "claude-sonnet-4-6", "persona": "collaborator", "why": "负责验收校验"},
            ],
            "steps": [
                {
                    "id": f"S{index}",
                    "owner": "codex" if index % 2 else "claude",
                    "goal": f"步骤 {index} 标题",
                    "input": "任务输入",
                    "output": "任务输出",
                    "done_when": f"步骤 {index} 的验收条件需要足够长，以便在终端里产生换行并测试滚动预览。",
                    "eta_minutes": 5 + index,
                }
                for index in range(1, 9)
            ],
            "approval_question": "是否按此多 Agent 计划开始制作贪吃蛇小游戏？",
        },
    )

    lines = _review_body_lines(state, result, width=80)
    visible_top, _, _ = _slice_review_body_lines(lines, scroll_offset=0, max_lines=8)
    visible_bottom, _, _ = _slice_review_body_lines(lines, scroll_offset=999, max_lines=8)

    top_text = "\n".join(visible_top)
    bottom_text = "\n".join(visible_bottom)
    assert "Agent 路由" in top_text
    assert "S8" not in top_text
    assert "S8" in bottom_text


def test_review_screen_renderable_can_render_scrolled_body_slice() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        plan=[
            LabPlanItem(f"S{index}", f"步骤 {index}", "codex", 10, f"完成步骤 {index}") for index in range(1, 7)
        ],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责实现"}],
            "steps": [
                {
                    "id": f"S{index}",
                    "owner": "codex",
                    "goal": f"步骤 {index}",
                    "input": "任务输入",
                    "output": "任务输出",
                    "done_when": f"完成步骤 {index}",
                    "eta_minutes": 10,
                }
                for index in range(1, 7)
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    console.print(
        _review_screen_renderable(
            state,
            result,
            scroll_offset=999,
            max_body_lines=8,
        )
    )
    output = buffer.getvalue()

    assert "S6" in output
    assert "S1" not in output


def test_review_screen_renderable_uses_compact_action_bar() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        plan=[LabPlanItem("S1", "实现基础结构", "codex", 10, "页面可打开")],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": False,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责实现"}],
            "steps": [
                {"id": "S1", "owner": "codex", "goal": "实现基础结构", "input": "任务输入", "output": "页面", "done_when": "页面可打开", "eta_minutes": 10}
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    console.print(_review_screen_renderable(state, result, scroll_offset=0, max_body_lines=8))
    output = buffer.getvalue()

    assert "Enter 开始任务" in output
    assert "E 调整编排" in output
    assert "S 保存启动包" in output
    assert "使用当前编排继续进入执行阶段" not in output
    assert "用操作式方式修改步骤" not in output


def test_review_screen_renderable_wraps_scroll_region_in_box() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        plan=[LabPlanItem(f"S{index}", f"步骤 {index}", "codex", 10, f"完成步骤 {index}") for index in range(1, 6)],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责实现"}],
            "steps": [
                {"id": f"S{index}", "owner": "codex", "goal": f"步骤 {index}", "input": "任务输入", "output": "任务输出", "done_when": f"完成步骤 {index}", "eta_minutes": 10}
                for index in range(1, 6)
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    console.print(_review_screen_renderable(state, result, scroll_offset=0, max_body_lines=8, width=90))
    output = buffer.getvalue()

    assert "┌" in output
    assert "└" in output
    assert "计划内容" in output


def test_review_screen_renderable_shows_scrollbar_thumb_for_long_plan() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        plan=[LabPlanItem(f"S{index}", f"步骤 {index}", "codex", 10, f"完成步骤 {index}") for index in range(1, 12)],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责实现"}],
            "steps": [
                {"id": f"S{index}", "owner": "codex", "goal": f"步骤 {index}", "input": "任务输入", "output": "任务输出", "done_when": f"完成步骤 {index}", "eta_minutes": 10}
                for index in range(1, 12)
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    console.print(_review_screen_renderable(state, result, scroll_offset=5, max_body_lines=8, width=90))
    output = buffer.getvalue()

    assert "█" in output


def test_review_screen_renderable_uses_dedicated_right_scrollbar_column() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _review_screen_renderable
    from ai_collab.ux_lab_v3 import LabPlanItem, UxLabV3Result

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    result = UxLabV3Result(
        status="planned",
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        plan=[LabPlanItem(f"S{index}", f"步骤 {index}", "codex", 10, f"完成步骤 {index}") for index in range(1, 12)],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [{"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责实现"}],
            "steps": [
                {"id": f"S{index}", "owner": "codex", "goal": f"步骤 {index}", "input": "任务输入", "output": "任务输出", "done_when": f"完成步骤 {index}", "eta_minutes": 10}
                for index in range(1, 12)
            ],
            "approval_question": "是否执行该计划？",
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    console.print(_review_screen_renderable(state, result, scroll_offset=5, max_body_lines=8, width=90))
    output = buffer.getvalue()

    assert "│█│" in output
    assert "│░│" in output


def test_plan_step_form_renderable_shows_prefilled_values() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_step_form_renderable
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    draft = PlanDraft(
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep(
                id="S1",
                title="收敛测试范围并定义通过标准",
                owner="claude",
                eta_minutes=10,
                done_when="明确至少 1 条主测试路径和 2 类边界条件",
            )
        ],
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    console.print(_plan_step_form_renderable(state, draft, step_index=0, is_insert=False))
    output = buffer.getvalue()

    assert "编辑步骤 · S1" in output
    assert "步骤标题" in output
    assert "收敛测试范围并定义通过标准" in output
    assert "分配 Agent" in output
    assert "Claude Code" in output
    assert "预计耗时" in output
    assert "10" in output
    assert "完成条件" in output
    assert "明确至少 1 条主测试路径和 2 类边界条件" in output


def test_plan_step_form_renderable_uses_compact_layout_for_small_terminal() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_step_form_renderable
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    draft = PlanDraft(
        workspace=state.workspace,
        controller="codex",
        task="制作一个贪吃蛇小游戏",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep(
                id="S1",
                title="收敛测试范围并定义通过标准",
                owner="claude",
                eta_minutes=10,
                done_when="明确至少 1 条主测试路径和 2 类边界条件",
            )
        ],
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=64)
    console.print(_plan_step_form_renderable(state, draft, step_index=0, is_insert=False, compact=True, width=64))
    output = buffer.getvalue()

    assert "编辑步骤 · S1" in output
    assert "步骤标题 ·" in output
    assert "分配 Agent · Claude Code" in output
    assert "╭─ 步骤标题" not in output
    assert len(output.splitlines()) <= 8


def test_plan_task_form_renderable_shows_prefilled_task_name() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_task_form_renderable

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    task = "完成 ProjectPrinting 的 Widget 设计与落地"

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    console.print(_plan_task_form_renderable(state, task))
    output = buffer.getvalue()

    assert "修改任务名称" in output
    assert "任务名称" in output
    assert "完成 ProjectPrinting 的 Widget 设计与落地" in output


def test_plan_task_form_renderable_uses_compact_layout_for_small_terminal() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_task_form_renderable

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/test_game"),
        from_entry=True,
    )
    task = "完成 ProjectPrinting 的 Widget 设计与落地并补齐回归验证"

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=64)
    console.print(_plan_task_form_renderable(state, task, compact=True, width=64))
    output = buffer.getvalue()

    assert "修改任务名称" in output
    assert "任务名称 ·" in output
    assert "ProjectPrinting" in output
    assert "╭─ 任务名称" not in output
    assert len(output.splitlines()) <= 6


def test_step_screen_renderable_emits_ansi_colors_for_planner_options(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _step_screen_renderable

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=tmp_path,
        workspace=tmp_path,
        from_entry=True,
    )
    state.controller = "claude"

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="truecolor", width=120, no_color=False)
    console.print(_step_screen_renderable(state, "planner", pointed_value="1"))

    ansi = buffer.getvalue()
    assert "\x1b[" in ansi
    assert "38;2;251;146;60" in ansi


def test_planning_progress_renderable_truncates_long_prompt(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, PlanningProgressState, _planning_progress_renderable

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    progress = PlanningProgressState(
        stage="prompt_ready",
        prompt_text="\n".join(f"line {index}" for index in range(30)),
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    console.print(_planning_progress_renderable(state, progress, spinner_frame="⠋"))
    output = buffer.getvalue()

    assert "line 0" in output
    assert "line 11" in output
    assert "line 20" not in output
    assert "..." in output


def test_planning_progress_renderable_shows_elapsed_and_cancel_hint(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, PlanningProgressState, _planning_progress_renderable

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    progress = PlanningProgressState(
        stage="command_started",
        prompt_text="任务测试",
        started_at=time.time() - 65,
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    console.print(_planning_progress_renderable(state, progress, spinner_frame="⠋"))
    output = buffer.getvalue()

    assert "已发送 prompt" in output
    assert "已耗时" in output
    assert "65s" in output
    assert "Ctrl-C" in output


def test_task_toolbar_copy_explains_slash_commands_need_new_line() -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _task_toolbar_message

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=Path("/Users/skyhua/ai-collab"), from_entry=True)

    message = _task_toolbar_message(state)

    assert "新起一行" in message or "另起一行" in message
    assert "/done" in message


def test_edit_plan_prompt_back_preserves_current_draft(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _edit_plan_prompt

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    result = UxLabV3Result(
        status="planned",
        workspace=tmp_path,
        controller="codex",
        task="实现 tmux 修复",
        lang="zh-CN",
        planner_mode="live",
        plan=[
            LabPlanItem("S1", "修改启动流程", "codex", 8, "能稳定进入执行"),
            LabPlanItem("S2", "补充回归测试", "claude", 6, "测试覆盖返回行为"),
        ],
        controller_plan={
            "plan_version": "1.0",
            "controller": "codex",
            "requires_multi_agent": True,
            "agents": [
                {"name": "codex", "model": "gpt-5.4", "persona": "controller", "why": "负责实现"},
                {"name": "claude", "model": "claude-sonnet-4-6", "persona": "collaborator", "why": "负责审查"},
            ],
            "steps": [
                {"id": "S1", "owner": "codex", "goal": "修改启动流程", "done_when": "能稳定进入执行", "eta_minutes": 8},
                {"id": "S2", "owner": "claude", "goal": "补充回归测试", "done_when": "测试覆盖返回行为", "eta_minutes": 6},
            ],
        },
    )
    actions = iter(["delete", "back"])

    def _selector(**_kwargs) -> str:
        return next(actions)

    updated = _edit_plan_prompt(
        state=state,
        result=result,
        selector_fn=_selector,
        input_fn=lambda *_args, **_kwargs: "",
        console_obj=Console(file=StringIO(), force_terminal=False, color_system=None, width=120),
        clear_screen=False,
    )

    assert len(updated.plan) == 1
    assert updated.plan[0].title == "补充回归测试"
    assert updated.controller_plan is not None
    assert updated.controller_plan["requires_multi_agent"] is False


def test_plan_editor_screen_renderable_highlights_model_routes_and_prompt(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_editor_screen_renderable
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    draft = PlanDraft(
        workspace=tmp_path,
        controller="codex",
        task="重新编排登录模块修复",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep("S1", "确认登录修复边界", "claude", 8, "列出鉴权入口和回归范围"),
            PlanDraftStep("S2", "实现登录修复", "codex", 20, "登录流程通过本地验证"),
        ],
        source_controller_plan={
            "agents": [
                {"name": "claude", "model": "claude-sonnet-4-6"},
                {"name": "codex", "model": "gpt-5.4"},
            ]
        },
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    console.print(_plan_editor_screen_renderable(state, draft, selected_index=1))
    output = buffer.getvalue()

    assert "Prompt / 任务输入" in output
    assert "模型路由" in output
    assert "重新编排登录模块修复" in output
    assert "gpt-5.4" in output
    assert "claude-sonnet-4-6" in output


def test_plan_editor_screen_renderable_keeps_selected_step_visible_in_viewport(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_editor_screen_renderable
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    draft = PlanDraft(
        workspace=tmp_path,
        controller="codex",
        task="检查长编排滚动",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep(f"S{index}", f"长编排步骤 {index}", "codex", 5, f"完成长编排步骤 {index}")
            for index in range(1, 10)
        ],
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    console.print(_plan_editor_screen_renderable(state, draft, selected_index=7, max_visible_steps=4))
    output = buffer.getvalue()

    assert "长编排步骤 8" in output
    assert "长编排步骤 1" not in output
    assert "显示步骤" in output


def test_plan_editor_screen_renderable_uses_compact_layout_for_small_terminal(tmp_path) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _plan_editor_screen_renderable
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    draft = PlanDraft(
        workspace=tmp_path,
        controller="codex",
        task="小窗口重新编排登录和支付修复",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep(f"S{index}", f"小窗口步骤 {index}", "codex", 5, f"完成小窗口步骤 {index}")
            for index in range(1, 10)
        ],
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=70)
    console.print(
        _plan_editor_screen_renderable(
            state,
            draft,
            selected_index=7,
            max_visible_steps=3,
            compact=True,
            width=70,
        )
    )
    output = buffer.getvalue()

    assert "Prompt / 任务输入 ·" in output
    assert "路由 ·" in output
    assert "╭─ 模型路由" not in output
    assert "小窗口步骤 8" in output
    assert "小窗口步骤 1" not in output
    assert len(output.splitlines()) <= 24


def test_plan_step_form_scales_layout_in_small_terminal(monkeypatch, tmp_path) -> None:
    import os
    from prompt_toolkit.layout.containers import HSplit

    from ai_collab.launch_prompt import LaunchPromptState, _prompt_plan_step_form_with_prompt_toolkit
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    draft = PlanDraft(
        workspace=tmp_path,
        controller="codex",
        task="检查极小窗口表单",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep("S1", "确认窗口太小时的降级提示", "claude", 5, "显示可理解的窗口太小提示")
        ],
    )
    captured: dict[str, object] = {}

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)

        def run(self) -> None:
            return None

    monkeypatch.setattr("prompt_toolkit.application.Application", _FakeApplication)
    monkeypatch.setattr(
        "ai_collab.launch_prompt.shutil.get_terminal_size",
        lambda *_args, **_kwargs: os.terminal_size((80, 12)),
    )

    _prompt_plan_step_form_with_prompt_toolkit(
        state=state,
        draft=draft,
        step_index=0,
        is_insert=False,
        console_obj=Console(file=StringIO(), force_terminal=False, color_system=None, width=80),
        clear_screen=False,
    )

    assert isinstance(captured["layout"].container, HSplit)


def test_plan_step_form_uses_window_too_small_fallback_only_for_tiny_terminal(monkeypatch, tmp_path) -> None:
    import os
    from prompt_toolkit.layout.containers import Window

    from ai_collab.launch_prompt import LaunchPromptState, _prompt_plan_step_form_with_prompt_toolkit
    from ai_collab.plan_editor_prompt import PlanDraft, PlanDraftStep

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(config, cwd=tmp_path, workspace=tmp_path, from_entry=True)
    draft = PlanDraft(
        workspace=tmp_path,
        controller="codex",
        task="检查极小窗口表单",
        lang="zh-CN",
        planner_mode="live",
        steps=[
            PlanDraftStep("S1", "确认极小窗口时仍有兜底提示", "claude", 5, "显示可理解的窗口太小提示")
        ],
    )
    captured: dict[str, object] = {}

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)

        def run(self) -> None:
            return None

    monkeypatch.setattr("prompt_toolkit.application.Application", _FakeApplication)
    monkeypatch.setattr(
        "ai_collab.launch_prompt.shutil.get_terminal_size",
        lambda *_args, **_kwargs: os.terminal_size((40, 7)),
    )

    _prompt_plan_step_form_with_prompt_toolkit(
        state=state,
        draft=draft,
        step_index=0,
        is_insert=False,
        console_obj=Console(file=StringIO(), force_terminal=False, color_system=None, width=40),
        clear_screen=False,
    )

    assert isinstance(captured["layout"].container, Window)


def test_prompt_task_with_prompt_toolkit_clears_screen_without_fullscreen_flash(monkeypatch) -> None:
    from ai_collab.launch_prompt import LaunchPromptState, _prompt_task_with_prompt_toolkit

    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = LaunchPromptState.from_config(
        config,
        cwd=Path("/Users/skyhua/ai-collab"),
        workspace=Path("/Users/skyhua/ai-collab"),
        from_entry=True,
    )
    captured: dict[str, object] = {}

    class _Console:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

    class _FakeApplication:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)

        def run(self) -> str:
            return "/quit"

    console = _Console()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("prompt_toolkit.application.Application", _FakeApplication)

    result = _prompt_task_with_prompt_toolkit(state, console_obj=console, clear_screen=True)

    assert result == "/quit"
    assert console.clear_calls == 1
    assert captured["full_screen"] is False
