import { clear, describeError, h } from '../ui/dom.js';

/**
 * The notes panel: the player's notebook, the same files and the same quota an agent's
 * `memory_*` commands use. Reading and writing go to /api/notes; they cost no game time and no
 * decision.
 *
 * @param {{
 *   api: ReturnType<typeof import('./api.js').createApi>,
 *   select: HTMLSelectElement, name: HTMLInputElement, text: HTMLTextAreaElement,
 *   quota: HTMLElement, status: HTMLElement, save: HTMLElement, fresh: HTMLElement, remove: HTMLElement,
 * }} o
 */
export function createNotesPanel(o) {
  let used = 0;
  let max = 0;

  const say = (msg, bad = false) => {
    o.status.textContent = msg;
    o.status.className = bad ? 'kv bad' : 'kv';
  };

  async function call(request) {
    try {
      const res = await o.api.notes(request);
      if (!res.ok) {
        say(`${res.error.message}（${res.error.code}）`, true);
        return null;
      }
      return res.result;
    } catch (err) {
      say(describeError(err), true);
      return null;
    }
  }

  function showQuota() {
    const left = max - used;
    o.quota.textContent = `笔记共 ${used}/${max} 字，还能写 ${left} 字；这个输入框 ${o.text.value.length} 字`;
  }

  async function refresh(keep = o.name.value) {
    const res = await call({ op: 'list' });
    if (!res) return;
    max = res.limit;
    used = res.used;
    clear(o.select);
    o.select.append(h('option', { value: '' }, '（选一份笔记）'));
    for (const f of res.files) o.select.append(h('option', { value: f.path, selected: f.path === keep }, `${f.path} · ${f.chars} 字`));
    showQuota();
  }

  async function open(path) {
    if (!path) return;
    const res = await call({ op: 'read', path });
    if (!res) return;
    o.name.value = res.path;
    o.text.value = res.text;
    showQuota();
    say(`已打开 ${res.path}`);
  }

  async function save() {
    const path = o.name.value.trim();
    if (!path) {
      say('先给这份笔记起个名字，例如 chemistry.md', true);
      return;
    }
    const res = await call({ op: 'write', path, text: o.text.value, append: false });
    if (!res) return;
    await refresh(path);
    say(`已保存 ${res.path}（${res.chars} 字）`);
  }

  async function remove() {
    const path = o.name.value.trim();
    if (!path || !window.confirm(`删除 ${path}？`)) return;
    const res = await call({ op: 'delete', path });
    if (!res) return;
    o.name.value = '';
    o.text.value = '';
    await refresh('');
    say(`已删除 ${res.path}`);
  }

  o.select.addEventListener('change', () => open(o.select.value));
  o.remove.addEventListener('click', remove);
  o.save.addEventListener('click', save);
  o.fresh.addEventListener('click', () => {
    o.name.value = '';
    o.text.value = '';
    o.select.value = '';
    showQuota();
    o.name.focus();
  });
  o.text.addEventListener('input', showQuota);

  return { refresh, open, save, remove };
}
