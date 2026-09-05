#!/usr/bin/env bash
# Run only on a native runner; the audit and publisher remain solve-only.
set -euo pipefail
if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 ARTIFACT SUBDIR SMOKE_SOURCE" >&2
  exit 2
fi
if [[ ! -f "$1" || ! -r "$1" ]]; then
  echo "candidate artifact is not a readable file: $1" >&2
  exit 2
fi
if [[ ! -f "$3" || ! -r "$3" ]]; then
  echo "consumer smoke source is not a readable file: $3" >&2
  exit 2
fi
artifact="$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"
subdir="$2"
smoke_source="$3"
case "$(uname -s):$(uname -m):$subdir" in
  Linux:x86_64:linux-64|Linux:aarch64:linux-aarch64|Darwin:arm64:osx-arm64) ;;
  *) echo "Native consumer verification refuses foreign platform $subdir" >&2; exit 2 ;;
esac
if [[ "$(pixi --version)" != "pixi 0.76.2" ]]; then
  echo "native consumer verification requires pixi 0.76.2" >&2
  exit 2
fi
consumer="$(mktemp -d "${TMPDIR:-/tmp}/mojo-native-consumer.XXXXXXXX")"
trap 'rm -rf -- "$consumer"' EXIT
cp "$smoke_source" "$consumer/smoke.mojo"
pixi init "$consumer" --platform "$subdir" \
  --channel https://ameyanagi.github.io/mojo-channel \
  --channel https://conda.modular.com/max --channel conda-forge
pixi add --manifest-path "$consumer" "$artifact"
(cd "$consumer" && pixi run --locked mojo run smoke.mojo)
printf 'Installed and ran exact native candidate: %s (%s)\n' "$artifact" "$subdir"
