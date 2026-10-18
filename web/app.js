'use strict';
const icons = {
  gear:'<path d="M10 2h4l.8 3 2.2 1.3 3-.8 2 3.4-2.2 2.3v1.6l2.2 2.3-2 3.4-3-.8-2.2 1.3L14 22h-4l-.8-3L7 17.7l-3 .8-2-3.4 2.2-2.3v-1.6L2 8.9l2-3.4 3 .8L9.2 5Z"/><circle cx="12" cy="12" r="3"/>',
  sliders:'<path d="M4 7h5m4 0h7M4 17h9m4 0h3"/><path d="M9 4v6m4 4v6"/>',
  expand:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  music:'<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="17" cy="16" rx="3" ry="3"/>',
  external:'<path d="M14 3h7v7m0-7L11 13"/><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  play:'<path d="m8 4 12 8-12 8Z"/>', pause:'<path d="M7 5h3v14H7zM14 5h3v14h-3z"/>',
  previous:'<path d="m17 5-10 7 10 7ZM5 5v14"/>', next:'<path d="m7 5 10 7-10 7ZM19 5v14"/>',
  shuffle:'<path d="M3 6h3c4 0 6 12 10 12h5m-4-4 4 4-4 4M3 18h3c1.4 0 2.5-1.4 3.5-3M14 8c.7-1.2 1.3-2 2-2h5m-4-4 4 4-4 4"/>',
  repeat:'<path d="m17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4m14-1v3a2 2 0 0 1-2 2H3"/>',
  minus:'<path d="M5 12h14"/>',plus:'<path d="M5 12h14M12 5v14"/>',
  volume:'<path d="m11 4-6 5H2v6h3l6 5Zm4 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
  muted:'<path d="m11 4-6 5H2v6h3l6 5ZM16 9l6 6m0-6-6 6"/>',
  game:'<path d="M7 7h10c3 0 5 10 4 12-1 2-5-3-6-3H9c-1 0-5 5-6 3C2 17 4 7 7 7Z"/><path d="M8 9v5m-2-2h5m5-1h.01M18 13h.01"/>',
  chat:'<path d="M21 14a3 3 0 0 1-3 3H9l-6 4V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3Z"/><path d="M7 8h10M7 12h7"/>',
  mic:'<rect x="8" y="2" width="8" height="13" rx="4"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4m-4 0h8"/>',
  headphones:'<path d="M3 14v-3a9 9 0 0 1 18 0v3"/><rect x="2" y="12" width="5" height="9" rx="2"/><rect x="17" y="12" width="5" height="9" rx="2"/>',
  aux:'<path d="M3 9v6m6-11v16m6-14v12m6-9v6"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  up:'<path d="m6 15 6-6 6 6"/>',down:'<path d="m6 9 6 6 6-6"/>',
  stop:'<rect x="5" y="5" width="14" height="14" rx="2"/>',
};
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.music}</svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy = obj => JSON.parse(JSON.stringify(obj));
let token, preferences, state = {}, catalog, draft, sheetChannel, lastFocus;
let toastTimer, disconnected = false;
let settingsTab = 'layout', playerOptions = [{id:'musicbee',name:'MusicBee'},{id:'auto',name:'Windows active media app'}];
let appVersionInfo=null, defaultVersionDraft='desktop', startupDraft=false, versionPrompted=false;
let updateInfo=null, updateTimer;
const edited = new Map(), writes = new Map();
const draggingMusic = new Set();
const chatmixWrite={running:false};
const actionNames = {mic:'Mute mic',media:'Mute media',master:'Mute all',musicbee:'Open MusicBee',sonar:'Open Sonar',playpause:'Play / pause',previous:'Previous track',next:'Next track',stop:'Stop music'};
const actionIcons = {mic:'mic',media:'volume',master:'muted',musicbee:'music',sonar:'sliders',playpause:'play',previous:'previous',next:'next',stop:'stop'};
const editableIcons = {mic:'Microphone',volume:'Speaker',muted:'Muted speaker',music:'Music note',headphones:'Headphones',sliders:'Mixer',play:'Play',pause:'Pause',previous:'Previous',next:'Next',stop:'Stop',external:'Open app'};
const internal = {game:'game',chat:'chatRender',media:'media',aux:'aux',mic:'chatCapture'};

function shortcutIcon(action, style={}, playing=false, muted=false) {
  if(style.icon && style.icon!==actionIcons[action])return style.icon;
  return muted?'muted':action==='playpause'&&playing?'pause':actionIcons[action];
}

function hydrate(parent = document) {
  $$('[data-icon]', parent).forEach(el => {
    if (!el.querySelector(':scope > svg')) el.insertAdjacentHTML('afterbegin', svg(el.dataset.icon));
  });
}
function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4200);
}
async function get(path) {
  if(window.SONAR_EDGE_NATIVE) return nativeCall('GET',path,{});
  const r = await fetch(path, {cache:'no-store', signal:AbortSignal.timeout(12000)});
  const data = await r.json(); if (!r.ok) throw new Error(data.error || 'Connection failed'); return data;
}
async function session() {
  const data = await get('/api/session'); token = data.token; preferences = data.preferences;
  appVersionInfo=data.appVersion||null;
  if(window.SONAR_EDGE_CHOOSE_VERSION&&!versionPrompted&&appVersionInfo){
    versionPrompted=true;queueMicrotask(()=>openSettings('version'));
  }
}
async function post(path, body, retry = true) {
  if(window.SONAR_EDGE_NATIVE) return nativeCall('POST',path,body);
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Edge-Token':token}, body:JSON.stringify(body), signal:AbortSignal.timeout(16000)});
  const data = await r.json();
  if (r.status === 403 && retry) { await session(); return post(path, body, false); }
  if (!r.ok) throw new Error(data.error || 'The app did not accept that command'); return data;
}
async function execute(path, body) {
  try { return await post(path, body); } catch(e) { toast(e.message); throw e; }
}
function fit() {
  const stage=$('#stage');
  const width=innerWidth/innerHeight>2.5?720*innerWidth/innerHeight:2560;
  stage.style.width=`${width}px`;
  stage.style.transform=`scale(${Math.min(innerWidth / width, innerHeight / 720)})`;
}
window.addEventListener('resize', fit); fit(); hydrate();
function time() {
  $('#clock').textContent = new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
}
time(); setInterval(time, 15000);
function applyAppearance(p) {
  const b=p.background, a=p.appearance, root=document.documentElement.style;
  root.setProperty('--accent',p.accent); root.setProperty('--base-color',b.color);
  root.setProperty('--panel-color',a.panelColor); root.setProperty('--panel-opacity',`${a.panelOpacity*100}%`);
  root.setProperty('--text-color',a.textColor); root.setProperty('--muted',a.mutedColor);
  root.setProperty('--text-scale',a.textScale||1);
  root.setProperty('--artwork-size',`${a.artworkSize||256}px`);
  root.setProperty('--roundness',`${a.roundness}px`); root.setProperty('--background-blur',`${b.blur}px`);
  root.setProperty('--background-dim',b.dim); root.setProperty('--background-fit',b.fit);
  root.setProperty('--ui-font', {system:"'Segoe UI Variable','Segoe UI',sans-serif",rounded:"'Trebuchet MS','Segoe UI',sans-serif",mono:"'Cascadia Code','Consolas',monospace"}[a.font]);
  $('#background-gradient').style.background=b.kind==='gradient'?`linear-gradient(${b.angle}deg,${b.color},${b.color2})`:b.color;
  const image=$('#background-image'),video=$('#background-video');
  const backgroundSource=assetSource(b.source);
  image.hidden=b.kind!=='image'||!b.source; video.hidden=b.kind!=='video'||!b.source;
  if (!image.hidden && image.getAttribute('src')!==backgroundSource) image.src=backgroundSource;
  if (image.hidden) image.removeAttribute('src');
  if (!video.hidden && video.getAttribute('src')!==backgroundSource) { video.src=backgroundSource;video.muted=true;video.play().catch(()=>{}); }
  if (video.hidden && video.getAttribute('src')) {video.pause();video.removeAttribute('src');video.load();}
  $('.artwork').hidden=!p.showArtwork;
  $('#stage').classList.toggle('meters-hidden',!p.showMeters);
  $('#chatmix-control').hidden=!p.showChatMix;
  EdgeVisuals.artwork(state.music||{},p);
}
function assetSource(source){return window.SONAR_EDGE_NATIVE&&source?.startsWith('/backgrounds/')?window.SONAR_EDGE_DATA_ROOT+source:source;}
function applyPreferences() {
  applyAppearance(preferences);
  $('#clock').hidden = !preferences.showClock;
  $('#workspace').className = 'workspace' + (preferences.layout === 'balanced' ? '' : ` ${preferences.layout}-focus`) + (preferences.playerSide === 'right' ? ' player-right' : '');
  $('#channels').innerHTML = preferences.channels.filter(c => c.visible).map(c => `
    <article class="channel" data-channel="${c.id}" style="--channel:${c.color}">
      <div class="channel-head">${svg(c.id === 'master' ? 'volume' : c.id === 'media' ? 'music' : c.id)}<span>${esc(c.label)}</span>${c.id==='master'?'':`<button class="eq-button" aria-label="${esc(c.label)} equalizer presets" disabled>EQ</button>`}</div>
      ${c.id==='master'?'<div class="device-button master-device"><small>CONTROLS</small><span>All Sonar channels</span></div>':`<button class="device-button" aria-label="Choose ${esc(c.label)} ${c.id==='mic'?'input':'output'} device" disabled><small>${c.id==='mic'?'INPUT':'OUTPUT'}</small><span class="device-name">Connecting…</span>${svg('down')}</button>`}
      <div class="fader-area"><div class="fader-ruler"></div><div class="fader-rail"><div class="fader-fill"></div></div><input type="range" class="fader" min="0" max="100" step="1" value="0" aria-label="${esc(c.label)} volume" disabled><div class="signal-meter unavailable" role="meter" aria-label="${esc(c.label)} live signal" aria-valuemin="-60" aria-valuemax="0" aria-valuenow="-60"><div class="signal-track"><div class="signal-mask"></div><div class="signal-segments"></div></div><i class="signal-peak"></i><span class="signal-scale top">0</span><span class="signal-scale middle">−30</span><span class="signal-scale bottom">−60</span></div></div>
      <div class="volume-stepper"><button data-step="-1" aria-label="Lower ${esc(c.label)} volume one percent" disabled>${svg('minus')}</button><div class="volume-readout"><span>—</span><small>%</small></div><button data-step="1" aria-label="Raise ${esc(c.label)} volume one percent" disabled>${svg('plus')}</button></div>
      <button class="mute-button" aria-label="Mute ${esc(c.label)}" aria-pressed="false" disabled>${svg('volume')}<span>Mute</span></button>
    </article>`).join('');
  $$('.channel').forEach(el => {
    const id = el.dataset.channel, input = $('.fader', el);
    input.addEventListener('input', () => setVolume(id, Number(input.value) / 100));
    $$('[data-step]', el).forEach(btn => btn.addEventListener('click', () => {
      const value = Math.max(0, Math.min(100, Number(input.value) + Number(btn.dataset.step))) / 100;
      setVolume(id, value);
    }));
    $('.mute-button', el).addEventListener('click', () => toggleMute(id));
    const preset = $('.eq-button', el), device=$('button.device-button',el);
    if (preset) preset.addEventListener('click', () => channelSheet(id,'eq'));
    if (device) device.addEventListener('click', () => channelSheet(id,'device'));
  });
  $('#stage').classList.toggle('no-shortcuts',!preferences.shortcuts.length);
  $('#shortcuts').classList.toggle('icons-only',!preferences.shortcutLabels);
  $('#shortcuts').innerHTML = preferences.shortcuts.map(action => `<button class="shortcut" data-action="${action}" title="${actionNames[action]}" aria-label="${actionNames[action]}">${svg(preferences.shortcutAppearance?.[action]?.icon||actionIcons[action])}<span>${esc(preferences.shortcutAppearance?.[action]?.label||actionNames[action])}</span></button>`).join('');
  $$('.shortcut').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.action;
    try {
      if (['mic','media','master'].includes(action)) await toggleMute(action);
      else if (['musicbee','sonar'].includes(action)) await execute('/api/launch', {app:action});
      else await musicAction(action);
    } catch {}
  }));
  update();
}
function localVolume(id, value) {
  const el = $(`[data-channel="${id}"]`); if (!el) return;
  $('.volume-readout>span',el).textContent = Math.round(value * 100);
  $('.fader',el).value = Math.round(value * 100);
  $('.fader-fill',el).style.setProperty('--level', `${value * 100}%`);
}
function setVolume(id, value) {
  localVolume(id, value); edited.set(id, Date.now() + 1200);
  const pending = writes.get(id) || {running:false}; pending.value = value; writes.set(id,pending);
  if (pending.timer) clearTimeout(pending.timer);
  if (!pending.running) pending.timer = setTimeout(() => flushVolume(id), 55);
}
async function flushVolume(id) {
  const pending = writes.get(id); if (!pending || pending.running || pending.value === undefined) return;
  pending.running = true; const value = pending.value; pending.value = undefined;
  try { state.sonar = await execute('/api/sonar', {channel:id,action:'volume',value}); }
  catch { edited.delete(id); }
  finally {
    pending.running = false;
    if (pending.value !== undefined) flushVolume(id);
    else { writes.delete(id); edited.set(id, Date.now() + 250); update(); }
  }
}
async function toggleMute(id) {
  const channel = state.sonar?.channels?.[id]; if (!state.sonar?.connected || !channel?.available) return;
  try { state.sonar = await execute('/api/sonar', {channel:id,action:'mute',value:!channel.muted}); update(); } catch {}
}
function update() {
  const sonar = state.sonar || {}, music = state.music || {};
  EdgeVisuals.syncMusic(music);
  EdgeVisuals.artwork(music,!$('#overlay').hidden&&settingsTab==='effects'&&draft?draft:preferences);
  const mix=sonar.chatMix||{},canMix=!!(sonar.connected&&mix.canControl);
  $('#chatmix').disabled=!canMix;$('#chatmix-center').disabled=!canMix;
  $('#chatmix-control').classList.toggle('hardware',!canMix);
  $('#chatmix-note').hidden=canMix||!sonar.connected;
  $('#chatmix-note').textContent=mix.message||'Unavailable';
  if(Number.isFinite(mix.balance)&&!(edited.get('chatmix')>Date.now())&&!chatmixWrite.running&&chatmixWrite.value===undefined)$('#chatmix').value=Math.round(mix.balance*100);
  const balance=Number($('#chatmix').value);
  $('#chatmix').title=canMix?(balance===0?'ChatMix centered':`${balance<0?'Game':'Chat'} +${Math.abs(balance)}%`):mix.message||'ChatMix unavailable';
  $('#chatmix').setAttribute('aria-valuetext',balance===0?'Centered':`${Math.abs(balance)} percent toward ${balance<0?'Game':'Chat'}`);
  const online = sonar.connected && music.connected;
  $('#connection').textContent = disconnected ? 'Bridge offline · reconnecting' : online ? 'All systems connected' : sonar.connected ? 'Waiting for MusicBee' : music.connected ? 'Waiting for Sonar' : 'Connecting to apps';
  $('#sonar-dot').classList.toggle('online',!!sonar.connected);
  $('#music-dot').classList.toggle('online',!!music.connected);
  $('#sonar-mode').textContent = sonar.connected ? (sonar.mode === 'classic' ? 'CLASSIC' : 'STREAM · MONITOR MIX') : 'OFFLINE';
  $('#sonar-mode').title = sonar.message || '';
  $$('.channel').forEach(el => {
    const id = el.dataset.channel, ch = sonar.channels?.[id];
    const available = !!(sonar.connected && ch?.available), enabled = available && ch.enabled;
    if (available && !(edited.get(id) > Date.now()) && !writes.has(id)) localVolume(id, ch.volume);
    if (!available) $('.volume-readout>span',el).textContent = '—';
    $('.fader',el).disabled = !enabled;
    $$('[data-step]',el).forEach(b => b.disabled = !enabled);
    const mute = $('.mute-button',el); mute.disabled = !enabled;
    mute.setAttribute('aria-pressed',String(!!ch?.muted));
    mute.setAttribute('aria-label',`${ch?.muted?'Unmute':'Mute'} ${preferences.channels.find(c=>c.id===id)?.label||id}`);
    mute.innerHTML = svg(ch?.muted ? 'muted':'volume') + `<span>${ch?.muted ? 'Unmute':'Mute'}</span>`;
    el.classList.toggle('is-muted',!!ch?.muted); el.classList.toggle('is-disabled',available && !ch.enabled);
    const preset = $('.eq-button',el), device=$('button.device-button',el);
    if (preset) { preset.disabled = !available; preset.title = `EQ · ${ch?.preset?.name||'Choose preset'}`; }
    if (device) {
      device.disabled=!available;
      const name=ch?.deviceName, shortName=name?.replace(/^(?:Headphones|Speakers|Headset|Microphone) \((.*)\)$/i,'$1').replace(/ \(VB-Audio[^)]*\)$/i,'');
      $('.device-name',device).textContent=!available?'Offline':!ch.enabled?'Off in Sonar':shortName||'Choose device';
      device.title=name?`${name}${ch.deviceAvailable===false?' · Disconnected':''}`:'Choose audio device';
      device.classList.toggle('device-offline',ch?.deviceAvailable===false);
    }
  });
  $('#play-state').textContent = music.connected ? (music.playing ? 'PLAYING' : music.playbackStatus === 3 ? 'STOPPED' : 'PAUSED') : 'OFFLINE';
  const playerName=music.name || 'MusicBee';
  $('#player-name').textContent=playerName;
  $('#track-title').textContent = music.connected ? music.title || 'No track selected' : playerName;
  $('#track-artist').textContent = music.connected ? music.artist || '' : 'Offline';
  $('#track-album').textContent = music.connected ? music.album || '' : music.message || '';
  const art = music.connected && music.art;
  if (art && $('#artwork').getAttribute('src') !== art) $('#artwork').src = art;
  $('#artwork').hidden = !art; $('#art-placeholder').hidden = !!art;
  $$('.transport [data-music]').forEach(btn => {
    const supported=!!(music.connected && music.controls?.[btn.dataset.music]);
    btn.disabled=!supported;
    btn.hidden=['shuffle','repeat'].includes(btn.dataset.music)&&!supported;
  });
  $('#play').innerHTML = svg(music.playing ? 'pause' : 'play');
  $('#play').setAttribute('aria-label',`${music.playing ? 'Pause':'Play'} ${playerName}`);
  for (const [action,label] of Object.entries({previous:'Previous track',next:'Next track',shuffle:'Shuffle',repeat:'Repeat'})) $('[data-music="'+action+'"]').setAttribute('aria-label',`${label} · ${playerName}`);
  $('[data-music="shuffle"]').setAttribute('aria-pressed',String(!!music.shuffle));
  $('[data-music="shuffle"]').title = music.controls?.shuffle ? 'Toggle shuffle' : 'Shuffle is unavailable through this media session';
  $('[data-music="repeat"]').setAttribute('aria-pressed',String(!!music.repeat));
  $('[data-music="repeat"]').title = music.controls?.repeat ? ['Repeat off','Repeat track','Repeat all'][music.repeat || 0] : 'Repeat is unavailable through this media session';
  $('#repeat-one').hidden = music.repeat !== 1;
  const hasTimeline = music.connected && music.duration > 0;
  $('#timeline').hidden = !hasTimeline;
  if (hasTimeline) {
    const format = s => `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
    $('#elapsed').textContent = format(music.position); $('#duration').textContent = format(music.duration);
    if (!draggingMusic.has('seek') && !(edited.get('seek')>Date.now())) { $('#seek').max = music.duration; $('#seek').value = music.position; }
    $('#seek').disabled = !music.controls?.seek;
  }
  const hasVolume=music.connected&&music.controls?.volume&&Number.isFinite(music.volume);
  $('#music-volume').disabled=!hasVolume;
  if(!draggingMusic.has('music-volume')&&!(edited.get('music-volume')>Date.now())){
    $('#music-volume-value').textContent=hasVolume?`${Math.round(music.volume*100)}%`:'—';
    if(hasVolume)$('#music-volume').value=Math.round(music.volume*100);
  }
  $('.music-volume-control').title=hasVolume?`${playerName} volume`:playerName==='MusicBee'?'Install the MusicBee helper in Customize → Music app':'This app does not report volume';
  $('#musicbee-helper').hidden=playerName!=='MusicBee'||hasVolume||!window.SONAR_EDGE_NATIVE;
  $$('.shortcut').forEach(button => {
    const action = button.dataset.action, channel = sonar.channels?.[action];
    button.classList.toggle('active',!!channel?.muted);
    const label=preferences.shortcutAppearance?.[action]?.label||(['mic','media','master'].includes(action)&&channel?.muted?actionNames[action].replace('Mute','Unmute'):action==='playpause'?(music.playing?'Pause music':'Play music'):actionNames[action]);
    $('span',button).textContent=label;
    button.title=label;button.setAttribute('aria-label',label);
    if(['mic','media','master'].includes(action))button.setAttribute('aria-pressed',String(!!channel?.muted));
    const icon=shortcutIcon(action,preferences.shortcutAppearance?.[action],music.playing,channel?.muted);
    const oldIcon=$('svg',button);if(oldIcon.dataset.name!==icon){oldIcon.outerHTML=svg(icon);$('svg',button).dataset.name=icon;}
    button.disabled = ['musicbee','sonar'].includes(action) ? false : ['mic','media','master'].includes(action) ? !sonar.connected || !channel?.available || !channel.enabled : !music.connected || !music.controls?.[action];
  });
}
async function musicAction(action, value) {
  state.music = await execute('/api/music', {action,value}); update();
}
function setChatMix(value){
  $('#chatmix').value=Math.round(value*100);edited.set('chatmix',Date.now()+1200);
  chatmixWrite.value=value;clearTimeout(chatmixWrite.timer);
  if(!chatmixWrite.running)chatmixWrite.timer=setTimeout(flushChatMix,60);
}
async function flushChatMix(){
  if(chatmixWrite.running||chatmixWrite.value===undefined)return;
  chatmixWrite.running=true;const value=chatmixWrite.value;chatmixWrite.value=undefined;
  try{state.sonar=await execute('/api/sonar',{action:'chatmix',value});}
  catch{edited.delete('chatmix');}
  finally{chatmixWrite.running=false;if(chatmixWrite.value!==undefined)flushChatMix();else{edited.set('chatmix',Date.now()+250);update();}}
}
$('#chatmix').addEventListener('input',()=>setChatMix(Number($('#chatmix').value)/100));
$('#chatmix-center').addEventListener('click',()=>setChatMix(0));
$$('[data-music]').forEach(btn => btn.addEventListener('click',() => musicAction(btn.dataset.music).catch(()=>{})));
$('#seek').addEventListener('change',() => musicAction('seek', Number($('#seek').value)).catch(()=>{}));
for(const id of ['seek','music-volume']){
  $('#'+id).addEventListener('pointerdown',()=>draggingMusic.add(id));
  $('#'+id).addEventListener('input',()=>edited.set(id,Date.now()+1200));
}
window.addEventListener('pointerup',()=>draggingMusic.clear());
window.addEventListener('pointercancel',()=>draggingMusic.clear());
$('#music-volume').addEventListener('input',()=>$('#music-volume-value').textContent=`${$('#music-volume').value}%`);
$('#music-volume').addEventListener('change',()=>musicAction('volume',Number($('#music-volume').value)/100).catch(()=>{}));
$('#musicbee-helper').addEventListener('click',installMusicBeeHelper);
async function installMusicBeeHelper(){try{const result=await nativeApi('install_musicbee_helper');toast(result.message);}catch(e){toast(e.message);}}
$('#artwork').addEventListener('error',() => { $('#artwork').hidden = true; $('#art-placeholder').hidden = false; });

function openSheet(title,kicker) {
  $('.sheet').classList.remove('settings-sheet');
  lastFocus = document.activeElement;
  $('#sheet-title').textContent = title; $('#sheet-kicker').textContent = kicker;
  $('#overlay').hidden = false; $('.workspace').inert = true; $('footer').inert = true; $('.topbar').inert = true;
  $('.sheet').focus();
}
function closeSheet() {
  clearTimeout(updateTimer);
  $('#overlay').hidden = true; sheetChannel = null;
  if(preferences)document.documentElement.style.setProperty('--text-scale',preferences.appearance.textScale||1);
  if(preferences)EdgeVisuals.artwork(state.music||{},preferences);
  $('.workspace').inert = false; $('footer').inert = false; $('.topbar').inert = false;
  if (lastFocus?.isConnected) lastFocus.focus();
}
$('#close-sheet').addEventListener('click',closeSheet);
$('#overlay').addEventListener('click',e => { if (e.target === $('#overlay')) closeSheet(); });
document.addEventListener('keydown',e => {
  if ($('#overlay').hidden) return;
  if (e.key === 'Escape') closeSheet();
  if (e.key === 'Tab') {
    const fields = $$('button,input,select', $('.sheet')).filter(el => !el.disabled && el.offsetParent);
    const first = fields[0], last = fields.at(-1);
    if (e.shiftKey && (document.activeElement === first || document.activeElement === $('.sheet'))) { last.focus(); e.preventDefault(); }
    else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
  }
});
function collectDraft() {
  if($('#app-default'))defaultVersionDraft=$('#app-default').value;
  if($('#settings-startup'))startupDraft=$('#settings-startup').checked;
  if ($('#settings-layout')) {
    draft.layout = $('#settings-layout').value; draft.playerSide = $('#settings-side').value;
    draft.showClock = $('#settings-clock').checked; draft.showArtwork = $('#settings-artwork').checked;
    draft.playerApp = $('#settings-player').value;
  }
  if ($('#settings-accent')) {
    draft.accent = $('#settings-accent').value;
    for (const key of ['panelColor','panelOpacity','textColor','mutedColor','roundness','font','textScale','artworkSize']) {
      const input=$('#appearance-'+key); draft.appearance[key]=['panelOpacity','roundness','textScale','artworkSize'].includes(key)?Number(input.value):input.value;
    }
  }
  if ($('#background-kind')) {
    for (const key of ['kind','source','color','color2','dim','blur','fit','angle']) {
      const input=$('#background-'+key); draft.background[key]=['dim','blur','angle'].includes(key)?Number(input.value):input.value;
    }
  }
  $$('.channel-setting-row').forEach(row => {
    const item = draft.channels.find(c => c.id === row.dataset.id);
    item.visible = $('input[type=checkbox]',row).checked; item.label = $('input[type=text]',row).value; item.color = $('input[type=color]',row).value;
  });
  if ($('#shortcut-labels')) {
    draft.shortcutLabels=$('#shortcut-labels').checked;
    draft.shortcuts=$$('.action-setting-row').map(row=>$('.shortcut-select',row).value);
    $$('.action-setting-row').forEach(row=>{
      const action=$('.shortcut-select',row).value,label=$('.action-label',row).value.trim(),icon=$('.action-icon',row).value,style={};
      if(label)style.label=label;
      if(icon!==actionIcons[action])style.icon=icon;
      draft.shortcutAppearance[action]=style;
    });
  }
  if($('#settings-meters'))draft.showMeters=$('#settings-meters').checked;
  if($('#settings-chatmix'))draft.showChatMix=$('#settings-chatmix').checked;
  if($('#effects-colors')){
    for(const key of ['colors','playerBackground','mixerBackground','appBackground'])draft.artworkEffects[key]=$('#effects-'+key).value;
    draft.artworkEffects.motion=$('#effects-motion').checked;
    draft.artworkEffects.intensity=Number($('#effects-intensity').value);
    draft.artworkEffects.blur=Number($('#effects-blur').value);
  }
}
async function renderBrightnessSettings(){
  const host=$('#brightness-settings');
  try{
    const info=await get('/api/display');
    if(!host?.isConnected)return;
    host.innerHTML=`<h3>XENEON EDGE brightness</h3>${info.displays.map(d=>d.brightness===null?`<p class="settings-help" role="status">${esc(d.error)}</p>`:`<label class="field range-field"><span class="range-label">${esc(d.name)}<output>${d.brightness}%</output></span><input type="range" min="0" max="100" step="1" value="${d.brightness}" data-brightness-id="${esc(d.id)}" aria-label="${esc(d.name)} brightness"></label>`).join('')}${info.message?`<p class="settings-help" role="status">${esc(info.message)}</p>`:''}<p class="settings-help">Changes the display brightness immediately.</p><button class="button secondary" id="refresh-brightness">Refresh display</button>`;
    host.querySelector('#refresh-brightness').addEventListener('click',renderBrightnessSettings);
    host.querySelectorAll('[data-brightness-id]').forEach(input=>{
      const output=input.closest('label').querySelector('output');
      let timer=null,pending=false,desired=null,confirmed=Number(input.value);
      async function apply(){
        clearTimeout(timer);
        if(pending||desired===null||!input.isConnected)return;
        const value=desired;desired=null;pending=true;
        try{
          const result=await execute('/api/display',{action:'brightness',id:input.dataset.brightnessId,value});
          confirmed=result.brightness;
          if(desired===null&&input.isConnected){input.value=confirmed;output.value=confirmed+'%';}
        }catch{
          desired=null;
          if(input.isConnected){input.value=confirmed;output.value=confirmed+'%';}
        }finally{pending=false;if(desired!==null)apply();}
      }
      input.addEventListener('input',()=>{output.value=input.value+'%';desired=Number(input.value);clearTimeout(timer);timer=setTimeout(apply,120);});
      input.addEventListener('change',()=>{desired=Number(input.value);apply();});
    });
  }catch(error){if(host?.isConnected)host.textContent=error.message;}
}
function settingsContent() {
  $('.sheet').classList.add('settings-sheet');
  const options = (choices,value) => choices.map(([v,label]) => `<option value="${v}"${v===value?' selected':''}>${label}</option>`).join('');
  const field=(label,id,choices,value)=>`<label class="field">${label}<select id="${id}">${options(choices,value)}</select></label>`;
  const color=(label,id,value)=>`<label class="color-field">${label}<input type="color" id="${id}" value="${value}"></label>`;
  const range=(label,id,value,min,max,step,display)=>`<label class="field range-field"><span class="range-label">${label}<output>${display}</output></span><input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${value}"></label>`;
  let content='';
  if(settingsTab==='window')content=`<div class="settings-grid ${window.SONAR_EDGE_NATIVE?'two-columns':'display-only'}"><div class="settings-column" id="brightness-settings">Reading display brightness…</div>${window.SONAR_EDGE_NATIVE?'<div class="settings-column" id="window-settings">Loading window settings…</div>':''}</div>`;
  if(settingsTab==='updates'){
    const u=updateInfo,busy=['checking','downloading','installing'].includes(u?.status);
    content=u?`<div class="update-card"><span class="eyebrow">INSTALLED VERSION ${esc(u.currentVersion)}</span><h3>${esc(u.message)}</h3><div class="update-buttons"><button class="button secondary" id="check-updates"${busy?' disabled':''}>Check for updates</button>${u.status==='available'?`<button class="button primary" id="install-update"${u.installed?'':' disabled'}>Download & install ${esc(u.version)}</button>`:''}${u.status==='downloading'?'<button class="button secondary" id="cancel-update">Cancel download</button>':''}</div>${['downloading','installing'].includes(u.status)?`<div class="update-progress"><progress max="100" value="${Number(u.progress)||0}"></progress><span>${Number(u.progress)||0}%</span></div>`:''}${!u.installed?'<p class="settings-help">Install Sonar Edge with Setup to enable in-app installation.</p>':''}${u.notes?`<h4>Release notes</h4><div class="update-notes">${esc(u.notes)}</div>`:''}</div><details class="update-source"><summary>GitHub repository</summary><div class="update-source-field"><input id="update-repository" type="text" value="${esc(u.repository)}" aria-label="GitHub update repository" placeholder="owner/repository"${busy?' disabled':''}><button class="button secondary" id="save-update-source"${busy?' disabled':''}>Save repository</button></div></details>`:'<p class="settings-help">Loading update settings…</p>';
  }
  if(settingsTab==='version')content=appVersionInfo?`<div class="version-cards">${[
    ['desktop','Desktop','iCUE Screen Setup: Desktop · opens on your Xeneon Edge','expand','Open desktop'],
    ['iframe','iCUE iframe','iCUE Screen Setup: iCUE Widgets · widget size XL','sliders','Use iCUE widget']
  ].map(([mode,title,description,icon,action])=>`<section class="version-card${appVersionInfo.current===mode?' current':''}"><div class="version-heading">${svg(icon)}<h3>${title}</h3>${appVersionInfo.current===mode?'<span class="version-current">CURRENT</span>':''}</div><p>${description}</p><button class="button primary" data-open-version="${mode}"${mode==='iframe'&&appVersionInfo.widgetReady===false?' disabled':''}>${action}</button>${mode==='iframe'?`<button class="button secondary" id="find-widget"${appVersionInfo.widgetAvailable?'':' disabled'}>Find XL widget</button>`:''}</section>`).join('')}</div>${appVersionInfo.widgetError?`<p class="settings-help" role="status">${esc(appVersionInfo.widgetError)}</p>`:''}<div class="version-options">${field('Open SonarEdge.exe as','app-default',[['desktop','Desktop'],['iframe','iCUE iframe']],defaultVersionDraft)}<p class="settings-help">One app and one tray icon serve both views, with shared layouts, backgrounds and audio controls.</p><button class="button secondary" id="icue-guide"${appVersionInfo.guideAvailable?'':' disabled'}>iCUE setup guide</button></div><div class="startup-options"><label class="check"><input type="checkbox" id="settings-startup"${startupDraft?' checked':''}${appVersionInfo.startup?.available?'':' disabled'}>Start with Windows</label><p class="settings-help">Starts Sonar Edge in your selected view when you sign in.</p></div><details class="iframe-details"><summary>Use iCUE’s iFrame widget</summary><label class="field">Widget URL<input id="iframe-url" type="text" readonly value="${esc(appVersionInfo.iframeUrl)}"></label><div class="iframe-copy"><button class="button secondary" data-copy-iframe="url">Copy URL</button><button class="button secondary" data-copy-iframe="html">Copy iframe HTML</button></div><textarea id="iframe-html" readonly aria-label="Iframe HTML" rows="3">${esc(appVersionInfo.iframeHtml)}</textarea></details>`:'<p class="settings-help">Open SonarEdge.exe from the complete shared package to choose Desktop or iCUE iframe.</p>';
  if (settingsTab==='layout') content=`<div class="settings-grid"><div class="settings-column"><h3>Layout</h3>
    ${field('Panel sizes','settings-layout',[['compact','Compact player'],['balanced','Equal panels'],['mixer','Larger mixer'],['music','Larger player']],draft.layout)}
    ${field('Player position','settings-side',[['left','Left'],['right','Right']],draft.playerSide)}
    <label class="check"><input type="checkbox" id="settings-clock"${draft.showClock?' checked':''}>Clock</label>
    <label class="check"><input type="checkbox" id="settings-artwork"${draft.showArtwork?' checked':''}>Album artwork</label></div>
    <div class="settings-column"><h3>Music app</h3>${field('Player','settings-player',playerOptions.map(p=>[esc(p.id),esc(p.name)]),draft.playerApp)}
    <button class="button secondary" id="refresh-players">Refresh apps</button><p class="settings-help">Open a player with Windows media controls enabled to add it to this list.</p>${window.SONAR_EDGE_NATIVE?'<button class="button secondary" id="install-bee-helper">Install MusicBee helper</button><p class="settings-help">Adds playback progress, seeking and player volume. Restart MusicBee after installing.</p>':''}</div>
    <div class="settings-column"><h3>Settings file</h3><button class="button secondary" id="export-settings">Export settings</button><p class="settings-help">Download your layout and appearance as a JSON file.</p><label class="button secondary" style="cursor:pointer;margin-top:16px">Import settings<input type="file" id="import-settings" accept="application/json,.json" hidden></label></div></div>`;
  if (settingsTab==='appearance') {
    const a=draft.appearance;
    content=`<div class="settings-grid"><div class="settings-column"><h3>Colors</h3>${color('Accent','settings-accent',draft.accent)}${color('Panel color','appearance-panelColor',a.panelColor)}${color('Text','appearance-textColor',a.textColor)}${color('Secondary text','appearance-mutedColor',a.mutedColor)}</div>
    <div class="settings-column"><h3>Style</h3>${field('Text size','appearance-textScale',[['1','Comfortable'],['1.12','Large'],['1.25','Extra large']],String(a.textScale||1))}${field('Artwork size','appearance-artworkSize',[['168','Compact'],['224','Large'],['256','Extra large']],String(a.artworkSize||256))}${field('Font','appearance-font',[['system','System'],['rounded','Rounded'],['mono','Monospace']],a.font)}${range('Panel opacity','appearance-panelOpacity',a.panelOpacity,.15,1,.01,Math.round(a.panelOpacity*100)+'%')}${range('Corner radius','appearance-roundness',a.roundness,0,36,1,a.roundness+' px')}</div>
    <div class="settings-column"><h3>Themes</h3><div class="theme-swatches">${[['Mint','#191e26','#8de4c7'],['Lavender','#211d31','#c9b0ff'],['Amber','#261f1b','#ffc781'],['Ice','#172733','#a9dbff'],['Rose','#2b1b24','#f5abc7']].map(([name,panel,accent])=>`<button class="theme-swatch" data-panel="${panel}" data-accent="${accent}" title="${name}" aria-label="${name} theme" style="background:${panel}"><i style="background:${accent}"></i></button>`).join('')}</div></div></div>`;
  }
  if (settingsTab==='background') {
    const b=draft.background;
    content=`<div class="settings-grid"><div class="settings-column"><h3>Background</h3>${field('Type','background-kind',[['solid','Solid color'],['gradient','Gradient'],['image','Image / GIF'],['video','Video']],b.kind)}
    <div class="background-upload"><label class="button secondary" style="cursor:pointer">Upload file<input type="file" id="background-file" accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm" hidden></label><span class="upload-name" id="upload-name">PNG · JPG · GIF · WebP · MP4 · WebM</span></div>
    <label class="field">Image or video URL<input type="text" id="background-source" value="${esc(b.source)}" placeholder="https://…"></label>
    ${field('Image fit','background-fit',[['cover','Cover'],['contain','Contain'],['fill','Stretch']],b.fit)}</div>
    <div class="settings-column"><h3>Adjust</h3>${color('Color 1','background-color',b.color)}${color('Color 2','background-color2',b.color2)}${range('Gradient angle','background-angle',b.angle,0,360,1,b.angle+'°')}${range('Dimming','background-dim',b.dim,0,.95,.01,Math.round(b.dim*100)+'%')}${range('Blur','background-blur',b.blur,0,24,1,b.blur+' px')}</div>
    <div class="settings-column"><h3>Preview</h3><div class="background-preview" id="background-preview"></div></div></div>`;
  }
  if(settingsTab==='effects'){
    const fx=draft.artworkEffects;
    content=`<div class="settings-grid effects-grid"><div class="settings-column"><h3>Album colors</h3>${field('Apply colors to','effects-colors',[['off','Off'],['music','Music panel'],['all','Whole app']],fx.colors)}<div class="effect-swatches" id="effect-swatches"></div><div class="effect-preview" id="effect-preview"><div class="ambient enabled"><div class="ambient-layer visible"></div></div><span>Album artwork preview</span></div></div><div class="settings-column"><h3>Backgrounds</h3>${field('Music panel','effects-playerBackground',[['off','Off'],['artwork','Blurred album artwork'],['colors','Album color wash']],fx.playerBackground)}${field('Sonar mixer','effects-mixerBackground',[['match','Match music panel'],['off','Off'],['artwork','Blurred album artwork'],['colors','Album color wash']],fx.mixerBackground||'match')}${field('Whole app','effects-appBackground',[['off','Off'],['artwork','Blurred album artwork'],['colors','Album color wash']],fx.appBackground)}<p class="settings-help">Follows the current album. Your custom background returns when this is off.</p></div><div class="settings-column"><h3>Motion & detail</h3><label class="check"><input type="checkbox" id="effects-motion"${fx.motion?' checked':''}>Animate background</label>${range('Intensity','effects-intensity',fx.intensity,.1,.8,.01,Math.round(fx.intensity*100)+'%')}${range('Blur','effects-blur',fx.blur,24,90,1,fx.blur+' px')}</div></div>`;
  }
  if (settingsTab==='channels') content=`<div class="settings-grid two-columns"><div class="settings-column"><h3>Channels</h3>
    ${draft.channels.map((c,i)=>`<div class="channel-setting-row" data-id="${c.id}"><input type="checkbox" aria-label="Show ${esc(c.label)}"${c.visible?' checked':''}><input type="text" aria-label="${c.id} channel label" maxlength="24" value="${esc(c.label)}"><input type="color" aria-label="${c.id} channel color" value="${c.color}"><button class="icon-button quiet" data-move="-1" data-id="${c.id}" aria-label="Move ${esc(c.label)} left"${i===0?' disabled':''}>${svg('up')}</button><button class="icon-button quiet" data-move="1" data-id="${c.id}" aria-label="Move ${esc(c.label)} right"${i===draft.channels.length-1?' disabled':''}>${svg('down')}</button></div>`).join('')}</div>
    <div class="settings-column"><h3>Channel layout</h3><label class="check"><input type="checkbox" id="settings-meters"${draft.showMeters?' checked':''}>Live audio meters</label><label class="check"><input type="checkbox" id="settings-chatmix"${draft.showChatMix?' checked':''}>ChatMix control</label><p class="settings-help">Meters show live channel activity before Sonar volume. Master summarizes output activity.</p><p class="settings-help">Choose which channels appear, rename them, change their colors, and move them with the arrows.</p></div></div>`;
  if(settingsTab==='actions')content=`<label class="check actions-label-toggle"><input type="checkbox" id="shortcut-labels"${draft.shortcutLabels?' checked':''}>Show button labels</label><div class="action-column-headings"><span>Action</span><span>Button label</span><span>Icon</span><span>Order</span></div><div class="action-setting-list">${draft.shortcuts.map((action,i)=>`<div class="action-setting-row" data-index="${i}"><select class="shortcut-select" aria-label="Action ${i+1}">${options(Object.entries(actionNames),action)}</select><input class="action-label" type="text" maxlength="24" value="${esc(draft.shortcutAppearance?.[action]?.label||'')}" placeholder="${actionNames[action]}" aria-label="Button ${i+1} label"><select class="action-icon" aria-label="Button ${i+1} icon">${options(Object.entries(editableIcons),draft.shortcutAppearance?.[action]?.icon||actionIcons[action])}</select><div class="action-order"><button class="icon-button quiet" data-action-move="-1" aria-label="Move action ${i+1} left"${i===0?' disabled':''}>${svg('up')}</button><button class="icon-button quiet" data-action-move="1" aria-label="Move action ${i+1} right"${i===draft.shortcuts.length-1?' disabled':''}>${svg('down')}</button><button class="icon-button quiet" data-action-remove aria-label="Remove action ${i+1}">${svg('close')}</button></div></div>`).join('')}</div><button class="button secondary" id="add-action"${draft.shortcuts.length>=8?' disabled':''}>${svg('plus')}Add action</button>`;
  $('#sheet-content').innerHTML=`<nav class="settings-tabs" aria-label="Settings categories">${[['layout','Layout & player'],['appearance','Appearance'],['effects','Artwork effects'],['background','Background'],['channels','Mixer channels'],['actions','Bottom buttons'],['version','App version'],['window',window.SONAR_EDGE_NATIVE?'Window & display':'Display'],['updates','Updates']].map(([id,label])=>`<button class="settings-tab${id===settingsTab?' active':''}" data-settings-tab="${id}" aria-current="${id===settingsTab?'page':'false'}">${label}</button>`).join('')}</nav><div class="settings-body">${content}</div><div class="settings-actions"><button class="button secondary" id="cancel-settings">Cancel</button><button class="button primary" id="save-settings">Save changes</button></div>`;
  if(settingsTab==='window')renderBrightnessSettings();
  if(settingsTab==='window'&&window.SONAR_EDGE_NATIVE)renderWindowSettings();
  $$('[data-open-version]').forEach(button=>button.addEventListener('click',async()=>{
    button.disabled=true;try{const result=await execute('/api/app',{action:'open',mode:button.dataset.openVersion});toast(result.message);}catch{}finally{button.disabled=false;}
  }));
  for(const [id,action] of [['check-updates','check'],['install-update','install'],['cancel-update','cancel'],['save-update-source','source']])if($('#'+id))$('#'+id).addEventListener('click',async()=>{
    if(action==='install'){
      collectDraft();
      if(JSON.stringify(draft)!==JSON.stringify(preferences)||defaultVersionDraft!==appVersionInfo?.default||startupDraft!==!!appVersionInfo?.startup?.enabled)return toast('Save your settings before installing an update.');
    }
    try{updateInfo=await execute('/api/update',{action,...(action==='source'?{repository:$('#update-repository').value.trim()}:{})});settingsContent();scheduleUpdateRefresh();}catch{}
  });
  if(settingsTab==='updates'&&!updateInfo)refreshUpdates();
  for(const [id,action] of [['find-widget','widget'],['icue-guide','guide']])if($('#'+id))$('#'+id).addEventListener('click',()=>execute('/api/app',{action}).catch(()=>{}));
  $$('[data-copy-iframe]').forEach(button=>button.addEventListener('click',async()=>{
    const field=button.dataset.copyIframe==='url'?$('#iframe-url'):$('#iframe-html');
    try{await navigator.clipboard.writeText(field.value);toast('Copied.');}catch{field.focus();field.select();toast('Select Copy to copy the selected text.');}
  }));
  $$('[data-settings-tab]').forEach(b=>b.addEventListener('click',()=>{collectDraft();clearTimeout(updateTimer);settingsTab=b.dataset.settingsTab;if(settingsTab==='updates')updateInfo=null;settingsContent();}));
  if($('#appearance-textScale'))$('#appearance-textScale').addEventListener('change',e=>{
    draft.appearance.textScale=Number(e.target.value);
    document.documentElement.style.setProperty('--text-scale',draft.appearance.textScale);
  });
  $$('[data-move]').forEach(b => b.addEventListener('click',() => {
    collectDraft(); const i = draft.channels.findIndex(c=>c.id===b.dataset.id), j=i+Number(b.dataset.move);
    [draft.channels[i],draft.channels[j]]=[draft.channels[j],draft.channels[i]]; settingsContent();
  }));
  $$('[data-action-move]').forEach(b=>b.addEventListener('click',()=>{collectDraft();const i=Number(b.closest('.action-setting-row').dataset.index),j=i+Number(b.dataset.actionMove);[draft.shortcuts[i],draft.shortcuts[j]]=[draft.shortcuts[j],draft.shortcuts[i]];settingsContent();}));
  $$('[data-action-remove]').forEach(b=>b.addEventListener('click',()=>{collectDraft();draft.shortcuts.splice(Number(b.closest('.action-setting-row').dataset.index),1);settingsContent();}));
  $$('.shortcut-select').forEach(select=>select.addEventListener('change',()=>{const row=select.closest('.action-setting-row'),action=select.value;$('.action-label',row).value=draft.shortcutAppearance?.[action]?.label||'';$('.action-label',row).placeholder=actionNames[action];$('.action-icon',row).value=draft.shortcutAppearance?.[action]?.icon||actionIcons[action];}));
  if($('#add-action'))$('#add-action').addEventListener('click',()=>{collectDraft();draft.shortcuts.push(Object.keys(actionNames).find(a=>!draft.shortcuts.includes(a))||'playpause');settingsContent();});
  if($('#install-bee-helper'))$('#install-bee-helper').addEventListener('click',installMusicBeeHelper);
  $('#cancel-settings').addEventListener('click',closeSheet);
  $$('.range-field input').forEach(input=>input.addEventListener('input',()=>{
    const v=Number(input.value);$('output',input.closest('label')).textContent=input.id.includes('Opacity')||input.id.endsWith('-dim')||input.id.endsWith('-intensity')?Math.round(v*100)+'%':input.id.endsWith('-angle')?v+'°':v+' px';
  }));
  if($('#effects-colors')){
    const preview=()=>{
      collectDraft();const fx=draft.artworkEffects,music=state.music||{},colors=EdgeVisuals.theme(music.palette,draft.accent),el=$('#effect-preview');
      $('#effect-swatches').innerHTML=[colors.accent,colors.secondary,colors.background].map(c=>`<i style="background:${c}"></i>`).join('');
      const layer=$('.ambient-layer',el);
      layer.style.backgroundImage=music.art?`url(${JSON.stringify(music.art)})`:`linear-gradient(120deg,${colors.accent},${colors.secondary})`;
      el.style.setProperty('--ambient-blur',`${fx.blur}px`);el.classList.toggle('preview-motion',fx.motion);
      EdgeVisuals.artwork(music,draft);
    };
    preview();$$('[id^="effects-"]').filter(el=>el.matches('input,select')).forEach(el=>el.addEventListener('input',preview));
  }
  $$('[data-panel]').forEach(button=>button.addEventListener('click',()=>{collectDraft();draft.appearance.panelColor=button.dataset.panel;draft.accent=button.dataset.accent;settingsContent();}));
  if ($('#refresh-players')) $('#refresh-players').addEventListener('click',async()=>{collectDraft();try{playerOptions=await get('/api/players');settingsContent();}catch(e){toast(e.message);}});
  if ($('#export-settings')) $('#export-settings').addEventListener('click',async()=>{collectDraft();if(window.SONAR_EDGE_NATIVE){try{await nativeApi('export_settings',draft);}catch(e){toast(e.message);}return;}const blob=new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='sonar-edge-settings.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  if ($('#import-settings')) $('#import-settings').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>16000)throw Error('Choose an Edge Audio settings file');const data=JSON.parse(await file.text());draft=await execute('/api/validate-preferences',data);settingsContent();}catch(err){toast(err.message);}});
  if ($('#background-file')) $('#background-file').addEventListener('change',async e=>{
    const file=e.target.files[0];if(!file)return;collectDraft();
    if(file.size>64*1024*1024)return toast('Choose a background smaller than 64 MB.');
    $('#upload-name').textContent='Uploading…';
    try{const response=await fetch('/api/background',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Edge-Token':token},body:file});const data=await response.json();if(!response.ok)throw Error(data.error);draft.background.source=data.source;draft.background.kind=data.kind;settingsContent();}
    catch(err){toast(err.message);$('#upload-name').textContent='Upload failed';}
  });
  if ($('#background-preview')) {
    const preview=()=>{
      collectDraft();const b=draft.background,el=$('#background-preview');
      el.style.background=b.kind==='gradient'?`linear-gradient(${b.angle}deg,${b.color},${b.color2})`:b.color;
      const safe=/^(https?:\/\/|\/backgrounds\/)/i.test(b.source);
      el.innerHTML=((['image','video'].includes(b.kind)&&safe)?(b.kind==='video'?`<video src="${esc(assetSource(b.source))}" autoplay muted loop playsinline style="object-fit:${b.fit};filter:blur(${b.blur}px)"></video>`:`<img src="${esc(assetSource(b.source))}" alt="Background preview" style="object-fit:${b.fit};filter:blur(${b.blur}px)">`):'')+`<div class="preview-dim" style="opacity:${b.dim}"></div><div class="preview-ui"><i></i><i></i></div>`;
    };
    preview(); $$('.settings-body input:not([type=file]),.settings-body select').forEach(el=>el.addEventListener(el.type==='text'?'change':'input',preview));
  }
  $('#save-settings').addEventListener('click',async () => {
    collectDraft(); const btn = $('#save-settings'); btn.disabled = true;
    try {
      preferences = await execute('/api/preferences',draft);
      if(appVersionInfo)appVersionInfo=await execute('/api/app',{action:'default',mode:defaultVersionDraft,startup:startupDraft});
      closeSheet(); applyPreferences(); toast('Your Sonar Edge settings are saved.');
    }
    catch {} finally { btn.disabled = false; }
  });
}
function scheduleUpdateRefresh(){clearTimeout(updateTimer);if(['checking','downloading','installing'].includes(updateInfo?.status))updateTimer=setTimeout(refreshUpdates,650);}
async function refreshUpdates(){
  try{updateInfo=await get('/api/update');if(!updateInfo)throw Error('Open the installed Sonar Edge app to use updates.');}
  catch(error){updateInfo={status:'error',message:error.message,currentVersion:'—',repository:'fivekeyelements/SonarEdge'};}
  if(!$('#overlay').hidden&&settingsTab==='updates'){settingsContent();scheduleUpdateRefresh();}
}
async function openSettings(tab='layout') {
  if (!preferences) return toast('The local helper is connecting. Try again in a moment.');
  try{const info=await get('/api/app');if(info)appVersionInfo=info;}catch{}
  draft = copy(preferences);defaultVersionDraft=appVersionInfo?.default||'desktop';startupDraft=!!appVersionInfo?.startup?.enabled;settingsTab=tab;openSheet('Settings','SONAR EDGE');settingsContent();
  get('/api/players').then(data=>{playerOptions=data;if(!$('#overlay').hidden&&$('#settings-player')){collectDraft();settingsContent();}}).catch(()=>{});
}
$('#customize').addEventListener('click',()=>openSettings());
async function choosePlayer() {
  openSheet('Music app','PLAYER');$('#sheet-content').innerHTML='';
  try{
    playerOptions=await get('/api/players');
    $('#sheet-content').innerHTML=`<div class="player-picker-list">${playerOptions.map(p=>`<button class="player-choice${p.id===preferences.playerApp?' selected':''}" data-player-id="${esc(p.id)}">${svg('music')}<span>${esc(p.name)}</span></button>`).join('')}</div>`;
    $$('[data-player-id]').forEach(b=>b.addEventListener('click',async()=>{try{preferences=await execute('/api/preferences',{...preferences,playerApp:b.dataset.playerId});closeSheet();state.music={connected:false,name:'Media player'};applyPreferences();}catch{}}));
  }catch(e){toast(e.message);closeSheet();}
}
$('#choose-player').addEventListener('click',choosePlayer);
async function channelSheet(id, section='eq') {
  sheetChannel = id;
  const label = preferences.channels.find(c=>c.id===id).label;
  openSheet(`${label} · ${section==='eq'?'EQ presets':id==='mic'?'Input device':'Output device'}`,'STEELSERIES SONAR');
  $('#sheet-content').innerHTML = '<p class="output-info">Loading your Sonar presets and devices…</p>';
  try {
    catalog = await get('/api/catalog');
    if (sheetChannel !== id) return;
    const ch = state.sonar.channels[id], flow = id === 'mic' ? 'capture' : 'render';
    const devices = catalog.devices.filter(d=>d.dataFlow===flow);
    const selectedDevice = devices.find(d=>d.id===ch.deviceId);
    const canRoute = ch.canRoute;
    if(section==='device'){
      let selected=devices.some(d=>d.id===ch.deviceId)?ch.deviceId:null;
      $('#sheet-content').innerHTML=`<div class="output-info">Connected to <strong>${esc(ch.deviceName||selectedDevice?.friendlyName||'No device selected')}${ch.deviceAvailable===false?' · Disconnected':''}</strong></div><input type="search" class="preset-filter" placeholder="Find a device…" aria-label="Search audio devices"><div class="device-picker-list"></div><div class="device-picker-footer">${canRoute?'':'<p class="settings-help">Per-channel outputs require Sonar Classic mode.</p>'}<button class="button secondary" data-open-gg>Open Sonar</button><button class="button primary" id="apply-device" disabled>Apply device</button></div>`;
      const renderDevices=()=>{
        const query=$('.preset-filter').value.toLowerCase();
        $('.device-picker-list').innerHTML=devices.filter(d=>d.friendlyName.toLowerCase().includes(query)).map(d=>`<button class="device-choice${d.id===selected?' selected':''}" data-device="${esc(d.id)}"${canRoute?'':' disabled'}>${svg(id==='mic'?'mic':'headphones')}<span>${esc(d.friendlyName)}</span>${d.id===ch.deviceId?'<small>CONNECTED</small>':''}</button>`).join('')||'<p class="settings-help">No available devices match.</p>';
        $$('[data-device]').forEach(b=>b.addEventListener('click',()=>{selected=b.dataset.device;renderDevices();$('#apply-device').disabled=selected===ch.deviceId;}));
      };
      renderDevices();$('.preset-filter').addEventListener('input',renderDevices);
      $('[data-open-gg]').addEventListener('click',()=>execute('/api/launch',{app:'sonar'}).catch(()=>{}));
      $('#apply-device').addEventListener('click',async()=>{const btn=$('#apply-device');btn.disabled=true;try{state.sonar=await execute('/api/sonar',{channel:id,action:'device',value:selected});update();closeSheet();toast('Sonar device updated.');}catch{}finally{btn.disabled=selected===ch.deviceId;}});
      return;
    }
    $('#sheet-content').innerHTML='<input type="search" class="preset-filter" placeholder="Find an EQ preset…" aria-label="Search Sonar presets"><div class="preset-list eq-picker-list"></div>';
    const renderPresets = () => {
      const query = $('.preset-filter').value.toLowerCase();
      const presets = catalog.presets.filter(p=>p.virtualAudioDevice===internal[id] && p.name.toLowerCase().includes(query)).sort((a,b)=>Number(b.isFavorite)-Number(a.isFavorite)||a.name.localeCompare(b.name));
      $('.preset-list').innerHTML = presets.map(p=>`<button class="preset-choice${p.id===state.sonar.channels[id].preset.id?' selected':''}" data-preset="${esc(p.id)}">${esc(p.name)}<span>${p.id===state.sonar.channels[id].preset.id?'ACTIVE':p.isFavorite?'FAVORITE':''}</span></button>`).join('') || '<p class="settings-help">No presets match this search.</p>';
      $$('[data-preset]').forEach(b=>b.addEventListener('click',async()=>{
        b.disabled=true;
        try { state.sonar = await execute('/api/sonar',{channel:id,action:'preset',value:b.dataset.preset}); update(); renderPresets(); toast('Sonar preset applied.'); }
        catch {} finally { b.disabled=false; }
      }));
    };
    renderPresets(); $('.preset-filter').addEventListener('input',renderPresets);
  } catch(e) { if (sheetChannel===id) $('#sheet-content').innerHTML=`<p class="output-info">${esc(e.message)}. Open GG, enable Sonar, then try again.</p>`; }
}
async function poll() {
  try {
    if (!token) { await session(); applyPreferences(); }
    const latest=await get('/api/state'); disconnected=false;
    if(latest.preferences&&JSON.stringify(latest.preferences)!==JSON.stringify(preferences)) {preferences=latest.preferences;applyPreferences();}
    // Do not let an older poll response replace a just-completed command.
    for (const key of ['sonar','music']) {
      if (!latest[key]?.updated || !state[key]?.updated || latest[key].updated >= state[key].updated) state[key]=latest[key];
      if (state[key]?.updated && Date.now()/1000-state[key].updated>12) state[key]={connected:false};
    }
    update();
    if(!window.SONAR_EDGE_NATIVE&&window.parent!==window)window.parent.postMessage({type:'sonar-edge-ready'},'*');
  } catch(e) {
    disconnected=true; token=null; state={sonar:{connected:false},music:{connected:false}}; update();
  } finally { setTimeout(poll,disconnected?2500:650); }
}
poll();
EdgeVisuals.start({preferences:()=>preferences,fetchMeters:()=>get('/api/meters'),editing:id=>draggingMusic.has(id)||edited.get(id)>Date.now()});
