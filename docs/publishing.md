# Publish this alpha on GitHub

The source is prepared for a GitHub repository. These are maintainer commands;
MPSC2 does not automatically create a repository, push commits or publish a
package. The public repository is
[devindeng94/mpsc2](https://github.com/devindeng94/mpsc2).

## Validate the source

From the repository root:

```sh
python -m pip install -r requirements-dev.txt
python scripts/check_docs.py
python -m pytest -q
python -m build --outdir dist/github-release
python -m twine check dist/github-release/*
```

Use a fresh distribution directory so an earlier version is not uploaded by
accident. Check that `pyproject.toml` and `mpsc2.__version__` agree, and read the
[current known issues](known-issues.md) and [release notes](release-notes-0.3.1a2.md).
Live SC2 coverage is recorded separately; GitHub Actions runs offline checks only.

## Create the repository and first commit

Create an **empty** repository on GitHub. Do not initialize another README,
license or gitignore: this source already supplies them. Authenticate Git using
your normal GitHub setup. These steps follow
[GitHub's existing-code instructions](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

For a source ZIP extracted into a new folder, initialize Git first:

```sh
git init -b main
```

Skip that command in an existing Git checkout. Inspect and commit the prepared
files locally:

```sh
git status --short
git add .
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
git commit -m "Prepare MPSC2 0.3.1a2 public alpha"
```

The staged list should contain source, examples, documentation, tests, maps,
licenses, workflow/templates and compact evidence. The supplied `.gitignore`
excludes environments, local game reports, compiled helpers and the historical
raw evidence containing machine paths. It keeps the original evidence on disk.
Ignored files already tracked by an older repository remain tracked; review the
staged list instead of assuming ignore rules remove them.

For the project repository, set the remote and push:

```sh
git remote add origin https://github.com/devindeng94/mpsc2.git
git remote -v
git push -u origin HEAD:main
```

If `origin` already exists, inspect it rather than adding a duplicate or silently
changing it. For an existing nonempty remote, reconcile its history normally;
these instructions do not require a force push.

A prepared source ZIP must be **extracted** before following these steps. Uploading
the ZIP itself as the repository's only file would hide the README, source and CI.

## Repository presentation

Suggested About description:

> Team-based StarCraft II self-play with 2–8 independent API clients and python-sc2-compatible bots. Experimental macOS alpha.

Suggested topics: `starcraft2`, `multi-agent`, `self-play`, `reinforcement-learning`,
`python`, `python-sc2`.

GitHub discovers the MIT license, README, issue forms, pull-request template and
Actions workflow from the included files. After the first push, inspect Actions
results; configuration alone is not a passed CI run. Repository-specific CI
badges should reflect actual workflow results.

The `Repository`, `Issues` and `Documentation` entries under `[project.urls]`
in `pyproject.toml` point to this repository. Update them when publishing a fork,
and rebuild distributions after metadata changes.

## Create an alpha release

After reviewing the first CI result and local validation:

1. Tag the intended commit `v0.3.1a2` and push that tag.
2. Create a GitHub release for that tag and mark it **pre-release**.
3. Copy the [prepared release notes](release-notes-0.3.1a2.md).
4. Attach the wheel and source archive from `dist/github-release/`.
5. Keep the exact-build requirement and known limitations in the release text.

GitHub generates a source archive for the tag. Do not attach the SC2 installation,
raw memory dumps, local journals or large replays as package files. This workflow
does not publish to PyPI; package-name availability, account ownership and a
separate package-publishing setup are outside this repository preparation.
