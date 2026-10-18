'use strict';
async function nativeReady(){
  if(window.pywebview?.api)return;
  await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(Error('The desktop controls did not start. Restart Sonar Edge.')),10000);
    window.addEventListener('pywebviewready',()=>{clearTimeout(timeout);resolve();},{once:true});
  });
}
async function nativeApi(method,...args){
  await nativeReady();const result=await window.pywebview.api[method](...args);
  if(!result?.ok)throw Error(result?.error||'The app did not accept that command');
  return result.data;
}
async function nativeCall(method,path,body){return nativeApi('call',method,path,body||{});}
let windowCommandPending=false;
async function nativeWindow(action,data){
  if(windowCommandPending)return;
  windowCommandPending=true;
  try{return await nativeApi('window_action',action,data||{});}catch(e){toast(e.message);}
  finally{windowCommandPending=false;}
}
function mediaSource(source){
  return window.SONAR_EDGE_NATIVE&&source?.startsWith('/backgrounds/')?window.SONAR_EDGE_DATA_ROOT+source:source;
}
if(window.SONAR_EDGE_NATIVE){
  document.addEventListener('click',async e=>{
    const element=e.target.closest?.('label')?.querySelector('input[type=file]')||(e.target.matches?.('input[type=file]')?e.target:null);
    if(!element||!['background-file','import-settings'].includes(element.id))return;
    e.preventDefault();e.stopImmediatePropagation();
    try{
      collectDraft();
      if(element.id==='background-file'){
        const result=await nativeApi('pick_background');if(!result)return;
        draft.background.source=result.source;draft.background.kind=result.kind;
      }else{
        const result=await nativeApi('import_settings');if(!result)return;draft=result;
      }
      settingsContent();
    }catch(error){toast(error.message);}
  },true);
  document.addEventListener('keydown',e=>{
    if(e.key==='F11'){e.preventDefault();if(!e.repeat)nativeWindow('fullscreen');}
    else if(e.key==='Escape'&&document.querySelector('#overlay')?.hidden)nativeWindow('leave_fullscreen');
  });
  queueMicrotask(()=>{
    const button=document.createElement('button');button.className='icon-button quiet';button.title='Display';button.setAttribute('aria-label','Choose display');
    button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>';
    document.querySelector('#fullscreen').before(button);
    button.addEventListener('click',async()=>{
      const info=await nativeWindow('displays');if(!info)return;
      openSheet('Display','SONAR EDGE');
      document.querySelector('#sheet-content').innerHTML=`<div class="player-picker-list">${info.displays.map(d=>`<button class="player-choice" data-display-id="${d.id}"><span>${esc(d.name)}</span><span class="eyebrow">${d.width} × ${d.height}</span></button>`).join('')}</div><label class="check"><input id="display-fullscreen" type="checkbox" checked>Fullscreen on selected display</label><label class="check"><input id="display-top" type="checkbox"${info.onTop?' checked':''}>Always on top</label><label class="check"><input id="display-auto-edge" type="checkbox"${preferences.autoEdge!==false?' checked':''}>Open on Xeneon Edge automatically</label>`;
      document.querySelectorAll('[data-display-id]').forEach(b=>b.addEventListener('click',async()=>{
        const result=await nativeWindow('move',{display:Number(b.dataset.displayId),fullscreen:document.querySelector('#display-fullscreen').checked});if(result)closeSheet();
      }));
      document.querySelector('#display-top').addEventListener('change',async e=>{
        const input=e.target,previous=!input.checked;input.disabled=true;
        const result=await nativeWindow('on_top',{value:input.checked});
        input.checked=result?result.onTop:previous;input.disabled=false;
      });
      document.querySelector('#display-auto-edge').addEventListener('change',async e=>{
        const input=e.target,previous=!input.checked;input.disabled=true;
        try{preferences=await execute('/api/preferences',{...preferences,autoEdge:input.checked});}
        catch{input.checked=previous;}
        finally{input.disabled=false;}
      });
    });
  });
}
