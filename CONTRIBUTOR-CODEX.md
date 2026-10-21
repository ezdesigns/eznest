# Test an idea and send a PR

Use this source workflow when you want to try EZ Nest, change something with
Codex, and propose it to the owner. The portable tester ZIP remains useful for
people who only want to try a fixed build.

The repo is private. The owner must give your GitHub account access first.
Sign in through your normal GitHub tool; never paste a token into a prompt.
Each person uses their own GitHub and Codex accounts. Never share the owner's
login. Before invitations, the owner should verify branch rules that require
review and passing checks on the integration and protected shop branches.
These written instructions do not enforce GitHub permissions.
Use a separate Windows x64 design/test PC. Leave the shop PC and protected rc.4
installation untouched. Read GOALS.md, AGENTS.md and CONTRIBUTING.md.

## The current contribution target

Until the owner explicitly changes it, start from and submit contributor PRs to
`cursor/shop-open-handoff-9891` in `ezdesigns/eznest`. Create a new branch for each
idea. PR #4 is the owner's integration PR; its protected base branch is not the
target for contributor PRs. Verify the current upstream head before starting.
Do not push directly to the integration branch, main, or the protected shop branch.

This private repo is currently owned by a personal account, so collaborators
receive write access. Push only your new contributor branch. If the repo later
moves to an organization with different permissions, verify the allowed PR
route first. If you cannot push or fork, preserve your local changes and ask the
owner for access. Do not make the repo public or change permissions yourself.

## Paste into a local Codex chat to get started

> Set up ezdesigns/eznest for contributor testing on this Windows design PC.
> Use the integration branch cursor/shop-open-handoff-9891. Read GOALS.md,
> AGENTS.md, CONTRIBUTING.md and CONTRIBUTOR-CODEX.md from that branch first.
> Verify repository access and the current remote head. Clone into a new local
> folder if necessary; preserve any existing checkout and uncommitted work.
> Create a separate contributor branch with a descriptive name. Set up the
> isolated environment using contributor.py setup, then start with
> contributor.py start. Use the available Python 3.12 x64 interpreter; ask only
> for missing prerequisites, authentication or required OS/tool approvals.
> Check the app is loopback-only, uses this checkout's separate marked data,
> and sends only to its TEST Output. Do not stop an existing app to free the
> port; explain a conflict first. Do not replace the shop installation.
> Run the supplied sample at one set and verify four pieces and saved test
> output. Preserve existing work. Then help me test a copy of a file I choose.
> Keep originals unchanged and customer artwork out of Git, chats and reports.
> Guide Illustrator steps you cannot perform. Do not invent production settings.
> Write a short local report with the tested commit, checks, errors and unknowns.
> Do not change app behavior or submit a PR until I describe an improvement.

## Source commands Codex can use

Use Python 3.12 x64. `py -3.12` below may be replaced with the verified full path
to that interpreter. Git is needed for contributions. Node 24, PowerShell 7 and
Chrome or Edge are needed for the full checks, not merely to launch the app.

```powershell
py -3.12 contributor.py setup
py -3.12 contributor.py info
py -3.12 contributor.py start
```

The environment lives under ignored `.local/contributor-venvs/`, keyed to the
requirements file. A changed requirements file gets a separate environment.
Data and TEST Output live under `%LOCALAPPDATA%/eznest-contributors/<checkout-id>/`.
The checkout ID stays the same across code updates in that folder. Another
checkout gets different data. Setup does not install a service or alter the
portable tester installation. The source process runs in the launching terminal;
use Ctrl+C there to stop it. Codex must track its own process when launching it
in the background and verify identity before stopping it.

Port 8765 is needed for Illustrator. Browser-only testing can use an explicitly
chosen free port, for example `contributor.py start --port 18765`; that does not
make the Illustrator bridge work at that port. Never pass `--lan` for this trial.

## When you have an idea, paste this

> I want to improve EZ Nest: [describe what you want to work differently].
> Reproduce the current behavior and explain the proposed result briefly. Read
> the repository instructions and keep the change focused on this idea. Work on
> a new contributor branch based on the current integration branch
> cursor/shop-open-handoff-9891; preserve unrelated edits and existing test data.
> Implement it, test it with synthetic examples, and let me try it locally.
> Run the relevant regressions and required repository checks. For UI changes,
> inspect desktop/mobile screenshots using non-customer artwork. State missing
> tests honestly. Never weaken cut, scale, review, isolation or update safeguards
> just to make a test pass. Do not change version.json or production deployments.
> Review the complete diff for unrelated changes, credentials, local data and
> customer artwork. Commit only this change, push my contributor branch, and
> open a draft PR to ezdesigns/eznest:cursor/shop-open-handoff-9891. This request
> authorizes that branch push and PR. Describe the problem, resulting behavior,
> validation and remaining limits; include only non-sensitive screenshots.
> If I lack push/fork access, preserve the work and tell me the exact blocker.
> Do not merge, publish a release, invite reviewers or send messages for me.

Codex should use an explicit PR base, not GitHub's default `main`. Check for an
existing PR from the branch before creating another. Never force-push someone
else's work. Failed or incomplete validation belongs in a draft PR, not a claim
that the change is ready for production.

```powershell
py -3.12 contributor.py setup --test-tools
py -3.12 contributor.py check
```

The check command runs the Python, Node and mocked PowerShell suites used here.
It never runs the real installer test on your computer. Use synthetic fixtures;
keep screenshots/reports under `.local/`. Checks do not certify physical output.

## Keeping contributors up to date

A commit does not update another computer automatically. Fetch the integration
branch, inspect its changes, and update a clean checkout with a fast-forward.
On a feature branch, merge the integration branch and resolve conflicts without
discarding local work. Stop your own source process and back up its data first;
rerun setup if requirements changed, then restart and check settings and output.
Do not clear browser storage; material presets live in the same browser/origin.

The owner reviews contributor PRs before merging them into this integration
branch. The owner then tests and distributes an approved build. Contributors'
experiments never automatically replace everyone else's app. Releases and the
protected shop installation retain their separate approval/acceptance gates.
