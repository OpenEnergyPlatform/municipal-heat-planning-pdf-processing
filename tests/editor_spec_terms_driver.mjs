// Driver of tests/test_editor_spec_terms.py: lists the terms of a list of the ontology, the lists of the spec they are held
// against and the terms put into such a list with the page's own modules (docpipe/editor/ui/src/spec/terms.ts and
// layout.ts, as they stand, their types stripped by node) for the jobs it reads from stdin (a JSON list) and writes the
// answers as a JSON list. `broken` names a deliberate defect the test uses to show that its checks can fail.
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
const T = await import(pathToFileURL(join(SRC, 'spec', 'terms.ts')).href);
const M = await import(pathToFileURL(join(SRC, 'spec', 'model.ts')).href);
const L = await import(pathToFileURL(join(SRC, 'spec', 'layout.ts')).href);

/* the terms as the panel lists them */
function rows(job) {
  let out = T.termRows(job.set, job.terms, job.list);
  if (job.broken === 'flat') out = out.map(r => ({ ...r, depth: 0 }));          // every term right under the root
  if (job.broken === 'drop') out = out.slice(0, -1);                            // a term left out
  if (job.broken === 'exact') {                                                 // held only under its bare identifier
    const list = job.list || {};
    out = out.map(r => ({ ...r, held: Object.prototype.hasOwnProperty.call(list, r.id) ? r.id : null }));
  }
  return out.map(r => ({ id: r.id, depth: r.depth, held: r.held }));
}

/* the lists of the spec a list of the ontology is held against, and the one chosen for where it was opened from */
function lists(job) {
  let out = T.listsFrom(job.data, job.onto, job.set);
  if (job.broken === 'shared_only') out = out.filter(w => w.uri == null);       // the fields' own lists left out
  const chosen = job.broken === 'first' ? (out[0] || null) : T.listChosen(out, job.at || null);
  return { lists: out, chosen };
}

/* the terms put into a list */
function put(job) {
  const before = JSON.stringify(job.list);
  let { list, added } = T.withTerms(job.list, job.set, job.ids, job.terms);
  if (job.broken === 'bare') {                                                  // every term put in under its bare id
    const out = {};
    for (const [k, v] of Object.entries(list)) {
      const a = added.find(x => x.key === k);
      out[a ? a.id : k] = v;
    }
    list = out;
    added = added.map(a => ({ key: a.id, id: a.id }));
  } else if (job.broken === 'at_end') {                                         // the new entries at the end of the list
    const out = {};
    for (const [k, v] of Object.entries(list)) if (!added.some(a => a.key === k)) out[k] = v;
    for (const a of added) out[a.key] = list[a.key];
    list = out;
  } else if (job.broken === 'twice') {                                          // a term put in again under another key
    const out = { ...list };
    for (const id of job.ids) if (!Object.prototype.hasOwnProperty.call(out, id)) { out[id] = T.entryOfTerm(job.terms[id], id); added = added.concat([{ key: id, id }]); }
    list = out;
  }
  return { list, keys: Object.keys(list), added, same: JSON.stringify(job.list) === before };
}

/* the boxes of the ontology in a field's drawing: the list of the first row each gives entries to */
function roots(job) {
  const pin = job.pin || {};
  const sets = Object.values((job.onto || {}).sets || {});
  const inOntology = id => !!pin[id] || sets.some(s => s.members.includes(M.termOf(id)));
  const placed = L.layoutField({ data: job.data, uri: job.uri, onto: job.onto, pick: null, open: false, kept: null, inOntology, selected: null });
  return placed.nodes.filter(n => n.type === 'root').map(n => {
    let at = n.data.at;
    if (job.broken === 'at_shared') at = { uri: null, name: n.data.feeds[0], key: 'vocabulary' };   // as if every row shared
    return { set: n.data.set, feeds: n.data.feeds, at };
  });
}

const jobs = JSON.parse(readFileSync(0, 'utf8'));
const answers = jobs.map(job => {
  if (job.op === 'rows') return rows(job);
  if (job.op === 'lists') return lists(job);
  if (job.op === 'put') return put(job);
  if (job.op === 'roots') return roots(job);
  throw new Error('no op ' + job.op);
});
process.stdout.write(JSON.stringify(answers));
