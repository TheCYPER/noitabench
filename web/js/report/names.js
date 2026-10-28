/**
 * Names the report shows for the codes of a profile (capability-graph.md sections 2 and 3). Display text only:
 * an unknown code is shown as it is, so a profile written by a newer evaluator still opens.
 */

/** Capabilities in the order the chart lists them. `short` fits a chart label, `name` is the full name. */
export const CAPABILITIES = {
  N1: { short: '因果推断', name: '因果推断 · 类比迁移 · 世界模型' },
  N2: { short: '记忆管理', name: '长期记忆与记忆管理' },
  N3: { short: '长程规划', name: '长程规划' },
  N4: { short: '物理直觉', name: '朴素物理直觉' },
  N5: { short: '空间推理', name: '空间推理' },
  N6: { short: '主动实验', name: '主动实验与探索' },
  N7: { short: '主动感知', name: '主动感知' },
  N8: { short: '组合构造', name: '组合式程序构造' },
  N9: { short: '风险决策', name: '风险决策' },
  N10: { short: '元认知', name: '元认知' },
  C: { short: '组合能力', name: '组合能力（C1 到 C4 的平均）' },
};

export const COMBINED = {
  C1: '资源管理',
  C2: '生存探索',
  C3: '获取并组装法杖',
  C4: '跨局成长',
};

/** The 24 encounters of the capability graph; only some are implemented, the profile says which. */
export const ENCOUNTERS = {
  E01: '落入液体的生物',
  E02: '熔岩河',
  E03: '火免疫的守卫',
  E04: '实验台遗迹',
  E05: '上锁的宝库',
  E06: '封住的最深处',
  E07: '连环关卡',
  E08: '淹水通道',
  E09: '木平台上的敌人',
  E10: '水池挡道',
  E11: '掩体后的射手',
  E12: '夹层挖掘',
  E13: '悬空平台',
  E14: '三瓶无名液体',
  E15: '炼金台',
  E16: '薄酸层',
  E17: '一排瓶子',
  E18: '厚墙后的宝藏',
  E19: '拐角后的机关',
  E20: '训练假人',
  E21: '低血与无名瓶',
  E22: '近路与远路',
  E23: '样本瓶与深池',
  E24: '新旧两间屋',
};

/** Global metrics (capability-graph.md section 4). */
export const METRICS = {
  repeat_harm: '同类伤害再次发生',
  low_hp_discipline: '低血时先恢复',
  backtracking: '回头路',
  decisions_per_layer: '每层决策数',
  route_efficiency: '路线效率',
  hit_rate: '命中率',
  layer_completion: '每层完成度',
  layer_end_hp: '离层时的血量',
  new_liquids_tried: '新液体先试',
  inspect_before_hazard: '危险前先查看',
  key_assembly: '破封钥匙组装',
  notes_used: '调用笔记解决问题',
  notes_corrected: '改正错的笔记',
  notes_accuracy: '笔记准确率',
  notes_learned: '学到的新东西',
  notes_recall: '开局读回笔记',
  notes_kept: '本局留下笔记',
  fire_and_buoyancy: '火往上窜与浮力',
  cross_game_gain: '跨局进步：同一遭遇点',
  growth_depth: '跨局进步：深度',
  growth_harm: '跨局进步：受伤',
  growth_pace: '跨局进步：步数',
  first_contact_physics: '初次接触的物理',
  experiment_value: '试验的价值',
  inspect_result_used: '查询结果的使用',
  wand_edit_gain: '改杖的收益',
  stop_when_unsure: '不确定时收手',
};

export const SOURCES = { agent: '模型', human: '人类', bot: '脚本 bot', unknown: '来源未知' };

/** How a run ended, from `outcome.over` (harness end reasons, contracts.md section 17). */
export const ENDINGS = {
  dead: '死亡',
  decision_limit: '决策用完',
  budget_usd: '美元预算用完',
  budget_calls: '调用次数用完',
  model_error: '模型出错',
  refusal: '模型拒绝',
  stalled: '卡住不动',
  aborted: '中止',
};

/**
 * Own property only: a code named `constructor` or `__proto__` must not find an inherited value.
 * @template T
 * @param {Record<string, T>} table
 * @param {unknown} key
 * @returns {T|undefined}
 */
export const own = (table, key) => (typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : undefined);

/** @param {string} key  N1 to N10, C */
export const capabilityShort = (key) => own(CAPABILITIES, key)?.short ?? own(COMBINED, key) ?? String(key);
/** @param {string} key */
export const capabilityName = (key) => own(CAPABILITIES, key)?.name ?? own(COMBINED, key) ?? String(key);
/** @param {string} id  E02 */
export const encounterName = (id) => own(ENCOUNTERS, id) ?? '';
/** @param {string} name  repeat_harm */
export const metricName = (name) => own(METRICS, name) ?? String(name);
/** @param {string} source */
export const sourceName = (source) => own(SOURCES, source) ?? SOURCES.unknown;
/** @param {string} over */
export const endingName = (over) => own(ENDINGS, over);

/** Key order of the chart: the known capabilities first, then anything else a profile carries. */
export function orderedCapabilityKeys(keys) {
  const known = Object.keys(CAPABILITIES);
  const rest = [...new Set(keys)].filter((k) => !known.includes(k)).sort();
  return [...known.filter((k) => keys.includes(k)), ...rest];
}
