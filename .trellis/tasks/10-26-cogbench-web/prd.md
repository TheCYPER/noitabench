# 网页客户端（cogbench-web）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R14、R16。排期：第 1 周做回放和世界预览（CP1），第 3 周做人类游玩，第 4 周做对比和报告。依赖：只依赖约定里的数据格式。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/design.md` 第 8、13 节；`.trellis/tasks/10-16-noita-cogbench/tick-design.md` 第 4.6 节（人类怎么玩）。

## 第 1 周要交付

- 按 `.trellis/spec/frontend/directory-structure.md` 建 `web/`。
- 格式读取：`materials.json`、世界文件对（`cogbench-world/0`）、录像（`cogbench-rec/0`，含 zlib 解压，可用 `web/vendor/` 里固定版本的解压库并附许可证）。
- 共用的 canvas 渲染器：按材料颜色画、最近邻缩放、整数倍放大。
- `replay.html`：选择一个录像目录（文件选择或拖拽），播放、暂停、拖动进度、0.25 到 8 倍速、缩放；有 `entities.jsonl` / `events.jsonl` 就叠加显示。
- `preview.html`：打开世界文件对，叠加群系边界、标记、遭遇点触发区、主路。
- 测试夹具：模拟核心还没好之前，写一个小 Python 脚本按约定生成**合成的**录像和世界文件（比如几帧下落的沙子），放在 `web/tests/fixtures/`；之后换成真实录像。
- `node --test` 跑格式读取的单元测试。

## 验收

- [ ] 能打开合成夹具；之后能打开 `cogbench-sim` 的演示录像和 `cogbench-world` 的预览世界。
- [ ] 网页里没有游戏逻辑。
- [ ] 在 Chrome 和 Safari 里能用；手机宽度不出现横向滚动。

## 之后几周

第 3 周：`play.html` 加本机 WebSocket 服务（Python），人类用暂停模式和同一套指令玩，鼠标悬停 = `inspect`。第 4 周：`compare.html`、`report.html`。
