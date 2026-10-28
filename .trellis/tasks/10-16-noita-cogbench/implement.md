# 执行计划（v2）

> 2026-10-26：第二轮问卷选了 4 周精简版（Q20）。范围比 v1 多了三块：Noita 式世界生成、可自改的 harness、人类游玩界面。
> 前提：你确认整体计划。确认之前不写代码，不运行 `task.py start`。
> 工作方式（J3）：子 agent 尽量用便宜的模型；每个检查点向你汇报；技术细节不等你点头。

## 0. 开工前（1 到 2 天）

- [x] 第二轮问卷的结论写回各文档（2026-10-26 已完成）。
- [ ] 准备离线库白名单：选一批通用 Python 库，预先下载成本地包仓库，记录版本。第 3 周用到，下载前单独征得你同意。
- [x] 你确认遭遇点清单（第二轮问卷 Q10）。
- [x] 归档旧任务（5 个 10-07 任务已移到 `.trellis/tasks/archive/2026-10/`），调研数据已移到本任务的 `research/`，知识库里的旧路径已改（2026-10-26）。
- [x] 知识库加一页 `v1-scope.md`：第一版用到的规则编号、材料、法术、敌人、群系；`DN-WORLD-02` 标为作废（改回 Wang 拼块）。不删旧内容。
- [x] 建子任务（第 2 节），各写自己的 `prd.md` 和依赖（2026-10-26）。
- [x] 跨模块约定 `.trellis/spec/backend/contracts.md`，材料表和反应表 `content/materials.json`、`content/reactions.json`（2026-10-26）。
- [x] 写 Rust、Python 和网页的代码规范到 `.trellis/spec/backend/`、`.trellis/spec/frontend/`（2026-10-26）。
- [x] `git init`，推到私有仓库 TheCYPER/NoitaClone（2026-10-26）；之后每个检查点打 tag。

## 1. 两种排法

### 采用：4 周精简版（Q20）

第一阶段只做最能验证整套思路的部分，其余放第二阶段。

| 周 | 内容 | 检查点 |
|---|---|---|
| 1 | 模拟核心（网格、运动、燃烧、爆炸、反应、存档、事件日志、可复现）；群系图和 Wang 拼块生成器；世界预览工具 | **CP1**：几段材料行为录像 + 5 个种子的世界预览图，你判断“像不像 Noita” |
| 2 | 玩家、物品、25 个法术、魔药、3 种敌人、扰动；9 个群系和 4 个全局场景；生成后检查；先做 12 个遭遇点（每个基础节点至少 1 个，加上全部必经遭遇点） | **CP2**：脚本 agent 从起点走到最深处（含破封）的录像；3 个规则种子的反应表对比 |
| 3 | 时间模型和指令、打断；三种观测；harness 的 L0–L5（游戏工具、工作区、Code Mode、钩子、子 agent 的 spawn 和 fork、插件和离线库白名单）；四家模型适配和成本记录；网页游玩界面（暂停模式） | **CP3**：一个便宜模型玩完一局的录像和成本；你在网页里自己玩一局 |
| 4 | 评估函数、全局指标、综合分；回放、对比、报告页；剩余遭遇点能做多少做多少；四家各一个模型试跑 | **CP4**：四个模型和你自己的综合分、能力画像、遭遇点明细 |

放到第二阶段：分叉侦察（`design.md` 第 7 节 a）、多个玩家角色（若选）、实时人类模式、外部 harness 赛道（MCP）、群系修饰、剩下的遭遇点、商店天赋宝箱。

### 第 2 周细分（2026-10-26，含 CP1 反馈）

CP1 的改动见 `cp1-feedback.md`（只做影响 agent 的部分）。分三批，同一批里的子 agent 改的目录互不重叠；`contracts.md` 只由主会话改，子 agent 在报告里给出要补的约定条文。

| 批次 | 内容 | 子任务 | 依赖 |
|---|---|---|---|
| A1 | 模拟扩展：酸会被消耗（r04）；`materials.json` 加 `explosion` 对象，去掉写死的火药参数；给实体用的网格查询（射线、方盒扫掠、投射物扫掠，`SIM-R60..R65`）；接触伤害接口（`HAZ-R01`）；岩浆成股下落（低优先） | `cogbench-sim` | 无 |
| A2 | 世界生成改进：地层、洞形变化、群系结构、休息区缩小、去掉地图上的酸、废弃工坊、沙穴悬沙、少量环境危险、桶的放置标记 | `cogbench-world` | 无 |
| A3 | 法杖施法引擎（纯逻辑，`crates/game/src/wand/`）：25 个法术的数据文件 `content/spells.json`、牌组施法算法 `WAND-R01..R64`、施法测试向量 | `cogbench-content` | 无 |
| B1 | 游戏实体（`crates/game`）：玩家移动、物品（瓶子、法杖、法术、三种桶）、踢、拾取、魔药和状态、3 种敌人、投射物（接 A3 的施法结果和 A1 的查询）、扰动生成器、Python 绑定扩展 | `cogbench-content` | A1、A3 |
| C1 | 12 个遭遇点预制场景（用 `cp1-feedback.md` 第 3.1 节的陷阱）；世界里的插槽换成场景；生成后检查加“遭遇点在扰动后可解”和“破封物品不用挖就能到”；脚本 agent 从起点走到最深处 | `cogbench-content`、`cogbench-world` | A2、B1 |
| C3a | 破封钥匙（2026-10-27 决定）：`EXPLOSIVE_PROJECTILE` 给被修饰投射物的爆炸加 3 点可破耐久（不叠加，取最大），`BOMB`+`EXPLOSIVE_PROJECTILE` = 14 正好能破砖；`EXPLOSIVE_PROJECTILE` 作为第二个 `role: "breaker"` 放进 E12 入口处（不用挖就能到）；`seal_breakable` 改成硬检查；E06 测试用真钥匙，不再用 `Game.blast` | `cogbench-content`、`cogbench-world` | C1 |
| C3b | 脚本 agent 补全：用自带的溶剂瓶解 E02（倒在岩浆河上结壳再走过去），捡齐两件破封物品，在法杖里按“修饰在前、炸弹在后”装好，扔炸弹后躲开爆炸，再下到最深处；重录 CP2 录像 | `cogbench-content` | C2；真钥匙测试等 C3a |

### CP2 决定（2026-10-27）

- 必经遭遇点：所在通道用砖围住，初始挖掘杖挖不穿。脚本 agent 因此要会解全部 9 个必经场景，放在第 3 周和 agent 接口一起做。
- 改法杖：只在休息区和 E06 大厅（破封前的改杖台，没有回血池）能改。第 3 周做 `edit_wand` 限制时一起实现。
- 反应表不再扰动，固定为原版；取消强度 1、2。`crates/rules` 只保留配方生成，反应表扰动代码在第 3 周停用和清理；世界生成里的槽位液体改用原版答案。
- 秘方魔药（方案，等用户最后确认）：8 种，只能靠配方做出来，效果都持续一段时间：活力（持续回血）、无敌（约 10 秒不受伤害）、回魔（回魔 ×3）、暴击（暴击率 +50%）、狂暴（法术伤害 ×2）、漂浮（漂浮能量不消耗）、隐身（敌人看不见，攻击后现形）、防火（不着火、不受火焰伤害）。治疗、魔力、加速 3 种普通魔药照常放在世界里。
- 配方：每种 3 种配料，按种子从 12 种配料里抽（水、血、油、威士忌、毒泥、沙、煤、火药，加新材料金粉、骨粉、蘑菇粉、黏液），220 种组合，8 个配方互不相同，两种会互相反应的配料不进同一个配方。三种配料在瓶子里、地上或碗里碰在一起就变成魔药。
- 炼金碗：新材料“金属”（不被腐蚀、挖不动、不燃烧），碗约 20 × 10 格，每个休息区一个，E04、E14 的砖容器改成金属碗，世界里再散几个。
- 破封钥匙：随机掉落（随机法术拾取、随机法杖）里不出 `EXPLOSIVE_PROJECTILE`；炸弹照常。

### 第 3 周细分（2026-10-27，先做 CP2 的改动，再做 agent 接口）

同一行里并行的批次改的目录互不重叠；`contracts.md` 只由主会话改。

| 批次 | 内容 | 子任务 | 依赖 |
|---|---|---|---|
| D1 | 反应表固定为原版：`crates/rules` 只生成配方，删掉反应表扰动和强度；Python 绑定新增 `noitabench_core.rules()`（原版表的查询对象）和 `recipes(rule_seed)`，`perturb` / `Perturbed` 暂时保留为只接受强度 0 的兼容层。新材料（追加在 `materials.json` 末尾）：金属、金粉、骨粉、蘑菇粉、黏液、7 种新秘方魔药。三种配料的配方反应（网格上和瓶子里）。8 种秘方魔药的效果。随机掉落不出 `EXPLOSIVE_PROJECTILE` | `cogbench-content`（含 `crates/sim`、`crates/rules`、`crates/game`、`crates/py`） | 无 |
| D2a | 世界生成：去掉 `strength`（槽位液体用原版表的答案）；必经场景所在通道用砖围住，检查“不破砖就绕不开”；E06 大厅加改杖台标记 | `cogbench-world` | 无（和 D1 并行，用强度 0 的现有接口） |
| E1 | agent 接口（`python/noitabench/agent/`）：时间模型 B（tick 10 帧、持续指令、`until`、300 帧上限、4 条默认打断）、指令表、三种观测、`inspect`、JSON Lines 协议、`decisions.jsonl`；`edit_wand` 只在休息区和改杖台 | `cogbench-agent-io` | 无（用现有 Game API） |
| D1b | 引擎补漏（D1、E1 报告的缺口）：瓶子能装多种材料、在瓶子里也能按配方混出魔药（按 Noita 的药瓶）；`drop` 控制键；地上法杖在实体视图里带属性；喝、倒、装的汇总事件当帧写出；`on_ground` 不再落后一帧；`reactions.json` 说明文字改掉“扰动”。读瓶子的地方（`game.py`、`agent/`）一起改。agent 层（E1 检查后的主会话决定）：`nearby` 只给种类和位置，瓶子内容、血量、状态要 `inspect` 才知道；一次决策最多 4 条指令，每个 `inspect` 各算一次决策；看得见的物体范围和 `inspect(x, y)` 都统一成 ASCII 地图的范围；和完成同一 tick 的打断写进 `also`；走路碰墙不管 `blocked` 打断开没开都会停；文本里的 `none` 能当方向用 | `cogbench-content`、`cogbench-agent-io` | D1、E1 检查完 |
| D2b | 配料放进世界，检查每个配方的配料都拿得到；炼金碗（每个休息区一个、E04/E14 的砖容器换成金属碗、世界里再散几个）；worldgen 换用 `rules()`，删掉兼容层；预览图 | `cogbench-world` | D1、D2a |
| D3 | 脚本 agent：在砖围后的世界里解全部 9 个必经遭遇点，只在允许的地方改法杖；重录 | `cogbench-content` | D2a、D2b、E1 |
| E2 | harness 核心（`python/noitabench/harness/`）：agent 循环；模型适配只用标准库 `urllib`（Anthropic Messages、OpenAI 兼容 chat completions（GPT 和开源模型）、Gemini），工具调用和纯文本两种模式，Anthropic 的 prompt caching；价格表和成本记录，超预算停止，运行前估算；L0 游戏工具（`agent.tools`）；L1 工作区（笔记和技能 8,000 字符、插件和脚本 64,000 字符，跨局保留）；最小 harness 设置；不联网的假模型做测试；`python -m noitabench harness run` | `cogbench-harness` | E1、D1b |
| E3 | harness 高级层：L2 Code Mode 沙箱（子进程、时间和内存上限、每次最多 200 条游戏指令、只能读写工作区、不联网）；L3 钩子；L4 子 agent（spawn / fork，同一家的型号）；L5 插件和离线库白名单（从本地 wheel 目录装；下载 wheel 前单独征得用户同意）；法杖试验场。另外（E4 后的主会话决定）：agent 的观测也显示燃烧状态，截图高亮着火的格子、ASCII 地图给着火格单独的图例，经 `agent/engine.py` 的 `burning()` 读取，人和 agent 看到的一致；`memory_*` 笔记操作不算决策（和 harness 的 `workspace_*` 工具、网页笔记面板一致） | `cogbench-harness`、`cogbench-agent-io` | E2 |
| E4 | 网页游玩（暂停模式）：`web/play.html` 加本机 Python 服务（标准库 HTTP，跑同一个 `AgentSession`）；键鼠映射到同一套指令；笔记面板就是同一个工作区；显示燃烧状态；录像格式和 agent 一致 | `cogbench-web` | E1、D1b |

### 第 4 周细分（2026-10-28，CP3 之后）

CP3 结果：Claude Haiku 5.5 一局走到 y = 908（封印在 1574），235 步、47 次模型调用、0.051 美元，第 2 层被敌人打死；整条链路跑通。用户试玩反馈：走路在“前方有落差”时自己停下，很多能走的地方也报 blocked；R 键漂浮别扭，改成 W 点一下跳、按住浮空。

| 批次 | 内容 | 子任务 | 依赖 |
|---|---|---|---|
| P1 | 走路：去掉“前方有落差就停”（没有摔落伤害，走到边上就掉下去），新增可选停止条件 `until=edge`；撞墙改成实际推不动才算（不再用预测）。网页：W 点一下跳、按住浮空（按多久浮多久，配合 A/D 斜飞），去掉 R。人类基线加固：`/content/materials.json` 只给编号和颜色、名字随 `view.legend` 下发；世界文件不写进录像目录；死亡或决策用完时自动结束并写完录像 | `cogbench-agent-io`、`cogbench-web` | 无 |
| F1 | 评分（`python/noitabench/eval/`）：已实现的 12 个遭遇点的评估函数（读录像和事件，触发区进入判定）、能力图第 4 节的全局指标、11 项能力分、深度分、综合分 = 80% 能力分 + 20% 深度分、覆盖不足的能力不进综合分；输出 `profile.json`；`python -m noitabench eval`；评分绝不进 agent 的观测；抽查思考记录里有没有“这是测试”之类的说法 | `cogbench-eval` | 无 |
| F2 | 网页：回放页按决策点跳转，显示每一步的观测、模型输出（思考摘要、工具调用、结果）、harness 动作（代码运行、钩子、帮手），0.25 到 8 倍速；对比页 2 到 4 局同步播放 | `cogbench-web` | 无 |
| F2b | 报告页：综合分、能力画像、遭遇点明细、成本（读 F1 的 `profile.json`） | `cogbench-web` | F1 |
| F3 | 四家模型各一个试跑（需要用户给 GPT、Gemini、开源模型的 key 和型号，价格要先核实） | `cogbench-harness` | F1、F2 |
| F4 | 剩下的遭遇点能做多少做多少。2026-10-28 用户定：先补覆盖少的 N2、N4、N10。G1：新场景 E05（上锁的宝库，N2）、E09（木平台上的敌人，N4）、E10（水池挡道，N4）、E24（新旧两间屋，N10，按“看起来像的另一种材料”重做）、E21（低血与无名瓶，N9/N10），可选遭遇点，带陷阱和线索、标准解法、放置和可解检查。G2：这 5 个的评分规则，加上能测的全局指标（N2 笔记被读取并用上、N4 第一次遇到物理情况的处理）。**做完（2026-10-28）**：E10 改成护城河（油火挡追兵在引擎里做不到）；E05 的锁是岩浆河、钥匙是一瓶水或血；E09 的火源是火药桶加油槽；E21 回血药的位置随变体变。评分器 0.3.0：五条规则；N2 `notes_recall`、`notes_kept`；N4 `first_contact_physics` 按“遇到”算题（3 格内），碰到最多 0.5，潜水要用掉一半憋气才算，着火要附近有水才算。仍没测到：`notes_used`、`fire_and_buoyancy` 等 | `cogbench-content`、`cogbench-world`、`cogbench-eval` | F1 |
| K | 知识库和笔记对错（2026-10-28 用户定，规格见 contracts 第 21 节）。K1：从数据文件自动生成知识库，分三档（种子独有的秘方、我们游戏独有、Noita 常识），遭遇点 JSON 加 `lessons`；可读版（不含秘方，现为英文 `docs/knowledge-base.md`）。K2：Haiku 把笔记翻成固定格式的说法（`notes_claims.json`，说法必须能在笔记原文里找到），代码判对错；新指标 `notes_accuracy`、`notes_learned`；带“可能”的说法不加分也不扣分。K3：每局开头存一份笔记（`workspace_start/`）；同族第 2 局起判 `notes_used`（读了、有料、遇到了、做成了）和 `notes_corrected`（错的笔记被推翻后改没改）。评分器 0.4.0。**做完（2026-10-28）**：规则种子 0 共 290 条事实（秘方 8、本游戏独有 73、Noita 常识 209，其中 88 条已告知）；遭遇点只把事实连到场景，不改它的档（水碰岩浆仍是常识）；15 个场景写了 `lessons`，E12、E18 没有；“混在一起没反应”这类说法不进笔记准确率（大多数组合本来就没反应）；说法的原文引用至少 4 个字母或 3 个汉字。**改为全英文（2026-10-28，用户定）**：知识库的句子、词表、遭遇点 lesson 说明、可读版（改名 `docs/knowledge-base.md`）和提取提示词都只用英文；“翻译”改叫“提取”（`extract.py`、`notes_claims.json` 的 `extractor`），评分器 0.4.1，事实和分数都不变；网页界面和 `name_zh` 没动。真模型提取还没试过 | `cogbench-eval`、`cogbench-content`、`cogbench-harness` | F4 |

### 第 4 周开头要做（找人做人类基线之前）

- 回放和对比页挡不住所有能推出配方的线索（瓶子事件里的魔药名、画面里的魔药格子、模型自己的话），所以流程上规定：人类参与者在玩某个规则种子之前，不看这个种子的任何回放（2026-10-28 决定）。

- 网页游玩：`/content/materials.json` 只给编号和颜色，名字只随 `view.legend` 下发（现在能从开发者工具看到全部材料名，包括秘方魔药）；世界文件不写进录像目录，或者游玩页去掉预览页的链接（现在参与者能打开世界文件看到关卡标注）；死亡或决策用完时自动结束并写完录像。

### 未采用：6 周完整版（留作参考）

在方案一的基础上：第 3、4 周之间插入 1 周做完 24 个遭遇点和群系修饰；第 5 周做分叉侦察消融、实时人类模式、MCP 外部赛道；第 6 周做人类基线招募试玩和全量试跑。

## 2. 子任务

| 子任务 | 内容 | 依赖 |
|---|---|---|
| `cogbench-sim` | 模拟核心、存档、事件日志、可复现、Python 绑定骨架 | 无 |
| `cogbench-world` | 群系图、Wang 拼块模板生成、群系生成、全局场景、遭遇点放置、生成后检查、世界预览 | `cogbench-sim` |
| `cogbench-content` | 玩家、物品、法杖法术、魔药、敌人、扰动、遭遇点预制场景 | `cogbench-sim`；遭遇点部分和 `cogbench-world` 一起做 |
| `cogbench-agent-io` | 时间模型、指令、打断、观测、`inspect`、协议和 MCP 包装 | `cogbench-content` |
| `cogbench-harness` | 模型适配、工作区（两个配额）、Code Mode 沙箱、钩子、子 agent、插件接口、离线库白名单、法杖试验场、预算 | `cogbench-agent-io` |
| `cogbench-eval` | 遭遇点评估函数、全局指标、综合分、覆盖统计 | `cogbench-world`、`cogbench-agent-io` |
| `cogbench-web` | 渲染器、人类游玩、回放、对比、报告、世界预览页、WebSocket 服务 | 只依赖录像格式和 Env 接口；第 1 周就能开始 |

## 3. 验证命令

```bash
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
maturin develop -m crates/py/Cargo.toml
pytest python/tests
python -m noitabench world preview --seed 42 --out previews/        # 世界预览图
python -m noitabench world check --seeds 200                        # 生成后检查
python -m noitabench run --agent scripted --family 7 --runs 3       # 脚本 agent 跑一个种子族
python -m noitabench run --agent claude --family 7 --runs 3 --dry-run   # 只估成本
python -m noitabench serve                                          # 网页：游玩、回放、报告
```

## 4. 检查和回退

- 每个子任务完成时跑 `trellis-check`；你在检查点上看预览图和录像。
- 可复现测试和世界生成检查是每次提交都要过的门槛。
- 每个检查点打 git tag，出问题可以回到上一个检查点。
- 风险最高的三块先做原型：Wang 拼块生成效果（第 1 周）、遭遇点在扰动后可解（第 2 周）、开放世界里一局的实际成本（第 3 周）。
