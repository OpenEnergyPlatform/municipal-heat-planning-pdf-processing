/* Crossing reduction for a drawing in columns: boxes stand in columns, arrows run from a port (a height inside a box) of
   one column to a port of a later column. The order of the boxes in each column is what this module changes, so that fewer
   arrows cross. Pure: no runtime imports, so the page, the Graph tab, the Spec tab and the tests' node all run it.

   An arrow that skips columns is counted through one point in each column between (a node of no height), and those
   points are placed like the nodes while the sweeps run; the count of a result (and so the choice of the best) places them
   on the straight line between the ports. Crossings are counted by the heights of the ports with the nodes stacked in
   the order given, without gaps. Deterministic: the same input gives the same output, and the result never has more
   crossings than the order it was given. */

export interface UNode {
  id: string;
  /* the height the node takes in its column */
  height: number;
  /* nodes of one group in one column stay together; the groups keep the order they first stand in */
  group?: string;
}
export interface UEdge {
  from: string; fromY: number; to: string; toY: number;
}
export interface UInput { columns: UNode[][]; edges: UEdge[] }
export interface UOptions {
  /* sweeps per round (default 12) */
  passes?: number;
  /* false returns the last order tried instead of the best one */
  keepBest?: boolean;
}
export interface UResult { columns: string[][]; before: number; after: number }

interface Item { id: string; h: number; group: string | undefined; col: number; virtual: boolean }
interface Seg { a: number; ao: number; b: number; bo: number }
interface Net {
  items: Item[]; segs: Seg[]; gaps: number[][]; left: number[][]; right: number[][]; order: number[][]; rank: Map<string, number>[];
}

function build(input: UInput): Net {
  const items: Item[] = [];
  const where = new Map<string, number>();
  const init: number[][] = [];
  const top0: number[] = [];
  const rank: Map<string, number>[] = [];
  input.columns.forEach((col, c) => {
    let y = 0;
    const list: number[] = [];
    const ranks = new Map<string, number>();
    for (const n of col) {
      const i = items.length;
      const h = Math.max(0, n.height);
      items.push({ id: n.id, h, group: n.group, col: c, virtual: false });
      where.set(n.id, i);
      top0[i] = y; y += h;
      list.push(i);
      if (n.group !== undefined && !ranks.has(n.group)) ranks.set(n.group, ranks.size);
    }
    init.push(list); rank.push(ranks);
  });
  const segs: Seg[] = [];
  const virt: { i: number; y: number }[] = [];
  for (const e of input.edges) {
    let a = where.get(e.from), b = where.get(e.to);
    if (a === undefined || b === undefined) continue;
    let fy = e.fromY, ty = e.toY;
    if (items[a].col > items[b].col) { [a, b] = [b, a]; [fy, ty] = [ty, fy]; }
    const ca = items[a].col, cb = items[b].col;
    if (ca === cb) continue;
    const ya = top0[a] + fy, yb = top0[b] + ty;
    let prev = a, prevOff = fy;
    for (let k = ca + 1; k < cb; k++) {
      const v = items.length;
      items.push({ id: '~' + v, h: 0, group: undefined, col: k, virtual: true });
      virt.push({ i: v, y: ya + (yb - ya) * (k - ca) / (cb - ca) });
      segs.push({ a: prev, ao: prevOff, b: v, bo: 0 });
      prev = v; prevOff = 0;
    }
    segs.push({ a: prev, ao: prevOff, b, bo: ty });
  }
  /* the points of skipping arrows go where their line passes, between the real nodes */
  const key = new Map<number, number>();
  for (const v of virt) key.set(v.i, v.y);
  const order = init.map((list, c) => {
    for (const i of list) key.set(i, top0[i] + items[i].h / 2);
    const extra = virt.filter(v => items[v.i].col === c).map(v => v.i);
    return [...list, ...extra].sort((p, q) => key.get(p)! - key.get(q)!);
  });
  const gaps: number[][] = input.columns.map(() => []);
  const left: number[][] = items.map(() => []);
  const right: number[][] = items.map(() => []);
  segs.forEach((s, k) => { gaps[items[s.a].col].push(k); right[s.a].push(k); left[s.b].push(k); });
  return { items, segs, gaps, left, right, order, rank };
}

function retop(net: Net, tops: number[], c: number) {
  let y = 0;
  for (const i of net.order[c]) { tops[i] = y; y += net.items[i].h; }
}
function retopAll(net: Net, tops: number[]) { net.order.forEach((_, c) => retop(net, tops, c)); }

function count(net: Net, tops: number[]): number {
  let n = 0;
  for (const gap of net.gaps) {
    const ys = gap.map(k => tops[net.segs[k].a] + net.segs[k].ao);
    const zs = gap.map(k => tops[net.segs[k].b] + net.segs[k].bo);
    for (let i = 0; i < gap.length; i++) {
      for (let j = i + 1; j < gap.length; j++) if ((ys[i] - ys[j]) * (zs[i] - zs[j]) < 0) n++;
    }
  }
  return n;
}

const mean = (v: number[]) => v.reduce((s, x) => s + x, 0) / v.length;
function median(v: number[]): number {
  const s = [...v].sort((p, q) => p - q), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/* order column c by where its neighbours on one side lead to; groups stay whole and in their order */
function place(net: Net, tops: number[], c: number, side: 'left' | 'right', useMedian: boolean) {
  const col = net.order[c];
  const lists = side === 'left' ? net.left : net.right;
  const want = new Map<number, number>();
  for (const i of col) {
    const vals = lists[i].map(k => {
      const s = net.segs[k];
      return side === 'left' ? tops[s.a] + s.ao - s.bo : tops[s.b] + s.bo - s.ao;
    });
    want.set(i, vals.length ? (useMedian ? median(vals) : mean(vals)) : tops[i]);
  }
  interface Unit { items: number[]; key: number; group: string | undefined; at: number }
  const units: Unit[] = [];
  const byGroup = new Map<string, Unit>();
  for (const i of col) {
    const g = net.items[i].group;
    if (g === undefined) { units.push({ items: [i], key: 0, group: undefined, at: units.length }); continue; }
    let u = byGroup.get(g);
    if (!u) { u = { items: [], key: 0, group: g, at: units.length }; byGroup.set(g, u); units.push(u); }
    u.items.push(i);
  }
  for (const u of units) {
    u.items.sort((p, q) => want.get(p)! - want.get(q)!);
    u.key = mean(u.items.map(i => want.get(i)!));
  }
  const sorted = [...units].sort((p, q) => (p.key === q.key ? p.at - q.at : p.key - q.key));
  /* the places that blocks take are filled by the blocks in their own order */
  const blocks = sorted.filter(u => u.group !== undefined).sort((p, q) => net.rank[c].get(p.group!)! - net.rank[c].get(q.group!)!);
  let next = 0;
  const result: number[] = [];
  for (const u of sorted) result.push(...(u.group !== undefined ? blocks[next++] : u).items);
  net.order[c] = result;
  retop(net, tops, c);
}

/* the change in crossings if u (just above v in column c) and v swap places */
function swapDelta(net: Net, tops: number[], u: number, v: number): number {
  const hu = net.items[u].h, hv = net.items[v].h, base = tops[u];
  let before = 0, after = 0;
  for (const lists of [net.left, net.right]) {
    for (const su of lists[u]) {
      for (const sv of lists[v]) {
        const a = net.segs[su], b = net.segs[sv];
        const left = lists === net.left;
        const ou = left ? a.bo : a.ao, ov = left ? b.bo : b.ao;
        const yu = left ? tops[a.a] + a.ao : tops[a.b] + a.bo, yv = left ? tops[b.a] + b.ao : tops[b.b] + b.bo;
        if ((base + ou - (base + hu + ov)) * (yu - yv) < 0) before++;
        if ((base + hv + ou - (base + ov)) * (yu - yv) < 0) after++;
      }
    }
  }
  return after - before;
}

/* swaps of neighbours that lower the count, until none does */
function refine(net: Net, tops: number[]) {
  for (let round = 0; round < 50; round++) {
    let moved = false;
    net.order.forEach(col => {
      for (let k = 0; k + 1 < col.length; k++) {
        const u = col[k], v = col[k + 1];
        if (net.items[u].group !== net.items[v].group) continue;
        if (swapDelta(net, tops, u, v) >= 0) continue;
        const base = tops[u];
        col[k] = v; col[k + 1] = u;
        tops[v] = base; tops[u] = base + net.items[v].h;
        moved = true;
      }
    });
    if (!moved) break;
  }
}

const copy = (order: number[][]) => order.map(c => c.slice());

/* the crossings of the drawing as given */
export function countCrossings(input: UInput): number {
  const net = build(input);
  const tops = new Array<number>(net.items.length).fill(0);
  retopAll(net, tops);
  return count(net, tops);
}

const realOrder = (net: Net): string[][] => net.order.map(col => col.filter(i => !net.items[i].virtual).map(i => net.items[i].id));

/* the count of a result: its real order with the points of skipping arrows on their lines */
function score(input: UInput, columns: string[][]): number {
  const by = new Map<string, UNode>();
  for (const col of input.columns) for (const n of col) by.set(n.id, n);
  return countCrossings({ columns: columns.map(col => col.map(id => by.get(id)!)), edges: input.edges });
}

/* a new order of every column with as few crossings as the sweeps and swaps find, never more than the order given */
export function untangle(input: UInput, options: UOptions = {}): UResult {
  const net = build(input);
  const tops = new Array<number>(net.items.length).fill(0);
  retopAll(net, tops);
  const before = count(net, tops);
  let best = { order: copy(net.order), columns: realOrder(net), n: before };
  const passes = options.passes ?? 12;
  const consider = () => {
    const columns = realOrder(net);
    const n = score(input, columns);
    if (n >= best.n) return false;
    best = { order: copy(net.order), columns, n };
    return true;
  };
  let improved = true;
  for (let round = 0; round < 6 && improved; round++) {
    improved = false;
    net.order = copy(best.order); retopAll(net, tops);
    for (let pass = 0; pass < passes; pass++) {
      const useMedian = pass % 2 === 1;
      for (let c = 1; c < net.order.length; c++) place(net, tops, c, 'left', useMedian);
      for (let c = net.order.length - 2; c >= 0; c--) place(net, tops, c, 'right', useMedian);
      if (consider()) improved = true;
    }
    if (options.keepBest === false) break;
    net.order = copy(best.order); retopAll(net, tops);
    refine(net, tops);
    if (consider()) improved = true;
  }
  if (options.keepBest === false) { const columns = realOrder(net); return { columns, before, after: score(input, columns) }; }
  return { columns: best.columns, before, after: best.n };
}
