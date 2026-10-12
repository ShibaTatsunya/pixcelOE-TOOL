// Shared controls, embedded verbatim in pixcelOE.html for file:// use.
let accentTool=null,accentDrag=null,accentOverlay=null,accentPaintOverlay=null,accentBrushSize=24;
function refreshAccentOverlay(){
  const editing=accentTool&&['paint','erase'].includes(accentTool.mode)&&state.view==='original';
  if(!editing){if(accentPaintOverlay)accentPaintOverlay.style.display='none';return;}
  const img=document.getElementById('img-original'),r=img.getBoundingClientRect();
  if(!accentPaintOverlay){accentPaintOverlay=document.createElement('canvas');accentPaintOverlay.style.cssText='position:fixed;pointer-events:none;z-index:8';document.body.append(accentPaintOverlay);}
  const cv=accentPaintOverlay;cv.width=img.naturalWidth;cv.height=img.naturalHeight;
  Object.assign(cv.style,{display:'block',left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px'});
  const ctx=cv.getContext('2d'),rule=(state.params.accent_rules||[])[accentTool.index];
  const strokes=[...(rule?.paint_mask?.strokes||[])];if(accentDrag?.stroke)strokes.push(accentDrag.stroke);
  for(const stroke of strokes){
    ctx.globalCompositeOperation=stroke.erase?'destination-out':'source-over';ctx.strokeStyle=ctx.fillStyle='#c040ff88';
    ctx.lineWidth=stroke.radius*Math.min(cv.width,cv.height)*2;ctx.lineCap=ctx.lineJoin='round';
    const pts=stroke.points;if(!pts.length)continue;
    if(pts.length===1){ctx.beginPath();ctx.arc(pts[0][0]*cv.width,pts[0][1]*cv.height,ctx.lineWidth/2,0,Math.PI*2);ctx.fill();}
    else{ctx.beginPath();ctx.moveTo(pts[0][0]*cv.width,pts[0][1]*cv.height);for(const p of pts.slice(1))ctx.lineTo(p[0]*cv.width,p[1]*cv.height);ctx.stroke();}
  }
}
function cancelAccentSelection(){
  accentTool=null;accentDrag=null;
  if(accentOverlay)accentOverlay.style.display='none';
  if(accentPaintOverlay)accentPaintOverlay.style.display='none';
  const img=document.getElementById('img-original');if(img)img.style.cursor='';
}
function updateAccent(index,key,value){
  const rules=(state.params.accent_rules||[]).map((r,i)=>i===index?{...r,[key]:value}:r);
  setParam('accent_rules',rules);
}
function buildAccentControls(host){
  const sec=document.createElement('div');sec.className='group';sec.dataset.k='selective_mode';
  const label=document.createElement('label');label.className='chk';
  const toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=!!state.params.selective_mode;
  toggle.onchange=()=>{
    state.params.selective_mode=toggle.checked;
    if(toggle.checked){state.params.color_mode=false;state.params.posterize_skip=false;}
    accentTool=null;buildControls();scheduleRender();
  };
  label.append(toggle,document.createTextNode(' ⑥ 抽色艺术（保留灰阶明度）'));sec.append(label);host.append(sec);
  if(!toggle.checked){cancelAccentSelection();return;}
  sec.append(helpEl('输出色相与灰阶明度结合。框选、画笔遮罩与原图颜色筛选共同生效；涂过的区域允许抽色，未涂区域保持灰阶。'));
  const rules=state.params.accent_rules||[];
  rules.forEach((rule,index)=>{
    const card=document.createElement('div');card.className='accent-rule';card.dataset.rule=index;
    card.style.cssText='border:1px solid #444;border-radius:6px;padding:10px;margin-top:10px';
    const heading=document.createElement('label'),enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=rule.enabled!==false;
    enabled.onchange=()=>updateAccent(index,'enabled',enabled.checked);heading.append(enabled,document.createTextNode(' 色块 '+(index+1)));card.append(heading);
    const button=(text,fn)=>{const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=text;b.onclick=fn;return b;};
    const colors=document.createElement('div');colors.style.cssText='display:flex;gap:12px;margin:8px 0';
    for(const [key,text] of [['source','原图颜色'],['target','输出色相']]){
      const lab=document.createElement('label');lab.textContent=text+' ';const input=document.createElement('input');input.type='color';input.value=rule[key];input.dataset.accent=key;
      input.oninput=()=>updateAccent(index,key,input.value);lab.append(input);colors.append(lab);
    }
    card.append(colors);
    const arm=mode=>{
      if(!state.srcW){toast('请先导入图片');return;}
      cancelAccentSelection();
      accentTool={index,mode};state.view='original';state.zoom='fit';applyView();
      document.getElementById('img-original').style.cursor='crosshair';
      document.querySelectorAll('#zoom button').forEach(b=>b.classList.toggle('on',b.dataset.z==='fit'));
      refreshAccentOverlay();
      toast(mode==='pick'?'点击原图取色':mode==='rect'?'在原图拖动框选作用范围':'在原图涂抹，完成后点击“完成遮罩”');
    };
    card.append(button('从原图取色',()=>arm('pick')),button('框选范围',()=>arm('rect')));
    const region=document.createElement('div');region.className='help';region.textContent=rule.region?'框选：'+rule.region.map(v=>Math.round(v*100)+'%').join(' / '):'范围：整张原图';card.append(region);
    if(rule.region)card.append(button('清除框选',()=>{updateAccent(index,'region',null);buildControls();}));
    const maskInfo=document.createElement('div');maskInfo.className='help';maskInfo.textContent=rule.paint_mask?'画笔遮罩：'+rule.paint_mask.strokes.length+' 笔（遮罩外保持灰阶）':'画笔遮罩：未启用';card.append(maskInfo);
    card.append(button('画笔绘制遮罩',()=>arm('paint')),button('橡皮擦',()=>arm('erase')));
    const brush=document.createElement('label');brush.style.display='block';brush.textContent='画笔半径（原图像素） ';
    const size=document.createElement('input');size.type='number';size.min=1;size.max=512;size.value=accentBrushSize;size.dataset.accent='brush_size';size.style.width='72px';
    size.oninput=()=>{accentBrushSize=Math.max(1,Math.min(512,Number(size.value)||1));};brush.append(size);card.append(brush);
    card.append(button('完成遮罩',()=>{cancelAccentSelection();state.view='result';applyView();}),button('撤销一笔',()=>{const mask=state.params.accent_rules[index].paint_mask;if(mask){updateAccent(index,'paint_mask',{strokes:mask.strokes.slice(0,-1)});buildControls();refreshAccentOverlay();}}));
    if(rule.paint_mask)card.append(button('清除遮罩',()=>{cancelAccentSelection();updateAccent(index,'paint_mask',null);buildControls();}));
    for(const [key,text,min,max,def] of [['tolerance','色相容差（度）',0,90,20],['saturation','最低饱和度（%）',0,100,20],['dark_limit','黑线保护（越大保护越多）',0,128,32],['min_size','最小连通色块（输出像素数）',1,4096,2]]){
      const lab=document.createElement('label');lab.style.cssText='display:block;margin-top:8px';
      const value=document.createElement('span');value.textContent=rule[key]??def;lab.append(document.createTextNode(text+' '),value);
      const input=document.createElement('input');input.type='range';input.min=min;input.max=max;input.step=1;input.value=rule[key]??def;input.dataset.accent=key;
      input.oninput=()=>{value.textContent=input.value;updateAccent(index,key,Number(input.value));};card.append(lab,input);
      if(key==='min_size'){
        const number=document.createElement('input');number.type='number';number.min=1;number.max=40000000;number.value=rule[key]??def;number.dataset.accent='min_size_number';number.style.width='100px';
        number.oninput=()=>{const n=Math.max(1,Math.min(40000000,Math.trunc(Number(number.value)||1)));value.textContent=n;input.value=n;updateAccent(index,key,n);};
        input.addEventListener('input',()=>number.value=input.value);card.append(number,helpEl('小于此面积的可见连通色块会被去除；相连的不同明度属于同一块。大色块可直接输入更大数值。'));
      }
    }
    card.append(button('删除此规则',()=>{cancelAccentSelection();setParam('accent_rules',(state.params.accent_rules||[]).filter((_,i)=>i!==index));buildControls();}));sec.append(card);
  });
  const add=document.createElement('button');add.className='btn';add.textContent='＋ 添加抽色规则';add.disabled=rules.length>=12;
  add.onclick=()=>{setParam('accent_rules',[...(state.params.accent_rules||[]),{source:'#35A7B4',target:'#35A7B4',tolerance:20,saturation:20,dark_limit:32,min_size:2,region:null,enabled:true}]);buildControls();};sec.append(add);
  installAccentSelection();
}
function installAccentSelection(){
  const img=document.getElementById('img-original');if(img.dataset.accentInstalled)return;img.dataset.accentInstalled='1';
  window.addEventListener('keydown',e=>{if(e.key==='Escape'&&accentTool){cancelAccentSelection();toast('已取消取色或框选');}});
  window.addEventListener('resize',refreshAccentOverlay);
  window.addEventListener('scroll',refreshAccentOverlay,true);
  const point=e=>{const r=img.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
  const overlay=region=>{
    if(!accentOverlay){accentOverlay=document.createElement('div');accentOverlay.style.cssText='position:fixed;border:2px dashed #b2a4ff;background:#8070ff22;pointer-events:none;z-index:8';document.body.append(accentOverlay);}
    const r=img.getBoundingClientRect();Object.assign(accentOverlay.style,{display:'block',left:r.left+region[0]*r.width+'px',top:r.top+region[1]*r.height+'px',width:(region[2]-region[0])*r.width+'px',height:(region[3]-region[1])*r.height+'px'});
  };
  img.addEventListener('mousedown',e=>{if(accentTool){e.preventDefault();e.stopPropagation();}},true);
  img.addEventListener('pointerdown',e=>{
    if(!accentTool||e.button!==0)return;e.preventDefault();e.stopPropagation();
    const pos=point(e);
    if(accentTool.mode==='pick'){
      const cv=document.createElement('canvas');cv.width=img.naturalWidth;cv.height=img.naturalHeight;const ctx=cv.getContext('2d');ctx.drawImage(img,0,0);
      const rgb=ctx.getImageData(Math.min(cv.width-1,Math.floor(pos[0]*cv.width)),Math.min(cv.height-1,Math.floor(pos[1]*cv.height)),1,1).data;
      if(Math.max(...rgb.slice(0,3))-Math.min(...rgb.slice(0,3))<=8){toast('此处接近灰色，请点击彩色部分取色');return;}
      const hex='#'+Array.from(rgb.slice(0,3),v=>v.toString(16).padStart(2,'0')).join('');
      updateAccent(accentTool.index,'source',hex);cancelAccentSelection();buildControls();state.view='result';applyView();toast('已取色，已切回成品');return;
    }
    if(['paint','erase'].includes(accentTool.mode)){
      const rule=state.params.accent_rules[accentTool.index];
      if((rule.paint_mask?.strokes.length||0)>=512){toast('笔画已达上限，请清除或撤销后重画');return;}
      accentDrag={index:accentTool.index,pointer:e.pointerId,stroke:{erase:accentTool.mode==='erase',radius:accentBrushSize/Math.min(img.naturalWidth,img.naturalHeight),points:[pos]}};
      img.setPointerCapture(e.pointerId);refreshAccentOverlay();return;
    }
    accentDrag={start:pos,index:accentTool.index,pointer:e.pointerId};img.setPointerCapture(e.pointerId);overlay([...pos,...pos]);
  },true);
  img.addEventListener('pointermove',e=>{
    if(!accentDrag)return;
    if(accentDrag.stroke){const b=point(e),pts=accentDrag.stroke.points,a=pts[pts.length-1];if(pts.length<4095&&Math.hypot((a[0]-b[0])*img.naturalWidth,(a[1]-b[1])*img.naturalHeight)>=Math.max(1,accentBrushSize/4))pts.push(b);refreshAccentOverlay();return;}
    const a=accentDrag.start,b=point(e);overlay([Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])]);
  });
  const finish=e=>{
    if(!accentDrag)return;
    if(accentDrag.stroke){
      const index=accentDrag.index,stroke=accentDrag.stroke;stroke.points.push(point(e));
      if(img.hasPointerCapture(accentDrag.pointer))img.releasePointerCapture(accentDrag.pointer);
      accentDrag=null;const rule=state.params.accent_rules[index];updateAccent(index,'paint_mask',{strokes:[...(rule.paint_mask?.strokes||[]),stroke]});buildControls();refreshAccentOverlay();return;
    }
    const a=accentDrag.start,b=point(e),index=accentDrag.index;
    if(img.hasPointerCapture(accentDrag.pointer))img.releasePointerCapture(accentDrag.pointer);
    cancelAccentSelection();
    const rect=[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];
    if(rect[2]>rect[0]&&rect[3]>rect[1]){updateAccent(index,'region',rect);buildControls();toast('框选已保存，切换结果查看效果');}
  };
  img.addEventListener('pointerup',finish);
  img.addEventListener('pointercancel',cancelAccentSelection);
}
