# ai-collab 全流程与默认行为参考（中文）

> 面向未来优化的默认编排基准、职责路由与角色 / skills 设计，请同时参考 `docs/AI_COLLAB_ORCHESTRATION_BASELINE_ZH.md`。

## 1. 文档目的

这份文档记录 **ai-collab 当前代码中的真实默认行为**，覆盖：

1. `init` 首次初始化会设置什么
2. `config` 中每类配置会影响什么
3. 默认任务类别、触发器、workflow、Agent 分工
4. 默认回退与接管流程
5. 在“全部使用默认值”时，系统实际会怎样运行

这份文档强调两件事：

1. **区分“产品期望”与“当前实现”**
2. **尽量给出对所有任务类型都通用的理解框架**

也就是说，它不仅适用于全栈开发，也适用于：

- 前端
- 后端
- 测试
- 游戏开发
- 原型设计
- 调试修复
- 文档写作
- 调研分析
- 其他非纯开发型任务

## 2. 三层默认值：要先分清

理解 ai-collab 时，必须先分清 3 层默认值：

### 2.1 模板默认值（正常首次初始化会用到）

这是 `config/config.template.json` 提供的值。

**正常用户第一次运行并初始化成功后，实际最常用的是这一层。**

当前模板默认值核心是：

- `ui_language = en-US`
- `entry_surface = guided`
- `runtime_mode = tmux`
- `current_controller = codex`
- 3 个 provider 默认全启用
- `auto_collaboration` 默认开启
- `controller_first = true`
- `planner_first = true`

### 2.2 内建 fallback 默认值（模板不可用时）

这是 `Config.create_default()` 里的回退值。

它主要用于：

- 模板不存在
- 测试
- 某些极端 fallback 场景

这一层和模板有一个重要差异：

- fallback 默认 `current_controller = claude`

所以：

- **正常初始化后的实际默认主控更接近 `codex`**
- **只有 fallback 路径才更接近 `claude`**

### 2.3 每次 run 的临时选择

真正创建 run 时，还会叠加：

- 当前 workspace
- 当前 task
- 当前 controller
- 当前 planner mode
- 当前可用 provider
- 当前 project profile / intent / trigger

所以 ai-collab 的最终行为不是“死配置”，而是：

**模板默认值 + 用户 config + 当前 run 上下文**

## 3. `init`：它到底设置了什么

`init` 的定位是 **全局 bootstrap**，不是运行时指挥台。

它当前主要设置这些字段：

### 3.1 界面语言

影响：

- 启动界面
- 配置菜单
- 新任务流程
- 规划失败/预览等终端文案

不影响：

- 实际模型能力
- 路由策略本身

### 3.2 默认主控 `current_controller`

影响：

- 新 run 默认由谁担任 controller
- 如果用户没有显式指定 controller，会优先使用它
- 在某些 strengths fallback 场景里，当前 controller 会带有轻微优先级

不等于：

- 所有步骤都必须交给它
- 它一定是主实现者

### 3.3 启用哪些 Agent / provider

影响非常大：

- 直接决定 planner 能看到哪些 Agent
- 直接限制 orchestrator 可分配对象
- 某个 Agent 没启用时，所有相关角色都会退化给其他 Agent

这是最“硬”的开关之一。

### 3.4 默认 runtime

当前主要是：

- `tmux`
- `direct`

影响：

- run 最终通过哪种执行后端运行

不直接影响：

- 哪个 Agent 负责哪类任务
- 模型路由优先级

### 3.5 默认入口 `entry_surface`

当前主要是：

- `guided`
- `command`

影响：

- 用户如何进入新任务与恢复流程

不直接影响：

- Agent 分工
- workflow
- 回退逻辑

### 3.6 是否默认开启自动协作

这是影响行为的关键开关。

如果开启：

- 新任务会先走 detector / planner / orchestration
- controller 会决定是否需要子 Agent

如果关闭：

- 新任务更偏 controller-only
- 必须由用户手动进行后续派发

## 4. `config`：哪些选项会真正影响实际 AI 使用

`config` 可以理解成“长期默认值编辑器”。

要点不是“有哪些选项”，而是“哪些选项真的会影响运行”。

## 4.1 Daily defaults：高影响、直接生效

这一组是最值得关注的。

### 4.1.1 Enabled agents

影响等级：**最高**

真实效果：

- 限制 planner 的可见 Agent 池
- 限制 orchestrator 的可分配对象
- 让某些角色被迫退化给其他 Agent

### 4.1.2 Current controller

影响等级：**高**

真实效果：

- 新 run 默认 controller
- 无显式 controller 时的默认 leader

注意：

- 它是“顶层主控默认值”
- 不是“所有实现都必须由该 Agent 完成”

### 4.1.3 Runtime mode

影响等级：**高**

真实效果：

- 决定 run 用 `tmux` 还是 `direct`

它主要影响执行 surface，不是分工逻辑。

### 4.1.4 Entry surface

影响等级：**中**

真实效果：

- 决定默认进入 guided 还是 command-first

主要是 UX 影响，不是协作逻辑影响。

### 4.1.5 Collaboration preset

影响等级：**高**

当前系统支持这些 preset：

- `auto-route`
- `coding-lead`
- `architecture-lead`
- `debug-lead`
- `design-lead`
- `research-lead`
- `custom`

当前实现里，preset 会参与生成一组“角色 lead 值”，即：

- research lead
- architecture lead
- implementation lead
- testing lead

但还要注意：

- **preset 不是最终唯一真相**
- `routing.intent_preferences` 会覆盖掉 preset 对这几个 intent 的 lead 结果

也就是说：

**preset 提供高层默认风格，intent preferences 提供更底层、更硬的任务类型路由。**

## 4.2 Routing & collaboration：最关键的真实分工层

这一组最直接决定“什么任务优先给谁”。

### 4.2.1 `routing.intent_preferences`

这是当前最重要的实际路由配置之一。

当前推荐顺序是：

- `implementation` → `codex`, `claude`, `gemini`
- `codebase_understanding` → `claude`, `codex`, `gemini`
- `research` → `gemini`, `claude`, `codex`
- `architecture` → `gemini`, `claude`, `codex`
- `testing` → `claude`, `codex`, `gemini`
- `multimodal` → `gemini`, `claude`, `codex`

这意味着当前通用产品策略是：

- 研究/方案/设计探索：`Gemini` 优先
- 主实现：`Codex` 优先
- 测试/验收/质量：`Claude` 优先

### 4.2.2 `cost_bias`

当前状态：

- 字段已存在
- config 菜单可编辑
- 文案完整

但在当前代码里，它的运行时影响仍然有限。

可以把它理解为：

- **配置层已准备好**
- **未来会更强影响路由**
- **当前不是最主要的实际决策因子**

## 4.3 Models & billing：有些会生效，有些目前偏“预留位”

### 4.3.1 provider model selection

这组是会真实生效的。

当前每家 provider 的默认模型/档位大致是：

- `Codex`
  - 模型：`gpt-5.4`
  - 默认 thinking：`high`
- `Claude`
  - 默认：`claude-sonnet-4-6`
- `Gemini`
  - 模板默认：`powerful`
  - 对应 `gemini-3.1-pro-preview`

这些会直接进入 `ModelSelector`。

### 4.3.2 economics / billing / quota / cross-provider fallback

当前状态要诚实说明：

- 配置层很完整
- 菜单也能改
- 字段会被保存

但是：

- 当前运行时对它们的使用仍然不算深入
- 它们还没有成为实际路由的主导因素

所以当前应理解为：

- **这是未来成本感知路由的基础**
- **不是当前行为的第一决定因素**

## 4.4 Application settings

这组主要影响：

- 语言
- 更新检查
- about / 展示类内容

不是协作核心。

## 5. 当前通用 Agent 分工：要按“任务阶段”理解

要想让 ai-collab 在“前端 / 后端 / 游戏 / 文档 / 调研 / 测试 / 非开发任务”里都成立，最稳妥的理解方式不是按技术栈分，而是按 **任务阶段** 分。

### 5.1 Gemini：方案、设计、原型、架构、探索

当前更适合它的通用任务是：

- 前端设计
- mockup
- demo HTML / 初稿页面
- UI/UX 方案
- 技术选型
- 架构设计
- 编程方案
- 模块骨架
- 生态调研
- 替代方案比较
- 游戏玩法设计
- 非开发类 research / analysis

一句话：

**Gemini 更像“前期定义与方案探索负责人”。**

### 5.2 Codex：主实现、联调、重构、正式开发

当前更适合它的通用任务是：

- 前端正式实现
- 后端正式实现
- 系统主逻辑开发
- 跨文件修改
- 集成与联调
- 主线 bug fix
- 需要真正把东西做出来的工程任务
- 拿到明确任务后直接执行

一句话：

**Codex 更像“主执行者 / 主开发者”。**

### 5.3 Claude：验收、审查、测试、质量驱动的小修补

当前更适合它的通用任务是：

- 代码审查
- 风险评估
- 回归测试
- 验收结论
- 质量补洞
- 文档结构整理
- trade-off 梳理
- 审查后的小修补

一句话：

**Claude 更像“质量守门 + 审核收敛负责人”。**

## 6. 任务类型与默认类别：系统如何认出“你在做什么”

当前默认 project profile 主要有：

- `docs-text`
- `superapp-fullstack`
- `macos-swift`
- `mobile-native`
- `systems-tooling`
- `game-dev`

这些由 `ProjectProfiler` 根据仓库文件结构自动推断。

### 6.1 docs-text

适合：

- 文档
- 博客
- 内容型项目

默认更容易进入：

- `docs-writing`
- `research`

### 6.2 superapp-fullstack

适合：

- 有 `admin/backend/frontend/client/web` 等复合目录的项目

默认更容易进入：

- `fullstack-superapp`
- `implementation`
- `architecture`
- `visual-design`

### 6.3 macos-swift

适合：

- Swift / Package.swift / xcodeproj 等项目

### 6.4 mobile-native

适合：

- iOS / Android 原生项目

### 6.5 systems-tooling

适合：

- Python / Node / Rust / Shell / Makefile / CLI 工具

### 6.6 game-dev

适合：

- Unity
- Unreal
- Ren'Py

## 7. 默认 trigger → workflow：当前真实内置模板

这一层非常重要，因为它会把“类别/intent”进一步变成具体 workflow。

当前模板里主要映射如下：

| trigger | workflow | primary | reviewers |
| --- | --- | --- | --- |
| `visual-design` | `design-review` | `gemini` | `claude` |
| `architecture` | `architecture-review` | `claude` | `codex`, `gemini` |
| `implementation` | `code-review` | `codex` | `claude` |
| `fullstack-superapp` | `full-stack` | `codex` | `claude`, `gemini` |
| `macos-native` | `native-macos` | `codex` | `claude`, `gemini` |
| `mobile-native` | `mobile-native` | `codex` | `claude`, `gemini` |
| `systems-tooling` | `systems-tooling` | `codex` | `claude` |
| `game-dev` | `game-dev` | `gemini` | `codex`, `claude` |
| `debugging` | `debug-fix-verify` | `codex` | `claude` |
| `security-audit` | `security-remediation` | `claude` | `codex`, `gemini` |
| `research` | `research-synthesis` | `gemini` | `claude` |
| `testing` | `test-driven` | `codex` | `claude` |
| `docs-writing` | `docs-review` | `claude` | `gemini` |

## 8. 一个必须诚实记录的事实：当前系统里存在“新旧两套路由”

这是当前 ai-collab 最重要的现实之一。

### 8.1 新策略

我们现在在 routing / orchestrator / live planner prompt 里推动的是：

- `Gemini`：research / architecture / mockup / options
- `Codex`：implementation
- `Claude`：testing / review / quality

### 8.2 旧模板 workflow

但是模板 workflow 里仍然保留一些更早的分工，例如：

- `architecture-review` 仍然以 `Claude` 为 primary
- `testing` 对应 `test-driven`，仍然以 `Codex` 为 primary
- `docs-writing` 仍然以 `Claude` 为 primary

### 8.3 这意味着什么

当前真实行为不是“完全统一的新策略”，而是：

**planner / routing 更偏新策略，但 trigger workflow metadata 仍可能把某些任务拉回旧策略。**

这是当前必须被记录的系统现状。

## 9. 默认回退与接管流程

当前默认回退逻辑可以理解为 5 层：

### 9.1 没开自动协作

如果 `auto_collaboration` 关闭：

- 新任务更偏 controller-only
- 不会主动进入完整多 Agent orchestration

### 9.2 Agent 不可用 / 未启用

如果某个 Agent 没启用：

- 所有该 Agent 的候选职责会被别的已启用 Agent 吞掉

### 9.3 planner 先做角色分配

默认模板里：

- `planner_first = true`
- `controller_first = true`

也就是说：

1. 先做 planning
2. 再由 controller 基于 plan 执行

### 9.4 执行失败时的 phase retry / takeover

默认 escalation policy 是：

- `max_retries = 1`
- `takeover_agent = codex`
- `takeover_after_failures = 2`
- `ask_user_on_repeated_failure = true`
- `stop_on_failure = true`

所以默认含义是：

1. 失败先重试
2. 多次失败后倾向让 `Codex` 接管
3. 如果还是不行，再问用户是否继续/跳过/接管

### 9.5 Claude 的默认边界

默认理解应是：

- `Claude` 可以做验收驱动的小修补
- 一旦问题升级成主实现、重构、架构变化，默认应回 controller 再决定，通常再转 `Codex`

## 10. 在“全部默认值”下，实际最接近什么使用体验

这里说的是 **正常初始化完成后、模板默认值生效** 的情形。

### 10.1 全局默认状态

通常会是：

- controller：`codex`
- runtime：`tmux`
- entry：`guided`
- providers：`codex` + `claude` + `gemini`
- auto collaboration：开启
- planner first：开启
- controller first：开启
- preset：`auto-route`
- routing mode：`recommended`

### 10.2 默认模型状态

- `Codex`：`gpt-5.4` + `high thinking`
- `Claude`：`claude-sonnet-4-6`
- `Gemini`：`gemini-3.1-pro-preview`（powerful）

### 10.3 如果任务很泛，不明显属于某一类

系统通常会：

1. 用 project profiler 识别当前仓库类别
2. 用 planner 生成一个 seed orchestration
3. 从 orchestration roles 推断 intent / trigger
4. 如果需要多 Agent，再决定 workflow / selected agents / primary / reviewers

### 10.4 当前“默认通用倾向”总结

在没有被 legacy workflow 强行改写时，当前最接近的默认通用倾向是：

- 方案 / 原型 / 设计 / 调研 → `Gemini`
- 实现 / 集成 / 主开发 → `Codex`
- 审查 / 测试 / 验收 / 风险收敛 → `Claude`

## 11. 典型任务的默认理解（面向广泛任务）

### 11.1 前端设计 / mockup / demo HTML

默认应理解为：

- `Gemini` 主导
- `Claude` 审查
- `Codex` 仅在进入正式实现后主导

### 11.2 前端正式开发

默认应理解为：

- `Codex` 主导实现
- `Claude` 做质量审查
- `Gemini` 只在需要方案/设计补充时重新介入

### 11.3 后端选型 / 架构 / 编程方案

当前通用产品策略应理解为：

- `Gemini` 优先

但要注意：

- 某些 legacy workflow 仍可能把 architecture primary 拉回 `Claude`

### 11.4 后端正式开发

默认应理解为：

- `Codex` 主导

### 11.5 调试修复

默认更接近：

- `Codex` 诊断 + 修复
- `Claude` 验证

### 11.6 测试 / 验收 / 回归

当前新策略应理解为：

- `Claude` 应更偏质量 leader

但 legacy `test-driven` workflow 仍更偏：

- `Codex` 写测试与实现
- `Claude` 做 review/refactor

### 11.7 游戏开发

默认更接近：

- `Gemini` 做玩法、UI flow、节奏设计
- `Codex` 做系统实现
- `Claude` 做 balance / exploit / 风险审查

### 11.8 非开发任务：调研、文档、分析

默认更接近：

- 调研 → `Gemini`
- 综合整理 / 写作结构 → `Claude`
- 执行计划 / 格式化落地 → `Codex`

## 12. 当前最该被长期记住的原则

如果要用一句足够通用的话描述 ai-collab 的默认产品心智，当前最适合写成：

### 12.1 产品原则

- `Gemini` 负责 **先定义问题与方案**
- `Codex` 负责 **把方案真正做出来**
- `Claude` 负责 **把结果审清楚、测清楚、补清楚**

### 12.2 对前端的专门翻译

- 前端设计 / mockup / demo HTML → `Gemini`
- 前端正式实现 → `Codex`
- 前端验收 / 可用性 / 回归 / 补丁 → `Claude`

### 12.3 对后端的专门翻译

- 后端选型 / 架构 / 方案 / 初始骨架 → `Gemini`
- 后端正式实现 / 集成 / 修复 → `Codex`
- 后端验收 / 风险审查 / 补洞 → `Claude`

## 13. 当前实现中的重要 caveats

最后把几个最关键的现实 caveat 单独列出来：

1. **模板默认主控是 `codex`，fallback 默认主控是 `claude`**
2. **新 routing 策略与旧 workflow 模板仍未完全统一**
3. **计费 / quota / cost bias 已有配置界面，但运行时影响仍有限**
4. **current controller 是 run 的默认 leader，不等于所有编码都归它**
5. **Claude 默认不是主实现者，而是质量驱动的小修补者**
6. **一旦问题升级成重构 / 架构变更 / 跨模块主修复，默认应回 controller 重新分派，通常转给 `Codex`**

## 14. 建议把它当作什么

这份文档建议被当作：

- 当前 ai-collab 的 **运行时语义参考**
- 未来统一 routing / workflow / prompt 时的 **校准基线**
- 讨论“某类任务到底该给谁”时的 **公共语言**

如果未来继续演进，优先应保持三件事一致：

1. `preset` 语义
2. `routing.intent_preferences`
3. `workflow templates`

只有这三层统一，ai-collab 才会真正表现出稳定、可预测的多 Agent 协作行为。
