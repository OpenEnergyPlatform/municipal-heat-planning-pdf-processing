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
    h('span', { class: 'tabs' }, (st.tabs || ['spec', 'prompts']).map(t => h('button', { class: t === S.tab ? 'on' : '',
      text: t.charAt(0).toUpperCase() + t.slice(1) + ((t === 'spec' ? S.dirty : t === 'flow' ? flowDirty() : t === 'sources' ? sourcesDirty()
        : t === 'graph' ? graphDirty() : promptsDirty()) ? ' •' : ''), onclick: () => setTab(t) }))),
    (S.tab === 'spec' || S.tab === 'prompts') ? h('button', { text: 'Rules', title: 'The rules of this tab', onclick: () => openRules(S.tab) }) : null,
    h('span', { class: 'spacer' }),
    anyDirty() ? h('span', { class: 'dirty', text: 'Unsaved edits' }) : h('span', { class: 'clean', text: 'No unsaved edits' }),
    S.tab === 'spec' ? h('button', { text: 'Reload from disk', disabled: S.busy, onclick: () => reload() }) : null,
    S.tab === 'spec' ? h('button', { text: 'Check', disabled: S.busy, title: 'Ctrl+Enter', onclick: () => doCheck() }) : null,
    S.tab === 'spec' ? h('button', { class: 'primary', text: 'Save', disabled: S.busy, title: 'Ctrl+S', onclick: () => doSave(false) }) : null);
  document.title = (anyDirty() ? '* ' : '') + 'docpipe edit ' + (st.profile || '');
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

/* entry_of: {"<coordinate>": "<entry key>"} as two selects; any other shape is edited as JSON */
function vocabOf(c) {
  const p = (S.data.parameters || []).find(x => isObj(x.axes) && own(x.axes, c));
  const ax = p && p.axes[c];
  return isObj(ax) && isObj(ax.vocabulary) ? ax.vocabulary : null;
}
function widgetEntryOf(f, obj, wrap) {
  const cur = obj[f.key];
  if (own(obj, f.key)) {
    const ks = isObj(cur) ? Object.keys(cur) : [];
    if (ks.length !== 1 || typeof cur[ks[0]] !== 'string') return widgetJson(f, obj, wrap);
  }
  const coords = [];
  for (const g of Object.values(isObj(S.data.groups) ? S.data.groups : {})) {
    for (const c of (isObj(g) && Array.isArray(g.pair) ? g.pair : [])) if (!coords.includes(c) && vocabOf(c)) coords.push(c);
  }
  let coord = own(obj, f.key) ? Object.keys(cur)[0] : '';
  if (coord && !coords.includes(coord)) coords.push(coord);
  const cSel = h('select', {}, h('option', { value: '', text: '(none)' }), coords.map(c => h('option', { value: c, text: c })));
  const eSel = h('select');
  cSel.value = coord;
  const drawEntries = () => {
    const voc = coord ? vocabOf(coord) || {} : {};
    const keys = Object.keys(voc);
    const now = coord && own(obj, f.key) ? obj[f.key][coord] : '';
    if (now && !keys.includes(now)) keys.push(now);
    put(eSel, h('option', { value: '', text: coord ? '(choose)' : '' }), keys.map(k => {
      const nm = own(voc, k) ? entryParts(voc[k]).name : '';
      return h('option', { value: k, text: nm ? nm + ' (' + k + ')' : k });
    }));
    eSel.value = now || ''; eSel.disabled = !coord;
  };
  cSel.addEventListener('change', () => {
    coord = cSel.value;
    if (!coord) delete obj[f.key];
    else obj[f.key] = { [coord]: Object.keys(vocabOf(coord) || {})[0] || '' };
    drawEntries(); markDirty();
  });
  eSel.addEventListener('change', () => { if (coord) { obj[f.key] = { [coord]: eSel.value }; markDirty(); } });
  drawEntries();
  return h('div', { class: 'row2' }, cSel, eSel);
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
    case 'entry_of': ctl = widgetEntryOf(f, obj, wrap); break;
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
    if (f.only && !(S.sel.t === 'plan' && f.only.includes(S.sel.key))) continue;
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

/* ---------- prompts tab ---------- */

/* State. Unsaved text is kept per prompt id in P.eds (and per module in P.phs) for as long as the page is open: opening
   another prompt never loses an edit, and the list marks every prompt whose text differs from what was loaded. */
const P = {
  loaded: false, loading: false, list: null, sel: null, filter: '',
  eds: new Map(), phs: new Map(), trace: null,
  req: null, tryRes: null, rui: null, pvSeq: 0, rqSeq: 0, pvTimer: null, rqTimer: null, sig: '',
};

/* like api() for a POST, but an answer that carries "ok" or "saved" is a report even when it holds an error sentence */
async function apiR(url, body) {
  let res;
  try {
    res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Docpipe-Edit': '1' }, body: JSON.stringify(body == null ? {} : body) });
  } catch (e) { throw new Error('The server cannot be reached: ' + e.message); }
  let j;
  try { j = await res.json(); } catch (e) { throw new Error('The server answered ' + res.status + ' without JSON.'); }
  if (isObj(j) && ('ok' in j || 'saved' in j)) return j;
  if (isObj(j) && typeof j.error === 'string') throw new Error(j.error);
  if (!res.ok) throw new Error('The server answered ' + res.status + '.');
  return j;
}

/* the one function that builds the text sent back for a prompt */
// The run reads a marker only on a line of its own. So the text before a
// marker ends its line, and a marker ends its line before its text: what is
// typed at the end of one box must not run into the marker of the next.
const lineEnded = t => (t === '' || t.endsWith('\n')) ? t : t + '\n';
function rawOf(E) {
  if (E.single) return E.cut.front + E.body;
  const parts = E.cut.parts;
  let out = E.cut.front + (parts.length ? lineEnded(E.cut.common) : E.cut.common);
  parts.forEach((p, i) => {
    out += (p.text === '' ? p.mark : lineEnded(p.mark))
      + (i < parts.length - 1 ? lineEnded(p.text) : p.text);
  });
  return out;
}
const edDirty = E => rawOf(E) !== E.detail.raw;
const phDirty = X => JSON.stringify(X.table) !== X.origJson;
function isDirty(X) { return X.kind === 'prompt' ? edDirty(X) : phDirty(X); }
function stampOf(X) { return X.kind === 'prompt' ? rawOf(X) : JSON.stringify(X.table); }
function promptsDirty() {
  for (const E of P.eds.values()) if (edDirty(E)) return true;
  for (const X of P.phs.values()) if (phDirty(X)) return true;
  return false;
}
function anyDirty() { return S.dirty || promptsDirty() || flowDirty() || sourcesDirty() || graphDirty() || rulesDirty(); }
function dirtySig() {
  const a = [];
  for (const [id, E] of P.eds) if (edDirty(E)) a.push('p:' + id);
  for (const [m, X] of P.phs) if (phDirty(X)) a.push('s:' + m);
  return a.join('|');
}
function editsMap() {
  const out = {};
  for (const [id, E] of P.eds) if (edDirty(E)) out[id] = rawOf(E);
  return out;
}
function currentX() {
  if (!P.sel) return null;
  return P.sel.t === 'prompt' ? P.eds.get(P.sel.id) || null : P.phs.get(P.sel.module) || null;
}
const isShown = X => { const c = currentX(); return !!c && c === X; };

/* settings in the front matter: only the value after the key is replaced, every other character stays */
const settingRe = key => new RegExp('^(' + key + ':)([^\\r\\n]*)', 'm');
function settingRest(front, key) { const m = settingRe(key).exec(front); return m ? m[2] : null; }
function withSetting(front, key, lead, v) { return front.replace(settingRe(key), (all, a) => a + lead + v); }

function bodyFromCut(cut) { return cut.common + (cut.parts || []).map(p => p.mark + p.text).join(''); }
function makeEd(d) {
  const cut = clone(d.cut);
  cut.parts = cut.parts || [];
  const single = !!d.composed || !cut.parts.length;
  return { kind: 'prompt', id: d.id, detail: d, cut, single, body: bodyFromCut(cut), rep: null, review: null, busy: false, ui: null };
}
function makePh(d) {
  return { kind: 'phrases', module: d.module, detail: d, table: clone(d.table || {}), origJson: JSON.stringify(d.table || {}),
    rep: null, review: null, busy: false, ui: null, shown: {} };
}

const mb = b => (b / 1e6).toFixed(1) + ' MB';
const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');

/* ---------- load and list ---------- */

async function loadPrompts() {
  if (P.loading) return;
  P.loading = true;
  put($('pl-items'), h('div', { class: 'help pr-pad', text: 'Loading…' }));
  try {
    P.list = await api('GET', '/api/prompts');
    P.loaded = true;
    const tr = P.list.traces || [];
    if (!P.trace || !tr.some(t => t.name === P.trace)) P.trace = tr.length ? tr[0].name : null;
  } catch (e) {
    put($('pl-items'), h('div', { class: 'box bad', text: e.message }));
    P.loading = false;
    return;
  }
  P.loading = false;
  renderList(); renderEditorColumn(); renderRight();
}

function stageOrder(a, b) { return (a === 'extraction' ? 0 : 1) - (b === 'extraction' ? 0 : 1) || a.localeCompare(b); }

function renderList() {
  const box = $('pl-items');
  if (!P.list) return;
  const top = $('pl-left').scrollTop;
  const words = P.filter.toLowerCase().split(/\s+/).filter(Boolean);
  const match = (...t) => { const hay = t.join('\n').toLowerCase(); return words.every(w => hay.includes(w)); };
  const els = [];
  const item = (selected, name, sub, badges, onclick) => h('button', { class: 'node' + (selected ? ' sel' : ''), onclick },
    h('span', { class: 'caret' }), h('span', { class: 'name', text: name, title: name + (sub ? ' · ' + sub : '') }), sub ? h('span', { class: 'sub', text: sub }) : null, badges);
  const prompts = (P.list.prompts || []).filter(p => match(p.id, p.owner || ''));
  const stages = [...new Set(prompts.map(p => p.stage))].sort(stageOrder);
  els.push(h('div', { class: 'tree-h', text: 'Prompts (' + prompts.length + ')' }));
  if (!prompts.length) els.push(h('div', { class: 'help pr-pad', text: (P.list.prompts || []).length ? 'No prompt matches the filter.' : 'This profile has no prompt files.' }));
  for (const st of stages) {
    els.push(h('div', { class: 'tree-h', text: st }));
    for (const p of prompts.filter(x => x.stage === st)) {
      const E = P.eds.get(p.id);
      els.push(item(P.sel && P.sel.t === 'prompt' && P.sel.id === p.id, p.name, p.own ? '' : 'inherited from ' + p.owner,
        [(p.kinds || []).length ? h('span', { class: 'badge ok', text: 'requests', title: 'Recorded requests can be shown for this prompt' }) : null,
          E && edDirty(E) ? h('span', { class: 'badge changed', text: 'unsaved' }) : null],
        () => selectPrompt(p.id)));
    }
  }
  els.push(h('div', { class: 'tree-h', text: 'Sentences' }));
  for (const m of (P.list.modules || []).filter(m => match(m, 'sentences'))) {
    const X = P.phs.get(m);
    els.push(item(P.sel && P.sel.t === 'phrases' && P.sel.module === m, m, '', X && phDirty(X) ? h('span', { class: 'badge changed', text: 'unsaved' }) : null, () => selectModule(m)));
  }
  put(box, ...els);
  $('pl-left').scrollTop = top;
}

/* called after every edit: the list, the tabs and the header say what is unsaved, only when that changed */
function touched() {
  const sig = dirtySig();
  if (sig === P.sig) return;
  P.sig = sig;
  renderList(); renderHeader();
}

async function selectPrompt(id) {
  P.sel = { t: 'prompt', id };
  resetRequests();
  renderList();
  const main = $('pl-main');
  if (!P.eds.has(id)) {
    put(main, h('div', { class: 'help', text: 'Loading ' + id + '…' }));
    renderRight();
    try {
      const d = await api('GET', '/api/prompt?id=' + encodeURIComponent(id));
      if (!P.eds.has(id)) P.eds.set(id, makeEd(d));
    } catch (e) {
      if (P.sel && P.sel.t === 'prompt' && P.sel.id === id) put(main, h('div', { class: 'box bad', text: e.message }));
      return;
    }
  }
  if (!(P.sel && P.sel.t === 'prompt' && P.sel.id === id)) return;
  resetRequests();
  renderEditorColumn(); renderRight();
  startRequests();
}
async function selectModule(m) {
  P.sel = { t: 'phrases', module: m };
  resetRequests();
  renderList();
  const main = $('pl-main');
  if (!P.phs.has(m)) {
    put(main, h('div', { class: 'help', text: 'Loading the sentences of ' + m + '…' }));
    renderRight();
    try {
      const d = await api('GET', '/api/phrases?module=' + encodeURIComponent(m));
      if (!P.phs.has(m)) P.phs.set(m, makePh(d));
    } catch (e) {
      if (P.sel && P.sel.t === 'phrases' && P.sel.module === m) put(main, h('div', { class: 'box bad', text: e.message }));
      return;
    }
  }
  if (!(P.sel && P.sel.t === 'phrases' && P.sel.module === m)) return;
  renderEditorColumn(); renderRight();
}

function renderEditorColumn() {
  const main = $('pl-main');
  const top = main.scrollTop;
  if (!P.list) { put(main); return; }
  if (!P.sel) { put(main, h('div', { class: 'help', text: 'Pick a prompt or the sentences of a module on the left.' })); return; }
  const X = currentX();
  if (!X) { put(main, h('div', { class: 'help', text: 'Loading…' })); return; }
  if (X.kind === 'prompt') renderPromptEditor(X); else renderPhrasesEditor(X);
  main.scrollTop = top;
}

/* ---------- the editor of a prompt ---------- */

function promptArea(value, onInput, readonly) {
  const ta = h('textarea', { class: 'prompt', spellcheck: 'false', value, readonly: readonly ? true : null });
  ta.rows = Math.max(3, Math.min(30, String(value).split('\n').length + 1));
  if (!readonly) ta.addEventListener('input', () => { onInput(ta.value); });
  return ta;
}
function syncButtons(X) {
  const u = X.ui;
  if (!u) return;
  u.check.disabled = X.busy; u.save.disabled = X.busy; u.discard.disabled = X.busy || !isDirty(X);
  u.dirty.hidden = !isDirty(X);
  if (u.stale) u.stale.hidden = !(X.rep && X.rep.stamp !== stampOf(X));
}
function edited(X) {
  syncButtons(X);
  touched();
  if (X.kind === 'prompt') schedulePreview();
}

function renderPromptEditor(E) {
  const d = E.detail;
  const ui = E.ui = {};
  ui.dirty = h('span', { class: 'badge changed', text: 'unsaved changes', hidden: !edDirty(E) });
  const kids = [
    h('div', { class: 'page-title' }, d.id, d.own ? h('span', { class: 'badge ok', text: 'own file' }) : h('span', { class: 'badge', text: 'inherited from ' + d.owner }), ui.dirty),
    h('div', { class: 'page-sub' }, 'File: ', h('code', { text: d.path || '' })),
  ];
  if (!d.own) kids.push(h('div', { class: 'warn', text: 'This profile runs with the file of ' + d.owner + '. Saving writes a file of its own: ' + (d.target || '') + '.' }));

  const keys = ['temperature', 'max_tokens'].filter(k => settingRest(E.cut.front, k) !== null);
  if (keys.length) {
    kids.push(h('div', { class: 'section', text: 'Settings' }), h('div', { class: 'row2' }, keys.map(k => {
      const rest = settingRest(E.cut.front, k);
      const lead = /^[ \t]*/.exec(rest)[0];
      const inp = h('input', { type: 'text', value: rest.slice(lead.length), spellcheck: 'false' });
      inp.addEventListener('input', () => { E.cut.front = withSetting(E.cut.front, k, lead, inp.value); edited(E); });
      return h('label', { class: 'pr-set' }, h('code', { text: k }), inp);
    })));
  }

  if (E.single) {
    kids.push(h('div', { class: 'section', text: d.composed ? 'The file, after its settings' : 'What every request is told' }),
      promptArea(E.body, v => { E.body = v; edited(E); }));
    if (d.composed) {
      kids.push(h('div', { class: 'help', text: 'This file is put together with a template of the core. The text that is sent:' }),
        promptArea(d.sent == null ? '' : d.sent, null, true),
        h('div', { class: 'help', text: 'This is the text sent with the file on disk; it does not change while you edit.' }));
    }
  } else {
    kids.push(h('div', { class: 'section', text: 'What every request is told' }), promptArea(E.cut.common, v => { E.cut.common = v; edited(E); }));
    for (const p of E.cut.parts) {
      const follow = p.kind === 'follow-up';
      kids.push(h('div', { class: 'field pr-part' },
        h('label', {}, follow ? 'The words of a follow-up message that carries: ' : 'Only told to a request whose message carries: ', h('code', { text: (p.keys || []).join(', ') })),
        h('div', { class: 'help' }, 'Opened by the line ', h('code', { text: String(p.mark).replace(/\n+$/, '') }), ' (not editable)'),
        promptArea(p.text, v => { p.text = v; edited(E); })));
    }
  }
  if ((d.placeholders || []).length) kids.push(h('div', { class: 'help' }, 'Places the code fills: ', d.placeholders.map(x => h('code', { text: '{{' + x + '}} ' }))));

  ui.check = h('button', { text: 'Check', title: 'Ctrl+Enter', onclick: () => actCheck(E) });
  ui.save = h('button', { class: 'primary', text: 'Save', title: 'Ctrl+S', onclick: () => actSave(E, false) });
  ui.discard = h('button', { text: 'Discard changes', onclick: () => actDiscard(E) });
  ui.report = h('div', { class: 'pr-report' });
  kids.push(h('div', { class: 'toolbar pr-actions' }, ui.check, ui.save, ui.discard), ui.report);
  put($('pl-main'), ...kids);
  syncButtons(E);
  renderReport(E);
}

/* ---------- check, save, discard, review (prompts and sentences) ---------- */

const urlOf = X => X.kind === 'prompt' ? '/api/prompt/' : '/api/phrases/';
const bodyOf = X => X.kind === 'prompt' ? { id: X.id, raw: rawOf(X) } : { module: X.module, table: X.table };

async function actCheck(X) {
  if (X.busy) return;
  const stamp = stampOf(X);
  X.busy = true; syncButtons(X);
  try { X.rep = { source: 'check', r: await apiR(urlOf(X) + 'check', bodyOf(X)), stamp }; }
  catch (e) { X.rep = { source: 'check', error: e.message, stamp }; }
  X.busy = false; syncButtons(X); renderReport(X);
}
async function actSave(X, confirm) {
  if (X.busy) return;
  const stamp = stampOf(X);
  const body = Object.assign(bodyOf(X), { base: X.detail.sha256 == null ? null : X.detail.sha256 });
  if (X.kind === 'phrases') body.confirm = !!confirm;
  X.busy = true; X.review = null; syncButtons(X);
  let saved = false;
  try {
    const r = await apiR(urlOf(X) + 'save', body);
    X.rep = { source: 'save', r, stamp };
    if (r.saved) { saved = true; await afterSaved(X, stamp); }
  } catch (e) { X.rep = { source: 'save', error: e.message, stamp }; }
  X.busy = false;
  if (saved && isShown(X)) renderEditorColumn(); else { syncButtons(X); renderReport(X); }
  touched();
  if (saved) runReview(X);
}
/* the file on disk is the new base; the text in the editor is kept when it was changed again meanwhile */
async function afterSaved(X, stamp) {
  try {
    if (X.kind === 'prompt') {
      adoptPrompt(X, await api('GET', '/api/prompt?id=' + encodeURIComponent(X.id)), stamp);
      const l = await api('GET', '/api/prompts');
      if (P.list && Array.isArray(l.prompts)) P.list.prompts = l.prompts;
    } else {
      adoptPhrases(X, await api('GET', '/api/phrases?module=' + encodeURIComponent(X.module)), stamp);
    }
  } catch (e) { showError(e); }
  renderList();
}
/* stamp null: take the text of the file whatever the editor holds */
function adoptPrompt(E, d, stamp) {
  const same = stamp === null || stampOf(E) === stamp;
  E.detail = d;
  if (same) {
    E.cut = clone(d.cut); E.cut.parts = E.cut.parts || [];
    E.single = !!d.composed || !E.cut.parts.length; E.body = bodyFromCut(E.cut);
  }
}
function adoptPhrases(X, d, stamp) {
  const same = stamp === null || stampOf(X) === stamp;
  X.detail = d; X.origJson = JSON.stringify(d.table || {});
  if (same) X.table = clone(d.table || {});
}
async function actDiscard(X) {
  const what = X.kind === 'prompt' ? X.id : 'the sentences of ' + X.module;
  if (!await askConfirm('Discard changes', 'Discard the changes to ' + what + '?', 'Discard')) return;
  if (X.kind === 'prompt') { X.cut = clone(X.detail.cut); X.cut.parts = X.cut.parts || []; X.body = bodyFromCut(X.cut); }
  else X.table = clone(X.detail.table || {});
  X.rep = null; X.review = null;
  if (isShown(X)) renderEditorColumn();
  touched();
  if (X.kind === 'prompt') schedulePreview();
}
async function reloadFromDisk(X) {
  if (isDirty(X) && !await askConfirm('Reload from disk', 'The file changed on disk. Reloading drops the changes in the editor.', 'Drop my changes and reload')) return;
  try {
    if (X.kind === 'prompt') adoptPrompt(X, await api('GET', '/api/prompt?id=' + encodeURIComponent(X.id)), null);
    else adoptPhrases(X, await api('GET', '/api/phrases?module=' + encodeURIComponent(X.module)), null);
  } catch (e) { showError(e); return; }
  X.rep = null; X.review = null;
  if (isShown(X)) renderEditorColumn();
  touched();
  if (X.kind === 'prompt') schedulePreview();
}
async function runReview(X) {
  X.review = { running: true }; renderReport(X);
  try { X.review = { res: await apiR('/api/review', {}) }; }
  catch (e) { X.review = { err: e.message }; }
  renderReport(X);
}

function diffPre(diff) {
  const pre = h('pre', { class: 'diff' });
  for (const line of String(diff || '').split('\n')) pre.append(h('span', { class: diffClass(line), text: line === '' ? ' ' : line }));
  return pre;
}
function renderReport(X) {
  const ui = X.ui;
  if (!ui) return;
  const kids = [];
  ui.stale = h('div', { class: 'warn', text: 'The text was edited after this result.', hidden: !(X.rep && X.rep.stamp !== stampOf(X)) });
  if (X.rep) kids.push(ui.stale, ...repNodes(X));
  if (X.review) kids.push(...reviewNodes(X.review));
  put(ui.report, ...kids);
}
function repNodes(X) {
  const R = X.rep;
  if (R.error) return [h('div', { class: 'box bad', text: R.error })];
  const r = R.r || {};
  const out = [];
  if (R.source === 'save') {
    if (r.saved) out.push(h('div', { class: 'box ok', text: 'Saved ' + (r.path || '') + '.' }));
    else if (r.reason === 'moved') {
      return [h('div', { class: 'box bad' }, h('div', { text: 'The file a run loads changed on disk since this page loaded it. Nothing was written.' }),
        h('button', { text: 'Reload from disk', onclick: () => reloadFromDisk(X) }))];
    } else if (r.reason === 'same') out.push(h('div', { class: 'box', text: 'Nothing changed. Nothing was written.' }));
    else if (r.reason === 'confirm') {
      out.push(h('div', { class: 'box warnbox' }, h('b', { text: 'This save takes own sentences away. Nothing is written yet.' }),
        h('ul', {}, (r.removed || []).map(c => h('li', {}, h('code', { text: c.key }), ' now: ', textOf(c.before), ' — then the profile runs with: ', textOf(c.after)))),
        h('button', { class: 'danger', text: 'Remove and save', onclick: () => actSave(X, true) })));
    } else if (r.reason === 'check') out.push(h('div', { class: 'box bad', text: 'Not saved: the check refuses this text.' }));
  }
  out.push(...(X.kind === 'prompt' ? promptReport(r) : phrasesReport(r, R.source === 'save')));
  return out;
}
const textOf = v => Array.isArray(v) ? v.join(' / ') : (v == null ? '' : String(v));

function promptReport(r) {
  const out = [];
  if (r.ok) out.push(h('div', { class: 'box ok', text: 'A run would load this text.' }));
  else out.push(h('div', { class: 'box bad' }, h('b', { text: 'The check refuses this text: ' }), r.error || ''));
  if (r.creates) out.push(h('div', { class: 'box warnbox', text: 'Saving writes a new file of this profile: ' + r.creates }));
  if (r.changed === false) out.push(h('div', { class: 'help', text: 'The text is the file on disk.' }));
  if (r.size) out.push(h('div', { class: 'help', text: 'The text that is sent: ' + r.size.before + ' → ' + r.size.after + ' characters.' }));
  if (r.meta && isObj(r.meta.before) && isObj(r.meta.after)) {
    const ks = [...new Set(Object.keys(r.meta.before).concat(Object.keys(r.meta.after)))].filter(k => JSON.stringify(r.meta.before[k]) !== JSON.stringify(r.meta.after[k]));
    for (const k of ks) out.push(h('div', { class: 'help' }, 'Setting ', h('code', { text: k }), ': ' + textOf(r.meta.before[k]) + ' → ' + textOf(r.meta.after[k])));
  }
  if (r.sentences) out.push(h('details', { open: true }, h('summary', { text: 'Changes by sentence' }), diffPre(r.sentences)));
  const ln = r.lines || {};
  if (r.diff) out.push(h('details', {}, h('summary', {}, 'Diff of the file ', h('span', { class: 'badge new', text: '+' + (ln.added || 0) + ' lines' }), ' ', h('span', { class: 'badge gone', text: '-' + (ln.removed || 0) + ' lines' })), diffPre(r.diff)));
  if (r.note) out.push(h('div', { class: 'help', text: r.note }));
  return out;
}
function phrasesReport(r, skipRemoved) {
  const out = [];
  if (r.ok) out.push(h('div', { class: 'box ok', text: 'A run would load these sentences.' }));
  else out.push(h('div', { class: 'box bad' }, h('b', { text: 'The check refuses these sentences: ' }), r.error || '', r.where ? ' (' + r.where + ')' : ''));
  if (r.creates) out.push(h('div', { class: 'box warnbox', text: 'Saving writes a new file of this profile: ' + r.creates }));
  if (r.changed === false) out.push(h('div', { class: 'help', text: 'The sentences are those of the file on disk.' }));
  const ch = r.changes || [];
  if (ch.length) {
    out.push(h('details', { open: true }, h('summary', { text: 'Changed sentences (' + ch.length + ')' }), ch.map(c => h('div', { class: 'chg' },
      h('span', { class: 'badge ' + (c.state === 'added' ? 'new' : c.state === 'removed' ? 'gone' : 'changed'), text: c.state }), ' ', h('code', { text: c.key }),
      c.state !== 'added' ? h('div', { class: 'pr-pair' }, 'before: ', textOf(c.before)) : null,
      c.state !== 'removed' ? h('div', { class: 'pr-pair' }, 'after: ', textOf(c.after)) : null))));
  }
  const ln = r.lines || {};
  if (r.diff) out.push(h('details', {}, h('summary', {}, 'Diff of the file ', h('span', { class: 'badge new', text: '+' + (ln.added || 0) + ' lines' }), ' ', h('span', { class: 'badge gone', text: '-' + (ln.removed || 0) + ' lines' })), diffPre(r.diff)));
  if (!skipRemoved && (r.removed || []).length) out.push(h('div', { class: 'warn', text: 'This text takes own sentences away (' + r.removed.map(c => c.key).join(', ') + '). Saving asks for a confirmation.' }));
  if (r.note) out.push(h('div', { class: 'help', text: r.note }));
  return out;
}
function reviewNodes(rv) {
  if (rv.running) return [h('div', { class: 'box', text: 'Running the profile check and the before/after comparison…' })];
  if (rv.err) return [h('div', { class: 'box bad', text: 'The review could not run: ' + rv.err })];
  const res = rv.res || {};
  const out = [h('div', { class: 'box ' + (res.ok ? 'ok' : 'bad') }, h('b', { text: res.ok ? 'The profile check and the before/after comparison passed.' : 'The profile check or the before/after comparison failed.' }))];
  for (const st of res.steps || []) {
    out.push(h('details', { open: !st.ok },
      h('summary', {}, h('span', { class: 'badge ' + (st.ok ? 'ok' : 'dep'), text: st.ok ? 'ok' : 'failed' }), ' ' + (st.name || ''), ' ', h('code', { text: st.command || '' })),
      st.output ? h('pre', { class: 'out', text: st.output }) : h('div', { class: 'help', text: 'No output.' }),
      st.summary ? [h('h4', { text: 'Summary' }), h('pre', { class: 'out pr-summary', text: st.summary })] : null));
  }
  return out;
}

/* ---------- the editor of the sentences of a module ---------- */

const inheritedOf = s => s.inherited != null ? s.inherited : s.text;

function diffSegs(a, b) {
  a = a == null ? '' : String(a); b = b == null ? '' : String(b);
  const m = Math.min(a.length, b.length);
  let i = 0;
  while (i < m && a[i] === b[i]) i++;
  let j = 0;
  while (j < m - i && a[a.length - 1 - j] === b[b.length - 1 - j]) j++;
  return { a: [a.slice(0, i), a.slice(i, a.length - j), a.slice(a.length - j)], b: [b.slice(0, i), b.slice(i, b.length - j), b.slice(b.length - j)] };
}
function segNodes(seg, cls) { return [seg[0], seg[1] ? h('span', { class: cls, text: seg[1] }) : null, seg[2]]; }

function traceSelect(onChange) {
  const tr = (P.list && P.list.traces) || [];
  if (!tr.length) return h('span', { class: 'help', text: (P.list && P.list.traces_note) || 'There is no recorded request.' });
  if (tr.length === 1) return h('span', {}, 'Trace ', h('code', { text: tr[0].name }), ' ', h('span', { class: 'help', text: mb(tr[0].bytes || 0) }));
  const sel = h('select', { style: 'width:auto' }, tr.map(t => h('option', { value: t.name, text: t.name + ' (' + mb(t.bytes || 0) + ')' })));
  sel.value = P.trace;
  sel.addEventListener('change', () => onChange(sel.value));
  return sel;
}
function setTrace(name) {
  P.trace = name;
  for (const X of P.phs.values()) X.shown = {};
  if (P.sel && P.sel.t === 'prompt') { resetRequests(); renderRight(); startRequests(); }
  else if (P.sel && P.sel.t === 'phrases') renderEditorColumn();
}

function renderPhrasesEditor(X) {
  const d = X.detail;
  const ui = X.ui = {};
  ui.dirty = h('span', { class: 'badge changed', text: 'unsaved changes', hidden: !phDirty(X) });
  const kids = [
    h('div', { class: 'page-title' }, 'Sentences of ' + X.module, ui.dirty),
    h('div', { class: 'page-sub' }, 'File: ', h('code', { text: d.path || '' })),
  ];
  if (!d.own_file) kids.push(h('div', { class: 'warn', text: 'This profile has no file of its own for this module yet. Saving a sentence writes one.' }));
  kids.push(h('div', { class: 'toolbar' }, h('b', { text: 'Recorded requests' }), traceSelect(setTrace)));
  for (const s of d.sentences || []) kids.push(sentenceRow(X, s));
  ui.check = h('button', { text: 'Check', title: 'Ctrl+Enter', onclick: () => actCheck(X) });
  ui.save = h('button', { class: 'primary', text: 'Save', title: 'Ctrl+S', onclick: () => actSave(X, false) });
  ui.discard = h('button', { text: 'Discard changes', onclick: () => actDiscard(X) });
  ui.report = h('div', { class: 'pr-report' });
  kids.push(h('div', { class: 'toolbar pr-actions' }, ui.check, ui.save, ui.discard), ui.report);
  put($('pl-main'), ...kids);
  syncButtons(X);
  renderReport(X);
}

function sentenceRow(X, s) {
  const box = h('div', { class: 'field pr-sent' });
  const key = s.key;
  const draw = () => {
    const mine = own(X.table, key);
    const cur = mine ? X.table[key] : inheritedOf(s);
    const isList = Array.isArray(cur);
    const items = isList ? cur : [cur];
    /* what the trace showed belongs to the wording it was looked up with: it is hidden once the sentence reads differently */
    let shownEl = null;
    const fresh = () => { const c = X.shown[key]; return !!c && (c.loading || c.text === firstText()); };
    const areas = items.map((t, i) => {
      const ta = h('textarea', { class: 'prompt', spellcheck: 'false', value: t == null ? '' : String(t), readonly: mine ? null : true });
      ta.rows = Math.max(2, Math.min(12, String(ta.value).split('\n').length + 1));
      if (mine) ta.addEventListener('input', () => {
        if (Array.isArray(X.table[key])) X.table[key][i] = ta.value; else X.table[key] = ta.value;
        if (shownEl) shownEl.hidden = !fresh();
        edited(X);
      });
      return ta;
    });
    const fromWhere = s.from || 'default';
    const acts = [];
    if (mine && s.inherited != null) acts.push(h('button', { text: 'Take the inherited wording again', onclick: () => { delete X.table[key]; draw(); edited(X); } }));
    if (!mine) acts.push(h('button', { text: 'Word it for this profile', onclick: () => { X.table[key] = clone(inheritedOf(s)); draw(); edited(X); } }));
    const cell = X.shown[key];
    const firstText = () => { const c = own(X.table, key) ? X.table[key] : inheritedOf(s); return Array.isArray(c) ? (c[0] == null ? '' : String(c[0])) : String(c == null ? '' : c); };
    shownEl = cell ? h('div', { hidden: !fresh() }, shownNodes(cell, draw)) : null;
    put(box,
      s.note ? h('div', { class: 'help', text: s.note }) : null,
      h('label', {}, h('code', { text: key }), ' ', s.required ? h('span', { class: 'badge', text: 'required' }) : null, ' ',
        mine ? h('span', { class: 'badge ok', text: 'this profile' }) : h('span', { class: 'badge', text: 'from ' + fromWhere })),
      areas,
      h('div', { class: 'help' }, s.names == null ? 'Takes no name in braces.' : 'Names the code fills: ' + (s.names.length ? s.names.map(n => '{' + n + '}').join(' ') : 'none')),
      h('div', { class: 'toolbar' }, acts,
        P.trace ? h('button', { text: 'Recorded requests with this sentence', disabled: !!(cell && cell.loading), onclick: () => fetchShown(X, s, draw, firstText()) }) : null),
      shownEl);
  };
  draw();
  return box;
}
async function fetchShown(X, s, draw, text) {
  const cell = { loading: true, trace: P.trace, text };
  X.shown[s.key] = cell; draw();
  try { cell.res = await apiR('/api/phrases/shown', { module: X.module, key: s.key, text, trace: P.trace }); }
  catch (e) { cell.err = e.message; }
  cell.loading = false;
  if (X.shown[s.key] === cell) draw();
}
function shownNodes(cell, draw) {
  if (cell.loading) return h('div', { class: 'help', text: 'Looking through the trace… the first time this takes several seconds.' });
  if (cell.err) return h('div', { class: 'box bad', text: cell.err });
  const r = cell.res || {};
  const all = r.shown || [];
  const limit = cell.all ? all.length : 50;
  return h('div', {},
    h('div', { class: 'help', text: 'Found in ' + (r.found == null ? all.length : r.found) + ' of ' + (r.searched == null ? '?' : r.searched) + ' requests.' + (r.why ? ' ' + r.why : '') }),
    all.slice(0, limit).map(it => {
      const segs = it.after == null ? null : diffSegs(it.before, it.after);
      return h('div', { class: 'pr-pair' },
        h('div', {}, h('span', { class: 'idx', text: '#' + it.index }), ' ', it.kind || '', it.asked ? ' (asks again: ' + it.asked + ')' : '', it.parameter ? ' · ' + it.parameter : ''),
        h('div', {}, 'before: ', segs ? segNodes(segs.a, 'pr-gone') : textOf(it.before)),
        segs ? h('div', {}, 'after: ', segNodes(segs.b, 'pr-hit')) : null,
        it.why ? h('div', { class: 'help', text: it.why }) : null);
    }),
    all.length > limit ? h('button', { text: 'Show all ' + all.length, onclick: () => { cell.all = true; draw(); } }) : null);
}

/* ---------- recorded requests (right column) ---------- */

function kindsOf(id) { const p = ((P.list && P.list.prompts) || []).find(x => x.id === id); return p ? (p.kinds || []) : []; }

function resetRequests() {
  clearTimeout(P.pvTimer); clearTimeout(P.rqTimer);
  P.pvSeq++; P.rqSeq++;
  P.req = null; P.tryRes = null; P.rui = null;
  if (P.sel && P.sel.t === 'prompt' && P.trace && kindsOf(P.sel.id).length) {
    P.req = { prompt: P.sel.id, trace: P.trace, kind: '', field: '', carries: '', text: '', offset: 0, listing: null, listErr: null, listLoading: false,
      opts: null, sel: null, pv: null, pvErr: null, pvLoading: false, pvEdited: false, showSent: false, sysOpen: false };
  }
}
function startRequests() { if (P.req) fetchRequests(); }

function renderRight() {
  const box = $('pl-right');
  if (!P.list) { put(box); return; }
  const note = t => put(box, h('div', { class: 'help', text: t }));
  if (!P.sel) { note('Pick a prompt to see the recorded requests it has a say in.'); return; }
  if (P.sel.t === 'phrases') { note('Recorded requests are shown beside a prompt. For a sentence, choose a trace in its editor and press "Recorded requests with this sentence".'); return; }
  if (!kindsOf(P.sel.id).length) { note('No request of a harvest is recorded with this prompt alone, so there is no preview.'); return; }
  if (!P.req) { note(P.list.traces_note || 'There is no recorded request to show.'); return; }
  const R = P.req;
  const rui = P.rui = { filters: h('div', { class: 'pr-filters' }), count: h('div', { class: 'help' }), list: h('div', { class: 'pr-reqlist' }),
    pager: h('div', { class: 'toolbar' }), tryBox: h('div'), chat: h('div'), textIn: h('input', { type: 'text', placeholder: 'text anywhere in the request or its answer', spellcheck: 'false', value: R.text }) };
  rui.textIn.addEventListener('input', () => {
    R.text = rui.textIn.value; R.offset = 0;
    clearTimeout(P.rqTimer); P.rqTimer = setTimeout(fetchRequests, 350);
  });
  put(box,
    h('div', { class: 'toolbar' }, h('b', { text: 'Recorded requests' }), traceSelect(setTrace)),
    rui.filters, rui.count, rui.list, rui.pager,
    h('div', { class: 'section', text: 'Try' }), rui.tryBox,
    h('div', { class: 'section', text: 'Request' }), rui.chat);
  renderFilters(); renderReqList(); renderTry(); renderChat();
}

function filterSelect(label, options, value, onChange) {
  const sel = h('select', { title: label }, h('option', { value: '', text: label + ': any' }), options.map(o => h('option', { value: o, text: o })));
  sel.value = options.includes(value) ? value : '';
  sel.addEventListener('change', () => onChange(sel.value));
  return sel;
}
function renderFilters() {
  const R = P.req, rui = P.rui;
  if (!R || !rui) return;
  const o = R.opts || { kinds: [], fields: [], carried: [] };
  const change = k => v => { R[k] = v; R.offset = 0; fetchRequests(); };
  put(rui.filters, filterSelect('kind', o.kinds, R.kind, change('kind')), filterSelect('field', o.fields, R.field, change('field')),
    filterSelect('message carries', o.carried, R.carries, change('carries')), rui.textIn);
}

async function fetchRequests() {
  const R = P.req;
  if (!R) return;
  const my = ++P.rqSeq;
  R.listLoading = true; R.listErr = null; renderReqList();
  const q = new URLSearchParams({ trace: R.trace, prompt: R.prompt, kind: R.kind, field: R.field, carries: R.carries, text: R.text, offset: String(R.offset), limit: '100' });
  try {
    const a = await api('GET', '/api/requests?' + q.toString());
    if (my !== P.rqSeq || P.req !== R) return;
    R.listing = a;
    const opts = { kinds: a.kinds || [], fields: a.fields || [], carried: a.carried || [] };
    const changedOpts = JSON.stringify(opts) !== JSON.stringify(R.opts);
    R.opts = opts;
    R.listLoading = false;
    if (changedOpts) renderFilters();
  } catch (e) {
    if (my !== P.rqSeq || P.req !== R) return;
    R.listErr = e.message; R.listLoading = false;
  }
  renderReqList(); renderTry();
}

const reqLabel = r => [r.kind, r.parameter, r.coordinate].filter(Boolean).join(' · ') + (r.asked ? ' (asks again: ' + r.asked + ')' : '');
function reqSub(r) {
  const a = [];
  if (r.owner != null) a.push('passage ' + r.owner);
  if (r.value != null) a.push('value ' + r.value + (r.at ? ' @' + r.at : ''));
  if (r.ms != null) a.push(Math.round(r.ms) + ' ms');
  a.push((r.prompt_tokens == null ? '?' : r.prompt_tokens) + '/' + (r.completion_tokens == null ? '?' : r.completion_tokens) + ' tok');
  if (r.attempt > 1) a.push('attempt ' + r.attempt);
  return a.join(' · ');
}
function renderReqList() {
  const R = P.req, rui = P.rui;
  if (!R || !rui) return;
  const L = R.listing;
  if (R.listErr) { put(rui.count, h('div', { class: 'box bad', text: R.listErr })); put(rui.list); put(rui.pager); return; }
  if (!L) { put(rui.count, h('div', { class: 'help', text: 'Reading the trace. The first time this takes several seconds…' })); put(rui.list); put(rui.pager); return; }
  const reqs = L.requests || [];
  put(rui.count, (L.matching == null ? reqs.length : L.matching) + ' of ' + L.total + ' requests' + (R.listLoading ? ' · updating…' : ''));
  const top = rui.list.scrollTop;
  put(rui.list, ...reqs.map(r => h('button', { class: 'pr-req' + (R.sel === r.index ? ' sel' : ''), onclick: () => selectRequest(r.index) },
    h('b', { text: reqLabel(r) }), h('small', { text: reqSub(r) }), h('small', { text: r.check || '' }))));
  if (!reqs.length) put(rui.list, h('div', { class: 'help pr-pad', text: 'No request matches.' }));
  rui.list.scrollTop = top;
  const m = L.matching == null ? reqs.length : L.matching;
  put(rui.pager,
    h('button', { text: 'Previous', disabled: R.offset <= 0 || R.listLoading, onclick: () => { R.offset = Math.max(0, R.offset - 100); fetchRequests(); } }),
    h('span', { class: 'count', text: m ? (R.offset + 1) + '–' + (R.offset + reqs.length) + ' of ' + m : '' }),
    h('button', { text: 'Next', disabled: R.offset + 100 >= m || R.listLoading, onclick: () => { R.offset += 100; fetchRequests(); } }));
}

function selectRequest(index) {
  const R = P.req;
  if (!R) return;
  R.sel = index; R.pv = null; R.pvErr = null;
  clearTimeout(P.pvTimer);
  renderReqList(); renderChat(); renderTry();
  doPreview();
}
function schedulePreview() {
  clearTimeout(P.pvTimer);
  if (!P.req || P.req.sel == null) return;
  P.pvTimer = setTimeout(doPreview, 400);
}
async function doPreview() {
  const R = P.req;
  if (!R || R.sel == null) return;
  const my = ++P.pvSeq;
  const edits = editsMap();
  R.pvLoading = true; renderChat();
  try {
    const a = await apiR('/api/request/preview', { trace: R.trace, index: R.sel, edits });
    if (my !== P.pvSeq || P.req !== R) return;
    R.pv = a; R.pvErr = null; R.pvEdited = Object.keys(edits).length > 0;
  } catch (e) {
    if (my !== P.pvSeq || P.req !== R) return;
    R.pvErr = e.message;
  }
  R.pvLoading = false;
  renderChat();
}

/* the chat view of scripts/chat_view.py: numbered lines, the lines an answer's addresses name highlighted */
function addrs(a) {
  const out = [];
  const add = x => {
    if (x === undefined || x === null) return;
    const m = String(x).match(/^([A-Za-z]*)(\d+)(?:\.\d+)?(?:-([A-Za-z]*)(\d+)(?:\.\d+)?)?$/);
    if (!m) return;
    const lo = +m[2], hi = m[4] ? +m[4] : lo;
    for (let n = lo; n <= Math.min(hi, lo + 500); n++) out.push(m[1] + n);
  };
  const walk = o => {
    if (Array.isArray(o)) o.forEach(walk);
    else if (o && typeof o === 'object') { if ('at' in o) add(o.at); Object.values(o).forEach(v => { if (typeof v === 'object') walk(v); }); }
  };
  walk(a);
  return new Set(out);
}
function lineKey(s) { const m = String(s).match(/^\s*([A-Za-z]*\d+)\b/); return m ? m[1] : null; }
function valNodes(v, hit, ind) {
  const pad = '  '.repeat(ind);
  if (Array.isArray(v)) {
    if (v.length && v.every(x => typeof x === 'string')) return v.map(s => { const k = lineKey(s); return h('span', { class: 'ln' + (k && hit.has(k) ? ' hit' : '') }, s); });
    return v.flatMap(x => valNodes(x, hit, ind));
  }
  if (v && typeof v === 'object') {
    return Object.entries(v).flatMap(([k, x]) => {
      const sub = x && typeof x === 'object';
      return [h('span', { class: 'ln' }, h('span', { class: 'key', text: pad + k + ':' }), sub ? null : ' ' + x)].concat(sub ? valNodes(x, hit, ind + 1) : []);
    });
  }
  return [h('span', { class: 'ln', text: pad + v })];
}
function userNodes(text, hit) {
  let o = null;
  try { o = JSON.parse(text); } catch (e) { o = null; }
  if (o && typeof o === 'object') return valNodes(o, hit, 0);
  return String(text).split('\n').map(line => { const k = lineKey(line); return h('span', { class: 'ln' + (k && hit.has(k) ? ' hit' : ''), text: line }); });
}
function prettyAnswer(a) {
  if (a && a.answer_json) {
    let t = JSON.stringify(a.answer_json, null, 2);
    if (Array.isArray(a.spelled) && a.spelled.length) t += '\n= ' + a.spelled.join('; ');
    return t;
  }
  return a && a.answer != null ? String(a.answer) : '';
}

function renderChat() {
  const R = P.req, rui = P.rui;
  if (!R || !rui) return;
  const box = rui.chat;
  if (R.sel == null) { put(box, h('div', { class: 'help', text: 'Pick a request to see it as a chat, with your unsaved changes in it.' })); return; }
  if (!R.pv) {
    put(box, R.pvErr ? h('div', { class: 'box bad', text: R.pvErr }) : h('div', { class: 'help', text: 'Loading request #' + R.sel + '…' }));
    return;
  }
  const pv = R.pv, rec = pv.recorded || {}, p = pv.preview || null, notes = pv.notes || {};
  const hit = addrs(rec.answer_json);
  const msgs = Array.isArray(rec.messages) ? rec.messages : [];
  const kids = [];
  kids.push(h('div', { class: 'page-title' }, reqLabel({ kind: pv.kind, parameter: notes.parameter, coordinate: notes.coordinate, asked: pv.asked })),
    h('div', { class: 'help', text: '#' + pv.index + (notes.doc != null ? ' · doc ' + notes.doc : '') + ' · ' + reqSub(notes) + (R.pvLoading ? ' · updating…' : '') }));
  if (R.pvErr) kids.push(h('div', { class: 'box bad', text: R.pvErr }));
  if (Array.isArray(pv.chain) && pv.chain.length > 1) {
    kids.push(h('div', { class: 'help' }, 'Requests of the same value: ', pv.chain.flatMap(i => [i === pv.index ? h('b', { text: '#' + i }) : h('button', { class: 'link', text: '#' + i, onclick: () => selectRequest(i) }), ' '])));
  }
  const usable = !!p && !p.why && !!p.edit;
  if (p && p.why) kids.push(h('div', { class: 'warn', text: p.why + ' The request is shown as it was sent.' }));
  else if (p) {
    if (p.same_as_recorded) kids.push(h('div', { class: 'help', text: 'The files on disk give this request character for character.' }));
    else if (p.example === 'lines') kids.push(h('div', { class: 'help', text: 'This request was sent with other words of this prompt; its example reply is taken from the record.' }));
    if (p.changed === false && R.pvEdited) kids.push(h('div', { class: 'warn', text: 'Your change does not reach this request.' }));
  }
  if (usable) {
    const cb = h('input', { type: 'checkbox' });
    cb.checked = R.showSent;
    cb.addEventListener('change', () => { R.showSent = cb.checked; renderChat(); });
    kids.push(h('label', { class: 'checkrow' }, cb, ' Show the instruction as it was sent'));
  }
  let instruction;
  if (!usable || R.showSent) instruction = h('div', { text: rec.system || '' });
  else if ((p.lines || []).length) {
    instruction = h('div', {}, p.lines.map(line => h('span', { class: 'ln' }, (line || []).map(pair => h('span', { class: pair && pair[1] ? 'pr-chg' : null, text: pair ? pair[0] : '' })))));
  } else instruction = h('div', { text: (p.edit && p.edit.system) || '' });
  const gone = usable && !R.showSent && (p.gone || []).length ? h('div', { class: 'pr-gonebox' }, h('div', { class: 'role', text: 'removed by your change' }), p.gone.map(s => h('div', { class: 'pr-gone', text: s }))) : null;
  const sysDetails = h('details', { class: 'pr-msg system', open: R.sysOpen ? true : null }, h('summary', { class: 'role', text: 'instruction' }), instruction, gone);
  sysDetails.addEventListener('toggle', () => { R.sysOpen = sysDetails.open; });
  kids.push(sysDetails);

  const first = msgs[0] ? String(msgs[0][1] == null ? '' : msgs[0][1]) : '';
  const userText = pv.kind === 'follow' && usable && typeof p.edit.user === 'string' ? p.edit.user : first;
  kids.push(h('div', { class: 'pr-msg user' }, h('div', { class: 'role', text: 'request' }), userNodes(userText, hit)));
  for (const m of msgs.slice(1)) {
    kids.push(h('div', { class: 'pr-msg ' + (m[0] === 'assistant' ? 'assistant' : 'user') }, h('div', { class: 'role', text: m[0] + ' (this attempt)' }), String(m[1] == null ? '' : m[1])));
  }
  kids.push(h('div', { class: 'pr-msg assistant' }, h('div', { class: 'role', text: 'answer' + (rec.finish ? ' · ' + rec.finish : '') }),
    rec.answer == null ? (rec.error || 'no answer') : prettyAnswer(rec)));
  kids.push(h('div', { class: 'pr-msg check' }, h('div', { class: 'role', text: 'result' }), rec.check || ''));
  put(box, ...kids);
}

/* ---------- Try: the only place that sends anything to a model, one click each ---------- */

function renderTry() {
  const R = P.req, rui = P.rui;
  if (!R || !rui) return;
  const T = (P.list && P.list.try) || {};
  const listed = R.listing && R.listing.requests ? R.listing.requests : [];
  const n = Math.min(T.limit || 3, listed.length);
  const running = !!(P.tryRes && P.tryRes.running);
  const off = !T.configured || running;
  const b1 = h('button', { text: 'Try on this request (sends 1 request)', disabled: off || R.sel == null, onclick: () => doTry([R.sel]) });
  const b2 = h('button', { text: 'Try on the first ' + n + ' listed (sends ' + plural(n, 'request') + ')', disabled: off || n < 1, onclick: () => doTry(listed.slice(0, n).map(r => r.index)) });
  const why = T.configured ? (T.model ? 'Model ' + T.model + (T.host ? ' on ' + T.host : '') : '') : 'Not available: ' + (T.why || 'no model is configured.');
  const kids = [h('div', { class: 'pr-tryrow' }, b1, b2), h('div', { class: T.configured ? 'help' : 'warn', text: why })];
  const tr = P.tryRes;
  if (tr && tr.running) kids.push(h('div', { class: 'box', text: 'Sending ' + plural(tr.n, 'request') + ' to ' + (T.host || 'the model') + '…' }));
  else if (tr && tr.err) kids.push(h('div', { class: 'box bad', text: tr.err }));
  else if (tr && tr.res) kids.push(...tryNodes(tr.res, listed));
  put(rui.tryBox, ...kids);
}
async function doTry(indexes) {
  const R = P.req;
  if (!R || !indexes.length) return;
  const T = (P.list && P.list.try) || {};
  if (!T.configured || (P.tryRes && P.tryRes.running)) return;
  const cell = { running: true, n: indexes.length };
  P.tryRes = cell; renderTry();
  try { cell.res = await apiR('/api/request/try', { trace: R.trace, indexes, edits: editsMap() }); }
  catch (e) { cell.err = e.message; }
  cell.running = false;
  if (P.tryRes === cell && P.req === R) renderTry();
}
const addrWhy = { not_an_address: 'names no shown line', words_not_in_line: 'its words do not stand in the line it names' };
function tryNodes(res, listed) {
  const c = res.counts || {};
  const out = [h('div', { class: 'help', text: 'Named ' + (c.named == null ? '?' : c.named) + ', sent ' + (c.sent == null ? '?' : c.sent) + ', failed ' + (c.failed == null ? '?' : c.failed) +
    '; the same answer ' + (c.same == null ? '?' : c.same) + ', a different answer ' + (c.different == null ? '?' : c.different) + ', not in the reply\'s form ' + (c.out_of_form == null ? '?' : c.out_of_form) +
    '; addresses that hold ' + (c.addresses_hold == null ? '?' : c.addresses_hold) + ', that fail ' + (c.addresses_fail == null ? '?' : c.addresses_fail) + '.' })];
  for (const r of res.results || []) {
    const found = listed.find(x => x.index === r.index);
    const head = h('div', {}, h('b', { text: '#' + r.index }), found ? ' ' + reqLabel(found) : '');
    if (!r.sent) { out.push(h('div', { class: 'pr-try' }, head, h('div', { class: 'warn', text: 'Not sent: ' + (r.why || 'no reason given.') }))); continue; }
    const o = r.old || {}, nw = r.new || {};
    const badges = [];
    if (r.same === true) badges.push(h('span', { class: 'badge ok', text: 'the same answer' }));
    else if (r.same === false) badges.push(h('span', { class: 'badge changed', text: 'a different answer' }));
    if (nw.in_form === true) badges.push(h('span', { class: 'badge ok', text: 'in the reply\'s form' }));
    else if (nw.in_form === false) badges.push(h('span', { class: 'badge dep', text: 'not in the reply\'s form' + (nw.fault ? ' (' + nw.fault + ')' : '') }));
    if (r.changed_request === false) badges.push(h('span', { class: 'badge', text: 'the edit did not change what was sent' }));
    if (r.holds === true) badges.push(h('span', { class: 'badge ok', text: 'every address holds' }));
    else if (r.holds === false) badges.push(h('span', { class: 'badge dep', text: 'an address fails' }));
    else badges.push(h('span', { class: 'badge', text: 'names no address' }));
    const stats = [];
    if (nw.ms != null) stats.push(Math.round(nw.ms) + ' ms');
    if (nw.prompt_tokens != null || nw.completion_tokens != null) stats.push((nw.prompt_tokens == null ? '?' : nw.prompt_tokens) + '/' + (nw.completion_tokens == null ? '?' : nw.completion_tokens) + ' tok' + (nw.max_tokens != null ? ' (max ' + nw.max_tokens + ')' : ''));
    if (nw.finish) stats.push(nw.finish);
    out.push(h('div', { class: 'pr-try' }, head, h('div', { class: 'pr-badges' }, badges),
      h('div', { class: 'two' },
        h('div', {}, h('h4', { text: 'recorded' }), h('pre', { text: prettyAnswer(o) || '(no answer)' }), o.check ? h('div', { class: 'help', text: o.check }) : null),
        h('div', {}, h('h4', { text: 'new' }), h('pre', { text: nw.error ? nw.error : (prettyAnswer(nw) || '(no answer)') }), nw.error ? h('div', { class: 'help', text: 'The server gave an error.' }) : null)),
      (r.addresses || []).length ? h('div', {}, h('h4', { text: 'addresses of the new answer' }), r.addresses.map(a => h('div', { class: 'help' },
        h('code', { text: String(a.at) }), a.words ? ' “' + a.words + '” ' : ' ',
        a.holds === true ? h('span', { class: 'badge ok', text: 'holds' })
          : a.holds === false ? h('span', { class: 'badge dep', text: a.why ? (addrWhy[a.why] || a.why) : 'does not hold' })
          : h('span', { class: 'badge', text: 'says that no shown line holds it' })))) : null,
      stats.length ? h('div', { class: 'help', text: stats.join(' · ') }) : null));
  }
  return out;
}

/* ---------- flow tab ---------- */

/* State. F.cur holds each number as the page has it: a whole number, or the text typed where that is none (the server
   refuses it and names the number). All inputs of one number share F.cur[name]; F.ui holds the nodes of the last drawing. */
const F = {
  loaded: false, loading: false, data: null, num: {}, cur: {}, report: null,
  meas: null, counting: false, trace: null, mSeq: 0, mTimer: null, busy: false, dirty: false, ui: null,
  order: null, off: new Set(),
};
const flowDirty = () => !!F.data && (F.data.numbers.some(n => F.cur[n.name] !== n.value) || orderDirty());
const numVal = t => { const s = String(t).trim(); return /^-?\d+$/.test(s) && Number.isSafeInteger(Number(s)) ? Number(s) : t; };
function flowNumbers() { const o = {}; for (const n of F.data.numbers) o[n.name] = F.cur[n.name]; return o; }
const flowSig = () => JSON.stringify([flowNumbers(), F.order, [...F.off].sort()]);
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function loadFlow(keep) {
  if (F.loading) return;
  F.loading = true;
  if (!F.loaded) put($('fl-wrap'), h('div', { class: 'help fl-pad', text: 'Loading…' }));
  try {
    const d = await api('GET', '/api/flow');
    const prev = F.cur;
    F.data = d; F.num = {}; F.cur = {};
    for (const n of d.numbers) { F.num[n.name] = n; F.cur[n.name] = keep && own(prev, n.name) ? prev[n.name] : n.value; }
    if (!keep || !F.order) { F.order = framesOf(d.steps || [], 'document'); F.off = new Set(offOf(d.steps || [])); }
    F.report = null; F.loaded = true;
    if (F.trace && !(d.traces || []).some(t => t.name === F.trace)) F.trace = null;
  } catch (e) {
    F.loading = false;
    if (F.loaded) showError(e); else put($('fl-wrap'), h('div', { class: 'box bad', text: e.message }));
    return;
  }
  F.loading = false;
  renderFlow(); renderHeader();
  runMeasured();
}

function openSpec(to) { setTab('spec'); if (to) select(to); }
async function openPrompt(id) {
  const p = setTab('prompts');
  if (p) await p;
  while (P.loading) await sleep(50);
  if (P.loaded) selectPrompt(id);
}

function renderFlow() {
  const d = F.data;
  const ui = F.ui = { inputs: new Map(), seen: new Set(), meas: [], counts: [] };
  F.dirty = flowDirty();
  const ownN = d.numbers.filter(n => n.own).length;
  const fileLine = !d.exists ? 'not written yet: every number is inherited from ' + d.starts_from
    : d.whole ? 'the whole flow of this profile' : 'sets ' + plural(ownN, 'number') + ' of its own';
  ui.check = h('button', { text: 'Check', title: 'Ctrl+Enter', onclick: flowCheck });
  ui.save = h('button', { class: 'primary', text: 'Save', title: 'Ctrl+S', onclick: flowSave });
  ui.discard = h('button', { text: 'Discard', onclick: flowDiscard });
  ui.stale = h('div', { class: 'warn', text: 'A number was edited after this result.', hidden: true });
  ui.report = h('div', { class: 'pr-report' });
  ui.why = h('span', { class: 'help' });
  ui.mnotes = h('div');
  const tr = d.traces || [];
  let traceBox = null;
  if (d.harvest && tr.length > 1) {
    const sel = h('select', { style: 'width:auto' }, h('option', { value: '', text: 'all traces' }), tr.map(t => h('option', { value: t.name, text: t.name + ' (' + mb(t.bytes || 0) + ')' })));
    sel.value = F.trace || '';
    sel.addEventListener('change', () => { F.trace = sel.value || null; runMeasured(); });
    traceBox = h('span', {}, 'Measured on: ', sel);
  }
  const bar = h('div', { class: 'fl-bar toolbar' }, h('code', { text: d.file }), h('span', { class: 'help', text: fileLine }),
    h('span', { class: 'spacer' }), traceBox, ui.why, h('button', { text: 'Rules', onclick: () => openRules('flow') }), ui.check, ui.save, ui.discard);
  const orderLine = h('div', { class: 'help fl-pad', text: 'Drag a step, or use ↑ ↓, to move it among the steps of its frame that move; switch a step off where the code can leave it out. '
    + 'An order the run cannot read in is refused with its reason when you check or save.' });
  const diagram = h('div', { class: 'fl-steps fl-diagram' }, stepList(d.steps || [], 'document'));
  const loose = d.numbers.filter(n => !ui.inputs.has(n.name));
  const looseBox = loose.length ? h('div', { class: 'fl-loose' }, h('div', { class: 'section', text: 'Numbers no step shows' }),
    loose.map(n => h('div', { class: 'fl-extra' }, h('code', { text: n.name }), ' ', numInput(n.name), ' ', h('span', { class: 'help', text: n.help || '' }), numExtras(n.name)))) : null;
  const below = h('div', { class: 'fl-below' },
    (d.notes || []).map(n => h('p', { class: 'fl-notep' }, n.says, n.to ? [' ', h('button', { class: 'link', text: 'open in Spec', onclick: () => openSpec(n.to) })] : null)),
    h('details', { class: 'fl-settings' }, h('summary', { text: 'Other settings of a run (shown, not edited here)' }),
      h('table', { class: 'grid' }, h('thead', {}, h('tr', {}, ['key', 'value', 'origin', 'environment', 'help'].map(t => h('th', { text: t })))),
        h('tbody', {}, (d.settings || []).map(s => h('tr', {}, h('td', { class: 'mono', text: s.key }),
          h('td', { text: s.secret ? (s.set ? '(set, not shown)' : '(unset)') : (s.value == null ? '(unset)' : String(s.value)) }),
          h('td', { text: s.origin || '' }), h('td', { class: 'mono', text: s.env || '' }), h('td', { text: s.help || '' })))))),
    ui.mnotes);
  put($('fl-wrap'), bar, ui.report, orderLine, diagram, looseBox, below);
  syncFlowButtons(); paintReport(); paintMeasured();
}

function stepList(steps, frame) {
  const out = [];
  inOrder(steps, frame).forEach((st, i) => {
    if (i > 0 || st.when) out.push(h('div', { class: 'fl-conn' + (st.when ? ' when' : '') }, st.when ? h('span', { class: 'fl-when', text: 'when: ' + st.when }) : null));
    out.push(stepEl(st, frame));
  });
  return out;
}
function stepEl(st, frame) {
  const ui = F.ui;
  const isFrame = Array.isArray(st.steps), isBox = !isFrame && st.ask != null;
  const kids = [];
  if (isFrame) kids.push(h('div', { class: 'fl-says' }, st.each ? h('b', { text: 'each ' + st.each + ' ' }) : null, st.says));
  else if (isBox) {
    const pr = st.prompt, count = h('span', { class: 'fl-count' });
    ui.counts.push({ el: count, id: st.id });
    kids.push(h('div', { class: 'fl-head' },
      pr && pr.written ? h('button', { class: 'link fl-kind', text: st.ask, title: 'Open the prompt ' + pr.id, onclick: () => openPrompt(pr.id) }) : h('b', { class: 'fl-kind', text: st.ask }), count),
      h('div', { class: 'fl-says', text: st.says }));
  } else kids.push(h('div', { class: 'fl-says', text: st.says }));
  const ctl = stepControls(st, frame);
  if (ctl) kids.unshift(ctl);
  const isOff = F.off.has(st.id) || (st.off && !st.switched_off);
  if (F.off.has(st.id)) kids.push(h('div', { class: 'fl-offsays', text: 'switched off: no run takes this step' }));
  else if (st.off && !st.switched_off) kids.push(h('div', { class: 'fl-offsays', text: st.off }));
  if (Array.isArray(st.bound) && st.bound.length) {
    const names = [...new Set(st.bound.filter(isObj).map(p => p.number))];
    kids.push(h('div', { class: 'fl-bound' }, st.bound.map(p => typeof p === 'string' ? p : numInput(p.number))));
    const extras = names.map(numExtras).filter(Boolean);
    if (extras.length) kids.push(h('div', { class: 'fl-extras' }, extras));
  }
  if (!isFrame) {
    const box = h('div', { class: 'fl-meas' });
    ui.meas.push({ el: box, id: st.id });
    kids.push(box);
  }
  for (const sw of st.switches || []) {
    const items = sw.items || [];
    kids.push(h('div', { class: 'fl-switch' }, sw.label + ': ', items.length
      ? items.flatMap((it, i) => [i ? ', ' : null, it.to ? h('button', { class: 'link', text: it.label, onclick: () => openSpec(it.to) }) : it.label])
      : sw.none));
  }
  const card = h('div', { class: 'fl-step ' + (isFrame ? 'fl-frame' : isBox ? 'fl-box' : 'fl-note') + (isOff ? ' off' : ''), 'data-step': st.id }, kids);
  dragWire(card, st, frame);
  if (isFrame) card.append(h('div', { class: 'fl-steps' }, stepList(st.steps, st.id)));
  if (isBox && st.each) return h('div', {}, h('div', { class: 'fl-each', text: 'each ' + st.each }), card);
  return card;
}

function numInput(name) {
  const n = F.num[name];
  if (!n) return h('code', { text: String(name) });
  const el = h('input', { type: 'number', class: 'fl-num', min: n.least, step: '1', title: n.help || '', value: String(F.cur[name]), 'data-number': name });
  el.classList.toggle('edited', F.cur[name] !== n.value);
  el.addEventListener('input', () => setNumber(name, numVal(el.value), el));
  if (!F.ui.inputs.has(name)) F.ui.inputs.set(name, []);
  F.ui.inputs.get(name).push(el);
  return el;
}
/* what is said once per number, at its first place: set by this profile, a setting that wins */
function numExtras(name) {
  const n = F.num[name], ui = F.ui;
  if (!n || ui.seen.has(name)) return null;
  ui.seen.add(name);
  const bits = [];
  if (n.own) {
    bits.push(h('span', { class: 'badge ok', text: 'set by this profile' }));
    if (!F.data.whole && n.inherited != null) bits.push(' ', h('button', { text: 'use inherited (' + n.inherited + ')', onclick: () => setNumber(name, n.inherited, null) }));
  }
  if (n.setting && (n.in_effect !== n.value || !String(n.origin || '').startsWith('flow.json'))) {
    bits.push(' ', h('span', { class: 'badge changed', text: n.setting + ' = ' + n.in_effect + ' wins here (' + n.origin + ')' }));
  }
  return bits.length ? h('div', { class: 'fl-extra' }, h('code', { text: name }), ' ', bits) : null;
}
/* one number changed: the other inputs of it and the markers are updated in place, nothing is redrawn */
function setNumber(name, v, from) {
  F.cur[name] = v;
  const edited = v !== F.num[name].value;
  for (const el of F.ui.inputs.get(name) || []) {
    if (el !== from) el.value = from ? from.value : String(v);
    el.classList.toggle('edited', edited);
  }
  syncFlowButtons();
  F.ui.stale.hidden = !(F.report && F.report.stamp !== flowSig());
  const d = flowDirty();
  if (d !== F.dirty) { F.dirty = d; renderHeader(); }
  scheduleMeasured();
}
function syncFlowButtons() {
  const u = F.ui;
  if (!u) return;
  u.check.disabled = F.busy; u.save.disabled = F.busy || !flowDirty(); u.discard.disabled = F.busy || !flowDirty();
}

/* measured: sentences written by the server for the numbers as they stand; an answer for older numbers is dropped */
function paintMeasured() {
  const ui = F.ui, M = F.meas;
  if (!ui) return;
  for (const b of ui.meas) {
    const said = M && isObj(M.says) && Array.isArray(M.says[b.id]) ? M.says[b.id] : [];
    put(b.el, F.counting && (b.el.childNodes.length || said.length) ? h('div', { class: 'help', text: 'counting ...' })
      : said.map(s => h('div', { class: 'help fl-sent', text: s })));
  }
  for (const c of ui.counts) {
    const v = M && isObj(M.steps) && own(M.steps, c.id) ? M.steps[c.id] : null;
    c.el.textContent = v == null ? '' : v.toLocaleString('en-US') + (v === 1 ? ' request' : ' requests') + ' in the last run';
  }
  put(ui.why, M && M.why ? M.why : null);
  put(ui.mnotes, (M && M.notes || []).map(t => h('p', { class: 'help', text: t })));
}
function scheduleMeasured() {
  clearTimeout(F.mTimer);
  if (F.meas && !F.meas.harvest) return;
  F.mSeq++; F.counting = true; paintMeasured();
  F.mTimer = setTimeout(runMeasured, 400);
}
async function runMeasured() {
  clearTimeout(F.mTimer);
  if (!F.data) return;
  const my = ++F.mSeq;
  F.counting = true; paintMeasured();
  try {
    const r = await apiR('/api/flow/measured', { numbers: flowNumbers(), trace: F.trace });
    if (my !== F.mSeq) return;
    F.meas = r;
  } catch (e) {
    if (my !== F.mSeq) return;
    F.meas = null; showError(e);
  }
  F.counting = false; paintMeasured();
}

/* check, save, discard */
function focusNumber(name) {
  const el = ((F.ui && F.ui.inputs.get(name)) || [])[0];
  if (el) { el.scrollIntoView({ block: 'center' }); el.focus(); }
}
const fmtN = v => v == null ? '(none)' : String(v);
const writesText = (w, file) => ({ created: 'Saving creates ', changed: 'Saving changes ', removed: 'Saving removes ', unchanged: 'Saving writes nothing to ' }[w] || ('Saving: ' + w + ' '))
  + (file || 'the file') + (w === 'removed' ? ' (nothing would differ from the inherited numbers any more).' : '.');
function paintReport() {
  const ui = F.ui, R = F.report;
  if (!ui) return;
  ui.stale.hidden = !(R && R.stamp !== flowSig());
  put(ui.report, R ? [ui.stale, ...reportNodes(R)] : null);
}
function reportNodes(R) {
  if (R.error) return [h('div', { class: 'box bad', text: R.error })];
  const r = R.r || {}, out = [];
  if (R.source === 'save') {
    if (r.reason === 'moved') return [h('div', { class: 'box bad' }, h('div', { text: r.message || 'The file changed on disk since the page loaded it. Nothing was written.' }),
      h('button', { text: 'Reload from disk', onclick: () => reloadFlow() }))];
    if (!r.saved) out.push(h('div', { class: 'box bad', text: 'Not saved: ' + (r.message || r.reason || 'the server refused the numbers.') }));
  }
  const errs = r.errors || [];
  if (errs.length) out.push(h('div', { class: 'box bad' }, h('b', { text: 'The server refuses: ' }),
    errs.map(e => h('div', {}, e.name ? [h('button', { class: 'link', text: e.name, onclick: () => focusNumber(e.name) }), ': '] : null, e.message))));
  else if (r.ok) out.push(h('div', { class: 'box ok', text: 'Accepted.' }));
  if (!errs.length && Array.isArray(r.changed)) out.push(h('div', { class: 'box' }, h('b', { text: 'Changes (' + r.changed.length + ')' }),
    r.changed.length ? r.changed.map(c => h('div', {}, h('code', { text: c.name }), ': ' + fmtN(c.from) + ' → ' + fmtN(c.to)))
      : h('div', { class: 'help', text: 'No number differs from the files on disk.' })));
  if (!errs.length && r.writes) out.push(h('div', { class: 'help', text: writesText(r.writes, r.file) }));
  if ((r.diff || []).length) out.push(h('details', { open: true }, h('summary', { text: 'Diff of ' + (r.file || 'the file') }), diffPre(r.diff.join('\n'))));
  for (const s of r.says || []) out.push(h('div', { class: 'help', text: s }));
  return out;
}
async function flowCheck() {
  if (!F.data || F.busy) return;
  const stamp = flowSig();
  F.busy = true; syncFlowButtons();
  const arr = orderDirty() ? { order: F.order, off: [...F.off] } : {};
  try { F.report = { source: 'check', r: await apiR('/api/flow/check', Object.assign({ numbers: flowNumbers() }, arr)), stamp }; }
  catch (e) { F.report = { source: 'check', error: e.message, stamp }; }
  F.busy = false; syncFlowButtons(); paintReport();
}
async function flowSave() {
  if (!F.data || F.busy || !flowDirty()) return;
  const stamp = flowSig();
  const body = Object.assign({ numbers: flowNumbers(), base: F.data.base == null ? null : F.data.base },
    orderDirty() ? { order: F.order, off: [...F.off] } : {});
  F.busy = true; syncFlowButtons();
  let saved = null;
  try {
    const r = await apiR('/api/flow/save', body);
    if (r.saved) saved = r; else F.report = { source: 'save', r, stamp };
  } catch (e) { F.report = { source: 'save', error: e.message, stamp }; }
  F.busy = false;
  if (saved) {
    showInfo('Saved ' + (saved.file || 'the flow file') + ' (' + (saved.writes || 'written') + ').');
    await loadFlow(flowSig() !== stamp);   // numbers edited while the save ran are kept
  } else { syncFlowButtons(); paintReport(); }
}
async function flowDiscard() {
  if (!flowDirty() || F.busy) return;
  if (!await askConfirm('Discard changes', 'Discard the edited numbers?', 'Discard')) return;
  for (const n of F.data.numbers) F.cur[n.name] = n.value;
  F.order = framesOf(F.data.steps || [], 'document'); F.off = new Set(offOf(F.data.steps || []));
  F.report = null;
  renderFlow(); renderHeader();
  runMeasured();
}
async function reloadFlow() {
  if (flowDirty() && !await askConfirm('Reload from disk', 'The flow file changed on disk. Reloading drops the edited numbers.', 'Drop my edits and reload')) return;
  await loadFlow(false);
}

/* ---------- rules of a tab ---------- */

/* One input per kind of rule; what the input holds is read back by valueOf. A value the server refuses comes back with
   the rule's name and the reason, nothing is written. */
function ruleInput(r, cur, onChange) {
  const v = cur;
  const kind = r.kind;
  let el;
  if (kind === 'switch') {
    el = h('input', { type: 'checkbox' }); el.checked = !!v;
    el.addEventListener('change', () => onChange(el.checked));
  } else if (kind === 'choice') {
    el = h('select', {}, (r.choices || []).map(c => h('option', { value: c, text: c })));
    el.value = v == null ? '' : String(v);
    el.addEventListener('change', () => onChange(el.value));
  } else if (kind === 'whole' || kind === 'number') {
    el = h('input', { type: 'number', class: 'fl-num', step: kind === 'whole' ? '1' : 'any', min: r.least, max: r.most, value: v == null ? '' : String(v) });
    el.addEventListener('input', () => { const s = el.value.trim(); onChange(s === '' ? null : (isNaN(Number(s)) ? s : Number(s))); });
  } else if (kind === 'text' || kind === 'chars') {
    el = h('input', { type: 'text', value: v == null ? '' : String(v), spellcheck: 'false' });
    el.addEventListener('input', () => onChange(el.value));
  } else if (kind === 'texts') {
    el = h('textarea', { rows: Math.min(8, Math.max(2, (v || []).length + 1)), spellcheck: 'false' });
    el.value = Array.isArray(v) ? v.join('\n') : '';
    el.addEventListener('input', () => onChange(el.value.split('\n').map(s => s.trim()).filter(Boolean)));
  } else {
    el = h('textarea', { rows: 6, class: 'mono', spellcheck: 'false' });
    el.value = JSON.stringify(v, null, 1);
    el.addEventListener('input', () => { try { onChange(JSON.parse(el.value)); el.classList.remove('bad'); } catch (e) { onChange(el.value); el.classList.add('bad'); } });
  }
  return el;
}
function ruleRow(r, cur, onChange, extra) {
  const changed = JSON.stringify(cur) !== JSON.stringify(r.value);
  return h('div', { class: 'ru-row' + (changed ? ' edited' : ''), 'data-rule': r.name },
    h('div', { class: 'ru-head' }, h('code', { text: r.name }), ' ',
      r.own || r.declared_here ? h('span', { class: 'badge ok', text: r.owner || 'set by this profile' }) : h('span', { class: 'badge', text: r.owner || 'inherited' }),
      r.decided ? h('span', { class: 'badge', text: 'decided ' + r.decided }) : null,
      r.setting ? h('span', { class: 'badge' + (r.setting_set || (r.in_effect !== undefined && JSON.stringify(r.in_effect) !== JSON.stringify(r.value)) ? ' changed' : ''), text: 'setting ' + r.setting + (r.setting_set || (r.in_effect !== undefined && JSON.stringify(r.in_effect) !== JSON.stringify(r.value)) ? ' is set and wins' : ' wins where set') }) : null,
      extra || null),
    h('div', { class: 'help', text: r.help || '' }),
    h('div', { class: 'ru-input' }, ruleInput(r, cur, onChange),
      r.has_inherited && JSON.stringify(cur) !== JSON.stringify(r.inherited) ? h('button', { text: 'use inherited', title: JSON.stringify(r.inherited), onclick: () => onChange(clone(r.inherited), true) }) : null),
    r.where ? h('div', { class: 'help mono', text: 'applied in ' + r.where }) : null);
}
function groupedRules(rules, curOf, onChange) {
  const groups = new Map();
  for (const r of rules) { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group).push(r); }
  return [...groups.entries()].map(([g, rs]) => h('details', { class: 'ru-group', open: true }, h('summary', { text: g + ' (' + rs.length + ')' }),
    rs.map(r => ruleRow(r, curOf(r.name), (v, redraw) => onChange(r.name, v, redraw)))));
}

const RU = { tab: null, data: null, cur: {}, report: null, busy: false, from: null };
const rulesDirty = () => !!RU.data && RU.data.rules.some(r => JSON.stringify(RU.cur[r.name]) !== JSON.stringify(r.value));
async function openRules(tab) {
  if (rulesDirty() && RU.tab !== tab && !await askConfirm('Rules', 'The rules of ' + RU.tab + ' have unsaved edits. Drop them?', 'Drop')) return;
  RU.from = tab; RU.tab = tab; RU.report = null;
  for (const id of ['layout', 'prompts', 'flow', 'sources', 'graph']) $(id).hidden = true;
  $('rules').hidden = false;
  put($('rules'), h('div', { class: 'help fl-pad', text: 'Loading…' }));
  try {
    RU.data = await api('GET', '/api/rules?tab=' + encodeURIComponent(tab));
    RU.cur = {};
    for (const r of RU.data.rules) RU.cur[r.name] = clone(r.value);
  } catch (e) { put($('rules'), h('div', { class: 'box bad', text: e.message })); return; }
  renderRules();
}
function closeRules() { $('rules').hidden = true; setTab(RU.from || 'spec'); }
function renderRules() {
  const d = RU.data;
  const bar = h('div', { class: 'fl-bar toolbar' }, h('button', { text: '← back to ' + RU.tab, onclick: closeRules }),
    h('b', { text: 'Rules of the ' + RU.tab + ' tab' }), h('code', { text: d.file }),
    h('span', { class: 'help', text: d.exists ? '' : 'not written yet: every rule is inherited' }), h('span', { class: 'spacer' }),
    h('button', { text: 'Check', disabled: RU.busy, onclick: () => rulesSend('check') }),
    h('button', { class: 'primary', text: 'Save', disabled: RU.busy || !rulesDirty(), onclick: () => rulesSend('save') }),
    h('button', { text: 'Discard', disabled: !rulesDirty(), onclick: () => { for (const r of d.rules) RU.cur[r.name] = clone(r.value); RU.report = null; renderRules(); } }));
  const body = d.rules.length ? groupedRules(d.rules, n => RU.cur[n], (n, v, redraw) => { RU.cur[n] = v; RU.report = null; if (redraw) renderRules(); else syncRulesBar(); })
    : h('div', { class: 'help fl-pad', text: 'No rule of this profile belongs to this tab.' });
  put($('rules'), bar, h('div', { class: 'help fl-pad', text: d.cost || '' }), h('div', { class: 'pr-report', id: 'ru-report' }, RU.report ? reportNodes(RU.report) : null), h('div', { class: 'ru-list' }, body));
}
function syncRulesBar() { renderHeader(); const b = $('rules').querySelector('button.primary'); if (b) b.disabled = RU.busy || !rulesDirty(); }
async function rulesSend(what) {
  if (RU.busy) return;
  const values = {};
  for (const r of RU.data.rules) if (JSON.stringify(RU.cur[r.name]) !== JSON.stringify(r.value)) values[r.name] = RU.cur[r.name];
  RU.busy = true;
  try {
    const r = await apiR('/api/rules/' + what, what === 'save' ? { values, base: RU.data.base } : { values });
    if (what === 'save' && r.saved) { showInfo('Saved ' + r.file + ' (' + r.writes + ').'); RU.busy = false; await openRules(RU.tab); return; }
    RU.report = { source: what, r };
  } catch (e) { RU.report = { source: what, error: e.message }; }
  RU.busy = false; renderRules();
}

/* ---------- sources tab ---------- */

const SR = { loaded: false, data: null, cur: null, report: null, fetch: null, picks: new Map(), busy: false };
const sourcesData = d => ({ sources: clone(Object.fromEntries(d.sources.map(s => [s.name, Object.assign({ kind: s.kind }, s.source)]))),
  lists: clone(Object.fromEntries(d.lists.map(l => [l.name, { kind: l.kind, root: l.root }]))), axis_lists: clone(d.axis_lists || {}) });
const sourcesDirty = () => !!SR.data && JSON.stringify(SR.cur) !== JSON.stringify(sourcesData(SR.data));
async function loadSources() {
  put($('sources'), h('div', { class: 'help fl-pad', text: 'Loading…' }));
  try { SR.data = await api('GET', '/api/sources'); SR.cur = sourcesData(SR.data); SR.loaded = true; }
  catch (e) { put($('sources'), h('div', { class: 'box bad', text: e.message })); return; }
  renderSources(); renderHeader();
}
function srField(obj, key, kind) {
  if (key === 'until_released') { const c = h('input', { type: 'checkbox' }); c.checked = !!obj[key]; c.addEventListener('change', () => { if (c.checked) obj[key] = true; else delete obj[key]; srChanged(); }); return c; }
  if (key === 'files' || key === 'paths' || key === 'query') {
    const t = h('textarea', { rows: key === 'query' ? 6 : 3, class: 'mono', spellcheck: 'false' });
    t.value = key === 'query' ? (obj[key] || '') : (obj[key] || []).join('\n');
    t.addEventListener('input', () => { if (key === 'query') obj[key] = t.value; else obj[key] = t.value.split('\n').map(s => s.trim()).filter(Boolean); srChanged(); });
    return t;
  }
  const i = h('input', { type: 'text', value: obj[key] == null ? '' : String(obj[key]), spellcheck: 'false' });
  i.addEventListener('input', () => { if (i.value === '') delete obj[key]; else obj[key] = i.value; srChanged(); });
  return i;
}
function srChanged() { SR.report = null; renderHeader(); const b = $('sources').querySelector('.sr-save'); if (b) b.disabled = SR.busy || !sourcesDirty(); }
function renderSources() {
  const d = SR.data, cur = SR.cur;
  const kinds = d.kinds || {};
  const bar = h('div', { class: 'fl-bar toolbar' }, h('code', { text: d.file }),
    h('span', { class: 'help', text: d.exists ? '' : (d.inherited_from ? 'inherited from ' + d.inherited_from : 'not written yet') }),
    h('span', { class: 'help', text: 'lock: ' + d.lock.file + (d.lock.fetched_at ? ', fetched ' + d.lock.fetched_at : ', never fetched') }),
    h('span', { class: 'spacer' }),
    h('button', { text: 'Rules', onclick: () => openRules('sources') }),
    h('button', { text: 'Check', disabled: SR.busy, onclick: () => srSend('check') }),
    h('button', { class: 'primary sr-save', text: 'Save', disabled: SR.busy || !sourcesDirty(), onclick: () => srSend('save') }),
    h('button', { text: SR.busy === 'fetch' ? 'Fetching…' : 'Fetch', disabled: !!SR.busy || !d.fetches || sourcesDirty(), title: sourcesDirty() ? 'Save the sources first: a fetch reads the saved file' : 'Pull every source into a folder of the temp directory and show what moved', onclick: srFetch }));
  const rows = Object.entries(cur.sources).map(([name, src]) => {
    const shown = d.sources.find(s => s.name === name);
    const k = kinds[src.kind] || { needs: [], may: [] };
    return h('div', { class: 'sr-src' },
      h('div', { class: 'ru-head' }, h('code', { text: name }), ' ',
        (() => { const s = h('select', {}, Object.keys(kinds).map(x => h('option', { value: x, text: x }))); s.value = src.kind; s.addEventListener('change', () => { cur.sources[name] = { kind: s.value }; srChanged(); renderSources(); }); return s; })(),
        h('span', { class: 'badge', text: (kinds[src.kind] || {}).stands || '' }),
        shown && shown.locked ? h('span', { class: 'badge ok', text: 'locked ' + (shown.locked.version || shown.locked.note || '?') }) : h('span', { class: 'badge dep', text: 'not in the lock' }),
        shown && shown.token ? h('span', { class: 'badge' + (shown.token.set ? ' ok' : ' dep'), text: shown.token.env + (shown.token.set ? ' is set' : ' is not set') }) : null,
        h('span', { class: 'spacer' }), h('button', { class: 'link', text: 'remove', onclick: () => { delete cur.sources[name]; srChanged(); renderSources(); } })),
      shown ? h('div', { class: 'help', text: shown.address }) : null,
      h('table', { class: 'grid' }, h('tbody', {}, [...k.needs, ...k.may].map(key => h('tr', {}, h('td', { class: 'mono', text: key + (k.needs.includes(key) ? ' *' : '') }), h('td', {}, srField(src, key)))))),
      shown && shown.locked && (shown.locked.changed_since_reviewed || []).length ? h('div', { class: 'warn', text: 'changed since reviewed: ' + shown.locked.changed_since_reviewed.join(', ') }) : null);
  });
  const lists = h('table', { class: 'grid' }, h('thead', {}, h('tr', {}, ['list', 'kind', 'root', 'entries now', ''].map(t => h('th', { text: t })))),
    h('tbody', {}, Object.entries(cur.lists).map(([name, l]) => {
      const now = d.lists.find(x => x.name === name);
      const kind = h('select', {}, (d.list_kinds || ['class', 'individual']).map(x => h('option', { value: x, text: x }))); kind.value = l.kind;
      kind.addEventListener('change', () => { l.kind = kind.value; srChanged(); });
      const root = h('input', { type: 'text', value: l.root, spellcheck: 'false' }); root.addEventListener('input', () => { l.root = root.value; srChanged(); });
      return h('tr', {}, h('td', { class: 'mono', text: name }), h('td', {}, kind), h('td', {}, root), h('td', { text: now && now.members != null ? String(now.members) : '' }),
        h('td', {}, h('button', { class: 'link', text: 'remove', onclick: () => { delete cur.lists[name]; for (const [a, n] of Object.entries(cur.axis_lists)) if (n === name) delete cur.axis_lists[a]; srChanged(); renderSources(); } })));
    })));
  const axes = h('table', { class: 'grid' }, h('thead', {}, h('tr', {}, ['coordinate', 'answers from the list', ''].map(t => h('th', { text: t })))),
    h('tbody', {}, Object.entries(cur.axis_lists).map(([axis, name]) => {
      const s = h('select', {}, Object.keys(cur.lists).map(x => h('option', { value: x, text: x }))); s.value = name;
      s.addEventListener('change', () => { cur.axis_lists[axis] = s.value; srChanged(); });
      return h('tr', {}, h('td', { class: 'mono', text: axis }), h('td', {}, s), h('td', {}, h('button', { class: 'link', text: 'remove', onclick: () => { delete cur.axis_lists[axis]; srChanged(); renderSources(); } })));
    })));
  const adders = h('div', { class: 'toolbar' },
    h('button', { text: 'Add a source', onclick: async () => { const n = await askText('Add a source', 'Name of the source', ''); if (n && !cur.sources[n]) { cur.sources[n] = { kind: 'url' }; srChanged(); renderSources(); } } }),
    h('button', { text: 'Add a list', onclick: async () => { const n = await askText('Add a list', 'Name of the list', ''); if (n && !cur.lists[n]) { cur.lists[n] = { kind: 'class', root: '' }; srChanged(); renderSources(); } } }),
    h('button', { text: 'Add a coordinate', onclick: async () => { const n = await askText('A coordinate that answers from a list', 'Name of the coordinate', ''); if (n && Object.keys(cur.lists).length) { cur.axis_lists[n] = Object.keys(cur.lists)[0]; srChanged(); renderSources(); } } }));
  put($('sources'), bar, h('div', { class: 'help fl-pad', text: d.cost }),
    h('div', { class: 'pr-report' }, SR.report ? reportNodes(SR.report) : null),
    h('div', { class: 'sr-cols' },
      h('div', {}, h('div', { class: 'section', text: 'Sources' }), rows, h('div', { class: 'section', text: 'Lists' }), lists,
        h('div', { class: 'section', text: 'Which coordinate answers from which list' }), axes, adders),
      h('div', {}, SR.fetch ? fetchNodes(SR.fetch) : null,
        h('div', { class: 'section', text: SR.fetch ? 'What the fetched shapes and ontology say otherwise than the spec' : 'What the shapes and the ontology say otherwise than the spec' }),
        differencesNodes(SR.fetch ? SR.fetch.differences : d.differences))));
}
function fetchNodes(f) {
  const moved = (f.sources || []).filter(s => s.moved);
  return h('div', { class: 'box' }, h('b', { text: 'Fetched into ' + f.id }),
    h('div', {}, moved.length ? moved.map(s => h('div', {}, h('code', { text: s.name }), ': ' + (s.before || '(none)') + ' → ' + (s.after || s.note || '(none)')))
      : h('div', { class: 'help', text: 'No source moved.' })),
    (f.lists || []).map(l => h('details', {}, h('summary', { text: l.list + ': ' + l.before + ' → ' + l.after + ' entries (' + l.added.length + ' new, ' + l.gone.length + ' gone, ' + l.renamed.length + ' renamed, ' + l.redefined.length + ' defined anew)' }),
      l.added.map(x => h('div', { class: 'help' }, '+ ', h('code', { text: x.id }), ' ' + (x.label || ''))),
      l.gone.map(x => h('div', { class: 'help' }, '− ', h('code', { text: x.id }), ' ' + (x.label || ''))),
      l.renamed.map(x => h('div', { class: 'help' }, h('code', { text: x.id }), ': ' + x.from + ' → ' + x.to)),
      l.redefined.map(x => h('div', { class: 'help' }, h('code', { text: x.id }), ' (' + (x.label || '') + ') defined anew')))),
    (f.files || []).filter(x => x.changed).map(x => h('div', { class: 'help' }, h('code', { text: x.file }), x.entries ? ': ' + x.entries.before + ' → ' + x.entries.after + ' entries' : ': changed')),
    h('div', { class: 'toolbar' }, h('button', { class: 'primary', text: 'Apply', disabled: !!SR.busy, title: 'Write the lists into the profile and the lock into the cache; the spec stays', onclick: srApply }),
      h('button', { text: 'Drop this fetch', onclick: () => { SR.fetch = null; SR.picks.clear(); renderSources(); } })));
}
function diffRow(r, pick) {
  const kids = [h('span', { class: 'badge', text: r.kind }), r.axis ? h('span', { class: 'badge', text: r.axis }) : null, ' ',
    h('code', { text: r.path || '' }), ' ', r.detail];
  if ((r.entries || []).length) {
    kids.push(h('div', { class: 'sr-entries' }, r.entries.map(e => {
      const c = h('input', { type: 'checkbox', disabled: !e.takes, title: e.why || '' });
      c.checked = SR.picks.has(e.id);
      c.addEventListener('change', () => pick(e.id, c.checked ? 'add' : null));
      return h('label', { class: 'sr-entry', title: e.definition || e.why || '' }, c, ' ', h('code', { text: shortId(e.iri) }), ' ' + (e.label || '(the pinned ontology does not carry it)'));
    })));
  }
  if (r.kind && r.kind.startsWith('definition_')) {
    const c = h('input', { type: 'checkbox' });
    c.checked = SR.picks.has(r.id);
    c.addEventListener('change', () => pick(r.id, c.checked ? 'replace' : null));
    kids.push(h('div', { class: 'sr-entries' }, h('label', {}, c, " take the ontology's definition"),
      h('div', { class: 'help', text: 'spec: ' + (r.spec || '(none)') }), h('div', { class: 'help', text: 'ontology: ' + (r.ontology || '') })));
  }
  return h('div', { class: 'sr-row' }, kids);
}
function differencesNodes(D) {
  if (!D) return h('div', { class: 'help', text: 'No spec to compare.' });
  if (D.skipped) return h('div', { class: 'help', text: 'Not compared: ' + D.skipped });
  const fields = (S.data && S.data.parameters || []).map(p => p.uri);
  const pick = (id, action, into) => { if (action) SR.picks.set(id, { id, action, into }); else SR.picks.delete(id); syncTake(); };
  const out = [];
  for (const f of D.fields) {
    out.push(h('details', { class: 'sr-field', open: f.rows.some(r => (r.actions || []).length) },
      h('summary', {}, h('code', { text: f.field }), ' ' + plural(f.rows.length, 'difference')),
      f.rows.map(r => diffRow(r, pick))));
  }
  if (D.unasked.length) out.push(h('details', { class: 'sr-field', open: true }, h('summary', {}, 'Properties of the shapes no field asks (' + D.unasked.length + ')'),
    D.unasked.map(r => {
      const into = h('select', { hidden: true }, fields.map(x => h('option', { value: x, text: x })));
      const act = h('select', {}, h('option', { value: '', text: '—' }), h('option', { value: 'new_field', text: 'new field (draft)' }), h('option', { value: 'merge', text: 'merge into a field' }));
      const set = () => { into.hidden = act.value !== 'merge'; pick(r.id, act.value || null, act.value === 'merge' ? into.value : undefined); };
      act.addEventListener('change', set); into.addEventListener('change', set);
      return h('div', { class: 'sr-row' }, h('code', { text: r.shape + '.' + r.path }), ' ', h('span', { class: 'help', text: r.detail }), ' ', act, ' ', into);
    })));
  out.push(h('div', { class: 'toolbar' }, h('button', { class: 'primary sr-take', text: 'Take into the spec', disabled: !SR.picks.size, onclick: srTake }),
    h('span', { class: 'help', text: 'The spec is changed in the Spec tab, where it is checked and saved with what it costs.' })));
  return out;
}
function syncTake() { const b = $('sources').querySelector('.sr-take'); if (b) b.disabled = !SR.picks.size; }
async function srSend(what) {
  if (SR.busy) return;
  SR.busy = true;
  try {
    const r = await apiR('/api/sources/' + what, what === 'save' ? { data: SR.cur, base: SR.data.base } : { data: SR.cur });
    if (what === 'save' && r.saved) { showInfo('Saved ' + r.file + ' (' + r.writes + ').'); SR.busy = false; await loadSources(); return; }
    SR.report = { source: what, r: Object.assign({}, r, { errors: (r.errors || []).map(e => typeof e === 'string' ? { name: null, message: e } : e) }) };
  } catch (e) { SR.report = { source: what, error: e.message }; }
  SR.busy = false; renderSources();
}
async function srFetch() {
  if (SR.busy) return;
  SR.busy = 'fetch'; renderSources();
  try { SR.fetch = await api('POST', '/api/sources/fetch', {}); SR.picks.clear(); }
  catch (e) { showError(e); }
  SR.busy = false; renderSources();
}
async function srApply() {
  if (!SR.fetch || SR.busy) return;
  if (!await askConfirm('Apply the fetch', 'Write the lists of ' + SR.fetch.id + ' into the profile and its lock into the cache? The spec stays as it is.', 'Apply')) return;
  SR.busy = true;
  try { const r = await api('POST', '/api/sources/apply', { fetch: SR.fetch.id }); showInfo('Applied ' + r.applied + ': ' + r.profile_files.length + ' file(s) of the profile, ' + r.cache_files + ' file(s) into the cache, lock ' + r.lock + '.'); SR.fetch = null; }
  catch (e) { showError(e); }
  SR.busy = false; await loadSources();
}
async function srTake() {
  if (!SR.picks.size) return;
  if (S.dirty && !await askConfirm('Take into the spec', 'The Spec tab has unsaved edits; the taken rows are applied to the spec as saved on disk and replace them.', 'Replace my edits')) return;
  try {
    const r = await api('POST', '/api/sources/take', { chosen: [...SR.picks.values()], fetch: SR.fetch ? SR.fetch.id : null });
    S.data = r.data; S.dirty = true; S.result = null;
    SR.picks.clear();
    setTab('spec'); renderTree(); renderMain(); renderPanel(); renderHeader();
    showInfo(plural(r.done.length, 'change') + ' taken into the spec' + (r.refused.length ? ', ' + r.refused.length + ' refused (' + r.refused.map(x => x.why).join('; ') + ')' : '') + '. Check and save them here.');
  } catch (e) { showError(e); }
}

/* ---------- graph tab ---------- */

const GR = { loaded: false, data: null, cur: null, report: null, probe: null, busy: false, db: '' };
const graphData = d => ({ classes: clone(d.set.classes || {}), constraints: clone(d.set.constraints || {}), rules: Object.fromEntries(d.rules.map(r => [r.name, clone(r.value)])) });
const graphDirty = () => !!GR.data && JSON.stringify(GR.cur) !== JSON.stringify(graphData(GR.data));
async function loadGraph() {
  put($('graph'), h('div', { class: 'help fl-pad', text: 'Loading…' }));
  try { GR.data = await api('GET', '/api/graph'); GR.cur = graphData(GR.data); GR.loaded = true; }
  catch (e) { put($('graph'), h('div', { class: 'box bad', text: e.message })); return; }
  renderGraph(); renderHeader();
}
function grChanged(redraw) { GR.report = null; renderHeader(); if (redraw) renderGraph(); else { const b = $('graph').querySelector('.gr-save'); if (b) b.disabled = GR.busy || !graphDirty(); } }
function constraintChip(c) {
  const sel = h('select', { class: 'gr-effect' }, (GR.data.effects || []).map(x => h('option', { value: x, text: x })));
  sel.value = GR.cur.constraints[c.key] || 'report';
  sel.addEventListener('change', () => { if (sel.value === 'report') delete GR.cur.constraints[c.key]; else GR.cur.constraints[c.key] = sel.value; grChanged(); });
  const P = GR.probe && GR.probe.differs, said = P ? (P.violations || []).find(v => v.key === c.key) : null;
  const says = Array.isArray(c.says) ? c.says.join(', ') : String(c.says);
  return h('span', { class: 'gr-con' + (said && said.after ? ' bad' : ''), title: c.key }, c.component + ' ' + says + ' ', sel,
    said ? h('span', { class: 'help', text: ' violations ' + said.before + ' → ' + said.after }) : null);
}
function classCard(c) {
  const set = GR.cur.classes[c.id] || {};
  const written = h('input', { type: 'checkbox' }); written.checked = set.written !== false;
  written.addEventListener('change', () => { const s = GR.cur.classes[c.id] = Object.assign({}, GR.cur.classes[c.id]); if (written.checked) delete s.written; else s.written = false; if (!Object.keys(s).length) delete GR.cur.classes[c.id]; grChanged(true); });
  const addr = set.address || null;
  const folder = h('input', { type: 'text', value: addr ? addr.folder : '', placeholder: 'as the writer names it', spellcheck: 'false' });
  const key = h('input', { type: 'text', value: addr ? addr.key.join(', ') : '', placeholder: 'properties, e.g. OEO_00140178, rdfs:label', spellcheck: 'false' });
  const setAddr = () => {
    const s = GR.cur.classes[c.id] = Object.assign({}, GR.cur.classes[c.id]);
    const keys = key.value.split(',').map(x => x.trim()).filter(Boolean);
    if (!folder.value.trim() && !keys.length) delete s.address; else s.address = { folder: folder.value.trim(), key: keys };
    if (!Object.keys(s).length) delete GR.cur.classes[c.id];
    grChanged();
  };
  folder.addEventListener('input', setAddr); key.addEventListener('input', setAddr);
  const P = GR.probe && GR.probe.differs, n = P && P.classes ? P.classes[c.id] : null;
  return h('div', { class: 'gr-class' + (written.checked ? '' : ' off') },
    h('div', { class: 'ru-head' }, h('label', {}, written, ' written'), ' ', h('b', { text: c.label || c.id }), ' ', h('code', { text: c.id }), c.shape ? h('span', { class: 'help', text: ' shape ' + c.shape }) : null,
      n ? h('span', { class: 'badge', text: n.before + ' → ' + n.after + ' nodes' }) : null),
    h('div', { class: 'gr-addr' }, 'address: folder ', folder, ' key ', key),
    h('table', { class: 'grid' }, h('tbody', {}, (c.properties || []).map(p => h('tr', {},
      h('td', {}, h('code', { text: p.path }), p.label ? h('div', { class: 'help', text: p.label }) : null),
      h('td', { class: 'gr-fields' }, p.fields.length ? p.fields.map(f => h('button', { class: 'link', text: '← ' + f, title: 'open the field in the Spec tab', onclick: () => openSpec({ t: 'param', uri: f }) })) : h('span', { class: 'help', text: 'no field' })),
      h('td', {}, (p.constraints || []).map(constraintChip)))))));
}
function renderGraph() {
  const d = GR.data;
  const db = h('input', { type: 'text', value: GR.db, placeholder: 'corpus database (default: the profile\'s)', spellcheck: 'false', style: 'width:22em' });
  db.addEventListener('input', () => { GR.db = db.value; });
  const bar = h('div', { class: 'fl-bar toolbar' }, h('code', { text: d.file }), h('span', { class: 'help', text: d.exists ? '' : 'not written yet' }), h('span', { class: 'spacer' }),
    db, h('button', { text: GR.busy === 'probe' ? 'Writing…' : 'Write probe', disabled: !!GR.busy, title: 'Write the graph of the page\'s harvest with the saved file and with this one, into the temp directory', onclick: grProbe }),
    h('button', { text: 'Check', disabled: !!GR.busy, onclick: () => grSend('check') }),
    h('button', { class: 'primary gr-save', text: 'Save', disabled: !!GR.busy || !graphDirty(), onclick: () => grSend('save') }),
    h('button', { text: 'Discard', disabled: !graphDirty(), onclick: () => { GR.cur = graphData(d); GR.report = null; renderGraph(); renderHeader(); } }));
  const rules = groupedRules(d.rules, n => GR.cur.rules[n], (n, v, redraw) => { GR.cur.rules[n] = v; grChanged(redraw); });
  const P = GR.probe && GR.probe.differs;
  const probe = P ? h('div', { class: 'box' }, h('b', { text: 'Probe in ' + GR.probe.folder }),
    h('div', {}, 'triples ' + P.triples.before + ' → ' + P.triples.after + ', named anew: ' + P.readdressed),
    h('details', {}, h('summary', { text: 'documents that differ (' + P.documents.length + ')' }), P.documents.map(x => h('div', { class: 'help' }, h('code', { text: x.document }), ': nodes ' + (x.before.kept || 0) + ' → ' + (x.after.kept || 0) + ', violations ' + (x.before.violations || 0) + ' → ' + (x.after.violations || 0) + (x.after.left_out && x.after.left_out.length ? ', left out: ' + x.after.left_out.map(l => l.constraint).join('; ') : '')))),
    h('details', {}, h('summary', { text: 'violations by constraint' }), (P.violations || []).map(v => h('div', { class: 'help' }, h('code', { text: v.key }), ': ' + v.before + ' → ' + v.after)))) : null;
  put($('graph'), bar, h('div', { class: 'help fl-pad', text: d.cost + ' ' + d.gate }),
    h('div', { class: 'pr-report' }, GR.report ? reportNodes(GR.report) : null), probe,
    h('div', { class: 'section', text: 'Rules of the writer' }), rules,
    h('div', { class: 'section', text: 'Classes of the shapes, the fields that write each property, and what each constraint does' }),
    d.skipped ? h('div', { class: 'help', text: d.skipped }) : (d.classes || []).map(classCard),
    (() => {
      const known = new Set((d.classes || []).map(c => c.id));
      const extra = GR.probe ? Object.keys(GR.probe.saved.classes || {}).filter(k => !known.has(k)) : [];
      return [h('div', { class: 'section', text: 'Classes the writer writes that no shape names' }),
        extra.length ? extra.map(k => classCard({ id: k, shape: null, label: null, properties: [] }))
          : h('div', { class: 'help', text: GR.probe ? 'none' : 'They are listed once a probe has written the graph.' })];
    })());
}
async function grSend(what) {
  if (GR.busy) return;
  GR.busy = true;
  try {
    const r = await apiR('/api/graph/' + what, what === 'save' ? { data: GR.cur, base: GR.data.base } : { data: GR.cur });
    if (what === 'save' && r.saved) { showInfo('Saved ' + r.file + ' (' + r.writes + ').'); GR.busy = false; await loadGraph(); return; }
    GR.report = { source: what, r: Object.assign({}, r, { errors: (r.errors || []).map(e => typeof e === 'string' ? { name: null, message: e } : e) }) };
  } catch (e) { GR.report = { source: what, error: e.message }; }
  GR.busy = false; renderGraph();
}
async function grProbe() {
  if (GR.busy) return;
  GR.busy = 'probe'; renderGraph();
  try { GR.probe = await api('POST', '/api/graph/probe', { data: GR.cur, db: GR.db || null }); }
  catch (e) { showError(e); }
  GR.busy = false; renderGraph();
}

/* ---------- the order of the flow's steps ---------- */

function framesOf(steps, frame, out) {
  out = out || {};
  out[frame] = steps.map(s => s.id);
  for (const s of steps) if (Array.isArray(s.steps)) framesOf(s.steps, s.id, out);
  return out;
}
function offOf(steps, out) {
  out = out || [];
  for (const s of steps) { if (s.switched_off) out.push(s.id); if (Array.isArray(s.steps)) offOf(s.steps, out); }
  return out;
}
const orderDirty = () => !!F.data && (JSON.stringify(F.order) !== JSON.stringify(framesOf(F.data.steps || [], 'document'))
  || JSON.stringify([...F.off].sort()) !== JSON.stringify(offOf(F.data.steps || []).sort()));
function inOrder(steps, frame) {
  const want = F.order && F.order[frame];
  if (!want) return steps;
  const by = new Map(steps.map(s => [s.id, s]));
  return want.map(id => by.get(id)).filter(Boolean);
}
function moveStep(frame, id, to) {
  const list = F.order[frame], i = list.indexOf(id);
  if (i < 0 || to < 0 || to >= list.length) return;
  list.splice(i, 1); list.splice(to, 0, id);
  F.report = null; renderFlow(); renderHeader();
}
function stepControls(st, frame) {
  if (!st.moves && !st.switch) return st.keeps ? h('div', { class: 'fl-keeps', title: st.keeps, text: 'keeps its place' }) : null;
  const bits = [];
  if (st.moves) {
    const list = F.order[frame] || [], i = list.indexOf(st.id);
    bits.push(h('button', { class: 'link', text: '↑', title: 'earlier', disabled: i <= 0, onclick: () => moveStep(frame, st.id, i - 1) }),
      h('button', { class: 'link', text: '↓', title: 'later', disabled: i < 0 || i >= list.length - 1, onclick: () => moveStep(frame, st.id, i + 1) }));
  }
  if (st.switch) {
    const c = h('input', { type: 'checkbox' }); c.checked = !F.off.has(st.id);
    c.addEventListener('change', () => { if (c.checked) F.off.delete(st.id); else F.off.add(st.id); F.report = null; renderFlow(); renderHeader(); });
    bits.push(h('label', { class: 'fl-on', title: st.keeps || '' }, c, ' on'));
  }
  return h('div', { class: 'fl-ctl' }, bits);
}
function dragWire(card, st, frame) {
  if (!st.moves) return;
  card.setAttribute('draggable', 'true');
  card.addEventListener('dragstart', ev => { ev.stopPropagation(); ev.dataTransfer.setData('text/plain', JSON.stringify({ frame, id: st.id })); });
  card.addEventListener('dragover', ev => { ev.preventDefault(); ev.stopPropagation(); });
  card.addEventListener('drop', ev => {
    ev.preventDefault(); ev.stopPropagation();
    let got; try { got = JSON.parse(ev.dataTransfer.getData('text/plain')); } catch (e) { return; }
    if (!got || got.frame !== frame || got.id === st.id) return;
    moveStep(frame, got.id, F.order[frame].indexOf(st.id));
  });
}

/* ---------- tabs ---------- */

function setTab(t) {
  S.tab = t;
  $('layout').hidden = t !== 'spec';
  $('prompts').hidden = t !== 'prompts';
  $('flow').hidden = t !== 'flow';
  $('sources').hidden = t !== 'sources';
  $('graph').hidden = t !== 'graph';
  $('rules').hidden = true;
  renderHeader();
  if (t === 'flow' && !F.loaded) loadFlow();
  if (t === 'sources' && !SR.loaded) loadSources();
  if (t === 'graph' && !GR.loaded) loadGraph();
  if (t === 'prompts' && !P.loaded) return loadPrompts();
}

/* ---------- load ---------- */

async function reload() {
  if (S.dirty && !await askConfirm('Reload from disk', 'There are unsaved edits. Reloading discards them.', 'Discard and reload')) return;
  await run(loadAll);
  if (F.loaded && !flowDirty()) loadFlow();
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

window.addEventListener('beforeunload', ev => { if (anyDirty()) { ev.preventDefault(); ev.returnValue = ''; } });
window.addEventListener('keydown', ev => {
  if (!(ev.ctrlKey || ev.metaKey)) return;
  if (S.tab === 'flow') {
    if (ev.key === 's' || ev.key === 'S') { ev.preventDefault(); flowSave(); }
    else if (ev.key === 'Enter') { ev.preventDefault(); flowCheck(); }
    return;
  }
  if (S.tab === 'prompts') {
    const X = currentX();
    if (!X) return;
    if (ev.key === 's' || ev.key === 'S') { ev.preventDefault(); actSave(X, false); }
    else if (ev.key === 'Enter') { ev.preventDefault(); actCheck(X); }
    return;
  }
  if (ev.key === 's' || ev.key === 'S') { ev.preventDefault(); if (!S.busy) doSave(false); }
  else if (ev.key === 'Enter') { ev.preventDefault(); if (!S.busy) doCheck(); }
});

$('pl-filter').addEventListener('input', ev => { P.filter = ev.target.value; renderList(); });
renderHeader(); renderPanel();
run(loadAll);

})();
