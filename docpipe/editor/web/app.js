'use strict';
/* docpipe spec editor page. Plain JavaScript, no library. The spec object is edited in place and sent back whole. */

/* ---------- pure helpers (also loaded in node) ---------- */

const own = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const clone = v => JSON.parse(JSON.stringify(v));

function writeString(obj, key, val) {
  if (val === '' || val == null) delete obj[key]; else obj[key] = val;
}
function writeNumber(obj, key, val) {
  if (val === '' || val == null || Number.isNaN(val)) delete obj[key]; else obj[key] = val;
}
/* keep: never remove the key (an enum list stays a list) */
function writeStrings(obj, key, arr, keep) {
  const a = arr.filter(s => s !== '');
  if (!a.length && !keep) delete obj[key]; else obj[key] = a;
}
/* lines widget: one list element per line; an empty text removes the key */
function writeLines(obj, key, text) {
  if (text === '') delete obj[key]; else obj[key] = text.split('\n');
}
function linesText(v) { return Array.isArray(v) ? v.join('\n') : (v == null ? '' : String(v)); }
function writeBool(obj, key, val, def, origObj) {
  const wasAbsent = !origObj || !own(origObj, key);
  if (def !== undefined && val === def && wasAbsent) delete obj[key]; else obj[key] = val;
}

function entryParts(e) {
  if (Array.isArray(e)) return { short: true, name: e[0] == null ? '' : String(e[0]), spellings: e.slice(1), definition: '', gloss: '', group: '' };
  const o = isObj(e) ? e : {};
  return {
    short: false, name: o.label == null ? '' : String(o.label),
    spellings: Array.isArray(o.spellings) ? o.spellings : [],
    definition: typeof o.definition === 'string' ? o.definition : '',
    gloss: typeof o.gloss === 'string' ? o.gloss : '',
    group: typeof o.group === 'string' ? o.group : '',
  };
}
function entryMatches(id, e, q) {
  const words = String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const p = entryParts(e);
  const hay = [id, p.name].concat(p.spellings).join('\n').toLowerCase();
  return words.every(w => hay.includes(w));
}
function hasSpelling(list, id, text) {
  const p = entryParts(list[id]);
  return p.name === text || p.spellings.includes(text);
}
/* a new spelling goes right after the name: index 1 of a short entry, index 0 of "spellings" */
function insertSpelling(list, id, text) {
  const e = list[id];
  if (Array.isArray(e)) e.splice(1, 0, text);
  else if (Array.isArray(e.spellings)) e.spellings.unshift(text);
  else e.spellings = [text];
}
function setEntryName(list, id, v) {
  const e = list[id];
  if (Array.isArray(e)) e[0] = v; else e.label = v;
}
/* definition, gloss, group: a short entry becomes the object form only when the user sets one */
function setEntryField(list, id, key, val) {
  const e = list[id];
  if (Array.isArray(e)) {
    if (val === '') return;
    const o = { label: e[0] == null ? '' : e[0] };
    const rest = e.slice(1);
    if (rest.length) o.spellings = rest;
    o[key] = val;
    list[id] = o;
  } else writeString(e, key, val);
}
/* a new list with the entry placed after afterId (else at the end); existing values are carried over untouched */
function listWithEntryAfter(list, afterId, id, entry) {
  const out = {};
  let placed = false;
  for (const k of Object.keys(list)) {
    out[k] = list[k];
    if (k === afterId) { out[id] = entry; placed = true; }
  }
  if (!placed) out[id] = entry;
  return out;
}
function newEntryFromTerm(t) {
  const e = { label: t.label };
  if (t.definition != null && t.definition !== '') e.definition = t.definition;
  return e;
}
/* an entry whose id is an IRI is shown by its last part; the whole id is its title */
function shortId(id) { const m = /^[a-z][a-z0-9+.-]*:\/\/.*[\/#]([^\/#]+)$/i.exec(String(id)); return m ? m[1] : String(id); }
function notesFor(notes, uri, coordinate, id) {
  const base = coordinate == null ? uri : uri + '.' + coordinate;
  return (notes || []).filter(n => n.id === id &&
    (n.where === base || n.where === base + '.vocabulary' || n.where === base + '.beside' || n.where === base + '.' + id));
}
function kindOf(axis) {
  const k = ['vocabulary', 'type', 'enum', 'dynamic'].filter(x => own(axis, x));
  return k;
}
function diffClass(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'hdr';
  if (line.startsWith('@@')) return 'hunk';
  if (line.startsWith('+')) return 'add';
  if (line.startsWith('-')) return 'del';
  return '';
}

/* names that may contain dots are matched as prefixes, the longest first */
function matchPrefix(names, rest) {
  const sorted = names.slice().sort((a, b) => b.length - a.length);
  for (const n of sorted) {
    if (rest === n) return { name: n, rest: '' };
    if (rest.startsWith(n + '.')) return { name: n, rest: rest.slice(n.length + 1) };
  }
  return null;
}
function firstSeg(s) { const i = s.indexOf('.'); return i < 0 ? s : s.slice(0, i); }
/* returns {node, field, entry}: the node of the tree that error.where names, the form key at its end, an entry id */
function locate(where, data) {
  let w = String(where || '');
  if (w === 'spec') return { node: { t: 'spec' }, field: null, entry: null };
  if (w.startsWith('spec.')) w = w.slice(5);
  let m;
  if ((m = /^parameters\[(\d+)\](?:\.(.*))?$/.exec(w))) {
    const param = (data.parameters || [])[+m[1]];
    if (!param) return { node: { t: 'spec' }, field: null, entry: null };
    const rest = m[2] || '';
    const entryIn = (list, r) => {
      if (!isObj(list)) return null;
      const f = matchPrefix(Object.keys(list), r);
      return f ? f.name : null;
    };
    if (rest === 'axes' || rest.startsWith('axes.')) {
      const r = rest === 'axes' ? '' : rest.slice(5);
      const ax = isObj(param.axes) ? matchPrefix(Object.keys(param.axes), r) : null;
      if (!ax) return { node: { t: 'param', uri: param.uri }, field: null, entry: null };
      const field = ax.rest ? firstSeg(ax.rest) : null;
      let entry = null;
      if ((field === 'vocabulary' || field === 'beside') && ax.rest.length > field.length + 1) {
        entry = entryIn(param.axes[ax.name][field], ax.rest.slice(field.length + 1));
      }
      return { node: { t: 'axis', uri: param.uri, name: ax.name }, field, entry };
    }
    const seg = rest ? firstSeg(rest) : null;
    if (seg === 'vocabulary' || seg === 'beside') {
      const entry = rest.length > seg.length + 1 ? entryIn(param[seg], rest.slice(seg.length + 1)) : null;
      return { node: { t: 'plist', uri: param.uri, list: seg }, field: seg, entry };
    }
    return { node: { t: 'param', uri: param.uri }, field: seg, entry: null };
  }
  if (w === 'plan_fields' || w.startsWith('plan_fields.')) {
    const r = w === 'plan_fields' ? '' : w.slice(12);
    const k = isObj(data.plan_fields) ? matchPrefix(Object.keys(data.plan_fields), r) : null;
    if (!k) return { node: { t: 'spec' }, field: null, entry: null };
    return { node: { t: 'plan', key: k.name }, field: k.rest ? firstSeg(k.rest) : null, entry: null };
  }
  if (w === 'works' || w.startsWith('works.')) {
    const r = w === 'works' ? '' : w.slice(6);
    return { node: { t: 'works' }, field: r ? firstSeg(r) : null, entry: null };
  }
  if (w === 'groups' || w.startsWith('groups.')) {
    const r = w === 'groups' ? '' : w.slice(7);
    const g = isObj(data.groups) ? matchPrefix(Object.keys(data.groups), r) : null;
    if (!g) return { node: { t: 'spec' }, field: null, entry: null };
    return { node: { t: 'group', name: g.name }, field: g.rest ? firstSeg(g.rest) : null, entry: null };
  }
  return { node: { t: 'spec' }, field: firstSeg(w) || null, entry: null };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { own, isObj, writeString, writeNumber, writeStrings, writeLines, linesText, writeBool, entryParts, entryMatches,
    hasSpelling, insertSpelling, setEntryName, setEntryField, listWithEntryAfter, newEntryFromTerm,
    notesFor, shortId, kindOf, diffClass, matchPrefix, locate };
}

/* ---------- page ---------- */
if (typeof document !== 'undefined') (function () {

const S = {
  state: null, data: null, orig: null, base: null, form: {}, pin: {}, notes: [],
  sel: { t: 'spec' }, dirty: false, expanded: new Set(), result: null, stale: false,
  generate: null, busy: false, panelOpen: true, flag: null, tab: 'spec',
};
const $ = id => document.getElementById(id);

/* replaceChildren without the absent ones: the DOM writes a null child as the text "null" */
function put(el, ...kids) { el.replaceChildren(...kids.flat().filter(c => c != null && c !== false)); }
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k === 'value') e.value = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, '');
    else e.setAttribute(k, v);
  }
  for (const c of kids.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}

/* ---------- server calls and messages ---------- */

function errText(e) {
  if (!e) return 'unknown error';
  if (typeof e === 'string') return e;
  return (e.message || 'error') + (e.where ? ' (' + e.where + ')' : '');
}
async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (method === 'POST') {
    opts.headers['Content-Type'] = 'application/json';
    opts.headers['X-Docpipe-Edit'] = '1';
    opts.body = JSON.stringify(body == null ? {} : body);
  }
  let res;
  try { res = await fetch(url, opts); }
  catch (e) { throw new Error('The server cannot be reached: ' + e.message); }
  let j;
  try { j = await res.json(); }
  catch (e) { throw new Error('The server answered ' + res.status + ' without JSON.'); }
  if (isObj(j) && typeof j.error === 'string') throw new Error(j.error);
  if (!res.ok && !(isObj(j) && ('saved' in j || 'ok' in j))) throw new Error(errText(j && j.error) || ('The server answered ' + res.status + '.'));
  return j;
}
function showBar(text, info) {
  const b = $('errbar');
  b.className = info ? 'info' : '';
  put(b, h('span', { class: 'msg', text }), h('button', { text: 'Dismiss', onclick: () => { b.hidden = true; } }));
  b.hidden = false;
}
const showError = e => showBar(e && e.message ? e.message : String(e), false);
const showInfo = t => showBar(t, true);
function clearBar() { $('errbar').hidden = true; }

/* ---------- dialogs ---------- */

function closeModal() { const m = $('modal'); m.hidden = true; put(m); m.onkeydown = null; }
function openModal(title, body, buttons, onClose) {
  const m = $('modal');
  const close = () => { closeModal(); if (onClose) onClose(); };
  put(m, h('div', { class: 'dlg' }, h('h3', { text: title }), h('div', { class: 'dbody' }, body),
    h('div', { class: 'dfoot' }, buttons.map(b => h('button', { class: b.cls, text: b.text, onclick: () => b.fn(close) })))));
  m.onkeydown = ev => { if (ev.key === 'Escape') close(); };
  m.onmousedown = ev => { if (ev.target === m) close(); };
  m.hidden = false;
  return close;
}
function askText(title, label, initial) {
  return new Promise(resolve => {
    const inp = h('input', { type: 'text', value: initial || '' });
    let done = false;
    const fin = v => { if (!done) { done = true; resolve(v); } };
    const close = openModal(title, [h('label', { text: label }), inp],
      [{ text: 'Cancel', fn: c => { fin(null); c(); } }, { text: 'OK', cls: 'primary', fn: c => { fin(inp.value.trim()); c(); } }],
      () => fin(null));
    inp.addEventListener('keydown', ev => { if (ev.key === 'Enter') { fin(inp.value.trim()); close(); } });
    inp.focus(); inp.select();
  });
}
function askConfirm(title, text, okText) {
  return new Promise(resolve => {
    let done = false;
    const fin = v => { if (!done) { done = true; resolve(v); } };
    openModal(title, h('div', { text, style: 'white-space:pre-wrap' }),
      [{ text: 'Cancel', fn: c => { fin(false); c(); } }, { text: okText || 'OK', cls: 'primary', fn: c => { fin(true); c(); } }],
      () => fin(false));
  });
}

/* ---------- data access ---------- */

const findParam = (data, uri) => (data && data.parameters || []).find(p => p.uri === uri);
function nodeObj(data, n) {
  if (!data) return undefined;
  switch (n.t) {
    case 'spec': return data;
    case 'plan': return data.plan_fields && data.plan_fields[n.key];
    case 'works': return data.works;
    case 'group': return data.groups && data.groups[n.name];
    case 'param': return findParam(data, n.uri);
    case 'plist': return findParam(data, n.uri);
    case 'axis': { const p = findParam(data, n.uri); return p && p.axes && p.axes[n.name]; }
  }
}
const nodeKey = n => JSON.stringify(n);
function ensureSel() { if (!nodeObj(S.data, S.sel)) S.sel = { t: 'spec' }; }
function markDirty() { S.dirty = true; if (S.result) S.stale = true; renderHeader(); renderPanelStale(); }
const listCount = l => (isObj(l) ? Object.keys(l).length : 0);

/* ---------- header ---------- */

function renderHeader() {
  const st = S.state || {};
  const hd = $('hdr');
  put(hd, 
    h('span', { class: 'title', text: 'docpipe edit' }),
    h('span', { class: 'meta' }, 'profile ', h('code', { text: st.profile || '' })),
    h('span', { class: 'meta' }, h('code', { text: st.spec || '' })),
    st.branch ? h('span', { class: 'meta' }, 'branch ', h('code', { text: st.branch })) : null,
    st.harvest ? h('span', { class: 'meta', title: st.harvest }, 'harvest: ', st.harvest_documents == null ? '' : st.harvest_documents + ' documents') : null,
    (st.changed && st.changed.length) ? h('span', { class: 'meta changed', title: st.changed.join('\n') }, 'uncommitted: ' + st.changed.join(', ')) : null,
    h('span', { class: 'tabs' }, (st.tabs || ['spec']).map(t => h('button', { class: t === S.tab ? 'on' : '', text: t.charAt(0).toUpperCase() + t.slice(1), onclick: () => { S.tab = t; } }))),
    h('span', { class: 'spacer' }),
    S.dirty ? h('span', { class: 'dirty', text: 'Unsaved edits' }) : h('span', { class: 'clean', text: 'No unsaved edits' }),
    h('button', { text: 'Reload from disk', disabled: S.busy, onclick: () => reload() }),
    h('button', { text: 'Check', disabled: S.busy, title: 'Ctrl+Enter', onclick: () => doCheck() }),
    h('button', { class: 'primary', text: 'Save', disabled: S.busy, title: 'Ctrl+S', onclick: () => doSave(false) }));
  document.title = (S.dirty ? '* ' : '') + 'docpipe edit ' + (st.profile || '');
}

/* ---------- tree ---------- */

function kindLabel(ax) {
  if (own(ax, 'vocabulary')) return 'list · ' + listCount(ax.vocabulary) + ' entries';
  if (own(ax, 'type')) return String(ax.type);
  if (own(ax, 'enum')) return 'strings';
  if (own(ax, 'dynamic')) return 'per document';
  return 'no kind';
}
function renderTree() {
  const tree = $('tree');
  const top = tree.scrollTop;
  const d = S.data;
  const els = [];
  const node = (n, label, sub, cls, extra) => {
    const sel = nodeKey(n) === nodeKey(S.sel);
    return h('button', { class: 'node ' + (cls || '') + (sel ? ' sel' : ''), 'data-node': nodeKey(n), onclick: () => select(n) },
      extra || h('span', { class: 'caret' }), h('span', { class: 'name', text: label, title: label }), sub ? h('span', { class: 'sub', text: sub }) : null);
  };
  els.push(h('div', { class: 'tree-h', text: 'Questions' }), node({ t: 'spec' }, 'Top-level questions', '', ''));
  els.push(h('div', { class: 'tree-h', text: 'Document' }));
  for (const k of ['settings', 'base_year', 'target_year']) {
    if (isObj(d.plan_fields) && own(d.plan_fields, k)) els.push(node({ t: 'plan', key: k }, k, 'plan field', ''));
    else els.push(h('button', { class: 'node addnode', text: '+ Add plan field ' + k, onclick: () => addPlanField(k) }));
  }
  for (const k of Object.keys(isObj(d.plan_fields) ? d.plan_fields : {})) {
    if (!['settings', 'base_year', 'target_year'].includes(k)) els.push(node({ t: 'plan', key: k }, k, 'plan field', ''));
  }
  if (own(d, 'works')) els.push(node({ t: 'works' }, 'works', 'other works', ''));
  else els.push(h('button', { class: 'node addnode', text: '+ Add works', onclick: addWorks }));
  const groups = Object.keys(isObj(d.groups) ? d.groups : {});
  els.push(h('div', { class: 'tree-h', text: 'Groups (' + groups.length + ')' }));
  for (const g of groups) els.push(node({ t: 'group', name: g }, g, d.groups[g] && Array.isArray(d.groups[g].coordinates) ? d.groups[g].coordinates.length + ' coordinates' : '', ''));
  const ps = d.parameters || [];
  els.push(h('div', { class: 'tree-h', text: 'Fields (' + ps.length + ')' }));
  for (const p of ps) {
    const open = S.expanded.has(p.uri);
    const caret = h('span', { class: 'caret', text: open ? '▾' : '▸', onclick: ev => { ev.stopPropagation(); if (open) S.expanded.delete(p.uri); else S.expanded.add(p.uri); renderTree(); } });
    els.push(node({ t: 'param', uri: p.uri }, p.label || p.uri, p.label ? p.uri : (p.value_type || ''), '', caret));
    if (!open) continue;
    for (const l of ['vocabulary', 'beside']) {
      if (isObj(p[l])) els.push(node({ t: 'plist', uri: p.uri, list: l }, l === 'vocabulary' ? 'list' : 'beside list', listCount(p[l]) + ' entries', 'l1'));
    }
    if (isObj(p.axes)) for (const [name, ax] of Object.entries(p.axes)) els.push(node({ t: 'axis', uri: p.uri, name }, name, isObj(ax) ? kindLabel(ax) : '', 'l1'));
  }
  put(tree, ...els);
  tree.scrollTop = top;
  const s = tree.querySelector('.node.sel');
  if (s) s.scrollIntoView({ block: 'nearest' });
}

function select(n, flag) {
  S.sel = n;
  S.flag = flag || null;
  if (n.uri) S.expanded.add(n.uri);
  renderTree(); renderMain();
}

/* ---------- form widgets ---------- */

function helpBlock(text) {
  if (!text) return null;
  const p = h('div', { class: 'help' + (text.length > 150 ? ' clamped' : ''), text });
  if (text.length <= 150) return p;
  const b = h('button', { class: 'link', text: 'more', onclick: () => { const c = p.classList.toggle('clamped'); b.textContent = c ? 'more' : 'less'; } });
  return h('div', {}, p, b);
}
function fieldWrap(f, control, extra) {
  return h('div', { class: 'field', 'data-key': f.key }, h('label', {}, h('code', { text: f.key })), helpBlock(f.help), control, extra);
}

function widgetLine(f, obj) {
  const el = h('input', { type: 'text', value: typeof obj[f.key] === 'string' ? obj[f.key] : (obj[f.key] == null ? '' : String(obj[f.key])), spellcheck: 'false' });
  el.addEventListener('input', () => { writeString(obj, f.key, el.value); markDirty(); });
  return el;
}
function widgetText(f, obj) {
  const el = h('textarea', { rows: 4, value: typeof obj[f.key] === 'string' ? obj[f.key] : (obj[f.key] == null ? '' : String(obj[f.key])) });
  el.addEventListener('input', () => { writeString(obj, f.key, el.value); markDirty(); });
  return el;
}
function widgetLines(f, obj) {
  const el = h('textarea', { class: 'lines', rows: 6, value: linesText(obj[f.key]) });
  el.addEventListener('input', () => { writeLines(obj, f.key, el.value); markDirty(); });
  return el;
}
function widgetBool(f, obj, orig) {
  const cur = own(obj, f.key) ? !!obj[f.key] : !!f.default;
  const el = h('input', { type: 'checkbox' });
  el.checked = cur;
  el.addEventListener('change', () => { writeBool(obj, f.key, el.checked, f.default, orig); markDirty(); });
  return h('div', { class: 'checkrow' }, el, h('span', { class: 'help', text: own(obj, f.key) ? '' : '(not set; default ' + (f.default ? 'true' : 'false') + ')' }));
}
function widgetChoice(f, obj) {
  const el = h('select');
  const cur = obj[f.key];
  const opts = (f.choices || []).slice();
  if (cur != null && !opts.includes(cur)) opts.push(cur);
  el.append(h('option', { value: '', text: own(obj, f.key) ? '(remove)' : '(not set)' }));
  for (const o of opts) el.append(h('option', { value: o, text: String(o) }));
  el.value = cur == null ? '' : cur;
  el.addEventListener('change', () => { writeString(obj, f.key, el.value); markDirty(); });
  return el;
}
function widgetNumber(f, obj) {
  const el = h('input', { type: 'number', step: 'any', value: obj[f.key] == null ? '' : obj[f.key] });
  el.addEventListener('input', () => {
    if (el.value === '') writeNumber(obj, f.key, ''); else { const n = Number(el.value); if (Number.isNaN(n)) return; writeNumber(obj, f.key, n); }
    markDirty();
  });
  return el;
}
function stringsEditor(obj, key, opts) {
  opts = opts || {};
  const box = h('div');
  let items = Array.isArray(obj[key]) ? obj[key].map(String) : [];
  const commit = () => { writeStrings(obj, key, items, opts.keep); markDirty(); };
  const draw = () => {
    put(box, ...items.map((s, i) => h('div', { class: 'strrow' },
      h('input', { type: 'text', value: s, spellcheck: 'false', list: opts.datalist, oninput: ev => { items[i] = ev.target.value; commit(); } }),
      h('button', { text: '↑', disabled: i === 0, onclick: () => { [items[i - 1], items[i]] = [items[i], items[i - 1]]; commit(); draw(); } }),
      h('button', { text: '↓', disabled: i === items.length - 1, onclick: () => { [items[i + 1], items[i]] = [items[i], items[i + 1]]; commit(); draw(); } }),
      h('button', { class: 'danger', text: '×', title: 'Remove', onclick: () => { items.splice(i, 1); commit(); draw(); } }))),
      h('button', { text: '+ Add', onclick: () => { items.push(''); draw(); const ins = box.querySelectorAll('input'); ins[ins.length - 1].focus(); } }));
  };
  draw();
  return box;
}
function widgetJson(f, obj, wrap) {
  let committed = own(obj, f.key) ? JSON.stringify(obj[f.key], null, 2) : '';
  const el = h('textarea', { class: 'json', rows: 8, value: committed, spellcheck: 'false' });
  const err = h('div', { class: 'err', hidden: true });
  const setErr = m => { err.textContent = m || ''; err.hidden = !m; wrap.classList.toggle('bad', !!m); };
  el.addEventListener('blur', () => {
    const t = el.value;
    if (t === committed) { setErr(''); return; }
    if (t.trim() === '') { delete obj[f.key]; committed = t; setErr(''); markDirty(); return; }
    try { obj[f.key] = JSON.parse(t); committed = t; setErr(''); markDirty(); }
    catch (e) { setErr('JSON error: ' + e.message + ' (the text is kept, nothing is written)'); }
  });
  return [el, err];
}

function widgetStrings(f, obj, ctx) { return stringsEditor(obj, f.key, { datalist: ctx.datalist }); }

function widgetUnits(f, obj, orig) {
  const box = h('div');
  const units = () => obj[f.key];
  const origUnit = u => orig && isObj(orig[f.key]) ? orig[f.key][u] : undefined;
  const draw = () => {
    const u = isObj(units()) ? units() : {};
    const rows = Object.keys(u).map(name => {
      const bare = !isObj(u[name]);
      const factor = bare ? u[name] : u[name].factor;
      const fIn = h('input', { type: 'number', step: 'any', value: factor == null ? '' : factor });
      const pIn = h('input', { type: 'checkbox' }); pIn.checked = !bare && !!u[name].names_period;
      const tIn = h('input', { type: 'text', value: bare ? '' : (u[name].target || ''), spellcheck: 'false' });
      const cur = () => units()[name];
      const toObj = () => { if (!isObj(cur())) units()[name] = { factor: cur() }; return units()[name]; };
      fIn.addEventListener('input', () => { const n = Number(fIn.value); if (fIn.value === '' || Number.isNaN(n)) return; if (isObj(cur())) cur().factor = n; else units()[name] = n; markDirty(); });
      pIn.addEventListener('change', () => {
        if (!isObj(cur())) { if (!pIn.checked) return; toObj().names_period = true; }
        else writeBool(cur(), 'names_period', pIn.checked, false, isObj(origUnit(name)) ? origUnit(name) : null);
        markDirty();
      });
      tIn.addEventListener('input', () => {
        if (!isObj(cur())) { if (tIn.value === '') return; toObj().target = tIn.value; }
        else writeString(cur(), 'target', tIn.value);
        markDirty();
      });
      return h('tr', {}, h('td', { class: 'mono', text: name }), h('td', {}, fIn), h('td', {}, pIn), h('td', {}, tIn),
        h('td', {}, h('button', { class: 'danger', text: 'Remove', title: 'Removed here, written with the next confirmed save', onclick: () => {
          delete units()[name]; if (!Object.keys(units()).length) delete obj[f.key]; markDirty(); draw(); } })));
    });
    const nu = h('input', { type: 'text', placeholder: 'new unit', spellcheck: 'false' });
    const nf = h('input', { type: 'number', step: 'any', placeholder: 'factor' });
    put(box, 
      h('table', { class: 'grid' }, h('tr', {}, h('th', { text: 'unit' }), h('th', { text: 'factor' }), h('th', { text: 'names a period' }), h('th', { text: 'target' }), h('th')), rows),
      h('div', { class: 'row2' }, nu, nf, h('button', { text: 'Add unit', onclick: () => {
        const name = nu.value.trim(); const n = Number(nf.value);
        if (!name || nf.value === '' || Number.isNaN(n)) { showError(new Error('A unit needs a name and a factor.')); return; }
        if (isObj(units()) && own(units(), name)) { showError(new Error('The unit ' + name + ' exists already.')); return; }
        if (!isObj(units())) obj[f.key] = {};
        obj[f.key][name] = n; markDirty(); draw(); } })));
  };
  draw();
  return box;
}

function widgetQuestions(f, obj) {
  const box = h('div');
  const q = () => obj[f.key];
  const draw = () => {
    const cur = isObj(q()) ? q() : {};
    const uris = (S.data.parameters || []).map(p => p.uri);
    const rows = Object.keys(cur).map(k => {
      const sel = h('select');
      const opts = uris.includes(k) ? uris : uris.concat([k]);
      for (const u of opts) sel.append(h('option', { value: u, text: u }));
      sel.value = k;
      let key = k;
      sel.addEventListener('change', () => {
        if (own(q(), sel.value)) { showError(new Error('A question for ' + sel.value + ' exists already.')); sel.value = key; return; }
        const nq = {}; for (const [kk, v] of Object.entries(q())) nq[kk === key ? sel.value : kk] = v;
        obj[f.key] = nq; key = sel.value; markDirty();
      });
      const ta = h('textarea', { rows: 3, value: cur[k] });
      ta.addEventListener('input', () => { q()[key] = ta.value; markDirty(); });
      return h('div', { class: 'row2' }, h('div', { style: 'width:240px;flex:none' }, sel), h('div', { style: 'flex:1' }, ta),
        h('button', { class: 'danger', text: '×', title: 'Remove', onclick: () => { delete q()[key]; markDirty(); draw(); } }));
    });
    put(box, ...rows, h('button', { text: '+ Add question', onclick: () => {
      const free = uris.find(u => !own(cur, u));
      if (!free) { showError(new Error('Every field has a question already.')); return; }
      if (!isObj(q())) obj[f.key] = {};
      obj[f.key][free] = ''; markDirty(); draw(); } }));
  };
  draw();
  return box;
}

function renderWidget(f, obj, orig, ctx) {
  const wrap = h('div', { class: 'field', 'data-key': f.key });
  let ctl;
  switch (f.widget) {
    case 'line': ctl = widgetLine(f, obj); break;
    case 'text': ctl = widgetText(f, obj); break;
    case 'lines': ctl = widgetLines(f, obj); break;
    case 'bool': ctl = widgetBool(f, obj, orig); break;
    case 'choice': ctl = widgetChoice(f, obj); break;
    case 'number': ctl = widgetNumber(f, obj); break;
    case 'strings': ctl = widgetStrings(f, obj, ctx); break;
    case 'json': ctl = widgetJson(f, obj, wrap); break;
    case 'units': ctl = widgetUnits(f, obj, orig); break;
    case 'questions': ctl = widgetQuestions(f, obj); break;
    case 'entries': ctl = entriesTable(ctx.refFor ? ctx.refFor(f.key) : null); break;
    default: ctl = h('div', { class: 'warn', text: 'Unknown widget "' + f.widget + '" for this key; it is kept as it is.' });
  }
  wrap.append(h('label', {}, h('code', { text: f.key })), helpBlock(f.help), ...[].concat(ctl));
  if (f.widget === 'line' && ctx.onUri && f.key === 'uri') {
    wrap.querySelector('input').addEventListener('change', ev => ctx.onUri(ev.target.value));
  }
  return wrap;
}
function renderForm(fields, obj, orig, ctx) {
  ctx = ctx || {};
  const skip = ctx.skip || new Set();
  const box = h('div', { class: 'form' });
  const shown = new Set();
  for (const f of fields || []) {
    if (skip.has(f.key)) { shown.add(f.key); continue; }
    shown.add(f.key);
    box.append(renderWidget(f, obj, orig, ctx));
  }
  const other = Object.keys(obj).filter(k => !shown.has(k) && !(ctx.skipQuiet && ctx.skipQuiet.has(k)));
  if (other.length) box.append(h('div', { class: 'others' }, 'Other keys kept untouched: ', other.map(k => h('code', { text: k + ' ' }))));
  return box;
}

/* ---------- entries table ---------- */

function entriesTable(ref) {
  const wrap = h('div', { class: 'entries' });
  if (!ref) return h('div', { class: 'warn', text: 'No list here.' });
  let selected = null;
  const list = () => { const hd = ref.holder(); return hd && isObj(hd[ref.key]) ? hd[ref.key] : {}; };
  const origList = () => { const o = ref.orig && ref.orig(); return o && isObj(o[ref.key]) ? o[ref.key] : {}; };
  const search = h('input', { type: 'text', placeholder: 'Filter by id, name or spelling', spellcheck: 'false' });
  const count = h('span', { class: 'count' });
  const tbody = h('tbody');
  const rowsById = new Map();
  const noteMap = id => notesFor(S.notes, ref.uri, ref.coordinate, id);

  const applyFilter = () => {
    const l = list(); let n = 0;
    for (const [id, tr] of rowsById) {
      const ok = entryMatches(id, l[id], search.value);
      tr.main.hidden = !ok; if (tr.detail) tr.detail.hidden = !ok || !tr.open;
      if (ok) n++;
    }
    count.textContent = n + ' of ' + rowsById.size + ' entries shown';
  };
  const afterStructural = () => { const top = $('main').scrollTop; renderTree(); renderMain(); $('main').scrollTop = top; };
  const remove = async (body, what) => {
    await run(async () => {
      const r = await api('POST', '/api/spec/remove', Object.assign({ data: S.data }, body));
      if (!r.ok) throw new Error(errText(r.error));
      S.data = r.data; markDirty(); afterStructural();
      showInfo('Removed ' + what + ' here. It is written with the next confirmed save.');
    });
  };
  const select_ = id => { selected = id; for (const [k, tr] of rowsById) tr.main.classList.toggle('sel', k === id); };

  const buildRow = id => {
    const l = list();
    const p = entryParts(l[id]);
    const notes = noteMap(id);
    const nameIn = h('input', { type: 'text', value: p.name });
    nameIn.addEventListener('input', () => { setEntryName(list(), id, nameIn.value); markDirty(); });
    const chips = h('div', { class: 'chips' });
    const drawChips = () => {
      const cur = entryParts(list()[id]);
      const add = h('input', { type: 'text', placeholder: 'add spelling', spellcheck: 'false' });
      const doAdd = () => {
        const v = add.value;
        if (v.trim() === '') return;
        if (hasSpelling(list(), id, v)) { showError(new Error('"' + v + '" is already a name or spelling of ' + id + '.')); return; }
        insertSpelling(list(), id, v); markDirty(); drawChips(); applyFilter();
        chips.querySelector('input').focus();
      };
      add.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); doAdd(); } });
      put(chips, ...cur.spellings.map(s => h('span', { class: 'chip' }, s,
        h('button', { text: '×', title: 'Remove spelling', onclick: () => remove({ kind: 'spelling', field: ref.uri, coordinate: ref.coordinate, list: ref.key, entry: id, spelling: s }, 'the spelling "' + s + '"') }))), add);
    };
    drawChips();
    const groupCell = h('td', { class: 'grp', text: p.group });
    const main = h('tr', { class: notes.length ? 'noted' : '', 'data-id': id },
      h('td', { class: 'id', title: id + ' (click to select: a new entry is added after the selected row)', onclick: () => select_(id) }, shortId(id), notes.length ? h('div', { class: 'badge', text: 'note', title: notes.map(n => n.text).join('\n') }) : null),
      h('td', {}, nameIn), h('td', {}, chips), groupCell,
      h('td', {}, h('button', { text: 'Details', onclick: () => toggle(id) }),
        h('button', { class: 'danger', text: 'Remove', onclick: () => remove({ kind: 'entry', field: ref.uri, coordinate: ref.coordinate, list: ref.key, entry: id }, 'the entry ' + id) })));
    main.addEventListener('focusin', () => select_(id));
    const rec = { main, detail: null, open: false, groupCell };
    rowsById.set(id, rec);
    return rec;
  };
  const toggle = id => {
    const rec = rowsById.get(id);
    rec.open = !rec.open;
    if (!rec.detail) {
      rec.detail = h('tr', { class: 'detail' }, h('td', { colspan: 5 }, detailBox(id, rec)));
      rec.main.after(rec.detail);
    }
    rec.detail.hidden = !rec.open;
  };
  const detailBox = (id, rec) => {
    const get = () => list()[id];
    const p = entryParts(get());
    const pin = S.pin && S.pin[id];
    const notes = noteMap(id);
    const defIn = h('textarea', { rows: 4, value: p.definition });
    defIn.addEventListener('input', () => { setEntryField(list(), id, 'definition', defIn.value); markDirty(); });
    const glossIn = h('textarea', { rows: 3, value: p.gloss });
    glossIn.addEventListener('input', () => { setEntryField(list(), id, 'gloss', glossIn.value); markDirty(); });
    const groupIn = h('input', { type: 'text', value: p.group });
    groupIn.addEventListener('input', () => { setEntryField(list(), id, 'group', groupIn.value); rec.groupCell.textContent = groupIn.value; markDirty(); });
    const extra = [];
    if (!Array.isArray(get())) {
      const ff = ((S.form && S.form.entry) || []).filter(f => !['label', 'spellings', 'definition', 'gloss', 'group'].includes(f.key));
      if (ff.length) extra.push(renderForm(ff, get(), (origList()[id] && isObj(origList()[id])) ? origList()[id] : null, { skipQuiet: new Set(['label', 'spellings', 'definition', 'gloss', 'group']) }));
    }
    return h('div', { class: 'detail' },
      notes.map(n => h('div', { class: 'warn' }, n.kind + ': ' + n.text)),
      h('div', { class: 'two' },
        h('div', {}, h('h4', { text: 'definition (spec)' }), defIn),
        h('div', {}, h('h4', {}, 'definition (ontology snapshot) ', pin && pin.deprecated ? h('span', { class: 'badge dep', text: 'deprecated' }) : null),
          h('div', { class: 'snap', text: pin ? ((pin.label ? pin.label + ': ' : '') + (pin.definition || '(no definition)')) : (id.startsWith('out:') ? '(the profile\'s own entry)' : '(not a term of the snapshot)') }),
          pin && pin.alt_labels && pin.alt_labels.length ? h('div', { class: 'help', text: 'alt labels: ' + pin.alt_labels.join(', ') }) : null)),
      h('div', { class: 'two', style: 'margin-top:8px' },
        h('div', {}, h('h4', { text: 'gloss' }), glossIn), h('div', {}, h('h4', { text: 'group' }), groupIn)),
      extra);
  };

  const l0 = list();
  for (const id of Object.keys(l0)) { const r = buildRow(id); tbody.append(r.main); }
  search.addEventListener('input', applyFilter);

  const addTerm = () => termDialog(ref, selected, afterStructural);
  const addOwn = () => ownDialog(ref, selected, afterStructural);
  wrap.append(
    h('div', { class: 'toolbar' }, search, count, h('button', { text: 'Add entry…', onclick: addTerm }), h('button', { text: 'Add own entry (out:)…', onclick: addOwn })),
    h('table', { class: 'grid' }, h('thead', {}, h('tr', {}, h('th', { text: 'id' }), h('th', { text: 'name' }), h('th', { text: 'spellings' }), h('th', { text: 'group' }), h('th'))), tbody));
  applyFilter();
  if (ref.markEntry && rowsById.has(ref.markEntry)) {
    const r = rowsById.get(ref.markEntry); r.main.classList.add('flag');
    setTimeout(() => r.main.scrollIntoView({ block: 'center' }), 0);
  }
  return wrap;
}

function addToList(ref, afterId, id, entry) {
  const hd = ref.holder();
  if (!isObj(hd[ref.key])) hd[ref.key] = {};
  if (own(hd[ref.key], id)) { showError(new Error('The entry ' + id + ' is in this list already.')); return false; }
  hd[ref.key] = listWithEntryAfter(hd[ref.key], afterId, id, entry);
  markDirty();
  return true;
}
function termDialog(ref, afterId, done) {
  const q = h('input', { type: 'text', placeholder: 'Search the ontology snapshot by id, label or alternative label', spellcheck: 'false' });
  const res = h('div');
  const info = h('div', { class: 'help' });
  let timer = null; let seq = 0;
  const search = async () => {
    const my = ++seq;
    try {
      const r = await api('GET', '/api/terms?q=' + encodeURIComponent(q.value) + '&limit=50');
      if (my !== seq) return;
      const cur = ref.holder()[ref.key] || {};
      info.textContent = r.total + ' terms match' + (r.terms.length < r.total ? ' (first ' + r.terms.length + ' shown)' : '');
      put(res, ...r.terms.map(t => h('div', { class: 'term' },
        h('div', { class: 'tt' }, h('code', { text: t.id }), ' ', h('b', { text: t.label || '' }), ' ', t.deprecated ? h('span', { class: 'badge dep', text: 'deprecated' }) : null,
          h('div', { class: 'df', text: (t.definition || '').slice(0, 200) })),
        h('button', { text: own(cur, t.id) ? 'In list' : 'Add', disabled: own(cur, t.id), onclick: () => { if (addToList(ref, afterId, t.id, newEntryFromTerm(t))) { closeModal(); done(); } } }))));
    } catch (e) { if (my === seq) showError(e); }
  };
  q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 250); });
  openModal('Add entry', [q, info, res], [{ text: 'Close', fn: c => c() }]);
  q.focus(); search();
}
function ownDialog(ref, afterId, done) {
  const id = h('input', { type: 'text', value: 'out:', spellcheck: 'false' });
  const name = h('input', { type: 'text', placeholder: 'name' });
  openModal('Add own entry', [h('label', { text: 'Id (starts with out:)' }), id, h('label', { text: 'Name' }), name],
    [{ text: 'Cancel', fn: c => c() }, { text: 'Add', cls: 'primary', fn: c => {
      const i = id.value.trim(); const n = name.value;
      if (!i.startsWith('out:') || i.length <= 4) { showError(new Error('The id of an own entry starts with "out:" and has a name after it.')); return; }
      if (!n.trim()) { showError(new Error('An entry needs a name.')); return; }
      if (addToList(ref, afterId, i, { label: n })) { c(); done(); } } }]);
  id.focus();
}

/* ---------- main area ---------- */

function actionsFor(n) {
  const mk = (text, fn, cls) => h('button', { text, class: cls, onclick: fn });
  if (n.t === 'param') return [mk('Copy as new field…', () => copyNode('field', n)), mk('Delete field', () => deleteNode('field', n), 'danger')];
  if (n.t === 'axis') return [mk('Copy as new coordinate…', () => copyNode('coordinate', n)), mk('Delete coordinate', () => deleteNode('coordinate', n), 'danger')];
  if (n.t === 'plan') return [mk('Remove plan field', () => deleteNode('plan_field', n), 'danger')];
  if (n.t === 'works') return [mk('Remove works', () => deleteNode('works', n), 'danger')];
  return [];
}
function titleOf(n) {
  switch (n.t) {
    case 'spec': return ['Top-level questions', ''];
    case 'plan': return ['Plan field ' + n.key, 'What a document settles once for all its values.'];
    case 'works': return ['Works', 'Other works a document presents beside itself.'];
    case 'group': return ['Group ' + n.name, 'Coordinates a document prints together.'];
    case 'param': return ['Field ' + n.uri, ''];
    case 'plist': return ['Field ' + n.uri + ' · ' + (n.list === 'beside' ? 'beside list' : 'list'), 'Fixed entries; edits are written with the next save.'];
    case 'axis': return ['Coordinate ' + n.name + ' of field ' + n.uri, ''];
  }
  return ['', ''];
}
function refFor(uri, coordinate, key, markEntry) {
  return {
    uri, coordinate, key, markEntry,
    holder: () => { const p = findParam(S.data, uri); return coordinate == null ? p : (p && p.axes && p.axes[coordinate]); },
    orig: () => { const p = findParam(S.orig, uri); return coordinate == null ? p : (p && p.axes && p.axes[coordinate]); },
  };
}
function renderMain() {
  ensureSel();
  const main = $('main');
  const n = S.sel;
  const obj = nodeObj(S.data, n);
  const [title, sub] = titleOf(n);
  const f = S.form || {};
  const parts = [h('div', { class: 'page-title' }, title, h('span', { class: 'acts' }, actionsFor(n))), sub ? h('div', { class: 'page-sub', text: sub }) : null];
  const coordNames = new Set();
  for (const p of S.data.parameters || []) for (const k of Object.keys(p.axes || {})) coordNames.add(k);
  const dl = h('datalist', { id: 'coordnames' }, [...coordNames].map(c => h('option', { value: c })));
  const origOf = () => nodeObj(S.orig, n);
  switch (n.t) {
    case 'spec':
      parts.push(renderForm(f.spec, obj, origOf(), { skip: new Set(['plan_fields', 'works', 'groups', 'parameters']), skipQuiet: new Set(['plan_fields', 'works', 'groups', 'parameters']) }));
      break;
    case 'plan': parts.push(renderForm(f.plan_field, obj, origOf())); break;
    case 'works': parts.push(renderForm(f.works, obj, origOf())); break;
    case 'group': parts.push(dl, renderForm(f.group, obj, origOf(), { datalist: 'coordnames' })); break;
    case 'param':
      parts.push(renderForm(f.parameter, obj, origOf(), {
        skip: new Set(['axes', 'vocabulary', 'beside']), skipQuiet: new Set(['axes', 'vocabulary', 'beside']),
        onUri: v => { S.sel = { t: 'param', uri: v }; S.expanded.add(v); renderTree(); renderTitleOnly(); },
      }));
      break;
    case 'plist':
      parts.push(entriesTable(refFor(n.uri, null, n.list, S.flag && S.flag.entry)));
      break;
    case 'axis': {
      const kinds = kindOf(obj);
      parts.push(h('div', { class: 'section', text: 'What the coordinate reads' }));
      if (kinds.length !== 1) parts.push(h('div', { class: 'warn', text: kinds.length ? 'More than one of vocabulary, type, enum, dynamic is set; the loader wants exactly one.' : 'None of vocabulary, type, enum, dynamic is set; the loader wants exactly one.' }));
      for (const k of kinds) {
        if (k === 'vocabulary') parts.push(h('div', {}, h('span', { class: 'kind', text: 'a list of entries' }), ' ', listCount(obj.vocabulary) + ' entries'), entriesTable(refFor(n.uri, n.name, 'vocabulary', S.flag && S.flag.entry)));
        else if (k === 'type') {
          const sel = h('select', {}, h('option', { value: 'int', text: 'int' }), h('option', { value: 'text', text: 'text' }));
          if (!['int', 'text'].includes(obj.type)) sel.append(h('option', { value: obj.type, text: String(obj.type) }));
          sel.value = obj.type;
          sel.addEventListener('change', () => { obj.type = sel.value; markDirty(); });
          parts.push(h('div', { class: 'field', 'data-key': 'type' }, h('span', { class: 'kind', text: 'a free value' }), ' ', h('label', { text: 'type' }), sel));
        } else if (k === 'enum') parts.push(h('div', { class: 'field', 'data-key': 'enum' }, h('span', { class: 'kind', text: 'a list of strings' }), stringsEditor(obj, 'enum', { keep: true })));
        else if (k === 'dynamic') parts.push(h('div', { class: 'field', 'data-key': 'dynamic' }, h('span', { class: 'kind', text: 'closed per document' }), ' The profile closes the list of this coordinate for each document.'));
      }
      if (isObj(obj.beside)) parts.push(h('div', { class: 'section', text: 'Beside list' }), entriesTable(refFor(n.uri, n.name, 'beside', S.flag && S.flag.entry)));
      parts.push(h('div', { class: 'section', text: 'The other keys of the coordinate' }));
      parts.push(renderForm(f.axis, obj, origOf(), { skip: new Set(['vocabulary', 'type', 'enum', 'dynamic', 'beside']), skipQuiet: new Set(['vocabulary', 'type', 'enum', 'dynamic', 'beside']) }));
      break;
    }
  }
  const top = main.scrollTop;
  put(main, ...parts);
  main.scrollTop = top;
  if (S.flag && S.flag.field) {
    const el = main.querySelector('.field[data-key="' + S.flag.field.replace(/"/g, '\\"') + '"]');
    if (el) { el.classList.add('flag'); el.scrollIntoView({ block: 'center' }); }
  }
  if (S.flag && S.flag.field == null && !S.flag.entry) main.scrollTop = 0;
}
function renderTitleOnly() { const t = $('main').querySelector('.page-title'); if (t) t.firstChild.textContent = titleOf(S.sel)[0]; }

/* ---------- structural actions ---------- */

async function run(fn) {
  if (S.busy) return;
  S.busy = true; renderHeader();
  try { await fn(); } catch (e) { showError(e); }
  S.busy = false; renderHeader();
}
function commitFocus() { const a = document.activeElement; if (a && a !== document.body && a.blur) a.blur(); }

async function copyNode(kind, n) {
  const key = await askText(kind === 'field' ? 'Copy as new field' : 'Copy as new coordinate', 'New key', '');
  if (!key) return;
  await run(async () => {
    const r = await api('POST', '/api/spec/copy', { data: S.data, kind, field: n.uri, coordinate: kind === 'coordinate' ? n.name : null, key });
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data; markDirty();
    S.sel = kind === 'field' ? { t: 'param', uri: key } : { t: 'axis', uri: n.uri, name: key };
    S.expanded.add(n.uri); S.expanded.add(key);
    ensureSel(); renderTree(); renderMain();
    showInfo('Copied. A copied field has no example: write its own before saving.');
  });
}
async function deleteNode(kind, n) {
  const what = { field: 'field ' + n.uri, coordinate: 'coordinate ' + n.name + ' of ' + n.uri, plan_field: 'plan field ' + n.key, works: 'the works block' }[kind];
  if (!await askConfirm('Delete', 'Delete ' + what + '?\nIt is removed here and written with the next confirmed save.', 'Delete')) return;
  const body = { kind };
  if (kind === 'field') body.field = n.uri;
  if (kind === 'coordinate') { body.field = n.uri; body.coordinate = n.name; }
  if (kind === 'plan_field') body.key = n.key;
  await run(async () => {
    const r = await api('POST', '/api/spec/remove', Object.assign({ data: S.data }, body));
    if (!r.ok) throw new Error(errText(r.error));
    S.data = r.data; markDirty();
    S.sel = kind === 'coordinate' ? { t: 'param', uri: n.uri } : { t: 'spec' };
    ensureSel(); renderTree(); renderMain();
    showInfo('Removed ' + what + ' here. It is written with the next confirmed save.');
  });
}
function addPlanField(k) {
  if (!isObj(S.data.plan_fields)) S.data.plan_fields = {};
  S.data.plan_fields[k] = { name: '', means: '' };
  markDirty(); select({ t: 'plan', key: k });
}
function addWorks() {
  S.data.works = { name: '', means: '', fields: {} };
  markDirty(); select({ t: 'works' });
}

/* ---------- check, save, generate ---------- */

function blockedByJson() {
  if (document.querySelector('.field.bad')) { showError(new Error('A JSON field has a parse error. Fix it first; nothing was sent.')); return true; }
  return false;
}
async function doCheck() {
  commitFocus();
  if (blockedByJson()) return;
  await run(async () => {
    clearBar();
    const r = await api('POST', '/api/spec/check', { data: S.data });
    S.result = { source: 'check', r }; S.stale = false; S.generate = null;
    if (r.notes) S.notes = r.notes;
    S.panelOpen = true; renderPanel(); renderMain();
  });
}
async function doSave(confirm) {
  commitFocus();
  if (blockedByJson()) return;
  await run(async () => {
    clearBar();
    const r = await api('POST', '/api/spec/save', { data: S.data, base: S.base, confirm: !!confirm });
    S.result = { source: 'save', r }; S.stale = false; S.generate = null;
    if (r.notes) S.notes = r.notes;
    if (r.saved) {
      S.base = r.base; S.orig = clone(S.data); S.dirty = false;
      try { S.state = await api('GET', '/api/state'); } catch (e) { showError(e); }
      renderHeader();
    }
    S.panelOpen = true; renderPanel(); renderMain();
  });
}
async function doGenerate() {
  await run(async () => {
    S.generate = await api('POST', '/api/generate', {});
    renderPanel();
    try { S.state = await api('GET', '/api/state'); renderHeader(); } catch (e) { showError(e); }
  });
}

function goToError(err) {
  const loc = locate(err.where, S.data);
  select(loc.node, { field: loc.field, entry: loc.entry });
}

function renderPanelStale() {
  const s = document.querySelector('#panel .stale');
  if (s) s.hidden = !S.stale;
}
function renderPanel() {
  const p = $('panel');
  p.className = S.panelOpen ? '' : 'collapsed';
  const R = S.result;
  const head = h('div', { class: 'phead', onclick: () => { S.panelOpen = !S.panelOpen; renderPanel(); } },
    h('span', { class: 'caret', text: S.panelOpen ? '▾' : '▸' }),
    h('b', { text: R ? (R.source === 'save' ? 'Result of the last save' : 'Result of the last check') : 'Check result' }),
    R ? summaryBadge(R) : h('span', { class: 'help', text: 'Press Check (Ctrl+Enter) to see what an edit costs.' }));
  if (!S.panelOpen || !R) { put(p, head); return; }
  const r = R.r;
  const body = h('div', { class: 'pbody' }, h('div', { class: 'warn stale', hidden: !S.stale, text: 'The data was edited after this result.' }));

  if (R.source === 'save') {
    if (r.saved) {
      body.append(h('div', { class: 'box ok' }, 'Saved. ',
        h('button', { text: 'Regenerate schema and docs', onclick: doGenerate })));
      if (S.generate) body.append(h('div', { class: 'box ' + (S.generate.ok ? 'ok' : 'bad') },
        S.generate.ok ? 'Regenerated.' : 'Regeneration failed.', ' Changed files: ', (S.generate.changed || []).length ? (S.generate.changed || []).map(f => h('code', { text: f + ' ' })) : 'none',
        S.generate.output ? h('pre', { class: 'out', text: S.generate.output }) : null));
    } else if (r.reason === 'moved') {
      body.append(h('div', { class: 'box bad' }, h('div', { text: r.message || 'The file on disk is not the one this page loaded.' }),
        h('button', { text: 'Reload from disk', onclick: () => reload() })));
      put(p, head, body); return;
    } else if (r.reason === 'confirm') {
      body.append(h('div', { class: 'box warnbox' }, h('b', { text: 'This edit removes something. Nothing is written yet.' }),
        removedList(r), h('div', {}, 'What it costs: see the changed questions below.'),
        h('button', { class: 'danger', text: 'Remove and save', onclick: () => doSave(true) })));
    } else if (r.reason === 'check') {
      body.append(h('div', { class: 'box bad', text: 'Not saved: the loader refused the spec.' }));
    }
  }
  if (r.error) {
    body.append(h('div', { class: 'box bad' }, h('b', { text: 'The loader refuses the spec: ' }), r.error.message || '', ' ',
      r.error.where ? h('button', { class: 'link', text: r.error.where, onclick: () => goToError(r.error) }) : null));
  } else if (R.source === 'check') {
    body.append(h('div', { class: 'box ok', text: 'The loader accepts the spec.' }));
  }
  if (!(R.source === 'save' && r.reason === 'confirm') && r.removed && r.removed.length) body.append(h('div', { class: 'box warnbox' }, h('b', { text: 'Removed by this edit:' }), removedList(r)));
  const ch = r.changes || [];
  body.append(h('details', { open: ch.length > 0 }, h('summary', { text: 'Changed questions (' + ch.length + ')' }),
    r.documents_note ? h('div', { class: 'help', text: r.documents_note }) : null,
    ch.length ? null : h('div', { class: 'help', text: r.error ? 'Not said while the loader refuses the spec.' : 'No question of the run changes.' }),
    ch.map(c => h('div', { class: 'chg' },
      h('span', { class: 'badge ' + c.state, text: c.state }), ' ', h('code', { text: c.key }), ' ', h('span', { class: 'help', text: c.effect }),
      h('div', { text: c.text }),
      c.documents ? h('details', {}, h('summary', { text: c.documents.length + ' documents' }), h('div', { class: 'docs' }, c.documents.map(d => h('div', { text: d })))) : null))));
  const ln = r.lines || {};
  const diff = r.diff || '';
  const pre = h('pre', { class: 'diff' });
  if (diff) for (const line of diff.split('\n')) pre.append(h('span', { class: diffClass(line), text: line === '' ? ' ' : line }));
  body.append(h('details', { open: !!diff }, h('summary', {}, 'Diff ', h('span', { class: 'badge new', text: '+' + (ln.added || 0) + ' lines' }), ' ', h('span', { class: 'badge gone', text: '-' + (ln.removed || 0) + ' lines' })),
    diff ? pre : h('div', { class: 'help', text: 'The file does not change.' })));
  put(p, head, body);
}
function removedList(r) { return h('ul', {}, (r.removed || []).map(x => h('li', { text: x }))); }
function summaryBadge(R) {
  const r = R.r;
  if (R.source === 'save' && r.saved) return h('span', { class: 'badge ok', text: 'saved' });
  if (R.source === 'save') return h('span', { class: 'badge dep', text: 'not saved: ' + (r.reason || '') });
  return r.ok ? h('span', { class: 'badge ok', text: 'ok' }) : h('span', { class: 'badge dep', text: 'refused' });
}

/* ---------- load ---------- */

async function reload() {
  if (S.dirty && !await askConfirm('Reload from disk', 'There are unsaved edits. Reloading discards them.', 'Discard and reload')) return;
  await run(loadAll);
}
async function loadAll() {
  clearBar();
  const [state, spec] = await Promise.all([api('GET', '/api/state'), api('GET', '/api/spec')]);
  S.state = state; S.data = spec.data; S.orig = clone(spec.data); S.base = spec.base;
  S.form = spec.form || {}; S.pin = spec.pin || {}; S.notes = spec.notes || [];
  S.dirty = false; S.result = null; S.stale = false; S.generate = null; S.flag = null;
  ensureSel();
  renderHeader(); renderTree(); renderMain(); renderPanel();
}

window.addEventListener('beforeunload', ev => { if (S.dirty) { ev.preventDefault(); ev.returnValue = ''; } });
window.addEventListener('keydown', ev => {
  if (!(ev.ctrlKey || ev.metaKey)) return;
  if (ev.key === 's' || ev.key === 'S') { ev.preventDefault(); if (!S.busy) doSave(false); }
  else if (ev.key === 'Enter') { ev.preventDefault(); if (!S.busy) doCheck(); }
});

renderHeader(); renderPanel();
run(loadAll);

})();
