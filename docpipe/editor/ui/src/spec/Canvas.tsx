/* A field as a drawing: the ontology it draws its lists from on the left, the field and what it asks of each value in the
   middle, the entries of the dimension chosen with the words of the plans on the right (layout.ts, nodes.tsx). Clicking a
   box edits it on the right; a box can be dragged elsewhere; "Untangle arrows" orders the left column so that fewer arrows
   cross. */
import { useEffect, useReducer, useRef } from 'react';
import { Background, Controls, getNodesBounds, MarkerType, ReactFlow, useReactFlow, type Node, type NodeChange } from '@xyflow/react';
import { Box } from '@mantine/core';
import { showInfo } from '../lib/dialogs';
import { t, useLang } from '../lib/i18n';
import { shownNodes, takeMoves } from '../lib/moved';
import { useStore } from '../lib/nav';
import { untangle } from '../lib/untangle';
import { termOf } from './model';
import { layoutField, type Placed } from './layout';
import { EDGE_TYPES, NODE_TYPES } from './nodes';
import { meta, S, select, toggleOpen, touch, view } from './state';
import '../graph/graph.css';

const edgeDefaults = { markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 } };
const flowWords = () => ({
  'node.a11yDescription.default': t('Press Enter or Space to choose this and Escape to cancel.'),
  'node.a11yDescription.keyboardDisabled': t('Press Enter or Space to choose this and Escape to cancel.'),
  'edge.a11yDescription.default': t('Press Enter or Space to choose this arrow and Escape to cancel.'),
  'controls.ariaLabel': t('View of the drawing'),
  'controls.zoomIn.ariaLabel': t('Zoom in'),
  'controls.zoomOut.ariaLabel': t('Zoom out'),
  'controls.fitView.ariaLabel': t('Show the whole drawing'),
  'minimap.ariaLabel': t('Overview of the drawing'),
  'handle.ariaLabel': t('End of an arrow'),
});

/* whether the ontology has an entry: the snapshot carries it, or a list of the sources holds it */
const inOntology = (id: string) => !!S.pin[id] || Object.values(S.onto.sets).some(s => s.members.includes(termOf(id)));

/* what is selected, as the drawing marks it */
function marked(): string | null {
  const n = S.sel;
  if (n.t === 'param') return 'field';
  if (n.t === 'units') return 'units';
  if (n.t === 'axis') return 'row:' + n.name;
  if (n.t === 'entry') return 'e:' + n.id;
  if (n.t === 'root') return 'root:' + n.set;
  return null;
}

export function placedField(uri: string): Placed {
  return layoutField({
    data: S.data, uri, onto: S.onto, pick: S.pick[uri] || null, open: S.open, kept: S.kept[uri] || null, inOntology,
    selected: marked(),
  });
}

/* the order of the left column with the fewest crossing arrows, kept until the page is loaded again */
export function untangleField(uri: string) {
  const placed = placedField(uri);
  const field = placed.nodes.find(n => n.id === 'field');
  if (!field) return;
  const r = untangle({
    columns: [placed.left.map(b => ({ id: b.id, height: b.height })), [{ id: 'field', height: field.height || 0 }]],
    edges: placed.arrows.map(a => ({ from: a.from, fromY: a.fromY, to: a.to, toY: a.toY })),
  });
  S.kept[uri] = r.columns[0];
  /* the boxes stand where the untangled layout puts them, the ones moved by hand too */
  delete S.moved[uri];
  showInfo(t('Crossings: {before} → {after}', { before: r.before, after: r.after }));
  touch();
}

export function FieldCanvas({ uri }: { uri: string }) {
  useStore(view);
  useStore(meta);
  useLang();
  const flow = useReactFlow();
  const placed = placedField(uri);
  /* a box dragged elsewhere stays there (lib/moved); only this drawing is drawn again while it moves */
  const [, redraw] = useReducer((x: number) => x + 1, 0);
  const moved = S.moved[uri] || (S.moved[uri] = new Map());
  const nodes = shownNodes(placed.nodes, moved);
  const onNodesChange = (changes: NodeChange[]) => { if (takeMoves(changes, nodes, moved)) redraw(); };
  /* after a field is chosen, the drawing as wide as the canvas, read from the top */
  const canvas = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = setTimeout(() => {
      const el = canvas.current;
      const boxes = nodes.filter(n => n.type !== 'label');
      if (!el || !boxes.length) return;
      const b = getNodesBounds(boxes);
      const pad = 24;
      const zoom = Math.min(1, Math.max(0.3, (el.clientWidth - 2 * pad) / Math.max(1, b.width)));
      flow.setViewport({ x: pad - b.x * zoom, y: pad - b.y * zoom + 8, zoom });
    }, 60);
    return () => clearTimeout(h);
  }, [S.fit, uri]); // eslint-disable-line react-hooks/exhaustive-deps
  const click = (_: unknown, n: Node) => { if (n.type === 'more') toggleOpen(); };
  return (
    <Box ref={canvas} className="sp-canvas gr-canvas" style={{ flex: 1, minHeight: 0, minWidth: 0, position: 'relative' }}>
      <ReactFlow nodes={nodes} edges={placed.edges} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES} defaultEdgeOptions={edgeDefaults}
        nodesDraggable onNodesChange={onNodesChange} nodesConnectable={false} elementsSelectable={false} onNodeClick={click} ariaLabelConfig={flowWords()}
        onPaneClick={() => select({ t: 'param', uri })} minZoom={0.15} maxZoom={1.6} proOptions={{ hideAttribution: true }}>
        <Background gap={24} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </Box>
  );
}
