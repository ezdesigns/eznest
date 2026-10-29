# Put eznest on GitHub

There are two handoffs: the **source repository** for development, and the **Windows ZIP under Releases** for people running the app. Publishing a repository does not deploy this local Python app as a website; GitHub Pages is not the runtime for eznest.

## 1. Extract the source package

Download `eznest-github-ready.zip`, right-click it in Windows, and choose **Extract All**. Open the resulting `eznest` folder. It contains `README.md`, `launcher.py`, `tests`, `licenses` and `.github`. Do not put the unopened ZIP into the repository.

## 2. Create the local repository with GitHub Desktop

1. Install [GitHub Desktop](https://desktop.github.com/) and sign in to your GitHub account.
2. Choose **File → New repository** (or **Create a New Repository on your Hard Drive**).
3. Set **Name** to `eznest`. Description: `Simple local nesting for print shops — SVG beta`.
4. Choose a local parent folder, for example `Documents/GitHub`. Desktop creates `Documents/GitHub/eznest` inside it.
5. Leave **Initialize with a README** unchecked. Set **Git ignore** and **License** to **None**; the repository already contains the ignore rules and the Apache-2.0 LICENSE.
6. Click **Create repository**. If `eznest` already exists on your GitHub account, clone that repository instead and add these files on a new branch; do not replace existing work blindly.

These controls are described in [GitHub's Desktop guide](https://docs.github.com/en/desktop/overview/creating-your-first-repository-using-github-desktop).

## 3. Copy the source files into that repository

1. In Desktop, choose **Repository → Show in Explorer**.
2. In a separate Explorer window, open the extracted `eznest` folder from step 1. Select **its contents**, copy them, and paste them into the new repository folder. Do not copy the outer folder itself: the correct result is `eznest/README.md`, not `eznest/eznest/README.md`.
3. Include `.github`, `.gitignore`, `.gitattributes` and `.editorconfig`. Windows Explorer's **View → Show → Hidden items** can help if they are hidden.
4. Return to Desktop. Review the Changes list. The list should contain application code, synthetic tests and third-party notices; no customer art or local queue should be there.
5. In **Summary**, type `Initial eznest SVG beta`. Click **Commit to main** (or the current default branch name shown).

GitHub's browser uploader accepts up to 100 files at once. This project has more because its dependency notices are included, so Desktop avoids splitting the initial upload into batches. See [GitHub's upload limits](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).

## 4. Publish your code

Click **Publish repository**. Keep the name `eznest`. Ez Nest is Apache-2.0 and is meant to be a public repository. Do not publish customer files, tokens, or a shop data folder. Select your account or intended organization, then click **Publish repository**. That uploads the committed source. Use **Repository → View on GitHub** to open it. [GitHub publishing instructions](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop).

On the Code tab, confirm `README.md`, `launcher.py`, `tests/` and `.github/workflows/test.yml` are at the top level. On **Actions**, look for the **Tests** workflow and its result. Local checks have passed; the GitHub-hosted check has not run until you upload. If Actions is disabled by your account or organization, the files remain uploaded but automatic checks will not run.

For later changes: edit files in this same repository folder, review Changes in Desktop, enter a Summary, **Commit**, then **Push origin**. Commit saves locally; Push uploads that commit.

## 5. Add the runnable Windows download

1. On GitHub, open your repository's **Releases** page and choose **Draft a new release** or **Create a new release**.
2. Create tag `v0.11.0-beta.1`, targeting the branch containing the uploaded source.
3. Title: `eznest 0.11.0-beta.1 — Windows production-file beta`.
4. Copy the content of `RELEASE-NOTES.md` into the description.
5. Attach `eznest-0.11.0-beta.1-windows-x64.zip` and `eznest-0.11.0-beta.1-SHA256.txt` as release assets. Keep the Windows ZIP intact; do not extract it into the source repository.
6. Check **This is a pre-release**. Click **Publish release**, or **Save draft** if you want to review it first.

GitHub documents this flow in [Managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository). In a private repo, recipients need repository access to get the release. To offer a download to everyone, make a deliberate public-release/source-visibility decision first.

## What is ready versus still pending

Ready: the clean source ZIP, current Windows ZIP, checksum file, README, test workflow and these instructions. No GitHub repository, commit, remote or release was created for you in this handoff.

Still pending: choose the GitHub owner, upload the repository, inspect its first Actions result, and publish the pre-release. This remains an SVG beta; uploading it does not add native AI/PDF, CMYK, bleed or production CutContour output.
