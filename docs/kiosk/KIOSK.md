# Kiosk finalization

Step 3 of `README_power_gui_workstream.md`'s build sequence: wrapping the already-verified
`chatterbox-powerd` + GUI stack (`docs/power/POWERD.md`, `docs/gui/GUI.md`, all of
`Bring-up_Integration_Test_Protocol_v0.1.md`'s T0-T7) in an actual unattended kiosk boot.

Prerequisite: T0-T7 green on real hardware, with the **real** (non-test) timers restored in
`chatterbox/config/user_prefs.yaml` — don't finalize kiosk boot with the short test timers T0
asked you to set.

## Compositor: cage

Finalized choice (was an open decision in the workstream README): **cage**, a minimal Wayland
kiosk compositor that runs a single app fullscreen via XWayland (Tk itself only speaks X11, not
native Wayland). `deploy/systemd/chatterbox-gui.service` already assumes this. Packages:
`cage`+`xwayland` in `apt-packages-pi.txt` (installed by `scripts/setup_pi.sh`).

If cage fails to acquire the display seat when launched as a systemd service
(`journalctl -u chatterbox-gui` showing a seat/session error): the usual fix is installing
`seatd` as a fallback seat manager — not pre-installed here, since systemd-logind (already
present on Raspberry Pi OS) is normally sufficient; only reach for it if you actually see that
failure.

## `scripts/kiosk_finalize.sh`

The one opt-in script that commits the Pi to unattended kiosk boot. **Not** part of
`scripts/setup_pi.sh`'s default run — that script stays scoped to "get the app runnable"; this is
the separate "make it boot straight into it, unattended" step, run manually once you're ready:

```bash
cd ~/chatterbox
bash scripts/kiosk_finalize.sh
```

What it does, in order — every step is independently logged, and either fully reversible or
backed-up-before-write (never a blind rewrite of a boot-config file):

| Step | Action | Undo |
|---|---|---|
| 1. EEPROM check | **Read-only** — reports current `POWER_OFF_ON_HALT`. Never writes EEPROM. | N/A (nothing written) |
| 2. `config.txt` | Backs up, then appends (only if missing) `dtoverlay=disable-wifi`, `dtoverlay=disable-bt`, `arm_freq_min=500`. Auto-detects `/boot/firmware/config.txt` vs `/boot/config.txt`. | Restore the printed `.bak.<timestamp>` file |
| 3. `cmdline.txt` | Same backup+idempotent-append approach: adds `quiet`, `loglevel=1`, `logo.nologo` tokens if not already present. | Restore the printed `.bak.<timestamp>` file |
| 4. `getty@tty1.service` | Disabled — `chatterbox-gui.service` uses `TTYPath=/dev/tty1`+`PAMName=login` to become the tty1 session directly (the standard systemd kiosk pattern); a stock getty on the same tty would race with it. | `sudo systemctl enable --now getty@tty1.service` |
| 5. Services | `chatterbox-powerd` + `chatterbox-gui` enabled **and started** (`setup_pi.sh` already enables them but deliberately doesn't start them). | `sudo systemctl disable --now chatterbox-powerd chatterbox-gui` |

Exits non-zero (with a `RESULT: FAIL` summary) if the getty-disable or service-start step failed —
review the warnings before rebooting unattended in that case. Safe to re-run: every step is
idempotent.

After a clean run: **`sudo reboot`** and confirm the Pi boots straight into the GUI with no login
prompt, no getty on tty1, and both services running (`systemctl status chatterbox-powerd
chatterbox-gui` over SSH).

## Deliberately not automated

- **EEPROM writes.** `rpi-eeprom-config --edit` is interactive and only needed if the read-only
  check in step 1 warns — a bad EEPROM write is harder to recover from than a bad `config.txt`
  line (which just needs the backup restored by reading the SD card from another machine).
- **`scripts/hw_check.py`** — referenced by `Bring-up_Integration_Test_Protocol_v0.1.md` as
  optional tooling for its T1 (hardware primitives)/T2 (socket roundtrip) steps; not built, since
  those steps are already done manually per that protocol.
- **Wake→interactive boot time measurement** — needs a stopwatch on an actual reboot; feeds
  `power.t_deep_s` in `user_prefs.yaml` (a value you set based on the real number, not something
  computed here).

## Maintenance / recovery access

Deliberately **not** an in-GUI "maintenance mode" button — the two things `kiosk_finalize.sh`
locks down (wifi/bluetooth radios, tty1's getty) are boot-time config changes, not runtime
toggles, so a GUI button couldn't flip them live anyway (both need a reboot to take effect), and a
kiosk-escape control has real access-control implications (who can reach it, PIN-gated or not) that
haven't been designed. Manual recovery instead:

- **SSH is never disabled by `kiosk_finalize.sh`** — only step 2's `dtoverlay=disable-wifi/-bt`
  and step 4's `getty@tty1` are touched, neither of which affects `sshd`. If the Pi has an
  **Ethernet** cable connected, SSH in over that even with wifi disabled by `config.txt`.
- **To restore wifi/bluetooth**: remove (or comment out) the `dtoverlay=disable-wifi` /
  `dtoverlay=disable-bt` lines from `config.txt` — either restore the `.bak.<timestamp>` file
  `kiosk_finalize.sh` printed the path to at the time, or SSH in and edit `config.txt` by hand —
  then `sudo reboot`. This is a boot-time overlay, not a running-kernel toggle; nothing short of a
  reboot re-enables the radios.
- **To get a terminal on the physical screen**: `sudo systemctl stop chatterbox-gui` (frees
  `tty1`, which the GUI service and a getty would otherwise both want), then
  `sudo systemctl enable --now getty@tty1.service` for a normal login prompt. Reverse with
  `sudo systemctl disable --now getty@tty1.service && sudo systemctl start chatterbox-gui` to
  return to kiosk mode.
- **No network access at all** (e.g. wifi-only Pi, disabled, no Ethernet handy): pull the SD card,
  edit `config.txt` from another machine, reinsert, boot.

## Mass deployment

Once one Pi 5 has been through `setup_pi.sh` → the full bring-up protocol → `kiosk_finalize.sh` →
a confirmed clean unattended boot, image that SD card rather than repeating all of the above per
unit — see `INSTALL.md` "Mass deployment: golden image".
