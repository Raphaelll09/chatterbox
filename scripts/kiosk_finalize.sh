#!/usr/bin/env bash
# Opt-in "commit to unattended kiosk boot" finalization for a Pi 5 already provisioned by
# scripts/setup_pi.sh and verified per Bring-up_Integration_Test_Protocol_v0.1.md (T0-T7 green).
# See docs/kiosk/KIOSK.md for what each step below does and how to undo it.
#
# NOT part of setup_pi.sh's default flow -- run this manually, once, only when you're ready to
# have the Pi boot straight into the kiosk GUI unattended (setup_pi.sh stays scoped to "get the
# app runnable"; this is the separate "make it a kiosk" step). Every step is independently
# logged and either fully reversible (systemd enable/disable) or backed-up-before-write
# (config.txt/cmdline.txt) -- never a blind rewrite.
#
# Deliberately does NOT touch EEPROM (rpi-eeprom-config) beyond reading it -- a bad EEPROM write
# is a harder failure mode to recover from than a bad config.txt/cmdline.txt line (which just
# needs the backup restored from another machine reading the SD card), and POWER_OFF_ON_HALT
# already defaults to the wanted value on stock Raspberry Pi OS.
set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Guard clause: must be Linux/aarch64 (Raspberry Pi 5, 64-bit OS) -- same as setup_pi.sh.
# ---------------------------------------------------------------------------
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"
if [[ "$OS_NAME" != "Linux" || "$ARCH_NAME" != "aarch64" ]]; then
    echo "ERROR: this script must be run on Linux/aarch64 (Raspberry Pi 5, 64-bit OS)." >&2
    echo "       detected: OS=$OS_NAME ARCH=$ARCH_NAME" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

STEP_EEPROM_OK=0
STEP_CONFIG_TXT_OK=0
STEP_CMDLINE_TXT_OK=0
STEP_GETTY_OK=0
STEP_SERVICES_OK=0

echo "== Chatterbox kiosk finalization =="
echo "Working root: $WORKING_ROOT"
echo

# ---------------------------------------------------------------------------
# 1. EEPROM check (read-only -- never writes EEPROM; see header comment).
# ---------------------------------------------------------------------------
echo "-- [1/5] Checking EEPROM POWER_OFF_ON_HALT (read-only)"
if command -v rpi-eeprom-config >/dev/null 2>&1; then
    EEPROM_CONF="$(sudo rpi-eeprom-config 2>/dev/null || true)"
    POWER_OFF_VALUE="$(echo "$EEPROM_CONF" | grep -E '^POWER_OFF_ON_HALT=' | cut -d= -f2 || true)"
    if [[ -z "$POWER_OFF_VALUE" || "$POWER_OFF_VALUE" == "0" ]]; then
        echo "   OK: POWER_OFF_ON_HALT is ${POWER_OFF_VALUE:-unset (defaults to 0)} -- halt stays button-wakeable."
        STEP_EEPROM_OK=1
    else
        echo "   WARNING: POWER_OFF_ON_HALT=$POWER_OFF_VALUE -- DEEP's halt will be power-cycle-only," >&2
        echo "            not button-wakeable. To fix: sudo rpi-eeprom-config --edit, set" >&2
        echo "            POWER_OFF_ON_HALT=0, save, then 'sudo reboot' -- not done automatically." >&2
    fi
else
    echo "   WARNING: rpi-eeprom-config not found -- skipping (not on real Pi 5 firmware?)." >&2
fi
echo

# ---------------------------------------------------------------------------
# 2. config.txt tuning: idempotent, backed-up append -- never a blind rewrite.
# ---------------------------------------------------------------------------
echo "-- [2/5] Tuning config.txt (dtoverlay=disable-wifi/-bt, arm_freq_min=500)"
CONFIG_TXT=""
for candidate in /boot/firmware/config.txt /boot/config.txt; do
    if [[ -f "$candidate" ]]; then
        CONFIG_TXT="$candidate"
        break
    fi
done

append_line_if_missing() {
    # append_line_if_missing <file> <line> -- exact whole-line match, so safe to re-run.
    local file="$1" line="$2"
    if grep -qxF "$line" "$file"; then
        echo "   [skip] already present: $line"
    else
        echo "$line" | sudo tee -a "$file" >/dev/null
        echo "   Added: $line"
    fi
}

if [[ -n "$CONFIG_TXT" ]]; then
    BACKUP="${CONFIG_TXT}.bak.$(date +%Y%m%d_%H%M%S)"
    sudo cp "$CONFIG_TXT" "$BACKUP"
    echo "   Backed up $CONFIG_TXT -> $BACKUP"
    append_line_if_missing "$CONFIG_TXT" "dtoverlay=disable-wifi"
    append_line_if_missing "$CONFIG_TXT" "dtoverlay=disable-bt"
    append_line_if_missing "$CONFIG_TXT" "arm_freq_min=500"
    STEP_CONFIG_TXT_OK=1
else
    echo "   WARNING: neither /boot/firmware/config.txt nor /boot/config.txt found -- skipping." >&2
fi
echo

# ---------------------------------------------------------------------------
# 3. cmdline.txt tuning: same backup+idempotent-append approach, one line file.
# ---------------------------------------------------------------------------
echo "-- [3/5] Tuning cmdline.txt (quiet boot)"
CMDLINE_TXT=""
for candidate in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
    if [[ -f "$candidate" ]]; then
        CMDLINE_TXT="$candidate"
        break
    fi
done

append_token_if_missing() {
    # append_token_if_missing <file> <token> -- cmdline.txt is a single line of space-separated
    # tokens; appends <token> only if it isn't already a whole token on that line (avoids a
    # substring false-positive, e.g. "quiet" inside some other token).
    local file="$1" token="$2"
    local current
    current="$(cat "$file")"
    if [[ " $current " == *" $token "* ]]; then
        echo "   [skip] already present: $token"
    else
        echo "${current} ${token}" | sudo tee "$file" >/dev/null
        echo "   Added: $token"
    fi
}

if [[ -n "$CMDLINE_TXT" ]]; then
    BACKUP="${CMDLINE_TXT}.bak.$(date +%Y%m%d_%H%M%S)"
    sudo cp "$CMDLINE_TXT" "$BACKUP"
    echo "   Backed up $CMDLINE_TXT -> $BACKUP"
    append_token_if_missing "$CMDLINE_TXT" "quiet"
    append_token_if_missing "$CMDLINE_TXT" "loglevel=1"
    append_token_if_missing "$CMDLINE_TXT" "logo.nologo"
    STEP_CMDLINE_TXT_OK=1
else
    echo "   WARNING: neither /boot/firmware/cmdline.txt nor /boot/cmdline.txt found -- skipping." >&2
fi
echo

# ---------------------------------------------------------------------------
# 4. Disable getty@tty1 -- chatterbox-gui.service uses TTYPath=/dev/tty1 + PAMName=login to
# become the tty1 session directly (the standard systemd kiosk pattern); leaving the stock
# getty enabled on the same tty races with it. Fully reversible.
# ---------------------------------------------------------------------------
echo "-- [4/5] Disabling getty@tty1.service (chatterbox-gui.service replaces it on tty1)"
if sudo systemctl disable getty@tty1.service; then
    echo "   Disabled. Undo with: sudo systemctl enable --now getty@tty1.service"
    STEP_GETTY_OK=1
else
    echo "   WARNING: could not disable getty@tty1.service -- check manually." >&2
fi
echo

# ---------------------------------------------------------------------------
# 5. Enable + start chatterbox-powerd / chatterbox-gui. setup_pi.sh already installs+enables
# these but deliberately does not start them -- this is that explicit "go" step.
# ---------------------------------------------------------------------------
echo "-- [5/5] Enabling + starting chatterbox-powerd and chatterbox-gui"
if sudo systemctl enable --now chatterbox-powerd.service chatterbox-gui.service; then
    echo "   Started. Check with: systemctl status chatterbox-powerd chatterbox-gui"
    STEP_SERVICES_OK=1
else
    echo "   WARNING: failed to enable/start one or both services -- check with" >&2
    echo "            'journalctl -u chatterbox-powerd -u chatterbox-gui'." >&2
fi
echo

# ---------------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------------
echo "== Summary =="
printf '%-40s %s\n' "EEPROM POWER_OFF_ON_HALT:"  "$([[ $STEP_EEPROM_OK -eq 1 ]] && echo PASS || echo "WARN (see above)")"
printf '%-40s %s\n' "config.txt tuning:"          "$([[ $STEP_CONFIG_TXT_OK -eq 1 ]] && echo PASS || echo "SKIPPED/FAIL")"
printf '%-40s %s\n' "cmdline.txt tuning:"         "$([[ $STEP_CMDLINE_TXT_OK -eq 1 ]] && echo PASS || echo "SKIPPED/FAIL")"
printf '%-40s %s\n' "getty@tty1 disabled:"        "$([[ $STEP_GETTY_OK -eq 1 ]] && echo PASS || echo FAIL)"
printf '%-40s %s\n' "services enabled+started:"   "$([[ $STEP_SERVICES_OK -eq 1 ]] && echo PASS || echo FAIL)"
echo

if [[ "$STEP_GETTY_OK" -eq 1 && "$STEP_SERVICES_OK" -eq 1 ]]; then
    echo "RESULT: PASS (kiosk boot path is live)."
    echo "Reboot now to verify the Pi boots straight into the kiosk GUI unattended: sudo reboot"
    exit 0
else
    echo "RESULT: FAIL -- see warnings above before rebooting unattended." >&2
    exit 1
fi
