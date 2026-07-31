#!/usr/bin/env bash
# Downloads the Piper voices this repo's Piper backend config_tts.yaml entries expect
# (chatterbox/synthesis/backends/piper/), verifying each file's sha256 against the values recorded
# in chatterbox/synthesis/backends/piper/README.md (captured live from a real download during
# Phase B of the Piper integration, and again when the English lessac voice was added -- see
# docs/context/CHANGELOG.md for both).
#
# Not part of scripts/setup_pi.sh's default run (doc's cc_prompt_piper_backend.md Sec1/Sec7:
# Piper is an optional, separately-installed backend, not a hard dependency of this repo). Run
# manually, from the repo root:
#   ./scripts/fetch_piper_voices.sh
#
# Safe to re-run: skips a file whose sha256 already matches.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST_DIR="$WORKING_ROOT/assets/models/Piper"
HF_ROOT="https://huggingface.co/rhasspy/piper-voices/resolve/main"

mkdir -p "$DEST_DIR"

# locale_path:voice_dir:checkpoint_stem:sha256(.onnx):sha256(.onnx.json)
# locale_path is HuggingFace's own <lang>/<lang_region> path segment (differs per voice, unlike
# the single shared fr/fr_FR BASE_URL this script used before the English voice was added).
# "tom" was removed (docs/context/CHANGELOG.md) after real-hardware evaluation found noticeably
# lower voice quality and slower inference than siwis/upmc, with no offsetting benefit.
VOICES=(
  "fr/fr_FR:siwis:fr_FR-siwis-medium:641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99:39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959"
  "fr/fr_FR:upmc:fr_FR-upmc-medium:9abb3800c199148897a9ed64e100d224f3de83579f100044174ad19418f1786f:e8636ec15dfd5d72db37a02cb5320a20f2b8d339f2a0e4337da64c58a33a5868"
  "en/en_US:lessac:en_US-lessac-medium:5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f:efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"
)

verify_sha256() {
    local file="$1" expected="$2"
    local actual
    actual="$(sha256sum "$file" | cut -d' ' -f1)"
    if [[ "$actual" != "$expected" ]]; then
        echo "ERROR: sha256 mismatch for $file" >&2
        echo "       expected: $expected" >&2
        echo "       actual:   $actual" >&2
        return 1
    fi
}

fetch_one() {
    local url="$1" dest="$2" expected_sha="$3"
    if [[ -f "$dest" ]] && verify_sha256 "$dest" "$expected_sha" 2>/dev/null; then
        echo "  already present, sha256 verified: $(basename "$dest")"
        return 0
    fi
    echo "  downloading $(basename "$dest") ..."
    curl -sL -o "$dest" "$url"
    verify_sha256 "$dest" "$expected_sha"
    echo "  OK: $(basename "$dest")"
}

for entry in "${VOICES[@]}"; do
    IFS=':' read -r locale_path voice_dir stem onnx_sha json_sha <<< "$entry"
    voice_url="$HF_ROOT/$locale_path/$voice_dir/medium"
    echo "-- ${stem}"
    fetch_one "$voice_url/${stem}.onnx" "$DEST_DIR/${stem}.onnx" "$onnx_sha"
    fetch_one "$voice_url/${stem}.onnx.json" "$DEST_DIR/${stem}.onnx.json" "$json_sha"
done

echo
echo "All ${#VOICES[@]} Piper voices present and sha256-verified in $DEST_DIR"
