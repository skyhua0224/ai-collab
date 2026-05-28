#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time


SCHEMES = [
    "baseline-current",
    "strict-param",
    "compact-operator",
    "timeline-focused",
    "two-stage-gate",
]
SCENARIOS = ["success", "planner-fail"]

CTX = {
    "controller": "codex",
    "session": "ai-collab-live",
    "controller_pane": "%0",
    "gemini_pane": "%1",
    "claude_window": "@2",
    "claude_pane": "%2",
    "planner_error": (
        "codex planner failed: /Users/skyhua/.cc-switch/skills/"
        "madappgang-claude-code-vue-typescript/SKILL.md missing YAML frontmatter"
    ),
}


def color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def emit(lines: list[str], *, delay: float, use_color: bool) -> None:
    palette = {
        "title": "1;36",
        "ok": "1;32",
        "warn": "1;33",
        "err": "1;31",
        "dim": "2",
        "step": "1;34",
    }
    for raw in lines:
        tag = ""
        text = raw
        if raw.startswith("[TITLE] "):
            tag, text = "title", raw[8:]
        elif raw.startswith("[OK] "):
            tag, text = "ok", raw[5:]
        elif raw.startswith("[WARN] "):
            tag, text = "warn", raw[7:]
        elif raw.startswith("[ERR] "):
            tag, text = "err", raw[6:]
        elif raw.startswith("[DIM] "):
            tag, text = "dim", raw[6:]
        elif raw.startswith("[STEP] "):
            tag, text = "step", raw[7:]
        if tag:
            print(color(text, palette[tag], use_color))
        else:
            print(text)
        if delay > 0:
            time.sleep(delay)


def baseline_current(scenario: str) -> list[str]:
    lines = [
        "[TITLE] 方案: baseline-current",
        "[DIM] 对照组。模拟当前最容易让用户困惑的输出风格。",
        "",
        "🤝 启动多 AI 协作流程",
        "工作流: systems-tooling",
        "主导 Agent: codex",
        "审查 Agent: claude",
        "项目分类: docs-text, systems-tooling",
        "自动技能: cli-tooling, automation, release-pipeline, technical-writing, editorial-review, testing",
        "",
        "可用 Agent",
        "  - claude: model=claude-sonnet-4-6 profile=default strengths=reasoning, code-review, architecture, documentation, security",
        "  - codex: model=gpt-5.4 profile=high strengths=implementation, testing, debugging, integration, backend",
        "  - gemini: model=gemini-3.1-pro-preview profile=powerful strengths=visual-design, html-css, research, ecosystem, frontend",
    ]
    if scenario == "planner-fail":
        lines.extend(
            [
                "",
                "[WARN] 主控先规划失败，回退到内置分工。",
                f"[ERR] 请求主控计划失败: {CTX['planner_error']}",
                "[DIM] 主控提示词文档已写入: /Users/skyhua/ai-collab/.ai-collab/prompts/20260307-194105-codex-controller-prompt.md",
                "[DIM] 简报文件已写入: /Users/skyhua/ai-collab/.ai-collab/briefings/20260307-194109-codex-controller.txt",
                "[DIM] run_id: 20260307T114118Z-50e691a3",
                f"[OK] tmux 协作会话已就绪: {CTX['session']}",
                "[DIM] 窗格日志: /Users/skyhua/ai-collab/.ai-collab/logs/ai-collab-live",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "[OK] 主控计划成功。",
                "[DIM] 主控提示词文档已写入: ...",
                "[DIM] 简报文件已写入: ...",
                f"[OK] tmux 协作会话已就绪: {CTX['session']}",
                f"[DIM] S1 pane: {CTX['gemini_pane']}",
                f"[DIM] S2 window/pane: {CTX['claude_window']} / {CTX['claude_pane']}",
                "[WARN] 子控完成后，请根据提醒决定是否关闭 pane 或 window。",
            ]
        )
    return lines


def strict_param(scenario: str) -> list[str]:
    lines = [
        "[TITLE] 方案: strict-param",
        "[DIM] 参数模式只显示硬状态，不显示 detector 摘要。",
        "",
        "[STEP] PLAN_START controller=codex mode=tmux",
    ]
    if scenario == "planner-fail":
        lines.extend(
            [
                f"[ERR] PLAN_FAILED reason={CTX['planner_error']}",
                "[ERR] EXIT planner_required no_builtin_fallback",
            ]
        )
        return lines
    lines.extend(
        [
            "[OK] PLAN_OK steps=S1:gemini-pane,S2:claude-window",
            f"[STEP] TMUX_START session={CTX['session']}",
            f"[OK] TMUX_READY session={CTX['session']} controller_pane={CTX['controller_pane']}",
            f"[STEP] S1_SPAWN agent=gemini pane={CTX['gemini_pane']}",
            f"[OK] S1_DONE pane={CTX['gemini_pane']}",
            f"[WARN] ASK_CLOSE agent=gemini target=pane:{CTX['gemini_pane']}",
            f"[STEP] S2_SPAWN agent=claude window={CTX['claude_window']} pane={CTX['claude_pane']}",
            f"[OK] S2_DONE window={CTX['claude_window']} pane={CTX['claude_pane']}",
            f"[WARN] ASK_CLOSE agent=claude target=window:{CTX['claude_window']} pane:{CTX['claude_pane']}",
            "[OK] TASK_COMPLETE",
        ]
    )
    return lines


def compact_operator(scenario: str) -> list[str]:
    lines = [
        "[TITLE] 方案: compact-operator",
        "[DIM] 默认用户模式。给一个小概要卡片，然后只报当前动作。",
        "",
        "任务: codex 主控 tmux 编排测试",
        "计划: S1 gemini pane -> S2 claude window",
        "策略: planner 必须成功 | 禁止隐式 fallback | 完成后询问关闭还是保留",
        "",
        "[STEP] 当前: 正在由 codex 生成主控计划",
    ]
    if scenario == "planner-fail":
        lines.extend(
            [
                f"[ERR] 规划失败: {CTX['planner_error']}",
                "[WARN] 本次没有进入 tmux，也没有启动任何子控。",
                "[DIM] 如需更多信息，请使用 --verbose 或查看 planner 诊断。",
            ]
        )
        return lines
    lines.extend(
        [
            "[OK] 当前: 计划已生成",
            f"[STEP] 当前: 正在进入 tmux 会话 {CTX['session']}",
            f"[OK] 当前: 已进入 tmux，会话 {CTX['session']} 已就绪",
            f"[STEP] 当前: 正在执行 S1，启动 gemini pane {CTX['gemini_pane']}",
            f"[OK] 当前: S1 完成，gemini pane {CTX['gemini_pane']} 已返回任务完成",
            f"[WARN] 需要你的决定: 关闭还是保留 gemini pane {CTX['gemini_pane']}？",
            f"[STEP] 当前: 正在执行 S2，启动 claude window {CTX['claude_window']}",
            f"[OK] 当前: S2 完成，claude window {CTX['claude_window']} / pane {CTX['claude_pane']} 已返回任务完成",
            f"[WARN] 需要你的决定: 关闭还是保留 claude window {CTX['claude_window']}？",
            "[OK] 当前: 全部流程结束",
        ]
    )
    return lines


def timeline_focused(scenario: str) -> list[str]:
    lines = [
        "[TITLE] 方案: timeline-focused",
        "[DIM] 适合在 iTerm2 外部窗口长期观察，强调卡点和阶段。",
        "",
        "01 Planning controller plan ............ running",
    ]
    if scenario == "planner-fail":
        lines.extend(
            [
                f"01 Planning controller plan ............ failed",
                f"   reason: {CTX['planner_error']}",
                "02 Enter tmux session ................... skipped",
                "03 S1 gemini pane ....................... skipped",
                "04 S2 claude window ..................... skipped",
                "[ERR] 停止于 Planning。没有自动 fallback。",
            ]
        )
        return lines
    lines.extend(
        [
            "01 Planning controller plan ............ done",
            f"02 Enter tmux session ................... done ({CTX['session']})",
            f"03 S1 gemini pane ....................... done ({CTX['gemini_pane']})",
            f"04 User close/keep choice for S1 ........ waiting ({CTX['gemini_pane']})",
            f"05 S2 claude window ..................... done ({CTX['claude_window']} / {CTX['claude_pane']})",
            f"06 User close/keep choice for S2 ........ waiting ({CTX['claude_window']})",
            "07 End .................................. done",
        ]
    )
    return lines


def two_stage_gate(scenario: str) -> list[str]:
    lines = [
        "[TITLE] 方案: two-stage-gate",
        "[DIM] 最严格的 controller-first。没过 Plan 就绝不进入 Execute。",
        "",
        "[STEP] Stage 1 / Plan",
        "  controller: codex",
        "  target: S1 gemini pane + S2 claude window",
        "  policy: planner_required, no_implicit_fallback",
    ]
    if scenario == "planner-fail":
        lines.extend(
            [
                f"[ERR]   result: failed ({CTX['planner_error']})",
                "[ERR] Stage 2 / Execute was not started.",
            ]
        )
        return lines
    lines.extend(
        [
            "[OK]   result: approved",
            "",
            "[STEP] Stage 2 / Execute",
            f"[OK]   tmux session ready: {CTX['session']}",
            f"[OK]   S1 ready: gemini pane {CTX['gemini_pane']}",
            f"[WARN]   user decision required: close or keep pane {CTX['gemini_pane']}",
            f"[OK]   S2 ready: claude window {CTX['claude_window']} pane {CTX['claude_pane']}",
            f"[WARN]   user decision required: close or keep window {CTX['claude_window']}",
            "[OK]   orchestration finished",
        ]
    )
    return lines


RENDERERS = {
    "baseline-current": baseline_current,
    "strict-param": strict_param,
    "compact-operator": compact_operator,
    "timeline-focused": timeline_focused,
    "two-stage-gate": two_stage_gate,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview ai-collab UX flow schemes.")
    parser.add_argument("--scheme", choices=SCHEMES, help="Preview a single scheme")
    parser.add_argument("--scenario", choices=SCENARIOS, default="success", help="Scenario to render")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between lines for live preview")
    parser.add_argument("--all", action="store_true", help="Render all schemes")
    parser.add_argument("--list", action="store_true", help="List schemes and exit")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list:
        print("Schemes:")
        for item in SCHEMES:
            print(f"  - {item}")
        print("")
        print("Scenarios:")
        for item in SCENARIOS:
            print(f"  - {item}")
        return 0

    targets = SCHEMES if args.all else [args.scheme or "compact-operator"]
    for index, scheme in enumerate(targets):
        if index:
            print("\n" + "=" * 72 + "\n")
        emit(RENDERERS[scheme](args.scenario), delay=max(0.0, args.delay), use_color=not args.no_color)
    return 0


if __name__ == "__main__":
    sys.exit(main())
