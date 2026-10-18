const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(__dirname+'/widget/index.html','utf8');
const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
let now=20000,interval,receive,retry,connected=false,reloads=0;
const panel={contentWindow:{},set src(v){assert.equal(v,'http://127.0.0.1:47832/?icue=xl');reloads++;}};
vm.runInNewContext(source,{
  Date:{now:()=>now},setInterval:fn=>interval=fn,
  window:{addEventListener:(type,fn)=>{assert.equal(type,'message');receive=fn;}},
  document:{getElementById:id=>id==='panel'?panel:{addEventListener:(type,fn)=>retry=fn},
    body:{classList:{add:()=>connected=true,remove:()=>connected=false}}}
});
receive({source:panel.contentWindow,origin:'https://untrusted.example',data:{type:'sonar-edge-ready'}});
assert.equal(connected,false);
receive({source:{},origin:'http://127.0.0.1:47832',data:{type:'sonar-edge-ready'}});
assert.equal(connected,false);
receive({source:panel.contentWindow,origin:'http://127.0.0.1:47832',data:{type:'sonar-edge-ready'}});
assert.equal(connected,true);
now+=10000;interval();assert.equal(connected,true);assert.equal(reloads,0);
now+=3000;interval();assert.equal(connected,false);assert.equal(reloads,1);
receive({source:panel.contentWindow,origin:'http://127.0.0.1:47832',data:{type:'sonar-edge-ready'}});
assert.equal(connected,true);
retry();assert.equal(connected,false);assert.equal(reloads,2);
console.log('Iframe validates its source, recovers after companion loss and supports manual reconnect.');
