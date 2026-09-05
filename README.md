# Ameyanagi Mojo channel

This repository is the immutable, three-platform Conda channel for the
Ameyanagi Mojo ecosystem:

- `linux-64`
- `linux-aarch64`
- `osx-arm64`

Add it before the Modular and Conda Forge channels:

```toml
channels = [
    "https://ameyanagi.github.io/mojo-channel",
    "https://conda.modular.com/max",
    "conda-forge",
]
```

## Publishing

The **Build and publish package** workflow builds one allowlisted repository on
native runners for all three platforms. A preflight run accepts a branch or
commit and uploads temporary workflow artifacts without changing the channel.
A publication run accepts only an annotated `vX.Y.Z` tag whose version matches
both `pixi.toml` and `conda.recipe/recipe.yaml`.

Only the final publication job has `contents: write`. It rejects an existing
package filename with different bytes, records source and artifact hashes in
`artifacts.tsv`, regenerates the channel indexes, commits one additive update,
and verifies that each exact local artifact resolves with the Modular and Conda
Forge channels. Cross-platform verification is solve-only, so the Linux
publisher never links or executes macOS packages (or vice versa).

Published package files are never replaced. Fixes use a new package version or
an incremented Conda build number.

## Channel integrity

Run the complete read-only audit with the same tools as CI:

```sh
pixi exec --spec 'python=3.14.6' --spec 'zstd=1.5.7' \
  python scripts/validate_channel.py .
```

The audit checks every archive's SHA-256, archive identity and runtime dependency
against the ledger and canonical `repodata.json`, including exact archive/index
inventory, build, size, MD5 and dependency agreement. CI also compares the ledger
with the PR base commit; existing source and artifact provenance cannot change.
The publisher runs this same audit before committing any new artifact.

`legacy-artifacts.json` freezes twelve pre-ledger files: Hibana, Moji and ShuhaFFT
0.0.0, and MojoTUI 0.1.0, on all three platforms. Their hashes and full internal
metadata are checked, but their non-exact Mojo dependencies and absent verified
source provenance make them **unsupported legacy artifacts**. They remain
available only to preserve historical bytes. The legacy inventory cannot expand
or change after adoption; all new archives require exact Mojo 1.0.0 runtime
metadata and annotated release provenance. The audit never installs artifacts.

## Dependency maintenance

Dependabot checks SHA-pinned Actions weekly, groups minor/patch updates and leaves
major updates separate, with at most five open PRs. Review upstream compatibility
notes and require a successful **Validate package gate** result before merging
an update. `setup-pixi` 0.10.2 adds RISC-V installation support; the exact Pixi
0.76.2 and Mojo 1.0.0 toolchain remains unchanged. Artifact action major upgrades
must also pass the native package transfer preflight before adoption.

The channel currently publishes additive artifact commits directly to `main`.
Required branch status checks cannot be added without adapting that publication
flow; until publication uses reviewed PRs, the maintainer must enforce the check
above when merging dependency PRs. No automated merge or protection bypass is
configured. See [dependency security ownership and coverage](docs/dependency-security.md)
for ecosystem alert configuration and weekly advisory review.

## Kumihan publication

`kumihan` / `mojo-kumihan` is supported by the native publication allowlist.
Preflight the immutable annotated `v0.1.0` release with `publish=false`; it must
pass all native checks, recipe installed-package tests, exact Mojo metadata and
a second clean consumer installation on Linux x86-64, Linux ARM64 and macOS ARM64.
Only then run the same reviewed tag with `publish=true`. Existing archive bytes
and provenance remain immutable. The initial tag's commit is
`2b00342a3e4570c3bd06b868e15304b406432394`.
