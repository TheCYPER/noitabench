import { FormatError, NotFoundError } from '../format/errors.js';
import { FrameStore } from '../format/frame-store.js';
import { normalizeHarness, normalizeTranscript, parseRunSummary } from '../format/harness-run.js';
import { exactBigInts } from '../format/json.js';
import {
  indexFrames, normalizeEntities, normalizeEvents, parseJsonl, parseMeta,
} from '../format/recording.js';
import { buildModel } from './model.js';

/**
 * @typedef {{
 *   meta: ReturnType<typeof parseMeta>,
 *   store: FrameStore,
 *   entities: ReturnType<typeof normalizeEntities>,
 *   events: ReturnType<typeof normalizeEvents>,
 *   decisions: object[],
 *   transcript: object[], harness: object[],
 *   summary: ReturnType<typeof parseRunSummary>,
 *   model: import('./model.js').DecisionModel,
 *   warnings: string[],
 *   firstFrame: number, lastFrame: number,
 * }} Run
 */

/**
 * Event types the pages never show or draw. `mix` names the potion a recipe made (harness side only, contracts.md
 * sections 13 and 18): the replay of a model's game may be watched by someone who is about to play the same rules.
 */
export const HIDDEN_EVENT_TYPES = new Set(['mix']);

/**
 * Drops the hidden event types. Every page gets its events through `loadRun`, which calls this once, so the event
 * list, the overlays and the counts all agree.
 * @template {{type:string}} E
 * @param {E[]} events
 * @returns {E[]}
 */
export function visibleEvents(events) {
  return events.filter((e) => !HIDDEN_EVENT_TYPES.has(e.type.trim().toLowerCase()));
}

/**
 * Loads one run directory (a FileSet already narrowed to it).
 * meta.json and frames.bin are required; every other file is optional (a
 * run by a person has no transcript, a scripted one no decisions) and a
 * damaged one only produces a warning.
 *
 * @param {import('../ui/file-set.js').FileSet} files
 * @returns {Promise<Run>}
 */
export async function loadRun(files) {
  const metaText = await readText(files, 'meta.json');
  const meta = parseMeta(parseJson(metaText, 'meta.json'), 'meta.json');
  const big = exactBigInts(metaText, ['seed', 'rule_seed']);
  if (big.seed) meta.seed = big.seed;
  if (big.rule_seed) meta.ruleSeed = big.rule_seed;
  let buffer;
  try {
    buffer = await files.buffer('frames.bin');
  } catch (err) {
    if (err instanceof NotFoundError) throw new FormatError('frames.bin', 'file is missing');
    throw err;
  }
  const index = indexFrames(buffer, meta, 'frames.bin');
  const warnings = [];
  const entityLines = await optionalJsonl(files, 'entities.jsonl', warnings);
  const entities = normalizeEntities(entityLines);
  warnIgnored(warnings, 'entities.jsonl', entityLines.length - entities.length, 'frame and entities[]');
  const eventLines = await optionalJsonl(files, 'events.jsonl', warnings);
  const allEvents = normalizeEvents(eventLines);
  warnIgnored(warnings, 'events.jsonl', eventLines.length - allEvents.length, 'frame and type');
  const events = visibleEvents(allEvents);
  const decisionLines = await optionalJsonl(files, 'decisions.jsonl', warnings);
  const decisions = decisionLines
    .filter((d) => Number.isInteger(d.frame))
    .sort((a, b) => a.frame - b.frame);
  warnIgnored(warnings, 'decisions.jsonl', decisionLines.length - decisions.length, 'an integer frame');
  const transcript = normalizeTranscript(await optionalJsonl(files, 'transcript.jsonl', warnings));
  const harness = normalizeHarness(await optionalJsonl(files, 'harness.jsonl', warnings));
  const summary = await optionalSummary(files, warnings);
  const steps = index.steps;
  return {
    meta,
    store: new FrameStore(buffer, index),
    entities,
    events,
    decisions,
    transcript,
    harness,
    summary,
    model: buildModel({ decisions, transcript, harness }),
    warnings,
    firstFrame: steps[0].frame,
    lastFrame: steps[steps.length - 1].frame,
  };
}

async function readText(files, name) {
  try {
    return await files.text(name);
  } catch (err) {
    if (err instanceof NotFoundError) throw new FormatError(name, 'file is missing');
    throw err;
  }
}

function parseJson(text, name) {
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new FormatError(name, `not valid JSON (${err.message})`);
  }
}

function warnIgnored(warnings, name, n, needs) {
  if (n > 0) warnings.push(`${name}: ${n} line(s) ignored (each needs ${needs})`);
}

/** Text of an optional file: null when it is absent, and also when it cannot be read (that is a warning, the run still opens). */
async function optionalText(files, name, warnings) {
  try {
    return await files.optionalText(name);
  } catch (err) {
    warnings.push(`${name}: could not be read (${err && err.message ? err.message : err})`);
    return null;
  }
}

async function optionalJsonl(files, name, warnings) {
  const text = await optionalText(files, name, warnings);
  if (text === null) return [];
  const { items, errors } = parseJsonl(text, name);
  if (errors.length) warnings.push(`${errors[0]}${errors.length > 1 ? ` (and ${errors.length - 1} more bad lines)` : ''}`);
  return items;
}

async function optionalSummary(files, warnings) {
  const text = await optionalText(files, 'summary.json', warnings);
  if (text === null) return null;
  try {
    return parseRunSummary(JSON.parse(text));
  } catch {
    warnings.push('summary.json: not valid JSON');
    return null;
  }
}
