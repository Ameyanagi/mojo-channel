#!/usr/bin/env bash

set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 ARTIFACT SUBDIR CHANNEL_ROOT" >&2
  exit 2
fi

artifact="$1"
subdir="$2"
channel_root="$3"

case "$subdir" in
  linux-64 | linux-aarch64 | osx-arm64) ;;
  *)
    echo "unsupported candidate subdir: $subdir" >&2
    exit 2
    ;;
esac

if [[ ! -f "$artifact" ]]; then
  echo "candidate artifact is not a file: $artifact" >&2
  exit 2
fi
if [[ ! -d "$channel_root" ]]; then
  echo "channel root is not a directory: $channel_root" >&2
  exit 2
fi
if [[ "$(pixi --version)" != "pixi 0.76.2" ]]; then
  echo "candidate solving requires pixi 0.76.2" >&2
  exit 2
fi

artifact_directory="$(cd "$(dirname "$artifact")" && pwd -P)"
artifact_path="${artifact_directory}/$(basename "$artifact")"
channel_root="$(cd "$channel_root" && pwd -P)"
if [[ "$artifact_directory" != "${channel_root}/${subdir}" ]]; then
  echo "candidate must be a direct child of ${channel_root}/${subdir}" >&2
  exit 2
fi

channel_uri="file://${channel_root}"
artifact_uri="file://${artifact_path}"
solve_workspace="$(mktemp -d "${TMPDIR:-/tmp}/mojo-channel-solve.XXXXXXXX")"
trap 'rm -rf -- "$solve_workspace"' EXIT

pixi init "$solve_workspace" \
  --channel "$channel_uri" \
  --channel https://conda.modular.com/max \
  --channel conda-forge \
  --platform "$subdir"
pixi add \
  --manifest-path "$solve_workspace" \
  --no-install \
  "$artifact_path"
pixi lock --manifest-path "$solve_workspace" --check

grep -Fq -- "url = \"${artifact_uri}\"" "$solve_workspace/pixi.toml"
grep -Fq -- "channels = [\"${channel_uri}\", \"https://conda.modular.com/max\", \"conda-forge\"]" \
  "$solve_workspace/pixi.toml"
grep -Fq -- "- conda: ${artifact_path}" "$solve_workspace/pixi.lock"
grep -Fq -- "- url: ${channel_uri}/" "$solve_workspace/pixi.lock"
grep -Fq -- "- url: https://conda.modular.com/max/" "$solve_workspace/pixi.lock"
grep -Fq -- "- url: https://conda.anaconda.org/conda-forge/" "$solve_workspace/pixi.lock"
[[ ! -d "$solve_workspace/.pixi/envs" ]]

printf 'Solved exact candidate without installation: %s (%s)\n' \
  "$artifact_path" "$subdir"
