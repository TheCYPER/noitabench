import { lastAtOrBefore } from '../format/recording.js';

/** Game frames per second at speed 1x. */
export const FRAMES_PER_SECOND = 60;
export const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];

/**
 * The playback state of the replay page: one plain object, no hidden state.
 * `time` is a game-frame position (float).
 * @returns {{time:number,playing:boolean,speed:number}}
 */
export function createPlayback() {
  return { time: 0, playing: false, speed: 1 };
}

/**
 * Index of the step to show at game frame `time`: the last step at or before
 * it (0 before the first one).
 * @param {{frame:number}[]} steps
 * @param {number} time  game frame, may be fractional
 * @returns {number}
 */
export function stepForTime(steps, time) {
  return Math.max(0, lastAtOrBefore(steps, time));
}

/**
 * Advances the clock by `dtMs` of wall time. At the end of the run playback
 * stops on the last frame.
 * @param {ReturnType<typeof createPlayback>} pb
 * @param {number} dtMs
 * @param {number} lastFrame
 */
export function advance(pb, dtMs, lastFrame) {
  if (!pb.playing) return;
  pb.time += (dtMs / 1000) * FRAMES_PER_SECOND * pb.speed;
  if (pb.time >= lastFrame) {
    pb.time = lastFrame;
    pb.playing = false;
  }
}

/**
 * Moves the clock onto a step (scrubbing, stepping); the step is clamped.
 * @param {ReturnType<typeof createPlayback>} pb
 * @param {{frame:number}[]} steps
 * @param {number} step
 * @returns {number} the step the clock is on now
 */
export function seekToStep(pb, steps, step) {
  const s = Math.max(0, Math.min(steps.length - 1, step));
  pb.time = steps[s].frame;
  return s;
}

/**
 * Events in the half-open window (frame - window, frame].
 * @param {{frame:number}[]} events  sorted by frame
 * @param {number} frame
 * @param {number} window  length in game frames
 */
export function eventsInWindow(events, frame, window) {
  const hi = lastAtOrBefore(events, frame);
  if (hi < 0) return [];
  const lo = lastAtOrBefore(events, frame - window);
  return events.slice(lo + 1, hi + 1);
}

/**
 * Moves the clock onto a game frame (the frame of a decision the user picked),
 * clamped to the run. Unlike seekToStep the clock is not snapped to a
 * recorded step: the picture shows the last step at or before it, and the
 * decision panel keeps showing the decision whose frame it is.
 * @param {ReturnType<typeof createPlayback>} pb
 * @param {number} frame
 * @param {number} first  first recorded frame
 * @param {number} last  last recorded frame
 * @returns {number} the frame the clock is on now
 */
export function seekToFrame(pb, frame, first, last) {
  pb.time = Math.min(last, Math.max(first, frame));
  return pb.time;
}
