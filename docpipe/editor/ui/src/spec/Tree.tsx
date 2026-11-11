/* The tree on the left: the top-level questions, the document's plan fields and works, the groups, the fields with their
   list and coordinates under them. */
import { useEffect, useRef, type ReactNode } from 'react';
import { IconChevronDown, IconChevronRight, IconPlus } from '@tabler/icons-react';
import { useStore } from '../lib/nav';
import { isObj, own, type Obj } from '../lib/util';
import type { SpecNode } from '../lib/spec';
import { addPlanField, addWorks, listCount, nodeKey, S, select, touch, view } from './state';

const PLAN_KEYS = ['settings', 'base_year', 'target_year'];

function kindLabel(ax: Obj): string {
  if (own(ax, 'vocabulary')) return 'list · ' + listCount(ax.vocabulary) + ' entries';
  if (own(ax, 'type')) return String(ax.type);
  if (own(ax, 'enum')) return 'strings';
  if (own(ax, 'dynamic')) return 'per document';
  return 'no kind';
}

function Node({ n, label, sub, l1, caret }: { n: SpecNode; label: string; sub?: string; l1?: boolean; caret?: ReactNode }) {
  const sel = nodeKey(n) === nodeKey(S.sel);
  return (
    <button type="button" className={'dp-spec-node' + (l1 ? ' l1' : '')} data-sel={sel ? 'true' : 'false'} onClick={() => select(n)}>
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
  return (
    <div className="dp-spec-tree" ref={box}>
      <Head>Questions</Head>
      <Node n={{ t: 'spec' }} label="Top-level questions" />
      <Head>Document</Head>
      {PLAN_KEYS.map(k => isObj(d.plan_fields) && own(d.plan_fields, k)
        ? <Node key={k} n={{ t: 'plan', key: k }} label={k} sub="plan field" />
        : <AddNode key={k} text={'Add plan field ' + k} onClick={() => addPlanField(k)} />)}
      {planKeys.filter(k => !PLAN_KEYS.includes(k)).map(k => <Node key={k} n={{ t: 'plan', key: k }} label={k} sub="plan field" />)}
      {own(d, 'works') ? <Node n={{ t: 'works' }} label="works" sub="other works" /> : <AddNode text="Add works" onClick={addWorks} />}
      <Head>Groups ({groups.length})</Head>
      {groups.map(g => <Node key={g} n={{ t: 'group', name: g }} label={g}
        sub={d.groups[g] && Array.isArray(d.groups[g].coordinates) ? d.groups[g].coordinates.length + ' coordinates' : ''} />)}
      <Head>Fields ({ps.length})</Head>
      {ps.map(p => {
        const open = S.expanded.has(p.uri);
        const caret = (
          <span className="dp-spec-caret" role="button" aria-label={open ? 'Fold' : 'Unfold'}
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
                  <Node key={l} l1 n={{ t: 'plist', uri: p.uri, list: l }} label={l === 'vocabulary' ? 'list' : 'beside list'} sub={listCount(p[l]) + ' entries'} />)}
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
