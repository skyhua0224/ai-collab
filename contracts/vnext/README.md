# vNext Contracts

这组文件是 `ai-collab vNext` 在 `P0/P1` 阶段给前端与集成测试使用的第一版稳定 contract。

## 目录

- `schemas/`
  - `run_action.schema.json`
  - `stored_run_event.schema.json`
  - `run_projection.schema.json`
- `mock/`
  - `run_events.jsonl`
  - `run_projection.json`

## 用途

这组文件用于：

1. 前端并行开发
2. mock server / fake backend
3. contract drift 检查
4. 协议稳定性回归测试

## 更新方式

Rust 实现更新后，使用下面的命令重导出：

```bash
cargo run -p ac_engine --example export_contract_assets
```

然后再运行：

```bash
cargo test --workspace
```

如果导出的文件与测试中的生成结果不一致，测试会失败。
