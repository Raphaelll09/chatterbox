#!/usr/bin/env bash
# Provisioning script for a fresh Raspberry Pi 5 (Raspberry Pi OS 64-bit).
# Run this DIRECTLY ON THE PI over SSH, from inside the cloned repo, e.g.:
#   ssh pi@<pi-host>
#   git clone <repo-url> ~/chatterbox
#   cd ~/chatterbox
#   ./scripts/setup_pi.sh
#
# Safe to re-run: every step below checks for existing state before acting (idempotent venv
# creation, skips weight downloads whose target files already exist, etc).
set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Guard clause: must be Linux/aarch64 (Raspberry Pi 5, 64-bit OS).
# ---------------------------------------------------------------------------
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"
if [[ "$OS_NAME" != "Linux" || "$ARCH_NAME" != "aarch64" ]]; then
    echo "ERROR: this script must be run on Linux/aarch64 (Raspberry Pi 5, 64-bit OS)." >&2
    echo "       detected: OS=$OS_NAME ARCH=$ARCH_NAME" >&2
    echo "       it downloads a CPU-only aarch64 build and will not do the right thing elsewhere." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"   # embedded_tts/ — see CLAUDE.md "working root"
VENV_DIR="$HOME/chatterbox/venv"
LOCK_FILE="$WORKING_ROOT/requirements-pi-lock.txt"

STEP_APT_OK=0
STEP_VENV_OK=0
STEP_PIP_OK=0
STEP_WEIGHTS_OK=0
STEP_SMOKE_TORCH_OK=0
STEP_SMOKE_SYNTH_OK=0

echo "== Chatterbox Pi5 provisioning =="
echo "Working root: $WORKING_ROOT"
echo "Venv target : $VENV_DIR"
echo

# ---------------------------------------------------------------------------
# 1. System (apt) dependencies.
# ---------------------------------------------------------------------------
echo "-- [1/7] Installing apt packages from apt-packages-pi.txt"
APT_LIST_FILE="$WORKING_ROOT/apt-packages-pi.txt"
if [[ ! -f "$APT_LIST_FILE" ]]; then
    echo "ERROR: $APT_LIST_FILE not found." >&2
    exit 1
fi
# Strip comments/blank lines — apt-packages-pi.txt documents *why* each package is needed inline.
mapfile -t APT_PACKAGES < <(grep -vE '^\s*#' "$APT_LIST_FILE" | grep -vE '^\s*$')
sudo apt update
sudo apt install -y "${APT_PACKAGES[@]}"
STEP_APT_OK=1
echo

# ---------------------------------------------------------------------------
# 2. Python venv.
# ---------------------------------------------------------------------------
echo "-- [2/7] Creating/reusing venv at $VENV_DIR"
mkdir -p "$(dirname "$VENV_DIR")"
if [[ -f "$VENV_DIR/bin/activate" ]]; then
    echo "   venv already exists, reusing it."
else
    python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
STEP_VENV_OK=1
echo

# ---------------------------------------------------------------------------
# 3. Python (pip) dependencies.
# ---------------------------------------------------------------------------
echo "-- [3/7] Installing requirements-pi.txt"
pip install --upgrade pip
pip install -r "$WORKING_ROOT/requirements-pi.txt"
STEP_PIP_OK=1
echo

# ---------------------------------------------------------------------------
# 4. Pretrained weights.
#
# Links copied verbatim from embedded_tts/README.md ("Modeles pre-entraines et configuration").
# Waveglow is intentionally NOT downloaded here: its vocoder entry is commented out in
# config_tts.yaml (the active pipeline is FastSpeech2 + HiFi-GAN), so it isn't needed to run the
# demo. Link left below as a comment for anyone who wants it manually.
#   Waveglow: https://drive.google.com/drive/folders/1XhpZDhUWTw3EzKxclAnFMfAp9ZQ4NV8t?usp=sharing
# ---------------------------------------------------------------------------
echo "-- [4/7] Downloading pretrained weights"
pip install --quiet gdown

# fetch_and_unzip <drive-folder-url> <extract-target-dir> <sentinel-file>
# Downloads every file in the Drive folder into a temp dir, unzips any archives found into
# <extract-target-dir>, then flattens a one-level self-named nested directory if the archive's
# top-level folder duplicates the target dir name (observed with these exact archives on the dev
# checkout this script's paths were verified against — e.g. hifi-gan-master/FR_V2/FR_V2/...).
fetch_and_unzip() {
    local drive_url="$1"
    local target_dir="$2"
    local sentinel="$3"

    if [[ -f "$sentinel" ]]; then
        echo "   [skip] $sentinel already present."
        return 0
    fi

    echo "   Fetching $(basename "$target_dir") weights..."
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    mkdir -p "$target_dir"

    if ! gdown --folder "$drive_url" -O "$tmp_dir" --quiet; then
        echo "   WARNING: gdown failed for $drive_url — download it manually per README.md and re-run." >&2
        rm -rf "$tmp_dir"
        return 1
    fi

    local found_zip=0
    while IFS= read -r -d '' zip_file; do
        found_zip=1
        unzip -o -q "$zip_file" -d "$target_dir"
    done < <(find "$tmp_dir" -iname '*.zip' -print0)

    if [[ "$found_zip" -eq 0 ]]; then
        # Folder contained raw files (no zip) — gdown already laid them out; copy as-is.
        cp -r "$tmp_dir"/. "$target_dir"/
    fi
    rm -rf "$tmp_dir"

    # Flatten "<target_dir>/<basename(target_dir)>/..." if the zip duplicated the folder name.
    local self_nested="$target_dir/$(basename "$target_dir")"
    if [[ -d "$self_nested" ]]; then
        echo "   Flattening duplicated nested directory: $self_nested"
        cp -r "$self_nested"/. "$target_dir"/
        rm -rf "$self_nested"
    fi

    if [[ -f "$sentinel" ]]; then
        echo "   OK: $sentinel"
        return 0
    else
        echo "   WARNING: expected $sentinel after extraction but did not find it — check $target_dir manually." >&2
        return 1
    fi
}

WEIGHTS_OK=1
fetch_and_unzip \
    "https://drive.google.com/drive/folders/13kLu5UwwTRH3hCyD8EcTwkl4aHosffy4?usp=sharing" \
    "$WORKING_ROOT/assets/models/FastSpeech2" \
    "$WORKING_ROOT/assets/models/FastSpeech2/output/ckpt/ALL_corpus/390000.pth.tar" || WEIGHTS_OK=0

fetch_and_unzip \
    "https://drive.google.com/drive/folders/1yJ7jMCbP0fstVrCar7bKAO3uTBAgjCel?usp=sharing" \
    "$WORKING_ROOT/assets/models/flaubert/flaubert_large_cased" \
    "$WORKING_ROOT/assets/models/flaubert/flaubert_large_cased/pytorch_model.bin" || WEIGHTS_OK=0

fetch_and_unzip \
    "https://drive.google.com/drive/folders/1q4-gRK0QqIYT7PImVczYhi9yN4YG7OYC?usp=sharing" \
    "$WORKING_ROOT/assets/models/hifi-gan-master" \
    "$WORKING_ROOT/assets/models/hifi-gan-master/FR_V2/g_00570000" || WEIGHTS_OK=0

STEP_WEIGHTS_OK=$WEIGHTS_OK
echo

# ---------------------------------------------------------------------------
# 5. Smoke test: torch CPU sanity.
# ---------------------------------------------------------------------------
echo "-- [5/7] Smoke test: torch CPU tensor ops"
if python3 - <<'PYEOF'
import torch
a = torch.randn(4, 4)
b = torch.randn(4, 4)
c = a @ b
assert c.shape == (4, 4)
assert not c.is_cuda
print("torch CPU matmul OK, torch version:", torch.__version__)
PYEOF
then
    STEP_SMOKE_TORCH_OK=1
else
    echo "ERROR: torch CPU smoke test failed." >&2
fi
echo

# ---------------------------------------------------------------------------
# 6. Smoke test: end-to-end synthesis (best-effort — only if weights are present).
# ---------------------------------------------------------------------------
echo "-- [6/7] Smoke test: end-to-end synthesis (best-effort)"
if [[ "$STEP_WEIGHTS_OK" -eq 1 ]]; then
    (
        cd "$WORKING_ROOT"
        if printf 'Bonjour, ceci est un test.\n' | timeout 300 python3 do_tts.py > /tmp/chatterbox_smoke.log 2>&1; then
            STEP_SMOKE_SYNTH_OK=1
        fi
    ) && STEP_SMOKE_SYNTH_OK=1 || STEP_SMOKE_SYNTH_OK=0
    if [[ "$STEP_SMOKE_SYNTH_OK" -eq 1 ]]; then
        echo "   OK: one-sentence synthesis completed."
    else
        echo "   WARNING: end-to-end synthesis smoke test failed or timed out — see /tmp/chatterbox_smoke.log." >&2
        echo "   (non-fatal: dependency/weight install above already succeeded)" >&2
    fi
else
    echo "   [skip] weights are incomplete, skipping end-to-end synthesis test."
fi
echo

# ---------------------------------------------------------------------------
# 7. Lock file.
# ---------------------------------------------------------------------------
echo "-- [7/7] Writing lock file"
if [[ "$STEP_APT_OK" -eq 1 && "$STEP_VENV_OK" -eq 1 && "$STEP_PIP_OK" -eq 1 ]]; then
    pip freeze > "$LOCK_FILE"
    echo "   Wrote $LOCK_FILE"
else
    echo "   [skip] earlier required step failed, not writing lock file." >&2
fi
echo

# ---------------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------------
echo "== Summary =="
printf '%-45s %s\n' "apt packages installed:"        "$([[ $STEP_APT_OK -eq 1 ]] && echo PASS || echo FAIL)"
printf '%-45s %s\n' "venv ready:"                     "$([[ $STEP_VENV_OK -eq 1 ]] && echo PASS || echo FAIL)"
printf '%-45s %s\n' "pip install -r requirements-pi.txt:" "$([[ $STEP_PIP_OK -eq 1 ]] && echo PASS || echo FAIL)"
printf '%-45s %s\n' "pretrained weights present:"     "$([[ $STEP_WEIGHTS_OK -eq 1 ]] && echo PASS || echo "FAIL (see warnings above)")"
printf '%-45s %s\n' "torch CPU smoke test:"            "$([[ $STEP_SMOKE_TORCH_OK -eq 1 ]] && echo PASS || echo FAIL)"
printf '%-45s %s\n' "end-to-end synthesis smoke test:" "$([[ $STEP_SMOKE_SYNTH_OK -eq 1 ]] && echo PASS || echo "SKIPPED/FAIL (non-fatal)")"

if [[ "$STEP_APT_OK" -eq 1 && "$STEP_VENV_OK" -eq 1 && "$STEP_PIP_OK" -eq 1 && "$STEP_SMOKE_TORCH_OK" -eq 1 ]]; then
    echo
    echo "RESULT: PASS (core install verified)."
    echo "Lock file: $LOCK_FILE"
    [[ "$STEP_WEIGHTS_OK" -eq 1 && "$STEP_SMOKE_SYNTH_OK" -eq 1 ]] || \
        echo "NOTE: weights and/or end-to-end synthesis need manual follow-up — see warnings above."
    exit 0
else
    echo
    echo "RESULT: FAIL — see errors above."
    exit 1
fi
