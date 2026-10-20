#target illustrator
(function(){
    $.global.EZNestSettingsOnly=true;
    try{$.evalFile(new File(File($.fileName).parent.fsName+'/Prepare for EZ Nest.jsx'));}
    finally{$.global.EZNestSettingsOnly=false;}
}());
