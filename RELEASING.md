# Releasing DevDoctor

This is the repeatable process for cutting a DevDoctor release. It is
deliberately lightweight and pre-1.0: DevDoctor follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html), and while the
major version is `0`, breaking changes are allowed in minor bumps.

> **Note on names:** the product is **DevDoctor**; the installable Python
> package and CLI are still named `devdoctor`. There are two version strings to
> keep in sync — `pyproject.toml` (the package) and `web/package.json` (the web
> UI and desktop shell).

## What is and isn't automated

- **Not yet published to PyPI.** Reserving the `devdoctor` name on PyPI is
  tracked by [#7](https://github.com/katagun/devdoctor/issues/7); until then the
  release process does **not** publish to PyPI, and there is no PyPI credential
  anywhere in CI.
- **No signed desktop distributable yet.** `npm run electron:pack` produces an
  **unsigned** `.app`. A signed and notarized `.dmg`/`.zip` is deferred to
  [#6](https://github.com/katagun/devdoctor/issues/6), which is blocked on an
  Apple Developer certificate.
- **Optional release workflow.** `.github/workflows/release.yml` builds the
  Python sdist/wheel and creates the GitHub Release automatically when you push
  a `v*` tag (see [step 6](#6-tag-and-push)). You can also do every step by hand
  with the commands below.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) for the Python build.
- Node and npm (only if you are also producing the desktop app).
- Push access to `main` and permission to create tags and releases.
- A clean working tree on an up-to-date `main`.

## Steps

### 1. Pick the version

Decide the new `x.y.z` per SemVer based on what's in the `[Unreleased]` section
of [CHANGELOG.md](CHANGELOG.md).

### 2. Bump the version in both manifests

The two must stay in sync:

- `pyproject.toml` → `[project]` `version`
- `web/package.json` → `version`

### 3. Update the changelog

In [CHANGELOG.md](CHANGELOG.md):

- Rename the `## [Unreleased]` heading to `## [x.y.z] - YYYY-MM-DD` (today's
  date), and add a fresh, empty `## [Unreleased]` section above it.
- Update the link references at the bottom of the file:

  ```markdown
  [Unreleased]: https://github.com/katagun/devdoctor/compare/vX.Y.Z...HEAD
  [x.y.z]: https://github.com/katagun/devdoctor/releases/tag/vX.Y.Z
  ```

  (The very first release replaces the `commits/main` link with these two.)

### 4. Open a release PR

Commit the version bumps and changelog on a branch, open a PR against `main`,
and let CI (Python + web) go green. Merge it.

### 5. Build the artifacts

From an up-to-date checkout of the merged commit:

```bash
# Python sdist + wheel (hatchling backend) → dist/
uv build
```

The wheel force-includes the built web bundle
(`src/devdoctor/web/_static/dist`), so if you are building the wheel by hand
run the web build first — `./scripts/deploy.sh` or `cd web && npm run build` —
otherwise the packaged UI shows the "assets are not built yet" placeholder.

For the desktop app (macOS only, unsigned):

```bash
cd web
npm ci
npm run electron:pack   # → web/release/…/DevDoctor.app (unsigned)
```

### 6. Tag and push

```bash
git checkout main
git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 7. Create the GitHub Release

If `.github/workflows/release.yml` is present, pushing the `vX.Y.Z` tag builds
the sdist/wheel and creates the GitHub Release with those artifacts attached
automatically. Then edit the release notes to paste in the changelog section for
this version.

To do it manually instead:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "<paste the CHANGELOG section for x.y.z>" \
  dist/*
```

Attach the unsigned `DevDoctor.app` (zipped) if you want to share the desktop
build, noting that it is unsigned until [#6](https://github.com/katagun/devdoctor/issues/6).

### 8. PyPI (deferred)

Skipped until the package name is reserved
([#7](https://github.com/katagun/devdoctor/issues/7)). Once that lands, the
publish step (`uv publish` with a trusted-publisher / API token) can be added
here and, if desired, to the release workflow.
