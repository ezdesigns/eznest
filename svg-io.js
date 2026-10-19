'use strict';
/* Original SVG adapter. Geometry is measured by the browser, in millimeters. */
window.EZNSVG = (() => {
  const NS = 'http://www.w3.org/2000/svg', MM = 25.4 / 96;
  const geometry = new Set(['path','rect','circle','ellipse','polygon']);
  const elements = new Set(['svg','g','defs','path','rect','circle','ellipse','line','polyline','polygon','clipPath','linearGradient','radialGradient','stop','pattern','image','use','title','desc']);
  const presentation = new Set(['fill','fill-opacity','fill-rule','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','opacity','clip-path','clip-rule','color','stop-color','stop-opacity','display','visibility','vector-effect','paint-order']);
  const inherited = ['fill','fill-opacity','fill-rule','clip-rule','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','color','visibility','paint-order'];
  const attrs = new Set([...presentation,'id','d','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','width','height','viewBox','preserveAspectRatio','points','transform','gradientTransform','gradientUnits','spreadMethod','offset','fx','fy','fr','patternUnits','patternContentUnits','patternTransform','clipPathUnits','href','version','data-name','data-ezn-boundary','data-ezn-layer']);
  const serialize = node => new XMLSerializer().serializeToString(node);
  const fail = message => {throw Error(message);};
  function checkValue(value) {
    if (/\\|\/\*|@import|expression\s*\(/i.test(value)) fail('Unsupported SVG style syntax. Export a plain SVG first.');
    for (const match of value.matchAll(/url\s*\((.*?)\)/gi)) {
      if (!/^['"]?#[\w.:-]+['"]?$/.test(match[1].trim())) fail('SVG uses an external resource. Embed images and keep references inside the file.');
    }
  }
  function declarations(text) {
    const result = [];
    for (const entry of text.split(';').filter(x => x.trim())) {
      const colon = entry.indexOf(':');
      if (colon < 1) fail('Invalid SVG style.');
      const key = entry.slice(0,colon).trim(), value = entry.slice(colon+1).trim();
      if (!presentation.has(key) || /!important/i.test(value)) fail('Unsupported SVG style: '+key+'. Expand effects and export a plain SVG.');
      checkValue(value); result.push([key,value]);
    }
    return result;
  }
  function sanitize(text) {
    if (typeof text !== 'string' || text.length > 8_000_000) fail('SVG must be smaller than 8 MB.');
    if (/<!DOCTYPE|<!ENTITY/i.test(text)) fail('SVG document declarations are unsupported. Export a plain SVG without a DTD.');
    const documentSVG = new DOMParser().parseFromString(text,'image/svg+xml');
    if (documentSVG.querySelector('parsererror')) fail('This file is not valid SVG.');
    const root = documentSVG.documentElement;
    if (root.localName !== 'svg' || root.namespaceURI !== NS) fail('Choose an SVG artwork file.');
    root.querySelectorAll('metadata').forEach(node => node.remove());
    const rules = [];
    root.querySelectorAll('style').forEach(style => {
      const css = style.textContent.replace(/\/\*[\s\S]*?\*\//g,'');
      let remainder = css;
      for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const values = declarations(match[2]);
        for (const raw of match[1].split(',')) {
          const selector = raw.trim();
          if (!/^(?:[a-zA-Z][\w-]*)?(?:[.#][a-zA-Z_][\w-]*)*$/.test(selector) || !selector) fail('SVG contains complex CSS. Export with presentation attributes.');
          const weight = (selector.match(/#/g)||[]).length*100+(selector.match(/\./g)||[]).length*10+(/^[a-zA-Z]/.test(selector)?1:0);
          rules.push({selector,values,weight});
        }
        remainder = remainder.replace(match[0],'');
      }
      if (remainder.trim()) fail('Unsupported SVG stylesheet. Export with presentation attributes.');
      style.remove();
    });
    rules.sort((a,b)=>a.weight-b.weight);
    const ids = new Set();
    for (const node of [root,...root.querySelectorAll('*')]) {
      if (node.namespaceURI !== NS || !elements.has(node.localName)) fail('Unsupported SVG element: '+node.localName+'. Outline text and expand effects before exporting.');
      if (node !== root && node.localName === 'svg') fail('Nested SVG viewports are not supported yet. Export separate top-level groups.');
      const inline = declarations(node.getAttribute('style')||'');
      for (const rule of rules) if (node.matches(rule.selector)) for (const [key,value] of rule.values) node.setAttribute(key,value);
      for (const [key,value] of inline) node.setAttribute(key,value);
      for (const attribute of [...node.attributes]) {
        const key = attribute.localName, value = attribute.value;
        if (/^on/i.test(key)) fail('SVG contains an event handler. Use a static artwork export.');
        if (attribute.namespaceURI === 'http://www.w3.org/2000/xmlns/') continue;
        if (key === 'style' || key === 'class') {node.removeAttributeNode(attribute);continue;}
        if (attribute.namespaceURI && attribute.namespaceURI !== 'http://www.w3.org/1999/xlink') {
          if (key === 'label') node.setAttribute('data-name',value);
          if (key === 'groupmode' && value === 'layer') node.setAttribute('data-ezn-layer','true');
          node.removeAttributeNode(attribute);continue;
        }
        if (!attrs.has(key)) fail('Unsupported SVG attribute: '+key+'. Export a plain SVG with effects expanded.');
        if (key === 'id') {if (!/^[\w.:-]+$/.test(value)||ids.has(value)) fail('SVG IDs must be unique and contain no spaces.');ids.add(value);}
        if (key === 'href') {
          if (!/^#[\w.:-]+$/.test(value) && !(node.localName==='image' && /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+$/.test(value))) fail('Linked images are unsupported. Embed the image in your SVG.');
        } else checkValue(value);
        if (key === 'vector-effect' && value !== 'none') fail('Non-scaling strokes are unsupported. Expand the stroke before importing.');
        if (key === 'display' && value !== 'none' && value !== 'inline') fail('Unsupported SVG display mode.');
        const relativeLength=/[%]|(?:em|ex|ch|rem|vw|vh)\b/i.test(value);
        if(relativeLength && ['x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','width','height','fx','fy','fr','stroke-width','stroke-dasharray','stroke-dashoffset'].includes(key)) {
          const boxGradient=['linearGradient','radialGradient'].includes(node.localName)&&node.getAttribute('gradientUnits')!=='userSpaceOnUse';
          if(!boxGradient)fail('Relative SVG geometry is unsupported. Export with absolute coordinates and sizes.');
        }
      }
    }
    // Resolve references before mounting. Cyclic use/paint references are rejected.
    const active = new Set(), done = new Set();
    function references(node) {
      if (active.has(node)) fail('SVG contains a circular reference.');
      if (done.has(node)) return;
      active.add(node);
      for (const child of [node,...node.querySelectorAll('*')]) for (const attribute of child.attributes) {
        const refs = [...attribute.value.matchAll(/url\s*\(['"]?#([\w.:-]+)['"]?\)/g)].map(m=>m[1]);
        if (attribute.localName === 'href' && attribute.value.startsWith('#')) refs.push(attribute.value.slice(1));
        for (const id of refs) {const target=documentSVG.getElementById(id);if(!target)fail('SVG reference is missing: '+id);references(target);}
      }
      active.delete(node);done.add(node);
    }
    for (const node of root.children) references(node);
    return root;
  }
  function size(value,fallback) {
    if (!value) return {mm:fallback*MM,assumed:true};
    const m = /^\s*([+]?\d*\.?\d+(?:e[+-]?\d+)?)\s*(mm|cm|in|pt|pc|px)?\s*$/i.exec(value);
    if (!m || !(Number(m[1])>0)) fail('SVG needs a positive width and height in mm, cm, inches, points or pixels.');
    return {mm:Number(m[1])*({mm:1,cm:10,in:25.4,pt:25.4/72,pc:25.4/6,px:MM}[m[2]?.toLowerCase()]||MM),assumed:!m[2]||m[2]==='px'};
  }
  function visible(node,root) {
    for(let p=node;p&&p!==root.parentElement;p=p.parentElement) if(p.getAttribute('display')==='none'||p.getAttribute('visibility')==='hidden'||p.getAttribute('visibility')==='collapse'||p.getAttribute('opacity')==='0')return false;
    return true;
  }
  function partsOf(root) {
    const result=[];
    function visit(parent) {
      for (const node of parent.children) {
        if (['defs','title','desc'].includes(node.localName)||!visible(node,root))continue;
        const layer = node.localName==='g' && (node.getAttribute('data-ezn-layer')==='true'||/^layer[_ -]?\d+$/i.test(node.id));
        if(layer) {
          if(node.hasAttribute('clip-path')||node.hasAttribute('opacity'))fail('A layer has clipping or opacity. Make each complete part a top-level group before importing.');
          visit(node);
        } else result.push(node);
      }
    }
    visit(root); return result;
  }
  function closed(node) {
    if(!geometry.has(node.localName))fail('A nesting boundary must be a closed path, polygon, rectangle, ellipse or circle.');
    if(node.localName==='path') {
      const d=node.getAttribute('d')||'';
      if((d.match(/[mM]/g)||[]).length!==1||(d.match(/[zZ]/g)||[]).length!==1||!/[zZ]\s*$/.test(d))fail('Boundary must be one closed outline without holes or disconnected subpaths.');
    }
  }
  function localMatrix(node) {return node.transform?.baseVal.consolidate()?.matrix || node.ownerSVGElement.createSVGMatrix();}
  function boundary(part,root) {
    const shapes=[part,...part.querySelectorAll('*')].filter(n=>geometry.has(n.localName)&&!n.closest('defs'));
    const explicit=shapes.filter(n=>n.hasAttribute('data-ezn-boundary')||/^EZN_BOUNDARY(?:$|[-_])/i.test(n.getAttribute('data-name')||n.id));
    if(explicit.length>1)fail('More than one EZN_BOUNDARY in a part. Keep one outer boundary.');
    if(explicit.length===1)return {node:explicit[0],matrix:explicit[0].getCTM(),kind:'Named boundary'};
    if(geometry.has(part.localName))return {node:part,matrix:part.getCTM(),kind:'Closed outline'};
    const clipping=part.getAttribute('clip-path');
    if(clipping) {
      const id=/url\s*\(['"]?#([\w.:-]+)['"]?\)/.exec(clipping)?.[1];
      const clip=[...root.querySelectorAll('clipPath')].find(n=>n.id===id);
      if(!clip||clip.getAttribute('clipPathUnits')==='objectBoundingBox')fail('Use a single clipping outline with userSpaceOnUse coordinates.');
      const children=[...clip.children].filter(n=>!['title','desc'].includes(n.localName));
      if(children.length!==1||!geometry.has(children[0].localName))fail('Clipping boundary must contain one simple closed shape.');
      return {node:children[0],matrix:part.getCTM().multiply(localMatrix(clip)).multiply(localMatrix(children[0])),kind:'Clipping outline'};
    }
    const cuts=shapes.filter(n=>/cutcontour/i.test(n.getAttribute('data-name')||n.id));
    if(cuts.length===1)return {node:cuts[0],matrix:cuts[0].getCTM(),kind:'Cut contour'};
    const children=[...part.children].filter(n=>!['defs','title','desc'].includes(n.localName));
    if(part.localName==='g'&&children.length===1)return boundary(children[0],root);
    fail('Group “'+(part.getAttribute('data-name')||part.id||'unnamed')+'” needs one clipping outline, one CutContour path, or a closed path named EZN_BOUNDARY.');
  }
  function flatten(node,matrix) {
    closed(node);
    if(!matrix||![matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f].every(Number.isFinite))fail('Invalid SVG transform.');
    const length=node.getTotalLength();
    if(!(length>0)||!Number.isFinite(length))fail('Boundary has no usable size.');
    const scale=Math.hypot(matrix.a,matrix.b,matrix.c,matrix.d)*MM;
    const point=s=>{const p=node.getPointAtLength(s).matrixTransform(matrix);return [p.x*MM,p.y*MM];};
    const result=[point(0)], tolerance=.02;
    function segment(a,b,pa,pb,depth) {
      const m=(a+b)/2,pm=point(m), chord=Math.hypot(pb[0]-pa[0],pb[1]-pa[1]);
      const dx=pb[0]-pa[0],dy=pb[1]-pa[1];
      const distance=p=>{const t=chord?Math.max(0,Math.min(1,((p[0]-pa[0])*dx+(p[1]-pa[1])*dy)/(chord*chord))):0;return Math.hypot(p[0]-pa[0]-t*dx,p[1]-pa[1]-t*dy);};
      const error=Math.max(distance(pm),distance(point((3*a+b)/4)),distance(point((a+3*b)/4)));
      if(depth<22 && (error>tolerance||(chord<tolerance&&(b-a)*scale>tolerance*2))) {segment(a,m,pa,pm,depth+1);segment(m,b,pm,pb,depth+1);}
      else {if(error>tolerance)fail('Boundary could not be flattened accurately.');result.push(pb);if(result.length>5000)fail('Boundary is too complex. Simplify the outline before importing.');}
    }
    // Seed each path with short arc-length spans so tiny corners are not skipped.
    const count=Math.min(1000,Math.max(32,Math.ceil(length*scale/2)));
    for(let i=0;i<count;i++)segment(length*i/count,length*(i+1)/count,point(length*i/count),point(length*(i+1)/count),0);
    if(Math.hypot(result.at(-1)[0]-result[0][0],result.at(-1)[1]-result[0][1])<.00001)result.pop();
    return result.filter((p,i)=>!i||Math.hypot(p[0]-result[i-1][0],p[1]-result[i-1][1])>.000001);
  }
  function importSVG(text,name='SVG artwork') {
    const root=sanitize(text), vb=(root.getAttribute('viewBox')||'').trim().split(/[\s,]+/).map(Number);
    if(root.hasAttribute('opacity')||root.hasAttribute('clip-path'))fail('Root SVG opacity or clipping must be moved into each part group before importing.');
    if(!root.hasAttribute('color'))root.setAttribute('color','#000000');
    const w=size(root.getAttribute('width'),vb[2]),h=size(root.getAttribute('height'),vb[3]);
    if(!Number.isFinite(w.mm)||!Number.isFinite(h.mm)||w.mm>10000||h.mm>10000)fail('SVG physical size is missing or exceeds 10 meters.');
    if(root.hasAttribute('viewBox')&&(vb.length!==4||!vb.every(Number.isFinite)||vb[2]<=0||vb[3]<=0))fail('Invalid SVG viewBox.');
    root.setAttribute('width',w.mm/MM);root.setAttribute('height',h.mm/MM);
    const mount=document.createElement('div');mount.className='svg-measure';mount.append(document.importNode(root,true));document.body.append(mount);
    const live=mount.firstElementChild;
    try {
      const nodes=partsOf(live);
      if(!nodes.length||nodes.length>800)fail('SVG needs between 1 and 800 visible parts.');
      const definitions=[...live.querySelectorAll('defs')].filter(n=>!n.parentElement.closest('defs')).map(serialize).join('');
      const parts=nodes.map((part,index)=>{
        const b=boundary(part,live), points=flatten(b.node,b.matrix), origin=[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1]))];
        const parent=part.parentElement.getCTM();
        const inheritedAttributes={};
        for(let p=part.parentElement;p&&p!==mount;p=p.parentElement)for(const key of inherited)if(!(key in inheritedAttributes)&&p.hasAttribute(key))inheritedAttributes[key]=p.getAttribute(key);
        if(part.contains(b.node))b.node.setAttribute('data-ezn-boundary','true');
        const clone=part.cloneNode(true);clone.querySelectorAll('defs').forEach(n=>n.remove());
        clone.removeAttribute('data-ezn-layer');
        return {id:'svg-'+(index+1),name:part.getAttribute('data-name')||part.id||'Part '+(index+1),quantity:1,boundaryKind:b.kind,objectCount:1+part.querySelectorAll('*').length,
          points:points.map(p=>[p[0]-origin[0],p[1]-origin[1]]),svg:{markup:serialize(clone),parent:[parent.a,parent.b,parent.c,parent.d,parent.e,parent.f].map(x=>x*MM),origin,inherited:inheritedAttributes}};
      });
      return {name,parts,svgSource:{defs:definitions,widthMM:w.mm,heightMM:h.mm},importNote:(w.assumed||h.assumed?'SVG pixel dimensions interpreted at 96 pixels per inch. ':'')+'Imported '+nodes.length+' complete parts. Check the cut boundaries and physical dimensions before production.'};
    } finally {mount.remove();}
  }
  function prefixIDs(root,prefix) {
    for(const node of [root,...root.querySelectorAll('*')])for(const attr of [...node.attributes]){
      if(attr.localName==='id')attr.value=prefix+attr.value;
      else if(attr.localName==='href'&&attr.value.startsWith('#'))attr.value='#'+prefix+attr.value.slice(1);
      else attr.value=attr.value.replace(/url\s*\(['"]?#([\w.:-]+)['"]?\)/g,(_,id)=>'url(#'+prefix+id+')');
    }
  }
  function buildSVG(job,result) {
    const output=document.createElementNS(NS,'svg');output.setAttribute('xmlns',NS);output.setAttribute('width',result.width+'mm');output.setAttribute('height',result.usedLength+'mm');output.setAttribute('viewBox',`0 0 ${result.width} ${result.usedLength}`);
    const description=document.createElementNS(NS,'desc');description.textContent='EZ Nest artwork layout. Spacing uses imported boundaries; bleed and RIP spot colors require separate verification.';output.append(description);
    result.placements.forEach((placement,index)=>{
      const part=job.parts.find(p=>p.id===placement.id);
      if(!part?.svg||(!job.svgSource&&!job.svgSources))fail('Original SVG artwork is unavailable for this job.');
      const source=part.svg;
      if(source.parent.length!==6||source.origin.length!==2||![...source.parent,...source.origin].every(Number.isFinite))fail('Invalid saved artwork transform.');
      const definitions=job.svgSources?.[part.sourceJobId]?.defs ?? job.svgSource?.defs;
      if(typeof definitions!=='string')fail('The source artwork definitions are missing.');
      const fragment=sanitize('<svg xmlns="'+NS+'">'+definitions+'<g>'+source.markup+'</g></svg>');
      prefixIDs(fragment,'ez'+index+'_');
      const outer=document.createElementNS(NS,'g');outer.setAttribute('id','ez-part-'+(index+1));
      outer.setAttribute('transform',`translate(${placement.x} ${placement.y}) rotate(${placement.rotation}) translate(${-source.origin[0]} ${-source.origin[1]})`);
      const inner=document.createElementNS(NS,'g');inner.setAttribute('transform','matrix('+source.parent.join(' ')+')');
      for(const [key,value] of Object.entries(source.inherited||{})){if(!inherited.includes(key))fail('Invalid saved SVG appearance.');checkValue(value);inner.setAttribute(key,value.replace(/url\s*\(['"]?#([\w.:-]+)['"]?\)/g,(_,id)=>'url(#ez'+index+'_'+id+')'));}
      for(const child of [...fragment.children])inner.append(document.importNode(child,true));
      outer.append(inner);output.append(outer);
    });
    return output;
  }
  return {importSVG,buildSVG,serialize,sanitize};
})();
