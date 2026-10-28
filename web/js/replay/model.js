import { buildCostIndex, costAtDecision, rowOfCall } from './costs.js';
import { buildMarks, markLabel } from './timeline.js';
import { parseTranscript, turnForDecision } from './transcript.js';

/**
 * Everything the replay and compare pages know about one run's decisions:
 * the marks of the timeline, the model turns of the transcript and the cost
 * log, put together. Pure functions, no DOM.
 *
 * @typedef {ReturnType<typeof buildModel>} DecisionModel
 */

/**
 * @param {{decisions?:object[], transcript?:object[], harness?:object[]}} run  the optional files, already normalized
 */
export function buildModel(run) {
  const transcript = run.transcript ?? [];
  const tr = parseTranscript(transcript);
  const first = buildMarks(run.decisions ?? []);
  const views = new Set(first.map((m) => m.view));
  const lastView = first.length ? first[first.length - 1].view : null;
  // A briefing comes between decision `after` and the next one; if the run ended there, it belongs to the last mark.
  const briefings = new Map();
  for (const b of tr.briefings) {
    const n = views.has(b.after + 1) ? b.after + 1 : lastView;
    if (n !== null) briefings.set(n, b);
  }
  const marks = buildMarks(run.decisions ?? [], { briefingBefore: new Set(briefings.keys()), diedAtEnd: tr.end?.over === 'dead' });
  // which turn made each decision, and the decisions of each turn in order. A decision that cost nothing (notes only)
  // shares its number with the next one and its turn owns no number, so it gets no turn rather than the next one's.
  const turnOf = marks.map((m) => (transcript.length && m.cost !== 0 ? turnForDecision(tr.turns, m.view) : null));
  const turnMarks = new Map();
  marks.forEach((m, pos) => { if (turnOf[pos]) turnMarks.set(turnOf[pos], [...(turnMarks.get(turnOf[pos]) ?? []), pos]); });
  return {
    marks,
    tr,
    costs: buildCostIndex(run.harness ?? []),
    hasTranscript: transcript.length > 0,
    hasCosts: (run.harness ?? []).length > 0,
    briefings,
    turnOf,
    turnMarks,
  };
}

/**
 * The view model of the decision panel for the mark at position `pos`.
 * Every field is plain data; the DOM code only lays it out.
 *
 * @param {DecisionModel} model
 * @param {number} pos
 */
export function detailFor(model, pos) {
  const mark = model.marks[pos];
  if (!mark) return null;
  const turn = model.turnOf[pos];
  const view = model.hasTranscript ? model.tr.observations.get(mark.view) ?? null : null;
  const own = turn ? model.turnMarks.get(turn) : null;
  const inTurn = own ? { k: own.indexOf(pos) + 1, count: own.length } : null;
  return {
    mark,
    label: markLabel(mark),
    total: model.marks.length,
    observation: view,
    turn,
    inTurn,
    briefing: mark.briefing ? model.briefings.get(mark.view) ?? null : null,
    cost: model.hasCosts ? costAtDecision(model.costs, mark.view) : null,
    call: turn && model.hasCosts ? rowOfCall(model.costs, turn.call) : null,
    hasTranscript: model.hasTranscript,
    end: pos === model.marks.length - 1 ? model.tr.end : null,
  };
}
