/**
 * Whether a page-level keyboard shortcut should react to this key press.
 * Form fields keep their own keys (arrows on the progress slider, typing in
 * a select); a focused button or summary keeps Space and Enter, which click it, and
 * a focused link keeps Enter, but the other shortcuts still work after clicking a button.
 * @param {KeyboardEvent} e
 */
export function shortcutAllowed(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return false;
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return false;
  if ((tag === 'BUTTON' || tag === 'SUMMARY') && (e.key === ' ' || e.key === 'Enter')) return false;
  if (tag === 'A' && e.key === 'Enter') return false; // a focused link is followed, not shortcut
  return true;
}
