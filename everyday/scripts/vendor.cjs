const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),out=path.join(root,'vendor');fs.mkdirSync(out,{recursive:true});
function copy(pkg,from,to){const source=path.join(root,'node_modules',pkg,from),target=path.join(out,to);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(source,target);}
for(const name of ['tesseract.min.js','worker.min.js','tesseract.min.js.LICENSE.txt','worker.min.js.LICENSE.txt'])copy('tesseract.js','dist/'+name,name);
copy('tesseract.js','LICENSE.md','TESSERACT-LICENSE');copy('tesseract.js-core','LICENSE','CORE-LICENSE');
// OEM 1 uses LSTM only. Ship every CPU feature variant selected by core v7.
for(const suffix of ['lstm','simd-lstm','relaxedsimd-lstm'])copy('tesseract.js-core',`tesseract-core-${suffix}.wasm.js`,`core/tesseract-core-${suffix}.wasm.js`);
for(const lang of ['eng','chi_sim']){copy('@tesseract.js-data/'+lang,`4.0.0_best_int/${lang}.traineddata.gz`,`lang/${lang}.traineddata.gz`);}
const files=[];function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else if(e.name!=='manifest.json'){const b=fs.readFileSync(p);files.push({path:path.relative(out,p).replaceAll('\\','/'),bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex')});}}}walk(out);
fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({packages:require('../package.json').dependencies,files},null,2));console.log(files.length,'assets;',files.reduce((s,f)=>s+f.bytes,0),'bytes');
