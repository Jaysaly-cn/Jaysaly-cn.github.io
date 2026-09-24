const esbuild=require('esbuild');
esbuild.buildSync({entryPoints:['readalong-worker.js'],bundle:true,format:'esm',platform:'browser',target:'es2022',outfile:'vendor/readalong-worker.bundle.js',minify:true,legalComments:'linked'});
