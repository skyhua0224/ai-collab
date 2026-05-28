from pathlib import Path

import ai_collab.cli as cli
from ai_collab.ux_lab import (
    build_mock_plan,
    filter_workspace_candidates,
    parse_task_editor_command,
    resolve_lab_language,
)


def test_resolve_lab_language_uses_supported_config_value() -> None:
    assert resolve_lab_language("zh-CN") == "zh-CN"
    assert resolve_lab_language("en-US") == "en-US"


def test_resolve_lab_language_falls_back_to_english() -> None:
    assert resolve_lab_language("") == "en-US"
    assert resolve_lab_language("fr-FR") == "en-US"


def test_filter_workspace_candidates_matches_query_and_preserves_order() -> None:
    candidates = [
        Path("/Users/skyhua/ai-collab"),
        Path("/Users/skyhua/ProjectPrinting"),
        Path("/Users/skyhua/Downloads"),
    ]

    result = filter_workspace_candidates(candidates, "proj")

    assert result == [Path("/Users/skyhua/ProjectPrinting")]


def test_parse_task_editor_command_supports_known_editor_commands() -> None:
    assert parse_task_editor_command("/nano") == "nano"
    assert parse_task_editor_command(" /vim  ") == "vim"
    assert parse_task_editor_command("/noop") is None


def test_build_mock_plan_returns_localized_numbered_steps() -> None:
    plan = build_mock_plan(
        task="使用 codex 主控调度 gemini 和 claude 完成 tmux 测试",
        controller="codex",
        lang="zh-CN",
    )

    assert [item.sx for item in plan] == ["S1", "S2", "S3"]
    assert plan[0].agent == "codex"
    assert plan[1].agent in {"gemini", "claude"}
    assert plan[0].title
    assert plan[0].done_when
    assert plan[0].eta_minutes > 0


def test_project_main_routes_ux_lab_to_click_main(monkeypatch) -> None:
    captured = {"args": []}

    def _fake_click_main(*, args, prog_name, standalone_mode):  # noqa: ARG001
        captured["args"] = list(args)

    monkeypatch.setattr(cli.main, "main", _fake_click_main)
    monkeypatch.setattr(cli.sys, "argv", ["ai-collab", "ux-lab", "--help"])

    cli.project_main()

    assert captured["args"] == ["ux-lab", "--help"]


def test_project_help_mentions_ux_lab(capsys) -> None:
    cli._print_project_help()

    captured = capsys.readouterr()
    assert "ux-lab" in (captured.out + captured.err)
