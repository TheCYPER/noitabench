# 评测和综合分（cogbench-eval）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R10。排期：第 4 周（CP4）。依赖：`cogbench-world`、`cogbench-agent-io`。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/capability-graph.md`（**主文档**）。

## 范围

- 已实现遭遇点的评估函数（读事件日志），触发区进入判定。
- 全局指标（`capability-graph.md` 第 4 节）。
- 能力分、深度分、综合分 = 80% 能力分 + 20% 深度分；能力分 = 11 项按机会数打折（× n/(n+2)，没遇到算 0）后的平均（2026-10-28 用户决定）；深度只算到封印为止，除非进了封印房间；输出 `profile.json`。
- 评分绝不出现在 agent 的观测和工具输出里。
- 抽查思考记录里有没有“这是测试”之类的说法（AC13）。

## 验收

- [ ] 四个模型和你自己的综合分、能力画像、遭遇点明细（CP4）。
