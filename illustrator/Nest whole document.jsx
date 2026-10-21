#target illustrator
// Prepare the visible, unlocked artwork without changing the source selection.
$.global.EZNestWholeDocument=true;
try {
    $.evalFile(new File(File($.fileName).parent.fsName+'/Prepare for EZ Nest.jsx'));
} finally {
    $.global.EZNestWholeDocument=false;
}
