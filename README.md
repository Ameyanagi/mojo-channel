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
