# Kiosk finalization

Step 3 of `README_power_gui_workstream.md`'s build sequence: wrapping the already-verified
`chatterbox-powerd` + GUI stack (`docs/POWERD.md`, `docs/GUI.md`, all of
`Bring-up_Integration_Test_Protocol_v0.1.md`'s T0-T7) in an actual unattended kiosk boot.

Prerequisite: T0-T7 green on real hardware, with the **real** (non-test) timers restored in
`chatterbox/config/user_prefs.yaml` — don't finalize kiosk boot with the short test timers T0
asked you to set.

## Compositor: plain Xorg (cage ruled out — see `deploy/xorg-kiosk/README.md`)

**cage** (a minimal Wayland kiosk compositor running the Tk app fullscreen via XWayland) was the
originally finalized choice — an open decision in the workstream README, resolved in an earlier
session. Real Pi5 hardware bring-up (2026-07-31, `docs/research/CHANGELOG.md`) overturned that:
a reproducible SIGSEGV deep inside `libwlroots` (Raspberry Pi Foundation's own `0.18.2-3+rpt4`
build), triggered by essentially any input event causing a seat/focus signal, confirmed via
`coredumpctl` — backtrace bottoms out in `wl_signal_emit_mutable` inside `libwlroots-0.18.so`, not
in any chatterbox code, cage's own logic, or the XWayland version (reproduced identically on
`22.1.9` and `24.1.6`). No fixed package is available in either the Raspberry Pi or Debian repos
as of that date.

**Current default: plain Xorg**, launched via a real `agetty --autologin` console session (not a
systemd `TTYPath=`/`PAMName=login` unit — that pattern is Wayland/logind-oriented and was
measurably flakier for legacy X11's own console/VT expectations). Tk only ever needs X11 — it
doesn't care whether that X11 comes via XWayland-under-cage or a plain Xorg session — so this
sidesteps `wlroots` entirely. Full mechanism, exact files, and every real bug found getting there
(a `Toplevel.grab_set()` crash, a fullscreen-sizing gap, a relative-config-path crash, output
buffering hiding a traceback): `deploy/xorg-kiosk/README.md`.

`deploy/systemd/chatterbox-gui.service` (the cage unit) is untouched in the repo, not deleted —
see its own header comment for what reverting looks like if a fixed `libwlroots` package ever
lands.

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
| 4. `getty@tty1.service` | **Verified** enabled with the autologin override (**inverted** from this step's cage-era behavior, which used to *disable* it) — the plain-Xorg mechanism (`deploy/xorg-kiosk/`) needs a real `agetty --autologin` session on tty1 to launch the GUI via `.bash_profile` → `startx` → `.xinitrc`; `scripts/setup_pi.sh`'s own step 9 is what actually installs this, this step just confirms it didn't drift. | Re-run `scripts/setup_pi.sh`, or see `deploy/xorg-kiosk/README.md` |
| 5. Services | `chatterbox-powerd` enabled **and started** (`setup_pi.sh` already enables it but deliberately doesn't start it). `chatterbox-gui.service` is **not** touched — see step 4, the GUI autostarts via the console login instead of a systemd unit. | `sudo systemctl disable --now chatterbox-powerd` |

Exits non-zero (with a `RESULT: FAIL` summary) if the getty-autologin check or service-start step
failed — review the warnings before rebooting unattended in that case. Safe to re-run: every step
is idempotent.

After a clean run: **`sudo reboot`** and confirm the Pi boots straight into the GUI via tty1's
autologin (briefly shows a text console before `startx` takes over — that's normal, not a stuck
login prompt) with `chatterbox-powerd` running (`systemctl status chatterbox-powerd` over SSH).

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

Deliberately **not** an in-GUI "maintenance mode" button — wifi/bluetooth radios are boot-time
config changes, not runtime toggles, so a GUI button couldn't flip them live anyway (needs a
reboot to take effect), and a kiosk-escape control has real access-control implications (who can
reach it, PIN-gated or not) that haven't been designed. Manual recovery instead:

- **SSH is never disabled by `kiosk_finalize.sh`** — only step 2's `dtoverlay=disable-wifi/-bt`
  are touched, which doesn't affect `sshd`. If the Pi has an **Ethernet** cable connected, SSH in
  over that even with wifi disabled by `config.txt`.
- **To restore wifi/bluetooth**: remove (or comment out) the `dtoverlay=disable-wifi` /
  `dtoverlay=disable-bt` lines from `config.txt` — either restore the `.bak.<timestamp>` file
  `kiosk_finalize.sh` printed the path to at the time, or SSH in and edit `config.txt` by hand —
  then `sudo reboot`. This is a boot-time overlay, not a running-kernel toggle; nothing short of a
  reboot re-enables the radios.
- **To get a plain terminal on the physical screen** (plain-Xorg mechanism, unlike the old cage
  setup — tty1's autologin now `exec`s straight into `startx`, so there's no separate "GUI
  service" to stop): SSH in and temporarily break the autologin→`startx` chain, e.g.
  `mv ~/.bash_profile ~/.bash_profile.disabled && sudo systemctl restart getty@tty1` — the next
  autologin drops to a plain shell instead of launching X. Reverse with
  `mv ~/.bash_profile.disabled ~/.bash_profile && sudo systemctl restart getty@tty1`.
- **No network access at all** (e.g. wifi-only Pi, disabled, no Ethernet handy): pull the SD card,
  edit `config.txt` from another machine, reinsert, boot.

## Mass deployment

Once one Pi 5 has been through `setup_pi.sh` → the full bring-up protocol → `kiosk_finalize.sh` →
a confirmed clean unattended boot, image that SD card rather than repeating all of the above per
unit — see `INSTALL.md` "Mass deployment: golden image".
