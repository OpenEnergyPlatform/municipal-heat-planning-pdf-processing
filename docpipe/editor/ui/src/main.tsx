import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@xyflow/react/dist/style.css';
import './app.css';
import { createRoot } from 'react-dom/client';
import { Badge, createTheme, localStorageColorSchemeManager, MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { App } from './App';

/* System fonts only: the page loads nothing from outside. */
const theme = createTheme({
  primaryColor: 'indigo',
  defaultRadius: 'md',
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace: 'ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace',
  headings: { fontWeight: '650' },
  /* a badge shows its words as written: versions, names of settings and counts are not shouted */
  components: { Badge: Badge.extend({ styles: { root: { textTransform: 'none' } } }) },
});

createRoot(document.getElementById('root')!).render(
  <MantineProvider theme={theme} defaultColorScheme="auto"
    colorSchemeManager={localStorageColorSchemeManager({ key: 'docpipe-edit-color-scheme' })}>
    <ModalsProvider>
      <Notifications position="top-right" limit={4} />
      <App />
    </ModalsProvider>
  </MantineProvider>,
);
