export function validateFile(file){
 if(!['image/png','image/jpeg','image/webp','image/bmp'].includes(file.type))throw Error('请选择 PNG、JPEG、WebP 或 BMP 图片。');
 if(!file.size)throw Error('图片文件为空。');
 if(file.size>10*1024*1024)throw Error('图片超过 10 MB，请先压缩或裁剪。');
}
export function dimensions(width,height){
 if(!Number.isFinite(width)||!Number.isFinite(height)||width<1||height<1)throw Error('无法读取图片尺寸。');
 if(width*height>16000000)throw Error('图片超过 1600 万像素，请先裁剪。');
 const ratio=Math.min(1,2500/Math.max(width,height));
 return {width:Math.round(width*ratio),height:Math.round(height*ratio),scaled:ratio<1};
}
export function txtName(name){return (name.replace(/\.[^.]+$/,'').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,80)||'snaptext')+'.txt';}
export function recognitionRecord({name,language,text,confidence,elapsed,width,height}){
 return {engine:'Tesseract.js 7.0.0 / LSTM',language,input:name,width,height,elapsedMs:Math.round(elapsed),confidence:Number.isFinite(confidence)?confidence:null,characters:[...text].length,rawText:text,at:new Date().toISOString()};
}
