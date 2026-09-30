'use strict';
(function(root){
  const operations=['thru','kiss','contour'];
  function defaults(){
    const rules=[];
    for(const [operation,layers,spots] of [
      ['thru',['Thru-cut','thru-cut','LNThru-cut'],['CutContour_Thru-cut','CutContourThruCut']],
      ['kiss',['Kiss-cut','kiss-cut','LNKiss-cut','CutContour_Kiss-cut'],['CutContour_Kiss-cut','CutContourKissCut']],
      ['regmark',['Regmark','LNRegmark'],['Regmark','LNRegmark']]]){
      for(const [source,names] of [['layer',layers],['spot',spots]])for(const name of names)rules.push({source,match:'exact',name,operation});
    }
    return {version:1,rules,genericOperation:'',outputs:{thru:{spot:'CutContour_Thru-cut',layer:'Thru-cut',toolHint:''},kiss:{spot:'CutContour_Kiss-cut',layer:'Kiss-cut',toolHint:''},contour:{spot:'CutContour',layer:'CutContour',toolHint:''}},suspectPrefixes:['CutContour','Thru-cut','Kiss-cut','LNThru-cut','LNKiss-cut','Regmark','LNRegmark']};
  }
  function validate(value){
    if(!value||value.version!==1)throw Error('Choose a version 1 cut mapping.');
    const text=(value,label,empty=false)=>{if(typeof value!=='string'||value.length>80||/[\x00-\x1f\x7f]/.test(value)||(!empty&&!value.trim()))throw Error('Invalid cut mapping '+label+'.');return value.trim();};
    if(!Array.isArray(value.rules)||value.rules.length<1||value.rules.length>100)throw Error('Use between 1 and 100 cut mapping rules.');
    const rules=[];
    for(const rule of value.rules){
      if(!rule||!['spot','layer'].includes(rule.source)||!['exact','prefix'].includes(rule.match)||![...operations,'regmark'].includes(rule.operation))throw Error('Invalid cut mapping rule.');
      const item={source:rule.source,match:rule.match,operation:rule.operation,name:text(rule.name,'source name')};
      if(rules.some(r=>r.source===item.source&&r.match===item.match&&r.name===item.name&&r.operation!==item.operation))throw Error('One source name cannot map to different cut operations.');
      if(!rules.some(r=>JSON.stringify(r)===JSON.stringify(item)))rules.push(item);
    }
    const genericOperation=value.genericOperation??'';
    if(!['',...operations].includes(genericOperation))throw Error('Choose how unspecified cut paths should be handled.');
    const outputs={};for(const op of operations){const raw=value.outputs?.[op]||{};outputs[op]={spot:text(raw.spot,'spot'),layer:text(raw.layer,'layer'),toolHint:text(raw.toolHint??'','toolHint',true)};}
    for(const key of ['spot','layer'])if(new Set(Object.values(outputs).map(o=>o[key])).size!==operations.length)throw Error('Each cut type needs a different output '+key+' name.');
    const prefixes=value.suspectPrefixes??[];if(!Array.isArray(prefixes)||prefixes.length>40)throw Error('Invalid cut-name prefixes.');
    return {version:1,rules,genericOperation,outputs,suspectPrefixes:[...new Set(prefixes.map(p=>text(p,'prefix')))]};
  }
  function formatCounts(counts){return [['thru','thru-cut'],['kiss','kiss-cut'],['contour','generic cut']].filter(([op])=>counts?.[op]).map(([op,label])=>counts[op]+' '+label+' path'+(counts[op]===1?'':'s')).join(' · ')||'No cut paths';}
  const api={defaults,validate,formatCounts,operations};if(typeof module!=='undefined')module.exports=api;else root.EZNCuts=api;
})(typeof window!=='undefined'?window:this);
