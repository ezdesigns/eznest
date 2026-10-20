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
    while(parent){if(parent.typename==='Layer'){layer=parent.name.toLowerCase();break;}parent=parent.parent;}
    var byLayer=layer==='thru-cut'?'thru':layer==='kiss cut'?'kiss':'';
    var bySpot=/^CutContour_Thru-cut$/.test(name)?'thru':/^CutContour_Kiss-cut$/.test(name)?'kiss':'';
    if(byLayer&&bySpot&&byLayer!==bySpot)throw Error('A cut layer and its spot color disagree.');
    if(name==='CutContour'&&!byLayer)throw Error('Put generic CutContour strokes on thru-cut or kiss cut before preparing.');
    if(/^CutContour/.test(name)&&!byLayer&&!bySpot)throw Error('Unrecognized cut spot: '+name);
    return byLayer||bySpot;
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
