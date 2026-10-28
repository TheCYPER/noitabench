# 世界生成（cogbench-world）

> 父任务：`.trellis/tasks/10-16-noita-cogbench`。对应需求 R8。排期：第 1 周做原型（CP1），第 2 周接上模拟核心和遭遇点。依赖：第 1 周无（只依赖约定和材料表）；第 2 周依赖 `cogbench-sim`。

## 先读

1. `.trellis/spec/backend/contracts.md`（跨模块约定，**必读**）
2. 父任务 `.trellis/tasks/10-16-noita-cogbench/prd.md`、`.trellis/tasks/10-16-noita-cogbench/design.md`（以及下面列出的相关设计文档）
3. `.trellis/spec/game-design/v1-scope.md`，再按需读其他知识库页
4. 代码规范：`.trellis/spec/backend/`（Rust、Python）或 `.trellis/spec/frontend/`（网页）

相关设计：`.trellis/tasks/10-16-noita-cogbench/world-design.md`（**主文档**）、`.trellis/tasks/10-16-noita-cogbench/capability-graph.md` 第 3 节；调研 `.trellis/tasks/10-16-noita-cogbench/research/worldgen.md`、`biome_map_ascii.txt`、`wang_template_*.json`。

## 第 1 周要交付（纯 Python 原型，放在 `python/noitabench/worldgen/`）

- `content/biome_map.json`：6 列 × 13 行、每格 128 像素的固定群系图，内容照 `world-design.md` 第 2.1 节。
- `content/biomes/<key>.json`：9 个群系，每个写材料填充比例、拼块风格参数、刷怪和物品标记的密度、遭遇点插槽数量。
- 人字形 Wang 拼块（herringbone，Sean Barrett 的方法）：按群系风格参数**程序生成**拼块模板，再按种子拼满群系范围。
- 材料填充：拼块里的灰色区域按群系材料比例加噪声填充。
- 标记：出生点、敌人、物品、遭遇点插槽（第 1 周先用矩形占位，写进 `markers`，带 `must_pass`）。
- 全局场景：起点、两个休息区、最底部的封印室（先用简单的程序化房间）。
- 生成后检查（`world-design.md` 第 2.5 节）：连通（把用起始法杖能挖开的格子算作可通过）、每层主路至少 2 个必经插槽、封印门前可达。
- 输出世界文件对（约定第 4 节：调色板 PNG + JSON）。
- 命令：`python -m noitabench world preview --seed N --out previews/`（放大的预览图，叠加群系边界、主路、标记）和 `python -m noitabench world check --seeds 200`。

## 验收

- [ ] 同一种子生成结果逐字节一致；不同种子地形明显不同，群系图不变。
- [ ] `world check --seeds 200` 全部通过，单张世界生成在 10 秒内。
- [ ] 5 个种子的预览图放进 `docs/previews/` 并提交（`previews/` 本身不进仓库），能看出 3 层、每层左中右不同群系、层间休息区、主路和遭遇点插槽。你在 CP1 上判断“像不像 Noita”。
- [ ] Python 测试覆盖拼块边缘匹配、连通检查、标记数量。

## 第 2 周

接上 `cogbench-sim`（`Env.from_world`），和 `cogbench-content` 一起把 12 个遭遇点做成真的预制场景，替换占位矩形。
