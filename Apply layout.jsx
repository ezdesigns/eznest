#target illustrator
#targetengine "eznest"
$.evalFile(new File(File($.fileName).parent.fsName+'/jsx/host.jsx'));
var applyReply=EZN.parse(EZNApply());
alert(applyReply.ok?'Created a separate document with '+applyReply.count+' production copies. Review dimensions before printing.':applyReply.error);
