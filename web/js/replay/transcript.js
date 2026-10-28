/**
 * Turns the records of transcript.jsonl (contracts.md section 17) into model
 * turns the replay page can show. Pure functions, no DOM.
 *
 * What the file holds, in order:
 *   opening     the first view the model got
 *   assistant   one model call: thinking summary, text, tool calls (`agent` set = a helper's call)
 *   code_run    a program, hook script or plugin tool the player's code ran (between assistant and results)
 *   lib_install a library installed from the wheelhouse
 *   helper      a helper started (spawn, fork), was written to (message) or answered (answer)
 *   results     what the tools answered; the last one holds the next view (`agent` set = a helper's)
 *   summary     a briefing: a new conversation starts with it
 *   note        a refused or empty turn the harness handled
 *   end         why the game ended
 *
 * A model turn can make many decisions (a program steps the game 35 times), so
 * a turn owns the decision numbers `first..last`, taken from the `decision` field of
 * its assistant record (decisions made before it) and of its results record (made after).
 */

/** @typedef {{id:string,name:string,arguments:any}} ToolCall */

/**
 * @typedef {{
 *   call:number, first:number, last:number|null, text:string, thinking:string,
 *   toolCalls:{name:string,text:string,code:string|null}[],
 *   modelStop:string, results:{name:string,isError:boolean,content:string}[]|null,
 *   programs:object[], installs:object[], helpers:Helper[], notes:string[],
 * }} Turn
 * @typedef {{
 *   id:string, parent:string, depth:number, kind:string,
 *   events:{event:string,text:string,state:string}[],
 *   turns:{call:number,text:string,thinking:string,toolCalls:Turn['toolCalls'],results:Turn['results']}[],
 * }} Helper
 */

const MAX_ARG_TEXT = 240;

/**
 * `name(key=value, ...)` for a tool call, and the program text of `run_code`.
 * @param {{name?:string,arguments?:any}} tc
 */
export function describeToolCall(tc) {
  const call = tc && typeof tc === 'object' ? tc : {};
  const name = String(call.name ?? '?');
  const args = call.arguments && typeof call.arguments === 'object' ? call.arguments : {};
  const code = typeof args.code === 'string' ? args.code : null;
  const shown = Object.entries(args).filter(([k]) => !(code !== null && k === 'code'));
  const body = shown.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ');
  const text = `${name}(${body.length > MAX_ARG_TEXT ? `${body.slice(0, MAX_ARG_TEXT - 1)}…` : body})`;
  return { name, text, code };
}

const asString = (v) => (typeof v === 'string' ? v : '');
const asNumber = (v) => (Number.isFinite(v) ? v : null);

function newTurn(r) {
  const before = Number.isInteger(r.decision) ? r.decision : 0;
  return {
    call: asNumber(r.call) ?? 0,
    first: before + 1,
    last: null,
    text: asString(r.text),
    thinking: asString(r.thinking),
    toolCalls: Array.isArray(r.tool_calls) ? r.tool_calls.map(describeToolCall) : [],
    modelStop: asString(r.stop),
    results: null,
    programs: [],
    installs: [],
    helpers: [],
    notes: [],
  };
}

/** results[] of a `results` record; text-mode runs have a single `text` instead. */
function resultList(r) {
  if (Array.isArray(r.results)) {
    return r.results.map((x) => ({ name: asString(x?.name), isError: x?.is_error === true, content: asString(x?.content) }));
  }
  return typeof r.text === 'string' ? [{ name: '', isError: false, content: r.text }] : [];
}

function program(r) {
  return {
    label: asString(r.label), job: asString(r.job), ok: r.ok !== false,
    limit: r.limit ?? null, commands: asNumber(r.commands), steps: asNumber(r.steps),
    firstDecision: asNumber(r.first_decision), ended: r.ended ?? null,
    seconds: asNumber(r.seconds), error: asString(r.error), output: '',
  };
}

/** Which tool answers for which kind of code run (hooks print into the last result of the turn instead). */
const OUTPUT_TOOL = [[(label) => label === 'run_code', 'run_code'], [(label) => label.startsWith('plugin '), 'plugin_call']];

/**
 * Gives each program the text its tool returned (what it printed): the n-th `run_code` run is answered by the
 * n-th `run_code` result of the turn, and the same for plugin tools.
 * @param {Turn} turn
 * @returns {Turn['programs']}
 */
function withOutputs(turn) {
  return turn.programs.map((p, i) => {
    const hit = OUTPUT_TOOL.find(([is]) => is(p.label));
    if (!hit) return p;
    const nth = turn.programs.slice(0, i).filter((q) => hit[0](q.label)).length;
    const answers = (turn.results ?? []).filter((x) => x.name === hit[1]);
    return { ...p, output: answers[nth]?.content ?? '' };
  });
}

/** The helper group of `agent` inside `turn`, created on first use. */
function helperIn(turn, agent, init = {}) {
  let hp = turn.helpers.find((x) => x.id === agent);
  if (!hp) {
    hp = { id: agent, parent: '', depth: 1, kind: '', events: [], turns: [], ...init };
    turn.helpers.push(hp);
  }
  return hp;
}

/**
 * @param {object[]} records  normalized transcript
 * @returns {{
 *   opening: string|null, turns: Turn[],
 *   briefings: {call:number, text:string, after:number}[],
 *   looseNotes: {text:string, after:number}[],
 *   end: {over:string, detail:string}|null,
 *   observations: Map<number,{text:string,complete:boolean}>,
 * }}
 */
export function parseTranscript(records) {
  /** @type {Turn[]} */ const turns = [];
  const briefings = [];
  const looseNotes = [];
  let opening = null;
  let end = null;
  /** @type {Turn|null} */ let cur = null;
  let decisionsSoFar = 0;
  const closeStalled = () => {
    if (cur && cur.last === null) cur.last = cur.first - 1; // a turn that made no decision
    cur = null;
  };

  for (const r of records) {
    switch (r.kind) {
      case 'opening': opening = asString(r.text); break;
      case 'assistant':
        if (r.agent) {
          if (cur) helperIn(cur, String(r.agent)).turns.push({
            call: asNumber(r.call) ?? 0, text: asString(r.text), thinking: asString(r.thinking),
            toolCalls: Array.isArray(r.tool_calls) ? r.tool_calls.map(describeToolCall) : [], results: null,
          });
        } else if (r.purpose !== 'summary') {
          closeStalled();
          cur = newTurn(r);
          turns.push(cur);
        }
        break;
      case 'results':
        if (r.agent) {
          const hp = cur ? helperIn(cur, String(r.agent)) : null;
          const t = hp?.turns.findLast((x) => x.results === null);
          if (t) t.results = resultList(r);
        } else if (cur) {
          cur.results = resultList(r);
          cur.programs = withOutputs(cur);
          cur.last = Number.isInteger(r.decision) ? r.decision : cur.first - 1;
          decisionsSoFar = Math.max(decisionsSoFar, cur.last);
          cur = null;
        }
        break;
      case 'code_run': if (cur) cur.programs.push(program(r)); break;
      case 'lib_install':
        if (cur) cur.installs.push({ name: asString(r.name), ok: r.ok !== false, detail: asString(r.detail), via: r.via ?? null });
        break;
      case 'helper':
        if (cur) {
          const hp = helperIn(cur, String(r.agent), { parent: asString(r.parent), depth: asNumber(r.depth) ?? 1 });
          if (r.event === 'spawn' || r.event === 'fork') hp.kind = r.event;
          hp.events.push({ event: asString(r.event), text: asString(r.text), state: asString(r.state) });
        }
        break;
      case 'summary':
        closeStalled();
        briefings.push({ call: asNumber(r.call) ?? 0, text: asString(r.text), after: decisionsSoFar });
        break;
      case 'note':
        if (cur) cur.notes.push(asString(r.text)); else looseNotes.push({ text: asString(r.text), after: decisionsSoFar });
        break;
      case 'end': closeStalled(); end = { over: asString(r.over), detail: asString(r.detail) }; break;
      default: break;
    }
  }
  closeStalled();
  return { opening, turns, briefings, looseNotes, end, observations: collectViews(opening, turns) };
}

/** A view starts a line with "Decision N (frame F"; a program's print() puts its own counter in front ("3 Decision 8 ..."). */
const VIEW_HEADER = /^(\d+ )?Decision (\d+) \(frame (\d+)/gm;
/** A full view has the state lines, the wands and the map; a fragment (a program's truncated print) has two lines. */
const FULL_VIEW_LINES = 6;

/**
 * Splits text at its "Decision N (frame F..." headers: one piece per view
 * (or fragment of one) that the text shows.
 * @param {string} text
 * @returns {{n:number, text:string, complete:boolean}[]}
 */
export function splitViews(text) {
  const heads = [...text.matchAll(VIEW_HEADER)];
  return heads.map((m, i) => {
    const start = m.index + (m[1]?.length ?? 0);
    const piece = text.slice(start, i + 1 < heads.length ? heads[i + 1].index : text.length).trimEnd();
    return { n: Number(m[2]), text: piece, complete: piece.split('\n').length >= FULL_VIEW_LINES };
  });
}

/**
 * The view shown at each decision number, from the opening and every results text.
 * A full view wins over a fragment; of two full ones the first stays.
 */
function collectViews(opening, turns) {
  /** @type {Map<number,{text:string,complete:boolean}>} */
  const out = new Map();
  const add = (text) => {
    for (const v of splitViews(text)) {
      const old = out.get(v.n);
      if (!old || (v.complete && !old.complete)) out.set(v.n, { text: v.text, complete: v.complete });
    }
  };
  if (opening) add(opening);
  for (const t of turns) for (const x of t.results ?? []) add(x.content);
  return out;
}

/**
 * The turn that made decision number `n`, or null (the run has no
 * transcript, or the decision belongs to a turn the log lost).
 * @param {Turn[]} turns
 * @param {number} n
 * @returns {Turn|null}
 */
export function turnForDecision(turns, n) {
  for (const t of turns) {
    if (n >= t.first && n <= (t.last ?? Infinity)) return t;
  }
  return null;
}
