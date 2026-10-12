// Deliberately complete HTTP render/report requests out of order.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const pending=[],nodes=new Map(),reports=[];
const node=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{},textContent:'',src:'',classList:{toggle(){}}});return nodes.get(id);};
const ctx=vm.createContext({console,setTimeout,clearTimeout,reports,
  document:{querySelector:node},
  URL:{createObjectURL:b=>'blob:'+b.tag,revokeObjectURL(){}},
  fetch:(url,opts)=>new Promise((resolve,reject)=>pending.push({url,body:JSON.parse(opts.body),resolve,reject}))});
vm.runInContext(fs.readFileSync('web/app.js','utf8').replace(/\binit\(\);/g,''),ctx);
vm.runInContext("setBusy=()=>{};applyView=()=>{};toast=()=>{};renderReport=j=>reports.push(j);state.id='image';state.srcW=32;state.srcH=24;",ctx);
const response=tag=>({ok:true,blob:async()=>({tag}),headers:{get:k=>k==='X-Out-Size'?tag+'x24':'1'}});
const tick=()=>new Promise(r=>setTimeout(r,0));
const old=vm.runInContext('state.params.factor=8;renderNow()',ctx);
const latest=vm.runInContext('state.params.factor=2;renderNow()',ctx);
pending[1].resolve(response(2));await tick();
assert.equal(pending[2].url,'/api/report');assert.equal(pending[2].body.params.factor,2);
vm.runInContext('state.params.factor=3;scheduleRender();clearTimeout(state.timer)',ctx);
const newest=vm.runInContext('renderNow()',ctx);
pending[0].resolve(response(8));await old;
assert.equal(node('#img-result').src,'blob:2');
pending[3].resolve(response(3));await tick();
pending[4].resolve({json:async()=>({factor:3})});await newest;
pending[2].resolve({json:async()=>({factor:2})});await latest;
assert.equal(node('#img-result').src,'blob:3');
assert.equal(reports.length,1);assert.equal(reports[0].factor,3);
assert.equal(pending[0].body.params.factor,8);
assert.equal(pending[4].body.params.factor,3);
console.log('PASS immutable request parameters, outdated preview discarded, outdated report discarded; newest render/report agree');
