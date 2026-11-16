/* What a block of the Graph tab, or one step of its steps, is in another form (graph/blocks.tsx). The switch only shows
   it: nothing is stored until something is edited there. A brick shows as its own Python together with what makes that
   code do what the brick does: its settings, how often it is called and what it writes. Pure, so that node runs it in
   tests/test_editor_graph_forms.py. */

export type Obj = Record<string, any>;
/* a brick as the server sends it, with its own logic as Python (graphpage.bricks_of) */
export interface FormBrick { name: string; kind: string; per?: string; writes?: string; python?: string }

/* which form a block has */
export const formOf = (ref: unknown): 'brick' | 'if' | 'steps' | 'python' | '' => {
  if (typeof ref === 'string') return 'brick';
  if (!ref || typeof ref !== 'object') return '';
  const r = ref as Obj;
  if ('if' in r) return 'if';
  if ('steps' in r) return 'steps';
  if ('python' in r) return 'python';
  return 'brick' in r ? 'brick' : '';
};

/* the Python a new step starts with: it passes on what it was given */
export const STEP_PYTHON = 'def run(call):\n    return call.value\n';

/* the brick a block or a step names, by its name alone or as {brick} */
export function brickNamed(ref: unknown, bricks: FormBrick[]): FormBrick | undefined {
  if (formOf(ref) !== 'brick') return undefined;
  const name = typeof ref === 'string' ? ref : (ref as Obj).brick;
  return bricks.find(b => b.name === name);
}

/* a brick as Python that does what it does, null where the server sent no code for it */
export function brickAsPython(ref: unknown, bricks: FormBrick[]): Obj | null {
  const brick = brickNamed(ref, bricks);
  if (!brick || !brick.python) return null;
  const own: Obj = { python: brick.python };
  const settings = ref && typeof ref === 'object' ? (ref as Obj).settings : undefined;
  if (settings && typeof settings === 'object' && Object.keys(settings).length) own.settings = settings;
  if (brick.per && brick.per !== 'row') own.per = brick.per;
  if (brick.writes) own.writes = brick.writes;
  return own;
}

/* one step of steps as it is shown in a form: in its own form as it is; a brick in Python as its own logic (a new step
   where the server sent none); Python as a brick not yet chosen */
export function stepIn(step: unknown, form: 'brick' | 'python', bricks: FormBrick[]): Obj {
  const was: Obj = typeof step === 'string' ? { brick: step } : step && typeof step === 'object' ? step as Obj : {};
  if (form === (formOf(was) === 'python' ? 'python' : 'brick')) return was;
  if (form === 'python') return brickAsPython(was, bricks) || { python: STEP_PYTHON };
  return { brick: '' };
}
