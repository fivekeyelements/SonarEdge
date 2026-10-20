const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/web/app.js','utf8');
const context={};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function listedDevices('),source.indexOf('\nfunction hydrate('))+'\nthis.api={listedDevices,setDeviceVisible,volumeRequest};',context);
const {listedDevices,setDeviceVisible,volumeRequest}=context.api;
const devices=[
  {id:'headphones',friendlyName:'USB headphones',dataFlow:'render'},
  {id:'speakers',friendlyName:'Desk speakers',dataFlow:'render'},
  {id:'virtual',friendlyName:'Virtual cable',dataFlow:'render'},
  {id:'mic',friendlyName:'USB microphone',dataFlow:'capture'},
  {id:'same-name',friendlyName:'USB headphones',dataFlow:'capture'}
];
const ids=items=>Array.from(items,d=>d.id);
assert.deepEqual(ids(listedDevices(devices,'render',['virtual'])),['speakers','headphones']);
assert.deepEqual(ids(listedDevices(devices,'capture',['virtual'])),['same-name','mic']);
assert.deepEqual(ids(listedDevices(devices,'render',['virtual'],['virtual'])),['speakers','headphones','virtual']);
assert.deepEqual(ids(listedDevices(devices,'render',['virtual'],[],' VIRTUAL ',true)),['virtual']);
assert.deepEqual(ids(listedDevices(devices,'render',['virtual'],[],' VIRTUAL ')),[]);
const settings={hiddenDevices:{render:['unplugged','virtual'],capture:['mic']}};
setDeviceVisible(settings,'render','virtual',true);
setDeviceVisible(settings,'render','headphones',false);
setDeviceVisible(settings,'render','headphones',false);
assert.deepEqual(Array.from(settings.hiddenDevices.render),['unplugged','headphones']);
assert.deepEqual(settings.hiddenDevices.capture,['mic']);
const normalize=value=>JSON.parse(JSON.stringify(value));
assert.deepEqual(normalize(volumeRequest('master','volume',.4,{masterVolumeTarget:'windows'},{systemVolume:{deviceId:'windows-speakers'}})),
  {path:'/api/system-volume',key:'systemVolume',body:{action:'volume',value:.4,deviceId:'windows-speakers'}});
assert.deepEqual(normalize(volumeRequest('game','volume',.4,{masterVolumeTarget:'windows'},{})),
  {path:'/api/sonar',key:'sonar',body:{channel:'game',action:'volume',value:.4}});
assert.deepEqual(normalize(volumeRequest('master','mute',true,{masterVolumeTarget:'sonar'},{})),
  {path:'/api/sonar',key:'sonar',body:{channel:'master',action:'mute',value:true}});
console.log('Device filters preserve current devices and disconnected choices; Windows volume never writes Sonar Master.');
