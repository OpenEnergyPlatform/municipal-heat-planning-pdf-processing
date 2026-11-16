// Driver of tests/test_editor_graph_forms.py: shows a step of the Graph tab in a form with the page's own module
// (docpipe/editor/ui/src/graph/forms.ts, as it stands, its types stripped by node) for the jobs it reads from stdin (a JSON
// list) and writes the answers as a JSON list. `broken` names a deliberate defect the test uses to show that its checks
// can fail.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const F = await import(join(here, '..', 'docpipe', 'editor', 'ui', 'src', 'graph', 'forms.ts').replace(/\\/g, '/').replace(/^([A-Za-z]):/, 'file:///$1:'));

function shown(step, form, bricks, broken) {
  if (broken === 'mutate' && step && typeof step === 'object') step.python = 'def run(call):\n    return None\n';
  if (broken === 'always_new') return form === 'python' ? { python: F.STEP_PYTHON } : { brick: '' };
  if (broken === 'keeps_code' && form === 'brick' && step && typeof step === 'object') return { ...step, brick: '' };
  if (broken === 'name_alone_unknown' && typeof step === 'string') step = {};
  let out = F.stepIn(step, form, bricks);
  if (form === 'python') {
    out = { ...out };
    if (broken === 'no_settings') delete out.settings;
    if (broken === 'no_per') delete out.per;
    if (broken === 'no_writes') delete out.writes;
    if (broken === 'no_new_step' && out.python === F.STEP_PYTHON) out = {};
  }
  return out;
}

const jobs = JSON.parse(readFileSync(0, 'utf8'));
const answers = jobs.map(job => {
  if (job.op === 'shown') {
    const out = shown(job.step, job.form, job.bricks, job.broken);
    return { out, step: job.step, form: F.formOf(out) };
  }
  throw new Error('no op ' + job.op);
});
process.stdout.write(JSON.stringify(answers));
