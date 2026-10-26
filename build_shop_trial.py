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
Installer: open the EZ Nest Tester desktop shortcut after installing.
Portable ZIP: extract the whole ZIP to a new local folder, then double-click
START Shop Test.cmd. Neither option needs Python or a developer setup.
Use a separate test PC. Keep the protected shop installation running as it is.

TRY IT IN FIVE MINUTES
1. Click Add file and choose Examples/sample-artwork.svg from this trial folder.
   It contains four sample designs, with no customer information.
2. Choose a material, check printable width, and enter copies. The layout starts
   automatically. Layout settings lets you choose Quick, Balanced or Best fit.
3. Check pieces and the large preview. Read Material used and Unused space.
4. Click Review and save, then My computer to choose a local test folder in the
   normal Save As window. Saving a file does not send it to a printer.
5. Use Send feedback. The version is included; result numbers are optional and
   unchecked. Review the report, then save it or continue to a GitHub issue draft.
   Never include customer artwork, names or paths in shared feedback.

DAILY FLOW
Finish colors, bleed and cut lines in Illustrator. Save a prepared print PDF.
Add file > choose material and copies > check the layout > Review and save.
The app keeps existing artwork and bleed; do not enter or add a new bleed amount.
It nests around the protected artwork, not just the cut lines. It does not yet
create missing cuts. If separate stickers have no cuts, add their cut lines first.
Dashed cut lines pause import for review; exclude only lines you know are guides.
Existing jobs are retained. Use Next job after saving to begin another job.

USING ILLUSTRATOR DIRECTLY (OPTIONAL)
Select complete artwork and cut paths. Choose File > Scripts > Other Script >
Illustrator/Prepare and Nest.jsx. Keep that folder's files together. The script
asks for your existing approved PDF preset and preparation settings. It does not
choose color or bleed rules for you. Regular preparation is the supported pilot;
specialty roll presets in the browser only set nesting dimensions and spacing.

WHERE THE FILE GOES
Default folder saves into the local TEST Output folder until you change it in
Settings. OPEN Test Output.cmd opens that folder. My computer opens Save As on
the PC running the app; a remote browser uses its normal download instead.
The suggested filename matches the imported file. One-sheet PDFs save as PDF;
multiple sheets and SVG jobs save as a ZIP pack. Replacing a different existing
file requires confirmation and retains a local backup.
Keep all trial outputs outside live ONYX/hot folders. Physical print/cut checks
are a separate operator-controlled test after checking scale, colors, bleed and
cut paths. Record the results in TEST RESULTS.txt. A saved PDF is not proof of
printed color, actual scale or cutter registration.

UNDERSTANDING THE NUMBERS
Material used is roll length. Unused space includes blank areas, gaps and margins
inside the printable sheet; it is not ink waste. For meaningful savings, enter
the previous print length for the same pieces, copies, material and width under
Compare a previous layout. Try tighter fit can also compare with the first fit.
Enter full roll cost and length in Edit material for material-only dollar savings.
No previous layout or price means no claimed saving. Longer search is best-found,
not a guarantee of the shortest possible print. Stock remaining is entered manually.

WHAT THIS BUILD DOES
Imports prepared PDF, PDF-compatible AI and SVG, nests complete artwork and cuts,
and lets you review and save locally. Original designs are not saved or deleted
by importing or by the optional preparation script. This is an unsigned trial.
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

HELP FROM CODEX
CODEX TEST PROMPT.txt contains a prompt to set up and check this trial on a test
PC. Contributor code changes use a separate branch and draft PR; pushing code
does not update installed tester PCs.
'''.format(build=args.build_id)
    (out/'READ FIRST.txt').write_text(text,encoding='utf-8')
    (out/'CODEX TEST PROMPT.txt').write_text('''Paste this into Codex on the separate Windows test PC, and tell it the local
folder containing this verified EZ Nest Tester package/installer:

Help me install and test EZ Nest Tester build {build} on this separate Windows
PC. Read READ FIRST.txt and BUILD.json. Verify the supplied installer checksum,
or FILES.sha256.json for the portable folder. Use the normal per-user tester
installer or portable START Shop Test.cmd, not the shop-service installer.
Do not bypass Windows security warnings. If an EZ Nest app already uses port
8765, identify it and preserve its job; do not stop or replace a different shop
installation. Do not create accounts, tasks, firewall rules or network listeners.
Keep updates, LAN and OUTPUT off, and use only local TEST Output or another new
local test folder. Do not delete anything or change the protected shop rc.4.

Start with Examples/sample-artwork.svg: confirm all four designs import, nest,
save and restore after a browser refresh and app restart. Check the suggested
filename and My computer Save As. Then help me test a local COPY of a prepared
print file with its existing bleed and cuts. Ask only for missing material/cut
choices. Never invent cuts, change scale, recolor or trim customer artwork.
If the computer tools cannot perform a step, explain the exact step for me.
Do not run hosted-runner install/uninstall acceptance scripts on this PC.

Record the exact build and Windows version, expected/detected piece and cut
counts, sheet length, material used, unused space and elapsed time locally.
Use Send feedback with result numbers unchecked unless I choose to include them.
Never attach or upload customer files, artwork, names or paths. Distinguish
software checks from physical printer/cutter acceptance; do not send to a RIP.

If I request a code improvement, read GOALS.md, AGENTS.md and
CONTRIBUTOR-CODEX.md in ezdesigns/eznest first. Work from
cursor/shop-open-handoff-9891 on a separate contributor branch and open a draft
PR back to that branch. Do not push directly to integration, merge, release,
publish or change repository visibility. Installed testers update manually.
'''.format(build=args.build_id),encoding='utf-8')
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
