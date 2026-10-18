const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/web/app.js','utf8');
const extract=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const context={};vm.createContext(context);
vm.runInContext(source.match(/const actionIcons = [^\n]+/)[0]+'\n'+extract('function shortcutIcon(', '\nfunction hydrate(')+'\nthis.pick=shortcutIcon;',context);
assert.equal(context.pick('mic',{},false,true),'muted');
assert.equal(context.pick('mic',{icon:'mic'},false,true),'muted');
assert.equal(context.pick('media',{icon:'volume'},false,true),'muted');
assert.equal(context.pick('playpause',{icon:'play'},true,false),'pause');
assert.equal(context.pick('playpause',{},false,false),'play');
assert.equal(context.pick('mic',{icon:'headphones'},false,true),'headphones');
const rows=[
  {'.shortcut-select':'mic','.action-label':'  ','.action-icon':'mic'},
  {'.shortcut-select':'playpause','.action-label':' My player ','.action-icon':'headphones'}
];
context.draft={channels:[],shortcutAppearance:{}};
context.$=(selector,row)=>row?{value:row[selector]}:selector==='#shortcut-labels'?{checked:true}:null;
context.$$=selector=>selector==='.action-setting-row'?rows:[];
vm.runInContext(extract('function collectDraft() {','\nfunction settingsContent(')+'\ncollectDraft();',context);
assert.deepEqual(JSON.parse(JSON.stringify(context.draft.shortcutAppearance)),{mic:{},playpause:{label:'My player',icon:'headphones'}});
console.log('Default and saved default icons follow playback/mute state; custom icons and labels remain customizable.');
