"""Thin step-by-step launch flow aligned with entry/init/config."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from io import StringIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Optional

import click
from rich.cells import cell_len
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from ai_collab.core.config import Config
from ai_collab.core.selector import ModelSelector
from ai_collab.init_prompt import PROVIDER_THEME, build_init_banner
from ai_collab.plan_editor_prompt import (
    ExecutionTargetOption,
    PlanDraft,
    apply_plan_draft_to_result,
    build_execution_targets,
    delete_step,
    insert_step_after,
    move_step,
    plan_draft_from_result,
    rename_task,
    update_step,
)
from ai_collab.tui.launcher_service import run_launcher_flow
from ai_collab.tui.setup import CONTROLLER_LABELS
from ai_collab.ux_lab_v3 import UxLabV3Result, export_launch_bundle_v3

TextInputFn = Callable[..., str]
SelectFn = Callable[..., str]
SUPPORTED_LANGS = {"en-US", "zh-CN"}
TASK_COMMAND_ORDER = ("/nano", "/vim", "/done", "/back", "/home", "/quit")
TASK_COMMANDS = set(TASK_COMMAND_ORDER)

TEXT = {
    "en-US": {
        "step_workspace_label": "Workspace",
        "step_task_label": "Task draft",
        "step_controller_label": "Controller",
        "step_planner_label": "Planning",
        "step_review_label": "Confirm",
        "task_step_title": "Task draft",
        "task_step_hint": "Write the task directly here. To open command help, start a new line with /.",
        "task_workspace_note": "Workspace · {workspace}",
        "task_editor_title": "Current draft",
        "task_editor_placeholder": "No task yet. Type here directly, or use /nano or /vim.",
        "task_commands": "Start a new line with / for commands · Tab complete · /nano · /vim · /done · /back · /home · /quit",
        "task_prompt": "Task draft",
        "task_editor_loaded": "Loaded editor content back into the task draft.",
        "task_editor_missing": "{editor} is not available in PATH.",
        "task_editor_failed": "Failed to open {editor}: {error}",
        "controller_step_title": "Controller",
        "controller_step_hint": "Pick who leads planning and orchestration for this run.",
        "controller_note": "Task · {task}",
        "controller_codex_desc": "Best for end-to-end implementation, refactors, testing, and parallel agent work.",
        "controller_claude_desc": "Best for repository understanding, editing, debugging, and workflow automation.",
        "controller_gemini_desc": "Best for large context, multimodal input, search-heavy research, and terminal automation.",
        "planner_step_title": "Planning mode",
        "planner_step_hint": "Choose whether this run plans through the real controller or the mock planner.",
        "planner_live": "Live",
        "planner_live_desc": "Generate a fresh plan through the real controller for this task.",
        "planner_mock": "Mock",
        "planner_mock_desc": "Use the bundled demo planner for rehearsal or UI validation.",
        "review_step_title": "Confirm and generate",
        "review_step_hint": "Check the draft summary, then generate the orchestration plan.",
        "review_generate": "Generate plan",
        "review_generate_desc": "Run the planner with the current draft.",
        "plan_review_title": "Plan review",
        "plan_review_hint": "Review the result, adjust orchestration, or start the task.",
        "plan_review_source_live": "Live controller JSON",
        "plan_review_source_mock": "Bundled mock plan",
        "plan_review_mode_multi": "Multi-agent",
        "plan_review_mode_single": "Controller-only",
        "plan_review_approval": "Approval question",
        "plan_review_agents": "Agent routing",
        "plan_review_steps": "Planned steps",
        "plan_review_model_unknown": "model not specified",
        "plan_review_panel_title": "Plan Content",
        "plan_review_scroll_hint": "↑/↓ or mouse wheel scroll · PgUp/PgDn page · Home/End top/bottom",
        "plan_review_scroll_status": "Plan content · lines {start}-{end} / {total}",
        "plan_review_actions_label": "Actions",
        "plan_review_action_start": "Enter start",
        "plan_review_action_edit": "E edit",
        "plan_review_action_save": "S save bundle",
        "plan_review_action_back": "B back",
        "plan_review_action_home": "H home",
        "plan_review_action_quit": "Q quit",
        "planning_error_title": "Planning failed",
        "planning_error_hint": "The controller did not return a usable JSON plan yet.",
        "planning_error_back": "Back to planning options",
        "planning_error_back_desc": "Change controller or planning mode, then try again.",
        "planning_progress_title": "Generating plan",
        "planning_progress_hint": "Asking the controller for structured JSON and mapping it into ai-collab steps.",
        "planning_progress_prompt": "Prompt preview",
        "planning_progress_stage": "Current stage",
        "planning_progress_controller": "Controller",
        "planning_progress_mode": "Mode",
        "planning_progress_elapsed": "Elapsed",
        "planning_progress_wait": "Waiting for controller JSON",
        "planning_stage_prompt_ready": "Prompt prepared",
        "planning_stage_command_started": "Prompt sent",
        "planning_stage_json_received": "Structured JSON received",
        "planning_stage_steps_mapped": "Mapped into launcher steps",
        "planning_stage_request_failed": "Controller request failed",
        "planning_stage_cancel_requested": "Cancel requested",
        "planning_progress_cancel_hint": "Planning usually takes 1–2 minutes. If it still looks stuck after that, press Ctrl-C to cancel.",
        "planning_progress_cancelling": "Stopping controller request…",
        "plan_review_start": "Start task",
        "plan_review_start_desc": "Use the current orchestration and continue into execution.",
        "plan_review_edit": "Adjust orchestration",
        "plan_review_edit_desc": "Edit steps, agent assignment, and task wording without touching raw JSON.",
        "plan_review_save": "Save startup bundle only",
        "plan_review_save_desc": "Only write the startup bundle to disk for later use.",
        "plan_review_back": "Back to confirm",
        "plan_review_back_desc": "Return to the previous confirmation step without exporting.",
        "plan_edit_title": "Adjust orchestration",
        "plan_edit_hint": "Reorder, insert, delete, or refine steps before execution.",
        "plan_edit_task": "Task wording",
        "plan_edit_task_desc": "Rename the overall task shown to the controller and in summaries.",
        "plan_edit_add": "Add step",
        "plan_edit_add_desc": "Insert one more orchestration step.",
        "plan_edit_step": "Edit step",
        "plan_edit_step_desc": "Change title, owner, ETA, or remove an existing step.",
        "plan_edit_done": "Done editing",
        "plan_edit_done_desc": "Return to the plan preview with the updated draft.",
        "plan_edit_pick_step": "Choose a step to edit.",
        "plan_edit_step_title": "Step title",
        "plan_edit_step_title_desc": "Rename what this step is trying to accomplish.",
        "plan_edit_step_owner": "Assigned agent",
        "plan_edit_step_owner_desc": "Move this step to another agent.",
        "plan_edit_step_eta": "Estimated time",
        "plan_edit_step_eta_desc": "Change the ETA in minutes.",
        "plan_edit_step_done_when": "Done condition",
        "plan_edit_step_done_when_desc": "Rewrite how this step is verified.",
        "plan_edit_step_delete": "Delete step",
        "plan_edit_step_delete_desc": "Remove this step from the orchestration.",
        "plan_edit_saved": "Updated orchestration draft.",
        "plan_edit_status_saved": "Draft updated. Return to preview when you're ready.",
        "plan_edit_status_delete_blocked": "At least one step must remain in the draft.",
        "plan_edit_status_inserted": "Inserted a new step after the current one.",
        "plan_edit_status_deleted": "Removed the selected step.",
        "plan_edit_status_moved": "Reordered the selected step.",
        "plan_edit_list_title": "Orchestration editor",
        "plan_edit_list_hint": "Model routing, prompt wording, and step ownership stay visible while you reshape the plan.",
        "plan_edit_summary_task": "Task",
        "plan_edit_summary_controller": "Controller",
        "plan_edit_summary_steps": "Steps",
        "plan_edit_summary_mode": "Routing",
        "plan_edit_summary_models": "Models",
        "plan_edit_prompt_panel": "Prompt / Task Input",
        "plan_edit_routes_panel": "Model Routing",
        "plan_edit_steps_window": "Showing steps {start}-{end} / {total}",
        "plan_edit_compact_routes": "Routes",
        "plan_edit_multi_agent": "Multi-agent",
        "plan_edit_single_agent": "Controller-only",
        "plan_edit_current_step": "Current step",
        "plan_edit_step_owner_short": "Agent",
        "plan_edit_step_model_short": "Model",
        "plan_edit_step_eta_short": "ETA",
        "plan_edit_step_done_short": "Done when",
        "plan_edit_shortcuts": "↑/↓ select · Enter edit · a insert · d delete · J/K move · t task · s/b/Esc back to preview · q discard",
        "plan_edit_form_step_title": "Edit step · {step_id}",
        "plan_edit_form_insert_title": "Insert step · after {step_id}",
        "plan_edit_form_task_title": "Rename task",
        "plan_edit_form_step_hint": "Edit the fields directly. Use Tab to switch fields, ↑/↓ to pick the agent, Ctrl+S to save, and Esc to cancel.",
        "plan_edit_form_task_hint": "Edit the task text directly, then save to return to the orchestration list.",
        "plan_edit_form_field_preview": "Current values",
        "plan_edit_form_eta_invalid": "ETA must be a whole number of minutes before you can save.",
        "plan_edit_form_footer": "Tab switch field · ↑/↓ choose agent · Ctrl+S save · Esc cancel",
        "plan_edit_discarded": "Discarded orchestration edits and returned to preview.",
        "execution_title": "Execution target",
        "execution_hint": "Pick how to continue this approved orchestration.",
        "execution_note": "direct runtime keeps execution in the current terminal: controller-only plans run as one agent, while multi-agent plans run sequentially without tmux panes.",
        "execution_error_title": "Start failed",
        "execution_direct": "direct runtime",
        "execution_save": "Save startup bundle only",
        "execution_tmux": "tmux runtime",
        "execution_result_saved_title": "Startup bundle saved",
        "execution_result_saved_hint": "The orchestration is saved and can be started later.",
        "execution_result_started_title": "Task started",
        "execution_result_started_hint": "The approved orchestration has been handed off to the runtime target.",
        "execution_result_path": "Startup bundle path",
        "execution_result_runtime": "Execution target",
        "plan_start_tmux": "Start with tmux runtime",
        "plan_start_tmux_desc": "Launch the approved multi-agent plan in tmux now.",
        "plan_start_bundle": "Save startup bundle only",
        "plan_start_bundle_desc": "Do not run it now; only save the launch bundle.",
        "plan_start_not_ready": "Current runtime is not ready for direct start yet, so only saving the startup bundle is available.",
        "nav_back": "Back",
        "nav_back_desc": "Return to the previous step in this flow.",
        "nav_home": "Home",
        "nav_home_desc": "Leave this flow and return to the ai-collab home screen.",
        "quit": "Quit",
        "quit_desc": "Exit this flow without generating anything.",
        "summary_workspace": "Workspace",
        "summary_task": "Task",
        "summary_controller": "Controller",
        "summary_planner": "Planning mode",
        "empty_task": "Not set",
        "task_required": "Task is required before you can continue.",
        "sent_title": "Bundle ready",
        "sent_hint": "Launch bundle exported from the thin terminal flow.",
        "sent_path": "Bundle path",
        "sent_controller": "Controller",
        "sent_task": "Task",
        "footer": "↑/↓ move · Enter confirm · b back · h home · q quit · Esc cancel",
        "footer_basic": "↑/↓ move · Enter confirm · q quit · Esc cancel",
    },
    "zh-CN": {
        "step_workspace_label": "工作区",
        "step_task_label": "任务草稿",
        "step_controller_label": "主控",
        "step_planner_label": "规划模式",
        "step_review_label": "确认并生成",
        "task_step_title": "任务草稿",
        "task_step_hint": "直接输入任务草稿；如需命令，请新起一行输入 /。",
        "task_workspace_note": "工作区 · {workspace}",
        "task_editor_title": "当前草稿",
        "task_editor_placeholder": "还没有任务内容。可以直接输入，或使用 /nano、/vim 打开外部编辑器。",
        "task_commands": "新起一行输入 / 查看命令 · Tab 补全 · /nano · /vim · /done · /back · /home · /quit",
        "task_prompt": "任务草稿",
        "task_editor_loaded": "已把外部编辑器内容载回当前草稿。",
        "task_editor_missing": "PATH 中没有找到 {editor}。",
        "task_editor_failed": "打开 {editor} 失败：{error}",
        "controller_step_title": "主控",
        "controller_step_hint": "选择本次任务由谁负责规划与编排。",
        "controller_note": "任务 · {task}",
        "controller_codex_desc": "适合端到端工程执行、重构、测试与并行 Agent 工作流。",
        "controller_claude_desc": "适合代码库理解、编辑、调试与工作流自动化。",
        "controller_gemini_desc": "适合大上下文、多模态输入、搜索调研与终端自动化。",
        "planner_step_title": "规划模式",
        "planner_step_hint": "决定本次生成计划时使用真实主控还是演示规划。",
        "planner_live": "实时规划",
        "planner_live_desc": "调用真实主控为当前任务生成一份新计划。",
        "planner_mock": "演示规划",
        "planner_mock_desc": "使用内置演示规划，适合验证流程、录屏或界面预演。",
        "review_step_title": "确认并生成",
        "review_step_hint": "检查本次草稿摘要，然后生成多 Agent 计划。",
        "review_generate": "生成计划",
        "review_generate_desc": "按当前草稿调用规划器。",
        "plan_review_title": "计划预览",
        "plan_review_hint": "查看结果、调整编排或开始任务。",
        "plan_review_source_live": "真实主控 JSON",
        "plan_review_source_mock": "内置演示计划",
        "plan_review_mode_multi": "多 Agent",
        "plan_review_mode_single": "仅主控",
        "plan_review_approval": "确认问题",
        "plan_review_agents": "Agent 路由",
        "plan_review_steps": "计划步骤",
        "plan_review_model_unknown": "未声明模型",
        "plan_review_panel_title": "计划内容",
        "plan_review_scroll_hint": "↑/↓ 或滚轮滚动 · PgUp/PgDn 翻页 · Home/End 顶部/底部",
        "plan_review_scroll_status": "计划内容 · 第 {start}-{end} 行 / 共 {total} 行",
        "plan_review_actions_label": "操作",
        "plan_review_action_start": "Enter 开始任务",
        "plan_review_action_edit": "E 调整编排",
        "plan_review_action_save": "S 保存启动包",
        "plan_review_action_back": "B 返回",
        "plan_review_action_home": "H 主菜单",
        "plan_review_action_quit": "Q 退出",
        "planning_error_title": "规划失败",
        "planning_error_hint": "主控暂时没有返回可用的 JSON 计划。",
        "planning_error_back": "返回规划设置",
        "planning_error_back_desc": "改一下主控或规划模式后再试一次。",
        "planning_progress_title": "正在生成计划",
        "planning_progress_hint": "正在请求主控返回结构化 JSON，并映射成 ai-collab 可执行步骤。",
        "planning_progress_prompt": "发送给主控的 prompt",
        "planning_progress_stage": "当前阶段",
        "planning_progress_controller": "主控",
        "planning_progress_mode": "模式",
        "planning_progress_elapsed": "已耗时",
        "planning_progress_wait": "等待主控返回 JSON",
        "planning_stage_prompt_ready": "已整理 prompt",
        "planning_stage_command_started": "已发送 prompt",
        "planning_stage_json_received": "已收到结构化 JSON",
        "planning_stage_steps_mapped": "已映射成启动步骤",
        "planning_stage_request_failed": "主控请求失败",
        "planning_stage_cancel_requested": "已请求取消",
        "planning_progress_cancel_hint": "规划通常需要 1–2 分钟；如果这之后仍明显卡住，可按 Ctrl-C 手动取消。",
        "planning_progress_cancelling": "正在停止主控请求…",
        "plan_review_start": "开始任务",
        "plan_review_start_desc": "使用当前编排继续进入执行阶段。",
        "plan_review_edit": "调整编排",
        "plan_review_edit_desc": "用操作式方式修改步骤、分配 Agent 和任务表述，不直接改原始 JSON。",
        "plan_review_save": "仅保存启动包",
        "plan_review_save_desc": "只写入启动 bundle，稍后再执行。",
        "plan_review_back": "返回确认页",
        "plan_review_back_desc": "不导出，回到上一页确认步骤。",
        "plan_edit_title": "调整编排",
        "plan_edit_hint": "在开始前直接调整步骤顺序、Agent 分配与任务表述。",
        "plan_edit_task": "任务名称",
        "plan_edit_task_desc": "修改整体任务名称与摘要显示。",
        "plan_edit_add": "添加步骤",
        "plan_edit_add_desc": "在当前编排里补充一个新步骤。",
        "plan_edit_step": "编辑步骤",
        "plan_edit_step_desc": "修改步骤标题、Agent、预计耗时，或删除步骤。",
        "plan_edit_done": "完成调整",
        "plan_edit_done_desc": "带着更新后的编排返回计划预览。",
        "plan_edit_pick_step": "选择一个步骤进行调整。",
        "plan_edit_step_title": "步骤标题",
        "plan_edit_step_title_desc": "修改这一步的目标标题。",
        "plan_edit_step_owner": "分配 Agent",
        "plan_edit_step_owner_desc": "把这一步交给别的 Agent。",
        "plan_edit_step_eta": "预计耗时",
        "plan_edit_step_eta_desc": "修改预计耗时（分钟）。",
        "plan_edit_step_done_when": "完成条件",
        "plan_edit_step_done_when_desc": "重写这一步的验收条件。",
        "plan_edit_step_delete": "删除步骤",
        "plan_edit_step_delete_desc": "从编排中移除这一步。",
        "plan_edit_saved": "编排草稿已更新。",
        "plan_edit_status_saved": "编排草稿已更新，可随时返回预览继续。",
        "plan_edit_status_delete_blocked": "至少要保留 1 个步骤，不能删空。",
        "plan_edit_status_inserted": "已在当前步骤后插入新步骤。",
        "plan_edit_status_deleted": "已删除当前步骤。",
        "plan_edit_status_moved": "已调整当前步骤顺序。",
        "plan_edit_list_title": "编排编辑器",
        "plan_edit_list_hint": "重排计划时持续显示模型路由、Prompt 文案与步骤归属。",
        "plan_edit_summary_task": "任务",
        "plan_edit_summary_controller": "主控",
        "plan_edit_summary_steps": "步骤数",
        "plan_edit_summary_mode": "编排模式",
        "plan_edit_summary_models": "模型数",
        "plan_edit_prompt_panel": "Prompt / 任务输入",
        "plan_edit_routes_panel": "模型路由",
        "plan_edit_steps_window": "显示步骤 {start}-{end} / {total}",
        "plan_edit_compact_routes": "路由",
        "plan_edit_multi_agent": "多 Agent",
        "plan_edit_single_agent": "仅主控",
        "plan_edit_current_step": "当前步骤",
        "plan_edit_step_owner_short": "Agent",
        "plan_edit_step_model_short": "模型",
        "plan_edit_step_eta_short": "ETA",
        "plan_edit_step_done_short": "完成条件",
        "plan_edit_shortcuts": "↑/↓ 选步骤 · Enter 编辑 · a 插入 · d 删除 · J/K 下移/上移 · t 改任务名 · s/b/Esc 返回预览 · q 放弃修改",
        "plan_edit_form_step_title": "编辑步骤 · {step_id}",
        "plan_edit_form_insert_title": "插入新步骤 · 接在 {step_id} 后",
        "plan_edit_form_task_title": "修改任务名称",
        "plan_edit_form_step_hint": "直接在表单里修改内容；Tab 切换字段，↑/↓ 选择 Agent，Ctrl+S 保存，Esc 取消。",
        "plan_edit_form_task_hint": "直接在输入框里修改任务名称；保存后会回到步骤列表。",
        "plan_edit_form_field_preview": "当前内容",
        "plan_edit_form_eta_invalid": "预计耗时需要填写整数分钟后才能保存。",
        "plan_edit_form_footer": "Tab 切换字段 · ↑/↓ 选择 Agent · Ctrl+S 保存 · Esc 取消",
        "plan_edit_discarded": "已放弃本次编排修改，返回计划预览。",
        "execution_title": "执行方式",
        "execution_hint": "选择这份已确认编排接下来如何执行。",
        "execution_note": "直接执行会留在当前终端执行：单 Agent 计划直接运行，多 Agent 计划按步骤顺序执行且不创建 tmux 窗格。",
        "execution_error_title": "启动失败",
        "execution_direct": "直接执行",
        "execution_save": "仅保存启动包",
        "execution_tmux": "tmux runtime",
        "execution_result_saved_title": "启动包已保存",
        "execution_result_saved_hint": "这份编排已写入启动包，可稍后再执行。",
        "execution_result_started_title": "任务已启动",
        "execution_result_started_hint": "已把当前编排交给执行目标继续运行。",
        "execution_result_path": "启动包路径",
        "execution_result_runtime": "执行方式",
        "plan_start_tmux": "使用 tmux 立即开始",
        "plan_start_tmux_desc": "现在就用 tmux 拉起批准后的多 Agent 计划。",
        "plan_start_bundle": "仅保存启动包",
        "plan_start_bundle_desc": "暂不执行，只写入启动 bundle。",
        "plan_start_not_ready": "当前运行方式还不适合直接开始任务，所以这里只提供保存启动包。",
        "nav_back": "返回上一步",
        "nav_back_desc": "回到当前流程中的上一步。",
        "nav_home": "返回主菜单",
        "nav_home_desc": "离开本次新任务流程，回到 ai-collab 首页。",
        "quit": "退出",
        "quit_desc": "不生成任何内容，直接退出当前流程。",
        "summary_workspace": "工作区",
        "summary_task": "任务",
        "summary_controller": "主控",
        "summary_planner": "规划模式",
        "empty_task": "未填写",
        "task_required": "请先填写任务内容，再进入下一步。",
        "sent_title": "Bundle 已生成",
        "sent_hint": "已保存启动包，可稍后继续执行。",
        "sent_path": "Bundle 路径",
        "sent_controller": "主控",
        "sent_task": "任务",
        "footer": "↑/↓ 移动 · Enter 确认 · b 返回 · h 主菜单 · q 退出 · Esc 取消",
        "footer_basic": "↑/↓ 移动 · Enter 确认 · q 退出 · Esc 取消",
    },
}


@dataclass
class LaunchPromptState:
    config: Config
    cwd: Path
    workspace: Path
    controller: str
    task: str
    planner_mode: str
    output_bundle: Optional[Path]
    from_entry: bool = False
    status_message: str = ""

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        cwd: Path,
        workspace: Optional[Path] = None,
        controller: Optional[str] = None,
        task: Optional[str] = None,
        planner_mode: str = "live",
        output_bundle: Optional[Path] = None,
        from_entry: bool = False,
    ) -> "LaunchPromptState":
        resolved_workspace = Path(workspace or cwd).expanduser().resolve()
        resolved_controller = str(controller or getattr(config, "current_controller", "codex") or "codex")
        if resolved_controller not in {"codex", "claude", "gemini"}:
            resolved_controller = "codex"
        resolved_mode = planner_mode if planner_mode in {"live", "mock"} else "live"
        return cls(
            config=config,
            cwd=Path(cwd).expanduser().resolve(),
            workspace=resolved_workspace,
            controller=resolved_controller,
            task=str(task or "").strip(),
            planner_mode=resolved_mode,
            output_bundle=output_bundle.expanduser().resolve() if output_bundle else None,
            from_entry=from_entry,
        )


@dataclass(frozen=True)
class MenuItem:
    value: str
    label: str
    description: str
    provider: str | None = None


@dataclass(frozen=True)
class LaunchRow:
    value: str
    prefix: str
    label: str
    label_style: str
    description: str = ""
    description_style: str = "#64748B italic"


@dataclass
class PlanningProgressState:
    stage: str = "prompt_ready"
    prompt_text: str = ""
    step_count: int = 0
    started_at: float = 0.0
    cancelling: bool = False


STEP_ORDER = {"task": 2, "controller": 3, "planner": 4, "review": 5}
TOTAL_STEPS = 5


def _lang(config: Config) -> str:
    candidate = getattr(config, "ui_language", "en-US")
    return candidate if candidate in SUPPORTED_LANGS else "en-US"



def _copy(config: Config) -> dict[str, str]:
    return TEXT[_lang(config)]


def _task_command_specs(state: LaunchPromptState) -> list[tuple[str, str]]:
    if _lang(state.config) == "zh-CN":
        specs = [
            ("/nano", "打开 nano 编辑当前草稿"),
            ("/vim", "打开 vim 编辑当前草稿"),
            ("/done", "确认草稿并进入下一步"),
            ("/back", "返回上一步"),
            ("/home", "回到主菜单"),
            ("/quit", "退出当前流程"),
        ]
    else:
        specs = [
            ("/nano", "Open nano for the current draft"),
            ("/vim", "Open vim for the current draft"),
            ("/done", "Accept the draft and continue"),
            ("/back", "Go back one step"),
            ("/home", "Return to home"),
            ("/quit", "Quit this flow"),
        ]
    if state.from_entry:
        return specs
    return [item for item in specs if item[0] != "/home"]



def _matching_task_commands(state: LaunchPromptState, query: str) -> list[tuple[str, str]]:
    normalized = str(query or "").strip().lower()
    if not normalized.startswith("/"):
        return []
    return [item for item in _task_command_specs(state) if item[0].startswith(normalized)]



def _task_toolbar_message(state: LaunchPromptState, query: str = "") -> str:
    copy = _copy(state.config)
    matches = _matching_task_commands(state, query)
    if not matches:
        return copy["task_commands"]
    return "   ".join(f"{command} {description}" for command, description in matches)



def _task_summary(state: LaunchPromptState) -> str:
    copy = _copy(state.config)
    if not state.task.strip():
        return copy["empty_task"]
    first_line = state.task.splitlines()[0].strip()
    return first_line if len(first_line) <= 60 else first_line[:57] + "..."



def _task_preview(state: LaunchPromptState) -> str:
    copy = _copy(state.config)
    if not state.task.strip():
        return copy["task_editor_placeholder"]
    lines = state.task.strip().splitlines()
    preview = "\n".join(lines[:10]).strip()
    if len(lines) > 10 or len(preview) > 700:
        preview = preview[:700].rstrip() + "\n..."
    return preview



def _controller_label(state: LaunchPromptState) -> str:
    return str(CONTROLLER_LABELS.get(state.controller, state.controller))



def _planner_label(state: LaunchPromptState) -> str:
    copy = _copy(state.config)
    return copy["planner_live"] if state.planner_mode == "live" else copy["planner_mock"]



def _step_title(state: LaunchPromptState, step: str) -> str:
    copy = _copy(state.config)
    title = copy[f"{step}_step_title"]
    current = STEP_ORDER[step]
    return f"Step {current}/{TOTAL_STEPS} · {title}" if _lang(state.config) == "en-US" else f"步骤 {current}/{TOTAL_STEPS} · {title}"



def _step_cells(config: Config) -> list[str]:
    if _lang(config) == "en-US":
        return ["Workspace", "Task", "Controller", "Plan", "Confirm"]
    return ["工作区", "草稿", "主控", "规划", "确认"]



def _step_indicator(state: LaunchPromptState, step: str) -> Text:
    current = STEP_ORDER[step]
    text = Text()
    for index, label in enumerate(_step_cells(state.config), start=1):
        if index < current:
            text.append(f" ✓ {index} {label} ", style="bold #7DD3FC")
        elif index == current:
            text.append(f" ● {index} {label} ", style="bold #0F172A on #7DD3FC")
        else:
            text.append(f" ○ {index} {label} ", style="#64748B")
        if index < TOTAL_STEPS:
            text.append("─", style="#334155")
    return text



def _row_label_style(*, is_pointed: bool, is_default: bool, provider: str | None = None) -> str:
    if is_pointed:
        color = PROVIDER_THEME.get(provider, "#7DD3FC")
        return f"{color} bold underline"
    if is_default:
        return "#F8FAFC bold"
    return "#CBD5E1"


def _accent_provider(state: LaunchPromptState) -> str:
    return state.controller if state.controller in PROVIDER_THEME else "codex"


def _accent_color(state: LaunchPromptState) -> str:
    return str(PROVIDER_THEME.get(_accent_provider(state), "#7DD3FC"))


def _build_rows(
    items: list[MenuItem],
    *,
    pointed_value: str,
    default_value: str,
    accent_provider: str | None = None,
) -> list[LaunchRow]:
    rows: list[LaunchRow] = []
    for item in items:
        rows.append(
            LaunchRow(
                value=item.value,
                prefix="> " if item.value == pointed_value else "  ",
                label=item.label,
                label_style=_row_label_style(
                    is_pointed=item.value == pointed_value,
                    is_default=item.value == default_value,
                    provider=item.provider or accent_provider,
                ),
                description=item.description,
            )
        )
    return rows



def _row_text(row: LaunchRow) -> Text:
    value_prefix = f"{row.value}. " if str(row.value).strip() else ""
    return Text.assemble((row.prefix, ""), (value_prefix, "#64748B"), (row.label, row.label_style))



def _controller_rows(state: LaunchPromptState, *, pointed_value: str | None = None, include_nav: bool = True) -> list[LaunchRow]:
    copy = _copy(state.config)
    default_value = {"codex": "1", "claude": "2", "gemini": "3"}.get(state.controller, "1")
    items = [
        MenuItem("1", str(CONTROLLER_LABELS["codex"]), copy["controller_codex_desc"], provider="codex"),
        MenuItem("2", str(CONTROLLER_LABELS["claude"]), copy["controller_claude_desc"], provider="claude"),
        MenuItem("3", str(CONTROLLER_LABELS["gemini"]), copy["controller_gemini_desc"], provider="gemini"),
    ]
    if include_nav and state.from_entry:
        items.append(MenuItem("b", copy["nav_back"], copy["nav_back_desc"]))
        items.append(MenuItem("h", copy["nav_home"], copy["nav_home_desc"]))
    if include_nav:
        items.append(MenuItem("q", copy["quit"], copy["quit_desc"]))
    return _build_rows(items, pointed_value=pointed_value or default_value, default_value=default_value)



def _build_controller_rows(state: LaunchPromptState, *, pointed_value: str | None = None) -> list[LaunchRow]:
    return _controller_rows(state, pointed_value=pointed_value, include_nav=True)



def _planner_rows(state: LaunchPromptState, *, pointed_value: str | None = None) -> list[LaunchRow]:
    copy = _copy(state.config)
    default_value = "2" if state.planner_mode == "mock" else "1"
    items = [
        MenuItem("1", copy["planner_live"], copy["planner_live_desc"]),
        MenuItem("2", copy["planner_mock"], copy["planner_mock_desc"]),
    ]
    if state.from_entry:
        items.append(MenuItem("b", copy["nav_back"], copy["nav_back_desc"]))
        items.append(MenuItem("h", copy["nav_home"], copy["nav_home_desc"]))
    items.append(MenuItem("q", copy["quit"], copy["quit_desc"]))
    return _build_rows(
        items,
        pointed_value=pointed_value or default_value,
        default_value=default_value,
        accent_provider=_accent_provider(state),
    )



def _review_rows(state: LaunchPromptState, *, pointed_value: str = "1") -> list[LaunchRow]:
    copy = _copy(state.config)
    items = [MenuItem("1", copy["review_generate"], copy["review_generate_desc"])]
    if state.from_entry:
        items.append(MenuItem("b", copy["nav_back"], copy["nav_back_desc"]))
        items.append(MenuItem("h", copy["nav_home"], copy["nav_home_desc"]))
    items.append(MenuItem("q", copy["quit"], copy["quit_desc"]))
    return _build_rows(
        items,
        pointed_value=pointed_value,
        default_value="1",
        accent_provider=_accent_provider(state),
    )



def _plan_review_rows(state: LaunchPromptState, *, pointed_value: str = "1") -> list[LaunchRow]:
    copy = _copy(state.config)
    items = [
        MenuItem("1", copy["plan_review_start"], copy["plan_review_start_desc"]),
        MenuItem("2", copy["plan_review_edit"], copy["plan_review_edit_desc"]),
        MenuItem("3", copy["plan_review_save"], copy["plan_review_save_desc"]),
        MenuItem("b", copy["plan_review_back"], copy["plan_review_back_desc"]),
    ]
    if state.from_entry:
        items.append(MenuItem("h", copy["nav_home"], copy["nav_home_desc"]))
    items.append(MenuItem("q", copy["quit"], copy["quit_desc"]))
    return _build_rows(
        items,
        pointed_value=pointed_value,
        default_value="1",
        accent_provider=_accent_provider(state),
    )



def _render_lines(renderable: object, *, width: int, ansi: bool = False) -> list[str]:
    local_buffer = StringIO()
    render_console = Console(
        file=local_buffer,
        force_terminal=ansi,
        color_system="truecolor" if ansi else None,
        width=max(60, int(width)),
        no_color=False if ansi else True,
    )
    render_console.print(renderable, end="")
    lines = local_buffer.getvalue().splitlines()
    return lines or [""]


def _review_header_renderable(state: LaunchPromptState) -> Group:
    copy = _copy(state.config)
    return Group(
        *_banner_parts(),
        Text(),
        _step_indicator(state, "review"),
        Text(),
        Text(copy["plan_review_title"], style=f"bold {_accent_color(state)}"),
        Text(copy["plan_review_hint"], style="dim"),
    )


def _review_body_renderable(state: LaunchPromptState, result: UxLabV3Result) -> Group:
    copy = _copy(state.config)
    model_map = _plan_agent_model_map(state, result.controller_plan)
    parts: list[object] = []
    parts.extend(_controller_plan_blocks(state, result))
    parts.append(Text())
    parts.append(Text(copy["plan_review_steps"], style="bold #CBD5E1"))
    for item in result.plan:
        model = model_map.get(item.agent, "")
        line = Text.assemble(
            (f"{item.sx} · ", "#64748B"),
            (str(CONTROLLER_LABELS.get(item.agent, item.agent.title())), _provider_rich_style(item.agent, bold=True)),
        )
        if model:
            line.append(f" · {model}", style="#CBD5E1")
        line.append(f" · {item.eta_minutes}m", style="#94A3B8")
        parts.append(line)
        parts.append(Text(f"    {item.title}", style="#CBD5E1"))
        parts.append(Text(f"    {item.done_when}", style="dim italic"))
    return Group(*parts)


def _review_actions_renderable(state: LaunchPromptState) -> Group:
    copy = _copy(state.config)
    actions = [
        copy["plan_review_action_start"],
        copy["plan_review_action_edit"],
        copy["plan_review_action_save"],
        copy["plan_review_action_back"],
    ]
    if state.from_entry:
        actions.append(copy["plan_review_action_home"])
    actions.append(copy["plan_review_action_quit"])
    return Group(
        Text.assemble(
            (f"{copy['plan_review_actions_label']} · ", "#64748B"),
            ("  ".join(actions), f"bold {_accent_color(state)}"),
        ),
        Text(copy["footer"] if state.from_entry else copy["footer_basic"], style="dim"),
    )


def _review_body_lines(
    state: LaunchPromptState,
    result: UxLabV3Result,
    *,
    width: int,
    ansi: bool = False,
) -> list[str]:
    return _render_lines(_review_body_renderable(state, result), width=width, ansi=ansi)


def _slice_review_body_lines(
    lines: list[str],
    *,
    scroll_offset: int,
    max_lines: int,
) -> tuple[list[str], int, int]:
    viewport = max(1, int(max_lines))
    source = list(lines or [""])
    max_offset = max(0, len(source) - viewport)
    offset = max(0, min(int(scroll_offset), max_offset))
    visible = source[offset : offset + viewport]
    if len(visible) < viewport:
        visible.extend([""] * (viewport - len(visible)))
    return visible, offset, max_offset


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(text or ""))


def _review_scrollbar_glyph(*, row: int, viewport: int, total: int, offset: int) -> str:
    if viewport <= 0:
        return " "
    if total <= viewport:
        return "█"
    thumb_size = max(1, min(viewport, round((viewport * viewport) / max(total, 1))))
    max_offset = max(1, total - viewport)
    thumb_start = 0 if viewport <= thumb_size else round(offset * (viewport - thumb_size) / max_offset)
    return "█" if thumb_start <= row < thumb_start + thumb_size else "░"


def _review_panel_lines(
    state: LaunchPromptState,
    *,
    visible_lines: list[str],
    total_lines: int,
    scroll_offset: int,
    width: int,
) -> list[str]:
    copy = _copy(state.config)
    inner_content_width = max(20, int(width) - 4)
    scrollbar_column_width = 2
    title = f" {copy['plan_review_panel_title']} "
    title_width = cell_len(title)
    top_fill = max(0, inner_content_width + scrollbar_column_width - title_width)
    top = "┌" + title + ("─" * top_fill) + "┐"
    bottom = "└" + ("─" * (inner_content_width + scrollbar_column_width)) + "┘"

    boxed: list[str] = [top]
    viewport = len(visible_lines)
    for index, line in enumerate(visible_lines):
        plain = _strip_ansi(line)
        padding = max(0, inner_content_width - cell_len(plain))
        scrollbar = _review_scrollbar_glyph(
            row=index,
            viewport=viewport,
            total=total_lines,
            offset=scroll_offset,
        )
        boxed.append(f"│{line}{' ' * padding}│{scrollbar}│")
    boxed.append(bottom)
    return boxed


def _review_scroll_meta_renderable(
    state: LaunchPromptState,
    *,
    start_line: int,
    end_line: int,
    total_lines: int,
) -> Group:
    copy = _copy(state.config)
    return Group(
        Text(copy["plan_review_scroll_hint"], style="dim"),
        Text(
            copy["plan_review_scroll_status"].format(
                start=start_line,
                end=end_line,
                total=total_lines,
            ),
            style="#64748B",
        ),
    )


def _summary_text(state: LaunchPromptState) -> list[Text]:
    copy = _copy(state.config)
    accent = _accent_color(state)
    return [
        Text(f"{copy['summary_workspace']} · {state.workspace}", style="#CBD5E1"),
        Text(f"{copy['summary_task']} · {_task_summary(state)}", style="#CBD5E1"),
        Text.assemble(
            (f"{copy['summary_controller']} · ", "#CBD5E1"),
            (_controller_label(state), f"bold {accent}"),
        ),
        Text(f"{copy['summary_planner']} · {_planner_label(state)}", style="#CBD5E1"),
    ]


def _provider_rich_style(provider: str | None, *, bold: bool = False) -> str:
    color = str(PROVIDER_THEME.get(str(provider or "").strip().lower(), "#CBD5E1"))
    return f"{'bold ' if bold else ''}{color}"


def _configured_model_label(config: Config, provider: str) -> str:
    provider_key = str(provider or "").strip().lower()
    if provider_key == "codex":
        provider_config = config.providers.get(provider_key)
        models = provider_config.models if provider_config is not None else {}
        default_model = str(models.get("default_model", "")).strip()
        if default_model:
            return default_model

    try:
        selection = ModelSelector(config).select_model(provider_key, "", "default")
    except Exception:  # noqa: BLE001
        return ""
    model = str(selection.model or "").strip()
    if not model:
        return ""
    if provider_key == "codex" and str(selection.thinking or "").strip():
        return f"{model} · {selection.thinking}"
    return model


def _resolved_plan_model_label(state: LaunchPromptState, provider: str, raw_model: str) -> str:
    model = str(raw_model or "").strip()
    if model and model.lower() != "unknown":
        return model
    configured = _configured_model_label(state.config, provider)
    if configured:
        return configured
    return _copy(state.config)["plan_review_model_unknown"]


def _plan_agent_model_map(state: LaunchPromptState, controller_plan: dict[str, Any] | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not isinstance(controller_plan, dict):
        return mapping
    agents = controller_plan.get("agents", [])
    if not isinstance(agents, list):
        return mapping
    for item in agents:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        model = _resolved_plan_model_label(state, name, str(item.get("model", "")).strip())
        if name and model:
            mapping[name] = model
    return mapping


def _controller_plan_blocks(state: LaunchPromptState, result: UxLabV3Result) -> list[Text]:
    copy = _copy(state.config)
    blocks: list[Text] = []
    controller_plan = result.controller_plan if isinstance(result.controller_plan, dict) else None
    source_label = copy["plan_review_source_live"] if result.planner_mode == "live" else copy["plan_review_source_mock"]
    if controller_plan is None:
        blocks.append(Text(source_label, style="bold #7DD3FC"))
        return blocks

    requires_multi = bool(controller_plan.get("requires_multi_agent", False))
    blocks.append(
        Text.assemble(
            (source_label, "bold #7DD3FC"),
            (" · ", "#475569"),
            (copy["plan_review_mode_multi"] if requires_multi else copy["plan_review_mode_single"], "#CBD5E1"),
        )
    )

    approval_question = str(controller_plan.get("approval_question", "")).strip()
    if approval_question:
        blocks.append(
            Text.assemble(
                (f"{copy['plan_review_approval']} · ", "#64748B"),
                (approval_question, "#E2E8F0 italic"),
            )
        )

    agents = controller_plan.get("agents", [])
    if isinstance(agents, list) and agents:
        blocks.append(Text(copy["plan_review_agents"], style="bold #CBD5E1"))
        for item in agents:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip().lower()
            label = str(CONTROLLER_LABELS.get(name, name.title() if name else "-"))
            model = _resolved_plan_model_label(state, name, str(item.get("model", "")).strip())
            why = str(item.get("why", "")).strip()
            persona = str(item.get("persona", "")).strip()
            line = Text.assemble(
                ("    • ", ""),
                (label, _provider_rich_style(name, bold=True)),
                (f" · {model}", "#CBD5E1"),
            )
            if persona:
                line.append(f" · {persona}", style="#94A3B8")
            blocks.append(line)
            if why:
                blocks.append(Text(f"      {why}", style="#64748B italic"))
    return blocks


def _planning_stage_label(config: Config, stage: str) -> str:
    copy = _copy(config)
    return copy.get(f"planning_stage_{stage}", stage)


def _planning_progress_renderable(
    state: LaunchPromptState,
    progress: PlanningProgressState,
    *,
    spinner_frame: str,
) -> Group:
    copy = _copy(state.config)
    total = 4
    completed = {
        "prompt_ready": 1,
        "command_started": 2,
        "json_received": 3,
        "steps_mapped": 4,
        "request_failed": 2,
        "cancel_requested": 2,
    }.get(progress.stage, 1)
    bar_width = 30
    filled = max(1, min(bar_width, int(bar_width * completed / total)))
    bar = "█" * filled + "░" * (bar_width - filled)
    elapsed_seconds = max(0, int(time.time() - (progress.started_at or time.time())))
    elapsed_text = f"{elapsed_seconds}s"
    prompt_preview = (progress.prompt_text or "").strip()
    if prompt_preview:
        prompt_lines = prompt_preview.splitlines()
        prompt_preview = "\n".join(prompt_lines[:12]).strip()
        if len(prompt_lines) > 12 or len(prompt_preview) > 900:
            prompt_preview = prompt_preview[:900].rstrip() + "\n..."

    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    parts.append(_step_indicator(state, "planner"))
    parts.append(Text())
    parts.append(Text(copy["planning_progress_title"], style=f"bold {_accent_color(state)}"))
    parts.append(Text(copy["planning_progress_hint"], style="dim"))
    parts.append(Text())
    parts.append(
        Text.assemble(
            (f"{copy['planning_progress_stage']} · ", "#64748B"),
            (spinner_frame, f"bold {_accent_color(state)}"),
            (" ", ""),
            (_planning_stage_label(state.config, progress.stage), "#E2E8F0"),
        )
    )
    parts.append(Text.assemble((bar, _accent_color(state)), (f" {completed}/{total}", "#94A3B8")))
    parts.append(Text())
    parts.append(
        Text.assemble(
            (f"{copy['planning_progress_controller']} · ", "#64748B"),
            (_controller_label(state), _provider_rich_style(state.controller, bold=True)),
            ("    ", ""),
            (f"{copy['planning_progress_mode']} · {_planner_label(state)}", "#CBD5E1"),
            ("    ", ""),
            (f"{copy['planning_progress_elapsed']} · {elapsed_text}", "#CBD5E1"),
        )
    )
    if progress.cancelling:
        parts.append(Text(copy["planning_progress_cancelling"], style="bold #F59E0B"))
    elif elapsed_seconds >= 60:
        parts.append(Text(copy["planning_progress_cancel_hint"], style="#FBBF24"))
    parts.append(Text())
    parts.append(
        Panel(
            Text(prompt_preview or copy["planning_progress_wait"], style="#E2E8F0"),
            title=copy["planning_progress_prompt"],
            title_align="left",
            border_style=_accent_color(state),
            expand=True,
        )
    )
    return Group(*parts)


def _run_planning_with_progress(
    *,
    state: LaunchPromptState,
    config: Config,
    console_obj: Console,
    clear_screen: bool,
) -> UxLabV3Result:
    progress = PlanningProgressState(started_at=time.time())
    result_box: dict[str, UxLabV3Result] = {}
    cancel_event = threading.Event()

    def _on_progress(stage: str, payload: dict[str, Any]) -> None:
        progress.stage = stage
        prompt_text = str(payload.get("prompt_text", "")).strip()
        if prompt_text:
            progress.prompt_text = prompt_text
        step_count = int(payload.get("step_count", 0) or 0)
        if step_count:
            progress.step_count = step_count

    def _worker() -> None:
        result_box["result"] = run_launcher_flow(
            config=config,
            cwd=state.cwd,
            workspace=state.workspace,
            controller=state.controller,
            task=state.task,
            task_file=None,
            skip_review=False,
            planner_mode=state.planner_mode,
            output_bundle=state.output_bundle,
            progress_callback=_on_progress,
            cancel_requested=cancel_event.is_set,
        )

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    if clear_screen:
        console_obj.clear()

    with Live(console=console_obj, refresh_per_second=12, transient=True) as live:
        frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        index = 0
        try:
            while thread.is_alive():
                live.update(_planning_progress_renderable(state, progress, spinner_frame=frames[index % len(frames)]))
                index += 1
                time.sleep(0.08)
        except KeyboardInterrupt:
            cancel_event.set()
            progress.cancelling = True
            progress.stage = "cancel_requested"
            while thread.is_alive():
                live.update(_planning_progress_renderable(state, progress, spinner_frame="×"))
                time.sleep(0.08)
        thread.join()
        live.update(
            _planning_progress_renderable(
                state,
                progress,
                spinner_frame="×" if progress.cancelling else "✓",
            )
        )

    return result_box["result"]


def _ask_text_value(prompt: str, *, default: str, input_fn: TextInputFn | None) -> str:
    ask = input_fn or Prompt.ask
    return str(ask(prompt, default=default)).strip()


def _terminal_shape(
    *,
    fallback: tuple[int, int] = (120, 32),
    min_width: int = 20,
    max_width: int = 140,
    min_height: int = 8,
) -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback)
    width = size.columns or fallback[0]
    height = size.lines or fallback[1]
    return max(min_width, min(width, max_width)), max(min_height, height)


def _render_ansi(renderable: object, *, width: int = 120) -> str:
    local_buffer = StringIO()
    render_console = Console(
        file=local_buffer,
        force_terminal=True,
        color_system="truecolor",
        width=width,
        no_color=False,
    )
    render_console.print(renderable, end="")
    return local_buffer.getvalue()


def _plan_field_preview_panel(*, label: str, value: str, border_style: str = "#334155") -> Panel:
    content = str(value or "").strip() or "—"
    return Panel(Text(content, style="#E2E8F0"), title=label, title_align="left", border_style=border_style, expand=True)


def _plan_step_form_renderable(
    state: LaunchPromptState,
    draft: PlanDraft,
    *,
    step_index: int,
    is_insert: bool,
    compact: bool = False,
    width: int = 120,
) -> Group:
    copy = _copy(state.config)
    step = draft.steps[step_index]
    title_key = "plan_edit_form_insert_title" if is_insert else "plan_edit_form_step_title"
    if compact:
        return Group(
            Text(copy[title_key].format(step_id=step.id), style=f"bold {_accent_color(state)}"),
            Text.assemble(
                (f"{copy['plan_edit_step_title']} · ", "#64748B"),
                (_compact_text(step.title, limit=max(24, width - 14)), "#E2E8F0"),
            ),
            Text.assemble(
                (f"{copy['plan_edit_step_owner']} · ", "#64748B"),
                (str(CONTROLLER_LABELS.get(step.owner, step.owner.title())), _provider_rich_style(step.owner, bold=True)),
                ("    ", ""),
                (f"{copy['plan_edit_step_eta']} · {step.eta_minutes}", "#CBD5E1"),
            ),
            Text.assemble(
                (f"{copy['plan_edit_step_done_when']} · ", "#64748B"),
                (_compact_text(step.done_when, limit=max(24, width - 14)), "#CBD5E1"),
            ),
            Text("Tab · Ctrl+S · Esc", style="dim"),
        )
    parts: list[object] = [
        Text(copy[title_key].format(step_id=step.id), style=f"bold {_accent_color(state)}"),
        Text(copy["plan_edit_form_step_hint"], style="dim"),
        Text(),
        Text(copy["plan_edit_form_field_preview"], style="bold #CBD5E1"),
        _plan_field_preview_panel(label=copy["plan_edit_step_title"], value=step.title, border_style=_accent_color(state)),
        _plan_field_preview_panel(
            label=copy["plan_edit_step_owner"],
            value=str(CONTROLLER_LABELS.get(step.owner, step.owner.title())),
        ),
        _plan_field_preview_panel(label=copy["plan_edit_step_eta"], value=str(step.eta_minutes)),
        _plan_field_preview_panel(label=copy["plan_edit_step_done_when"], value=step.done_when),
        Text(),
        Text(copy["plan_edit_form_footer"], style="dim"),
    ]
    return Group(*parts)


def _plan_task_form_renderable(state: LaunchPromptState, task: str, *, compact: bool = False, width: int = 120) -> Group:
    copy = _copy(state.config)
    if compact:
        return Group(
            Text(copy["plan_edit_form_task_title"], style=f"bold {_accent_color(state)}"),
            Text.assemble(
                (f"{copy['plan_edit_task']} · ", "#64748B"),
                (_compact_text(task, limit=max(24, width - 12)), "#E2E8F0"),
            ),
            Text("Ctrl+S · Esc", style="dim"),
        )
    return Group(
        Text(copy["plan_edit_form_task_title"], style=f"bold {_accent_color(state)}"),
        Text(copy["plan_edit_form_task_hint"], style="dim"),
        Text(),
        Text(copy["plan_edit_form_field_preview"], style="bold #CBD5E1"),
        _plan_field_preview_panel(label=copy["plan_edit_task"], value=task, border_style=_accent_color(state)),
        Text(),
        Text(copy["plan_edit_form_footer"], style="dim"),
    )


def _plan_step_form_header_renderable(
    state: LaunchPromptState,
    draft: PlanDraft,
    *,
    step_index: int,
    is_insert: bool,
) -> Group:
    copy = _copy(state.config)
    step = draft.steps[step_index]
    title_key = "plan_edit_form_insert_title" if is_insert else "plan_edit_form_step_title"
    return Group(
        Text(f"Task Config: {step.id}", style=f"bold {_accent_color(state)}"),
        Text(
            f"{copy[title_key].format(step_id=step.id)}    "
            f"{copy['plan_edit_summary_task']} · {draft.task or state.task}    "
            f"{copy['plan_edit_step_owner_short']} · {CONTROLLER_LABELS.get(step.owner, step.owner.title())}",
            style="#94A3B8",
        ),
    )


def _plan_task_form_header_renderable(state: LaunchPromptState, task: str) -> Group:
    copy = _copy(state.config)
    return Group(
        Text(copy["plan_edit_form_task_title"], style=f"bold {_accent_color(state)}"),
        Text(copy["plan_edit_form_task_hint"], style="dim"),
        Text(f"{copy['plan_edit_summary_task']} · {task}", style="#94A3B8"),
    )


def _plan_form_style():  # noqa: ANN201
    from prompt_toolkit.styles import Style

    return Style.from_dict(
        {
            "": "#dbe7f5",
            "frame.border": "#35515a",
            "frame.label": "bold #f8fafc",
            "radio": "#dbe7f5",
            "radio-focused": "bg:#334155 #f8fafc",
            "radio-selected": "bg:#334155 #f8fafc",
            "radio-checked": "bold #7dd3fc",
            "radio-checked-focused": "bold #7dd3fc bg:#334155",
            "text-area": "#e2e8f0",
            "field-label": "bold #67e8f9",
            "form-rule": "#3b565f",
            "form-footer": "#67e8f9",
            "form-surface": "",
            "field-box": "",
            "agent-option": "#94a3b8",
            "agent-active-marker": "bold #67e8f9",
            "agent-active-label": "bold #f8fafc",
            "agent-active-tag": "#94a3b8",
            "too-small-title": "bold #67e8f9",
            "too-small-body": "#cbd5e1",
        }
    )


def _use_prompt_toolkit_form(*, selector_fn: SelectFn | None, input_fn: TextInputFn | None) -> bool:
    return selector_fn is None and input_fn is None and sys.stdin.isatty()


def _plan_form_too_small_window(*, title: str) -> object:
    from prompt_toolkit.layout import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    return Window(
        FormattedTextControl(
            [
                ("class:too-small-title", f"{title}\n"),
                ("class:too-small-body", "Terminal window is too small for this editor.\n"),
                ("class:too-small-body", "请拉高窗口，或按 Esc 取消后在更大的终端里编辑。"),
            ],
            focusable=False,
            show_cursor=False,
        ),
        dont_extend_height=True,
    )


def _plan_form_density(width: int, height: int, *, compact: bool) -> dict[str, int | bool]:
    """Scale editor blocks to fit the current terminal instead of requiring fullscreen."""
    tight = height < 24
    ultra_tight = height < 18
    stack_meta = width < 96
    body_padding = 0 if compact or tight else 1
    section_gap = 0 if tight else 1
    header_preferred = 2 if ultra_tight else 3
    done_input_rows = 2 if tight else (3 if compact else 4)
    done_frame_height = 4 if ultra_tight else (5 if tight else (6 if compact else 7))
    done_block_height = done_frame_height + 2
    meta_row_height = 9 if stack_meta and ultra_tight else (10 if stack_meta and tight else (11 if stack_meta else 5))
    min_render_height = 12 if stack_meta else 10
    return {
        "stack_meta": stack_meta,
        "tight": tight,
        "ultra_tight": ultra_tight,
        "body_padding": body_padding,
        "section_gap": section_gap,
        "header_preferred": header_preferred,
        "done_input_rows": done_input_rows,
        "done_frame_height": done_frame_height,
        "done_block_height": done_block_height,
        "meta_row_height": meta_row_height,
        "min_render_height": min_render_height,
    }


def _prompt_plan_step_form_with_prompt_toolkit(
    *,
    state: LaunchPromptState,
    draft: PlanDraft,
    step_index: int,
    is_insert: bool,
    console_obj: Console,
    clear_screen: bool,
) -> tuple[str, str, int, str] | None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import HSplit, HorizontalAlign, Layout, VSplit, VerticalAlign, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import D
    from prompt_toolkit.widgets import Box, Frame, Label, TextArea

    copy = _copy(state.config)
    step = draft.steps[step_index]
    _width, _height, compact = _plan_editor_terminal_shape()
    density = _plan_form_density(_width, _height, compact=compact)
    too_small_window = _plan_form_too_small_window(title=f"Task Config: {step.id}")
    done_height = D.exact(int(density["done_input_rows"]))
    body_padding = int(density["body_padding"])
    owner_options = [
        ("codex", str(CONTROLLER_LABELS.get("codex", "Codex"))),
        ("claude", str(CONTROLLER_LABELS.get("claude", "Claude Code"))),
        ("gemini", str(CONTROLLER_LABELS.get("gemini", "Gemini CLI"))),
    ]
    owner_index = next((index for index, (value, _label) in enumerate(owner_options) if value == step.owner), 0)

    title_input = TextArea(
        text=step.title,
        multiline=False,
        wrap_lines=False,
        focus_on_click=False,
        style="class:text-area",
    )
    eta_input = TextArea(
        text=str(5 if is_insert else step.eta_minutes),
        multiline=False,
        wrap_lines=False,
        focus_on_click=False,
        style="class:text-area",
    )
    done_input = TextArea(
        text=step.done_when,
        multiline=True,
        wrap_lines=True,
        scrollbar=False,
        focus_on_click=False,
        height=3 if compact else 4,
        style="class:text-area",
    )

    status_message = copy["plan_edit_form_footer"]

    def _section_label(label: str) -> Label:
        return Label(f"  ■  {label}", style="class:field-label")

    def _header_tokens() -> list[tuple[str, str]]:
        current_width, _current_height, _current_compact = _plan_editor_terminal_shape()
        return list(
            to_formatted_text(
                ANSI(
                    _render_ansi(
                        _plan_step_form_header_renderable(
                            state,
                            draft,
                            step_index=step_index,
                            is_insert=is_insert,
                        ),
                        width=max(56, min(current_width, 110)),
                    )
                )
            )
        )

    def _footer_tokens() -> list[tuple[str, str]]:
        color = "fg:#FBBF24" if status_message == copy["plan_edit_form_eta_invalid"] else "class:form-footer"
        prefix = "💡 " if status_message == copy["plan_edit_form_footer"] else ""
        return [(color, f"{prefix}{status_message}")]

    def _owner_tokens() -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        for index, (_value, label) in enumerate(owner_options):
            selected = index == owner_index
            tokens.append(("class:agent-active-marker" if selected else "class:agent-option", f"     [{'●' if selected else ' '}]  "))
            tokens.append(("class:agent-active-label" if selected else "class:agent-option", label))
            if selected:
                tokens.append(("class:agent-active-tag", "  (Active)"))
            if index < len(owner_options) - 1:
                tokens.append(("", "\n"))
        return tokens

    bindings = KeyBindings()
    owner_bindings = KeyBindings()

    @bindings.add("tab", eager=True)
    def _focus_next(event) -> None:
        event.app.layout.focus_next()

    @bindings.add("s-tab", eager=True)
    def _focus_previous(event) -> None:
        event.app.layout.focus_previous()

    @owner_bindings.add(Keys.Down, eager=True)
    def _owner_down(event) -> None:
        nonlocal owner_index
        owner_index = (owner_index + 1) % len(owner_options)
        event.app.invalidate()

    @owner_bindings.add(Keys.Up, eager=True)
    def _owner_up(event) -> None:
        nonlocal owner_index
        owner_index = (owner_index - 1) % len(owner_options)
        event.app.invalidate()

    @bindings.add(Keys.ControlS, eager=True)
    def _save(event) -> None:
        nonlocal status_message
        eta_text = eta_input.text.strip()
        if not eta_text.isdigit():
            status_message = copy["plan_edit_form_eta_invalid"]
            event.app.invalidate()
            return
        event.app.exit(
            result=(
                title_input.text.strip() or step.title,
                owner_options[owner_index][0],
                int(eta_text),
                done_input.text.strip() or step.done_when,
            )
        )

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _cancel(event) -> None:
        event.app.exit(result=None)

    title_block = HSplit(
        [
            _section_label(copy["plan_edit_step_title"]),
            Frame(Box(title_input, height=D.exact(1), padding_left=1, padding_right=1), height=D.exact(3)),
        ],
        padding=0,
        height=D.exact(4),
        align=VerticalAlign.TOP,
    )
    owner_control = FormattedTextControl(_owner_tokens, focusable=True, show_cursor=False, key_bindings=owner_bindings)
    owner_block = HSplit(
        [
            _section_label(copy["plan_edit_step_owner"]),
            Window(owner_control, height=3, dont_extend_height=True),
        ],
        padding=0,
        width=None if bool(density["stack_meta"]) else D.exact(40),
        height=D.exact(4),
        align=VerticalAlign.TOP,
    )
    eta_block = HSplit(
        [
            _section_label(f"{copy['plan_edit_step_eta']} (Min)"),
            Frame(Box(eta_input, height=D.exact(1), padding_left=1, padding_right=1), height=D.exact(3), width=D.exact(13)),
        ],
        padding=0,
        width=D.exact(20),
        height=D.exact(4),
        align=VerticalAlign.TOP,
    )
    done_block = HSplit(
        [
            _section_label(copy["plan_edit_step_done_when"]),
            Frame(
                Box(done_input, height=done_height, padding_left=1, padding_right=1),
                height=D.exact(int(density["done_frame_height"])),
            ),
        ],
        padding=0,
        height=D.exact(int(density["done_block_height"])),
        align=VerticalAlign.TOP,
    )
    meta_row = (
        HSplit(
            [owner_block, eta_block],
            padding=1,
            height=D.exact(int(density["meta_row_height"])),
            align=VerticalAlign.TOP,
            window_too_small=too_small_window,
        )
        if bool(density["stack_meta"])
        else VSplit(
            [owner_block, eta_block],
            padding=4,
            height=D.exact(int(density["meta_row_height"])),
            align=HorizontalAlign.LEFT,
            window_too_small=too_small_window,
        )
    )
    body = HSplit(
        [
            Window(
                FormattedTextControl(_header_tokens),
                height=D(min=2, preferred=int(density["header_preferred"]), max=4),
                dont_extend_height=True,
            ),
            Window(char="─", height=1, style="class:form-rule"),
            title_block,
            Window(height=int(density["section_gap"])),
            meta_row,
            Window(height=int(density["section_gap"])),
            done_block,
            Window(char="─", height=1, style="class:form-rule"),
            Window(FormattedTextControl(_footer_tokens), height=1),
        ],
        padding=body_padding,
        align=VerticalAlign.TOP,
        style="class:form-surface",
        window_too_small=too_small_window,
    )
    use_too_small_fallback = _height < int(density["min_render_height"]) or _width < 48
    if use_too_small_fallback:
        body = too_small_window

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(body, focused_element=None if use_too_small_fallback else title_input),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
        style=_plan_form_style(),
    )
    return app.run()


def _prompt_plan_task_form_with_prompt_toolkit(
    *,
    state: LaunchPromptState,
    task: str,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import HSplit, Layout, VerticalAlign, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import D
    from prompt_toolkit.widgets import Box, Label, TextArea

    copy = _copy(state.config)
    _width, _height, compact = _plan_editor_terminal_shape()
    density = _plan_form_density(_width, _height, compact=compact)
    too_small_window = _plan_form_too_small_window(title=copy["plan_edit_form_task_title"])
    task_input = TextArea(
        text=task,
        multiline=True,
        wrap_lines=True,
        scrollbar=True,
        focus_on_click=False,
        height=int(density["done_input_rows"]),
        style="class:text-area",
    )

    def _header_tokens() -> list[tuple[str, str]]:
        current_width, _current_height, _current_compact = _plan_editor_terminal_shape()
        return list(to_formatted_text(ANSI(_render_ansi(_plan_task_form_header_renderable(state, task), width=max(56, min(current_width, 110))))))

    bindings = KeyBindings()

    @bindings.add(Keys.ControlS, eager=True)
    def _save(event) -> None:
        event.app.exit(result=task_input.text.strip() or task)

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _cancel(event) -> None:
        event.app.exit(result=None)

    @bindings.add("tab", eager=True)
    @bindings.add("s-tab", eager=True)
    def _noop_tab(event) -> None:
        return None

    body = HSplit(
        [
            Window(FormattedTextControl(_header_tokens), height=D(min=3, preferred=3, max=4), dont_extend_height=True),
            Window(char="─", height=1, style="class:form-rule"),
            HSplit(
                [
                    Label(copy["plan_edit_task"], style="class:field-label"),
                    Box(
                        task_input,
                        height=(
                            D(min=2, preferred=3, max=4)
                            if bool(density["tight"])
                            else (D(min=3, preferred=4, max=5) if compact else D(min=6, preferred=8, max=10))
                        ),
                        padding_left=1,
                        padding_right=1,
                        style="class:field-box",
                    ),
                ],
                padding=0,
                height=D.exact(5 if bool(density["tight"]) else (6 if compact else 10)),
                align=VerticalAlign.TOP,
                window_too_small=too_small_window,
            ),
            Window(char="─", height=1, style="class:form-rule"),
            Window(FormattedTextControl(lambda: [("class:form-footer", copy["plan_edit_form_footer"])]), height=1),
        ],
        padding=int(density["body_padding"]),
        align=VerticalAlign.TOP,
        style="class:form-surface",
        window_too_small=too_small_window,
    )
    use_too_small_fallback = _height < 8 or _width < 42
    if use_too_small_fallback:
        body = too_small_window

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(body, focused_element=None if use_too_small_fallback else task_input),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
        style=_plan_form_style(),
    )
    return app.run()


def _plan_draft_mode_label(copy: dict[str, str], draft: PlanDraft) -> str:
    return copy["plan_edit_multi_agent"] if len({step.owner for step in draft.steps}) > 1 else copy["plan_edit_single_agent"]


def _plan_draft_model_map(state: LaunchPromptState, draft: PlanDraft) -> dict[str, str]:
    mapping: dict[str, str] = {}
    controller_plan = draft.source_controller_plan if isinstance(draft.source_controller_plan, dict) else {}
    agents = controller_plan.get("agents", []) if isinstance(controller_plan, dict) else []
    if isinstance(agents, list):
        for item in agents:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip().lower()
            if name not in {"codex", "claude", "gemini"}:
                continue
            mapping[name] = _resolved_plan_model_label(state, name, str(item.get("model", "")).strip())

    for step in draft.steps:
        if step.owner not in mapping:
            mapping[step.owner] = _configured_model_label(state.config, step.owner)
    return mapping


def _plan_editor_summary_table(state: LaunchPromptState, draft: PlanDraft, model_map: dict[str, str]) -> Table:
    copy = _copy(state.config)
    table = Table.grid(expand=True)
    table.add_column(ratio=2)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_row(
        Text.assemble((f"{copy['plan_edit_summary_task']}\n", "#64748B"), (draft.task or _task_summary(state), "bold #E2E8F0")),
        Text.assemble((f"{copy['plan_edit_summary_controller']}\n", "#64748B"), (str(CONTROLLER_LABELS.get(draft.controller, draft.controller.title())), _provider_rich_style(draft.controller, bold=True))),
        Text.assemble((f"{copy['plan_edit_summary_mode']}\n", "#64748B"), (_plan_draft_mode_label(copy, draft), "bold #CBD5E1")),
        Text.assemble((f"{copy['plan_edit_summary_steps']}\n", "#64748B"), (str(len(draft.steps)), "bold #CBD5E1")),
        Text.assemble((f"{copy['plan_edit_summary_models']}\n", "#64748B"), (str(len(model_map)), "bold #CBD5E1")),
    )
    return table


def _plan_editor_route_table(state: LaunchPromptState, draft: PlanDraft, model_map: dict[str, str]) -> Table:
    step_suffix = "步" if _lang(state.config) == "zh-CN" else "step"
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=2)
    table.add_column(justify="right", ratio=1)
    ordered_owners: list[str] = []
    for step in draft.steps:
        if step.owner not in ordered_owners:
            ordered_owners.append(step.owner)
    for owner in ordered_owners:
        count = len([step for step in draft.steps if step.owner == owner])
        table.add_row(
            Text(str(CONTROLLER_LABELS.get(owner, owner.title())), style=_provider_rich_style(owner, bold=True)),
            Text(model_map.get(owner, ""), style="#CBD5E1"),
            Text(f"{count} {step_suffix}", style="#64748B"),
        )
    return table


def _plan_editor_compact_summary(state: LaunchPromptState, draft: PlanDraft, model_map: dict[str, str], *, width: int) -> Text:
    copy = _copy(state.config)
    summary = (
        f"{copy['plan_edit_summary_task']}: {draft.task or _task_summary(state)}  |  "
        f"{copy['plan_edit_summary_controller']}: {CONTROLLER_LABELS.get(draft.controller, draft.controller.title())}  |  "
        f"{copy['plan_edit_summary_steps']}: {len(draft.steps)}  |  "
        f"{copy['plan_edit_summary_models']}: {len(model_map)}"
    )
    return Text(_compact_text(summary, limit=max(32, width - 2)), style="#94A3B8")


def _plan_editor_list_line(state: LaunchPromptState, step, *, selected: bool, model: str = "") -> Text:
    prefix = "> " if selected else "  "
    style = f"bold {_accent_color(state)} underline" if selected else "#CBD5E1"
    line = Text.assemble((prefix, ""), (f"{step.id} ", "#64748B"), (step.title, style))
    line.append(" · ", style="#334155")
    line.append(str(CONTROLLER_LABELS.get(step.owner, step.owner.title())), style=_provider_rich_style(step.owner, bold=selected))
    if model:
        line.append(" · ", style="#334155")
        line.append(model, style="#94A3B8")
    line.append(f" · {step.eta_minutes}m", style="#94A3B8")
    return line


def _plan_editor_compact_current_step(state: LaunchPromptState, step, *, model: str, width: int) -> Text:
    copy = _copy(state.config)
    current = (
        f"{copy['plan_edit_current_step']} · {step.id} {step.title}  |  "
        f"{copy['plan_edit_step_owner_short']}: {CONTROLLER_LABELS.get(step.owner, step.owner.title())}  |  "
        f"{copy['plan_edit_step_model_short']}: {model}  |  "
        f"{copy['plan_edit_step_eta_short']}: {step.eta_minutes}m"
    )
    return Text(_compact_text(current, limit=max(32, width - 2)), style="#CBD5E1")


def _plan_editor_step_window(
    *,
    total_steps: int,
    selected_index: int,
    max_visible_steps: int | None,
) -> tuple[int, int]:
    if max_visible_steps is None or total_steps <= max_visible_steps:
        return 0, total_steps
    viewport = max(1, min(total_steps, int(max_visible_steps)))
    selected = max(0, min(selected_index, total_steps - 1))
    half_window = viewport // 2
    start = selected - half_window
    start = max(0, min(start, total_steps - viewport))
    return start, start + viewport


def _plan_editor_visible_step_count() -> int:
    _width, height, compact = _plan_editor_terminal_shape()
    return _plan_editor_visible_step_count_for_height(height, compact=compact)


def _plan_editor_terminal_shape() -> tuple[int, int, bool]:
    width, height = _terminal_shape()
    compact = width < 96 or height < 34
    return width, height, compact


def _plan_editor_visible_step_count_for_height(height: int, *, compact: bool) -> int:
    reserved_lines = 20 if compact else 28
    available_step_lines = max(4, height - reserved_lines)
    minimum = 2 if compact else 3
    maximum = 6 if compact else 8
    return max(minimum, min(maximum, available_step_lines // 2))


def _compact_text(value: str, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _plan_editor_compact_routes(state: LaunchPromptState, draft: PlanDraft, model_map: dict[str, str], *, width: int) -> Text:
    copy = _copy(state.config)
    ordered_owners: list[str] = []
    for step in draft.steps:
        if step.owner not in ordered_owners:
            ordered_owners.append(step.owner)
    fragments = [
        f"{CONTROLLER_LABELS.get(owner, owner.title())}: {model_map.get(owner, '')}"
        for owner in ordered_owners
    ]
    route_text = "  |  ".join(fragments)
    return Text.assemble(
        (f"{copy['plan_edit_compact_routes']} · ", "#64748B"),
        (_compact_text(route_text, limit=max(24, width - 12)), "#CBD5E1"),
    )


def _plan_editor_screen_renderable(
    state: LaunchPromptState,
    draft: PlanDraft,
    *,
    selected_index: int,
    status_message: str = "",
    max_visible_steps: int | None = None,
    compact: bool = False,
    width: int = 120,
) -> Group:
    copy = _copy(state.config)
    selected_step = draft.steps[selected_index]
    model_map = _plan_draft_model_map(state, draft)
    selected_model = model_map.get(selected_step.owner, "")
    parts: list[object] = []
    if not compact:
        parts.extend(_banner_parts())
        parts.append(Text())
    parts.append(_step_indicator(state, "review"))
    parts.append(Text())
    parts.append(Text(copy["plan_edit_list_title"], style=f"bold {_accent_color(state)}"))
    parts.append(Text(copy["plan_edit_list_hint"], style="dim"))
    parts.append(Text())
    if compact:
        parts.append(_plan_editor_compact_summary(state, draft, model_map, width=width))
    else:
        parts.append(
            Panel(
                _plan_editor_summary_table(state, draft, model_map),
                border_style="#1E293B",
                title=copy["plan_edit_title"],
                title_align="left",
                expand=True,
            )
        )
    if status_message:
        parts.append(Text(status_message, style="#FBBF24"))
    parts.append(Text())
    if compact:
        parts.append(
            Text.assemble(
                (f"{copy['plan_edit_prompt_panel']} · ", "#64748B"),
                (_compact_text(draft.task or _task_summary(state), limit=max(24, width - 22)), "#E2E8F0"),
            )
        )
        parts.append(_plan_editor_compact_routes(state, draft, model_map, width=width))
    else:
        parts.append(
            Panel(
                Text(draft.task or _task_summary(state), style="#E2E8F0"),
                title=copy["plan_edit_prompt_panel"],
                title_align="left",
                border_style="#334155",
                expand=True,
            )
        )
        parts.append(
            Panel(
                _plan_editor_route_table(state, draft, model_map),
                title=copy["plan_edit_routes_panel"],
                title_align="left",
                border_style="#334155",
                expand=True,
            )
        )
    parts.append(Text())
    parts.append(Text(copy["plan_review_steps"], style="bold #CBD5E1"))
    window_start, window_end = _plan_editor_step_window(
        total_steps=len(draft.steps),
        selected_index=selected_index,
        max_visible_steps=max_visible_steps,
    )
    if window_start > 0:
        parts.append(Text("  …", style="#64748B"))
    for index, step in enumerate(draft.steps[window_start:window_end], start=window_start):
        parts.append(_plan_editor_list_line(state, step, selected=index == selected_index, model=model_map.get(step.owner, "")))
        if not compact:
            parts.append(Text(f"    {step.done_when}", style="#64748B italic"))
    if window_end < len(draft.steps):
        parts.append(Text("  …", style="#64748B"))
    if max_visible_steps is not None and len(draft.steps) > max_visible_steps:
        parts.append(
            Text(
                copy["plan_edit_steps_window"].format(
                    start=window_start + 1,
                    end=window_end,
                    total=len(draft.steps),
                ),
                style="#64748B",
            )
        )
    parts.append(Text())
    if compact:
        parts.append(_plan_editor_compact_current_step(state, selected_step, model=selected_model, width=width))
    else:
        parts.append(
            Panel(
                Group(
                    Text(selected_step.title, style="bold #E2E8F0"),
                    Text.assemble((f"{copy['plan_edit_step_owner_short']} · ", "#64748B"), (str(CONTROLLER_LABELS.get(selected_step.owner, selected_step.owner.title())), _provider_rich_style(selected_step.owner, bold=True))),
                    Text(f"{copy['plan_edit_step_model_short']} · {selected_model}", style="#CBD5E1"),
                    Text(f"{copy['plan_edit_step_eta_short']} · {selected_step.eta_minutes}m", style="#CBD5E1"),
                    Text(f"{copy['plan_edit_step_done_short']} · {selected_step.done_when}", style="#CBD5E1"),
                ),
                title=copy["plan_edit_current_step"],
                title_align="left",
                border_style=_accent_color(state),
                expand=True,
            )
        )
    parts.append(Text())
    parts.append(Text(copy["plan_edit_shortcuts"], style="dim"))
    return Group(*parts)


def _prompt_step_owner(
    *,
    state: LaunchPromptState,
    default_owner: str,
    selector_fn: SelectFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    def _owner_renderable(pointed: str) -> Group:
        width, _height, compact = _plan_editor_terminal_shape()
        parts: list[object] = []
        if not compact:
            parts.extend(_banner_parts())
            parts.append(Text())
        parts.extend(
            [
                Text(_copy(state.config)["plan_edit_step_owner"], style=f"bold {_accent_color(state)}"),
                Text(),
                *[_row_text(row) for row in _controller_rows(state, pointed_value=pointed, include_nav=False)],
                Text(),
                Text(_compact_text(_copy(state.config)["footer_basic"], limit=max(32, width - 2)) if compact else _copy(state.config)["footer_basic"], style="dim"),
            ]
        )
        return Group(*parts)

    owner_choice = _select_screen(
        _owner_renderable,
        values=["1", "2", "3", "q"],
        default_value={"codex": "1", "claude": "2", "gemini": "3"}.get(default_owner, "1"),
        selector_fn=selector_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
    )
    return {"1": "codex", "2": "claude", "3": "gemini"}.get(owner_choice, default_owner)


def _edit_step_form_prompt(
    *,
    state: LaunchPromptState,
    draft: PlanDraft,
    step_index: int,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> None:
    step = draft.steps[step_index]
    if _use_prompt_toolkit_form(selector_fn=selector_fn, input_fn=input_fn):
        result = _prompt_plan_step_form_with_prompt_toolkit(
            state=state,
            draft=draft,
            step_index=step_index,
            is_insert=False,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )
        if result is None:
            return
        title, owner, eta_minutes, done_when = result
        update_step(
            draft,
            index=step_index,
            title=title,
            owner=owner,
            eta_minutes=eta_minutes,
            done_when=done_when,
        )
        return
    title = _ask_text_value(_copy(state.config)["plan_edit_step_title"], default=step.title, input_fn=input_fn) or step.title
    owner = _prompt_step_owner(
        state=state,
        default_owner=step.owner,
        selector_fn=selector_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
    )
    eta_text = _ask_text_value(_copy(state.config)["plan_edit_step_eta"], default=str(step.eta_minutes), input_fn=input_fn)
    done_when = _ask_text_value(_copy(state.config)["plan_edit_step_done_when"], default=step.done_when, input_fn=input_fn) or step.done_when
    update_step(
        draft,
        index=step_index,
        title=title,
        owner=owner,
        eta_minutes=int(eta_text) if eta_text.isdigit() else step.eta_minutes,
        done_when=done_when,
    )


def _insert_step_form_prompt(
    *,
    state: LaunchPromptState,
    draft: PlanDraft,
    step_index: int,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> int:
    current = draft.steps[step_index]
    if _use_prompt_toolkit_form(selector_fn=selector_fn, input_fn=input_fn):
        result = _prompt_plan_step_form_with_prompt_toolkit(
            state=state,
            draft=draft,
            step_index=step_index,
            is_insert=True,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )
        if result is None:
            return step_index
        title, owner, eta_minutes, done_when = result
        return insert_step_after(
            draft,
            index=step_index,
            owner=owner,
            title=title,
            eta_minutes=eta_minutes,
            done_when=done_when,
        )
    title = _ask_text_value(_copy(state.config)["plan_edit_step_title"], default=current.title, input_fn=input_fn) or current.title
    owner = _prompt_step_owner(
        state=state,
        default_owner=current.owner,
        selector_fn=selector_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
    )
    eta_text = _ask_text_value(_copy(state.config)["plan_edit_step_eta"], default="5", input_fn=input_fn)
    done_when = _ask_text_value(_copy(state.config)["plan_edit_step_done_when"], default=current.done_when, input_fn=input_fn) or current.done_when
    return insert_step_after(
        draft,
        index=step_index,
        owner=owner,
        title=title,
        eta_minutes=int(eta_text) if eta_text.isdigit() else 5,
        done_when=done_when,
    )


def _select_plan_editor_action(
    *,
    state: LaunchPromptState,
    draft: PlanDraft,
    selected_index: int,
    status_message: str,
    selector_fn: SelectFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> tuple[str, int]:
    values = ["up", "down", "edit", "insert", "delete", "move_down", "move_up", "rename_task", "save", "back", "quit"]
    if selector_fn is not None or not sys.stdin.isatty():
        if clear_screen:
            console_obj.clear()
        console_obj.print(
            _plan_editor_screen_renderable(
                state,
                draft,
                selected_index=selected_index,
                status_message=status_message,
            ),
            end="",
        )
        choose = selector_fn or (lambda **kwargs: Prompt.ask("Action", choices=kwargs["choices"], default=kwargs["default_value"]))
        return str(choose(screen="plan_editor", choices=values, default_value="edit")), selected_index

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    local_selected = selected_index

    def _tokens() -> list[tuple[str, str]]:
        local_buffer = StringIO()
        width, height, compact = _plan_editor_terminal_shape()
        render_console = Console(file=local_buffer, force_terminal=True, color_system="truecolor", width=width, no_color=False)
        render_console.print(
            _plan_editor_screen_renderable(
                state,
                draft,
                selected_index=local_selected,
                status_message=status_message,
                max_visible_steps=_plan_editor_visible_step_count_for_height(height, compact=compact),
                compact=compact,
                width=width,
            ),
            end="",
        )
        return list(to_formatted_text(ANSI(local_buffer.getvalue())))

    def _move(offset: int) -> None:
        nonlocal local_selected
        local_selected = (local_selected + offset) % len(draft.steps)

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)
        event.app.invalidate()

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)
        event.app.invalidate()

    @bindings.add(Keys.ControlM, eager=True)
    def _edit(event) -> None:
        event.app.exit(result="edit")

    @bindings.add("a", eager=True)
    def _insert(event) -> None:
        event.app.exit(result="insert")

    @bindings.add("d", eager=True)
    def _delete(event) -> None:
        event.app.exit(result="delete")

    @bindings.add("J", eager=True)
    def _move_down(event) -> None:
        event.app.exit(result="move_down")

    @bindings.add("K", eager=True)
    def _move_up(event) -> None:
        event.app.exit(result="move_up")

    @bindings.add("t", eager=True)
    def _rename(event) -> None:
        event.app.exit(result="rename_task")

    @bindings.add("s", eager=True)
    def _save(event) -> None:
        event.app.exit(result="save")

    @bindings.add("b", eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _back(event) -> None:
        event.app.exit(result="back")

    @bindings.add("q", eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _quit(event) -> None:
        event.app.exit(result="quit")

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(_tokens, focusable=True, show_cursor=False),
                dont_extend_height=True,
                always_hide_cursor=True,
            )
        ),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
    )
    choice = app.run()
    if choice is None:
        raise click.Abort()
    return str(choice), local_selected


def _edit_plan_prompt(
    *,
    state: LaunchPromptState,
    result: UxLabV3Result,
    selector_fn: SelectFn | None,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> UxLabV3Result:
    copy = _copy(state.config)
    draft = plan_draft_from_result(result)
    selected_index = 0
    status_message = ""
    while True:
        action, selected_index = _select_plan_editor_action(
            state=state,
            draft=draft,
            selected_index=selected_index,
            status_message=status_message,
            selector_fn=selector_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )
        status_message = ""
        if action == "up":
            selected_index = (selected_index - 1) % len(draft.steps)
            continue
        if action == "down":
            selected_index = (selected_index + 1) % len(draft.steps)
            continue
        if action == "edit":
            _edit_step_form_prompt(
                state=state,
                draft=draft,
                step_index=selected_index,
                selector_fn=selector_fn,
                input_fn=input_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            status_message = copy["plan_edit_status_saved"]
            continue
        if action == "insert":
            selected_index = _insert_step_form_prompt(
                state=state,
                draft=draft,
                step_index=selected_index,
                selector_fn=selector_fn,
                input_fn=input_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            status_message = copy["plan_edit_status_inserted"]
            continue
        if action == "delete":
            if delete_step(draft, index=selected_index):
                selected_index = min(selected_index, len(draft.steps) - 1)
                status_message = copy["plan_edit_status_deleted"]
            else:
                status_message = copy["plan_edit_status_delete_blocked"]
            continue
        if action == "move_down":
            selected_index = move_step(draft, index=selected_index, direction=1)
            status_message = copy["plan_edit_status_moved"]
            continue
        if action == "move_up":
            selected_index = move_step(draft, index=selected_index, direction=-1)
            status_message = copy["plan_edit_status_moved"]
            continue
        if action == "rename_task":
            if _use_prompt_toolkit_form(selector_fn=selector_fn, input_fn=input_fn):
                task_result = _prompt_plan_task_form_with_prompt_toolkit(
                    state=state,
                    task=draft.task or state.task,
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
                if task_result is not None:
                    rename_task(draft, task_result)
                    status_message = copy["plan_edit_status_saved"]
                continue
            rename_task(draft, _ask_text_value(copy["plan_edit_task"], default=draft.task or state.task, input_fn=input_fn) or draft.task)
            status_message = copy["plan_edit_status_saved"]
            continue
        if action in {"save", "back"}:
            updated = apply_plan_draft_to_result(draft, result)
            state.task = updated.task
            return updated
        return result


def _execution_target_default_value(state: LaunchPromptState, targets: list[ExecutionTargetOption]) -> str:
    runtime_mode = str(getattr(state.config, "runtime_mode", "tmux") or "tmux").strip().lower()
    if runtime_mode == "tmux" and any(target.key == "tmux" and target.enabled for target in targets):
        return "tmux"
    if runtime_mode == "direct" and any(target.key == "direct" and target.enabled for target in targets):
        return "direct"
    if any(target.key == "direct" and target.enabled for target in targets):
        return "direct"
    return "save" if any(target.key == "save" and target.enabled for target in targets) else "tmux"


def _execution_target_screen_renderable(
    state: LaunchPromptState,
    result: UxLabV3Result,
    *,
    pointed_value: str,
    error_message: str = "",
) -> Group:
    copy = _copy(state.config)
    targets = build_execution_targets(state, result)
    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    parts.append(_step_indicator(state, "review"))
    parts.append(Text())
    parts.append(Text(copy["execution_title"], style=f"bold {_accent_color(state)}"))
    parts.append(Text(copy["execution_hint"], style="dim"))
    if error_message:
        parts.append(Text())
        parts.append(
            Panel(
                Text(error_message, style="#FCA5A5"),
                title=copy["execution_error_title"],
                title_align="left",
                border_style="#F87171",
                expand=True,
            )
        )
    parts.append(Text())
    for target in targets:
        is_pointed = target.key == pointed_value
        prefix = "> " if is_pointed and target.enabled else "  "
        style = _row_label_style(
            is_pointed=is_pointed and target.enabled,
            is_default=target.key == _execution_target_default_value(state, targets),
            provider=_accent_provider(state) if target.key == "tmux" else None,
        )
        if not target.enabled:
            style = "#64748B"
        row = Text.assemble((prefix, ""), (target.label, style))
        if target.badge:
            row.append(f" · {target.badge}", style="#94A3B8")
        parts.append(row)
        parts.append(Text(f"    {target.description}", style="#64748B italic" if not target.enabled else "#64748B"))
    parts.append(Text())
    parts.append(Text(copy["execution_note"], style="dim"))
    parts.append(Text())
    for row in _build_rows(
        [
            MenuItem("b", copy["nav_back"], copy["nav_back_desc"]),
            *( [MenuItem("h", copy["nav_home"], copy["nav_home_desc"])] if state.from_entry else [] ),
            MenuItem("q", copy["quit"], copy["quit_desc"]),
        ],
        pointed_value=pointed_value if pointed_value in {"b", "h", "q"} else "b",
        default_value="b",
        accent_provider=_accent_provider(state),
    ):
        parts.append(_row_text(row))
        if row.description:
            parts.append(Text(f"    {row.description}", style=row.description_style))
    parts.append(Text())
    parts.append(Text(copy["footer"] if state.from_entry else copy["footer_basic"], style="dim"))
    return Group(*parts)


def _start_execution_prompt(
    *,
    state: LaunchPromptState,
    result: UxLabV3Result,
    selector_fn: SelectFn | None,
    console_obj: Console,
    clear_screen: bool,
    error_message: str = "",
) -> str:
    targets = build_execution_targets(state, result)
    enabled_values = [target.key for target in targets if target.enabled]
    values = [*enabled_values, "b", *(["h"] if state.from_entry else []), "q"]
    default_value = _execution_target_default_value(state, targets)
    return _select_screen(
        lambda pointed: _execution_target_screen_renderable(
            state,
            result,
            pointed_value=pointed,
            error_message=error_message,
        ),
        values=values,
        default_value=default_value,
        selector_fn=selector_fn,
        console_obj=console_obj,
        clear_screen=clear_screen,
    )


def _summarize_tmux_launch_error(raw_output: str, *, fallback: str) -> str:
    lines = [line.strip() for line in str(raw_output or "").splitlines() if line.strip()]
    filtered = [line for line in lines if not line.lower().startswith("openai codex v")]
    if filtered:
        return "\n".join(filtered[-6:])
    return fallback


def _build_direct_execution_prompt(
    *,
    task: str,
    controller_plan: dict[str, Any],
    lang: str,
) -> str:
    serialized = json.dumps(controller_plan, indent=2, ensure_ascii=False)
    if lang == "zh-CN":
        return f"""以下是已获用户确认的单 Agent 执行计划，请在当前 Agent 中直接执行。

用户任务:
{task}

执行计划 JSON:
{serialized}

执行要求:
1. 严格按 steps 顺序执行。
2. 仅由当前 Agent 执行，不要再派生 tmux 子 Agent。
3. 每一步都必须满足对应 done_when，再进入下一步。
4. 若步骤里含有 boundary / responsibility_stage / artifact_type / timebox_minutes，必须把它们视为约束。
5. 完成后直接给出可检查的最终结果与必要验证说明。
"""
    return f"""This approved controller-only execution plan has been confirmed by the user. Execute it directly in the current agent.

User task:
{task}

Execution plan JSON:
{serialized}

Execution rules:
1. Follow the steps in order.
2. Execute in the current agent only; do not spawn tmux sub-agents.
3. Satisfy each step's done_when before moving on.
4. Treat boundary / responsibility_stage / artifact_type / timebox_minutes as binding constraints when present.
5. Finish with a checkable final result and concise validation notes.
"""


def _start_tmux_execution(
    *,
    state: LaunchPromptState,
    result: UxLabV3Result,
) -> tuple[bool, str]:
    from ai_collab import cli as cli_module

    launch_result = cli_module._result_for_tmux_launch(result, result.controller_plan)
    if not cli_module._can_launch_tmux(launch_result):
        return False, _copy(state.config)["plan_start_not_ready"]

    capture_buffer = StringIO()
    previous_console = cli_module.console
    cli_module.console = Console(file=capture_buffer, force_terminal=False, color_system=None, width=120)
    try:
        controller_prompt_text = cli_module._build_controller_execution_prompt(
            plan=result.controller_plan or {},
            lang=_lang(state.config),
        )
        previous_cwd = Path.cwd()
        try:
            os.chdir(state.workspace)
            launched = cli_module._launch_tmux_orchestration(
                task=state.task,
                controller=state.controller,
                result=launch_result,
                lang=_lang(state.config),
                controller_prompt_override=controller_prompt_text,
                tmux_target="session",
            )
        finally:
            os.chdir(previous_cwd)
    except Exception as exc:  # noqa: BLE001
        return False, _summarize_tmux_launch_error(capture_buffer.getvalue(), fallback=str(exc))
    finally:
        cli_module.console = previous_console

    if not launched:
        return False, _summarize_tmux_launch_error(
            capture_buffer.getvalue(),
            fallback="tmux runtime did not report a successful start.",
        )
    return True, ""


def _start_direct_execution(
    *,
    state: LaunchPromptState,
    result: UxLabV3Result,
) -> tuple[bool, str]:
    from ai_collab import cli as cli_module

    targets = build_execution_targets(state, result)
    if not any(target.key == "direct" and target.enabled for target in targets):
        return False, (
            "当前计划不能使用直接执行。"
            if _lang(state.config) == "zh-CN"
            else "Current plan is not ready for direct execution."
        )

    controller_plan = result.controller_plan if isinstance(result.controller_plan, dict) else {}
    owners = {
        str(item.get("owner", "")).strip().lower()
        for item in controller_plan.get("steps", [])
        if isinstance(item, dict) and str(item.get("owner", "")).strip()
    }
    single_agent_direct = len(owners) <= 1 and bool(owners)
    task_payload = (
        _build_direct_execution_prompt(
            task=state.task,
            controller_plan=controller_plan,
            lang=_lang(state.config),
        )
        if single_agent_direct
        else None
    )
    direct_result = None
    if not single_agent_direct:
        direct_result = type(
            "_DirectRuntimeResult",
            (),
            {
                "need_collaboration": True,
                "project_categories": [],
                "suggested_skills": [],
                "intent": "",
                "workflow_engine": str(controller_plan.get("workflow_engine", "") or "v2"),
                "session_preset": str(controller_plan.get("session_preset", "") or ""),
                "workflow_blueprint": str(controller_plan.get("workflow_blueprint", "") or ""),
            },
        )()

    exit_code = cli_module._execute_direct_runtime(
        config=state.config,
        provider=state.controller,
        task=state.task,
        result=direct_result,
        controller_plan=controller_plan,
        cwd=state.workspace,
        interactive=False,
        task_payload=task_payload,
    )
    if exit_code != 0:
        detail = str(getattr(cli_module, "_last_direct_runtime_error", lambda: "")()).strip()
        if detail:
            return False, (
                f"直接执行退出码: {exit_code} · {detail}"
                if _lang(state.config) == "zh-CN"
                else f"direct runtime exited with status {exit_code} · {detail}"
            )
        return False, (
            f"直接执行退出码: {exit_code}"
            if _lang(state.config) == "zh-CN"
            else f"direct runtime exited with status {exit_code}"
        )
    return True, ""



def _banner_parts(width: int = 100) -> list[Text]:
    parts: list[Text] = []
    for line in build_init_banner(width):
        style = "bold #7DD3FC" if line != "multi-agent coding orchestrator" else "dim"
        parts.append(Text(line, style=style))
    return parts



def _task_screen_renderable(state: LaunchPromptState) -> Group:
    copy = _copy(state.config)
    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    parts.append(_step_indicator(state, "task"))
    parts.append(Text())
    parts.append(Text(_step_title(state, "task"), style="bold"))
    parts.append(Text(copy["task_step_hint"], style="dim"))
    parts.append(Text(copy["task_workspace_note"].format(workspace=state.workspace), style="dim italic"))
    if state.status_message:
        parts.append(Text(state.status_message, style="yellow"))
    parts.append(Text())
    parts.append(
        Panel(
            Text(_task_preview(state), style="#E2E8F0" if state.task.strip() else "#64748B italic"),
            title=copy["task_editor_title"],
            title_align="left",
            border_style="#334155",
            expand=True,
        )
    )
    parts.append(Text())
    parts.append(Text(copy["task_commands"], style="dim"))
    return Group(*parts)



def _step_screen_renderable(state: LaunchPromptState, step: str, *, pointed_value: str = "1") -> Group:
    copy = _copy(state.config)
    if step == "task":
        return _task_screen_renderable(state)

    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    parts.append(_step_indicator(state, step))
    parts.append(Text())
    parts.append(Text(_step_title(state, step), style=f"bold {_accent_color(state)}"))
    parts.append(Text(copy[f"{step}_step_hint"], style="dim"))
    if step == "controller":
        parts.append(Text(copy["controller_note"].format(task=_task_summary(state)), style="dim italic"))
        rows = _controller_rows(state, pointed_value=pointed_value, include_nav=True)
    elif step == "planner":
        parts.append(Text(copy["controller_note"].format(task=_task_summary(state)), style="dim italic"))
        rows = _planner_rows(state, pointed_value=pointed_value)
    else:
        parts.append(Text())
        parts.extend(_summary_text(state))
        rows = _review_rows(state, pointed_value=pointed_value)
    if state.status_message:
        parts.append(Text(state.status_message, style="yellow"))
    parts.append(Text())
    for row in rows:
        parts.append(_row_text(row))
        if row.description:
            parts.append(Text(f"    {row.description}", style=row.description_style))
    parts.append(Text())
    parts.append(Text(copy["footer"] if state.from_entry else copy["footer_basic"], style="dim"))
    return Group(*parts)



def render_launch_prompt_screen(state: LaunchPromptState, *, pointed_value: str = "1") -> str:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)
    console.print(_step_screen_renderable(state, "task", pointed_value=pointed_value))
    return buffer.getvalue().rstrip() + "\n"



def _review_screen_renderable(
    state: LaunchPromptState,
    result: UxLabV3Result,
    *,
    scroll_offset: int = 0,
    max_body_lines: int | None = None,
    width: int = 120,
) -> Group:
    parts: list[object] = [_review_header_renderable(state), Text()]
    panel_width = max(50, int(width) - 2)
    body_lines = _review_body_lines(state, result, width=panel_width - 3, ansi=False)
    total_lines = len(body_lines)
    if max_body_lines is None:
        visible_lines = body_lines
        resolved_offset = 0
    else:
        visible_lines, resolved_offset, _max_offset = _slice_review_body_lines(
            body_lines,
            scroll_offset=scroll_offset,
            max_lines=max_body_lines,
        )
        start_line = resolved_offset + 1 if total_lines else 0
        end_line = min(total_lines, resolved_offset + max_body_lines) if total_lines else 0
        parts.append(
            _review_scroll_meta_renderable(
                state,
                start_line=start_line,
                end_line=end_line,
                total_lines=total_lines,
            )
        )
        parts.append(Text())
    for line in _review_panel_lines(
        state,
        visible_lines=visible_lines,
        total_lines=total_lines,
        scroll_offset=resolved_offset,
        width=panel_width,
    ):
        parts.append(Text(line))
    parts.append(Text())
    parts.append(_review_actions_renderable(state))
    return Group(*parts)


def _select_review_screen(
    *,
    state: LaunchPromptState,
    result: UxLabV3Result,
    values: list[str],
    default_value: str,
    selector_fn: SelectFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    if selector_fn is not None or not sys.stdin.isatty():
        return _select_screen(
            lambda _pointed: _review_screen_renderable(state, result),
            values=values,
            default_value=default_value,
            selector_fn=selector_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    scroll_offset = 0
    app: Application[str] | None = None

    def _geometry() -> tuple[int, int, int, int, int]:
        assert app is not None
        size = app.output.get_size()
        width = max(70, int(size.columns) - 2)
        header_lines = _render_lines(_review_header_renderable(state), width=width, ansi=False)
        action_lines = _render_lines(_review_actions_renderable(state), width=width, ansi=False)
        meta_lines = _render_lines(
            _review_scroll_meta_renderable(
                state,
                start_line=1,
                end_line=1,
                total_lines=1,
            ),
            width=width,
            ansi=False,
        )
        body_lines = _review_body_lines(state, result, width=width - 5, ansi=False)
        body_height = max(6, int(size.rows) - len(header_lines) - len(action_lines) - len(meta_lines) - 5)
        return width, int(size.rows), body_height, len(body_lines), len(action_lines)

    def _max_scroll() -> int:
        _width, _rows, body_height, body_total, _action_count = _geometry()
        return max(0, body_total - body_height)

    def _scroll(delta: int) -> None:
        nonlocal scroll_offset
        scroll_offset = max(0, min(scroll_offset + delta, _max_scroll()))

    def _page_scroll(direction: int) -> None:
        _width, _rows, body_height, _body_total, _action_count = _geometry()
        _scroll(max(1, body_height - 2) * direction)

    def _tokens() -> list[tuple[str, str]]:
        nonlocal scroll_offset
        assert app is not None
        width, _rows, body_height, _body_total, _action_count = _geometry()
        header_lines = _render_lines(_review_header_renderable(state), width=width, ansi=True)
        panel_width = max(50, width - 2)
        body_lines = _review_body_lines(state, result, width=panel_width - 3, ansi=True)
        visible_lines, resolved_offset, _max_offset = _slice_review_body_lines(
            body_lines,
            scroll_offset=scroll_offset,
            max_lines=body_height,
        )
        scroll_offset = resolved_offset
        total_lines = len(body_lines)
        start_line = resolved_offset + 1 if total_lines else 0
        end_line = min(total_lines, resolved_offset + body_height) if total_lines else 0
        meta_lines = _render_lines(
            _review_scroll_meta_renderable(
                state,
                start_line=start_line,
                end_line=end_line,
                total_lines=total_lines,
            ),
            width=width,
            ansi=True,
        )
        panel_lines = _review_panel_lines(
            state,
            visible_lines=visible_lines,
            total_lines=total_lines,
            scroll_offset=resolved_offset,
            width=panel_width,
        )
        action_lines = _render_lines(_review_actions_renderable(state), width=width, ansi=True)
        page_lines = [
            *header_lines,
            "",
            *meta_lines,
            "",
            *panel_lines,
            *([""] * max(0, body_height + 2 - len(panel_lines))),
            "",
            *action_lines,
        ]
        return list(to_formatted_text(ANSI("\n".join(page_lines))))

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _scroll(1)
        event.app.invalidate()

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _scroll(-1)
        event.app.invalidate()

    @bindings.add("j", eager=True)
    def _j(event) -> None:
        _scroll(1)
        event.app.invalidate()

    @bindings.add("k", eager=True)
    def _k(event) -> None:
        _scroll(-1)
        event.app.invalidate()

    @bindings.add(Keys.PageDown, eager=True)
    def _page_down(event) -> None:
        _page_scroll(1)
        event.app.invalidate()

    @bindings.add(Keys.PageUp, eager=True)
    def _page_up(event) -> None:
        _page_scroll(-1)
        event.app.invalidate()

    @bindings.add(Keys.Home, eager=True)
    def _home_key(event) -> None:
        nonlocal scroll_offset
        scroll_offset = 0
        event.app.invalidate()

    @bindings.add(Keys.End, eager=True)
    def _end_key(event) -> None:
        nonlocal scroll_offset
        scroll_offset = _max_scroll()
        event.app.invalidate()

    @bindings.add(Keys.ScrollDown, eager=True)
    def _scroll_down(event) -> None:
        _scroll(3)
        event.app.invalidate()

    @bindings.add(Keys.ScrollUp, eager=True)
    def _scroll_up(event) -> None:
        _scroll(-3)
        event.app.invalidate()

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result="1")

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

    if "2" in values:
        @bindings.add("e", eager=True)
        @bindings.add("E", eager=True)
        def _edit(event) -> None:
            event.app.exit(result="2")

    if "3" in values:
        @bindings.add("s", eager=True)
        @bindings.add("S", eager=True)
        def _save(event) -> None:
            event.app.exit(result="3")

    if "b" in values:
        @bindings.add("b", eager=True)
        def _back(event) -> None:
            event.app.exit(result="b")

    if "h" in values:
        @bindings.add("h", eager=True)
        def _go_home(event) -> None:
            event.app.exit(result="h")

    for value in ("1", "2", "3"):
        if value in values:
            @bindings.add(value, eager=True)
            def _pick(event, value=value) -> None:
                event.app.exit(result=value)

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(_tokens, focusable=True, show_cursor=False),
                always_hide_cursor=True,
            )
        ),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=True,
    )
    choice = app.run()
    if choice is None:
        raise click.Abort()
    return str(choice)


def _planning_error_screen_renderable(state: LaunchPromptState, result: UxLabV3Result, *, pointed_value: str = "b") -> Group:
    copy = _copy(state.config)
    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    parts.append(_step_indicator(state, "planner"))
    parts.append(Text())
    parts.append(Text(copy["planning_error_title"], style="bold #F87171"))
    parts.append(Text(copy["planning_error_hint"], style="dim"))
    parts.append(Text())
    parts.extend(_summary_text(state))
    parts.append(Text())
    parts.append(Text(result.error_message or "Unknown planning error", style="#FCA5A5"))
    parts.append(Text())
    items = [MenuItem("b", copy["planning_error_back"], copy["planning_error_back_desc"])]
    if state.from_entry:
        items.append(MenuItem("h", copy["nav_home"], copy["nav_home_desc"]))
    items.append(MenuItem("q", copy["quit"], copy["quit_desc"]))
    for row in _build_rows(
        items,
        pointed_value=pointed_value,
        default_value="b",
        accent_provider=_accent_provider(state),
    ):
        parts.append(_row_text(row))
        if row.description:
            parts.append(Text(f"    {row.description}", style=row.description_style))
    parts.append(Text())
    parts.append(Text(copy["footer"] if state.from_entry else copy["footer_basic"], style="dim"))
    return Group(*parts)



def _result_screen_renderable(state: LaunchPromptState, result: UxLabV3Result, *, runtime_label: str) -> Group:
    copy = _copy(state.config)
    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    if result.status == "started":
        parts.append(Text(copy["execution_result_started_title"], style="bold green"))
        parts.append(Text(copy["execution_result_started_hint"], style="dim"))
    else:
        parts.append(Text(copy["execution_result_saved_title"], style="bold green"))
        parts.append(Text(copy["execution_result_saved_hint"], style="dim"))
    parts.append(Text())
    parts.append(Text(f"{copy['execution_result_runtime']} · {runtime_label}", style="#CBD5E1"))
    if result.bundle_path is not None:
        parts.append(Text(f"{copy['execution_result_path']} · {result.bundle_path}", style="#CBD5E1"))
    parts.append(Text(f"{copy['sent_controller']} · {_controller_label(state)}", style="#CBD5E1"))
    parts.append(Text(f"{copy['sent_task']} · {_task_summary(state)}", style="#CBD5E1"))
    return Group(*parts)



def _select_screen(
    render_fn,
    *,
    values: list[str],
    default_value: str,
    selector_fn: SelectFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    if selector_fn is not None:
        if clear_screen:
            console_obj.clear()
        console_obj.print(render_fn(default_value), end="")
        return selector_fn(screen="menu", choices=values, default_value=default_value)

    if not sys.stdin.isatty():
        if clear_screen:
            console_obj.clear()
        console_obj.print(render_fn(default_value), end="")
        return Prompt.ask("Select", choices=values, default=default_value)

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    pointed_index = values.index(default_value) if default_value in values else 0

    def _move(offset: int) -> None:
        nonlocal pointed_index
        pointed_index = (pointed_index + offset) % len(values)

    def _current_value() -> str:
        return values[pointed_index]

    def _tokens() -> list[tuple[str, str]]:
        local_buffer = StringIO()
        width, _height = _terminal_shape()
        render_console = Console(
            file=local_buffer,
            force_terminal=True,
            color_system="truecolor",
            width=width,
            no_color=False,
        )
        render_console.print(render_fn(_current_value()), end="")
        ansi = local_buffer.getvalue()
        return list(to_formatted_text(ANSI(ansi)))

    bindings = KeyBindings()

    @bindings.add(Keys.Down, eager=True)
    def _down(event) -> None:
        _move(1)
        event.app.invalidate()

    @bindings.add(Keys.Up, eager=True)
    def _up(event) -> None:
        _move(-1)
        event.app.invalidate()

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        event.app.exit(result=_current_value())

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="q")

    @bindings.add("q", eager=True)
    def _quit(event) -> None:
        event.app.exit(result="q")

    if "b" in values:
        @bindings.add("b", eager=True)
        def _back(event) -> None:
            event.app.exit(result="b")

    if "h" in values:
        @bindings.add("h", eager=True)
        def _home(event) -> None:
            event.app.exit(result="h")

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(_tokens, focusable=True, show_cursor=False),
                dont_extend_height=True,
                always_hide_cursor=True,
            )
        ),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
    )
    choice = app.run()
    if choice is None:
        raise click.Abort()
    return str(choice)



def _resolve_editor_command(editor: str) -> list[str] | None:
    candidates = [editor]
    if editor == "vim":
        candidates.append("vi")
    for candidate in candidates:
        if shutil.which(candidate):
            return [candidate]
    return None



def _open_task_in_editor(*, editor: str, seed_text: str) -> tuple[str | None, str | None]:
    editor_cmd = _resolve_editor_command(editor)
    if editor_cmd is None:
        return None, "missing"

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
            temp_path = Path(handle.name)
            handle.write(seed_text)
            if seed_text and not seed_text.endswith("\n"):
                handle.write("\n")
        subprocess.run([*editor_cmd, str(temp_path)], check=False)
        return temp_path.read_text(encoding="utf-8").strip(), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)



def _strip_done_command(text: str) -> str | None:
    stripped = text.rstrip()
    if not stripped:
        return None
    lines = stripped.splitlines()
    if not lines:
        return None
    if lines[-1].strip().lower() != "/done":
        return None
    content = "\n".join(lines[:-1]).strip()
    return content



def _render_task_header_ansi(state: LaunchPromptState) -> str:
    local_buffer = StringIO()
    render_console = Console(
        file=local_buffer,
        force_terminal=True,
        color_system="truecolor",
        width=120,
        no_color=False,
    )
    parts: list[object] = []
    parts.extend(_banner_parts())
    parts.append(Text())
    parts.append(_step_indicator(state, "task"))
    parts.append(Text())
    parts.append(Text(_step_title(state, "task"), style="bold"))
    parts.append(Text(_copy(state.config)["task_workspace_note"].format(workspace=state.workspace), style="dim italic"))
    if state.status_message:
        parts.append(Text(state.status_message, style="yellow"))
    parts.append(Text())
    render_console.print(Group(*parts), end="")
    return local_buffer.getvalue()



def _prompt_task_with_prompt_toolkit(
    state: LaunchPromptState,
    *,
    console_obj: Console,
    clear_screen: bool,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.menus import CompletionsMenu
    from prompt_toolkit.widgets import Frame, TextArea

    copy = _copy(state.config)

    class _SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):  # noqa: ANN001
            current = document.current_line_before_cursor.strip().lower()
            for command, description in _matching_task_commands(state, current):
                yield Completion(command, start_position=-len(current), display=command, display_meta=description)

    text_area = TextArea(
        text=state.task,
        multiline=True,
        wrap_lines=True,
        focus_on_click=False,
        scrollbar=True,
        completer=_SlashCommandCompleter(),
        complete_while_typing=True,
        height=12,
        style="bg:#0F172A #E2E8F0",
    )

    def _header_tokens() -> list[tuple[str, str]]:
        return list(to_formatted_text(ANSI(_render_task_header_ansi(state))))

    def _toolbar_tokens() -> list[tuple[str, str]]:
        current = text_area.document.current_line_before_cursor.strip()
        return [("fg:#64748B", _task_toolbar_message(state, current))]

    def _command_from_buffer() -> str | None:
        candidate = text_area.text.strip().lower()
        available = {command for command, _description in _task_command_specs(state)}
        return candidate if candidate in available else None

    def _done_payload() -> str | None:
        return _strip_done_command(text_area.text)

    @Condition
    def _has_completion_menu() -> bool:
        return text_area.buffer.complete_state is not None

    bindings = KeyBindings()

    @bindings.add("tab", eager=True)
    def _tab(event) -> None:
        if text_area.buffer.complete_state is not None:
            text_area.buffer.complete_next()
            return
        current = text_area.document.current_line_before_cursor.strip()
        if current.startswith("/"):
            text_area.buffer.start_completion(select_first=True)
            return
        text_area.buffer.insert_text("    ")

    @bindings.add("s-tab", eager=True)
    def _shift_tab(event) -> None:
        if text_area.buffer.complete_state is not None:
            text_area.buffer.complete_previous()

    @bindings.add(Keys.Down, filter=_has_completion_menu, eager=True)
    def _completion_down(event) -> None:
        text_area.buffer.complete_next()

    @bindings.add(Keys.Up, filter=_has_completion_menu, eager=True)
    def _completion_up(event) -> None:
        text_area.buffer.complete_previous()

    @bindings.add(Keys.ControlD, eager=True)
    def _submit(event) -> None:
        event.app.exit(result=text_area.text)

    @bindings.add(Keys.ControlM, eager=True)
    def _enter(event) -> None:
        if text_area.buffer.complete_state and text_area.buffer.complete_state.current_completion is not None:
            text_area.buffer.apply_completion(text_area.buffer.complete_state.current_completion)
            return
        command = _command_from_buffer()
        if command in {"/nano", "/vim", "/back", "/home", "/quit"}:
            event.app.exit(result=command)
            return
        done_payload = _done_payload()
        if done_payload is not None:
            event.app.exit(result=done_payload)
            return
        text_area.buffer.insert_text("\n")

    @bindings.add(Keys.ControlC, eager=True)
    @bindings.add(Keys.Escape, eager=True)
    def _abort(event) -> None:
        event.app.exit(result="/quit")

    body = FloatContainer(
        content=HSplit(
            [
                Window(FormattedTextControl(_header_tokens), dont_extend_height=True),
                Frame(text_area, title=copy["task_editor_title"]),
                Window(FormattedTextControl(_toolbar_tokens), height=1),
            ]
        ),
        floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=8))],
    )

    if clear_screen:
        console_obj.clear()

    app = Application(
        layout=Layout(body),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
    )
    result = app.run()
    if result is None:
        raise click.Abort()
    return str(result)

def _prompt_task_text(
    state: LaunchPromptState,
    *,
    input_fn: TextInputFn | None,
    console_obj: Console,
    clear_screen: bool,
) -> str | None:
    copy = _copy(state.config)

    while True:
        if input_fn is not None or not sys.stdin.isatty():
            if clear_screen:
                console_obj.clear()
            console_obj.print(_task_screen_renderable(state), end="")
            ask = input_fn or Prompt.ask
            raw_value = str(ask(copy["task_prompt"], default=state.task))
        else:
            raw_value = _prompt_task_with_prompt_toolkit(state, console_obj=console_obj, clear_screen=clear_screen)

        normalized = raw_value.strip().lower()
        if normalized == "/nano":
            updated, error = _open_task_in_editor(editor="nano", seed_text=state.task)
            if error == "missing":
                state.status_message = copy["task_editor_missing"].format(editor="nano")
            elif error:
                state.status_message = copy["task_editor_failed"].format(editor="nano", error=error)
            else:
                state.task = str(updated or "").strip()
                state.status_message = copy["task_editor_loaded"]
            continue
        if normalized == "/vim":
            updated, error = _open_task_in_editor(editor="vim", seed_text=state.task)
            if error == "missing":
                state.status_message = copy["task_editor_missing"].format(editor="vim")
            elif error:
                state.status_message = copy["task_editor_failed"].format(editor="vim", error=error)
            else:
                state.task = str(updated or "").strip()
                state.status_message = copy["task_editor_loaded"]
            continue
        if normalized == "/back":
            return "back"
        if normalized == "/home":
            return "home"
        if normalized == "/quit":
            return "quit"

        submitted = _strip_done_command(raw_value)
        if submitted is None:
            submitted = raw_value.strip()
        if submitted:
            state.task = submitted
            state.status_message = ""
            return submitted

        state.status_message = copy["task_required"]



def run_launch_prompt(
    *,
    config: Config,
    cwd: Path,
    workspace: Optional[Path] = None,
    controller: Optional[str] = None,
    task: Optional[str] = None,
    task_file: Optional[Path] = None,
    planner_mode: str = "live",
    output_bundle: Optional[Path] = None,
    input_fn: TextInputFn | None = None,
    selector_fn: SelectFn | None = None,
    console_obj: Optional[Console] = None,
    clear_screen: bool = True,
    from_entry: bool = False,
) -> Optional[UxLabV3Result | str]:
    console_obj = console_obj or Console()
    initial_task = task
    if task_file is not None:
        initial_task = Path(task_file).expanduser().read_text(encoding="utf-8").strip()
    state = LaunchPromptState.from_config(
        config,
        cwd=Path(cwd),
        workspace=workspace,
        controller=controller,
        task=initial_task,
        planner_mode=planner_mode,
        output_bundle=output_bundle,
        from_entry=from_entry,
    )
    step = "task"

    while True:
        if step == "task":
            task_result = _prompt_task_text(state, input_fn=input_fn, console_obj=console_obj, clear_screen=clear_screen)
            if task_result == "back":
                return "back" if state.from_entry else None
            if task_result == "home":
                return "home" if state.from_entry else None
            if task_result == "quit" or task_result is None:
                return None
            step = "controller"
            continue

        if step == "controller":
            values = ["1", "2", "3"] + (["b", "h"] if state.from_entry else []) + ["q"]
            choice = _select_screen(
                lambda pointed: _step_screen_renderable(state, "controller", pointed_value=pointed),
                values=values,
                default_value={"codex": "1", "claude": "2", "gemini": "3"}.get(state.controller, "1"),
                selector_fn=selector_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if choice in {"1", "2", "3"}:
                state.controller = {"1": "codex", "2": "claude", "3": "gemini"}[choice]
                step = "planner"
                continue
            if choice == "b":
                step = "task"
                continue
            if choice == "h":
                return "home" if state.from_entry else None
            return None

        if step == "planner":
            values = ["1", "2"] + (["b", "h"] if state.from_entry else []) + ["q"]
            choice = _select_screen(
                lambda pointed: _step_screen_renderable(state, "planner", pointed_value=pointed),
                values=values,
                default_value="2" if state.planner_mode == "mock" else "1",
                selector_fn=selector_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if choice == "1":
                state.planner_mode = "live"
                step = "review"
                continue
            if choice == "2":
                state.planner_mode = "mock"
                step = "review"
                continue
            if choice == "b":
                step = "controller"
                continue
            if choice == "h":
                return "home" if state.from_entry else None
            return None

        values = ["1"] + (["b", "h"] if state.from_entry else []) + ["q"]
        choice = _select_screen(
            lambda pointed: _step_screen_renderable(state, "review", pointed_value=pointed),
            values=values,
            default_value="1",
            selector_fn=selector_fn,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )
        if choice == "b":
            step = "planner"
            continue
        if choice == "h":
            return "home" if state.from_entry else None
        if choice == "q":
            return None

        result = _run_planning_with_progress(
            state=state,
            config=config,
            console_obj=console_obj,
            clear_screen=clear_screen,
        )
        if result.status == "error":
            error_values = ["b"] + (["h"] if state.from_entry else []) + ["q"]
            error_choice = _select_screen(
                lambda pointed: _planning_error_screen_renderable(state, result, pointed_value=pointed),
                values=error_values,
                default_value="b",
                selector_fn=selector_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if error_choice == "b":
                step = "planner"
                continue
            if error_choice == "h":
                return "home" if state.from_entry else None
            return None
        if result.status != "planned":
            return result

        while True:
            review_values = ["1", "2", "3", "b"] + (["h"] if state.from_entry else []) + ["q"]
            review_choice = _select_review_screen(
                state=state,
                result=result,
                values=review_values,
                default_value="1",
                selector_fn=selector_fn,
                console_obj=console_obj,
                clear_screen=clear_screen,
            )
            if review_choice == "b":
                break
            if review_choice == "h":
                return "home" if state.from_entry else None
            if review_choice == "q":
                return None
            if review_choice == "2":
                result = _edit_plan_prompt(
                    state=state,
                    result=result,
                    selector_fn=selector_fn,
                    input_fn=input_fn,
                    console_obj=console_obj,
                    clear_screen=clear_screen,
                )
                continue
            if review_choice == "1":
                execution_error = ""
                while True:
                    start_choice = _start_execution_prompt(
                        state=state,
                        result=result,
                        selector_fn=selector_fn,
                        console_obj=console_obj,
                        clear_screen=clear_screen,
                        error_message=execution_error,
                    )
                    if start_choice == "b":
                        break
                    if start_choice == "h":
                        return "home" if state.from_entry else None
                    if start_choice == "q":
                        return None
                    if start_choice == "tmux":
                        launched, execution_error = _start_tmux_execution(state=state, result=result)
                        if not launched:
                            continue
                        started = UxLabV3Result(
                            status="started",
                            workspace=state.workspace,
                            controller=state.controller,
                            task=state.task,
                            lang=_lang(state.config),
                            planner_mode=state.planner_mode,
                            plan=result.plan,
                            controller_plan=result.controller_plan,
                        )
                        if clear_screen:
                            console_obj.clear()
                        console_obj.print(_result_screen_renderable(state, started, runtime_label=_copy(state.config)["execution_tmux"]), end="")
                        return started
                    if start_choice == "direct":
                        launched, execution_error = _start_direct_execution(state=state, result=result)
                        if not launched:
                            continue
                        started = UxLabV3Result(
                            status="started",
                            workspace=state.workspace,
                            controller=state.controller,
                            task=state.task,
                            lang=_lang(state.config),
                            planner_mode=state.planner_mode,
                            plan=result.plan,
                            controller_plan=result.controller_plan,
                        )
                        if clear_screen:
                            console_obj.clear()
                        console_obj.print(_result_screen_renderable(state, started, runtime_label=_copy(state.config)["execution_direct"]), end="")
                        return started
                    if start_choice == "save":
                        review_choice = "3"
                        break
                if review_choice != "3":
                    continue

            bundle_path = export_launch_bundle_v3(
                workspace=state.workspace,
                controller=state.controller,
                task=state.task,
                lang=_lang(state.config),
                planner_mode=state.planner_mode,
                plan=result.plan,
                output_path=state.output_bundle,
                controller_plan=result.controller_plan,
            )
            saved = UxLabV3Result(
                status="saved",
                workspace=state.workspace,
                controller=state.controller,
                task=state.task,
                lang=_lang(state.config),
                planner_mode=state.planner_mode,
                plan=result.plan,
                bundle_path=bundle_path,
                controller_plan=result.controller_plan,
            )
            if clear_screen:
                console_obj.clear()
            console_obj.print(_result_screen_renderable(state, saved, runtime_label=_copy(state.config)["execution_save"]), end="")
            return saved
        continue


__all__ = [
    "LaunchPromptState",
    "render_launch_prompt_screen",
    "run_launch_prompt",
    "_build_controller_rows",
]
