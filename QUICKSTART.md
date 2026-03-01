# Quick Start

本指南面向首次使用者，旨在帮助您在 10 分钟内完成一次可验证的协作执行。

## 前置条件

1. Python 版本 `>=3.9`
2. 已安装至少一个 Agent CLI 工具：`codex` / `claude` / `gemini`
3. 如需可视化协作过程，需安装 `tmux`

快速检查环境：

```bash
which python3
which codex claude gemini tmux
```

## 1) 安装

```bash
git clone https://github.com/skyhua/ai-collab.git
cd ai-collab
python3 -m pip install -e .
```

## 2) 初始化配置

```bash
ai-collab init
ai-collab status
```

初始化将创建以下配置文件：

1. `~/.ai-collab/config.json` - 主配置文件
2. `~/.ai-collab/workflows.json` - 工作流定义

## 3) 执行任务（交互式）

```bash
ai-collab
```

## 4) 非交互式执行

### Direct 模式

```bash
ai-collab --provider codex --execution-mode direct "实现一个用户登录与权限校验模块"
```

### tmux 模式

```bash
ai-collab \
  --provider codex \
  --execution-mode tmux \
  --tmux-target inline \
  --tmux-prewarm-subagents \
  "实现一个前后端联动功能并完成审查交接"
```

## 5) 仅生成计划（不执行）

```bash
ai-collab --dry-run --output json "你的任务描述"
```

## 6) 常用操作

### 查看执行参数

```bash
ai-collab run --help
```

### 查看管理子命令

```bash
ai-collab --help
```

### 指定输出语言

```bash
ai-collab --lang zh-CN "你的任务"
ai-collab --lang en-US "your task"
```

### 查看执行日志

```bash
tail -f .ai-collab/logs/<session>/*.log
```

## 7) 常见问题

### 协作未触发

检查任务检测结果：

```bash
ai-collab detect "你的任务" --output json
```

### Provider 命令不可用

验证环境配置：

```bash
ai-collab status
which codex claude gemini
```

### tmux 窗口无预期输出

建议同时启用以下选项：

1. `--tmux-target inline`
2. `--tmux-prewarm-subagents`
3. `--controller-first`

## 下一步

1. 详细命令说明请参阅 [docs/USAGE.md](./docs/USAGE.md)
2. 发布流程请参阅 [docs/RELEASE.md](./docs/RELEASE.md)
