/* The first view of a drawing, the same for every tab that draws one (owner request 2026-11-19, A9): the whole drawing
   where it can be read whole, else its top at a size that can be read, scrolled with the wheel; and that view again
   whenever the canvas changes its size, until the view is moved by hand. */
import { useEffect, useRef, type RefObject } from 'react';
import type { Node, ReactFlowInstance } from '@xyflow/react';

/* below this zoom the words of a box are too small to read */
export const READABLE = 0.8;

export function readableView(flow: ReactFlowInstance<any, any>, el: HTMLElement | null, boxes: Node[], duration = 300): void {
  if (!el || !boxes.length) return;
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const b = flow.getNodesBounds(boxes);
  if (!b.width || !b.height) return;
  const whole = Math.min(W / (b.width * 1.12), H / (b.height * 1.12));
  if (whole >= READABLE) { flow.fitView({ nodes: boxes, padding: 0.06, maxZoom: 1, duration }); return; }
  const z = Math.max(READABLE, Math.min(1, W / (b.width + 80)));
  flow.setViewport({ x: (W - b.width * z) / 2 - b.x * z, y: 28 - b.y * z, zoom: z }, { duration });
}

/* The first view after each change of *fit* (a new drawing, a loaded file) and after every change of the canvas's size
   while the view was not moved by hand. *boxes* gives the boxes the view is about. Returns the handler of ReactFlow's
   onMoveStart: a move with an event is one by hand, one without is the page's own. */
export function useReadableView(flow: ReactFlowInstance<any, any>, canvas: RefObject<HTMLElement | null>,
  boxes: () => Node[], fit: unknown): (event: unknown) => void {
  const byHand = useRef(false);
  const latest = useRef(boxes);
  latest.current = boxes;
  useEffect(() => {
    if (fit === undefined || fit === null || fit === 0) return;
    byHand.current = false;
    const h = setTimeout(() => readableView(flow, canvas.current, latest.current()), 120);
    return () => clearTimeout(h);
  }, [fit]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = canvas.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let size = el.clientWidth + 'x' + el.clientHeight;
    const seen = new ResizeObserver(() => {
      const now = el.clientWidth + 'x' + el.clientHeight;
      if (now === size || byHand.current) { size = now; return; }
      size = now;
      clearTimeout(timer);
      timer = setTimeout(() => readableView(flow, el, latest.current(), 0), 150);
    });
    seen.observe(el);
    return () => { seen.disconnect(); clearTimeout(timer); };
  }, [canvas.current]); // eslint-disable-line react-hooks/exhaustive-deps
  return (event: unknown) => { if (event) byHand.current = true; };
}
