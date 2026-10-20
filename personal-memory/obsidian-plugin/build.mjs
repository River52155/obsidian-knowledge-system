import { build } from 'esbuild';
await build({entryPoints:['src/main.ts'],outfile:'main.js',bundle:true,platform:'node',
  format:'cjs',target:'es2022',external:['obsidian'],sourcemap:false});
