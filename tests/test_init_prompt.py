from __future__ import annotations

from io import StringIO

import click
import pytest

import ai_collab.cli as cli
from ai_collab.core.config import Config
from click.testing import CliRunner
from rich.console import Console

from ai_collab.init_prompt import (
    InitPromptState,
    _build_selector_rows,
    _enabled_agent_values,
    _resolve_screen,
    build_init_banner,
    render_init_prompt_screen,
    run_init_prompt,
)


def test_init_auto_mode_prefers_prompt_setup(monkeypatch) -> None:
    config = Config.create_default()
    saved: dict[str, bool] = {"called": False}
    prompt_calls: list[str] = []

    monkeypatch.setattr(cli.Config, "initialize", classmethod(lambda cls: config))
    monkeypatch.setattr(cli.Config, "save", lambda self: saved.__setitem__("called", True))
    monkeypatch.setattr(cli.sys, "stdin", type("_TTY", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(cli, "_run_init_setup_prompt", lambda cfg: prompt_calls.append(cfg.current_controller), raising=False)
    monkeypatch.setattr(cli, "_run_init_setup_tui", lambda cfg: (_ for _ in ()).throw(AssertionError("tui setup should not run")))
    monkeypatch.setattr(cli, "_run_init_setup_raw", lambda cfg: (_ for _ in ()).throw(AssertionError("raw setup should not run")))

    cli.init.callback.__wrapped__(None, force=True, interactive=True, ui_mode="auto", auto_install_deps=True)

    assert prompt_calls == ["claude"]
    assert saved["called"] is True



def test_init_text_mode_is_prompt_alias(monkeypatch) -> None:
    config = Config.create_default()
    prompt_calls: list[str] = []

    monkeypatch.setattr(cli.Config, "initialize", classmethod(lambda cls: config))
    monkeypatch.setattr(cli.Config, "save", lambda self: None)
    monkeypatch.setattr(cli.sys, "stdin", type("_TTY", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(cli, "_run_init_setup_prompt", lambda cfg: prompt_calls.append(cfg.current_controller), raising=False)
    monkeypatch.setattr(cli, "_run_init_setup_tui", lambda cfg: (_ for _ in ()).throw(AssertionError("tui setup should not run")))
    monkeypatch.setattr(cli, "_run_init_setup_raw", lambda cfg: (_ for _ in ()).throw(AssertionError("raw setup should not run")))

    cli.init.callback.__wrapped__(None, force=True, interactive=True, ui_mode="text", auto_install_deps=True)

    assert prompt_calls == ["claude"]



def test_init_help_defaults_to_auto_mode() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["init", "--help"])

    assert result.exit_code == 0
    assert "[default: auto]" in result.output



def test_build_init_banner_uses_remembered_brand_shape() -> None:
    banner = build_init_banner(90)

    assert any("___      ___" in line for line in banner)
    assert banner[-1] == "multi-agent coding orchestrator"



def test_build_init_banner_uses_block_brand_for_wide_term() -> None:
    banner = build_init_banner(160)

    assert any("█████" in line for line in banner)
    assert banner[-1] == "multi-agent coding orchestrator"



def test_render_init_prompt_screen_is_minimal_and_step_focused() -> None:
    config = Config.create_default()
    output = render_init_prompt_screen(config, step_id="language")

    assert "___      ___" in output or "AI COLLAB" in output
    assert "Step 1/7 · Display language" in output
    assert "Choose the display language for ai-collab." in output
    assert "Current defaults" not in output



def test_render_init_prompt_screen_shows_explicit_enabled_agents_step_after_language() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="enabled_agents")

    assert "步骤 2/7 · 启用 Agent" in output
    assert "选择哪些 Agent 默认保持启用。" in output
    assert "Codex" in output
    assert "Claude Code" in output
    assert "Gemini CLI" in output



def test_enabled_agents_screen_keeps_first_option_as_default() -> None:
    state = InitPromptState.from_config(Config.create_default())
    screen = _resolve_screen(state, "enabled_agents")

    assert screen.default_value == "1"
    assert screen.selection_mode == "multi"
    assert screen.options == [("1", "Codex"), ("2", "Claude Code"), ("3", "Gemini CLI")]



def test_enabled_agents_step_starts_with_all_agents_selected() -> None:
    state = InitPromptState.from_config(Config.create_default())

    assert _enabled_agent_values(state.form) == ["1", "2", "3"]



def test_enabled_agents_rows_include_explicit_continue_action() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"
    screen = _resolve_screen(state, "enabled_agents")
    rows = _build_selector_rows(state, screen, pointed_value="1", allow_back=True)

    assert [row.value for row in rows] == ["1", "2", "3", "c", "b", "q"]
    assert rows[3].label == "继续"



def test_enabled_agents_screen_shows_agent_descriptions_and_multiselect_note() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="enabled_agents")

    assert "默认全部启用。" in output
    assert "Enter / Space 切换，c 继续" in output
    assert "适合端到端工程执行、重构、测试与并行 Agent 工作流。" in output
    assert "适合代码库理解、编辑、调试与工作流自动化。" in output
    assert "适合大上下文、多模态输入、搜索调研与终端自动化。" in output



def test_controller_screen_uses_enabled_agents_only_and_defaults_to_first() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.providers = {"codex": True, "claude": False, "gemini": True}
    screen = _resolve_screen(state, "controller")

    assert screen.options == [("1", "Codex"), ("2", "Gemini CLI")]
    assert screen.default_value == "1"



def test_controller_screen_mentions_config_can_change_later() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="controller")

    assert "之后可在 ai-collab config 或交互终端的 /config 随时修改。" in output



def test_controller_screen_uses_full_names_and_specific_positioning_copy() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="controller")

    assert "Claude Code" in output
    assert "Gemini CLI" in output
    assert "适合端到端工程执行、重构、测试与并行 Agent 工作流。" in output
    assert "适合代码库理解、编辑、调试与工作流自动化。" in output
    assert "适合大上下文、多模态输入、搜索调研与终端自动化。" in output



def test_collaboration_screen_shows_explanations_for_each_option() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="collaboration")

    assert "新任务会先由主控判断，再按需要派发给其他 Agent。" in output
    assert "默认只使用主控，需要时再手动分配给其他 Agent。" in output



def test_entry_screen_shows_dim_explanations() -> None:
    state = InitPromptState.from_config(Config.create_default())

    output = render_init_prompt_screen(state, step_id="entry")

    assert "Guided launcher" in output
    assert "Start in the guided menu for common flows." in output
    assert "Command-first" in output
    assert "Jump straight into the minimal command surface." in output



def test_entry_rows_include_italic_descriptions() -> None:
    state = InitPromptState.from_config(Config.create_default())
    screen = _resolve_screen(state, "entry")
    rows = {row.value: row for row in _build_selector_rows(state, screen, pointed_value="2", allow_back=False)}

    assert rows["1"].description == "Start in the guided menu for common flows."
    assert rows["1"].description_style == "fg:#64748B italic"
    assert rows["2"].description == "Jump straight into the minimal command surface."
    assert rows["2"].description_style == "fg:#64748B italic"



def test_review_screen_uses_grouped_summary_layout() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="review")

    assert "当前配置" in output
    assert "界面" in output
    assert "Agent" in output
    assert "运行" in output
    assert "........" not in output



def test_review_screen_uses_icons_and_localized_labels() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"

    output = render_init_prompt_screen(state, step_id="review")

    assert "🖥 界面" in output
    assert "🤖 Agent" in output
    assert "⚙ 运行" in output
    assert "默认入口: 引导式启动器" in output
    assert "默认运行方式: tmux（稳定，推荐）" in output
    assert "启用 Agent: Codex, Claude Code, Gemini CLI" in output



def test_review_step_does_not_duplicate_back_action() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"
    screen = _resolve_screen(state, "review")
    rows = _build_selector_rows(state, screen, pointed_value="1", allow_back=True)
    values = [row.value for row in rows]
    output = render_init_prompt_screen(state, step_id="review")

    assert values == ["1", "2", "3", "q"]
    assert "返回上一步" in output
    assert "b 返回" not in output



def test_review_step_includes_advanced_config_entry() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.ui_language = "zh-CN"
    screen = _resolve_screen(state, "review")
    rows = _build_selector_rows(state, screen, pointed_value="1", allow_back=True)
    values = [row.value for row in rows]
    output = render_init_prompt_screen(state, step_id="review")

    assert values == ["1", "2", "3", "q"]
    assert "进入详细配置" in output
    assert "进入 config 菜单，继续调整更细的默认偏好与长期习惯。" in output



def test_build_selector_rows_swaps_default_and_pointed_treatment() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.providers = {"codex": True, "claude": False, "gemini": True}
    screen = _resolve_screen(state, "controller")
    rows = {row.value: row for row in _build_selector_rows(state, screen, pointed_value="2", allow_back=False)}

    assert rows["1"].prefix == "  "
    assert "bold" in rows["1"].label_style
    assert "underline" not in rows["1"].label_style
    assert rows["2"].prefix == "❯ "
    assert "#22C55E" in rows["2"].label_style
    assert "underline" not in rows["2"].label_style
    assert rows["2"].marker == ""



def test_enabled_agents_rows_use_multiselect_circles_and_colored_checked_state() -> None:
    state = InitPromptState.from_config(Config.create_default())
    state.form.providers = {"codex": True, "claude": False, "gemini": True}
    screen = _resolve_screen(state, "enabled_agents")
    rows = {row.value: row for row in _build_selector_rows(state, screen, pointed_value="3", allow_back=False)}

    assert rows["1"].prefix == "  "
    assert rows["1"].marker == "●"
    assert "#06B6D4" in rows["1"].marker_style
    assert rows["2"].marker == "○"
    assert rows["2"].marker_style == "fg:#64748B"
    assert rows["3"].prefix == "❯ "
    assert rows["3"].marker == "●"
    assert "#22C55E" in rows["3"].marker_style
    assert "underline" not in rows["3"].label_style



def test_run_init_prompt_uses_selector_fn_for_arrow_flow(monkeypatch) -> None:
    config = Config.create_default()
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    answers = iter(["1", "1,2,3", "1", "1", "1", "1", "1"])
    events: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(Config, "save", lambda self: None)

    def _selector(state, screen, *, allow_back: bool, console_obj: Console, clear_screen: bool) -> str:
        events.append((screen.title, screen.default_value, allow_back))
        return next(answers)

    run_init_prompt(
        config,
        console_obj=console,
        clear_screen=False,
        selector_fn=_selector,
    )

    assert events
    assert events[0] == ("Display language", "1", False)
    assert events[1][0] == "Enabled agents"
    assert events[1][2] is True



def test_run_init_prompt_saves_language_immediately(monkeypatch) -> None:
    config = Config.create_default()
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    answers = iter(["2", "q"])
    saved_languages: list[str] = []

    monkeypatch.setattr(Config, "save", lambda self: saved_languages.append(self.ui_language))

    def _selector(state, screen, *, allow_back: bool, console_obj: Console, clear_screen: bool) -> str:
        return next(answers)

    with pytest.raises(click.Abort):
        run_init_prompt(
            config,
            console_obj=console,
            clear_screen=False,
            selector_fn=_selector,
        )

    assert config.ui_language == "zh-CN"
    assert saved_languages == ["zh-CN"]



def test_run_init_prompt_applies_scripted_answers(monkeypatch) -> None:
    config = Config.create_default()
    answers = iter(["2", "1,3", "1", "2", "2", "2", "1"])
    console = Console(file=StringIO(), force_terminal=False, color_system=None, width=90)

    monkeypatch.setattr(Config, "save", lambda self: None)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        if "," in answer:
            selected = {item.strip() for item in answer.split(",") if item.strip()}
            assert selected.issubset(set(choices))
        else:
            assert answer in choices
        return answer

    run_init_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert config.ui_language == "zh-CN"
    assert config.current_controller == "codex"
    assert config.providers["codex"].enabled is True
    assert config.providers["claude"].enabled is False
    assert config.providers["gemini"].enabled is True
    assert config.runtime_mode == "direct"
    assert config.entry_surface == "command"
    assert config.auto_collaboration["enabled"] is False



def test_run_init_prompt_can_jump_into_advanced_config(monkeypatch) -> None:
    config = Config.create_default()
    answers = iter(["2", "1,2,3", "1", "1", "1", "1", "3"])
    console = Console(file=StringIO(), force_terminal=False, color_system=None, width=90)
    advanced_calls: list[Config] = []

    monkeypatch.setattr(Config, "save", lambda self: None)
    monkeypatch.setattr("ai_collab.config_prompt.run_config_menu_prompt", lambda cfg, **kwargs: advanced_calls.append(cfg) or True)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        if "," in answer:
            selected = {item.strip() for item in answer.split(",") if item.strip()}
            assert selected.issubset(set(choices))
        else:
            assert answer in choices
        return answer

    run_init_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert len(advanced_calls) == 1
    assert advanced_calls[0].ui_language == "zh-CN"
    assert advanced_calls[0].current_controller == "codex"



def test_render_init_prompt_screen_omits_full_summary_on_non_review_steps() -> None:
    config = Config.create_default()
    output = render_init_prompt_screen(config, step_id="language")

    assert "Current defaults" not in output
    assert "Controller: " not in output



def test_render_init_prompt_screen_uses_ascii_banner() -> None:
    config = Config.create_default()
    output = render_init_prompt_screen(config, step_id="language")

    assert "multi-agent coding orchestrator" in output
    assert "___      ___" in output or "AI COLLAB" in output



def test_run_init_prompt_renders_each_step_once(monkeypatch) -> None:
    config = Config.create_default()
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=90)
    answers = iter(["1", "1,2,3", "1", "1", "1", "1", "1"])

    monkeypatch.setattr(Config, "save", lambda self: None)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        return next(answers)

    run_init_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)
    output = buffer.getvalue()

    assert output.count("multi-agent coding orchestrator") == 7
    assert output.count("Step 1/7 · Display language") == 1



def test_render_init_prompt_screen_runtime_shows_enabled_agents_summary_and_descriptions() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    output = render_init_prompt_screen(config, step_id="runtime")

    assert "当前已启用：Codex、Claude Code、Gemini CLI" in output
    assert "适合长期会话、分屏观察与稳定协作。" in output
    assert "启动更直接，但终端接管与兼容性更依赖当前环境。" in output
