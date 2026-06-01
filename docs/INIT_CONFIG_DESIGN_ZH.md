# ai-collab `init` / `config` 设计草案（中文）

## 1. 设计目标

`init` 和 `config` 的目标不是展示完整产品能力，而是让用户能够：

1. 快速完成首次引导
2. 随时修改常用设置
3. 理解默认行为
4. 在不进入复杂 TUI 的情况下完成配置操作

因此，这两个入口应设计为：

**薄 CLI + 轻交互提示 + 少量明确的选择。**

## 2. 为什么不建议把 `init/config` 做成主 TUI

### 2.1 用户进入频率不够高

用户每天真正停留的地方应是 Session Console，而不是 `init` 或 `config`。

### 2.2 配置是低频操作

低频操作更适合：

1. 简洁 prompt
2. 菜单式选择
3. 命令式修改

而不是长期驻留式界面。

### 2.3 复杂 TUI 会掩盖真正的产品边界

如果 `init/config` 做得像主界面，会让产品重心偏离“多 Agent 编排”本体。

## 3. `init` 的定位

`init` 是 **global bootstrap**，不是 runtime console。

它解决的是：

1. 默认语言
2. 默认主控
3. 默认 runtime backend
4. provider 可用性与默认启用状态
5. 默认协作策略

它不应该承担：

1. run 的创建
2. 多 agent 运行观察
3. 聊天/事件流展示
4. pane 输出浏览

## 4. 推荐的 `init` 流程

推荐将 `init` 压缩为 4 步：

### Step 1：Welcome / 环境说明

目的：说明这次会设置什么，不进入复杂解释。

建议内容：

- 这是全局设置，不是项目内 run 控制台
- 稍后仍可通过 `ai-collab config` 修改
- 本次只会设置默认值，不会启动 Agent 运行

示例：

```text
ai-collab setup
Global bootstrap for multi-agent orchestration.
You can change these settings later with `ai-collab config`.

Enter to continue · Esc to cancel
```

### Step 2：Language

目的：设置界面语言。

建议选项：

1. English (en-US)
2. 中文 (zh-CN)

示例：

```text
ai-collab setup
Step 1/4 · Language
Choose the display language for ai-collab.

❯ 1. English (en-US)
  2. 中文 (zh-CN)

Enter confirm · Esc cancel
```

### Step 3：Controller + Provider Baseline

目的：用尽量少的交互完成最重要的 Agent 默认设置。

建议拆成两个轻问题：

1. 默认主控是谁
2. 启用哪些 provider

但不要展开成复杂表单。

示例：

```text
Step 2/4 · Default controller
Which agent should lead new runs by default?

❯ 1. Codex
  2. Claude
  3. Gemini

Enter confirm · b back · Esc cancel
```

```text
Step 2/4 · Enabled providers
Keep this simple. You can fine-tune models later.

❯ 1. Controller only
  2. Controller + one helper
  3. Enable all available providers

Enter confirm · b back · Esc cancel
```

### Step 4：Runtime Default

目的：明确默认执行后端。

现阶段建议选项：

1. `tmux`（推荐）
2. `console`（未来实验/新交互 backend）
3. `direct`（单终端执行 backend）

注意：

- `console` 在这里是 runtime/backend 维度，不是 init 的 UI 维度
- 这一步的语言必须清楚区分 surface 与 backend

示例：

```text
Step 3/4 · Default runtime
Choose how ai-collab should execute multi-agent runs.

❯ 1. tmux (stable, recommended)
  2. console (new runtime path)
  3. direct (single-terminal backend)

Enter confirm · b back · Esc cancel
```

### Step 5：Review / Finish

目的：展示简洁摘要并写入。

示例：

```text
Step 4/4 · Review
Language .............. 中文 (zh-CN)
Controller ............ Codex
Enabled providers ..... Codex, Claude, Gemini
Default runtime ....... tmux
Auto collaboration .... Enabled

1. Save and finish
2. Go back

Enter confirm · Esc cancel
```

## 5. `init` 不应该出现的东西

1. 大块常驻配置摘要
2. 多栏复杂布局
3. 一屏多个字段同时编辑
4. 很重的 fullscreen TUI 框架感
5. 很多不必要的边框和按钮
6. 技术性过强的字段名

## 6. `config` 的定位

`config` 是 **日常修改默认设置的入口**。

用户不应该因为修改一个语言或主控设置而进入一个沉重界面。

建议 `config` 提供三种方式：

1. `ai-collab config`：交互式菜单
2. `ai-collab config get <key>`：读取值
3. `ai-collab config set <key> <value>`：直接写值

## 7. `config` 应暴露的用户级配置

建议分两层：

### 7.1 第一层：高频用户级配置（优先暴露）

这些应成为主菜单与 `config set/get` 的核心字段。

1. `ui_language`
2. `current_controller`
3. `runtime_mode`
4. `entry_surface`
5. `auto_orchestration`
6. `providers.<name>.enabled`
7. `providers.<name>.model_selection`
8. `theme`（未来）
9. `notifications`（未来）

### 7.2 第二层：高级系统配置（暂不直接暴露到主菜单）

这些存在于配置文件中，但不建议作为第一阶段主交互的一部分：

1. `delegation_strategy`
2. `quality_gate.*`
3. `auto_collaboration.persona_*`
4. `auto_collaboration.phase_completion_criteria`
5. `auto_collaboration.intent_trigger_map`
6. `auto_collaboration.profile_trigger_map`
7. `auto_collaboration.skill_map`
8. `auto_collaboration.triggers`

这些更适合：

1. 直接编辑配置文件
2. 未来做 advanced config 子命令
3. 导入/导出 profile

## 8. 当前代码里已经存在并暴露的配置键

从当前 CLI 实现看，已经明确支持：

1. `auto_orchestration`
2. `ui_language`
3. `current_controller`
4. `entry_surface`
5. `runtime_mode`

这组键适合作为第一阶段的基础配置面。

## 9. 建议的未来配置结构

当前字段可保留，但建议逐步朝更清晰的结构演进：

```json
{
  "ui": {
    "language": "zh-CN",
    "theme": "default"
  },
  "launch": {
    "default_surface": "session-console"
  },
  "runtime": {
    "default_backend": "tmux"
  },
  "agents": {
    "controller": "codex",
    "enabled": ["codex", "claude", "gemini"]
  },
  "collaboration": {
    "auto": true
  }
}
```

这里的目标不是立即重写全部配置模型，而是为未来 GUI 和 Session Console 提前建立更稳定的命名。

## 9.1 协作预设（未来配置层草案）

“如何把任务分配给不同 Coding Agent” 不建议在第一阶段直接暴露为底层 `assignment_map` 编辑器。

原因：

1. 首次初始化阶段不适合让用户理解过多路由细节
2. `primary / reviewers / workflow / triggers` 这类内部结构更适合系统维护，不适合新用户首次配置
3. 真正频繁发生的任务分配，更适合在 Session Console 里按 run 临时调整

因此建议引入一层 **用户可理解的协作预设（collaboration preset）**，作为：

1. `init` 中可选的薄配置（第二阶段再接入）
2. `ai-collab config` 中的高频默认项
3. Session Console 中的 run-level override 基础

建议配置草案：

```json
{
  "collaboration": {
    "auto": true,
    "preset": "auto-route",
    "allow_runtime_override": true
  }
}
```

其中：

- `auto`：是否默认开启自动协作
- `preset`：默认协作预设
- `allow_runtime_override`：是否允许在 Session Console 内临时改派发策略

建议预设名与含义：

1. `auto-route`：按任务自动决定主做与评审
2. `coding-lead`：Codex 主做，Claude 评审，Gemini 按需补充
3. `architecture-lead`：Claude 主控，Codex 落地，Gemini 补充方案
4. `debug-lead`：Codex 主修复，Claude 复盘验证
5. `design-lead`：Gemini 主设计，Codex 实现，Claude 审查
6. `research-lead`：Claude 主写作 / 整理，Gemini 调研补充
7. `custom`：保留当前配置文件中的高级映射，不覆盖

这些预设不直接替代现有的 `auto_collaboration.triggers`、`workflow`、`persona_*` 结构，而是位于它们之上的“用户层入口”。

换句话说：

- 用户在 `init/config` 里看到的是 `preset`
- 系统内部仍然可以继续映射到更复杂的触发器、工作流和 reviewer 规则

### 为什么暂时不接入当前 `init`

当前阶段建议先完成：

1. 语言
2. 启用 Agent
3. 默认主控
4. 默认 runtime
5. 默认入口
6. 自动协作
7. 确认写入

等这条路径足够稳定后，再把 `协作预设` 加为下一阶段步骤。

这样做的好处是：

1. 首次引导仍然保持简单
2. 后续团队成员能先基于稳定版本加入开发
3. 复杂的任务分配逻辑会被放到更合适的配置层和 Session Console 中演进

## 10. 推荐的 `config` 交互样式

### 10.1 `ai-collab config`

建议做成轻量菜单，而不是 fullscreen TUI。

示例：

```text
ai-collab config
先选择一个配置分组。高频默认项放前面，低频设置放到下一层。
这里用于调整长期默认偏好与个人习惯。如果只是某次任务的临时偏好，建议在 Session Console 中修改。
系统会先使用推荐值，你可以在这里覆盖。

❯ 1. 常用默认项 · 主控 Codex · tmux（稳定，推荐） · 自动协作 启用
    启用 Agent、默认主控、运行方式、默认入口、自动协作。
  2. 协作与路由 · 系统推荐自动路由
    协作预设与任务类型偏好。
  3. 模型与计费 · 3 个模型提供方已设定 · 未启用价格感知
    模型档位、价格参考、配额策略与计费设定。
  4. 应用设置 · 中文 (zh-CN) · 自动检查更新
    语言、关于与更新偏好。
  5. 保存并完成
    写入 ~/.ai-collab/config.json 并退出。
  q. 退出且不保存

输入数字 · Enter 确认 · q 退出
```

进入具体项后，再做单个问题的选择。

### 10.1.1 当前已落地的偏好层

当前版本已经开始落地更清晰的五层思路：

1. **系统推荐层**：内置推荐的 `routing.intent_preferences`
2. **用户路由偏好层**：通过 `ai-collab config` 覆盖协作预设与任务类型偏好
3. **模型与计费层**：通过 `economics` 与各模型提供方的模型偏好，表达“选中谁之后默认用什么模型 / 思考档位，以及如何理解价格、配额与回退”
4. **应用设置层**：管理语言、关于、更新检查等应用级偏好
5. **运行时覆盖层**：保留给未来 Session Console / GUI 在单次 run 中临时覆盖

这里要明确区分：

- **协作与路由**：回答“先找谁做”
- **模型与计费**：回答“选中某个模型提供方后默认用什么模型 / 思考档位，以及价格、配额和回退策略如何影响判断”

当前配置结构重点如下：

```json
{
  "routing": {
    "mode": "recommended | custom",
    "cost_bias": "balanced | quality-first | cost-first",
    "intent_preferences": {
      "implementation": ["codex", "claude", "gemini"],
      "research": ["gemini", "claude", "codex"],
      "architecture": ["claude", "codex", "gemini"]
    }
  },
  "economics": {
    "pricing_mode": "disabled | official-reference | custom-reference",
    "quota_strategy": "balanced | prefer-included-quota | preserve-included-quota",
    "cross_provider_fallback": "same-provider-first | same-capability | allow-any",
    "providers": {
      "codex": {
        "billing_mode": "unconfigured | official-api | subscription-quota | custom-priced",
        "quota_window": "none | daily | monthly",
        "relative_cost_tier": "lower | standard | higher"
      }
    }
  },
  "application": {
    "auto_check_updates": true
  },
  "auto_collaboration": {
    "enabled": true,
    "preset": "auto-route"
  }
}
```

其中：

- `routing.cost_bias` 仍然保存“质量优先 / 平衡 / 成本优先”这个策略偏好
- 但它只有在 `economics.pricing_mode` 启用后，才真正具备稳定的价格语义
- `economics.providers.*` 用于表达用户自己的真实计费方式，例如官方 API、订阅配额、或更便宜的自定义渠道
- `economics.quota_strategy` 用于表达在订阅 / 配额存在时，是平衡使用、优先消耗，还是尽量保留
- `economics.cross_provider_fallback` 用于表达价格敏感时是否允许跨模型提供方回退
- `application.auto_check_updates` 属于应用级设置，不参与任务路由

### 10.2 `ai-collab config get`

示例：

```bash
ai-collab config get ui_language
ai-collab config get current_controller
ai-collab config get runtime_mode
```

### 10.3 `ai-collab config set`

示例：

```bash
ai-collab config set ui_language zh-CN
ai-collab config set current_controller codex
ai-collab config set runtime_mode tmux
ai-collab config set entry_surface session-console
ai-collab config set auto_orchestration true
```

## 11. 视觉与呈现原则

`init/config` 的视觉不是越复杂越好，而应遵守：

1. 一屏一件事
2. 少边框
3. 少颜色
4. 少常驻说明
5. 强调当前问题与当前选择
6. 底部只保留极少的操作提示

推荐风格关键词：

1. 轻
2. 干净
3. 像产品，不像调试页
4. 终端原生
5. prompt-first

## 12. 展现效果（建议稿）

### `init` 效果方向

```text
ai-collab setup
Step 2/4 · Default controller
Which agent should lead new runs by default?

❯ Codex
  Claude
  Gemini

Enter confirm · b back · Esc cancel
```

### `config` 效果方向

```text
ai-collab config
Edit default behavior for ai-collab.

1. Language ................. 中文 (zh-CN)
2. Default controller ....... Codex
3. Default runtime .......... tmux
4. Default entry ............ session-console
5. Auto collaboration ....... on
6. Providers ................ Codex, Claude, Gemini

Select item number · q quit
```

### `Session Console` 与 `init/config` 的区别

`init/config` 应像“设置入口”，而 `Session Console` 才应该像“长期使用的主界面”。

不要让两者长得太像。

## 13. 当前阶段的直接建议

1. 停止继续把 `init` 打磨成主 TUI
2. 重做一个更漂亮的薄 CLI `init`
3. 保留 `config set/get` 的命令式能力
4. 后续再做一个轻量菜单式 `config`
5. 把主要设计精力转移到 Session Console
