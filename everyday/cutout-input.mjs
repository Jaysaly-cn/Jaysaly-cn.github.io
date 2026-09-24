export function hasVisibleVariation(pixels){
  let reference;
  for(let i=0;i<pixels.length;i+=4){
    if(!pixels[i+3])continue;
    const color=[pixels[i],pixels[i+1],pixels[i+2]];
    if(!reference)reference=color;
    else if(color.some((v,j)=>v!==reference[j]))return true;
  }
  return false;
}
