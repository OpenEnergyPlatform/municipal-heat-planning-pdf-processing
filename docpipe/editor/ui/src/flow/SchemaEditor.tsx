/* The visual editor of a JSON schema (jsonjoy-builder, MIT), in the page's language. It is loaded only when the form
   of an answer is edited (General.tsx), so the page does not carry it otherwise. It keeps its own light colours on a
   light card in both of the page's schemes, and its dialogs stand above the window it opens in (app.css). */
import { SchemaFieldsEditor, de, en } from 'jsonjoy-builder';
import 'jsonjoy-builder/styles.css';

export default function SchemaEditor({ value, onChange, lang }: {
  value: Record<string, unknown>; onChange: (schema: Record<string, unknown>) => void; lang: string;
}) {
  return <SchemaFieldsEditor value={value as never} locale={lang === 'de' ? de : en}
    onChange={(schema: unknown) => onChange(schema as Record<string, unknown>)} />;
}
