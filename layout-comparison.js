'use strict';
(function(root){
  const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
  function inputs(state){
    const job=structuredClone(state.requestJob||state.job);
    delete job._progress;delete job.settings.seed;
    return canonical(job);
  }
  function capture(state){
    const r=state.result,m=state.manifest,s=(state.requestJob||state.job).settings;
    if(r.validated!==true||m.complete!==true)throw Error('Only complete, checked layouts can be compared.');
    const finite=n=>typeof n==='number'&&Number.isFinite(n);
    if(![r.width,r.usedLength,r.utilization,r.elapsed,s.seconds,s.gap,s.margin].every(finite)||r.width<=0||r.usedLength<=0)throw Error('Layout measurements are unavailable.');
    const parts=new Map(state.job.parts.map(p=>[p.id,p]));
    const fillIds=new Set(m.jobs.filter(j=>j.role==='fill').flatMap(j=>j.partIds||[]));
    const fillJobs=new Set(m.jobs.filter(j=>j.role==='fill').map(j=>j.id));
    const shapes=r.placements.map(p=>{
      const part=parts.get(p.id);
      if(!part||![p.x,p.y,p.rotation].every(finite)||!part.points.every(v=>v.length===2&&v.every(finite)))throw Error('Layout outlines are unavailable.');
      return {points:part.points.map(v=>v.slice()),x:p.x,y:p.y,rotation:p.rotation,fill:fillIds.has(p.id)||fillJobs.has(part.sourceJobId)};
    });
    const required=m.jobs.filter(j=>j.role!=='fill');
    const outputCounts={};for(const p of r.placements)outputCounts[p.id]=(outputCounts[p.id]||0)+1;
    return {version:1,width:r.width,length:r.usedLength,coverage:r.utilization,elapsed:r.elapsed,budget:s.seconds,gap:s.gap,margin:s.margin,
      required:required.reduce((n,j)=>n+j.placed,0),expected:required.reduce((n,j)=>n+j.expected,0),
      fillerPieces:(r.fillSummary||[]).reduce((n,j)=>n+j.pieces,0),fillerSets:(r.fillSummary||[]).reduce((n,j)=>n+(j.sets||0),0),
      outputCounts:canonical(outputCounts),sheets:r.sheets?.length||1,sheetOffsets:(r.sheets||[]).filter(s=>s.index>0).map(s=>s.offset),shapes};
  }
  function compare(before,after){
    const saved=before.length-after.length,percent=100*saved/before.length;
    const outputKnown=!!before.outputCounts&&!!after.outputCounts;
    const equalPieces=outputKnown&&before.required===after.required&&before.fillerPieces===after.fillerPieces&&JSON.stringify(canonical(before.outputCounts))===JSON.stringify(canonical(after.outputCounts));
    const headline=Math.abs(saved)<.005?'No length change':`${Math.abs(percent).toFixed(2)}% ${saved>0?'shorter':'longer'}`;
    return {saved,percent,equalPieces,outputKnown,headline,coveragePoints:100*(after.coverage-before.coverage),
      areaSaved:before.width*before.length-after.width*after.length};
  }
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const number=n=>Number(n.toFixed(3));
  function figure(before,after,key){
    const d=compare(before,after),maxLength=Math.max(before.length,after.length),scale=Math.min(1104/maxLength,190/before.width),stripHeight=before.width*scale;
    const rowStep=stripHeight+88,height=336+2*rowStep;
    const text=(x,y,size,value,fill='#1c2438',weight=400)=>`<text x="${x}" y="${y}" font-size="${size}" fill="${fill}" font-weight="${weight}">${escape(value)}</text>`;
    const f=n=>n.toFixed(2),signed=n=>(n>0?'+':'')+f(n);
    let svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="${number(height)}" viewBox="0 0 1200 ${number(height)}" role="img" aria-labelledby="title desc"><title id="title">EZNest before and after: ${escape(d.headline)}</title><desc id="desc">Same inputs and search budget per run. Blue: required artwork envelopes. Gold: optional fillers. Both layouts use one physical scale. Diagram only, not a print file.</desc><rect width="1200" height="100%" fill="#fff"/><g font-family="Arial, sans-serif">`;
    svg+=text(48,44,14,'EZNEST / LAYOUT COMPARISON','#0066e6',700)+text(48,82,28,d.headline,'#1c2438',700);
    svg+=text(48,114,15,`${before.expected} required pieces | ${f(before.width)} mm roll | ${f(before.gap)} mm gap | ${f(before.margin)} mm margins | ${before.budget} s search per run`);
    svg+=text(48,140,14,`Length ${signed(after.length-before.length)} mm | Coverage ${signed(d.coveragePoints)} percentage points | Filler pieces ${before.fillerPieces} → ${after.fillerPieces}`);
    svg+=text(48,164,13,'Blue: required artwork envelopes    Gold: optional fillers    Same physical scale','#626974');
    [before,after].forEach((s,i)=>{
      const y=204+i*rowStep;
      svg+=text(48,y,17,i?'AFTER / Current best':'BEFORE / First saved fit','#1c2438',700);
      svg+=text(48,y+25,14,`${f(s.length)} mm | ${(s.coverage*100).toFixed(1)}% coverage | ${s.elapsed.toFixed(2)} s layout run | ${s.required}/${s.expected} required | ${s.fillerSets} filler sets | ${s.sheets} sheet(s)`);
      svg+=`<g transform="translate(48 ${y+38}) scale(${scale})"><rect width="${maxLength}" height="${s.width}" fill="#f1f3f6"/><rect width="${s.length}" height="${s.width}" fill="#fff" stroke="#858b95" stroke-width="${1/scale}"/><g transform="translate(0 ${s.width}) rotate(-90)">`;
      for(const p of s.shapes)svg+=`<polygon points="${p.points.map(v=>v.map(number).join(',')).join(' ')}" transform="translate(${number(p.x)} ${number(p.y)}) rotate(${number(p.rotation)})" fill="${p.fill?'#e4bf65':'#bfddf2'}" stroke="#626974" stroke-width="${.6/scale}"/>`;
      svg+='</g>';
      for(const offset of s.sheetOffsets)svg+=`<line x1="${offset}" x2="${offset}" y1="0" y2="${s.width}" stroke="#626974" stroke-dasharray="4 3" stroke-width="${1/scale}"/>`;
      svg+='</g>';
    });
    const foot=204+2*rowStep;
    svg+=text(48,foot,14,d.equalPieces?`Same output piece counts. Material area difference: ${signed(-d.areaSaved/1000000)} m².`:(d.outputKnown?'Output composition differs. Length difference is not an equal-output material saving.':'Output composition was not recorded for the baseline. Equal-output savings are not established.'),'#626974');
    svg+=text(48,foot+25,13,'Both layouts passed completeness and geometry checks. Times belong to the displayed layout runs.','#626974');
    svg+=text(48,foot+48,13,'Additional searches take extra time; this is not a speed benchmark or a guaranteed optimum.','#626974');
    svg+=text(48,foot+71,13,`Same-input reference: ${String(key).slice(0,16)} · Saved in this browser · No physical print/cut verification`,'#626974');
    return svg+'</g></svg>';
  }
  const api={inputs,capture,compare,figure};root.EZNComparison=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:this);
