# 游戏内容（cogbench-content）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R2–R5、R9 的场景部分。排期：第 2 周（CP2）。依赖：`cogbench-sim`；遭遇点场景和 `cogbench-world` 一起做。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/design.md` 第 2–4 节、`.trellis/tasks/10-16-noita-cogbench/capability-graph.md` 第 3 节；知识库 `wand-casting.md`、`spells.md`、`entities-damage.md`。

## 范围

- `crates/game`：玩家（Noita 移动数值、悬浮 3 秒）、物品（瓶子装倒喝扔、法杖、法术，全部是简单弹道物体）、踢、拾取。
- 25 个法术和第一阶段牌组施法规则（`WAND-R01..R64`），施法测试向量。
- 魔药和状态（接触和喝下都带来状态，单一伤害类型）。
- 3 种敌人：哈米斯、霰弹希西、斯滕达里（火免疫），按 10 帧 tick 调速度。
- 扰动生成器：规则种子 → 强度 0/1/2 的反应表和隐藏配方；族结构检查；表封闭。
- 第一阶段 12 个遭遇点的预制场景（每个基础节点至少 1 个 + 全部必经遭遇点），带变体参数和触发区。

## 第 1 周留下来的事（2026-10-26）

- 火药的爆炸参数（`EXPLOSIVE_RADIUS` 等）现在写死在 `crates/sim/src/consts.rs`，违反“材料数值只从 materials.json 读”的规范。给 `materials.json` 加一个可选的 `explosion` 对象，同时升级约定第 2 节。
- `reactions.json` 没有 `blob` 字段，所以岩浆遇水只结一格厚的壳；需要的话加上可选的 `blob`（`RXN-R10`）。
- 世界里约 13% 的物品落在只能挖进去的洞里。破封需要的关键物品必须放在不用挖就能到的地方，加一条生成后检查。
- 起始法杖必须带挖掘类法术，世界生成的连通检查假设它能挖耐久不超过 10 的格子（`python/noitabench/worldgen/checks.py` 里的 `STARTER_DIG_MAX_DURABILITY`）。
- `crates/sim/tests/content.rs` 写死了 22 种材料、14 条反应；加材料或反应时一起更新。

## 验收

- [ ] 施法测试向量全过；材料、魔药、状态、敌人都有测试。
- [ ] 3 个规则种子的反应表对比可读（CP2 给你看）。
- [ ] 脚本 agent 从起点走到最深处（含破封）的录像。
