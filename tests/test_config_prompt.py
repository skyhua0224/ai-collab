from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import ai_collab.cli as cli
from ai_collab.core.config import Config
from ai_collab.config_prompt import _app_section_screen, _provider_picker_screen, _routing_section_screen, render_choice_screen, render_config_menu_screen, run_config_menu_prompt, ConfigMenuState
from rich.console import Console


def test_render_config_menu_screen_groups_settings_by_category() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    config.current_controller = "codex"
    config.entry_surface = "guided"
    config.runtime_mode = "tmux"

    output = render_config_menu_screen(config)

    assert "ai-collab config" in output
    assert "常用默认项" in output
    assert "协作与路由" in output
    assert "模型与计费" in output
    assert "应用设置" in output
    assert "1. 显示语言" not in output
    assert "保存并完成" in output



def test_render_config_menu_screen_explains_advanced_preferences_role() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    output = render_config_menu_screen(config)

    assert "这里用于调整长期默认偏好与个人习惯。" in output
    assert "如果只是某次任务的临时偏好，建议在 Session Console 中修改。" in output



def test_run_config_menu_prompt_applies_scripted_changes(monkeypatch) -> None:
    config = Config.create_default()
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    answers = iter(["4", "1", "2", "b", "1", "2", "1", "3", "2", "b", "5"])
    saved_states: list[tuple[str, str, str]] = []

    monkeypatch.setattr(Config, "save", lambda self: saved_states.append((self.ui_language, self.current_controller, self.runtime_mode)))

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is True
    assert config.ui_language == "zh-CN"
    assert config.current_controller == "codex"
    assert config.runtime_mode == "direct"
    assert saved_states == [("zh-CN", "codex", "direct")]



def test_config_interactive_uses_prompt_menu(monkeypatch, capsys) -> None:
    config = Config.create_default()
    ctx = SimpleNamespace(obj={"config": config})
    called: list[Config] = []

    monkeypatch.setattr("ai_collab.config_prompt.run_config_menu_prompt", lambda cfg: called.append(cfg) or True)

    cli.config.callback.__wrapped__(ctx, action="interactive", key=None, value=None)

    captured = capsys.readouterr().out
    assert called == [config]
    assert "Configuration saved" in captured



def test_render_config_menu_screen_keeps_root_menu_minimal() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    output = render_config_menu_screen(config)

    assert "    主控 Claude Code /" not in output
    assert "    系统推荐自动路由 /" not in output
    assert "    3 个模型提供方 /" not in output
    assert "    中文 (zh-CN) /" not in output
    assert "启用 Agent、默认主控、运行方式、默认入口、自动协作。" in output



def test_run_config_menu_prompt_saves_routing_and_model_preferences(monkeypatch) -> None:
    config = Config.create_default()
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    answers = iter([
        "2", "1", "2",      # routing -> preset -> coding lead
        "2", "3", "3",      # routing -> research -> Claude Code first
        "b",                  # back to root
        "3", "2",            # models&cost -> economics
        "2", "3",            # economics -> cost bias -> cost first
        "b",                  # back to models&cost
        "1", "2", "2",      # model pref -> Claude Code -> powerful
        "b",                  # back to root
        "5",                  # save
    ])
    saved_snapshots: list[tuple[str, str, str, str, str, str]] = []

    def _save(self: Config) -> None:
        saved_snapshots.append((
            self.ui_language,
            self.auto_collaboration.get("preset", ""),
            self.routing.get("cost_bias", ""),
            self.routing.get("intent_preferences", {}).get("research", [""])[0],
            self.providers["claude"].model_selection,
            self.providers["claude"].models.get("default", ""),
        ))

    monkeypatch.setattr(Config, "save", _save)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is True
    assert config.auto_collaboration["preset"] == "coding-lead"
    assert config.routing["cost_bias"] == "cost-first"
    assert config.routing["intent_preferences"]["research"][0] == "claude"
    assert config.providers["claude"].model_selection == "powerful"
    assert config.providers["claude"].models["default"] == "claude-opus-4-6"
    assert saved_snapshots == [(
        "en-US",
        "coding-lead",
        "cost-first",
        "claude",
        "powerful",
        "claude-opus-4-6",
    )]



def test_config_enabled_agents_editor_does_not_fall_back_to_init_step_ui(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    answers = iter(["1", "1", "q"])

    monkeypatch.setattr(Config, "save", lambda self: None)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "常用默认项" in output
    assert "步骤 2/7" not in output
    assert "Step 2/7" not in output


def test_run_config_menu_prompt_saves_economics_preferences(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    answers = iter([
        "3",
        "2", "1", "2",      # models&cost -> economics -> pricing -> official reference
        "2", "3",            # economics -> cost bias -> cost first
        "3", "2", "3", "2", "1",  # provider billing -> Claude -> subscription -> daily quota -> lower cost
        "b",                  # back to models&cost
        "b",                  # back to root
        "5",
    ])
    saved_snapshots: list[tuple[str, str, str, str]] = []

    def _save(self: Config) -> None:
        saved_snapshots.append((
            self.ui_language,
            self.economics.get("pricing_mode", ""),
            self.routing.get("cost_bias", ""),
            self.economics.get("providers", {}).get("claude", {}).get("billing_mode", ""),
        ))

    monkeypatch.setattr(Config, "save", _save)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is True
    assert config.economics["pricing_mode"] == "official-reference"
    assert config.routing["cost_bias"] == "cost-first"
    assert config.economics["providers"]["claude"]["billing_mode"] == "subscription-quota"
    assert config.economics["providers"]["claude"]["quota_window"] == "daily"
    assert config.economics["providers"]["claude"]["relative_cost_tier"] == "lower"
    assert saved_snapshots == [("zh-CN", "official-reference", "cost-first", "subscription-quota")]


def test_render_config_menu_screen_uses_application_settings_group_name() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    output = render_config_menu_screen(config)

    assert "应用设置" in output
    assert "界面与显示" not in output


def test_provider_picker_shows_actual_model_identifier_and_thinking() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = ConfigMenuState.from_config(config)

    output = render_choice_screen(_provider_picker_screen(state, config), lang="zh-CN", allow_back=True)

    assert "gpt-5.4" in output
    assert "深度开发" in output or "标准开发" in output
    assert "claude-sonnet-4-6" in output
    assert "gemini-3.1-pro-preview" in output


def test_application_settings_screen_includes_about_and_update_preferences() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = ConfigMenuState.from_config(config)

    output = render_choice_screen(_app_section_screen(state), lang="zh-CN", allow_back=True)

    assert "显示语言" in output
    assert "检查更新" in output
    assert "自动检查更新" in output
    assert "关于 ai-collab" in output




def test_render_config_menu_screen_keeps_root_items_clean_without_inline_status_blob() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    output = render_config_menu_screen(config)

    assert "1. 常用默认项 ·" not in output
    assert "2. 协作与路由 ·" not in output
    assert "3. 模型与计费 ·" not in output
    assert "4. 应用设置 ·" not in output
    assert "    主控 Claude Code /" not in output


def test_provider_picker_and_profile_copy_use_chinese_descriptions() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = ConfigMenuState.from_config(config)

    picker_output = render_choice_screen(_provider_picker_screen(state, config), lang="zh-CN", allow_back=True)

    assert "深度开发" in picker_output or "均衡默认" in picker_output

    answers = iter(["3", "1", "1", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "多文件实现" in output or "高质量视觉设计" in output or "轻量审查" in output
    assert "高思考" not in output


def test_routing_screen_includes_agent_preference_area() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = ConfigMenuState.from_config(config)

    output = render_choice_screen(_routing_section_screen(state), lang="zh-CN", allow_back=True)

    assert "Agent 偏好" in output
    assert "用人话说明 Codex、Claude 与 Gemini 默认更适合做什么" in output


def test_run_config_menu_prompt_can_open_agent_preference_reference_page(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["2", "3", "b", "b", "q"])

    monkeypatch.setattr(Config, "save", lambda self: None)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "Agent 偏好" in output
    assert "Codex" in output
    assert "终端执行、改代码、跑测试" in output


def test_application_settings_screen_is_flat_and_has_check_updates_entry() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    state = ConfigMenuState.from_config(config)

    output = render_choice_screen(_app_section_screen(state), lang="zh-CN", allow_back=True)

    assert "显示语言" in output
    assert "检查更新" in output
    assert "自动检查更新" in output
    assert "关于 ai-collab" in output
    assert "更新设置" not in output


def test_run_config_menu_prompt_can_toggle_auto_update_from_flat_app_screen(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    answers = iter(["4", "3", "2", "b", "5"])

    monkeypatch.setattr(Config, "save", lambda self: None)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is True
    assert config.application["auto_check_updates"] is False




def test_check_updates_page_uses_pypi_comparison(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    monkeypatch.setattr(
        "ai_collab.config_prompt.check_pypi_update",
        lambda **_: type("Result", (), {
            "local_version": "0.1.5.dev0",
            "remote_version": "0.1.4",
            "status": "ahead",
            "package_name": "ai-collab",
            "detail": "Local build is ahead of PyPI.",
        })(),
    )

    answers = iter(["4", "2", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "PyPI" in output
    assert "0.1.5.dev0" in output
    assert "0.1.4" in output
    assert "领先" in output or "ahead" in output


def test_about_page_renders_compact_metadata_with_inline_actions() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    answers = iter(["4", "4", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "AI COLLAB" in output
    assert "开发者" in output
    assert "GitHub" in output
    assert "https://github.com/skyhua0224/ai-collab" in output
    assert "检查更新" in output
    assert "当前聚焦" not in output
    assert "界面路线" not in output


def test_render_config_menu_screen_uses_billing_wording_instead_of_provider_english() -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    output = render_config_menu_screen(config)

    assert "模型与计费" in output
    assert "Provider 偏好" not in output


def test_check_updates_page_uses_compact_single_page_layout(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    monkeypatch.setattr(
        "ai_collab.config_prompt.check_pypi_update",
        lambda **_: type("Result", (), {
            "local_version": "0.1.5.dev0",
            "remote_version": "0.1.4",
            "status": "ahead",
            "package_name": "ai-collab",
            "detail": "Local build is ahead of PyPI.",
        })(),
    )

    answers = iter(["4", "2", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "本地版本" in output
    assert "PyPI 版本" in output
    assert "自动检查" in output
    assert "立即更新" in output
    assert "版本对比" not in output
    assert "更新策略" not in output
    assert "下一步" not in output


def test_about_page_can_jump_to_update_page(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"

    monkeypatch.setattr(
        "ai_collab.config_prompt.check_pypi_update",
        lambda **_: type("Result", (), {
            "local_version": "0.1.5.dev0",
            "remote_version": "0.1.6",
            "status": "behind",
            "package_name": "ai-collab",
            "detail": "A newer release exists on PyPI.",
        })(),
    )

    answers = iter(["4", "4", "u", "b", "b", "q"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    output = buffer.getvalue()
    assert "GitHub" in output
    assert "PyPI 版本" in output


def test_update_page_can_toggle_auto_update_inline(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    answers = iter(["4", "2", "t", "b", "b", "5"])

    monkeypatch.setattr(Config, "save", lambda self: None)
    monkeypatch.setattr(
        "ai_collab.config_prompt.check_pypi_update",
        lambda **_: type("Result", (), {
            "local_version": "0.1.5.dev0",
            "remote_version": "0.1.5.dev0",
            "status": "equal",
            "package_name": "ai-collab",
            "detail": "Local version matches PyPI.",
        })(),
    )

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is True
    assert config.application["auto_check_updates"] is False


def test_update_page_can_run_self_update_when_requested(monkeypatch) -> None:
    config = Config.create_default()
    config.ui_language = "zh-CN"
    calls = {"updated": False}

    monkeypatch.setattr(
        "ai_collab.config_prompt.check_pypi_update",
        lambda **_: type("Result", (), {
            "local_version": "0.1.5.dev0",
            "remote_version": "0.1.6",
            "status": "behind",
            "package_name": "ai-collab",
            "detail": "A newer release exists on PyPI.",
        })(),
    )
    monkeypatch.setattr(
        "ai_collab.config_prompt.run_self_update",
        lambda **_: calls.__setitem__("updated", True) or True,
    )

    answers = iter(["4", "2", "i"])
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    def _input(prompt: str, *, choices: list[str], default: str) -> str:
        answer = next(answers)
        assert answer in choices
        return answer

    saved = run_config_menu_prompt(config, input_fn=_input, console_obj=console, clear_screen=False)

    assert saved is False
    assert calls["updated"] is True
    assert "更新完成" in buffer.getvalue()
