// Driver of tests/test_editor_untangle.py: runs the crossing reduction of the editor (docpipe/editor/ui/src/lib/untangle.ts,
// as it stands, its types stripped by node) on the jobs it reads from stdin (a JSON list) and writes the answers as a JSON
// list. `broken` names a deliberate defect the test uses to show that its checks can fail.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const U = await import(join(here, '..', 'docpipe', 'editor', 'ui', 'src', 'lib', 'untangle.ts').replace(/\\/g, '/').replace(/^([A-Za-z]):/, 'file:///$1:'));

// An input that breaks the counting on purpose.
function spoilCount(kind, input) {
  const out = JSON.parse(JSON.stringify(input));
  if (kind === 'ignore_ports') out.edges = out.edges.map(e => ({ ...e, fromY: 0, toY: 0 }));
  if (kind === 'drop_skipping') {
    const col = new Map();
    out.columns.forEach((c, i) => c.forEach(n => col.set(n.id, i)));
    out.edges = out.edges.filter(e => Math.abs(col.get(e.from) - col.get(e.to)) <= 1);
  }
  return out;
}

const jobs = JSON.parse(readFileSync(0, 'utf8'));
const answers = jobs.map(job => {
  if (job.op === 'count') return { n: U.countCrossings(spoilCount(job.broken, job.input)) };
  if (job.op === 'untangle') {
    let input = job.input, options = { ...(job.options || {}) };
    if (job.broken === 'ignore_groups') input = { ...input, columns: input.columns.map(c => c.map(n => ({ id: n.id, height: n.height }))) };
    if (job.broken === 'no_best') options.keepBest = false;
    const r = U.untangle(input, options);
    if (job.broken === 'reverse') r.columns = r.columns.map(c => [...c].reverse());
    return r;
  }
  throw new Error('no op ' + job.op);
});
process.stdout.write(JSON.stringify(answers));
