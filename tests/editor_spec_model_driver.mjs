// Driver of tests/test_editor_spec_model.py: runs what the Spec tab draws of a field and the edits it makes
// (docpipe/editor/ui/src/spec/model.ts and layout.ts, lib/untangle.ts and lib/moved.ts, as they stand, their types stripped by node) on
// the jobs it reads from stdin (a JSON list) and writes the answers as a JSON list. `broken` names a deliberate defect a
// test uses to show that its checks can fail.
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// the page's sources import each other without an extension, as the bundler takes them
registerHooks({
  resolve(specifier, context, next) {
    if (/^\.\.?\//.test(specifier) && !/\.[cm]?[jt]sx?$/.test(specifier)) {
      try { return next(specifier + '.ts', context); } catch { /* not a TypeScript file */ }
    }
    return next(specifier, context);
  },
});

const here = dirname(fileURLToPath(import.meta.url));
const SRC = join(here, '..', 'docpipe', 'editor', 'ui', 'src');
const M = await import(pathToFileURL(join(SRC, 'spec', 'model.ts')).href);
const L = await import(pathToFileURL(join(SRC, 'spec', 'layout.ts')).href);
const U = await import(pathToFileURL(join(SRC, 'lib', 'untangle.ts')).href);
const D = await import(pathToFileURL(join(SRC, 'lib', 'moved.ts')).href);

/* the drawing of a field as the page lays it out (spec/Canvas.tsx placedField) */
function place(job, kept) {
  const pin = job.pin || {};
  const sets = Object.values((job.onto || {}).sets || {});
  const inOntology = id => !!pin[id] || sets.some(s => s.members.includes(M.termOf(id)));
  if (job.broken === 'mutates') M.fieldOf(job.data, job.uri)._drawn = true;
  return L.layoutField({
    data: job.data, uri: job.uri, onto: job.onto, pick: job.pick || null, open: !!job.open,
    kept: job.broken === 'ignore_kept' ? null : kept, inOntology, selected: null,
  });
}

/* what a test reads of a drawing */
function shown(placed) {
  const nodes = placed.nodes.map(n => {
    const d = n.data || {};
    const out = { id: n.id, type: n.type, x: n.position.x, y: n.position.y };
    if (n.type === 'field') {
      out.pick = d.pick;
      out.rows = d.rows.map(r => ({
        name: r.name, kind: r.kind, shared: r.shared, specials: r.specials, count: r.count,
        derived: r.derived ? { value: r.derived.value, byUnit: r.derived.byUnit } : null,
        origin: r.origin ? { set: r.origin.set, under: r.origin.under, own: r.origin.own } : null,
      }));
    } else if (n.type === 'root') {
      out.set = d.set; out.feeds = d.feeds; out.under = d.origin.under;
    } else if (n.type === 'entry') {
      out.entry = d.entry.id; out.label = d.entry.label; out.words = d.entry.words; out.own = d.own; out.where = d.where;
    } else if (n.type === 'more') {
      out.count = d.count; out.open = d.open;
    } else if (n.type === 'frame') {
      out.name = d.name; out.count = d.count; out.shown = d.shown;
    }
    return out;
  });
  const edges = placed.edges.map(e => ({
    source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle,
    kind: e.data.kind, label: e.data.label,
  }));
  return { nodes, edges, left: placed.left.map(b => b.id) };
}

/* a drawing that breaks a promise on purpose */
function spoil(kind, d) {
  const field = d.nodes.find(n => n.type === 'field');
  if (kind === 'own_as_shared') {           // a dimension of the field's own drawn as a shared one
    const row = field.rows.find(r => !r.shared && r.kind !== 'unit');
    if (row) row.shared = true;
  } else if (kind === 'root_to_first') {    // every arrow of the ontology drawn from its first list
    const first = d.edges.find(e => e.kind === 'root');
    for (const e of d.edges) if (e.kind === 'root') e.source = first.source;
  } else if (kind === 'drop_entry') {       // an entry of the list left out
    const i = d.nodes.findIndex(n => n.type === 'entry');
    if (i >= 0) d.nodes.splice(i, 1);
  } else if (kind === 'drop_word') {        // a word of the plans left out of its entry
    const e = d.nodes.find(n => n.type === 'entry' && n.words.length);
    if (e) e.words = e.words.slice(0, -1);
  } else if (kind === 'no_derive') {        // what the unit decides not drawn
    d.edges = d.edges.filter(e => e.kind !== 'derive');
  }
  return d;
}

/* the crossings of a drawing's arrows between the column of the ontology and the field */
function crossings(placed) {
  const field = placed.nodes.find(n => n.id === 'field');
  return U.countCrossings({
    columns: [placed.left.map(b => ({ id: b.id, height: b.height })), [{ id: 'field', height: field.height || 0 }]],
    edges: placed.arrows,
  });
}

/* an edit that breaks a promise on purpose */
function spoiledEdit(job, data) {
  const a = job.args;
  if (job.broken === 'copy') {              // the word is put on the other entry and stays where it was
    return M.addWord(listOf(data, a.where), a.to, a.word);
  }
  if (job.broken === 'by_reference') {      // the field's "own copy" is the shared object itself
    const p = M.fieldOf(data, a.uri);
    p.axes[a.name] = data.shared_axes[a.name];
    return true;
  }
  if (job.broken === 'any_order') {         // an order taken as given
    data.coordinates.order = a.order.slice();
    return true;
  }
  if (job.broken === 'keep_other') {        // a mark that leaves the other one standing
    const c = data.coordinates;
    c[a.key] = (Array.isArray(c[a.key]) ? c[a.key] : []).concat([a.name]);
    return true;
  }
  throw new Error('no such defect: ' + job.broken);
}

function listOf(data, where) {
  const holder = where.uri ? M.axisOf(data, where.uri, where.name) : M.sharedOf(data)[where.name];
  return holder && holder[where.key || 'vocabulary'];
}

function edit(job) {
  const data = job.data;
  const a = job.args;
  let said;
  if (job.broken) said = spoiledEdit(job, data);
  else if (job.op === 'move') said = M.moveWord(listOf(data, a.where), a.from, a.word, a.to);
  else if (job.op === 'add') said = M.addWord(listOf(data, a.where), a.id, a.word);
  else if (job.op === 'remove') said = M.removeWord(listOf(data, a.where), a.id, a.word);
  else if (job.op === 'unshare') said = M.unshare(data, a.uri, a.name);
  else if (job.op === 'share') said = M.share(data, a.uri, a.name, !!a.replace);
  else if (job.op === 'give_shared') said = M.giveShared(data, a.uri, a.name);
  else if (job.op === 'order') said = M.setOrder(data, a.order);
  else if (job.op === 'special') said = M.setSpecial(data, a.name, a.key, a.on);
  else throw new Error('no such edit: ' + job.op);
  /* an edit through what the field now asks, after the edit (`then`): where it reaches */
  if (job.then) Object.assign(M.axisOf(data, job.then.uri, job.then.name), job.then.set);
  return { said, data };
}

/* the boxes as shown and the moves taken, as the page does them (lib/moved), or with a deliberate defect */
function shownOf(nodes, moved, broken) {
  if (broken === 'no_keep') return nodes;                      // a box dragged goes back to where the layout put it
  if (broken === 'mutate') {                                   // the places written into the layout's own boxes
    for (const n of nodes) { const at = moved.get(n.id); if (at) n.position = at; }
    return nodes;
  }
  return D.shownNodes(nodes, moved);
}
function takeOf(changes, shown, moved, broken) {
  if (broken === 'no_carry') {                                 // a box takes none of what it carries along
    return D.takeMoves(changes, shown.map(n => ({ ...n, data: { ...(n.data || {}), carries: [] } })), moved);
  }
  if (broken === 'move_all') {                                 // every box moves with the one dragged
    for (const c of changes) {
      const n = shown.find(m => m.id === c.id);
      if (c.type !== 'position' || !c.position || !n) continue;
      const dx = c.position.x - n.position.x, dy = c.position.y - n.position.y;
      for (const m of shown) moved.set(m.id, { x: m.position.x + dx, y: m.position.y + dy });
    }
    return true;
  }
  return D.takeMoves(changes, shown, moved);
}

/* boxes dragged by hand: the nodes given, or the drawing of a field; each drag a place for one box, or the changes the
   drawing reports */
function drag(job) {
  const nodes = job.nodes || place(job, null).nodes;
  const before = JSON.stringify(nodes.map(n => [n.id, n.position]));
  const moved = new Map();
  let shown = shownOf(nodes, moved, job.broken);
  const said = [];
  for (const step of job.drags) {
    const changes = step.changes || [{ type: 'position', id: step.id, position: { x: step.x, y: step.y }, dragging: true }];
    said.push(takeOf(changes, shown, moved, job.broken));
    shown = shownOf(nodes, moved, job.broken);
  }
  const at = list => list.map(n => ({ id: n.id, type: n.type, x: n.position.x, y: n.position.y, carries: (n.data && n.data.carries) || [] }));
  return { shown: at(shown), said, same: JSON.stringify(nodes.map(n => [n.id, n.position])) === before };
}

const jobs = JSON.parse(readFileSync(0, 'utf8'));
const answers = jobs.map(job => {
  if (job.op === 'layout') {
    const before = JSON.stringify(job.data);
    const d = shown(place(job, job.kept || null));
    return { drawing: job.broken && job.broken !== 'mutates' ? spoil(job.broken, d) : d, same: JSON.stringify(job.data) === before };
  }
  if (job.op === 'drag') return drag(job);
  if (job.op === 'untangle') {
    // as the page's button does (spec/Canvas.tsx untangleField): the order found, then the drawing laid out with it
    const first = place(job, null);
    const field = first.nodes.find(n => n.id === 'field');
    const r = U.untangle({
      columns: [first.left.map(b => ({ id: b.id, height: b.height })), [{ id: 'field', height: field.height || 0 }]],
      edges: first.arrows,
    });
    const again = place(job, r.columns[0]);
    return { before: r.before, after: r.after, order: r.columns[0], drawn: again.left.map(b => b.id), counted: crossings(again) };
  }
  return edit(job);
});
process.stdout.write(JSON.stringify(answers));
