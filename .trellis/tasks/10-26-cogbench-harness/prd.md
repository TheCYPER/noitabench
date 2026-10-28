# 可自改的 harness（cogbench-harness）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R11–R13。排期：第 3 周（CP3）。依赖：`cogbench-agent-io`。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/design.md` 第 6、7、9、12 节。

## 范围

- 四家模型适配（Claude、GPT、Gemini、OpenAI 兼容接口的开源模型），工具调用和纯文本两种模式，prompt caching。
- 六层能力：L0 游戏工具、L1 工作区（笔记 8,000 字符 + 代码 64,000 字符两个配额，跨局保留）、L2 Code Mode 沙箱、L3 钩子、L4 子 agent（spawn / fork）、L5 插件和离线库白名单。
- 边界：改不了引擎、评分、预算；插件只能通过游戏工具读世界；不联网。
- 法杖试验场。预算：所有模型调用计入；运行前估算；超预算停止。
- 跨局：规则种子族、多局、工作区保留或清空。最小 harness 设置。

## 验收

- [ ] 一个便宜模型玩完一局（CP3），记录 token 和美元。
- [ ] agent 能写插件给自己加工具、从白名单装库、派生子 agent；越界操作被拒绝并记录。
- [ ] 离线库白名单在下载前单独征得用户同意。
