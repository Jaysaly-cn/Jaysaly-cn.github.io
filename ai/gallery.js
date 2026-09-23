function initialize(){
 const projects=JSON.parse(document.querySelector('#project-catalogue').textContent);
 const dialog=document.querySelector('#archive');
 for(const button of document.querySelectorAll('[data-detail]')){
  button.addEventListener('click',()=>{
   const p=projects.find(p=>p.id===button.dataset.detail);
   if(!p)return;
   for(const [id,key] of [['title','name'],['reason','reason'],['engineering','engineering'],['model','model'],['tests','tests']])document.querySelector('#archive-'+id).textContent=p[key];
   document.querySelector('#archive-case').href='../cases/'+p.id+'.html';
   document.querySelector('#archive-source').href='https://github.com/Jaysaly-cn/Jaysaly-cn.github.io/tree/main/projects/'+p.id;
   dialog.setAttribute('aria-labelledby','archive-title');dialog.showModal();
  });
 }
 const search=document.querySelector('#project-search'),scene=document.querySelector('#scene-filter');
 let room='all';
 const normalize=value=>value.normalize('NFKC').toLocaleLowerCase().trim();
 const catalogue=projects.map(p=>({project:p,element:document.getElementById(p.id),entry:document.querySelector(`[data-directory="${p.id}"]`),text:normalize([p.name,p.category,p.line,p.desc,p.engineering,p.keywords,...p.steps].join(' '))}));
 function applyFilters(){
  const terms=normalize(search.value).split(/\s+/).filter(Boolean);
  let count=0;
  for(const {project:p,element,entry,text} of catalogue){
   const visible=(room==='all'||p.room===room)&&(scene.value==='all'||p.scenes.includes(scene.value))&&terms.every(term=>text.includes(term));
   element.hidden=entry.hidden=!visible;
   if(visible)count++;
  }
  for(const button of document.querySelectorAll('[data-filter]'))button.setAttribute('aria-pressed',String(button.dataset.filter===room));
  document.querySelector('#filter-status').textContent=`显示 ${count} / ${projects.length} 件作品`+(room==='all'&&scene.value==='all'&&!terms.length?' · 按策展顺序陈列':' · 保留策展顺序');
  document.querySelector('#directory-count').textContent=count;
  document.querySelector('#empty-results').hidden=count!==0;
  document.querySelector('.directory').hidden=count===0;
 }
 function reset(){room='all';scene.value='all';search.value='';applyFilters();}
 for(const button of document.querySelectorAll('[data-filter]'))button.addEventListener('click',()=>{room=button.dataset.filter;applyFilters();});
 search.addEventListener('input',event=>{if(!event.isComposing)applyFilters();});
 search.addEventListener('compositionend',applyFilters);
 scene.addEventListener('change',applyFilters);
 document.querySelector('#clear-filters').addEventListener('click',reset);
 document.querySelector('#reset-empty').addEventListener('click',()=>{reset();search.focus();});
 for(const {project:p,entry,element} of catalogue)entry.querySelector('a').addEventListener('click',()=>element.focus({preventScroll:true}));
 applyFilters();
 document.body.classList.add('enhanced');
}
try{initialize();}catch{/* The static cases, source links and details remain usable. */}
