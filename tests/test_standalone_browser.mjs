// Exercise the offline file:// entry point in a real Edge browser.
// Run: node tests/test_standalone_browser.mjs
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const exe=['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p=>fs.existsSync(p));
if(!exe)throw new Error('Edge/Chrome is required for offline browser verification');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'pixceloe-offline-'));
const edge=spawn(exe,['--headless=new','--disable-gpu','--no-first-run','--disable-extensions',
  `--user-data-dir=${profile}`,'--remote-debugging-port=0',pathToFileURL(path.join(root,'pixcelOE.html')).href],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws,id=0;const pending=new Map();
function command(method,params={}){return new Promise((resolve,reject)=>{
  const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));
});}
try{
  let target;
  for(let n=0;n<100&&!target;n++){
    await sleep(200);
    try{const port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split(/\r?\n/)[0];
      target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page'&&t.url.startsWith('file:'));}catch{}
  }
  if(!target)throw new Error('Browser did not start');
  ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
  ws.addEventListener('message',e=>{const m=JSON.parse(e.data);const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result);}});
  let ready=false;
  for(let n=0;n<50&&!ready;n++){
    try{const state=await command('Runtime.evaluate',{expression:'document.readyState === "complete" && document.querySelectorAll(".field").length > 0',returnByValue:true});ready=state.result?.value===true;}
    catch(e){if(!e.message.includes('context'))throw e;}
    if(!ready)await sleep(200);
  }
  if(!ready)throw new Error('Offline page did not finish initializing');
  const test=await command('Runtime.evaluate',{awaitPromise:true,returnByValue:true,expression:`(async()=>{
    const results=[];const check=(c,label)=>{results.push({pass:!!c,label});};
    const sleep=ms=>new Promise(r=>setTimeout(r,ms));
    const idle=async()=>{const until=performance.now()+30000;while(workerBusy||renderPending||renderTimer){
      // renderTimer holds a completed timeout ID; only wait for the debounce interval once.
      await sleep(180);if(!workerBusy&&!renderPending)break;if(performance.now()>until)throw new Error('Render timeout');
    }};
    for(let n=0;n<30&&document.querySelectorAll('.field').length===0;n++)await sleep(100);
    const controlCount=document.querySelectorAll('.field').length;
    check(controlCount===17&&!document.querySelector('[data-k="gamma"]'),'controls initialized without Gamma ('+controlCount+' fields)');
    const cv=document.createElement('canvas');cv.width=640;cv.height=960;const cx=cv.getContext('2d');
    const pixels=cx.createImageData(640,960);
    for(let i=0;i<pixels.data.length;i+=4){const x=(i/4)%640,y=Math.floor(i/4/640);pixels.data[i]=x%256;pixels.data[i+1]=y%256;pixels.data[i+2]=(x+y)%256;pixels.data[i+3]=255;}
    cx.putImageData(pixels,0,0);
    const file=new File([await new Promise(r=>cv.toBlob(r))],'test.png',{type:'image/png'});
    let ticks=0;const heartbeat=setInterval(()=>ticks++,10);
    const start=performance.now();await upload(file);clearInterval(heartbeat);
    const firstMs=performance.now()-start;
    check(state.outW===160&&state.outH===240,'640×960 import produces 160×240');
    check(ticks>5,'main thread remains responsive during processing ('+ticks+' ticks)');
    const preview=new Image();preview.src=document.querySelector('#img-result').src;await preview.decode();
    const out=document.createElement('canvas');out.width=state.outW;out.height=state.outH;out.getContext('2d').drawImage(preview,0,0);
    const actual=out.getContext('2d').getImageData(0,0,out.width,out.height).data;
    let correct=true;for(let i=0,j=0;i<state.finalData.length;i+=3,j+=4){if(actual[j]!==state.finalData[i]||actual[j+1]!==state.finalData[i+1]||actual[j+2]!==state.finalData[i+2]||actual[j+3]!==255){correct=false;break;}}
    check(correct,'preview pixels match RGB output; all alpha=255');
    const before=Array.from(state.finalData);const toggle=document.querySelector('[data-k="color_mode"] input');toggle.click();await idle();
    check(state.params.color_mode&&state.finalData.some((v,i)=>v!==before[i]),'color toggle automatically recalculates');
    check(document.querySelector('#st-check').textContent.includes('✗'),'color output does not falsely pass grayscale acceptance');
    const sourceGuide=cleanColorSpeckles(downsampleColor(state.srcData,state.srcH,state.srcW,4,'bridge'),state.outH,state.outW,state.params.color_cleanup);
    const hue=c=>{const hi=Math.max(...c),lo=Math.min(...c),d=hi-lo;
      const h=hi===c[0]?(c[1]-c[2])/d:hi===c[1]?2+(c[2]-c[0])/d:4+(c[0]-c[1])/d;
      return (h*60+360)%360;};
    const layerSlider=document.querySelector('[data-k="color_levels"] input');
    for(let levels=2;levels<=12;levels++){
      layerSlider.value=levels;layerSlider.dispatchEvent(new Event('input',{bubbles:true}));await renderNow();
      let maxError=0,compared=0;
      for(let o=0;o<state.finalData.length;o+=3){
        const a=Array.from(state.finalData.subarray(o,o+3)),b=Array.from(sourceGuide.subarray(o,o+3));
        if(Math.max(...a)-Math.min(...a)<24||Math.max(...b)-Math.min(...b)<24)continue;
        const d=Math.abs(hue(a)-hue(b));maxError=Math.max(maxError,Math.min(d,360-d));compared++;
      }
      check(compared>0&&maxError<=3,'layer slider '+levels+' preserves source-position hue (max '+maxError.toFixed(2)+'°)');
    }
    setParam('dither','bayer4');await renderNow();const quantized=Array.from(state.finalData);
    const fifth=document.querySelectorAll('.step-toggle input')[4];fifth.click();await idle();
    check(!state.params.enable_quantize&&state.finalData.some((v,i)=>v!==quantized[i]),'fifth step toggle takes effect in color mode');
    fifth.click();setParam('dither','none');await renderNow();
    setParam('color_mode',false);buildControls();await idle();
    const cachedStart=performance.now();setParam('factor',3);await renderNow();const cachedMs=performance.now()-cachedStart;
    check(state.outW===214&&state.outH===320,'nondivisible factor retains image edges');
    setParam('factor',8);const a=renderNow();setParam('factor',2);const b=renderNow();setParam('factor',4);const c=renderNow();await Promise.all([a,b,c]);
    check(state.outW===160&&state.outH===240,'queued slider updates settle on latest parameters');
    document.querySelector('#zoom button[data-z="4"]').click();document.querySelector('#chk-grid').click();
    check(!document.querySelector('.grid-overlay').classList.contains('hidden'),'grid checkbox draws overlay');
    const badFile=new File(['bad'],'broken.png',{type:'image/png'});check(!await upload(badFile),'invalid image handled without breaking UI');
    let prompts=0;window.prompt=()=>{prompts++;return '4';};
    const downloads=[];downloadBlob=(blob,name)=>downloads.push({blob,name});
    state.files=[file,new File([file],'second.png',{type:'image/png'})];
    await upload(state.files[0]);check(state.files.length===2,'import preserves multiple selected files');
    document.querySelector('#btn-batch').click();while(state.batching)await sleep(50);
    check(prompts===1&&downloads.length===4,'batch exports both PNG+JSON pairs with one scale prompt');
    const imageBlob=downloads.find(d=>d.name.endsWith('.png')).blob;
    const bitmap=await createImageBitmap(imageBlob);check(bitmap.width===640&&bitmap.height===960,'export uses integer nearest-neighbor scale');
    const pngCanvas=document.createElement('canvas');pngCanvas.width=bitmap.width;pngCanvas.height=bitmap.height;pngCanvas.getContext('2d').drawImage(bitmap,0,0);bitmap.close();
    const png=pngCanvas.getContext('2d').getImageData(0,0,pngCanvas.width,pngCanvas.height).data;
    check(png.every((v,i)=>i%4!==3||v===255),'exported PNG is fully opaque');
    let exactScale=true;
    for(let y=0;y<960&&exactScale;y++)for(let x=0;x<640;x++){
      const i=(y*640+x)*4,j=(Math.floor(y/4)*160+Math.floor(x/4))*3;
      if(png[i]!==state.finalData[j]||png[i+1]!==state.finalData[j+1]||png[i+2]!==state.finalData[j+2]){exactScale=false;break;}
    }
    check(exactScale,'exported RGB pixels exactly repeat in 4×4 blocks');
    const meta=JSON.parse(await downloads.find(d=>d.name.endsWith('.json')).blob.text());
    check(meta.scale===4&&meta.params.factor===4&&meta.validate.checks.length===3,'metadata records parameters and actual validation');
    const count=downloads.length;window.prompt=()=>null;await doExport();check(downloads.length===count,'cancel export performs no download');
    window.prompt=()=> 'browser-test';document.querySelector('#btn-save-preset').click();
    check(document.querySelector('#preset').value==='custom:browser-test','save preset works');
    document.querySelector('#btn-reset').click();await idle();document.querySelector('#preset').value='custom:browser-test';document.querySelector('#preset').dispatchEvent(new Event('change'));await idle();
    check(state.params.factor===4,'saved preset restores parameters');
    return {results,firstMs,cachedMs};
  })()`});
  if(test.exceptionDetails)throw new Error(test.exceptionDetails.exception?.description||test.exceptionDetails.text);
  const result=test.result.value;
  const evaluate=async expression=>{
    const r=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
    return r.result.value;
  };
  const rectangle=await evaluate(`(async()=>{
    state.params={...PRESETS.character,factor:1,enable_outline:false};buildControls();
    const cv=document.createElement('canvas');cv.width=32;cv.height=24;const cx=cv.getContext('2d');
    cx.fillStyle='#BEBEBE';cx.fillRect(0,0,32,24);cx.fillStyle='#B42328';cx.fillRect(2,4,10,12);cx.fillRect(20,4,10,12);cx.fillRect(2,2,1,1);
    await upload(new File([await new Promise(r=>cv.toBlob(r))],'selective.png',{type:'image/png'}));
    document.querySelector('[data-k="selective_mode"] input').click();
    [...document.querySelectorAll('[data-k="selective_mode"] button')].find(b=>b.textContent.includes('添加')).click();
    [...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='从原图取色').click();
    await document.querySelector('#img-original').decode();
    const r=document.querySelector('#img-original').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};
  })()`);
  const mouse=async(type,fx,fy)=>command('Input.dispatchMouseEvent',{type,x:rectangle.x+rectangle.w*fx,y:rectangle.y+rectangle.h*fy,
    button:type==='mouseMoved'?'none':'left',buttons:type==='mousePressed'?1:0,clickCount:type==='mouseMoved'?0:1});
  await mouse('mousePressed',.15,.3);await mouse('mouseReleased',.15,.3);
  const picked=await evaluate(`state.params.accent_rules[0].source.toUpperCase()`);
  result.results.push({pass:picked==='#B42328',label:'eyedropper picks original RGB with real mouse input'});
  result.results.push({pass:await evaluate(`state.view==='result'&&document.querySelector('#view-mode [data-v="result"]').classList.contains('on')`),label:'successful color pick automatically switches to result view'});
  await evaluate(`(()=>{
    const target=document.querySelector('[data-rule="0"] [data-accent="target"]');target.value='#a92f35';target.dispatchEvent(new Event('input'));
    [...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='框选范围').click();
  })()`);
  await mouse('mousePressed',.02,.02);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:rectangle.x+rectangle.w*.5,y:rectangle.y+rectangle.h*.98,buttons:1,button:'left'});
  await mouse('mouseReleased',.5,.98);
  const selective=await evaluate(`(async()=>{
    await renderNow();const region=state.params.accent_rules[0].region;
    let count=0,clean=true,rightGray=true;
    for(let y=0;y<24;y++)for(let x=0;x<32;x++){
      const o=(y*32+x)*3,c=Array.from(state.finalData.subarray(o,o+3));
      if(Math.max(...c)-Math.min(...c)>8){count++;if(c.join(',')!=='91,25,28')clean=false;if(x>=16)rightGray=false;}
    }
    const isolated=Array.from(state.finalData.subarray((2*32+2)*3,(2*32+2)*3+3));
    const downloads=[];downloadBlob=(blob,name)=>downloads.push({blob,name});window.prompt=()=> '1';await doExport();
    const meta=JSON.parse(await downloads.find(d=>d.name.endsWith('.json')).blob.text());
    state.view='result';applyView();document.querySelector('[data-k="selective_mode"]').scrollIntoView({block:'nearest'});
    return {region,count,clean,rightGray,isolated,pass:state.report.pass,meta};
  })()`);
  result.results.push({pass:selective.region&&Math.abs(selective.region[2]-.5)<.01,label:'drag rectangle saves normalized source coordinates'});
  result.results.push({pass:selective.count===120&&selective.clean&&selective.rightGray,label:'selected block keeps gray lightness with red hue; matching right block remains gray'});
  result.results.push({pass:new Set(selective.isolated).size===1,label:'isolated source color speckle is removed'});
  result.results.push({pass:selective.pass&&selective.meta.params.accent_rules[0].region&&selective.meta.validate.details.accent_pixels===120,label:'selective export records rules, actual colors and accent area'});
  await evaluate(`[...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='从原图取色').click()`);
  await mouse('mousePressed',.9,.1);await mouse('mouseReleased',.9,.1);
  result.results.push({pass:await evaluate(`state.params.accent_rules[0].source.toUpperCase()==='#B42328'&&accentTool?.mode==='pick'`),label:'neutral source click prompts another pick without selecting unrelated red hue'});
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  result.results.push({pass:await evaluate(`accentTool===null&&document.querySelector('#img-original').style.cursor===''`),label:'Escape cancels color selection'});
  const threshold=await evaluate(`(async()=>{
    const number=document.querySelector('[data-accent="min_size_number"]');number.value=121;number.dispatchEvent(new Event('input'));await renderNow();
    const removed=state.finalData.every((v,i)=>v===state.finalData[Math.floor(i/3)*3]);
    number.value=2;number.dispatchEvent(new Event('input'));await renderNow();return removed;
  })()`);
  result.results.push({pass:threshold,label:'minimum area above 64 removes the 120-pixel component through the UI'});
  await evaluate(`(()=>{
    const size=document.querySelector('[data-accent="brush_size"]');size.value=2;size.dispatchEvent(new Event('input'));
    [...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='画笔绘制遮罩').click();
  })()`);
  await mouse('mousePressed',.16,.3);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:rectangle.x+rectangle.w*.25,y:rectangle.y+rectangle.h*.4,buttons:1,button:'left'});
  await mouse('mouseReleased',.25,.4);
  const painted=await evaluate(`(async()=>{await renderNow();return {count:Array.from(state.finalData).filter((v,i)=>i%3===0&&Math.max(...state.finalData.subarray(i,i+3))-Math.min(...state.finalData.subarray(i,i+3))>8).length,strokes:state.params.accent_rules[0].paint_mask?.strokes.length};})()`);
  result.results.push({pass:painted.count>0&&painted.count<120&&painted.strokes===1,label:'real brush stroke restricts color to painted source-space mask'});
  await evaluate(`(()=>{const size=document.querySelector('[data-accent="brush_size"]');size.value=1;size.dispatchEvent(new Event('input'));[...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='橡皮擦').click();})()`);
  await mouse('mousePressed',.16,.3);await mouse('mouseReleased',.16,.3);
  const erased=await evaluate(`(async()=>{await renderNow();return Array.from(state.finalData).filter((v,i)=>i%3===0&&Math.max(...state.finalData.subarray(i,i+3))-Math.min(...state.finalData.subarray(i,i+3))>8).length;})()`);
  result.results.push({pass:erased<painted.count,label:'eraser removes painted eligibility'});
  const maskExport=await evaluate(`(async()=>{
    [...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='完成遮罩').click();
    const downloads=[];downloadBlob=(blob,name)=>downloads.push({blob,name});window.prompt=()=> '1';await doExport();
    const meta=JSON.parse(await downloads.find(d=>d.name.endsWith('.json')).blob.text());
    return {result:state.view==='result',hidden:accentPaintOverlay.style.display==='none',strokes:meta.params.accent_rules[0].paint_mask.strokes,pass:meta.validate.pass};
  })()`);
  result.results.push({pass:maskExport.result&&maskExport.hidden&&maskExport.strokes.length===2&&maskExport.strokes[1].erase&&maskExport.pass,label:'finish mask returns to result and exports paint/erase strokes with valid output'});
  await evaluate(`[...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='撤销一笔').click()`);
  result.results.push({pass:await evaluate(`state.params.accent_rules[0].paint_mask.strokes.length===1`),label:'undo removes the last painted mask operation'});
  await evaluate(`[...document.querySelectorAll('[data-rule="0"] button')].find(b=>b.textContent==='清除遮罩').click()`);
  result.results.push({pass:await evaluate(`state.params.accent_rules[0].paint_mask===null`),label:'clear mask restores unrestricted color selection inside the rectangle'});
  const neutralBackground=await evaluate(`(async()=>{
    const cv=document.createElement('canvas');cv.width=64;cv.height=64;const ctx=cv.getContext('2d');ctx.fillStyle='#fbfdff';ctx.fillRect(0,0,64,64);
    state.params={...PRESETS.character,color_mode:true,brightness:-70,color_levels:4};buildControls();
    await upload(new File([await new Promise(r=>cv.toBlob(r))],'nearwhite.png',{type:'image/png'}));
    return state.finalData.every((v,i)=>v===state.finalData[Math.floor(i/3)*3]);
  })()`);
  result.results.push({pass:neutralBackground,label:'darkened near-white source remains neutral in actual worker preview'});
  await evaluate(`state.view='result';applyView()`);
  for(const r of result.results)console.log(`${r.pass?'PASS':'FAIL'} ${r.label}`);
  console.log(`TIMING first=${result.firstMs.toFixed(0)}ms, cached=${result.cachedMs.toFixed(0)}ms`);
  const screenshot=await command('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(root,'outputs','_standalone_qa.png'),Buffer.from(screenshot.data,'base64'));
  process.exitCode=result.results.every(r=>r.pass)?0:1;
}finally{
  if(ws)ws.close();edge.kill();
  await new Promise(r=>edge.exitCode!==null?r():edge.once('exit',r));
  // Delete only the verified temporary profile created by this test.
  if(path.dirname(profile)===path.resolve(os.tmpdir())&&path.basename(profile).startsWith('pixceloe-offline-')){
    for(let n=0;n<10;n++){try{fs.rmSync(profile,{recursive:true,force:true});break;}catch{await sleep(200);}}
  }
}
