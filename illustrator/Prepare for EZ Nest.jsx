#target illustrator
/* Pilot: preserves the source, separates approved cut strokes, exports a PDF copy. */
$.evalFile(new File(File($.fileName).parent.fsName+'/bridge-core.js'));
(function(){
    var production=null,exported=false,i;
    try{
        var presetNames=[];for(i=0;i<app.PDFPresetsList.length;i++)presetNames.push(String(app.PDFPresetsList[i]));
        var preferencesFile=new File(Folder.userData.fsName+'/eznest/illustrator-settings.json');
        var settings=EZPilot.readPreferences(preferencesFile,presetNames);
        var settingsOnly=$.global.EZNestSettingsOnly===true;
        if(!settings||settingsOnly){
            var dialog=new Window('dialog','Nest in eznest - setup');
            dialog.orientation='column';dialog.alignChildren='fill';
            dialog.add('statictext',undefined,'Saved for this Windows user. Change later with EZ Nest Settings.jsx.');
            dialog.add('statictext',undefined,'Material');
            var material=dialog.add('dropdownlist',undefined,['Regular']);material.selection=0;
            dialog.add('statictext',undefined,'Chrome and Holographic need approved shop rules.');
            function field(label,value){var row=dialog.add('group');row.add('statictext',undefined,label);var input=row.add('edittext',undefined,value);input.characters=12;return input;}
            var width=field('Printable width (inches)',String(settings?settings.widthIn:51.5));
            var bleed=field('Existing bleed (mm)',String(settings?settings.bleedMm:0));
            dialog.add('statictext',undefined,'Choose your approved ONYX Adobe PDF preset:');
            var presets=dialog.add('dropdownlist',undefined,presetNames);
            for(i=0;settings&&i<presetNames.length;i++)if(presetNames[i]===settings.pdfPreset)presets.selection=i;
            dialog.add('statictext',undefined,'Before each Nest action: finish colors and existing bleed, save, and select complete parts.',{multiline:true});
            dialog.add('statictext',undefined,'No automatic recoloring or bleed generation. Review cuts and artwork before Send.',{multiline:true});
            var buttons=dialog.add('group');buttons.add('button',undefined,'Cancel',{name:'cancel'});
            var submit=buttons.add('button',undefined,settingsOnly?'Save settings':'Save and nest',{name:'ok'});
            submit.onClick=function(){
                var candidate={version:1,pdfPreset:presets.selection?presets.selection.text:'',material:'regular',widthIn:Number(width.text),bleedMm:Number(bleed.text)};
                if(!EZPilot.validPreferences(candidate,presetNames)){alert('Choose an available PDF preset and check printable width and existing bleed.');return;}
                try{EZPilot.writePreferences(preferencesFile,candidate);}catch(error){alert(String(error.message||error));return;}
                settings=candidate;dialog.close(1);
            };
            if(dialog.show()!==1)return;
        }
        if(settingsOnly)return;
        if(!app.documents.length)throw Error('Open a saved kit and select its production artwork and cut paths.');
        var source=app.activeDocument,selected=source.selection;
        if(!source.saved)throw Error('Save your design first so this export has a stable source reference.');
        var items=$.global.EZNestWholeDocument===true?EZPilot.documentRoots(source):EZPilot.selectionRoots(selected);
        var session=EZPilot.http('GET','/api/session');
        if(session.app!=='eznest')throw Error('Port 8765 is not running eznest.');
        var sourceKey=source.fullName.fsName;
        production=EZPilot.prepareSelection(source,items,settings.bleedMm).document;
        var folder=new Folder(Folder.temp.fsName+'/eznest-illustrator');
        if(!folder.exists&&!folder.create())throw Error('Cannot create the temporary export folder.');
        var requestId='',hex='0123456789abcdef';for(i=0;i<32;i++)requestId+=hex.charAt(Math.floor(Math.random()*16));
        var file=new File(folder.fsName+'/'+requestId+'.pdf'),options=new PDFSaveOptions();
        options.pDFPreset=settings.pdfPreset;
        options.preserveEditability=false;
        production.saveAs(file,options);
        exported=true;
        if(file.length>256000000)throw Error('The PDF is over 256 MB. Export a smaller selection.');
        file.encoding='BINARY';if(!file.open('r'))throw Error('Cannot read the production PDF.');
        var bytes=file.read();file.close();
        var reply=EZPilot.http('POST','/api/illustrator/intake',{requestId:requestId,sourceKey:sourceKey,content:EZPilot.base64(bytes),material:settings.material,widthIn:settings.widthIn,sets:1,bleedMm:settings.bleedMm},session.token);
        var url='http://127.0.0.1:8765/web?illustrator='+requestId;
        var link=new File(folder.fsName+'/'+requestId+'.html');link.encoding='UTF-8';
        if(!link.open('w'))throw Error('Production copy saved, but the browser link could not be created. Open '+url);
        link.write('<!doctype html><meta http-equiv="refresh" content="0;url='+url+'"><a href="'+url+'">Open eznest</a>');link.close();
        source.activate();
        if(!link.execute())throw Error('Production copy saved. Open '+url);
    }catch(error){
        if(production&&!exported){try{production.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}
        // Leave an exported production copy open for inspection; never save the source.
        alert('EZ Nest: '+String(error.message||error));
    }
}());
