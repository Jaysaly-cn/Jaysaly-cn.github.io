const esbuild=require('esbuild');
const fs=require('node:fs');
esbuild.buildSync({entryPoints:['cutout-worker.js'],bundle:true,format:'esm',platform:'browser',target:'es2022',outfile:'vendor/cutout-worker.bundle.js',minify:true,legalComments:'linked'});
fs.copyFileSync('node_modules/@imgly/background-removal/LICENSE.md','vendor/CUTOUT-AGPL-LICENSE.md');
fs.copyFileSync('node_modules/@imgly/background-removal/ThirdPartyLicenses.json','vendor/CUTOUT-THIRD-PARTY.json');
