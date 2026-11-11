/* The Flow tab: the drawing of boxes and frames a run does (extraction/flow.py, engine.py), its library, its numbers,
   checked and saved through /api/flow, tried on one document with made-up answers (/api/flow/try). Takes the page's
   helpers from window.DP (app.js); app.js calls window.FlowTab. No library; English like the rest of the page. */
(function () {
'use strict';
const D = () => window.DP;
const el = (...a) => D().h(...a);
const clone = v => JSON.parse(JSON.stringify(v));
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);

const F = {
  loaded: false, loading: false, data: null, tree: null, cur: {}, sel: null, report: null, busy: false,
  meas: null, trial: null, trying: false, docs: null, doc: '', pages: '', mode: 'nothing', filter: '', fold: new Set(),
  drag: null,
};
const numDirty = () => !!F.data && F.data.numbers.some(n => F.cur[n.name] !== n.value);
const treeDirty = () => !!F.data && JSON.stringify(F.tree) !== JSON.stringify(F.data.tree);
const dirty = () => numDirty() || treeDirty();
function numbers() { const o = {}; for (const n of F.data.numbers) o[n.name] = F.cur[n.name]; return o; }

/* -- the drawing as data -------------------------------------------------------------------------------------- */

const kindOf = n => ['box', 'each', 'round', 'if'].find(k => n && Object.prototype.hasOwnProperty.call(n, k)) || '';
function lists(n) {
  const k = kindOf(n);
  if (k === 'each' || k === 'round') { n.steps = n.steps || []; return [{ label: '', steps: n.steps }]; }
  if (k === 'if') {
    const out = (n.if || []).map((w, i) => ({ label: 'way ' + (i + 1), way: w, steps: (w.steps = w.steps || []) }));
    if (Object.prototype.hasOwnProperty.call(n, 'else')) out.push({ label: 'else', steps: n.else });
    return out;
  }
  return [];
}
function* walk(steps, parent) {
  for (const n of steps) { yield [n, steps, parent]; for (const l of lists(n)) yield* walk(l.steps, n); }
}
function find(id) { for (const [n, steps, parent] of walk(F.tree)) if (n.id === id) return { n, steps, parent }; return null; }
function newId(base) {
  const ids = new Set([...walk(F.tree)].map(([n]) => n.id));
  let i = 1; while (ids.has(base + '_' + i)) i++;
  return base + '_' + i;
}
const lib = t => (F.data.library.boxes || []).find(b => b.type === t);
function labelOf(n) {
  const k = kindOf(n);
  if (k === 'box') { const b = lib(n.box); return b ? b.label : n.box; }
  if (k === 'each') return 'For each ' + n.each + (n.which ? ' (' + (F.data.library.which[n.which] || n.which) + ')' : '');
  if (k === 'round') return n.round && n.round.most ? 'Round, at most ' + n.round.most + ' times' : 'Round, until the supply is used up';
  return 'If';
}
function giveOf(n) {
  const k = kindOf(n);
  if (k === 'box') { const b = lib(n.box); return b ? b.gives : ''; }
  if (k === 'each') return n.each === 'coordinate' ? 'coordinates' : n.each === 'value' ? 'values' : n.each === 'field' ? 'fields' : n.each;
  return '';
}

/* -- conditions ------------------------------------------------------------------------------------------------- */

const OPS = { is: 'is', is_not: 'is not', less: 'less than', more: 'more than', at_least: 'at least', at_most: 'at most',
  contains: 'contains', empty: 'is empty', one_of: 'is one of' };
function subj(name) { return (F.data.conditions || []).find(s => s.name === name); }
function propOf(row) { const s = subj(row.of); return s && s.props.find(p => p.name === row.is); }
function sentence(c) {
  if (!isObj(c)) return '';
  const joiner = c.all ? ' and ' : ' or ';
  return 'when ' + (c.all || c.any || []).map(r => {
    const s = subj(r.of), p = propOf(r);
    if (!s || !p) return '(?)';
    if (p.kind === 'yes') return s.label + (r.not ? ' not: ' : ' ') + p.label;
    const v = Array.isArray(r.value) ? r.value.join(' or ') : r.value;
    return s.label + "'s " + p.label + (r.not ? ' not ' : ' ') + (OPS[r.op] || r.op) + (r.op === 'empty' ? '' : ' ' + v);
  }).join(joiner);
}
/* An editor of one condition: rows of [what][property][comparison][value][not], joined by all or any. */
function condEditor(get, set, only) {
  const wrap = el('div', { class: 'fw-cond' });
  const paint = () => {
    const c = get();
    const kids = [];
    if (!c) {
      kids.push(el('button', { text: '+ condition', onclick: () => { set({ all: [{ of: only || 'coordinate', is: firstProp(only || 'coordinate') }] }); paint(); } }));
      D().put(wrap, kids); return;
    }
    const joinerName = c.all ? 'all' : 'any', rows = c[joinerName];
    const joiner = el('select', {}, el('option', { value: 'all', text: 'all rows hold (and)' }), el('option', { value: 'any', text: 'one row holds (or)' }));
    joiner.value = joinerName;
    joiner.addEventListener('change', () => { const o = {}; o[joiner.value] = rows; set(o); paint(); });
    kids.push(el('div', { class: 'fw-row' }, joiner, el('button', { class: 'link', text: 'remove condition', onclick: () => { set(null); paint(); } })));
    rows.forEach((r, i) => kids.push(rowEditor(r, () => { set(c); paint(); }, () => { rows.splice(i, 1); if (!rows.length) set(null); else set(c); paint(); }, only)));
    kids.push(el('button', { text: '+ row', onclick: () => { rows.push({ of: only || 'coordinate', is: firstProp(only || 'coordinate') }); set(c); paint(); } }));
    kids.push(el('div', { class: 'help', text: sentence(c) }));
    D().put(wrap, kids);
  };
  paint();
  return wrap;
}
function firstProp(s) { const x = subj(s); return x ? x.props[0].name : ''; }
function rowEditor(r, changed, remove, only) {
  const subjects = (F.data.conditions || []).filter(s => only ? s.name === only : s.name !== 'line');
  const sSel = el('select', {}, subjects.map(s => el('option', { value: s.name, text: s.label })));
  sSel.value = r.of;
  const pSel = el('select', {}, (subj(r.of) ? subj(r.of).props : []).map(p => el('option', { value: p.name, text: p.label })));
  pSel.value = r.is;
  const p = propOf(r);
  const parts = [sSel, pSel];
  if (p && p.kind !== 'yes') {
    const oSel = el('select', {}, p.ops.map(o => el('option', { value: o, text: OPS[o] || o })));
    if (!p.ops.includes(r.op)) r.op = p.ops[0];
    oSel.value = r.op;
    oSel.addEventListener('change', () => { r.op = oSel.value; if (r.op === 'empty') delete r.value; changed(); });
    parts.push(oSel);
    if (r.op !== 'empty') {
      if (p.kind === 'choice') {
        const have = new Set(Array.isArray(r.value) ? r.value : []);
        parts.push(el('span', { class: 'fw-choices' }, p.choices.map(ch => {
          const box = el('input', { type: 'checkbox' }); box.checked = have.has(ch);
          box.addEventListener('change', () => { const v = new Set(Array.isArray(r.value) ? r.value : []); if (box.checked) v.add(ch); else v.delete(ch); r.value = p.choices.filter(x => v.has(x)); changed(); });
          return el('label', {}, box, ' ' + ch);
        })));
      } else {
        const inp = el('input', { type: p.kind === 'number' ? 'number' : 'text', value: r.value == null ? '' : String(r.value) });
        inp.addEventListener('change', () => { r.value = p.kind === 'number' ? (inp.value === '' ? undefined : Number(inp.value)) : inp.value; changed(); });
        parts.push(inp);
      }
    }
  } else { delete r.op; delete r.value; }
  const no = el('input', { type: 'checkbox' }); no.checked = !!r.not;
  no.addEventListener('change', () => { if (no.checked) r.not = true; else delete r.not; changed(); });
  parts.push(el('label', { title: 'the row holds where its sentence does not' }, no, ' not'));
  parts.push(el('button', { class: 'link', text: '−', title: 'remove the row', onclick: remove }));
  sSel.addEventListener('change', () => { r.of = sSel.value; r.is = firstProp(r.of); delete r.op; delete r.value; changed(); });
  pSel.addEventListener('change', () => { r.is = pSel.value; delete r.op; delete r.value; changed(); });
  return el('div', { class: 'fw-row' }, parts);
}

/* -- load, check, save -------------------------------------------------------------------------------------------- */

async function load(keep) {
  if (F.loading) return;
  F.loading = true;
  const wrap = D().$('fl-wrap');
  if (!F.loaded) D().put(wrap, el('div', { class: 'help fl-pad', text: 'Loading…' }));
  try {
    const d = await D().api('GET', '/api/flow');
    const prevCur = F.cur, prevTree = F.tree;
    F.data = d; F.cur = {};
    for (const n of d.numbers) F.cur[n.name] = keep && Object.prototype.hasOwnProperty.call(prevCur, n.name) ? prevCur[n.name] : n.value;
    F.tree = keep && prevTree ? prevTree : clone(d.tree);
    F.report = null; F.loaded = true;
  } catch (e) {
    F.loading = false;
    if (F.loaded) D().showError(e); else D().put(wrap, el('div', { class: 'box bad', text: e.message }));
    return;
  }
  F.loading = false;
  render(); D().renderHeader();
  measured();
}
async function check() {
  if (!F.data || F.busy) return;
  F.busy = true; render();
  try { F.report = { source: 'check', r: await D().apiR('/api/flow/check', { numbers: numbers(), tree: F.tree }) }; }
  catch (e) { F.report = { source: 'check', error: e.message }; }
  F.busy = false; render();
}
async function save() {
  if (!F.data || F.busy || !dirty()) return;
  F.busy = true; render();
  let saved = null;
  try {
    const r = await D().apiR('/api/flow/save', { numbers: numbers(), tree: F.tree, base: F.data.base == null ? null : F.data.base });
    if (r.saved) saved = r; else F.report = { source: 'save', r };
  } catch (e) { F.report = { source: 'save', error: e.message }; }
  F.busy = false;
  if (saved) { D().showInfo('Saved ' + (saved.file || 'the flow file') + ' (' + (saved.writes || 'written') + ').'); F.tree = null; await load(false); }
  else render();
}
async function discard() {
  if (!dirty() || F.busy) return;
  if (!await D().askConfirm('Discard changes', 'Discard the edited drawing and numbers?', 'Discard')) return;
  F.tree = clone(F.data.tree); for (const n of F.data.numbers) F.cur[n.name] = n.value;
  F.report = null; F.trial = null; render(); D().renderHeader();
}
async function reload() {
  if (dirty() && !await D().askConfirm('Reload from disk', 'The flow file changed on disk. Reloading drops the edits.', 'Drop my edits and reload')) return;
  F.tree = null; await load(false);
}
async function measured() {
  try { F.meas = await D().apiR('/api/flow/measured', { numbers: numbers(), trace: null }); }
  catch (e) { F.meas = null; }
  render();
}
async function tryIt() {
  if (F.trying) return;
  F.trying = true; render();
  const body = { tree: F.tree, numbers: numbers(), mode: F.mode };
  if (F.doc) {
    body.document = Number(F.doc);
    const m = /^\s*(\d+)\s*-\s*(\d+)\s*$/.exec(F.pages || '');
    if (m) body.pages = [Number(m[1]), Number(m[2])];
  }
  try { F.trial = await D().apiR('/api/flow/try', body); }
  catch (e) { F.trial = { error: e.message }; }
  F.trying = false; render();
}
async function docs() {
  if (F.docs) return;
  try { F.docs = await D().api('GET', '/api/flow/documents'); } catch (e) { F.docs = { db: null, documents: [] }; }
  render();
}

/* -- editing the drawing ---------------------------------------------------------------------------------------- */

function edited() { F.report = null; F.trial = null; render(); D().renderHeader(); }
function fresh(kind, arg) {
  if (kind === 'box') return { id: newId(arg), box: arg };
  if (kind === 'each') return { id: newId('each_' + arg), each: arg, steps: [] };
  if (kind === 'round') return { id: newId('round'), round: { most: 1 }, steps: [] };
  return { id: newId('if'), if: [{ when: { all: [{ of: 'coordinate', is: 'year' }] }, steps: [] }], else: [] };
}
function dropAt(steps, at) {
  const g = F.drag; F.drag = null;
  if (!g) return;
  let node;
  if (g.move) {
    const got = find(g.move);
    if (!got) return;
    for (const [n] of walk([got.n])) if (n.steps === steps || (n.if || []).some(w => w.steps === steps) || n.else === steps) return;
    const i = got.steps.indexOf(got.n);
    got.steps.splice(i, 1);
    if (got.steps === steps && i < at) at--;
    node = got.n;
  } else node = fresh(g.kind, g.arg);
  steps.splice(at, 0, node);
  F.sel = node.id;
  edited();
}
function arrow(steps, at, gives) {
  const a = el('div', { class: 'fw-arrow', title: 'drop a box here' }, el('span', { class: 'fw-line' }), gives ? el('span', { class: 'fw-gives', text: gives }) : null);
  a.addEventListener('dragover', ev => { if (F.drag) { ev.preventDefault(); a.classList.add('over'); } });
  a.addEventListener('dragleave', () => a.classList.remove('over'));
  a.addEventListener('drop', ev => { ev.preventDefault(); a.classList.remove('over'); dropAt(steps, at); });
  return a;
}
function move(id, by) {
  const got = find(id);
  const i = got.steps.indexOf(got.n), j = i + by;
  if (j < 0 || j >= got.steps.length) return;
  got.steps.splice(i, 1); got.steps.splice(j, 0, got.n); edited();
}
function remove(id) {
  const got = find(id);
  got.steps.splice(got.steps.indexOf(got.n), 1);
  if (F.sel === id) F.sel = null;
  edited();
}
function duplicate(id) {
  const got = find(id);
  const copy = clone(got.n);
  for (const [n] of walk([copy])) n.id = newId(n.id.replace(/_\d+$/, ''));
  got.steps.splice(got.steps.indexOf(got.n) + 1, 0, copy);
  F.sel = copy.id; edited();
}

/* -- drawing ------------------------------------------------------------------------------------------------------ */

function problemsOf(id) {
  const R = F.report && F.report.r;
  const said = R && R.errors ? R.errors : F.data.problems || [];
  return said.filter(p => p.id === id);
}
function counted(id) {
  const m = F.meas && F.meas.steps ? F.meas.steps[id] : null;
  const t = F.trial && F.trial.boxes && F.trial.boxes[id] ? F.trial.boxes[id].requests : null;
  const bits = [];
  if (m != null) bits.push(el('span', { class: 'fw-count', title: 'requests of this box in the recorded traces', text: m.toLocaleString('en-US') + ' in the last run' }));
  if (t != null) bits.push(el('span', { class: 'fw-count try', title: 'requests of this box in the try', text: t + ' in the try' }));
  return bits;
}
function card(n) {
  const k = kindOf(n), b = k === 'box' ? lib(n.box) : null;
  const never = b && F.data.never ? F.data.never[n.box] : null;
  const bad = problemsOf(n.id);
  const head = el('div', { class: 'fw-head' },
    k !== 'box' && lists(n).length ? el('button', { class: 'link fw-fold', text: F.fold.has(n.id) ? '▸' : '▾', onclick: ev => { ev.stopPropagation(); if (F.fold.has(n.id)) F.fold.delete(n.id); else F.fold.add(n.id); render(); } }) : null,
    el('b', { text: labelOf(n) }), ' ', el('code', { class: 'fw-id', text: n.id }),
    b && b.asks ? el('span', { class: 'fw-asks', text: 'asks ' + b.asks }) : null,
    ...counted(n.id),
    el('span', { class: 'spacer' }),
    el('button', { class: 'link', text: '↑', title: 'earlier', onclick: ev => { ev.stopPropagation(); move(n.id, -1); } }),
    el('button', { class: 'link', text: '↓', title: 'later', onclick: ev => { ev.stopPropagation(); move(n.id, 1); } }),
    el('button', { class: 'link', text: '⧉', title: 'duplicate', onclick: ev => { ev.stopPropagation(); duplicate(n.id); } }),
    !(b && (b.fixed || !b.switch)) ? el('button', { class: 'link', text: '✕', title: 'delete', onclick: ev => { ev.stopPropagation(); remove(n.id); } }) : null);
  const kids = [head];
  const said = [];
  if (n.when) said.push('only ' + sentence(n.when));
  if (k === 'each' && n.together) said.push('side by side');
  if (k === 'each' && n.order) said.push('order: ' + n.order.replace('_', ' '));
  if (k === 'round' && n.stop) said.push('stop ' + sentence(n.stop));
  if (said.length) kids.push(el('div', { class: 'fw-says', text: said.join(' · ') }));
  if (b && b.marks && b.marks.length) kids.push(el('div', { class: 'fw-marks', title: 'fixed checks, cannot be removed' }, b.marks.map(m => el('span', { class: 'badge', text: m }))));
  if (n.off) kids.push(el('div', { class: 'fw-off', text: 'switched off: no run takes this' }));
  if (never) kids.push(el('div', { class: 'fw-off', text: 'never taken by this profile: ' + never }));
  for (const p of bad) kids.push(el('div', { class: 'fw-bad', text: p.message }));
  if (k !== 'box' && !F.fold.has(n.id)) {
    const ways = lists(n);
    const inner = ways.map(w => el('div', { class: 'fw-way' },
      k === 'if' ? el('div', { class: 'fw-wayhead', text: w.label === 'else' ? 'else' : sentence(w.way.when) }) : null,
      column(w.steps)));
    kids.push(el('div', { class: k === 'if' ? 'fw-ways' : 'fw-inner' }, inner));
  } else if (k !== 'box') kids.push(el('div', { class: 'help', text: [...walk(lists(n).flatMap(l => l.steps))].length + ' boxes and frames inside' }));
  const c = el('div', { class: 'fw-card fw-' + (k || 'bad') + (F.sel === n.id ? ' sel' : '') + (n.off || never ? ' off' : '') + (bad.length ? ' bad' : ''), 'data-id': n.id }, kids);
  c.setAttribute('draggable', 'true');
  c.addEventListener('dragstart', ev => { ev.stopPropagation(); F.drag = { move: n.id }; ev.dataTransfer.setData('text/plain', n.id); });
  c.addEventListener('click', ev => { ev.stopPropagation(); F.sel = n.id; render(); });
  return c;
}
function column(steps) {
  const out = [arrow(steps, 0, '')];
  steps.forEach((n, i) => { out.push(card(n)); out.push(arrow(steps, i + 1, giveOf(n))); });
  return el('div', { class: 'fw-col' }, out);
}
function library() {
  const L = F.data.library, q = F.filter.toLowerCase();
  const item = (label, says, drag) => {
    if (q && !(label + ' ' + says).toLowerCase().includes(q)) return null;
    const it = el('div', { class: 'fw-lib', title: says, draggable: 'true' }, el('b', { text: label }), el('div', { class: 'help', text: says }));
    it.addEventListener('dragstart', ev => { F.drag = drag; ev.dataTransfer.setData('text/plain', label); });
    it.addEventListener('click', () => { const got = F.sel && find(F.sel); const steps = got ? got.steps : F.tree; F.drag = drag; dropAt(steps, got ? steps.indexOf(got.n) + 1 : steps.length); });
    return it;
  };
  const groups = {};
  for (const b of L.boxes) (groups[b.group] = groups[b.group] || []).push(b);
  const search = el('input', { type: 'text', placeholder: 'Search the library', value: F.filter });
  search.addEventListener('input', () => { F.filter = search.value; const r = D().$('fw-libitems'); if (r) D().put(r, libItems(groups, item, L)); });
  return el('div', { class: 'fw-left' }, el('div', { class: 'section', text: 'Library' }), search,
    el('div', { class: 'help', text: 'Drag onto an arrow, or click to put it after the chosen box.' }),
    el('div', { id: 'fw-libitems' }, libItems(groups, item, L)));
}
function libItems(groups, item, L) {
  const out = [el('div', { class: 'fw-group', text: 'frames' })];
  for (const [what, says] of Object.entries(L.each)) out.push(item('For each ' + what, says, { kind: 'each', arg: what }));
  out.push(item('Round', 'Its boxes again: at most N times, or until the supply is used up; stops where a condition holds.', { kind: 'round' }));
  out.push(item('If / else', 'Ways side by side, each under its condition, the last without one; they join again below.', { kind: 'if' }));
  for (const [g, list] of Object.entries(groups)) {
    out.push(el('div', { class: 'fw-group', text: g }));
    for (const b of list) out.push(item(b.label, b.says, { kind: 'box', arg: b.type }));
  }
  return out.filter(Boolean);
}

/* -- the settings of what is chosen ------------------------------------------------------------------------------- */

function settings() {
  const got = F.sel && find(F.sel);
  if (!got) return numbersPane();
  const n = got.n, k = kindOf(n), out = [el('div', { class: 'section', text: labelOf(n) }), el('div', { class: 'help mono', text: n.id })];
  const field = (label, input, help) => el('div', { class: 'fw-field' }, el('label', { text: label }), input, help ? el('div', { class: 'help', text: help }) : null);
  const b = k === 'box' ? lib(n.box) : null;
  if (b) {
    out.push(el('p', { class: 'help', text: b.says }));
    out.push(el('div', { class: 'help', text: 'takes ' + (b.takes || 'nothing') + ', gives ' + b.gives + ' · in the code: ' + b.code + (b.decided ? ' · decided ' + b.decided : '') }));
    if (b.fixed) out.push(el('div', { class: 'help', text: 'Fixed: ' + b.fixed }));
    if (b.asks && F.data.prompts[b.asks]) {
      const pr = F.data.prompts[b.asks];
      out.push(field('prompt', pr.written ? el('button', { class: 'link', text: pr.id, onclick: () => D().openPrompt(pr.id) }) : el('span', { class: 'help', text: pr.id + ' (not written)' })));
    }
    if (b.spec && F.data.switches[b.spec]) {
      const sw = F.data.switches[b.spec];
      out.push(field(sw.label, el('div', {}, sw.items.length ? sw.items.map((it, i) => [i ? ', ' : null, it.to ? el('button', { class: 'link', text: it.label, onclick: () => D().openSpec(it.to) }) : it.label]) : sw.none)));
    }
    for (const s of b.settings) out.push(settingField(n, s, field));
  }
  if (k === 'each') {
    if (n.each === 'field') {
      const w = el('select', {}, Object.entries(F.data.library.which).map(([v, t]) => el('option', { value: v, text: t })));
      w.value = n.which || 'all'; w.addEventListener('change', () => { n.which = w.value; edited(); });
      out.push(field('which', w));
    }
    const orders = (F.data.library.orders || {})[n.each] || [];
    if (orders.length > 1) {
      const o = el('select', {}, orders.map(v => el('option', { value: v, text: v.replace('_', ' ') })));
      o.value = n.order || orders[0]; o.addEventListener('change', () => { n.order = o.value; edited(); });
      out.push(field('order', o));
    }
    const t = el('input', { type: 'checkbox' }); t.checked = !!n.together;
    t.addEventListener('change', () => { if (t.checked) n.together = true; else delete n.together; edited(); });
    out.push(field('side by side', t, 'Its items are asked at the same time.'));
  }
  if (k === 'round') {
    const mode = el('select', {}, el('option', { value: 'most', text: 'at most N times' }), el('option', { value: 'supply', text: 'until the supply is used up' }));
    mode.value = n.round && n.round.supply ? 'supply' : 'most';
    const most = el('input', { type: 'number', min: 1, value: String((n.round && n.round.most) || 1) });
    mode.addEventListener('change', () => { n.round = mode.value === 'supply' ? { supply: true } : { most: Number(most.value) || 1 }; edited(); });
    most.addEventListener('change', () => { if (mode.value === 'most') { n.round = { most: Number(most.value) || 1 }; edited(); } });
    out.push(field('runs', el('span', {}, mode, ' ', mode.value === 'most' ? most : null)));
    out.push(field('stop when', condEditor(() => n.stop || null, c => { if (c) n.stop = c; else delete n.stop; edited(); })));
  }
  if (k === 'if') {
    n.if.forEach((w, i) => out.push(field('way ' + (i + 1) + ' when', el('div', {},
      condEditor(() => w.when || null, c => { w.when = c || { all: [{ of: 'coordinate', is: 'year' }] }; edited(); }),
      n.if.length > 1 ? el('button', { class: 'link', text: 'remove this way', onclick: () => { n.if.splice(i, 1); edited(); } }) : null))));
    out.push(el('button', { text: '+ way', onclick: () => { n.if.push({ when: { all: [{ of: 'coordinate', is: 'year' }] }, steps: [] }); edited(); } }));
    const e = el('input', { type: 'checkbox' }); e.checked = Object.prototype.hasOwnProperty.call(n, 'else');
    e.addEventListener('change', () => { if (e.checked) n.else = n.else || []; else delete n.else; edited(); });
    out.push(field('else way', e));
  }
  if (k !== 'if' && !(b && b.type === 'check')) out.push(field('only when', condEditor(() => n.when || null, c => { if (c) n.when = c; else delete n.when; edited(); })));
  if (!(b && (b.fixed || !b.switch))) {
    const off = el('input', { type: 'checkbox' }); off.checked = !n.off;
    off.addEventListener('change', () => { if (off.checked) delete n.off; else n.off = true; edited(); });
    out.push(field('on', off));
  }
  for (const p of problemsOf(n.id)) out.push(el('div', { class: 'fw-bad', text: p.message }));
  const t = F.trial && F.trial.boxes && F.trial.boxes[n.id];
  if (t && t.first) out.push(el('details', { class: 'fw-first' }, el('summary', { text: 'First request of the try (' + t.first.kind + ')' }),
    el('pre', { text: t.first.system }), el('pre', { text: t.first.message })));
  out.push(el('div', { class: 'fw-backrow' }, el('button', { class: 'link', text: '← numbers of the flow', onclick: () => { F.sel = null; render(); } })));
  return out;
}
function settingField(n, s, field) {
  const sets = n.set || {}, own = n.own || {};
  const put = (key, v) => { n.set = n.set || {}; if (v === undefined) delete n.set[key]; else n.set[key] = v; if (!Object.keys(n.set).length) delete n.set; edited(); };
  if (s.kind === 'number') {
    const named = F.data.numbers.find(x => x.name === s.number);
    const has = Object.prototype.hasOwnProperty.call(own, s.key);
    const only = el('input', { type: 'checkbox' }); only.checked = has;
    const inp = el('input', { type: 'number', min: named ? named.least : 0, value: String(has ? own[s.key] : (named ? F.cur[named.name] : '')), disabled: !has });
    only.addEventListener('change', () => { n.own = n.own || {}; if (only.checked) n.own[s.key] = Number(inp.value); else delete n.own[s.key]; if (!Object.keys(n.own).length) delete n.own; edited(); });
    inp.addEventListener('change', () => { if (only.checked) { n.own[s.key] = Number(inp.value); edited(); } });
    return field(s.label, el('span', {}, inp, ' ', el('label', { title: 'a value of its own instead of the named number ' + s.number }, only, ' only here')),
      (has ? 'own value; ' : 'the named number ') + s.number + (named && named.setting ? ' (a run setting ' + named.setting + ' wins over the named number, never over an own value)' : ''));
  }
  if (s.kind === 'rule') {
    return field(s.label, el('button', { class: 'link', text: (s.number ? s.number + ' = ' + F.cur[s.number] : 'rule ' + s.key) + ' →', onclick: () => s.number ? (F.sel = null, render()) : D().openRules('flow') }), s.help);
  }
  if (s.kind === 'switch') {
    const c = el('input', { type: 'checkbox' }); c.checked = Object.prototype.hasOwnProperty.call(sets, s.key) ? !!sets[s.key] : !!s.default;
    c.addEventListener('change', () => put(s.key, c.checked === !!s.default ? undefined : c.checked));
    return field(s.label, c, s.help);
  }
  if (s.kind === 'choice') {
    const sel = el('select', {}, s.choices.map(v => el('option', { value: v, text: v.replace(/_/g, ' ') })));
    sel.value = Object.prototype.hasOwnProperty.call(sets, s.key) ? sets[s.key] : s.default;
    sel.addEventListener('change', () => put(s.key, sel.value === s.default ? undefined : sel.value));
    return field(s.label, sel, s.help);
  }
  if (s.kind === 'text') {
    const inp = el('input', { type: 'text', value: sets[s.key] || '' });
    inp.addEventListener('change', () => put(s.key, inp.value || undefined));
    return field(s.label, inp, s.help);
  }
  if (s.kind === 'condition') {
    return field(s.label, condEditor(() => sets[s.key] || null, c => put(s.key, c || undefined), n.box === 'split' ? 'line' : null), s.help);
  }
  return null;
}
function numbersPane() {
  const out = [el('div', { class: 'section', text: 'Numbers of the flow' }),
    el('div', { class: 'help', text: 'Every box that takes a number takes the named one, unless it has its own value (only here). A setting of the run wins over the named number.' })];
  for (const n of F.data.numbers) {
    const inp = el('input', { type: 'number', min: n.least, value: String(F.cur[n.name]) });
    inp.classList.toggle('edited', F.cur[n.name] !== n.value);
    inp.addEventListener('change', () => { const v = /^-?\d+$/.test(inp.value.trim()) ? Number(inp.value) : inp.value; F.cur[n.name] = v; F.report = null; inp.classList.toggle('edited', v !== n.value); D().renderHeader(); renderBar(); measured(); });
    const bits = [];
    if (n.own) bits.push(el('span', { class: 'badge ok', text: 'set by this profile' }));
    if (n.setting && (n.in_effect !== n.value || !String(n.origin || '').startsWith('flow.json'))) bits.push(el('span', { class: 'badge changed', text: n.setting + ' = ' + n.in_effect + ' wins (' + n.origin + ')' }));
    const said = (F.meas && F.meas.says && F.meas.says[n.name]) || [];
    out.push(el('div', { class: 'fw-field' }, el('label', { title: n.help, text: n.name }), inp, ' ', bits, el('div', { class: 'help', text: n.help }),
      said.map(s => el('div', { class: 'fw-meas', title: 'what the last run measured, at the value in the field', text: s }))));
  }
  if (F.meas && F.meas.why) out.push(el('p', { class: 'help', text: 'Nothing measured: ' + F.meas.why + '.' }));
  for (const note of (F.meas && F.meas.notes) || []) out.push(el('p', { class: 'help', text: note }));
  for (const note of F.data.notes || []) out.push(el('p', { class: 'help' }, note.says));
  return out;
}

/* -- the bar, the report and the try ------------------------------------------------------------------------------ */

function renderBar() {
  const b = D().$('fw-bar');
  if (!b) return;
  const d = F.data;
  const line = !d.exists ? 'not written yet: the drawing and every number come from ' + d.starts_from
    : d.whole ? 'the whole flow of this profile' : (d.drawn_by === d.starts_from ? 'numbers of its own, the drawing of ' + d.drawn_by : 'its own drawing');
  D().put(b, el('code', { text: d.file }), el('span', { class: 'help', text: line }), el('span', { class: 'spacer' }),
    el('button', { text: 'Check', title: 'Ctrl+Enter', disabled: F.busy, onclick: check }),
    el('button', { class: 'primary', text: 'Save', title: 'Ctrl+S', disabled: F.busy || !dirty(), onclick: save }),
    el('button', { text: 'Discard', disabled: F.busy || !dirty(), onclick: discard }),
    el('button', { text: F.trying ? 'Trying…' : 'Try', disabled: F.trying, onclick: tryIt }),
    el('button', { text: 'Rules', onclick: () => D().openRules('flow') }));
}
function reportPane() {
  const out = [];
  const R = F.report;
  if (R) {
    if (R.error) out.push(el('div', { class: 'box bad', text: R.error }));
    else {
      const r = R.r || {};
      if (R.source === 'save' && r.reason === 'moved') out.push(el('div', { class: 'box bad' }, el('div', { text: r.message }), el('button', { text: 'Reload from disk', onclick: reload })));
      const errs = r.errors || [];
      if (errs.length) out.push(el('div', { class: 'box bad' }, el('b', { text: 'The run could not do this (' + errs.length + '):' }),
        errs.map(e => el('div', {}, e.id ? el('button', { class: 'link', text: e.id, onclick: () => { F.sel = e.id; render(); scrollTo(e.id); } }) : null, e.id ? ': ' : null, e.name ? e.name + ': ' : null, e.message))));
      else if (r.ok) out.push(el('div', { class: 'box ok', text: 'The run can do this drawing.' }));
      if (!errs.length && (r.changed || []).length) out.push(el('div', { class: 'box' }, el('b', { text: 'Changes' }), r.changed.map(c => el('div', {}, c.name === 'flow' ? c.to : c.name + ': ' + c.from + ' → ' + c.to))));
      if ((r.diff || []).length) out.push(el('details', {}, el('summary', { text: 'Diff of ' + (r.file || 'the file') }), D().diffPre(r.diff.join('\n'))));
      for (const s of r.says || []) out.push(el('div', { class: 'help', text: s }));
    }
  } else if ((F.data.problems || []).length) {
    out.push(el('div', { class: 'box bad' }, el('b', { text: 'The drawing on disk has problems:' }), F.data.problems.map(p => el('div', {}, p.id ? el('button', { class: 'link', text: p.id, onclick: () => { F.sel = p.id; render(); scrollTo(p.id); } }) : null, ' ' + p.message))));
  }
  return out;
}
function tryPane() {
  const out = [el('div', { class: 'section', text: 'Try' })];
  const mode = el('select', {}, el('option', { value: 'nothing', text: 'nothing found (a find names its piece\'s first number, or first word for a field of words; every other answer is empty)' }), el('option', { value: 'first_line', text: 'first line (every answer names the first line shown)' }));
  mode.value = F.mode; mode.addEventListener('change', () => { F.mode = mode.value; });
  const doc = el('select', {}, el('option', { value: '', text: 'the plan made up from the spec\'s examples' }),
    ((F.docs && F.docs.documents) || []).map(d => el('option', { value: String(d.id), text: d.id + ' ' + d.title })));
  doc.value = F.doc; doc.addEventListener('change', () => { F.doc = doc.value; });
  doc.addEventListener('focus', docs);
  const pages = el('input', { type: 'text', placeholder: 'pages, e.g. 1-12', value: F.pages, style: 'width:8em' });
  pages.addEventListener('change', () => { F.pages = pages.value; });
  out.push(el('div', { class: 'fw-row' }, doc, ' ', pages, ' ', mode, ' ', el('button', { text: F.trying ? 'Trying…' : 'Try', disabled: F.trying, onclick: tryIt })));
  const T = F.trial;
  if (T && T.error) out.push(el('div', { class: 'box bad', text: T.error }));
  else if (T) {
    out.push(el('div', { class: 'help', text: T.said }));
    out.push(el('div', {}, T.requests + ' requests, nothing sent; ' + T.values + ' values; ' + T.pieces + ' pieces' + (T.groups ? ' (' + T.groups + ' over several passages)' : '') + '. Each box shows its count; choose one for its first request.'));
    const states = Object.entries(T.states || {});
    if (states.length) out.push(el('table', { class: 'grid' }, el('thead', {}, el('tr', {}, el('th', { text: 'coordinate' }), el('th', { text: 'states' }))),
      el('tbody', {}, states.map(([c, st]) => el('tr', {}, el('td', { class: 'mono', text: c }), el('td', { text: Object.entries(st).map(([k, v]) => k + ' ' + v).join(', ') }))))));
  }
  return out;
}
function scrollTo(id) { const c = document.querySelector('.fw-card[data-id="' + id + '"]'); if (c) c.scrollIntoView({ block: 'center' }); }
function render() {
  const wrap = D().$('fl-wrap');
  if (!F.data || !wrap) return;
  const bar = el('div', { id: 'fw-bar', class: 'fl-bar toolbar' });
  const center = el('div', { class: 'fw-center' }, el('div', { class: 'help', text: 'The run does exactly this drawing. A way back is a round; a box goes where its arrow says what it takes.' }),
    column(F.tree), el('div', { class: 'fw-try' }, tryPane()));
  center.addEventListener('click', () => { if (F.sel) { F.sel = null; render(); } });
  D().put(wrap, bar, el('div', { class: 'pr-report' }, reportPane()),
    el('div', { class: 'fw-layout' }, library(), center, el('div', { class: 'fw-right' }, settings())));
  renderBar();
}

window.FlowTab = {
  load: () => load(true), loaded: () => F.loaded, dirty, save, check, reload,
  focus: name => { F.sel = null; render(); },
};
})();
