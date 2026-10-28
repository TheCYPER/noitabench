/**
 * Keeps a FrameStore showing the step the playback clock asks for, one seek
 * at a time, and never retries a step that failed.
 *
 * The page calls `pump(want)` on every animation frame. While a seek is
 * running further calls do nothing; when it ends `onSettled` lets the page
 * schedule the next frame.
 *
 * A failed seek (a corrupt record) must not be retried by the next frame:
 * the picture is blank and the same record would fail again, so a page would
 * spin on it forever. The step is remembered as "shown" instead, and the
 * next different step tries again.
 *
 * @param {{seek:(step:number)=>Promise<number>, applied:number}} store
 * @param {{
 *   onShown: (step:number) => void,
 *   onError: (err:unknown, step:number) => void,
 *   onSettled: () => void,
 * }} hooks
 */
export function createSync(store, hooks) {
  let shown = -1;
  let busy = false;
  return {
    /** Step on screen (or given up on after an error); -1 before the first seek. */
    get shown() { return shown; },
    get busy() { return busy; },
    /**
     * Starts a seek unless one is running or `want` is already shown.
     * @param {number} want
     * @returns {boolean} true if a seek is running after this call
     */
    pump(want) {
      if (busy || want === shown) return busy;
      busy = true;
      store.seek(want)
        .then(() => {
          shown = store.applied;
          hooks.onShown(shown);
        })
        .catch((err) => {
          shown = want;
          hooks.onError(err, want);
        })
        .finally(() => {
          busy = false;
          hooks.onSettled();
        });
      return true;
    },
  };
}
