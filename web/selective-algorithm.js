// Same deterministic masks as core/selective.py; also embedded in the offline worker.
function accentHSV(c){
  const hi=Math.max(...c),lo=Math.min(...c),d=hi-lo,safe=Math.max(d,1);
  const hue=hi===c[0]?(c[1]-c[2])/safe:hi===c[1]?2+(c[2]-c[0])/safe:4+(c[0]-c[1])/safe;
  return [(hue*60+360)%360,hi?d/hi*100:0,d];
}
function accentRGB(hex){return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));}
function accentShade(target,gray){
  const rgb=target.map(c=>f32(c/255)),base=f32(f32(Math.max(...rgb)+Math.min(...rgb))*.5);
  const light=f32(f32(f32(Math.max(...gray)/255)+f32(Math.min(...gray)/255))*.5);
  const out=new Uint8ClampedArray(3);
  if(Math.max(...target)-Math.min(...target)<=8)out.fill(roundEven(f32(light*255)));
  else writeLightness(out,0,...rgb,base,light);return out;
}
function rasterPaintMask(value,H,W,stride,w,h){
  const mask=new Uint8Array(H*W);
  for(const stroke of (value.strokes||[]).slice(0,512)){
    const pts=stroke.points||[],radius=Math.max(.00001,Math.min(64,Number(stroke.radius??.03)))*Math.min(w,h);
    for(let k=0;k<pts.length;k++){
      const a=pts[k],b=pts[Math.min(k+1,pts.length-1)],ax=a[0]*w,ay=a[1]*h,dx=(b[0]-a[0])*w,dy=(b[1]-a[1])*h;
      const denom=dx*dx+dy*dy;
      const x0=Math.max(0,Math.floor((Math.min(ax,ax+dx)-radius)/stride)-1),x1=Math.min(W,Math.ceil((Math.max(ax,ax+dx)+radius)/stride)+1);
      const y0=Math.max(0,Math.floor((Math.min(ay,ay+dy)-radius)/stride)-1),y1=Math.min(H,Math.ceil((Math.max(ay,ay+dy)+radius)/stride)+1);
      for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
        const sx=Math.min(x*stride+Math.floor(stride/2),w-1)+.5,sy=Math.min(y*stride+Math.floor(stride/2),h-1)+.5;
        const t=denom?clamp(((sx-ax)*dx+(sy-ay)*dy)/denom,0,1):0;
        if((sx-ax-t*dx)**2+(sy-ay-t*dy)**2<=radius*radius)mask[y*W+x]=stroke.erase!==true?1:0;
      }
    }
  }
  return mask;
}
function applySelectiveColor(gray,source,h,w,factor,downsample,rules){
  const guide=downsample?downsampleColor(source,h,w,factor,'median'):source;
  const H=downsample?Math.ceil(h/factor):h,W=downsample?Math.ceil(w/factor):w,stride=downsample?factor:1;
  const out=new Uint8ClampedArray(gray),hsv=Array.from({length:H*W},(_,i)=>accentHSV(guide.subarray(i*3,i*3+3)));
  for(const rule of (Array.isArray(rules)?rules:[]).slice(0,12)){
    if(!rule||rule.enabled===false||!/^#[0-9a-f]{6}$/i.test(rule.source)||!/^#[0-9a-f]{6}$/i.test(rule.target))continue;
    const reference=accentHSV(accentRGB(rule.source)),ref=reference[0],target=accentRGB(rule.target);
    if(reference[2]<=8)continue;
    const tolerance=clamp(Number(rule.tolerance??20),0,90),saturation=clamp(Number(rule.saturation??20),0,100);
    const dark=clamp(Math.trunc(rule.dark_limit??32),0,128),minimum=clamp(Math.trunc(rule.min_size??2),1,40000000);
    const region=rule.region,mask=new Uint8Array(H*W);
    const painted=rule.paint_mask?rasterPaintMask(rule.paint_mask,H,W,stride,w,h):null;
    for(let y=0;y<H;y++)for(let x=0;x<W;x++){
      const i=y*W+x,o=i*3,[hue,sat,delta]=hsv[i],d=Math.abs(hue-ref);
      const sx=(Math.min(x*stride+Math.floor(stride/2),w-1)+.5)/w,sy=(Math.min(y*stride+Math.floor(stride/2),h-1)+.5)/h;
      if(Math.min(d,360-d)>tolerance||sat<saturation||delta<=8||(gray[o]+gray[o+1]+gray[o+2])/3<=dark)continue;
      if(region&&!(sx>=region[0]&&sx<region[2]&&sy>=region[1]&&sy<region[3]))continue;
      if(painted&&!painted[i])continue;
      const shade=accentShade(target,gray.subarray(o,o+3));
      if(Math.max(...shade)-Math.min(...shade)<=8)continue;
      mask[i]=1;
    }
    if(minimum>1){
      const visited=new Uint8Array(H*W),queue=new Int32Array(H*W);
      for(let i=0;i<mask.length;i++){
        if(!mask[i]||visited[i])continue;
        let end=1;queue[0]=i;visited[i]=1;
        for(let start=0;start<end;start++){
          const n=queue[start],x=n%W,y=Math.floor(n/W);
          for(const j of [y>0?n-W:-1,y<H-1?n+W:-1,x>0?n-1:-1,x<W-1?n+1:-1]){
            if(j>=0&&mask[j]&&!visited[j]){visited[j]=1;queue[end++]=j;}
          }
        }
        if(end<minimum)for(let j=0;j<end;j++)mask[queue[j]]=0;
      }
    }
    for(let i=0;i<mask.length;i++)if(mask[i])out.set(accentShade(target,gray.subarray(i*3,i*3+3)),i*3);
  }
  return out;
}
