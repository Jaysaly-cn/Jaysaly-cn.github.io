const aliases={'番茄':'西红柿','油':'食用油','食盐':'盐','食用盐':'盐','白糖':'糖','白砂糖':'糖','大蒜':'蒜','蒜头':'蒜','蒜瓣':'蒜','白豆腐':'豆腐','香葱':'葱','小葱':'葱','葱花':'葱','冷饭':'米饭','剩饭':'米饭','五花肉':'猪肉','猪瘦肉':'猪肉','面条':'挂面','香醋':'醋','鸡蛋过敏':'蛋','牛奶过敏':'乳'};
export const canonical=s=>aliases[s.trim()]||s.trim();
export const tokens=s=>[...new Set(s.split(/[,，、;；\n]+/).map(canonical).filter(Boolean))];
export function amounts(item,factor,recipe){
 if(!Number.isInteger(factor)||factor<1||factor>4)throw Error('请选择 1–4 份原配方。');
 if(item.quantity===null)return {min:null,max:null,unit:item.unit};
 if(recipe.id==='tomato-eggs'&&item.name==='食用油')return {min:Math.ceil(1.5*factor)*4,max:Math.ceil(1.5*factor)*4,unit:'ml'};
 const round=item.rounding==='ceil'?Math.ceil:item.rounding==='floor'?Math.floor:n=>n;
 return {min:round(item.quantity*factor+(item.offset||0)),max:round((item.maximum??item.quantity)*factor+(item.offset||0)),unit:item.unit};
}
export function amountText(amount){const fmt=n=>Number(n.toFixed(2)).toString();return amount.min===null?'原方未定量，备料时核对':`${fmt(amount.min)}${amount.max!==amount.min?'–'+fmt(amount.max):''} ${amount.unit}`;}
export function inspectRecipe(recipe,{inventory,excluded,tools,maxTime,includeOptional}){
 const reasons=[];
 if(recipe.minutes>maxTime)reasons.push(`预估 ${recipe.minutes} 分钟，超出单菜时间`);
 const missingTools=recipe.tools.filter(t=>!tools.includes(t));if(missingTools.length)reasons.push('缺少厨具：'+missingTools.join('、'));
 const hits=excluded.filter(x=>recipe.ingredients.some(i=>canonical(i.name)===x)||recipe.allergens.includes(x));if(hits.length)reasons.push('包含排除项：'+hits.join('、'));
 const required=recipe.ingredients.filter(i=>includeOptional||!i.optional),missing=required.filter(i=>!inventory.includes(canonical(i.name)));
 return {recipe,reasons,missing,coverage:required.length?(required.length-missing.length)/required.length:0};
}
export function rankRecipes(inspected,scores){
 const map=new Map(scores.map(x=>[x.id,x.score]));
 return inspected.filter(x=>!x.reasons.length).map(x=>{const semantic=map.get(x.recipe.id);if(!Number.isFinite(semantic))throw Error('模型结果不完整，请重试。');return {...x,semantic,rank:.65*semantic+.35*x.coverage};}).sort((a,b)=>b.rank-a.rank||a.recipe.id.localeCompare(b.recipe.id));
}
export function shoppingList(recipes,settings){
 const grouped=new Map();
 for(const recipe of recipes)for(const ingredient of recipe.ingredients){
  if((ingredient.optional&&!settings.includeOptional)||settings.inventory.includes(canonical(ingredient.name)))continue;
  const a=amounts(ingredient,settings.factor,recipe),key=canonical(ingredient.name)+'|'+a.unit;
  const item=grouped.get(key)||{name:ingredient.name,unit:a.unit,min:0,max:0,unknown:false,recipes:[]};
  if(a.min===null)item.unknown=true;else{item.min+=a.min;item.max+=a.max;}
  item.recipes.push(recipe.name);grouped.set(key,item);
 }
 return [...grouped.values()];
}
