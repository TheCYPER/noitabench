# 模拟核心（cogbench-sim）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R1、R15，以及 R3–R4 的材料部分。排期：第 1 周（检查点 CP1）。依赖：无。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/design.md` 第 2、11 节；知识库 `pixel-simulation.md`、`materials-reactions.md`。

## 第 1 周要交付

- 根目录 cargo 工作区，`crates/sim`、`crates/py`（maturin 打包成 Python 模块 `noitabench_core`），根目录 `pyproject.toml`。目录按约定第 1 节。
- 读取 `content/materials.json`、`content/reactions.json` 并在加载时校验。
- 网格和 64×64 分块休眠；粉末、液体（按密度分层）、气体（按寿命消散）、火的运动。
- 燃烧状态：燃料、点燃、是否需要氧气；火药燃烧时爆炸。
- 反应表：标签匹配、`@burning` / `@extinguish`（约定第 3 节），每个非空气格每帧随机看一个 4 邻居。
- 射线爆炸挖地（`DUR-R01..R03`），提供 `explode(x, y, radius, ray_energy, max_durability)`。
- 存档和恢复（逐字节一致）；事件日志（反应、点燃、熄灭、爆炸）；录像写入（约定第 5 节 `cogbench-rec/0`）。
- Python API 按约定第 6 节。
- 演示脚本 `python -m noitabench demo materials`，生成 5 段录像到 `runs/demo-*`：水浇岩浆变岩石、油浮在水上并点燃、酸腐蚀岩石、火药爆炸挖坑、水熄灭燃烧的木头。
- 用 criterion 测一下性能：768×1664 的世界，典型活动量下每秒能跑多少帧（只记录，不设门槛）。

## 验收

- [ ] 质量门槛全过（`.trellis/spec/backend/quality-guidelines.md`）。
- [ ] 每条用到的规则都有测试，测试名对应知识库规则编号。
- [ ] 可复现：同种子两次运行，网格哈希和事件日志一致；存档、恢复、再跑，结果一致。
- [ ] 5 段演示录像能被网页查看器打开（网页那边还没好的话，至少能被约定里的读法正确解析）。
- [ ] Python 里 `import noitabench_core` 后能按约定第 6 节调用。

## 之后几周

第 2 周起由 `cogbench-content` 在 `crates/game` 里加实体，本任务负责配合扩展网格查询（射线、扫掠）和接触伤害的接口。
