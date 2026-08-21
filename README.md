# mojo-channel

Interim conda channel for the Ameyanagi Mojo ecosystem (akari, hibana, kagerou, moji, mojotui, nagare, nami, nerai, sen, shuhafft, yomi, yuragi).

Usage in pixi.toml:

    channels = ["https://ameyanagi.github.io/mojo-channel", ...]

Packages are built from the agent/wave3-* branches; osx-arm64 only for now (Linux builds will come from CI). This channel is interim until packages land on modular-community.
