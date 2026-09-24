const test=require('node:test'),assert=require('node:assert/strict');
test('reject blank and invisible RGB noise, retain low contrast photos',async()=>{
 const {hasVisibleVariation}=await import('../cutout-input.mjs');
 assert.equal(hasVisibleVariation(new Uint8ClampedArray([255,255,255,255,255,255,255,255])),false);
 assert.equal(hasVisibleVariation(new Uint8ClampedArray([1,2,3,0,7,8,9,0])),false);
 assert.equal(hasVisibleVariation(new Uint8ClampedArray([128,128,128,255,129,128,128,255])),true);
});
