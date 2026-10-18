'use strict';
(function(root){
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const peakDb=value=>Number.isFinite(value)&&value>0?clamp(20*Math.log10(value),-60,0):-60;
  const peakHeight=value=>(peakDb(value)+60)/60*100;
  const timeLabel=seconds=>`${Math.floor(Math.max(0,seconds)/60)}:${String(Math.floor(Math.max(0,seconds)%60)).padStart(2,'0')}`;
  function positionAt(music,received,now){
    const extra=music.playing?clamp((now-received)/1000,0,1.2):0;
    return clamp((music.position||0)+extra,0,music.duration||0);
  }
  function theme(palette,fallback){
    const valid=s=>typeof s==='string'&&/^#[0-9a-f]{6}$/i.test(s);
    return {accent:valid(palette?.accent)?palette.accent:fallback,
      secondary:valid(palette?.secondary)?palette.secondary:fallback,
      background:valid(palette?.background)?palette.background:'#1c2631'};
  }
  const mixerBackground=fx=>fx.mixerBackground&&fx.mixerBackground!=='match'?fx.mixerBackground:fx.playerBackground;
  let context, musicClock={}, musicReceived=0, musicStamp, lastArtKey='', lastEffectsKey='';
  let meterData={levels:{}}, meterReceived=0, lastFrame=0;
  const holds=new Map(), ambientState=new Map();
  function syncMusic(music){
    if(music.updated!==musicStamp||music.source!==musicClock.source||music.connected!==musicClock.connected){
      musicClock={...music};musicStamp=music.updated;musicReceived=performance.now();
    }
  }
  function ambient(host,mode,art,colors){
    const key=JSON.stringify([mode,art,colors]);
    if(ambientState.get(host)?.key===key)return;
    const previous=ambientState.get(host)||{slot:0};
    const slot=1-previous.slot,layers=host.querySelectorAll('.ambient-layer');
    const visible=mode!=='off'&&!!art;
    host.classList.toggle('enabled',visible);
    const layer=layers[slot];
    layer.style.backgroundImage=mode==='artwork'?`url(${JSON.stringify(art||'')})`:
      `radial-gradient(ellipse at 15% 20%,${colors.accent},transparent 65%),radial-gradient(ellipse at 85% 80%,${colors.secondary},${colors.background} 75%)`;
    layers[previous.slot].classList.remove('visible');layer.classList.toggle('visible',visible);
    ambientState.set(host,{key,slot});
  }
  function artwork(music,prefs){
    if(!prefs)return;
    const fx=prefs.artworkEffects,art=music.connected?music.art:null,colors=theme(music.palette,prefs.accent);
    const effectKey=JSON.stringify([fx,colors,art,prefs.accent]);
    if(effectKey===lastEffectsKey)return;
    lastEffectsKey=effectKey;
    const stage=document.querySelector('#stage'),player=document.querySelector('.player'),mixer=document.querySelector('.mixer');
    stage.style.setProperty('--music-accent',fx.colors!=='off'&&art?colors.accent:prefs.accent);
    stage.style.setProperty('--music-secondary',fx.colors!=='off'&&art?colors.secondary:prefs.accent);
    document.documentElement.style.setProperty('--accent',fx.colors==='all'&&art?colors.accent:prefs.accent);
    stage.style.setProperty('--ambient-opacity',fx.intensity);
    stage.style.setProperty('--ambient-blur',`${fx.blur}px`);
    stage.classList.toggle('ambient-motion',fx.motion);
    player.classList.toggle('has-ambient',fx.playerBackground!=='off'&&!!art);
    mixer.classList.toggle('has-ambient',mixerBackground(fx)!=='off'&&!!art);
    stage.classList.toggle('has-app-ambient',fx.appBackground!=='off'&&!!art);
    ambient(document.querySelector('#app-ambient'),fx.appBackground,art,colors);
    ambient(document.querySelector('#player-ambient'),fx.playerBackground,art,colors);
    ambient(document.querySelector('#mixer-ambient'),mixerBackground(fx),art,colors);
    lastArtKey=art||'';
  }
  function meterFrame(now){
    const prefs=context.preferences();
    if(!prefs?.showMeters)return;
    const fresh=now-meterReceived<1000&&Date.now()/1000-(meterData.sampledAt||0)<1.2;
    document.querySelectorAll('.channel').forEach(channel=>{
      const id=channel.dataset.channel,raw=fresh?meterData.levels?.[id]:null;
      const valid=Number.isFinite(raw),height=valid?peakHeight(raw):0;
      const meter=channel.querySelector('.signal-meter');if(!meter)return;
      const hold=holds.get(id)||{height:0,until:0};
      if(height>=hold.height){hold.height=height;hold.until=now+650;}
      else if(now>hold.until)hold.height=Math.max(height,hold.height-2.8);
      holds.set(id,hold);
      meter.style.setProperty('--signal-level',`${height}%`);
      meter.style.setProperty('--signal-hold',`${hold.height}%`);
      meter.classList.toggle('unavailable',!valid);
      meter.classList.toggle('signal-hot',valid&&raw>=.98);
      channel.classList.toggle('has-signal',valid&&raw>.003);
      const db=valid?Math.round(peakDb(raw)):-60;
      meter.setAttribute('aria-valuenow',String(db));
      meter.setAttribute('aria-valuetext',valid?(raw<.001?'Silent':`${db} dBFS`):'Meter unavailable');
      meter.title=!valid?'Live meter unavailable':id==='master'?'Combined Sonar output channel activity':'Live signal before Sonar volume';
    });
  }
  function musicFrame(now){
    const seek=document.querySelector('#seek'),volume=document.querySelector('#music-volume');
    if(musicClock.connected&&musicClock.duration>0){
      if(!context.editing('seek')){
        seek.max=musicClock.duration;seek.value=positionAt(musicClock,musicReceived,now);
      }
      seek.style.setProperty('--range-fill',`${clamp(Number(seek.value)/Number(seek.max)*100,0,100)}%`);
      document.querySelector('#elapsed').textContent=timeLabel(Number(seek.value));
    }
    volume.style.setProperty('--range-fill',`${clamp(Number(volume.value),0,100)}%`);
    const chatmix=document.querySelector('#chatmix');
    chatmix.style.setProperty('--mix-position',`${(Number(chatmix.value)+100)/2}%`);
  }
  function frame(now){
    if(now-lastFrame>=50&&!document.hidden){lastFrame=now;meterFrame(now);musicFrame(now);}
    requestAnimationFrame(frame);
  }
  async function pollMeters(){
    let delay=65;
    try{
      if(context.preferences()?.showMeters&&!document.hidden){
        meterData=await context.fetchMeters();meterReceived=performance.now();
      }else delay=600;
    }catch{meterData={levels:{}};delay=800;}
    setTimeout(pollMeters,delay);
  }
  function start(options){context=options;requestAnimationFrame(frame);pollMeters();}
  const api={peakDb,peakHeight,timeLabel,positionAt,theme,mixerBackground,syncMusic,artwork,start};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.EdgeVisuals=api;
})(globalThis);
