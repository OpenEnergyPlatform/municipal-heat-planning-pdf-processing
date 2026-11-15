/* The tree on the left: the library to drag from (owner request 2026-11-14, wish 4b: "Bibliothek wie im Ablauf"), the
   top-level questions, the value types, the document's plan fields and works, the groups, the fields with their list and
   coordinates under them. A block of the library is dragged onto the field it goes into, or clicked to go into the
   field selected. */
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react';
import { IconChevronDown, IconChevronRight, IconGripVertical, IconPlus } from '@tabler/icons-react';
import { showError } from '../lib/dialogs';
import { useStore } from '../lib/nav';
import { t, tn, tr } from '../lib/i18n';
import { isObj, own, type Obj } from '../lib/util';
import type { SpecNode } from '../lib/spec';
import {
  addAxis, addCheck, addField, addOwnPlanField, addPlanField, addUnit, addValueType, addWorks, listCount, nodeKey, S, select,
  touch, view,
} from './state';

const PLAN_KEYS = ['settings', 'base_year', 'target_year'];

function kindLabel(ax: Obj): string {
  if (own(ax, 'vocabulary')) return t('list · {n} entries', { n: listCount(ax.vocabulary) });
  if (own(ax, 'type')) return String(ax.type);
  if (own(ax, 'enum')) return t('strings');
  if (own(ax, 'dynamic')) return t('per document');
  return t('no kind');
}

/* a block of the library: what it is and what it puts in */
interface Block { what: 'field' | 'dimension' | 'unit' | 'check' | 'vtype' | 'plan'; kind?: string; label: string }
const DRAG = 'application/x-docpipe-spec-block';

/* the field a block goes into: the one dropped on, else the one selected (a dimension's or a list's field) */
const fieldOf = (n: SpecNode | null): string | null => (n && 'uri' in n ? n.uri : null);

function putIn(b: Block, at: SpecNode | null) {
  const uri = fieldOf(at);
  if (b.what === 'field') { void addField(b.kind!, uri || undefined); return; }
  if (b.what === 'vtype') { void addValueType(); return; }
  if (b.what === 'plan') { void addOwnPlanField(b.kind!); return; }
  if (!uri) { showError(new Error(t('Drop it on a field, or select a field first.'))); return; }
  if (b.what === 'dimension') void addAxis(uri, b.kind!);
  else if (b.what === 'unit') void addUnit(uri);
  else if (b.what === 'check') addCheck(uri);
}
function onDropAt(n: SpecNode | null) {
  return {
    onDragOver: (ev: DragEvent) => { if (ev.dataTransfer.types.includes(DRAG)) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; } },
    onDrop: (ev: DragEvent) => {
      const raw = ev.dataTransfer.getData(DRAG);
      if (!raw) return;
      ev.preventDefault();
      putIn(JSON.parse(raw) as Block, n);
    },
  };
}

const DIMENSION_WORDS = (): Record<string, string> => ({
  list: t('Dimension: a list of entries'), year: t('Dimension: a year'), words: t('Dimension: the words of the document'),
  per_document: t('Dimension: a list per document'),
});

/* the library: drag a block onto the tree, or click it to put it into the field selected */
function Library() {
  const [open, setOpen] = useState(true);
  const blocks: Block[] = [
    ...(S.library.types || []).map(x => ({ what: 'field' as const, kind: x.name, label: t('Field: {type}', { type: x.name }) })),
    ...Object.keys(S.library.dimensions || {}).map(k => ({ what: 'dimension' as const, kind: k, label: DIMENSION_WORDS()[k] || k })),
    { what: 'unit', label: t('An accepted unit') },
    { what: 'check', label: t('A check of its own') },
    { what: 'vtype', label: t('A value type of its own') },
    { what: 'plan', kind: 'settings', label: t('Field of the whole document: settings') },
    { what: 'plan', kind: 'year', label: t('Field of the whole document: a year') },
  ];
  const about = (b: Block) => {
    if (b.what === 'field') {
      const s = (S.library.types || []).find(x => x.name === b.kind)?.settings || {};
      return tr(s.answer === 'number' ? (s.units ? 'a number with units' : 'a number without units') : s.answer === 'entry' ? 'an entry of a list' : 'the words of the document');
    }
    return '';
  };
  return (
    <>
      <Head><span role="button" style={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>{open ? '▾' : '▸'} {t('Library')}</span></Head>
      {open ? (
        <div className="dp-spec-lib">
          {blocks.map((b, i) => (
            <div key={i} className="dp-spec-block" draggable title={t('Drag onto a field, or click to put it into the field selected.')}
              onDragStart={ev => { ev.dataTransfer.setData(DRAG, JSON.stringify(b)); ev.dataTransfer.effectAllowed = 'copy'; }}
              onClick={() => putIn(b, S.sel)}>
              <IconGripVertical size={14} />
              <span className="dp-spec-name">{b.label}</span>
              {about(b) ? <span className="dp-spec-sub">{about(b)}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}

function Node({ n, label, sub, l1, caret }: { n: SpecNode; label: string; sub?: string; l1?: boolean; caret?: ReactNode }) {
  const sel = nodeKey(n) === nodeKey(S.sel);
  return (
    <button type="button" className={'dp-spec-node' + (l1 ? ' l1' : '')} data-sel={sel ? 'true' : 'false'} onClick={() => select(n)}
      {...('uri' in n ? onDropAt(n) : {})}>
      {caret ?? <span className="dp-spec-caret" />}
      <span className="dp-spec-name" title={label}>{label}</span>
      {sub ? <span className="dp-spec-sub">{sub}</span> : null}
    </button>
  );
}
const Head = ({ children }: { children: ReactNode }) => <div className="dp-spec-head">{children}</div>;
function AddNode({ text, onClick }: { text: string; onClick: () => void }) {
  return <button type="button" className="dp-spec-node add" onClick={onClick}><span className="dp-spec-caret"><IconPlus size={14} /></span>{text}</button>;
}

export function Tree() {
  useStore(view);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.querySelector('[data-sel="true"]')?.scrollIntoView({ block: 'nearest' }); }, [S.rev, nodeKey(S.sel)]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = S.data;
  const groups = Object.keys(isObj(d.groups) ? d.groups : {});
  const ps: Obj[] = d.parameters || [];
  const planKeys = Object.keys(isObj(d.plan_fields) ? d.plan_fields : {});
  const types = S.library.types || [];
  return (
    <div className="dp-spec-tree" ref={box}>
      <Library />
      <Head>{t('Spec')}</Head>
      <Node n={{ t: 'spec' }} label={t('Questions and note')} />
      <Head>{t('Value types ({n})', { n: types.length })}</Head>
      {types.map(x => <Node key={x.name} n={{ t: 'vtype', name: x.name }} label={x.name} sub={x.builtin ? t('built in') : t('of this spec')} />)}
      <AddNode text={t('Add value type')} onClick={() => void addValueType()} />
      <Head>{t('Document')}</Head>
      {PLAN_KEYS.map(k => isObj(d.plan_fields) && own(d.plan_fields, k)
        ? <Node key={k} n={{ t: 'plan', key: k }} label={k} sub={t('field of the whole document')} />
        : <AddNode key={k} text={t('Add field of the whole document {key}', { key: k })} onClick={() => addPlanField(k)} />)}
      {planKeys.filter(k => !PLAN_KEYS.includes(k)).map(k => <Node key={k} n={{ t: 'plan', key: k }} label={k} sub={t('field of the whole document')} />)}
      {own(d, 'works') ? <Node n={{ t: 'works' }} label="works" sub={t('other works')} /> /* i18n-ignore: the key's name */ : <AddNode text={t('Add works')} onClick={addWorks} />}
      <Head>{t('Groups ({n})', { n: groups.length })}</Head>
      {groups.map(g => <Node key={g} n={{ t: 'group', name: g }} label={g}
        sub={d.groups[g] && Array.isArray(d.groups[g].coordinates) ? tn(d.groups[g].coordinates.length, '{n} dimension', '{n} dimensions') : ''} />)}
      <div {...onDropAt(null)}><Head>{t('Fields ({n})', { n: ps.length })}</Head></div>
      {ps.map(p => {
        const open = S.expanded.has(p.uri);
        const caret = (
          <span className="dp-spec-caret" role="button" aria-label={open ? t('Collapse') : t('Expand')}
            onClick={ev => { ev.stopPropagation(); if (open) S.expanded.delete(p.uri); else S.expanded.add(p.uri); touch(); }}>
            {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
          </span>
        );
        return (
          <div key={p.uri}>
            <Node n={{ t: 'param', uri: p.uri }} label={p.label || p.uri} sub={p.label ? p.uri : (p.value_type || '')} caret={caret} />
            {open ? (
              <>
                {(['vocabulary', 'beside'] as const).filter(l => isObj(p[l])).map(l =>
                  <Node key={l} l1 n={{ t: 'plist', uri: p.uri, list: l }} label={l === 'vocabulary' ? t('list') : t('answers outside the list')} sub={tn(listCount(p[l]), '{n} entry', '{n} entries')} />)}
                {isObj(p.axes) ? Object.entries(p.axes).map(([name, ax]) =>
                  <Node key={name} l1 n={{ t: 'axis', uri: p.uri, name }} label={name} sub={isObj(ax) ? kindLabel(ax) : ''} />) : null}
              </>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
