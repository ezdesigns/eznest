'use strict';
(async()=>{
  const reports=[],assert=(value,message)=>{if(!value)throw Error(message);};
  const close=(a,b)=>assert(Math.abs(a-b)<.05,`${a} is not close to ${b}`);
  const svg=body=>'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'+body+'</svg>';
  const extent=part=>{const x=part.points.map(p=>p[0]),y=part.points.map(p=>p[1]);return [Math.max(...x)-Math.min(...x),Math.max(...y)-Math.min(...y)];};
  async function test(name,fn){try{await fn();reports.push('PASS '+name);}catch(e){reports.push('FAIL '+name+': '+e.message);}document.getElementById('results').textContent=reports.join('\n');}
  await test('Millimeter dimensions and translated viewBox',()=>{const j=EZNSVG.importSVG('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="10 20 100 100"><rect x="10" y="20" width="30" height="40"/></svg>');close(extent(j.parts[0])[0],30);close(extent(j.parts[0])[1],40);close(j.parts[0].svg.origin[0],0);});
  await test('Inches and pixel fallback',()=>{const a=EZNSVG.importSVG('<svg xmlns="http://www.w3.org/2000/svg" width="2in" height="2in" viewBox="0 0 200 200"><rect width="100" height="100"/></svg>');close(extent(a.parts[0])[0],25.4);const b=EZNSVG.importSVG('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect width="96" height="96"/></svg>');close(extent(b.parts[0])[0],25.4);assert(b.importNote.includes('96 pixels'),'Pixel warning missing');});
  await test('Nested transforms and layer appearance',()=>{const j=EZNSVG.importSVG(svg('<g id="Layer_1" fill="#ff8800" transform="translate(5 7) scale(2)"><rect width="10" height="20" transform="rotate(90)"/></g>'));close(extent(j.parts[0])[0],40);close(extent(j.parts[0])[1],20);assert(j.parts[0].svg.inherited.fill==='#ff8800','Inherited fill lost');});
  await test('SVG class and inline paint styles',()=>{const j=EZNSVG.importSVG(svg('<style>.part{fill:#ff0000;stroke:#000000}</style><rect class="part" width="10" height="10" style="fill:#00ff00"/>'));assert(j.parts[0].svg.markup.includes('fill="#00ff00"'),'Style precedence lost');assert(!j.parts[0].svg.markup.includes('style='),'Inline style not converted');});
  await test('Clipping boundary follows group transform',()=>{const j=EZNSVG.importSVG(svg('<defs><clipPath id="c"><rect x="1" y="2" width="10" height="20"/></clipPath></defs><g clip-path="url(#c)" transform="translate(10 15) scale(2)"><rect x="-10" y="-10" width="100" height="100" fill="red"/></g>'));close(extent(j.parts[0])[0],20);close(j.parts[0].svg.origin[0],12);close(j.parts[0].svg.origin[1],19);});
  await test('Reject executable SVG, remote images, open and ambiguous boundaries',()=>{
    const bad=['<script>alert(1)</script><rect width="10" height="10"/>','<rect width="10" height="10" onclick="alert(1)"/>','<image href="https://example.com/image.png"/>','<path d="M0 0L10 0L10 10"/>','<g><rect width="10" height="10"/><circle cx="5" cy="5" r="2"/></g>','<rect width="10" height="10" fill="url(https://example.com/x)"/>','<path d="M0 0H20V20H0ZM5 5H10V10H5Z"/>','<rect width="50%" height="20"/>','<rect width="20" height="10" stroke-width="2%"/>'];
    for(const body of bad){let rejected=false;try{EZNSVG.importSVG(svg(body));}catch(e){rejected=true;}assert(rejected,'Accepted unsafe or unsupported SVG: '+body);}
  });
  await test('Embedded raster survives inside a bounded group',()=>{const j=EZNSVG.importSVG(svg('<g><rect id="EZN_BOUNDARY" width="10" height="10"/><image width="10" height="10" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="/></g>'));const o=EZNSVG.buildSVG(j,{width:30,usedLength:30,placements:[{id:j.parts[0].id,x:3,y:3,rotation:0}]});assert(o.querySelectorAll('image').length===1,'Image lost');});
  const response=await fetch('/sample-artwork.svg'),job=EZNSVG.importSVG(await response.text(),'Verified SVG workshop demo');
  await test('Four complete demo parts and duplicate reference isolation',()=>{assert(job.parts.length===4,'Wrong part count');const out=EZNSVG.buildSVG(job,{width:300,usedLength:300,placements:[{id:'svg-1',x:5,y:5,rotation:0},{id:'svg-1',x:90,y:5,rotation:90}]});const ids=[...out.querySelectorAll('[id]')].map(x=>x.id);assert(ids.length===new Set(ids).size,'Duplicate IDs');assert(out.querySelectorAll('[clip-path]').length===2,'Clipping lost');for(const n of out.querySelectorAll('[clip-path]'))assert(ids.includes(n.getAttribute('clip-path').match(/#([^)]*)/)[1]),'Broken clip reference');});
  await test('Native engine solves quantities and original artwork exports',async()=>{
    job.parts[0].quantity=2;job.parts[1].quantity=2;job.settings={width:180,maxLength:300,gap:3,margin:5,seconds:5,rotations:[0,90,180,270]};
    const session=await (await fetch('/api/session')).json();
    const response=await fetch('/api/solve',{method:'POST',headers:{'Content-Type':'application/json','X-EZ-Token':session.token},body:JSON.stringify(job)});
    const accepted=await response.json();assert(response.ok,accepted.error||'Search rejected');
    let state;
    for(let i=0;i<90;i++){await new Promise(resolve=>setTimeout(resolve,500));state=await(await fetch('/api/state')).json();if(state.status!=='running')break;}
    assert(state.status==='ready',state.error||'Search did not finish');assert(state.result.validated,'Independent validation missing');assert(state.result.placements.length===6,'Quantity mismatch');
    const out=EZNSVG.buildSVG(job,state.result);assert(out.querySelectorAll(':scope > g').length===6,'Artwork part lost');assert(out.querySelectorAll('[clip-path]').length===2,'Repeated clipping lost');assert(out.querySelectorAll('circle').length===2,'Repeated badge artwork lost');
    const serialized=EZNSVG.serialize(out);EZNSVG.sanitize(serialized);
    const roundtrip=EZNSVG.importSVG(serialized,'Export round trip');assert(roundtrip.parts.length===6,'Export cannot be reopened');
    roundtrip.parts.forEach((part,index)=>{
      const placement=state.result.placements[index],original=job.parts.find(p=>p.id===placement.id),r=placement.rotation*Math.PI/180;
      const expected=original.points.map(p=>[placement.x+p[0]*Math.cos(r)-p[1]*Math.sin(r),placement.y+p[0]*Math.sin(r)+p[1]*Math.cos(r)]);
      const xs=expected.map(p=>p[0]),ys=expected.map(p=>p[1]);
      close(part.svg.origin[0],Math.min(...xs));close(part.svg.origin[1],Math.min(...ys));close(extent(part)[0],Math.max(...xs)-Math.min(...xs));close(extent(part)[1],Math.max(...ys)-Math.min(...ys));
    });
    document.getElementById('exported').value=serialized;document.getElementById('job-data').value=JSON.stringify(job);document.getElementById('artwork').append(out);
    reports.push(`METRICS ${state.result.width.toFixed(1)} × ${state.result.usedLength.toFixed(2)} mm; ${(100*state.result.utilization).toFixed(1)}% contour utilization; ${state.result.placements.length} parts`);
  });
  document.getElementById('results').textContent=reports.join('\n')+'\nDONE';
})().catch(e=>{document.getElementById('results').textContent+='\nFATAL '+e.stack;});
