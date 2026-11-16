// Driver of tests/test_editor_graph_demands.py: the rows of a box of the Graph tab and what the shapes demand of them, with
// the page's own module (docpipe/editor/ui/src/graph/rows.ts, as it stands, its types stripped by node), for the jobs it
// reads from stdin (a JSON list); writes the answers as a JSON list. A job's `loaded` is the drawing as the page loaded it,
// beside the edited one (`map`); `broken: "loaded"` takes the loaded drawing for the rows, the defect a test shows it finds.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const R = await import(pathToFileURL(join(here, '..', 'docpipe', 'editor', 'ui', 'src', 'graph', 'rows.ts')).href);

const jobs = JSON.parse(readFileSync(0, 'utf8'));
const answers = jobs.map(job => {
  if (job.op !== 'rows') throw new Error('no op ' + job.op);
  const box = job.map.boxes.find(b => b.id === job.box);
  const data = { classes: job.classes, map: job.loaded || job.map };
  const rows = R.rowsOf(data, job.broken === 'loaded' ? data.map : job.map, box);
  return {
    rows: Object.fromEntries(rows.map(r => [R.localName(r.curie), {
      label: r.label, required: r.required, demanded: R.demanded(r), red: R.isRed(r),
      groups: r.oneOf.map(g => ({ labels: g.labels, met: g.met })),
    }])),
    missing: R.missingOf(rows),
    red_rows: rows.filter(R.isRed).length,
  };
});
process.stdout.write(JSON.stringify(answers));
