/* Inputs over text the page keeps elsewhere (the spec object, a form state of forms.js). While an input has the focus it
   shows what is typed, so a number half typed ("0.") is not turned into what it stands for under the cursor; after it
   loses the focus it shows the value again. Every keystroke is handed on at once. */
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Autocomplete, Textarea, TextInput } from '@mantine/core';

function useTyped(value: string) {
  const [text, setText] = useState(value);
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(value); }, [value]);
  return {
    text, setText,
    onFocus: () => { focused.current = true; },
    onBlur: () => { focused.current = false; setText(value); },
  };
}

interface Common {
  value: string; onText: (t: string) => void; label?: React.ReactNode; description?: React.ReactNode; placeholder?: string;
  disabled?: boolean; error?: React.ReactNode; style?: CSSProperties; className?: string; w?: number | string;
  size?: string; title?: string; 'aria-label'?: string; onCommit?: (t: string) => void;
}

/* one line of text; onCommit fires on blur and Enter, for what is taken only once it is typed out */
export function TextBox(p: Common & { list?: string[]; mono?: boolean }) {
  const t = useTyped(p.value);
  const shared = {
    label: p.label, description: p.description, placeholder: p.placeholder, disabled: p.disabled, error: p.error,
    style: p.style, className: p.className, w: p.w, size: p.size, title: p.title, 'aria-label': p['aria-label'],
    spellCheck: false, value: t.text, onFocus: t.onFocus,
    styles: p.mono ? { input: { fontFamily: 'var(--mantine-font-family-monospace)' } } : undefined,
  };
  const blur = () => { t.onBlur(); p.onCommit?.(t.text); };
  if (p.list && p.list.length) {
    return <Autocomplete {...shared} data={[...new Set(p.list)]} onBlur={blur} limit={50}
      onChange={v => { t.setText(v); p.onText(v); }} />;
  }
  return <TextInput {...shared} onBlur={blur}
    onKeyDown={e => { if (e.key === 'Enter') p.onCommit?.(e.currentTarget.value); }}
    onChange={e => { const v = e.currentTarget.value; t.setText(v); p.onText(v); }} />;
}

/* several lines of text; mono for prompts and code */
export function AreaBox(p: Common & { minRows?: number; maxRows?: number; mono?: boolean; fontSize?: number }) {
  const t = useTyped(p.value);
  return <Textarea label={p.label} description={p.description} placeholder={p.placeholder} disabled={p.disabled} error={p.error}
    style={p.style} className={p.className} w={p.w} title={p.title} aria-label={p['aria-label']} spellCheck={false}
    autosize minRows={p.minRows ?? 3} maxRows={p.maxRows ?? 24} value={t.text} onFocus={t.onFocus}
    styles={p.mono || p.fontSize ? { input: { fontFamily: p.mono ? 'var(--mantine-font-family-monospace)' : undefined, fontSize: p.fontSize } } : undefined}
    onBlur={() => { t.onBlur(); p.onCommit?.(t.text); }}
    onChange={e => { const v = e.currentTarget.value; t.setText(v); p.onText(v); }} />;
}

/* a number typed as text: what is typed goes on as it stands ("" for empty), the caller decides what it is */
export function NumberBox(p: Common & { step?: string | number; min?: number; max?: number }) {
  const t = useTyped(p.value);
  return <TextInput type="number" label={p.label} description={p.description} placeholder={p.placeholder} disabled={p.disabled}
    error={p.error} style={p.style} className={p.className} w={p.w ?? 120} title={p.title} aria-label={p['aria-label']}
    step={p.step ?? 'any'} min={p.min} max={p.max} value={t.text} onFocus={t.onFocus}
    onBlur={() => { t.onBlur(); p.onCommit?.(t.text); }}
    onKeyDown={e => { if (e.key === 'Enter') p.onCommit?.(e.currentTarget.value); }}
    onChange={e => { const v = e.currentTarget.value; t.setText(v); p.onText(v); }} />;
}
