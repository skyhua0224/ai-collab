# ai-collab 产品方向（中文草案）

> 运行时默认行为、`init/config` 影响面、任务类别与回退机制，请同时参考 `docs/AI_COLLAB_FULL_FLOW_REFERENCE_ZH.md`。
>
> 默认编排逻辑、职责阶段模型、角色与 skills 基准，请同时参考 `docs/AI_COLLAB_ORCHESTRATION_BASELINE_ZH.md`。
>
> vNext Rust 平台、跨端客户端、安装分发、Python 退场路线，请同时参考 `docs/VNEXT_RUST_PLATFORM_ARCHITECTURE_ZH.md`。

## 1. 定位一句话

`ai-collab` 不应定义为“又一个单 Agent Coding CLI”，而应定义为：

**面向多个 Coding Agent 的编排台（Multi-Agent Coding Orchestrator）。**

它的职责不是替代 Codex、Claude Code、Gemini CLI 本身，而是在这些 Agent 之上提供：

1. 主控选择
2. 子控派发
3. 多 Agent 运行观察
4. 运行中介入与接管
5. 任务恢复与继续执行
6. 最终产物汇总

## 2. 目标用户与典型场景

### 2.1 目标用户

1. 需要同时使用多个 Coding Agent 的个人开发者
2. 需要主控 + 审核 + 设计 + 实现协作流的高级用户
3. 未来可能扩展到小团队或共享协作场景

### 2.2 典型场景

1. 主控负责规划，子控分别负责实现、审查、研究
2. 一个长任务拆成多个可并发子任务
3. 当前 Agent 卡住时切换到其他 Agent 接管
4. 从历史运行中恢复上下文与状态继续执行

## 3. 当前问题的本质

当前项目在体验上容易陷入一个误区：

**把 `init` / `config` 这类启动与设置界面，当成了主产品界面。**

这会导致几个问题：

1. 反复优化的都是 setup surface，而不是用户每天真正使用的主界面
2. 终端 UI 看起来像“配置器”，而不像“指挥台”
3. `tmux` 执行逻辑和产品交互逻辑耦合过深
4. 未来 GUI 会被迫继承不适合 GUI 的结构

## 4. 正式产品分层

建议将 ai-collab 拆成三层：

### 4.1 Orchestration Core

核心领域层，不绑定具体交互界面，也不绑定具体 runtime。

核心对象建议包括：

1. `Run`
2. `Agent`
3. `Plan`
4. `Task`
5. `Event`
6. `Artifact`
7. `ResumeState`
8. `RuntimeBinding`

这一层负责回答：

1. 当前 run 是什么
2. 主控是谁
3. 有哪些 worker
4. 当前步骤和状态如何
5. 有哪些日志、总结、diff、产物
6. 运行是否可恢复

### 4.2 Runtime Backends

runtime 是执行后端，而不是产品界面本身。

建议拆成：

1. `tmux backend`
2. `console backend`
3. 未来的 provider-native backend / GUI backend bridge

其中：

- `tmux backend` 是当前第一优先维护对象
- `console backend` 是新的独立方案，用于未来默认控制台与 GUI 模板

### 4.3 Product Surfaces

面对用户的交互入口建议拆成：

1. `init/config`：薄 CLI / prompt 式 setup
2. `Session Console`：默认主界面（未来 TUI 主入口）
3. `resume/admin`：恢复、排障、运行管理
4. `GUI`：未来图形界面

## 5. 什么应该是默认入口

建议未来默认入口从“启动 setup / 配置向导”切换为：

**`ai-collab` 直接进入 Session Console。**

原因：

1. 用户真正高频进入的是任务协作界面，不是配置界面
2. Session Console 才是产品能力最强、最有辨识度的部分
3. GUI 未来也应该围绕同一套 session model 展开

## 6. Session Console 的职责

Session Console 不是简单聊天框，而是“任务指挥台”。

建议职责：

1. 新建 run
2. 选择 controller
3. 生成或查看计划
4. 将步骤派发给子 Agent
5. 观察多个 Agent 的运行状态
6. 查看某个 Agent 的输出、日志、diff、摘要
7. 接管、取消、重试、恢复
8. 导航到历史 run

## 7. Session Console 的信息架构

建议采用如下结构：

### 顶栏

显示：

1. 当前 workspace
2. 当前 run id / label
3. 当前 controller
4. 当前 runtime backend
5. 当前模式（live/mock 等）

### 左栏：Agents

显示：

1. controller
2. workers
3. 每个 agent 的状态（idle / planning / running / waiting / error / done）
4. 当前选中 agent

### 中央主区：Timeline / Plan / Conversation

显示：

1. run 的关键事件时间线
2. 当前计划步骤
3. 派发历史
4. 系统消息 / 协作消息 / 汇总结论

### 右栏：Inspector

显示选中 agent 的详细内容：

1. 最新输出
2. 最近 diff
3. 日志片段
4. 当前 prompt / handoff 摘要
5. 错误与告警

### 底部输入区

用于：

1. 直接输入自然语言任务
2. 输入 slash commands
3. 执行主控干预

## 8. 命令系统建议

Session Console 内部建议优先采用 slash commands：

1. `/new`
2. `/plan`
3. `/handoff`
4. `/agents`
5. `/watch`
6. `/resume`
7. `/config`
8. `/theme`
9. `/doctor`

原因：

1. 对终端用户而言心智成本低
2. 便于未来 GUI 做命令面板映射
3. 比当前零散子命令更适合作为主产品交互模型

## 9. `tmux` 与新的 Console 必须分离

这是本阶段最重要的架构结论之一。

### 9.1 `tmux` 不应被视为临时方案

`tmux` 方案应继续维护，并在 `init` 重构后优先稳定。它是当前可用的执行后端。

### 9.2 新的 Console 也不应只是 tmux 的皮肤

新的 Session Console 必须是独立的产品 surface，不能仅仅理解为“把 tmux pane 搬到一个界面里”。

Console 应基于统一的 run/event 模型，而不是基于 pane 视图模型。

### 9.3 GUI 不能直接以 tmux pane 为模板

未来 GUI 应复用 Session Console 的领域模型与信息架构，而不是直接复刻 tmux 拆分窗口。

## 10. `init` / `config` 的定位

`init` 和 `config` 的目标不是“产品主界面”，而是：

1. 首次启动引导
2. 基础配置修改
3. provider / runtime / controller 的快速设置
4. 基础诊断与安全确认

因此：

- 可以保留交互式体验
- 但不应该做成重型 fullscreen TUI
- 更适合做成“好看的薄 CLI / prompt 式 setup”

## 11. 为什么不建议继续围绕旧版 `init` TUI 打磨

旧版 `init` TUI 的问题不是单纯视觉，而是产品定位错误：

1. 它让 setup surface 占据了主设计精力
2. 它的交互模型不符合日常高频使用路径
3. 它不适合作为 GUI 的蓝本
4. 它会模糊 runtime backend 与 product surface 的边界

因此建议：

1. 停止把旧 `init` TUI 作为未来主方向
2. 将其降级为实验稿或过渡实现
3. 把设计重心转移到 Session Console 与 runtime backend 分离

## 12. 建议的阶段路线

### Phase 1：薄 CLI init/config

目标：

1. 重做 `init`
2. 重做 `config`
3. 让首次使用和日常修改设置都足够清晰、简洁、美观

### Phase 2：稳定 `tmux backend`

目标：

1. 明确 runtime backend 边界
2. 修复当前 tmux 中的 pane/session/control 问题
3. 为 resume / watch / capture 建立稳定基础

### Phase 3：Session Console Skeleton

目标：

1. 做出真正的默认入口
2. 以 run/event 为核心，而不是 pane 为核心
3. 形成未来 GUI 的模板

### Phase 4：GUI

目标：

1. 多 Agent 同屏
2. 主控 / 子控 / 系统消息分层展示
3. 复用 Session Console 模型

## 13. 对当前代码的直接指导

基于当前仓库，建议这样理解已有能力：

1. `launch` 更接近未来主流程的种子
2. `handoff` / `tmux-*` 更接近 runtime backend 能力
3. `init` / `config` 应缩减为 setup surface
4. `settings` 未来应改为轻量配置入口，而不是主 TUI

## 14. 最终方向总结

一句话总结：

**ai-collab 的主产品不是“配置向导”，也不是“单 Agent 聊天界面”，而是面向多个 Coding Agent 的协作控制台。**

而在这个方向下：

- `tmux` 是 backend
- `Session Console` 是 primary surface
- `init/config` 是 bootstrap surface
- `GUI` 是未来对同一模型的图形化展开
