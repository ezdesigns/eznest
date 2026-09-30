#target illustrator
#targetengine "eznest"
$.evalFile(new File(File($.fileName).parent.fsName+'/jsx/host.jsx'));
var captureReply=EZN.parse(EZNCapture());
alert(captureReply.ok?'Captured '+captureReply.count+' closed paths. In EZ Nest choose Load Illustrator capture.':captureReply.error);
