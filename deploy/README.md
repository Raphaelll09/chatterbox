# `deploy/` — Raspberry Pi 5 deployment

What turns a Pi into the kiosk. Installed by `scripts/setup_pi.sh`; see `INSTALL.md` for the
procedure and `docs/KIOSK.md` for how the kiosk actually boots.

| Path | What it is |
|---|---|
| `systemd/chatterbox-powerd.service` | Unit for the power daemon (`python3 -m chatterbox.power.daemon`). `setup_pi.sh` installs and enables it, but does not start it. **The only unit shipped** — the GUI autostarts via console login, not systemd. |
| `audio/asound.conf` | Pins ALSA's system-default output to the IQaudio DAC. Copied to `/etc/asound.conf` by `setup_pi.sh` step 10. Without it, ALSA's bare `default` resolves to the onboard HDMI/headphone output and nothing comes out of the real speaker. **Hardcodes the card name `IQaudIODAC`** — edit it for a different DAC. |
| `xorg-kiosk/` | The **current** kiosk autostart mechanism: plain Xorg, no compositor. |
| `xorg-kiosk/xinitrc` | Launches the GUI as the X session. |
| `xorg-kiosk/bash_profile_snippet.sh` | Starts X on tty1 login. |
| `xorg-kiosk/getty-tty1-autologin.conf` | `agetty --autologin` drop-in. |

## Why plain Xorg and not a Wayland compositor

The finalised design used `cage` (a kiosk Wayland compositor), and there was a
`chatterbox-gui.service` unit for it. Real Pi 5 bring-up hit a **reproducible SIGSEGV inside the
Raspberry Pi Foundation's own `libwlroots` build**, with no fixed package available. Plain Xorg
plus a console autologin replaced it. The cage unit was deleted in the release reorganisation; the
full account is in `xorg-kiosk/README.md` and `docs/KIOSK.md`.

## Manual steps these files do not perform

1. **Paths and user.** The unit defaults to the `chatterbox` account and
   `/home/chatterbox/chatterbox`. A different user or clone location means editing the installed
   copy under `/etc/systemd/system/`, then `systemctl daemon-reload` — and separately the hardcoded
   paths in `~/.xinitrc` and the `getty@tty1` override.
2. **Hardware confirmation.** `chatterbox/config/user_prefs.yaml`'s `amp.sd_pin`,
   `amp.enable_active_high` and `display.backlight` must match the board's wiring. Wrong values
   **fail silently** — powerd logs and disables that one control rather than crashing.
3. **Verify in the foreground first.** Run `chatterbox-powerd` and `do_tts.py --gui` by hand before
   enabling anything via systemd.

`scripts/kiosk_finalize.sh` is the opt-in last step, run only once a Pi has passed bring-up: it
disables `getty@tty1`, tunes `config.txt`/`cmdline.txt` (backed up, idempotent), and enables the
units. It never touches EEPROM beyond a read-only check.
