/* Original local handoff utilities; ES3 for Illustrator ExtendScript. */
var EZPilot = {};
// Revalidate saved choices against this Illustrator installation on every run.
EZPilot.validPreferences = function(p, names) {
    if(!p || p.version!==1 || p.material!=='regular' || typeof p.pdfPreset!=='string')return false;
    if(typeof p.widthIn!=='number'||!isFinite(p.widthIn)||p.widthIn<1||p.widthIn>196)return false;
    if(typeof p.bleedMm!=='number'||!isFinite(p.bleedMm)||p.bleedMm<0||p.bleedMm>25)return false;
    for(var i=0;i<names.length;i++)if(String(names[i])===p.pdfPreset)return true;
    return false;
};
EZPilot.readPreferences = function(file, names) {
    if(!file.exists)return null;
    try {
        file.encoding='UTF-8';if(!file.open('r'))return null;
        var text;try{text=file.read();}finally{file.close();}
        var p=EZPilot.parse(text);return EZPilot.validPreferences(p,names)?p:null;
    }catch(ignore){return null;}
};
EZPilot.writePreferences = function(file, p) {
    if(!file.parent.exists&&!file.parent.create())throw Error('Cannot create the eznest settings folder.');
    file.encoding='UTF-8';if(!file.open('w'))throw Error('Cannot save Illustrator settings.');
    try{if(!file.write(EZPilot.stringify(p)))throw Error('Cannot save Illustrator settings.');}finally{file.close();}
};
EZPilot.base64 = function(text) {
    var chars='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/',out='',i,a,b,c;
    for(i=0;i<text.length;i+=3){
        a=text.charCodeAt(i)&255;b=i+1<text.length?text.charCodeAt(i+1)&255:0;c=i+2<text.length?text.charCodeAt(i+2)&255:0;
        out+=chars.charAt(a>>2)+chars.charAt(((a&3)<<4)|(b>>4))+(i+1<text.length?chars.charAt(((b&15)<<2)|(c>>6)):'=')+(i+2<text.length?chars.charAt(c&63):'=');
    }
    return out;
};
EZPilot.cutType = function(item) {
    var name='',parent=item,layer='';
    if(item.stroked&&item.strokeColor&&item.strokeColor.typename==='SpotColor')name=item.strokeColor.spot.name;
    // A group's mask stays with the artwork, even when its parent layer is a
    // cut layer. A painted cut-colour mask is ambiguous and must be separated.
    if(item.clipping){
        if(/^CutContour/.test(name))throw Error('A clipping mask is also painted as a cut. Keep its artwork mask and cut stroke separate.');
        return '';
    }
    while(parent){if(parent.typename==='Layer'){layer=parent.name.toLowerCase();break;}parent=parent.parent;}
    var byLayer=layer==='thru-cut'?'thru':layer==='kiss cut'?'kiss':'';
    var bySpot=/^CutContour_Thru-cut$/.test(name)?'thru':/^CutContour_Kiss-cut$/.test(name)?'kiss':'';
    if(byLayer&&bySpot&&byLayer!==bySpot)throw Error('A cut layer and its spot color disagree.');
    if(name==='CutContour'&&!byLayer)throw Error('Put generic CutContour strokes on thru-cut or kiss cut before preparing.');
    if(/^CutContour/.test(name)&&!byLayer&&!bySpot)throw Error('Unrecognized cut spot: '+name);
    return byLayer||bySpot;
};
EZPilot.documentRoots = function(source) {
    var items=[],i,item,parent,visible;
    for(i=0;i<source.pageItems.length;i++){
        item=source.pageItems[i];parent=item;visible=true;
        while(parent&&parent!==source){
            if(parent.hidden||parent.locked||(parent.typename==='Layer'&&parent.visible===false)){visible=false;break;}
            parent=parent.parent;
        }
        if(visible)items.push(item);
    }
    return EZPilot.selectionRoots(items);
};
EZPilot.selectionRoots = function(selected) {
    var roots=[],i,j,parent,covered;
    if(!selected||!selected.length)throw Error('Select the complete artwork and its cut paths.');
    for(i=0;i<selected.length;i++){
        if(selected[i].typename==='TextRange'||selected[i].locked||selected[i].hidden)throw Error('Select complete, unlocked artwork objects.');
        covered=false;
        for(j=0;j<i;j++)if(selected[j]===selected[i])covered=true;
        parent=selected[i].parent;
        while(parent&&!covered){
            for(j=0;j<selected.length;j++)if(parent===selected[j]){covered=true;break;}
            parent=parent.parent;
        }
        if(!covered)roots.push(selected[i]);
    }
    if(roots.length>800)throw Error('Select no more than 800 complete artwork objects at once.');
    return roots;
};
EZPilot.fitProductionArtboard = function(production,bleedMm) {
    var bounds=[1e20,-1e20,-1e20,1e20],i,j,b;
    function include(rect){
        if(!rect||rect.length!==4)throw Error('The selected artwork has invalid bounds.');
        for(j=0;j<4;j++)if(!isFinite(Number(rect[j])))throw Error('The selected artwork has invalid bounds.');
        bounds[0]=Math.min(bounds[0],rect[0]);bounds[1]=Math.max(bounds[1],rect[1]);
        bounds[2]=Math.max(bounds[2],rect[2]);bounds[3]=Math.min(bounds[3],rect[3]);
    }
    for(i=0;i<production.pageItems.length;i++){
        b=production.pageItems[i];include(b.visibleBounds);include(b.geometricBounds);
    }
    if(bounds[2]<=bounds[0]||bounds[1]<=bounds[3])throw Error('The selected artwork has no printable size.');
    var pad=(2+(bleedMm||0))*72/25.4;
    production.artboards[0].artboardRect=[bounds[0]-pad,bounds[1]+pad,bounds[2]+pad,bounds[3]-pad];
    return production.artboards[0].artboardRect;
};
EZPilot.prepareSelection = function(source,selected,bleedMm) {
    var items=EZPilot.selectionRoots(selected),production=null,cutCount=0,i,j;
    function collect(node,result){
        if(node.typename==='PluginItem'||node.typename==='NonNativeItem')throw Error('Expand plug-in artwork before preparing.');
        if(node.typename==='PathItem'){result.push(node);return;}
        var list=node.typename==='GroupItem'?node.pageItems:node.typename==='CompoundPathItem'?node.pathItems:null,k;
        if(list)for(k=0;k<list.length;k++)if(list[k].parent===node)collect(list[k],result);
    }
    try{
        production=app.documents.add(source.documentColorSpace,1000,1000);
        var print=production.layers[0];print.name='print';
        var thru=production.layers.add();thru.name='thru-cut';
        var kiss=production.layers.add();kiss.name='kiss cut';
        function cutColor(name){
            var spot;try{spot=production.spots.getByName(name);}catch(ignore){spot=production.spots.add();spot.name=name;spot.colorType=ColorModel.SPOT;var color=new CMYKColor();color.cyan=name==='CutContour_Thru-cut'?100:0;color.magenta=name==='CutContour_Kiss-cut'?100:0;color.yellow=0;color.black=0;spot.color=color;}
            var result=new SpotColor();result.spot=spot;result.tint=100;return result;
        }
        var colors={thru:cutColor('CutContour_Thru-cut'),kiss:cutColor('CutContour_Kiss-cut')};
        for(i=0;i<items.length;i++){
            var original=[],types=[],copied=[];collect(items[i],original);
            for(j=0;j<original.length;j++)types.push(EZPilot.cutType(original[j]));
            var duplicate=items[i].duplicate(print,ElementPlacement.PLACEATEND);collect(duplicate,copied);
            if(original.length!==copied.length)throw Error('The copied artwork structure changed.');
            var before=items[i].geometricBounds,after=duplicate.geometricBounds;
            duplicate.translate(before[0]-after[0],before[1]-after[1]);
            for(j=0;j<copied.length;j++)if(types[j]){
                var path=copied[j];
                if(path.clipping||path.filled||!path.stroked||path.parent.typename==='CompoundPathItem')throw Error('A cut must be a separate unfilled stroke. Artwork clipping masks are kept automatically.');
                before=path.geometricBounds;
                path.strokeColor=colors[types[j]];
                path.move(types[j]==='thru'?thru:kiss,ElementPlacement.PLACEATEND);
                after=path.geometricBounds;
                if(Math.abs((before[2]-before[0])-(after[2]-after[0]))>.001||Math.abs((before[1]-before[3])-(after[1]-after[3]))>.001)throw Error('Moving a cut changed its dimensions. The source was left unchanged.');
                path.translate(before[0]-after[0],before[1]-after[1]);
                cutCount++;
            }
        }
        if(!cutCount)throw Error('No cut paths found. Use thru-cut / kiss cut layers or named cut spots.');
        EZPilot.fitProductionArtboard(production,bleedMm);
        return {document:production,cutCount:cutCount,selectionCount:items.length};
    }catch(error){
        if(production){try{production.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}
        source.activate();throw error;
    }
};
EZPilot.asciiJSON = function(value) {
    return EZPilot.stringify(value).replace(/[^\x00-\x7f]/g,function(c){return '\\u'+('0000'+c.charCodeAt(0).toString(16)).slice(-4);});
};
EZPilot.http = function(method,path,data,token) {
    var socket=new Socket(),body=data?EZPilot.asciiJSON(data):'',reply='',chunk,split,head,match,start=new Date().getTime();
    socket.timeout=5;
    if(!socket.open('127.0.0.1:8765','BINARY'))throw Error('Start the pilot eznest app on this PC (port 8765) first.');
    try{
        var request=method+' '+path+' HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: '+body.length+'\r\n';
        if(token)request+='X-EZ-Token: '+token+'\r\n';
        if(!socket.write(request+'\r\n'+body))throw Error('Could not send the production copy.');
        while(!socket.eof){
            chunk=socket.read(4096);reply+=chunk;
            if(reply.length>100000||new Date().getTime()-start>30000)throw Error('Local handoff timed out.');
            if(!chunk&&!socket.connected)break;
        }
    }finally{socket.close();}
    split=reply.indexOf('\r\n\r\n');if(split<0)throw Error('The local app did not answer.');
    head=reply.substring(0,split);match=/^HTTP\/1\.[01] (\d+)/.exec(head);
    var result=EZPilot.parse(reply.substring(split+4));
    if(!match||Number(match[1])!==200)throw Error(result.error||'Local handoff failed.');
    return result;
};
EZPilot.stringify = function(v){
    if(v===null)return 'null';
    if(typeof v==='string')return '"'+v.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';
    if(typeof v==='number')return isFinite(v)?String(v):'null';
    if(typeof v==='boolean')return v?'true':'false';
    var a=[],i,k;if(v instanceof Array){for(i=0;i<v.length;i++)a.push(EZPilot.stringify(v[i]));return '['+a.join(',')+']';}
    for(k in v)if(v.hasOwnProperty(k))a.push(EZPilot.stringify(k)+':'+EZPilot.stringify(v[k]));return '{'+a.join(',')+'}';
};
EZPilot.parse = function(text){
    var i=0;
    function ws(){while(i<text.length&&/\s/.test(text.charAt(i)))i++;}
    function str(){var out='',c,h;i++;while(i<text.length){c=text.charAt(i++);if(c==='"')return out;if(c==='\\'){c=text.charAt(i++);if(c==='u'){h=text.substr(i,4);if(!/^[0-9a-fA-F]{4}$/.test(h))throw Error('Invalid JSON escape');out+=String.fromCharCode(parseInt(h,16));i+=4;}else{var m={'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'};if(!m.hasOwnProperty(c))throw Error('Invalid JSON string');out+=m[c];}}else{if(c.charCodeAt(0)<32)throw Error('Invalid JSON character');out+=c;}}throw Error('Unclosed JSON string');}
    function value(){ws();var c=text.charAt(i),a,k,v,m;if(c==='"')return str();if(c==='['){i++;a=[];ws();if(text.charAt(i)===']'){i++;return a;}while(true){a.push(value());ws();c=text.charAt(i++);if(c===']')return a;if(c!==',')throw Error('Invalid JSON array');}}
        if(c==='{'){i++;a={};ws();if(text.charAt(i)==='}'){i++;return a;}while(true){ws();if(text.charAt(i)!=='"')throw Error('Invalid JSON key');k=str();if(k==='__proto__'||k==='constructor'||k==='prototype')throw Error('Invalid key');ws();if(text.charAt(i++)!==':')throw Error('Invalid JSON object');a[k]=value();ws();c=text.charAt(i++);if(c==='}')return a;if(c!==',')throw Error('Invalid JSON object');}}
        var rest=text.substring(i);if(rest.substr(0,4)==='true'){i+=4;return true;}if(rest.substr(0,5)==='false'){i+=5;return false;}if(rest.substr(0,4)==='null'){i+=4;return null;}m=rest.match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);if(m){i+=m[0].length;v=Number(m[0]);if(!isFinite(v))throw Error('Invalid number');return v;}throw Error('Invalid JSON value');}
    var result=value();ws();if(i!==text.length)throw Error('Trailing JSON content');return result;
};
