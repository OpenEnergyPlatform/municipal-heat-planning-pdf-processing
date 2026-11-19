/* What the page calls each dimension of a spec, and what it is for in one sentence. The spec file keeps its keys; the page
   shows these names. A dimension the page does not know is shown by its key. */
import { t } from '../lib/i18n';

export interface Named { name: string; about: string }

const KNOWN = (): Record<string, Named> => ({
  '@value': { name: t('What falls under the field'), about: t('The list the value itself is chosen from: each entry is one kind of value of this field.') },
  unit: { name: t('Unit'), about: t('The unit the document prints the number in; the number is converted from it into the unit of the field.') },
  quantity: { name: t('Quantity'), about: t('Which class of the ontology the number is; the model chooses it from the list of the field.') },
  what: { name: t('Name in the document'), about: t('What the document calls exactly this number; with these words, the column head and the unit the model chooses the quantity.') },
  subject: { name: t('Reference'), about: t('What sets this number apart from the numbers beside it, such as an age class of buildings or a network; the graph keeps two otherwise equal numbers apart by it.') },
  qualifier: { name: t('Precision'), about: t('A word right at the number that says how exactly it holds, such as "ca." or "bis zu".') },
  aggregation: { name: t('Kind of value'), about: t('Whether the number is a sum over a year, a mean or a value at one moment.') },
  carrier: { name: t('Energy carrier'), about: t('Which energy carrier the number holds for.') },
  sector: { name: t('Sector'), about: t('Which sector of consumption the number holds for.') },
  technology: { name: t('Technology'), about: t('Which technology of heat generation the document assigns the number to.') },
  year: { name: t('Year'), about: t('Which year or which span of years the number holds for.') },
  scenario: { name: t('Scenario'), about: t('Which state of the document the number refers to: its present state, a trend or its target.') },
  spatial_scope: { name: t('Area'), about: t('Which area the number holds for: the whole municipality or a part of it with its name.') },
  whole: { name: t('Share of'), about: t('What a share is a part of.') },
  role: { name: t('Role'), about: t('What part the organisation has in the document.') },
  work: { name: t('Work'), about: t('Which work a value belongs to: this publication, or a study it presents, compares or cites.') },
  year_kind: { name: t('Kind of year'), about: t('Whether a year is part of the period a scenario looks at, or another year.') },
});

export function named(key: string): Named {
  const k = KNOWN()[key];
  return k || { name: key, about: '' };
}
export const nameOf = (key: string) => named(key).name;
