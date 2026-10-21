"""Package an already-built portable app for a separate, reversible shop trial."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
from build_windows import ROOT, git_commit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--build-id',required=True)
    args=parser.parse_args();app=args.app.resolve();out=args.out.resolve()
    if out.exists():raise ValueError('Choose a new output folder; no previous trial is replaced.')
    if not (app/'eznest.exe').is_file():raise ValueError('Build the portable app first.')
    out.mkdir(parents=True);(out/'app').mkdir()
    shutil.copy2(app/'eznest.exe',out/'app/eznest.exe')
    shutil.copytree(app/'_internal',out/'app/_internal')
    for name in ['LICENSE','NOTICE','THIRD_PARTY.md']:
        shutil.copy2(app/name,out/name)
    shutil.copytree(app/'licenses',out/'licenses')
    shutil.copytree(app/'illustrator',out/'Illustrator')
    shutil.copytree(app/'examples',out/'Examples')
    shutil.copy2(app/'BUILD.json',out/'DEPENDENCIES.json')
    def cmd(name,text):
        (out/name).write_bytes(('@echo off\r\nsetlocal\r\n'+text.replace('\n','\r\n')+'\r\n').encode('utf-8'))
    cmd('START Shop Test.cmd','start "" "%~dp0app\\eznest.exe" --shop-test')
    cmd('OPEN Test Output.cmd','if not exist "%LOCALAPPDATA%\\eznest-shop-trial\\TEST Output" (\necho Start Shop Test once first.\npause\nexit /b 1\n)\nstart "" "%LOCALAPPDATA%\\eznest-shop-trial\\TEST Output"')
    stop="""$ErrorActionPreference='Stop'; try { $listeners=@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue); if($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1'){throw 'The trial is not the only local listener. Nothing was stopped.'}; $owned=Get-CimInstance Win32_Process -Filter ('ProcessId='+$listeners[0].OwningProcess); if($owned.ExecutablePath -ne $env:EZNEST_TRIAL_EXE -or $owned.CommandLine -notmatch ' --shop-test(?: |$)'){throw 'Another build is running. Use its own stop command. Nothing was stopped.'}; $url='http://127.0.0.1:8765'; $session=Invoke-RestMethod ($url+'/api/session'); if($session.app -ne 'eznest' -or $session.pid -ne $owned.ProcessId){throw 'The running process changed. Nothing was stopped.'}; $state=Invoke-RestMethod ($url+'/api/state'); if($state.status -eq 'running'){throw 'Finish nesting or use Stop - keep best first.'}; Invoke-RestMethod ($url+'/api/shutdown') -Method Post -ContentType 'application/json' -Headers @{'X-EZ-Token'=$session.token} -Body '{}' | Out-Null; Write-Host 'Shop trial stopped. Saved jobs and output are retained.' } catch { Write-Host $_.Exception.Message; exit 1 }"""
    cmd('STOP Shop Test.cmd','set "EZNEST_TRIAL_EXE=%~dp0app\\eznest.exe"\npowershell.exe -NoProfile -Command "'+stop+'"\nif errorlevel 1 pause')
    text='''EZ NEST - SHOP TRIAL
BUILD: {build}

FIRST TIME
1. Extract this whole ZIP to a new local folder on the Illustrator PC.
2. Double-click START Shop Test.cmd. No Python or installer is needed.
3. In Illustrator: File > Scripts > Other Script > Illustrator/Prepare and Nest.jsx.
   Keep the Illustrator folder's files together. For a permanent menu entry,
   copy them to Illustrator's Presets/<language>/Scripts folder and restart Illustrator.
4. Choose your approved PDF preset, printable width and existing bleed once.
   EZ Nest Settings.jsx changes these later. No preset is selected for you.

DAILY FLOW
Finish colors/bleed, save your design and select the complete parts and their cuts.
Prepare and Nest > review material, sets, artwork and cuts > Review and send.
Prepared PDFs can also be dropped directly into the app.
Existing jobs are retained; finish the current job before loading another.

WHERE THE FILE GOES
OPEN Test Output.cmd opens the local TEST Output folder.
The app does not send this trial to the live ONYX folder automatically.
For the first physical test, open artwork.pdf from one approved output pack in
ONYX manually, using your normal media/print settings. Check size, colors, bleed,
cut spots and RIP-generated registration marks before printing a small sample.
Measure a known part and check the cut registration before running a whole kit.
Record the outcome in TEST RESULTS.txt. A successful folder send is not printing.

WHAT THIS BUILD DOES
Copies selected Illustrator artwork, separates named cut strokes, exports using
your saved PDF preset, nests and lets you approve the output. Original designs
are not saved or deleted by the script. This is a local, unsigned trial build.
Recognized cuts: thru-cut / kiss cut layers or CutContour_Thru-cut /
CutContour_Kiss-cut spots. Ambiguous, clipped or unsupported cuts need review.

NOT INCLUDED YET
Automatic recoloring, new bleed generation, clipping repair, editable-nest return
to Illustrator, and persistent remaining-order counts. Finish colors and bleed
in Illustrator first. PDF imports are limited to 32 MB. Test outputs do not
certify ink, media, bleed or cutter performance.

KEEP THE CURRENT SHOP SETUP
Run this on the separate Illustrator/test PC. If port 8765 is occupied by a
different build, this trial refuses to attach or replace it. Do not stop rc.4
on the shop PC to make room. No accounts, startup tasks or firewall rules change.
Local data and test output: %LOCALAPPDATA%/eznest-shop-trial
The source version label remains unchanged; BUILD.json identifies this trial.

UPDATES / GO BACK
Automatic updates are disabled for this trial. Finish the current run, then use
STOP Shop Test.cmd from the running build's folder. Extract the next tested ZIP
into a NEW folder and run its START command. Keep this folder as your fallback.
The same separate trial data/output folder is reused. Before an update, copy
that folder to a dated backup while the app is stopped. To go back, stop the new
build and launch the previous one; retain the backup if data formats change.
Never copy trial files over the protected shop installation or delete originals.
'''.format(build=args.build_id)
    (out/'READ FIRST.txt').write_text(text,encoding='utf-8')
    (out/'TEST RESULTS.txt').write_text('Build: '+args.build_id+'\nDate / operator:\nSource copy:\nPDF preset:\nMaterial / print mode:\nPrintable width / existing bleed:\nExpected pieces / cuts:\nPreview and artwork comparison:\nMeasured size:\nPrinted colors / bleed:\nCut registration:\nAccepted or blocked:\nProblem to fix next:\n',encoding='utf-8')
    paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths)) if (ROOT/p).is_file()}
    fingerprint=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    manifest={'buildId':args.build_id,'version':json.loads((ROOT/'version.json').read_text())['version'],
              'baseCommit':git_commit(),'localChangesIncluded':True,'sourceFingerprint':fingerprint,
              'exeSha256':hashlib.sha256((out/'app/eznest.exe').read_bytes()).hexdigest(),
              'signed':False,'channel':'local-shop-trial','automaticUpdates':False}
    (out/'BUILD.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (out/'SOURCE-FINGERPRINT.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    files={str(p.relative_to(out)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    (out/'FILES.sha256.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for p in out.rglob('*'):
            if p.is_file():z.write(p,str(Path(out.name)/p.relative_to(out)))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n')
    print(json.dumps({'folder':str(out),'zip':str(archive),'sha256':digest,'files':len(files),'bytes':archive.stat().st_size}))


if __name__=='__main__':main()
