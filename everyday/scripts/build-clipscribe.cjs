const esbuild=require('esbuild'),fs=require('node:fs');
esbuild.buildSync({entryPoints:['clipscribe-worker.js'],bundle:true,format:'esm',platform:'browser',target:'es2022',outfile:'vendor/clipscribe-worker.bundle.js',minify:true,legalComments:'linked'});
fs.copyFileSync('node_modules/@huggingface/transformers/LICENSE','vendor/TRANSFORMERS-LICENSE');
