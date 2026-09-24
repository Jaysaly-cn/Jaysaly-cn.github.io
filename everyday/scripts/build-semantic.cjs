const esbuild=require('esbuild');
esbuild.buildSync({entryPoints:['semantic-worker.js'],bundle:true,format:'esm',platform:'browser',target:'es2022',outfile:'vendor/semantic-worker.bundle.js',minify:true,legalComments:'linked'});
