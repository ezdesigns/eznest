#target illustrator
#targetengine "eznest"
/* Original EZ Nest host bridge. Prototype: individual closed PathItems only. */
var EZN = typeof EZN !== 'undefined' ? EZN : {capture:null,applied:{}};
EZN.root = File($.fileName).parent.parent.fsName;
EZN.stringify = function(v){
    if(v===null)return 'null';
    if(typeof v==='string')return '"'+v.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';
    if(typeof v==='number')return isFinite(v)?String(v):'null';
    if(typeof v==='boolean')return v?'true':'false';
    var a=[],i,k;if(v instanceof Array){for(i=0;i<v.length;i++)a.push(EZN.stringify(v[i]));return '['+a.join(',')+']';}
    for(k in v)if(v.hasOwnProperty(k))a.push(EZN.stringify(k)+':'+EZN.stringify(v[k]));return '{'+a.join(',')+'}';
};
EZN.parse = function(text){
    var i=0;
    function ws(){while(i<text.length&&/\s/.test(text.charAt(i)))i++;}
    function str(){var out='',c,h;i++;while(i<text.length){c=text.charAt(i++);if(c==='"')return out;if(c==='\\'){c=text.charAt(i++);if(c==='u'){h=text.substr(i,4);if(!/^[0-9a-fA-F]{4}$/.test(h))throw Error('Invalid JSON escape');out+=String.fromCharCode(parseInt(h,16));i+=4;}else{var m={'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'};if(!m.hasOwnProperty(c))throw Error('Invalid JSON string');out+=m[c];}}else{if(c.charCodeAt(0)<32)throw Error('Invalid JSON character');out+=c;}}throw Error('Unclosed JSON string');}
    function value(){ws();var c=text.charAt(i),a,k,v,m;if(c==='"')return str();if(c==='['){i++;a=[];ws();if(text.charAt(i)===']'){i++;return a;}while(true){a.push(value());ws();c=text.charAt(i++);if(c===']')return a;if(c!==',')throw Error('Invalid JSON array');}}
        if(c==='{'){i++;a={};ws();if(text.charAt(i)==='}'){i++;return a;}while(true){ws();if(text.charAt(i)!=='"')throw Error('Invalid JSON key');k=str();if(k==='__proto__'||k==='constructor'||k==='prototype')throw Error('Invalid key');ws();if(text.charAt(i++)!==':')throw Error('Invalid JSON object');a[k]=value();ws();c=text.charAt(i++);if(c==='}')return a;if(c!==',')throw Error('Invalid JSON object');}}
        var rest=text.substring(i);if(rest.substr(0,4)==='true'){i+=4;return true;}if(rest.substr(0,5)==='false'){i+=5;return false;}if(rest.substr(0,4)==='null'){i+=4;return null;}m=rest.match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);if(m){i+=m[0].length;v=Number(m[0]);if(!isFinite(v))throw Error('Invalid number');return v;}throw Error('Invalid JSON value');}
    var result=value();ws();if(i!==text.length)throw Error('Trailing JSON content');return result;
};
EZN.write=function(name,data){var folder=new Folder(EZN.root+'/.local');if(!folder.exists&&!folder.create())throw Error('Cannot create job folder');var file=new File(folder.fsName+'/'+name);file.encoding='UTF-8';if(!file.open('w'))throw Error('Cannot write '+name);file.write(EZN.stringify(data));file.close();};
EZN.read=function(name){var file=new File(EZN.root+'/.local/'+name);if(!file.exists)throw Error('Prepare a layout in EZ Nest first.');file.encoding='UTF-8';if(!file.open('r'))throw Error('Cannot read '+name);var text=file.read();file.close();return EZN.parse(text.replace(/^\uFEFF/,''));};
EZN.signature=function(item){var a=[item.closed,item.pathPoints.length],i,p;for(i=0;i<item.pathPoints.length;i++){p=item.pathPoints[i];a.push(p.anchor.join(','),p.leftDirection.join(','),p.rightDirection.join(','));}return a.join('|');};
EZN.mid=function(a,b){return [(a[0]+b[0])/2,(a[1]+b[1])/2];};
EZN.dist=function(p,a,b){var dx=b[0]-a[0],dy=b[1]-a[1],d=dx*dx+dy*dy;if(d===0)return Math.sqrt(Math.pow(p[0]-a[0],2)+Math.pow(p[1]-a[1],2));var t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/d));return Math.sqrt(Math.pow(p[0]-a[0]-t*dx,2)+Math.pow(p[1]-a[1]-t*dy,2));};
EZN.curve=function(a,b,c,d,out,depth){if(Math.max(EZN.dist(b,a,d),EZN.dist(c,a,d))<=0.05*72/25.4){out.push(d);return;}if(depth>=16)throw Error('Curve is too complex. Simplify it before capture.');var ab=EZN.mid(a,b),bc=EZN.mid(b,c),cd=EZN.mid(c,d),abc=EZN.mid(ab,bc),bcd=EZN.mid(bc,cd),mid=EZN.mid(abc,bcd);EZN.curve(a,ab,abc,mid,out,depth+1);EZN.curve(mid,bcd,cd,d,out,depth+1);};
// Identify an explicit production boundary while retaining the complete artwork tree.
EZN.children=function(item){var result=[],i,items;if(item.typename==='GroupItem')items=item.pageItems;else if(item.typename==='CompoundPathItem')items=item.pathItems;else return result;for(i=0;i<items.length;i++)if(items[i].parent===item)result.push(items[i]);return result;};
EZN.nodes=function(item){var result=[];function visit(node,depth){if(depth>30||result.length>10000)throw Error('Artwork hierarchy is too complex.');result.push(node);var a=EZN.children(node),i;for(i=0;i<a.length;i++)visit(a[i],depth+1);}visit(item,0);return result;};
EZN.colorKey=function(color){if(!color)return '';if(color.typename==='SpotColor')return color.typename+':'+color.spot.name+':'+color.tint;return color.typename;};
EZN.artSignature=function(item){var nodes=EZN.nodes(item),out=[],i,n;for(i=0;i<nodes.length;i++){n=nodes[i];out.push(n.typename,n.name,n.hidden,n.locked,n.opacity);if(n.typename==='PathItem'){out.push(EZN.signature(n),n.stroked,n.strokeWidth,n.filled,n.clipping,EZN.colorKey(n.strokeColor),EZN.colorKey(n.fillColor));}else{out.push(n.geometricBounds.join(','));if(n.typename==='TextFrame')out.push(n.contents);if(n.typename==='PlacedItem')out.push(n.file.fsName);if(n.typename==='GroupItem')out.push(n.clipped);}}return out.join('|');};
EZN.boundary=function(item){
    var nodes=EZN.nodes(item),explicit=[],cuts=[],masks=[],i,n,children;
    if(item.typename==='PathItem')return {path:item,kind:'Closed path',nodes:nodes,index:0};
    if(item.typename==='CompoundPathItem'&&item.pathItems.length===1)return {path:item.pathItems[0],kind:'Single contour compound path',nodes:nodes,index:1};
    if(item.typename!=='GroupItem')throw Error('Select a whole group or a closed path. Compound boundaries with holes need a later version.');
    for(i=0;i<nodes.length;i++){n=nodes[i];if(n.typename!=='PathItem')continue;if(/^EZN_BOUNDARY$/i.test(n.name))explicit.push(n);if(/^CutContour/i.test(n.name)||(n.stroked&&n.strokeColor.typename==='SpotColor'&&/^CutContour/i.test(n.strokeColor.spot.name)))cuts.push(n);}
    children=EZN.children(item);if(item.clipped)for(i=0;i<children.length;i++)if(children[i].typename==='PathItem'&&children[i].clipping)masks.push(children[i]);
    var boundary,kind;if(explicit.length===1){boundary=explicit[0];kind='Named production boundary';}else if(explicit.length>1)throw Error('More than one EZN_BOUNDARY in this part.');else if(masks.length===1){boundary=masks[0];kind='Outer clipping boundary';}else if(cuts.length===1){boundary=cuts[0];kind='Cut contour (bleed must be included in spacing)';}else if(cuts.length>1)throw Error('Multiple cut contours: select each complete part separately.');else throw Error('No unambiguous outer boundary. Use an outer clipping path or name one closed path EZN_BOUNDARY inside the group.');
    for(i=0;i<nodes.length;i++)if(nodes[i]===boundary)return {path:boundary,kind:kind,nodes:nodes,index:i};
};
EZN.points=function(item){var bounds=item.geometricBounds,raw=[item.pathPoints[0].anchor],points=[],j,p,next,q,scale=25.4/72;
    for(j=0;j<item.pathPoints.length;j++){p=item.pathPoints[j];next=item.pathPoints[(j+1)%item.pathPoints.length];EZN.curve(p.anchor,p.rightDirection,next.leftDirection,next.anchor,raw,0);}
    for(j=0;j<raw.length;j++){q=[(raw[j][0]-bounds[0])*scale,(bounds[1]-raw[j][1])*scale];if(!points.length||Math.abs(q[0]-points[points.length-1][0])+Math.abs(q[1]-points[points.length-1][1])>0.000001)points.push(q);}
    if(points.length>5000)throw Error('Boundary is too complex for this version.');return points;
};
function EZNCapture(){try{
    if(!app.documents.length)throw Error('Open a document and select complete parts.');
    var doc=app.activeDocument,sel=doc.selection;if(!sel||!sel.length||sel.length>100)throw Error('Select 1–100 complete parts.');
    var parts=[],refs=[],issues=[],i,j,item,boundary,bounds,points,description;
    for(i=0;i<sel.length;i++){
        item=sel[i];try{
            if(item.locked||item.hidden)throw Error('Part is locked or hidden.');
            description=EZN.boundary(item);boundary=description.path;
            if(!boundary.closed||boundary.guides||boundary.hidden||boundary.pathPoints.length<3)throw Error('Boundary must be a visible, closed path.');
            if(boundary.pathPoints.length>1000)throw Error('Boundary has too many anchors.');
            for(j=0;j<description.nodes.length;j++)if(description.nodes[j].typename==='PluginItem'||description.nodes[j].typename==='NonNativeItem')throw Error('Expand unsupported plug-in artwork before capture.');
            bounds=boundary.geometricBounds;points=EZN.points(boundary);
            parts.push({id:'part-'+i,name:item.name||'Part '+(i+1),quantity:1,points:points,boundaryKind:description.kind,objectCount:description.nodes.length});
            refs.push({item:item,signature:EZN.artSignature(item),left:bounds[0],top:bounds[1],points:points,boundaryIndex:description.index});
        }catch(problem){issues.push((item.name||'Part '+(i+1))+': '+String(problem.message||problem));}
    }
    if(issues.length)throw Error('Artwork inspection found '+issues.length+' issue(s):\n'+issues.join('\n'));
    var id='capture-'+new Date().getTime();EZN.capture={id:id,document:doc,refs:refs};var data={captureId:id,name:doc.name,parts:parts,bridgeVersion:2};EZN.write('selection.json',data);return EZN.stringify({ok:true,count:parts.length});
}catch(e){return EZN.stringify({ok:false,error:String(e.message||e)});}}
function EZNApply(){var output=null;try{
    var payload=EZN.read('apply.json'),capture=EZN.capture;
    if(!capture||payload.captureId!==capture.id)throw Error('Capture the source paths again in this Illustrator session.');
    if(EZN.applied[payload.runId])throw Error('This layout was already applied. Calculate a new layout for another output.');
    if(app.activeDocument!==capture.document)throw Error('Activate the captured source document before applying.');
    var result=payload.result;if(!result||result.validated!==true||!result.placements.length||result.placements.length>100)throw Error('No validated placement plan.');
    var capturedData=EZN.read('selection.json');if(capturedData.captureId!==capture.id)throw Error('Capture file changed. Capture again.');
    var metrics=[],i,ref,placement,duplicate,b,angle,c,s,m,k=72/25.4;
    for(i=0;i<capture.refs.length;i++){ref=capture.refs[i];if(EZN.artSignature(ref.item)!==ref.signature)throw Error('Source contours changed after capture. Capture and calculate again.');}
    output=app.documents.add(capture.document.documentColorSpace,result.width*k,result.usedLength*k);
    output.artboards[0].artboardRect=[0,0,result.width*k,-result.usedLength*k];output.layers[0].name='EZ NEST — Production copies';
    for(i=0;i<result.placements.length;i++){
        placement=result.placements[i];var match=/^part-([0-9]+)$/.exec(placement.id);if(!match||!capture.refs[Number(match[1])])throw Error('Unknown part reference.');ref=capture.refs[Number(match[1])];
        duplicate=ref.item.duplicate(output.layers[0],ElementPlacement.PLACEATEND);
        var originalNodes=EZN.nodes(ref.item),copyNodes=EZN.nodes(duplicate);if(originalNodes.length!==copyNodes.length)throw Error('Artwork structure changed while duplicating.');var copyBoundary=copyNodes[ref.boundaryIndex];b=copyBoundary.geometricBounds;duplicate.translate(ref.left-b[0],ref.top-b[1]);
        angle=placement.rotation*Math.PI/180;c=Math.cos(angle);s=Math.sin(angle);m=app.getIdentityMatrix();m.mValueA=c;m.mValueB=-s;m.mValueC=s;m.mValueD=c;m.mValueTX=-c*ref.left-s*ref.top+placement.x*k;m.mValueTY=s*ref.left-c*ref.top-placement.y*k;
        duplicate.transform(m,true,true,true,true,100,Transformation.DOCUMENTORIGIN);
        // Restore every nested stroke after the host matrix transformation.
        var objectIndex,originalNode,copyNode;
        for(objectIndex=0;objectIndex<originalNodes.length;objectIndex++){
            originalNode=originalNodes[objectIndex];copyNode=copyNodes[objectIndex];
            if(originalNode.typename!==copyNode.typename)throw Error('Artwork hierarchy changed during placement.');
            if(originalNode.typename==='PathItem'){
                copyNode.strokeWidth=originalNode.strokeWidth;
                if(Math.abs(copyNode.strokeWidth-originalNode.strokeWidth)>0.0001)throw Error('Stroke width changed during placement.');
                if(Math.abs(Math.abs(copyNode.area)-Math.abs(originalNode.area))>0.01)throw Error('Part area changed during placement.');
                if(EZN.colorKey(copyNode.strokeColor)!==EZN.colorKey(originalNode.strokeColor))throw Error('Cut stroke color changed during placement.');
            }
        }
        b=copyBoundary.geometricBounds;var expected=[1e20,1e20,-1e20,-1e20],pts=capturedData.parts[Number(match[1])].points,j,qx,qy;
        for(j=0;j<pts.length;j++){qx=c*pts[j][0]-s*pts[j][1]+placement.x;qy=s*pts[j][0]+c*pts[j][1]+placement.y;expected[0]=Math.min(expected[0],qx);expected[1]=Math.min(expected[1],qy);expected[2]=Math.max(expected[2],qx);expected[3]=Math.max(expected[3],qy);}
        var actual=[b[0]/k,-b[1]/k,b[2]/k,-b[3]/k],err=0;for(j=0;j<4;j++)err=Math.max(err,Math.abs(actual[j]-expected[j]));
        if(err>0.15)throw Error('Placement verification failed for '+placement.id+' ('+err.toFixed(3)+' mm). Source is unchanged.');
        metrics.push({id:placement.id,maxBoundsErrorMM:err,objectCount:copyNodes.length,strokeWidthPoints:copyBoundary.strokeWidth,actual:actual,expected:expected});
    }
    EZN.write('applied-metrics.json',{runId:payload.runId,parts:metrics,sourceName:capture.document.name});EZN.applied[payload.runId]=true;output.selection=null;app.redraw();return EZN.stringify({ok:true,count:result.placements.length});
}catch(e){if(output){try{output.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}return EZN.stringify({ok:false,error:String(e.message||e)});}}
