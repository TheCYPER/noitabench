# Agent 输入输出（cogbench-agent-io）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R6、R7。排期：第 3 周（CP3）。依赖：`cogbench-content`。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/tick-design.md`（**主文档**）、`.trellis/tasks/10-16-noita-cogbench/design.md` 第 5 节。

## 范围

- 时间模型 B：tick 10 帧；持续指令和 `until` 条件；单条指令最长 300 帧；默认 4 条打断；停下原因和期间事件摘要。
- 指令表全部指令；`inspect` 不推进时间但算一次决策。
- 三种观测（结构化文本、ASCII 地图、截图），可单独开关；图例只写名称不写性质。
- JSON Lines 协议和 MCP 工具包装，两者驱动同一局结果一致。
- 决策记录写进录像 `decisions.jsonl`。

## 验收

- [ ] `tick-design.md` 第 4.5.1 节的例子能原样复现。
- [ ] 可复现：种子 + 指令序列复现整局，包括决策点出现的帧号。
