'use strict';
(function(root){
  function codeFor(index){let s='';for(let n=index+1;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
  function compose(entries,preset,mode='combined',options={}){
    const selected=entries.filter(e=>e.selected&&!isPrepared(e));
    if(!selected.length)throw Error('Select at least one ready job.');
    if(mode==='single'&&selected.length!==1)throw Error('Choose one job for this print.');
    const job={name:selected.length===1?selected[0].name:selected.length+' production jobs',materialId:preset.id,materialName:preset.name,settings:{...preset.settings},parts:[],productionJobs:[],svgSources:{},fillJobs:[],fillArea:options.fillArea||'gaps'};
    if(options.maxLength!==undefined)job.settings.maxLength=options.maxLength;
    for(const [index,entry] of selected.entries()){
      if(entry.status!=='ready'||!entry.data?.svgSource)throw Error(entry.name+' is not ready.');
      if(entry.materialId!==preset.id)throw Error('Use one material preset per batch. Change the selected jobs or their assigned material.');
      if(!Number.isInteger(entry.sets)||entry.sets<1||entry.sets>100)throw Error('Sets must be a whole number from 1 to 100.');
      const source={id:entry.id,code:codeFor(index),name:entry.name,sourceFile:entry.sourceFile||entry.name,revision:entry.revision,sets:entry.sets,materialId:entry.materialId,partIds:[],role:entry.role==='fill'?'fill':'required'};
      const parts=[];
      job.svgSources[entry.id]=entry.data.svgSource;
      for(const part of entry.data.parts){
        const id=entry.id+':'+part.id,perSet=part.quantity||1;
        source.partIds.push(id);parts.push({...part,id,sourceJobId:entry.id,originalPartId:part.id,perSet,quantity:perSet*entry.sets});
      }
      if(source.role==='fill')job.fillJobs.push({source,parts,maxSets:entry.sets});
      else {job.productionJobs.push(source);job.parts.push(...parts);}
    }
    if(job.parts.reduce((sum,p)=>sum+p.quantity,0)>100)throw Error('This build supports 100 pieces per batch. Select fewer jobs or sets.');
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
    return {name:p.name.trim(),units:p.units,settings:Object.fromEntries(['width','maxLength','gap','margin','seconds','rotations'].map(k=>[k,s[k]]))};
  }
  function importPresets(document){
    if(document?.format!=='eznest.material-presets'||document.version!==1||!Array.isArray(document.presets)||!document.presets.length||document.presets.length>100)throw Error('Choose an eznest material preset file (version 1).');
    return document.presets.map(validatePreset);
  }
  const api={compose,count,codeFor,validatePreset,importPresets,isPrepared,markPrepared,restorePrepared,groupName,unitScale};if(typeof module!=='undefined')module.exports=api;else root.EZNQueue=api;
})(typeof window!=='undefined'?window:this);
