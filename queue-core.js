'use strict';
(function(root){
  function codeFor(index){let s='';for(let n=index+1;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
  function compose(entries,preset,mode='combined',options={}){
    const selected=entries.filter(e=>e.selected&&!isPrepared(e));
    if(!selected.length)throw Error('Select at least one ready job.');
    if(mode==='single'&&selected.length!==1)throw Error('Choose one job for this print.');
    const formats=new Set(selected.map(e=>e.data?.format==='pdf'?'pdf':'svg'));
    if(formats.size>1)throw Error('Nest PDF/AI jobs together, and SVG jobs in a separate batch. This preserves the original print artwork.');
    const job={name:selected.length===1?selected[0].name:selected.length+' production jobs',materialId:preset.id,materialName:preset.name,settings:{...preset.settings},parts:[],productionJobs:[],svgSources:{},fillJobs:[],fillArea:options.fillArea||'gaps'};
    if(options.maxLength!==undefined)job.settings.maxLength=options.maxLength;
    for(const [index,entry] of selected.entries()){
      const pdf=entry.data?.format==='pdf';
      if(entry.status!=='ready'||(!pdf&&!entry.data?.svgSource))throw Error(entry.name+' is not ready.');
      if(pdf&&!entry.data.reviewed)throw Error('Review detected pieces and bleed in Job options for '+entry.name+'.');
      if(entry.materialId!==preset.id)throw Error('Use one material preset per batch. Change the selected jobs or their assigned material.');
      if(!Number.isInteger(entry.sets)||entry.sets<1||entry.sets>800)throw Error('Sets must be a whole number from 1 to 800.');
      const source={id:entry.id,code:codeFor(index),name:entry.name,sourceFile:entry.sourceFile||entry.name,revision:entry.revision,sets:entry.sets,materialId:entry.materialId,partIds:[],role:entry.role==='fill'?'fill':'required',customer:entry.customer||'',order:entry.order||'',kit:entry.kit||''};
      const parts=[];
      if(pdf){job.documentSources=job.documentSources||{};job.documentSources[entry.id]={documentId:entry.data.documentId,reviewed:entry.data.reviewed,bleedMm:entry.data.bleedMm};}
      else job.svgSources[entry.id]=entry.data.svgSource;
      for(const part of entry.data.parts){
        const id=entry.id+':'+part.id,perSet=part.quantity||1;
        source.partIds.push(id);parts.push({...part,id,sourceJobId:entry.id,originalPartId:part.id,perSet,quantity:perSet*entry.sets});
      }
      if(source.role==='fill')job.fillJobs.push({source,parts,maxSets:entry.sets});
      else {job.productionJobs.push(source);job.parts.push(...parts);}
    }
    if(job.parts.reduce((sum,p)=>sum+p.quantity,0)>800)throw Error('This build supports 800 pieces per batch. Select fewer jobs or sets.');
    if(job.fillJobs.length&&(!job.parts.length||job.fillArea==='length')&&job.settings.maxLength==null)throw Error('Enter a roll length to fill with stickers, or add required jobs and fill only their leftover space.');
    return job;
  }
  function count(entry){return (entry.data?.parts||[]).reduce((sum,p)=>sum+(p.quantity||1),0)*entry.sets;}
  function isPrepared(entry){return !!entry.preparedRevision&&entry.preparedRevision===entry.revision;}
  function markPrepared(entries,state){
    if(!state?.released||state.deliveryCompleted!==true||!state.manifest||!state.id||state.manifest.outputCheck?.ready===false)return 0;
    let count=0;
    for(const source of state.job.productionJobs){
      const placed=state.manifest.jobs.find(j=>j.id===source.id);
      const entry=entries.find(e=>e.id===source.id&&e.revision===source.revision);
      if(!entry||!placed?.placed||entry.lastPreparedBatch===state.id)continue;
      entry.preparedRevision=entry.revision;entry.exportedRevision=entry.revision;
      entry.preparedBatch=state.id;entry.lastPreparedBatch=state.id;
      entry.preparedAt=state.manifest.createdAt||new Date().toISOString();
      entry.savedPieces=placed.placed;entry.selected=false;count++;
    }
    return count;
  }
  function restorePrepared(entry){delete entry.preparedRevision;delete entry.exportedRevision;entry.selected=false;}
  function groupName(entry,mode,presets=[]){
    if(mode==='customer')return entry.customer?.trim()||'No customer assigned';
    if(mode==='order')return [entry.customer?.trim(),entry.order?.trim()].filter(Boolean).join(' / ')||'No order assigned';
    if(mode==='material')return presets.find(p=>p.id===entry.materialId)?.name||'Unassigned material';
    if(mode==='category')return entry.category?.trim()||'Uncategorized';
    if(entry.origin==='folder'){
      const parent=(entry.sourceFile||entry.name).replace(/\\/g,'/').split('/').slice(0,-1).join(' / ');
      return (entry.sourceRoot||'Source folder')+(parent?' / '+parent:'');
    }
    return entry.id.startsWith('demo-')?'Examples':'Added files';
  }
  function unitScale(unit){if(!['mm','cm','in'].includes(unit))throw Error('Choose inches, millimeters or centimeters.');return unit==='in'?25.4:unit==='cm'?10:1;}
  function validatePreset(p){
    if(!p||typeof p.name!=='string'||!p.name.trim()||p.name.length>80||!['mm','in','cm'].includes(p.units))throw Error('Invalid preset name or units.');
    const s=p.settings||{},finite=(k,lo,hi)=>typeof s[k]==='number'&&Number.isFinite(s[k])&&s[k]>=lo&&s[k]<=hi;
    if(!finite('width',10,5000)||(s.maxLength!==null&&!finite('maxLength',10,5000))||!finite('gap',0,100)||!finite('margin',0,100)||!finite('seconds',1,120)||s.margin*2>=s.width||(s.maxLength!==null&&s.margin*2>=s.maxLength))throw Error('Invalid material dimensions, margins or search time.');
    if(s.rotations!==null&&!['[0]','[0,180]','[0,90,180,270]'].includes(JSON.stringify(s.rotations)))throw Error('Invalid preset rotation rules.');
    if(s.sheetLength!=null&&(!finite('sheetLength',10,5000)||s.sheetLength<=s.margin*2))throw Error('Sheet length must leave room inside the margins.');
    if(s.costPerSquareMeter!=null&&!finite('costPerSquareMeter',0,1000000))throw Error('Enter a nonnegative material cost.');
    if(s.currency!=null&&!/^[A-Za-z]{3}$/.test(s.currency))throw Error('Use a three-letter currency code.');
    if(s.markMargin!=null&&!finite('markMargin',0,100))throw Error('Invalid mark margin.');
    if(s.edgeMargin!=null&&!finite('edgeMargin',0,100))throw Error('Invalid edge margin.');
    if(s.rollWidth!=null&&!finite('rollWidth',10,5000))throw Error('Invalid roll width.');
    if(s.autoBleedMm!=null&&!finite('autoBleedMm',0,25))throw Error('Auto bleed must be from 0 to 25 mm.');
    if(s.drawRegmarks!=null&&typeof s.drawRegmarks!=='boolean')throw Error('Registration marks are on or off.');
    const settings=Object.fromEntries(['width','maxLength','gap','margin','seconds','rotations'].map(k=>[k,s[k]]));
    for(const k of ['sheetLength','costPerSquareMeter','currency','markMargin','edgeMargin','rollWidth','autoBleedMm','drawRegmarks'])if(s[k]!==undefined)settings[k]=s[k];
    return {name:p.name.trim(),units:p.units,settings};
  }
  function importPresets(document){
    if(document?.format!=='eznest.material-presets'||document.version!==1||!Array.isArray(document.presets)||!document.presets.length||document.presets.length>100)throw Error('Choose an eznest material preset file (version 1).');
    return document.presets.map(validatePreset);
  }
  const api={compose,count,codeFor,validatePreset,importPresets,isPrepared,markPrepared,restorePrepared,groupName,unitScale};root.EZNQueue=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:this);
