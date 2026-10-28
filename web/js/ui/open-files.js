import { FileSet } from './file-set.js';

/**
 * Wires a drop zone, a folder picker and a file picker to one callback.
 *
 * @param {{
 *   drop: HTMLElement, folderInput: HTMLInputElement, filesInput: HTMLInputElement,
 *   folderButton: HTMLElement, filesButton: HTMLElement,
 *   onFiles: (files: FileSet) => void,
 * }} o
 */
export function wireOpeners(o) {
  const fromInput = (input) => {
    if (input.files && input.files.length > 0) o.onFiles(FileSet.fromFiles(input.files));
    input.value = ''; // allow choosing the same folder again
  };
  o.folderButton.addEventListener('click', () => o.folderInput.click());
  o.filesButton.addEventListener('click', () => o.filesInput.click());
  o.folderInput.addEventListener('change', () => fromInput(o.folderInput));
  o.filesInput.addEventListener('change', () => fromInput(o.filesInput));

  // The whole window accepts a drop, so a second run can be dropped at any time.
  let depth = 0;
  const mark = (on) => o.drop.classList.toggle('dragging', on);
  window.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; mark(true); });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (depth === 0) mark(false); });
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    depth = 0;
    mark(false);
    // Directory entries must be grabbed synchronously, inside the event.
    FileSet.fromDataTransfer(e.dataTransfer).then(o.onFiles, (err) => console.error(err));
  });
}
