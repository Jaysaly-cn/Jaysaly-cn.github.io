export function audioStats(samples){
  if(!samples.length)throw Error('音频没有可解码的采样。');
  let sum=0,squares=0;for(const x of samples){sum+=x;squares+=x*x;}
  const rms=Math.sqrt(Math.max(0,squares/samples.length-(sum/samples.length)**2));
  return {rms,silent:rms<0.00001};
}
export function normalizeChunks(chunks,duration){
  if(!Array.isArray(chunks))throw Error('模型未返回逐段时间戳，无法生成可靠字幕。');
  return chunks.map((x,i)=>{
    if(!x.text?.trim())return null;
    const start=x.timestamp?.[0],rawEnd=x.timestamp?.[1];
    const end=rawEnd??chunks[i+1]?.timestamp?.[0]??duration;
    if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||start>=duration)throw Error('模型返回异常时间戳，请重新识别。');
    return {start,end:Math.min(duration,end),text:x.text.trim(),estimatedEnd:rawEnd==null};
  }).filter(Boolean);
}
export function timestamp(seconds){
  const ms=Math.round(seconds*1000);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;
}
export function toSRT(segments,duration){
  let previousEnd=0;
  return segments.map((s,i)=>{
    const startMs=Math.round(s.start*1000),endMs=Math.round(s.end*1000);
    if(!Number.isFinite(s.start)||!Number.isFinite(s.end)||s.start<0||startMs<previousEnd||endMs<=startMs||endMs>Math.round(duration*1000))throw Error(`第 ${i+1} 段时间无效或与前段重叠，请修订。`);
    if(!s.text.trim())throw Error(`第 ${i+1} 段文字为空，请修订。`);
    previousEnd=endMs;
    return `${i+1}\n${timestamp(s.start)} --> ${timestamp(s.end)}\n${s.text.trim().replace(/\r?\n\s*\r?\n/g,'\n')}`;
  }).join('\n\n')+'\n';
}
