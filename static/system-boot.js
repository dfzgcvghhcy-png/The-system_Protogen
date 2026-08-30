(function(){
  const boot=document.querySelector('[data-system-boot]');
  if(!boot)return;
  const key=boot.dataset.bootKey||'protogen-system-boot';
  const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let seen=false;
  try{seen=sessionStorage.getItem(key)==='1';}catch(_){ }
  const finish=()=>{
    boot.classList.add('is-hidden');
    document.body.classList.remove('boot-locked');
    try{sessionStorage.setItem(key,'1');}catch(_){ }
    window.setTimeout(()=>boot.setAttribute('aria-hidden','true'),600);
  };
  if(seen||reduce){boot.classList.add('is-hidden');boot.setAttribute('aria-hidden','true');return;}
  document.body.classList.add('boot-locked');
  const bar=boot.querySelector('.boot-progress i');
  const pct=boot.querySelector('[data-boot-percent]');
  const statuses=[...boot.querySelectorAll('.boot-status')];
  const start=performance.now();
  const duration=2450;
  function frame(now){
    const p=Math.min(1,(now-start)/duration);
    const eased=1-Math.pow(1-p,3);
    const value=Math.round(eased*100);
    if(bar)bar.style.width=value+'%';
    if(pct)pct.textContent=value+'%';
    statuses.forEach((el,i)=>el.classList.toggle('is-active',p>(i+1)/(statuses.length+2)));
    if(p<1)requestAnimationFrame(frame);else window.setTimeout(finish,260);
  }
  requestAnimationFrame(frame);
  boot.querySelector('[data-boot-skip]')?.addEventListener('click',finish);
})();
