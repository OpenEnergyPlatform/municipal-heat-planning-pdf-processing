/* The conversion between a JSON value and a form stays in ../../web/forms.js, plain JavaScript without React, which the
   page loads before itself (window.DPForms) and the tests run in node (tests/editor_forms_driver.js). This module only
   names its parts for TypeScript. */

export interface Kind {
  k: 'text' | 'number' | 'bool' | 'record' | 'rows' | 'map' | 'bounds';
  fields?: Field[]; item?: Kind; value?: Kind; one?: boolean;
  list?: string; area?: boolean; choices?: string[]; keep?: boolean; auto?: boolean;
}
export interface Field { key: string; kind: Kind; help: string }
export type Path = (string | number)[];
/* a state of forms.js: its shape follows its kind (see stateOf there) */
export type FormState = any;
export interface Leaf { path: Path; vpath: Path; text: string; kind: string }

export interface DPForms {
  own(o: unknown, k: string): boolean;
  isObj(v: unknown): boolean;
  clone<T>(v: T): T;
  KINDS: Record<string, Kind>;
  TEXT: Kind; PREDICATE: Kind; LINK: Kind; SLOT: Kind; CLASSMAP: Kind;
  kindOf(decl: { kind?: string; choices?: string[] }): Kind | null;
  recordOf(decls: { key: string; kind?: string; help?: string; choices?: string[] }[]): Kind;
  ruleSpec(rule: { kind: string; of?: string; columns?: string[] }): Kind | null;
  exampleSpec(columns: string[], defaultKeys: string[], numeric: boolean): Kind;
  exampleColumns(coordinates: string[], example: unknown): string[];
  exampleOffers(coordinates: string[]): string[];
  defaultKeysOf(coordinates: string[], example: unknown): string[];
  fits(spec: Kind, v: unknown): boolean;
  stateOf(spec: Kind, value: unknown): FormState;
  valueOf(st: FormState): any;
  textOf(st: FormState): string;
  edit(root: FormState, path: Path, text: string | boolean): FormState;
  addRow(root: FormState, path: Path): number;
  removeRow(root: FormState, path: Path, i: number): void;
  moveRow(root: FormState, path: Path, i: number, d: number): void;
  addPair(root: FormState, path: Path): number;
  removePair(root: FormState, path: Path, i: number): void;
  leaves(st: FormState): Leaf[];
}

declare global { interface Window { DPForms: DPForms } }

export const DF = (): DPForms => {
  if (!window.DPForms) throw new Error('forms.js is not loaded: the page needs /forms.js beside it.');
  return window.DPForms;
};
