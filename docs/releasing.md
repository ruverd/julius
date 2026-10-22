# Releasing Julius

The public package is `@ruverd/julius`. The release source is `ruverd/julius` on
GitHub, not the upstream repository. Release from a clean checkout of `main`.
Node.js 20 remains the minimum supported runtime. Publication runs on Node.js 24
with npm 11.5.1 or newer for trusted publishing.

## Version policy

Use Semantic Versioning and annotated `vX.Y.Z` Git tags. While the package is
below 1.0, put breaking changes in a minor version and document migration steps.

| Change | Version bump | npm dist-tag |
| --- | --- | --- |
| Compatible fix | `patch` | `latest` |
| Feature or pre-1.0 breaking change | `minor` | `latest` |
| Stable API milestone or post-1.0 breaking change | `major` | `latest` |
| Preview | `X.Y.Z-alpha.N`, `X.Y.Z-beta.N` or `X.Y.Z-rc.N` | `next` |

Use `fix:`, `feat:`, `docs:`, `test:` and `chore:` commit prefixes. Add `!` and a
`BREAKING CHANGE:` explanation when the public API changes incompatibly.
Keep unreleased changes in `CHANGELOG.md`. The archived upstream changelog is
provenance and must remain unchanged.

## Prepare and review

Create a release branch from current `origin/main`. For example:

```sh
git switch -c release/next origin/main
npm version minor --no-git-tag-version
```

`npm version` updates both package files. Replace the unreleased changelog
section with `## X.Y.Z` matching `package.json`, write user-facing notes, and
leave a new empty `## [Unreleased]` section above it. Then run:

```sh
npm ci --engine-strict
npm test
node scripts/verify-native-parsers.mjs
npm run release:check
npm run release:smoke
julius check
```

The smoke check packs the built output, audits the file list, installs that
archive in a disposable consumer, imports the public API, builds and checks a
fixture graph, and runs the installed CLI. It contacts npm only because this
maintainer command explicitly installs dependencies. It changes no MCP settings.
Review and merge the release branch through a pull request with passing CI.

## Publish

After the release commit reaches `main`, tag that exact commit:

```sh
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

`release.yml` runs Linux and Windows tests on Node 20, checks native parsers,
and exercises WASM on Node 24. Publication verifies the tag matches both package
versions and the newest changelog release, and requires the tagged commit to be
an ancestor of `main`. A fresh Node 24 job builds and installs the exact tarball
before publishing it to npm with provenance. The workflow then creates a GitHub
release with those notes and the same archive.

## npm account setup

The first package publication requires an authenticated maintainer with access
to the `@ruverd` scope. If the package does not yet exist, publish the reviewed
archive once with `npm publish <archive.tgz> --access public --tag latest` after
`npm login`. npm may require the account's interactive 2FA approval. This local
bootstrap does not carry GitHub Actions provenance.

After the package exists, add this trusted publisher in its npm settings:

| Field | Value |
| --- | --- |
| Provider | GitHub Actions |
| Organization or user | `ruverd` |
| Repository | `julius` |
| Workflow filename | `release.yml` |
| Environment | Leave empty |
| Allowed actions | Enable direct publishing with `npm publish` |

No `NPM_TOKEN` secret is required. See the official
[npm trusted publishing guide](https://docs.npmjs.com/trusted-publishers/).

## Failure recovery

Keep published version numbers immutable. Fix code in a new patch release;
never move an existing release tag. For an interrupted workflow, use the Release
workflow's manual dispatch with the existing tag. It tests that tag again.
If npm already contains the version, publication may only be skipped when its
integrity matches the tested archive. A mismatch is a hard failure.
An existing GitHub release is preserved.

When an initial local publication finishes, create the matching GitHub release
from the reviewed changelog and archive. Later versions use the trusted
publisher automatically. Verify the public package with
`npm view @ruverd/julius version dist-tags dist.integrity` and install the
published version in a disposable prefix before announcing the release.
