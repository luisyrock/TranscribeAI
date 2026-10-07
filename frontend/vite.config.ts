import {defineConfig} from 'vite';
export default defineConfig({
  server:{proxy:{'/api':'http://127.0.0.1:8000'}},
  // Rollup's call-argument analysis explodes on the recursive Markdown plugin.
  // Import icons directly and skip tree-shaking; esbuild still minifies assets.
  build:{rollupOptions:{treeshake:false}},
});
