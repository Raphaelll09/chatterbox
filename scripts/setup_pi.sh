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
STEP_POWERD_OK=0

echo "== Chatterbox Pi5 provisioning =="
echo "Working root: $WORKING_ROOT"
echo "Venv target : $VENV_DIR"
echo

# ---------------------------------------------------------------------------
# 1. System (apt) dependencies.
# ---------------------------------------------------------------------------
echo "-- [1/8] Installing apt packages from apt-packages-pi.txt"
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
echo "-- [2/8] Creating/reusing venv at $VENV_DIR"
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
echo "-- [3/8] Installing requirements-pi.txt"
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
echo "-- [4/8] Downloading pretrained weights"
pip install --quiet gdown

# fetch_and_unzip <drive-folder-url> <extract-target-dir> <sentinel-file> [sentinel-file ...]
# Downloads every file in the Drive folder into a temp dir, unzips any archives found into
# <extract-target-dir>, then flattens a one-level self-named nested directory if the archive's
# top-level folder duplicates the target dir name (observed with these exact archives on the dev
# checkout this script's paths were verified against — e.g. hifi-gan-master/FR_V2/FR_V2/...).
#
# Accepts one or more sentinels (not just one) because a `gdown --folder` download can succeed
# for *some* of a Drive folder's files/archives and silently miss others — e.g. FastSpeech2's
# Drive folder bundles output/ckpt/, config/, and preprocessed_data/ separately, and a partial
# download that got the (large) checkpoint but not the (small) config/preprocessed_data files
# used to still pass this check and report PASS, only to fail much later as a confusing
# FileNotFoundError deep inside do_tts.py's backend.load_fastspeech2(). ALL given sentinels must
# exist, both to skip a re-download and to consider a fresh download successful.
fetch_and_unzip() {
    local drive_url="$1"
    local target_dir="$2"
    shift 2
    local sentinels=("$@")

    local all_present=1
    local s
    for s in "${sentinels[@]}"; do
        [[ -f "$s" ]] || all_present=0
    done
    if [[ "$all_present" -eq 1 ]]; then
        echo "   [skip] all sentinels already present for $(basename "$target_dir")."
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

    local missing=0
    for s in "${sentinels[@]}"; do
        if [[ -f "$s" ]]; then
            echo "   OK: $s"
        else
            echo "   WARNING: expected $s after extraction but did not find it — check $target_dir manually, or delete $target_dir and re-run to retry the whole download." >&2
            missing=1
        fi
    done
    [[ "$missing" -eq 0 ]]
}

WEIGHTS_OK=1
fetch_and_unzip \
    "https://drive.google.com/drive/folders/13kLu5UwwTRH3hCyD8EcTwkl4aHosffy4?usp=sharing" \
    "$WORKING_ROOT/assets/models/FastSpeech2" \
    "$WORKING_ROOT/assets/models/FastSpeech2/output/ckpt/ALL_corpus/390000.pth.tar" \
    "$WORKING_ROOT/assets/models/FastSpeech2/config/ALL_corpus/preprocess.yaml" \
    "$WORKING_ROOT/assets/models/FastSpeech2/config/ALL_corpus/model.yaml" \
    "$WORKING_ROOT/assets/models/FastSpeech2/config/ALL_corpus/train.yaml" \
    "$WORKING_ROOT/assets/models/FastSpeech2/preprocessed_data/ALL_corpus/speakers.json" || WEIGHTS_OK=0

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
echo "-- [5/8] Smoke test: torch CPU tensor ops"
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
echo "-- [6/8] Smoke test: end-to-end synthesis (best-effort)"
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
echo "-- [7/8] Writing lock file"
if [[ "$STEP_APT_OK" -eq 1 && "$STEP_VENV_OK" -eq 1 && "$STEP_PIP_OK" -eq 1 ]]; then
    pip freeze > "$LOCK_FILE"
    echo "   Wrote $LOCK_FILE"
else
    echo "   [skip] earlier required step failed, not writing lock file." >&2
fi
echo

# ---------------------------------------------------------------------------
# 8. chatterbox-powerd systemd units (chatterbox-powerd_spec_v0.1.md Sec8/Sec9.5).
#
# Non-fatal if any part of this fails (matches the weights/synth-smoke-test steps above) --
# powerd is an optional appliance-mode feature, not required for `do_tts.py` itself to work.
# Deliberately does NOT touch EEPROM/config.txt (POWER_OFF_ON_HALT, dtoverlay=disable-wifi/-bt,
# arm_freq_min) -- those are boot-config edits with a brick-on-mistake risk this script avoids
# elsewhere too; see INSTALL.md "chatterbox-powerd" for the manual steps.
# ---------------------------------------------------------------------------
echo "-- [8/8] Installing chatterbox-powerd systemd units"
UNIT_SRC_DIR="$WORKING_ROOT/deploy/systemd"
POWERD_GROUP="chatterbox"
INSTALL_USER="${SUDO_USER:-$USER}"

if [[ -f "$UNIT_SRC_DIR/chatterbox-powerd.service" && -f "$UNIT_SRC_DIR/chatterbox-gui.service" ]]; then
    if sudo cp "$UNIT_SRC_DIR/chatterbox-powerd.service" "$UNIT_SRC_DIR/chatterbox-gui.service" \
            /etc/systemd/system/ \
        && sudo groupadd -f "$POWERD_GROUP" \
        && sudo usermod -aG "$POWERD_GROUP" "$INSTALL_USER" \
        && sudo systemctl daemon-reload \
        && sudo systemctl enable chatterbox-powerd.service chatterbox-gui.service
    then
        echo "   Installed and enabled chatterbox-powerd.service + chatterbox-gui.service (not started)."
        echo "   Added '$INSTALL_USER' to the '$POWERD_GROUP' group (log out/in, or reboot, for it to take effect)."
        echo "   NOTE: both units reference /home/gerantos/chatterbox by default -- edit"
        echo "         /etc/systemd/system/chatterbox-{powerd,gui}.service if your user/clone path differs,"
        echo "         then \`sudo systemctl daemon-reload\`."
        echo "   NOT done automatically (see INSTALL.md \"chatterbox-powerd\" for the manual steps):"
        echo "     - EEPROM/config.txt: keep POWER_OFF_ON_HALT=0; consider dtoverlay=disable-wifi,"
        echo "       dtoverlay=disable-bt, arm_freq_min=500."
        echo "     - Confirm amp SD-pin polarity and the backlight sysfs node against real hardware"
        echo "       (chatterbox/config/user_prefs.yaml: amp.sd_pin / amp.enable_active_high / display.backlight)."
        echo "     - Start the services when ready: sudo systemctl start chatterbox-powerd chatterbox-gui"
        STEP_POWERD_OK=1
    else
        echo "   WARNING: systemd unit install failed partway through -- see errors above." >&2
    fi
else
    echo "   WARNING: $UNIT_SRC_DIR/*.service not found -- skipping (repo checkout out of sync?)." >&2
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
printf '%-45s %s\n' "chatterbox-powerd systemd units:"  "$([[ $STEP_POWERD_OK -eq 1 ]] && echo PASS || echo "SKIPPED/FAIL (non-fatal, optional)")"

if [[ "$STEP_APT_OK" -eq 1 && "$STEP_VENV_OK" -eq 1 && "$STEP_PIP_OK" -eq 1 && "$STEP_SMOKE_TORCH_OK" -eq 1 ]]; then
    echo
    echo "RESULT: PASS (core install verified)."
    echo "Lock file: $LOCK_FILE"
    [[ "$STEP_WEIGHTS_OK" -eq 1 && "$STEP_SMOKE_SYNTH_OK" -eq 1 ]] || \
        echo "NOTE: weights and/or end-to-end synthesis need manual follow-up — see warnings above."
    [[ "$STEP_POWERD_OK" -eq 1 ]] || \
        echo "NOTE: chatterbox-powerd systemd units were not installed — see warnings above (optional feature)."
    exit 0
else
    echo
    echo "RESULT: FAIL — see errors above."
    exit 1
fi
