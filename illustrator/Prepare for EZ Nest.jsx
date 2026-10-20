#target illustrator
/* Pilot: preserves the source, separates approved cut strokes, exports a PDF copy. */
$.evalFile(new File(File($.fileName).parent.fsName+'/bridge-core.js'));
(function(){
    var production=null,exported=false;
    try{
        if(!app.documents.length)throw Error('Open a saved kit and select its production artwork and cut paths.');
        var source=app.activeDocument,selected=source.selection,items=[],i;
        if(!source.saved)throw Error('Save your design first so this export has a stable source reference.');
        if(!selected||!selected.length||selected.length>100)throw Error('Select 1-100 complete parts, including artwork and their cut paths.');
        for(i=0;i<selected.length;i++){
            if(selected[i].typename==='TextRange'||selected[i].locked||selected[i].hidden)throw Error('Select complete, unlocked artwork objects.');
            items.push(selected[i]);
        }
        var session=EZPilot.http('GET','/api/session');
        if(session.app!=='eznest')throw Error('Port 8765 is not running eznest.');
        var dialog=new Window('dialog','EZ Nest - Illustrator pilot');
        dialog.orientation='column';dialog.alignChildren='fill';
        dialog.add('statictext',undefined,'Regular material - prepare a separate production copy.');
        dialog.add('statictext',undefined,'Chrome and Holographic need shop presets before testing.');
        function field(label,value){var row=dialog.add('group');row.add('statictext',undefined,label);var input=row.add('edittext',undefined,value);input.characters=12;return input;}
        var width=field('Printable width (inches)','51.5'),sets=field('Kit quantity','1'),bleed=field('Existing bleed (mm)','0');
        dialog.add('statictext',undefined,'Choose the Adobe PDF preset you normally use for ONYX:');
        var presetNames=[];for(i=0;i<app.PDFPresetsList.length;i++)presetNames.push(String(app.PDFPresetsList[i]));
        var presets=dialog.add('dropdownlist',undefined,presetNames);
        var approved=dialog.add('checkbox',undefined,'Artwork colors and existing bleed are ready for production.');
        dialog.add('statictext',undefined,'Creates print / thru-cut / kiss cut layers. No automatic recoloring or bleed generation.',{multiline:true});
        var buttons=dialog.add('group');buttons.add('button',undefined,'Cancel',{name:'cancel'});
        var submit=buttons.add('button',undefined,'Prepare & open nest',{name:'ok'});
        submit.onClick=function(){
            if(!presets.selection||!approved.value){alert('Choose your PDF preset and confirm the artwork preparation.');return;}
            if(!(Number(width.text)>=1&&Number(width.text)<=196&&Number(sets.text)>=1&&Number(sets.text)<=100&&Number(sets.text)%1===0&&Number(bleed.text)>=0&&Number(bleed.text)<=25)){alert('Check width, whole kit quantity, and existing bleed.');return;}
            dialog.close(1);
        };
        if(dialog.show()!==1)return;
        var sourceKey=source.fullName.fsName;
        production=app.documents.add(source.documentColorSpace,1000,1000);
        var print=production.layers[0];print.name='print';
        var thru=production.layers.add();thru.name='thru-cut';
        var kiss=production.layers.add();kiss.name='kiss cut';
        var bounds=[1e20,-1e20,-1e20,1e20],cutCount=0;
        function cutColor(name){
            var spot;try{spot=production.spots.getByName(name);}catch(ignore){spot=production.spots.add();spot.name=name;spot.colorType=ColorModel.SPOT;var color=new CMYKColor();color.cyan=0;color.magenta=100;color.yellow=0;color.black=0;spot.color=color;}
            var result=new SpotColor();result.spot=spot;result.tint=100;return result;
        }
        var colors={thru:cutColor('CutContour_Thru-cut'),kiss:cutColor('CutContour_Kiss-cut')};
        function collect(node,result){
            if(node.typename==='PluginItem'||node.typename==='NonNativeItem')throw Error('Expand plug-in artwork before preparing.');
            if(node.typename==='PathItem'){result.push(node);return;}
            var list=node.typename==='GroupItem'?node.pageItems:node.typename==='CompoundPathItem'?node.pathItems:null,j;
            if(list)for(j=0;j<list.length;j++)if(list[j].parent===node)collect(list[j],result);
        }
        for(i=0;i<items.length;i++){
            var sourcePaths=[];collect(items[i],sourcePaths);
            var types=[],j;
            for(j=0;j<sourcePaths.length;j++)types.push(EZPilot.cutType(sourcePaths[j]));
            var duplicate=items[i].duplicate(print,ElementPlacement.PLACEATEND),copyPaths=[];collect(duplicate,copyPaths);
            if(sourcePaths.length!==copyPaths.length)throw Error('The copied artwork structure changed.');
            // Keep the exact source position; no scaling or flattening.
            var originalBounds=items[i].geometricBounds,copyBounds=duplicate.geometricBounds;
            duplicate.translate(originalBounds[0]-copyBounds[0],originalBounds[1]-copyBounds[1]);
            for(j=0;j<copyPaths.length;j++)if(types[j]){
                var path=copyPaths[j];
                if(path.clipping||path.filled||!path.stroked||path.parent.typename==='CompoundPathItem')throw Error('Cut paths must be separate stroked, unfilled paths; keep clipping masks separate.');
                path.strokeColor=colors[types[j]];
                path.move(types[j]==='thru'?thru:kiss,ElementPlacement.PLACEATEND);
                cutCount++;
            }
        }
        if(!cutCount)throw Error('No cut paths found. Use thru-cut / kiss cut layers or named CutContour_Thru-cut / CutContour_Kiss-cut spots.');
        for(i=0;i<production.pageItems.length;i++){
            var b=production.pageItems[i].visibleBounds;
            bounds[0]=Math.min(bounds[0],b[0]);bounds[1]=Math.max(bounds[1],b[1]);bounds[2]=Math.max(bounds[2],b[2]);bounds[3]=Math.min(bounds[3],b[3]);
        }
        var pad=2*72/25.4;
        production.artboards[0].artboardRect=[bounds[0]-pad,bounds[1]+pad,bounds[2]+pad,bounds[3]-pad];
        var folder=new Folder(Folder.temp.fsName+'/eznest-illustrator');
        if(!folder.exists&&!folder.create())throw Error('Cannot create the temporary export folder.');
        var requestId='',hex='0123456789abcdef';for(i=0;i<32;i++)requestId+=hex.charAt(Math.floor(Math.random()*16));
        var file=new File(folder.fsName+'/'+requestId+'.pdf'),options=new PDFSaveOptions();
        options.pDFPreset=presets.selection.text;
        options.preserveEditability=false;
        production.saveAs(file,options);
        exported=true;
        if(file.length>20000000)throw Error('The PDF is over 20 MB. Export a smaller selection.');
        file.encoding='BINARY';if(!file.open('r'))throw Error('Cannot read the production PDF.');
        var bytes=file.read();file.close();
        var reply=EZPilot.http('POST','/api/illustrator/intake',{requestId:requestId,sourceKey:sourceKey,content:EZPilot.base64(bytes),material:'regular',widthIn:Number(width.text),sets:Number(sets.text),bleedMm:Number(bleed.text)},session.token);
        var url='http://127.0.0.1:8765/web?illustrator='+requestId;
        var link=new File(folder.fsName+'/'+requestId+'.html');link.encoding='UTF-8';
        if(link.open('w')){link.write('<!doctype html><meta http-equiv="refresh" content="0;url='+url+'"><a href="'+url+'">Open EZ Nest</a>');link.close();link.execute();}
        alert('Production copy prepared with '+cutCount+' cut paths. Your source is unchanged.\nIn EZ Nest, click Load Illustrator selection, review all pieces, then Send.\n'+url);
    }catch(error){
        if(production&&!exported){try{production.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}
        // Leave an exported production copy open for inspection; never save the source.
        alert('EZ Nest: '+String(error.message||error));
    }
}());
