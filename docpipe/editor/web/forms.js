/* Forms for the JSON-typed values of the editor: a value becomes a form state, an edit changes the state, the state gives the value back.
   Pure functions, no DOM; loaded by the page (window.DPForms) and by node (the tests of tests/test_editor_forms.py).
   The promise: with no edit a state gives back the identical value, key order included; an edit of one field changes only the
   key that field shows; a key no field shows is kept; a value that does not fit its form is kept as it is ("odd"). */
(function (root) {
'use strict';

const own = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const clone = v => v === undefined ? undefined : JSON.parse(JSON.stringify(v));
const isEmpty = v => (Array.isArray(v) && !v.length) || (isObj(v) && !Object.keys(v).length);

/* ---------- kinds ---------- */

const TEXT = { k: 'text' };
const KEPT = { k: 'text', keep: true };          // an empty text stays an empty text, not a missing key
const BOUNDS = { k: 'bounds' };
const f = (key, kind, help) => ({ key, kind, help: help || '' });
const PREDICATE = { k: 'record', fields: [f('prefix', { k: 'text', list: 'prefixes' }), f('predicate', { k: 'text', list: 'predicates' }), f('label', TEXT), f('datatype', { k: 'text', list: 'datatypes' }), f('accepted', TEXT)] };
const LINK = { k: 'record', fields: [f('node', TEXT), f('prefix', { k: 'text', list: 'prefixes' }), f('predicate', { k: 'text', list: 'predicates' }), f('schema_slot', TEXT), f('label', TEXT)] };
const SLOT = { k: 'record', fields: [f('schema_slot', TEXT), f('prefix', { k: 'text', list: 'prefixes' }), f('predicate', { k: 'text', list: 'predicates' }), f('label', TEXT), f('datatype', { k: 'text', list: 'datatypes' }), f('from', TEXT)] };
const CLASSMAP = { k: 'map', value: { k: 'record', fields: [f('class', { k: 'text', list: 'classes' }), f('schema_class', TEXT), f('note', { k: 'text', area: true }), f('linked_by', LINK)] } };

/* the kinds a profile's writer names for its kg keys (profiles/<name>/kg.py: KG_KEYS) */
const KINDS = {
  text: TEXT, line: TEXT, note: { k: 'text', area: true },
  class: { k: 'text', list: 'classes' }, datatype: { k: 'text', list: 'datatypes' },
  predicate: PREDICATE, link: LINK, slot: SLOT,
  predicates: { k: 'rows', item: PREDICATE, one: true },
  texts: { k: 'rows', item: TEXT }, labels: { k: 'map', value: TEXT }, classmap: CLASSMAP,
};
function kindOf(decl) {
  if (decl.choices) return { k: 'text', choices: decl.choices };
  return KINDS[decl.kind] || null;
}
/* the record of a block from the keys a writer declares: [{key, kind, help, choices?}] */
function recordOf(decls) { return { k: 'record', fields: (decls || []).map(d => ({ key: d.key, kind: kindOf(d) || TEXT, help: d.help || '' })) }; }

/* the form of a rule of the rules file (docpipe/rules.py): map, table and range, by what the rule says it is */
function ruleSpec(rule) {
  if (rule.kind === 'range') return BOUNDS;
  if (rule.kind === 'table') return { k: 'rows', item: { k: 'record', fields: (rule.columns || []).map(c => f(c, KEPT)) } };
  if (rule.kind === 'map') {
    const value = rule.of === 'texts' ? { k: 'rows', item: TEXT } : rule.of === 'whole' ? { k: 'number' } : KEPT;
    return { k: 'map', value };
  }
  return null;
}

/* the example of a parameter: its source and rows; columns are value, quote and the coordinates (and their wordings) */
function exampleSpec(columns, defaultKeys, numeric) {
  const cells = columns.map(c => f(c, c === 'value' && numeric ? { k: 'number' } : { k: 'text', auto: true }));
  return { k: 'record', fields: [f('source', { k: 'text', area: true }),
    f('defaults', { k: 'record', fields: defaultKeys.map(c => f(c, { k: 'text', auto: true })) }),
    f('tuples', { k: 'rows', item: { k: 'record', fields: cells } })] };
}
/* the columns an example table shows: value, quote, every coordinate and wording some row (or the defaults) uses, in that order */
function exampleColumns(coordinates, example) {
  const used = new Set();
  for (const t of (example && Array.isArray(example.tuples) ? example.tuples : [])) if (isObj(t)) Object.keys(t).forEach(k => used.add(k));
  const cols = ['value', 'quote'];
  for (const c of coordinates || []) for (const k of [c, c + '_raw']) if (used.has(k) && !cols.includes(k)) cols.push(k);
  for (const k of ['unit', 'unit_raw']) if (used.has(k) && !cols.includes(k)) cols.push(k);
  return cols;
}
function exampleOffers(coordinates) {
  const out = ['value', 'quote'];
  for (const c of coordinates || []) out.push(c, c + '_raw');
  out.push('unit', 'unit_raw');
  return out;
}
function defaultKeysOf(coordinates, example) {
  const keys = [];
  const d = example && isObj(example.defaults) ? example.defaults : {};
  for (const k of Object.keys(d)) keys.push(k);
  for (const c of coordinates || []) for (const k of [c, c + '_raw']) if (!keys.includes(k)) keys.push(k);
  for (const k of ['unit', 'unit_raw']) if (!keys.includes(k)) keys.push(k);
  return keys;
}

/* ---------- value -> state ---------- */

function fits(spec, v) {
  switch (spec.k) {
    case 'text': return typeof v === 'string' || v === null || (spec.auto && typeof v === 'number');
    case 'number': return (typeof v === 'number' && Number.isFinite(v)) || v === null;
    case 'bool': return typeof v === 'boolean';
    case 'record': return isObj(v);
    case 'rows': return Array.isArray(v) || (spec.one && isObj(v));
    case 'map': return isObj(v);
    case 'bounds': return v === null || (Array.isArray(v) && v.length === 2 && v.every(x => x === null || Number.isInteger(x)));
  }
  return false;
}

function stateOf(spec, value) {
  if (value !== undefined && !fits(spec, value)) return { odd: true, raw: clone(value) };
  const orig = clone(value);
  switch (spec.k) {
    case 'text': case 'number': case 'bool': return { v: orig, spec };
    case 'record': {
      const st = { spec, orig, touched: false, order: [], cells: {}, extra: {} };
      for (const key of Object.keys(value || {})) {
        st.order.push(key);
        const fld = spec.fields.find(x => x.key === key);
        if (fld) st.cells[key] = stateOf(fld.kind, value[key]); else st.extra[key] = clone(value[key]);
      }
      for (const fld of spec.fields) if (!own(st.cells, fld.key)) st.cells[fld.key] = stateOf(fld.kind, undefined);
      return st;
    }
    case 'rows': {
      const asList = Array.isArray(value) || value === undefined;
      const list = value === undefined ? [] : asList ? value : [value];
      return { spec, orig, touched: false, asList, rows: list.map(x => stateOf(spec.item, x)) };
    }
    case 'bounds': return { spec, orig, lo: Array.isArray(value) ? value[0] : undefined, hi: Array.isArray(value) ? value[1] : undefined };
    case 'map': {
      const keys = Object.keys(value || {});
      return { spec, orig, touched: false, pairs: keys.map(k => ({ key: k, state: stateOf(spec.value, value[k]) })) };
    }
  }
  return { odd: true, raw: clone(value) };
}

/* ---------- state -> value ---------- */

function valueOf(st) {
  if (st.odd) return clone(st.raw);
  const spec = st.spec;
  switch (spec.k) {
    case 'text': case 'number': case 'bool': return st.v === undefined ? undefined : st.v;
    case 'record': {
      const out = {};
      for (const key of st.order) {
        const v = own(st.cells, key) ? valueOf(st.cells[key]) : clone(st.extra[key]);
        if (v !== undefined) out[key] = v;
      }
      if (!Object.keys(out).length) return (st.orig !== undefined && isEmpty(st.orig) && !st.touched) ? {} : undefined;
      return out;
    }
    case 'rows': {
      const vs = st.rows.map(valueOf).filter(v => v !== undefined);
      if (!vs.length) return (st.orig !== undefined && isEmpty(st.orig) && !st.touched) ? clone(st.orig) : undefined;
      return !st.asList && vs.length === 1 ? vs[0] : vs;
    }
    case 'bounds': return st.lo === undefined && st.hi === undefined ? null : [st.lo === undefined ? null : st.lo, st.hi === undefined ? null : st.hi];
    case 'map': {
      const out = {};
      for (const p of st.pairs) { const v = valueOf(p.state); if (p.key !== '' && v !== undefined) out[p.key] = v; }
      if (!Object.keys(out).length) return (st.orig !== undefined && isEmpty(st.orig) && !st.touched) ? {} : undefined;
      return out;
    }
  }
  return undefined;
}

/* ---------- edits ---------- */

/* the text a leaf shows */
function textOf(st) { return st.v == null ? '' : String(st.v); }
/* a typed text into a leaf: '' removes the key; a number leaf, or one that held a number, takes a number where the text is one */
function setText(st, text) {
  const spec = st.spec;
  if (text === '') { st.v = spec.keep ? '' : undefined; return st; }
  if (spec.k === 'number' || (spec.auto && typeof st.v === 'number')) {
    const n = Number(text);
    st.v = Number.isFinite(n) && String(n) === text.trim() ? n : (spec.k === 'number' ? (Number.isFinite(n) ? n : st.v) : text);
  } else st.v = text;
  return st;
}
function setBool(st, on) { st.v = !!on; return st; }
/* Every edit names its field by a path from the root state: a record key, a row index, or a map's pair index and then 'key' or
   'value'. The containers on the way note they were touched, and a record puts a key that gets its first value at the end. */
function walk(root, path) {
  const chain = [];
  let cur = root;
  for (let i = 0; i < path.length; i++) {
    const p = path[i];
    if (cur.odd) throw new Error('no field at ' + path.join('.'));
    chain.push({ node: cur, p });
    if (cur.spec.k === 'bounds') return { chain, node: cur };
    if (cur.spec.k === 'record') cur = cur.cells[p];
    else if (cur.spec.k === 'rows') cur = cur.rows[p];
    else if (cur.spec.k === 'map') {
      const pair = cur.pairs[p], part = path[++i];
      if (part === 'key') return { chain, node: pair, pair };
      cur = pair.state;
    } else throw new Error('no field at ' + path.join('.'));
    if (cur === undefined) throw new Error('no field at ' + path.join('.'));
  }
  return { chain, node: cur };
}
function settle(chain) {
  for (const { node, p } of chain.slice().reverse()) {   // the leaf's own record first, its parent then sees a value
    node.touched = true;
    if (node.spec.k === 'record' && !node.order.includes(p) && valueOf(node.cells[p]) !== undefined) node.order.push(p);
  }
}
/* a typed text (or a checkbox) into the field at path */
function edit(root, path, text) {
  const w = walk(root, path);
  if (w.node && w.node.spec && w.node.spec.k === 'bounds') {
    const n = text === '' ? undefined : Number(text);
    if (n === undefined || Number.isInteger(n)) w.node[path[path.length - 1] === 'hi' ? 'hi' : 'lo'] = n;
    return root;
  }
  if (w.pair) w.pair.key = text;
  else if (typeof text === 'boolean') setBool(w.node, text);
  else setText(w.node, text);
  settle(w.chain);
  return root;
}
function blankValue(spec) {
  if (spec.k === 'record') { const o = {}; for (const fld of spec.fields) if (fld.kind.keep) o[fld.key] = ''; return o; }
  if (spec.k === 'map') return {};
  if (spec.k === 'rows') return [];
  return spec.keep ? '' : undefined;
}
function blank(spec) { const st = stateOf(spec, blankValue(spec)); if (st.touched !== undefined) st.touched = true; return st; }
function addRow(root, path) {
  const w = walk(root, path), rows = w.node;
  rows.asList = true;
  rows.rows.push(blank(rows.spec.item));
  settle(w.chain); rows.touched = true; settle([{ node: rows, p: null }]);
  return rows.rows.length - 1;
}
function removeRow(root, path, i) { const w = walk(root, path); w.node.rows.splice(i, 1); w.node.touched = true; settle(w.chain); }
function moveRow(root, path, i, d) {
  const w = walk(root, path), rows = w.node.rows, j = i + d;
  if (j < 0 || j >= rows.length) return;
  [rows[i], rows[j]] = [rows[j], rows[i]]; w.node.touched = true; settle(w.chain);
}
function addPair(root, path) {
  const w = walk(root, path), map = w.node;
  const pair = { key: '', state: blank(map.spec.value) };
  map.pairs.push(pair); map.touched = true; settle(w.chain);
  return map.pairs.length - 1;
}
function removePair(root, path, i) { const w = walk(root, path); w.node.pairs.splice(i, 1); w.node.touched = true; settle(w.chain); }

/* ---------- walking, for the tests and for a page that lists every field ---------- */

/* every field a form shows: {path, vpath, text, kind}; path walks the state (record key, row index, map index then 'key' or 'value'),
   vpath the value it changes */
function leaves(st, path, vpath) {
  path = path || []; vpath = vpath || [];
  if (st.odd) return [];
  const spec = st.spec, out = [];
  switch (spec.k) {
    case 'text': case 'number': return [{ path, vpath, text: textOf(st), kind: spec.k }];
    case 'bool': return [];
    case 'bounds': return [{ path: path.concat(['lo']), vpath: vpath.concat([0]), text: st.lo === undefined ? '' : String(st.lo), kind: 'int' },
      { path: path.concat(['hi']), vpath: vpath.concat([1]), text: st.hi === undefined ? '' : String(st.hi), kind: 'int' }];
    case 'record':
      for (const fld of spec.fields) out.push(...leaves(st.cells[fld.key], path.concat([fld.key]), vpath.concat([fld.key])));
      return out;
    case 'rows':
      st.rows.forEach((r, i) => out.push(...leaves(r, path.concat([i]), st.asList ? vpath.concat([i]) : vpath)));
      return out;
    case 'map':
      st.pairs.forEach((p, i) => {
        out.push({ path: path.concat([i, 'key']), vpath: vpath.concat([p.key]), text: p.key, kind: 'key' });
        out.push(...leaves(p.state, path.concat([i, 'value']), vpath.concat([p.key])));
      });
      return out;
  }
  return out;
}
const api = { own, isObj, clone, KINDS, kindOf, recordOf, ruleSpec, exampleSpec, exampleColumns, exampleOffers, defaultKeysOf, fits,
  stateOf, valueOf, textOf, setText, setBool, walk, edit, addRow, removeRow, moveRow, addPair, removePair, leaves, TEXT, PREDICATE, LINK, SLOT, CLASSMAP };
if (typeof module !== 'undefined') module.exports = api; else root.DPForms = api;
})(typeof window !== 'undefined' ? window : globalThis);
