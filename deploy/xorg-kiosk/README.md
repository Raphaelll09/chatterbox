# Plain-Xorg kiosk fallback

**Current default deployment path** — not the originally-finalized choice. `docs/kiosk/KIOSK.md`
documents `cage` (a Wayland kiosk compositor) as the compositor decision reached during the
power/GUI workstream, and `deploy/systemd/chatterbox-gui.service` still reflects that choice. Real
Pi5 hardware bring-up (2026-07-31, `docs/context/CHANGELOG.md`) found a reproducible SIGSEGV deep
inside `libwlroots` (Raspberry Pi Foundation's own `0.18.2-3+rpt4` build), triggered by essentially
any input event causing a seat/focus signal — confirmed via `coredumpctl`, backtrace bottoms out in
`wl_signal_emit_mutable` inside `libwlroots-0.18.so`, not in any chatterbox code, `cage`'s own
logic, or the XWayland version (reproduced identically on `22.1.9` and `24.1.6`). No newer wlroots
package is available in either the Raspberry Pi or Debian repos as of that date. Since Tk only ever
needs X11 — it doesn't care whether that X11 comes via XWayland-under-cage or a plain Xorg session
— this fallback sidesteps `wlroots` entirely instead of chasing an upstream fix.

**If a fixed `libwlroots` package ever lands**: reverting to `cage` means re-enabling
`chatterbox-gui.service` (`deploy/systemd/`), removing the 3 files this directory installs, and
restoring `getty@tty1`'s stock (non-autologin) config. Neither path is deleted; both coexist in the
repo.

## Why plain Xorg needs a *real* login session, not a systemd `TTYPath=`/`PAMName=login` unit

The very first attempt kept `chatterbox-gui.service`'s existing systemd pattern, just swapping
`ExecStart` from `cage -s -- ...` to `startx`. That mostly worked but was measurably flakier than a
real console login (`Couldn't get a file descriptor referring to the console` X errors, `tty`
reporting "not a tty" inside the launched process) — systemd's `TTYPath=`/`PAMName=login` mechanism
is designed for Wayland compositors managing their own seat via logind, not legacy X11's own
console/VT ownership expectations. Switching to a genuine `agetty --autologin` session (this
directory's actual mechanism) fixed both issues outright — this matches
`chatterbox-gui.service`'s own comment, which already anticipated this exact fallback.

## Files

- **`getty-tty1-autologin.conf`** → `/etc/systemd/system/getty@tty1.service.d/override.conf`.
  Makes `agetty` auto-login as `chatterbox` on tty1 instead of showing a login prompt.
- **`xinitrc`** → `~/.xinitrc` (chatterbox user's home, **not** the repo clone). `startx`/`xinit`
  exec this automatically when given no client argument on its own command line — deliberately
  *not* passed on the command line (`startx <client> <args>`), since `startx`'s own shell-script
  argument parsing measurably mangled a multi-word client command during testing. Two things this
  file exists to get right, both found the hard way on real hardware:
  1. `cd`s into the repo clone directory first — `chatterbox/cli.py` loads `config_tts.yaml` via a
     path relative to the process's current working directory, which a bare login shell does not
     default to; omitting this produces a `FileNotFoundError` before any window ever appears.
  2. Runs `python3 -u` (unbuffered) and redirects stdout/stderr to a log file — without `-u`,
     output written to a *file* (not a tty) is fully buffered, so a process killed by a signal
     loses whatever traceback was sitting in that buffer, making a real crash look like total
     silence.
- **`bash_profile_snippet.sh`** → appended to `~/.bash_profile`. On a real tty1 login with no
  `$DISPLAY` set, `exec startx -- -keeptty`. `-keeptty` avoids Xorg's own `Couldn't get a file
  descriptor referring to the console` error when it doesn't need to do its own VT-switch
  console ioctls (already attached to the right tty via the real login session above).

## Also required, not in this directory

- **`/etc/X11/Xwrapper.config`**: `allowed_users=console` (Debian's default, requires Xorg's
  wrapper to recognize the session as a genuine console login) → `allowed_users=anybody`. Acceptable
  relaxation for a single-purpose embedded kiosk device, not a shared multi-user system. Applied by
  `scripts/setup_pi.sh`.
- **`xserver-xorg`, `xinit`, `x11-xserver-utils`** (`apt-packages-pi.txt`) — the actual X server,
  `startx`/`xinit`, and `xrandr` (used during bring-up to confirm the real screen resolution/output
  config, not required at runtime but small and useful for future debugging).
- **A stale `/tmp/.X0-lock` / `/tmp/.X11-unix` left over from a killed X session blocks the next
  start** (`Fatal server error: Server is already active for display 0`) — not handled by any
  script here, since a clean reboot already clears `/tmp` (tmpfs). If debugging manually without a
  reboot: `sudo rm -f /tmp/.X0-lock && sudo rm -rf /tmp/.X11-unix`.

## The other real bugs found during this same bring-up (already fixed in the codebase, not just this deploy mechanism)

- `chatterbox/gui/settings.py`'s Settings `Toplevel` called `grab_set()` with no preceding
  `wait_visibility()` — harmless `TclError` on a desktop Xorg session, but crashed this Pi's
  `cage`/XWayland stack outright (a red herring at the time — fixed, real, but not *the* wlroots
  bug above; both were live simultaneously and had to be separated).
- `chatterbox/gui/app.py`'s fullscreen fallback (`-zoomed` / `-fullscreen`) assumed a `TclError`
  from `-zoomed` reliably signals "no window manager, fall back to explicit geometry" — false under
  a *bare* Xorg session with zero window manager at all: `-zoomed` "succeeds" from Tk's own point
  of view with nothing there to actually enforce it, so the explicit-geometry fallback never ran,
  leaving the window at Tk's natural widget-sizing default (visibly narrower than the real 800x480
  screen). Fixed by always applying the explicit, screen-matching geometry as a baseline.
