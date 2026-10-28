import { FormatError, check, isNum, isObject } from '../format/errors.js';

/** The only format this page reads (contracts.md section 19). */
export const PROFILE_FORMAT = 'cogbench-profile/0';

/**
 * What the report keeps of a `profile.json`. Deliberately not a copy of the file: `world` (seeds, world file
 * name) is dropped here, so no later code can show it by accident.
 *
 * @typedef {{
 *   name: string, score: number|null, opportunities: number, covered: boolean|null, note: string,
 *   discount: number|null, discounted: number|null,
 *   encounters: {id:string, role:string, weight:number|null, score:number|null}[],
 *   metrics: {name:string, value:number|null, n:number|null}[],
 *   parts: Capability[],
 * }} Capability
 * @typedef {{
 *   layer: number|null, mustPass: boolean, enter: number|null, exit: number|null,
 *   scored: boolean, score: number|null, reasons: string[],
 * }} Visit
 * @typedef {{ id:string, nodes:string[], placed:number, mustPassPlaced:number, visits:Visit[] }} Encounter
 * @typedef {{ name:string, capabilities:string[], status:string, value:number|null, opportunities:number|null, reason:string }} Metric
 * @typedef {{
 *   capability?:string, layer?:number, outcome?:string, frame?:number, encounter?:string, nodes?:string[], reason?:string,
 *   last_harm?:{frame?:number, source?:string, kind?:string}|null,
 * }} Attribution
 * @typedef {{
 *   file:string, runId:string, source:string, model:{provider:string, model:string}|null,
 *   composite:number|null, ability:number|null, abilityRaw:number|null, compositeNote:string,
 *   covered:string[], leftOut:string[],
 *   depth:{score:number|null, fraction:number|null, reachedSealedRoom:boolean, cappedAtSeal:boolean},
 *   outcome:{over:string, died:boolean, deathFrame:number|null, frames:number|null},
 *   capabilities: Map<string, Capability>, hasDiscount: boolean,
 *   encounters: Encounter[], metrics: Metric[], attribution: Attribution[],
 *   cost:{usd:number|null, costKnown:boolean|null, modelCalls:number|null, wallSeconds:number|null,
 *         inputTokens:number|null, outputTokens:number|null}|null,
 *   steps:{decisions:number|null, frames:number|null},
 *   awareness:{checked:number|null, hits:number, byCategory:Record<string,number>,
 *              snippets:{category:string, phrase:string, snippet:string, field:string}[]}|null,
 *   notes: string[],
 * }} Profile
 */

const num = (v) => (isNum(v) ? v : null);
const str = (v) => (typeof v === 'string' ? v : '');
const list = (v) => (Array.isArray(v) ? v : []);
const obj = (v) => (isObject(v) ? v : {});
const strings = (v) => list(v).filter((x) => typeof x === 'string');

/**
 * Validates and reads one profile.
 *
 * @param {unknown} json  the parsed file
 * @param {string} file  the file's name as the user knows it (error messages start with it)
 * @returns {Profile}
 * @throws {FormatError} when it is not a `cogbench-profile/0` object
 */
export function parseProfile(json, file) {
  check(isObject(json), file, 'not a JSON object');
  check(json.format === PROFILE_FORMAT, file, `format is ${JSON.stringify(json.format ?? null)}, expected "${PROFILE_FORMAT}" (is this a profile.json written by "python -m noitabench eval"?)`);
  const capabilities = readCapabilities(json.capabilities);
  const depth = obj(json.depth);
  const outcome = obj(json.outcome);
  const hasDiscount = [...capabilities.values()].some((c) => c.discounted !== null);
  return {
    file,
    runId: str(json.run_id) || str(json.run_dir) || file,
    source: str(json.source) || 'unknown',
    model: isObject(json.model) ? { provider: str(json.model.provider), model: str(json.model.model) } : null,
    composite: num(json.composite),
    ability: num(json.ability_mean),
    abilityRaw: num(json.ability_raw_mean),
    compositeNote: str(json.composite_note),
    covered: strings(json.covered),
    leftOut: strings(json.left_out),
    depth: {
      score: num(depth.score),
      fraction: num(depth.fraction),
      reachedSealedRoom: depth.reached_sealed_room === true,
      cappedAtSeal: depth.capped_at_seal === true,
    },
    outcome: {
      over: str(outcome.over),
      died: outcome.died === true,
      deathFrame: num(outcome.death_frame),
      frames: num(outcome.frames),
    },
    capabilities,
    hasDiscount,
    encounters: list(json.encounters).filter(isObject).map(readEncounter),
    metrics: list(json.metrics).filter(isObject).map(readMetric),
    attribution: list(json.attribution).filter(isObject).map(readAttribution),
    cost: readCost(json.cost),
    steps: { decisions: num(obj(json.steps).decisions), frames: num(obj(json.steps).frames) },
    awareness: readAwareness(json.test_awareness),
    notes: safeNotes(strings(obj(json.evaluator).notes)),
  };
}

/** @returns {Map<string, Capability>} */
function readCapabilities(raw) {
  const out = new Map();
  for (const [key, c] of Object.entries(obj(raw))) if (isObject(c)) out.set(key, readCapability(key, c));
  return out;
}

/** @returns {Capability} */
function readCapability(name, c) {
  const discount = num(c.discount);
  const score = num(c.score);
  // `discounted_score` is the evaluator's number; a profile that only has the factor still gets its product.
  const discounted = num(c.discounted_score) ?? (discount !== null && score !== null ? score * discount : null);
  return {
    name,
    score,
    opportunities: num(c.opportunities) ?? 0,
    covered: typeof c.covered === 'boolean' ? c.covered : null,
    note: str(c.note),
    discount,
    discounted,
    encounters: list(c.encounters).filter(isObject).map((e) => ({
      id: str(e.id), role: str(e.role), weight: num(e.weight), score: num(e.score),
    })),
    metrics: list(c.metrics).filter(isObject).map((m) => ({ name: str(m.name), value: num(m.value), n: num(m.n) })),
    parts: Object.entries(obj(c.parts)).filter(([, p]) => isObject(p)).map(([k, p]) => readCapability(k, p)),
  };
}

/** @returns {Encounter} */
function readEncounter(e) {
  return {
    id: str(e.id),
    nodes: strings(e.nodes),
    placed: num(e.placed) ?? 0,
    mustPassPlaced: num(e.must_pass_placed) ?? 0,
    visits: list(e.visits).filter(isObject).map((v) => ({
      layer: num(v.layer),
      mustPass: v.must_pass === true,
      enter: num(v.enter_frame),
      exit: num(v.exit_frame),
      scored: v.scored === true,
      score: num(v.score),
      reasons: strings(v.reasons),
    })),
  };
}

/** @returns {Metric} */
function readMetric(m) {
  return {
    name: str(m.name),
    capabilities: strings(m.capabilities),
    status: str(m.status) || (num(m.value) === null ? 'not_measured' : 'measured'),
    value: num(m.value),
    opportunities: num(m.opportunities),
    reason: str(m.reason),
  };
}

/**
 * An attribution entry, cut down to the fields the evaluator writes (`attribution.py`): like `world`, any other
 * field (a position, a seed) is dropped here, so no later code can show it by accident.
 * @returns {Attribution}
 */
function readAttribution(a) {
  const out = {};
  if (typeof a.capability === 'string') out.capability = a.capability;
  if (isNum(a.layer)) out.layer = a.layer;
  if (typeof a.outcome === 'string') out.outcome = a.outcome;
  if (isNum(a.frame)) out.frame = a.frame;
  if (typeof a.encounter === 'string') out.encounter = a.encounter;
  if (Array.isArray(a.nodes)) out.nodes = strings(a.nodes);
  if (typeof a.reason === 'string') out.reason = a.reason;
  if (isObject(a.last_harm)) {
    const h = a.last_harm;
    out.last_harm = {};
    if (isNum(h.frame)) out.last_harm.frame = h.frame;
    if (typeof h.source === 'string') out.last_harm.source = h.source;
    if (typeof h.kind === 'string') out.last_harm.kind = h.kind;
  }
  return out;
}

function readCost(c) {
  if (!isObject(c)) return null;
  return {
    usd: num(c.usd),
    costKnown: typeof c.cost_known === 'boolean' ? c.cost_known : null,
    modelCalls: num(c.model_calls),
    wallSeconds: num(c.wall_seconds),
    inputTokens: num(c.input_tokens),
    outputTokens: num(c.output_tokens),
  };
}

function readAwareness(a) {
  if (!isObject(a)) return null;
  const byCategory = {};
  for (const [k, v] of Object.entries(obj(a.by_category))) if (isNum(v)) byCategory[k] = v;
  return {
    checked: num(a.checked_texts),
    hits: num(a.hits) ?? 0,
    byCategory,
    snippets: list(a.snippets).filter(isObject).map((s) => ({
      category: str(s.category), phrase: str(s.phrase), snippet: str(s.snippet), field: str(s.field),
    })),
  };
}

/**
 * The evaluator's notes, minus any that talks about seeds: the note about a world file that does not match
 * the recording quotes both seeds, and the report never shows a seed.
 * @param {string[]} notes
 */
export function safeNotes(notes) {
  return notes.map((n) => (/seed/i.test(n) ? '世界文件和录像对不上（说明里带有种子，这里不显示）。' : n));
}

/**
 * Reads a profile from JSON text.
 * @param {string} text
 * @param {string} file
 * @returns {Profile}
 * @throws {FormatError}
 */
export function parseProfileText(text, file) {
  let json;
  try {
    json = JSON.parse(text);
  } catch (err) {
    throw new FormatError(file, `not valid JSON (${err.message})`);
  }
  return parseProfile(json, file);
}
