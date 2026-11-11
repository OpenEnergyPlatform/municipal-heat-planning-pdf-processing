/* The page of `docpipe edit`, built into ../web: index.html, assets/ and the licence texts of every library the page
   carries. `npm run dev` serves the sources and passes /api and forms.js on to a running `docpipe edit`
   (DOCPIPE_EDIT_URL, default http://127.0.0.1:8765). */
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const OUT = fileURLToPath(new URL('../web', import.meta.url));
const SERVER = process.env.DOCPIPE_EDIT_URL || 'http://127.0.0.1:8765';

/* a build replaces assets/ whole, so no file of an older build stays beside the new one */
const cleanAssets = (): Plugin => ({
  name: 'docpipe-clean-assets',
  apply: 'build',
  buildStart() { rmSync(join(OUT, 'assets'), { recursive: true, force: true }); },
});

/* the name, version, licence and licence text of every package whose code is in the page */
const licences = (): Plugin => ({
  name: 'docpipe-licences',
  apply: 'build',
  generateBundle(_options, bundle) {
    const roots = new Set<string>();
    for (const out of Object.values(bundle)) {
      if (out.type !== 'chunk') continue;
      const ids = (out as { moduleIds?: string[] }).moduleIds ?? Object.keys(out.modules ?? {});
      for (const raw of ids) {
        const id = raw.replace(/\\/g, '/').replace(/^\0/, '');
        const at = id.lastIndexOf('/node_modules/');
        if (at < 0) continue;
        const rest = id.slice(at + '/node_modules/'.length).split('/');
        const name = rest[0].startsWith('@') ? rest[0] + '/' + rest[1] : rest[0];
        roots.add(id.slice(0, at + '/node_modules/'.length) + name);
      }
    }
    const parts = ['# Libraries in this page', '',
      'Built from `docpipe/editor/ui` with `npm run build`. Each library below keeps its own licence.', ''];
    for (const root of [...roots].sort((a, b) => a.localeCompare(b))) {
      const meta = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
      const file = readdirSync(root).find(n => /^licen[cs]e(\.(md|txt))?$/i.test(n));
      const licence = typeof meta.license === 'string' ? meta.license : JSON.stringify(meta.license ?? meta.licenses ?? null);
      parts.push(`## ${meta.name} ${meta.version} (${licence})`, '');
      if (file && existsSync(join(root, file))) parts.push('```', readFileSync(join(root, file), 'utf8').trim(), '```', '');
      else parts.push('(the package carries no licence file)', '');
    }
    this.emitFile({ type: 'asset', fileName: 'third-party-licenses.md', source: parts.join('\n') });
  },
});

/* browsers that know light-dark(): the styles keep it as written, and it follows the colour scheme the page sets. For
   older browsers the build rewrites it into variables that only a declared color-scheme in the same stylesheet fills,
   and without them every colour written with it is dropped. */
const BROWSERS = ['chrome123', 'edge123', 'firefox120', 'safari17.5'];

export default defineConfig({
  plugins: [react(), cleanAssets(), licences()],
  base: './',
  build: {
    outDir: OUT, emptyOutDir: false, sourcemap: false, chunkSizeWarningLimit: 4000, assetsInlineLimit: 0,
    target: BROWSERS, cssTarget: BROWSERS,
  },
  server: { proxy: { '/api': { target: SERVER, changeOrigin: true }, '/forms.js': { target: SERVER, changeOrigin: true } } },
});
