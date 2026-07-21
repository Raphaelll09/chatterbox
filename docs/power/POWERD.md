# chatterbox-powerd

The kiosk power-state daemon: ACTIVE → DIM → DARK → DEEP, backlight, amplifier SD line, physical
switch/touch activity detection, halt-on-DEEP. Full design: `chatterbox-powerd_spec_v0.1.md`
(repo root). Code: `chatterbox/power/`. Optional — `do_tts.py`/the GUI work exactly as before if
powerd isn't running; see "Integration points" below.

## Running

**On the Pi, via systemd** (the normal path — see `INSTALL.md` "chatterbox-powerd" for the
one-time setup this needs before starting):

```bash
sudo systemctl start chatterbox-powerd chatterbox-gui
journalctl -u chatterbox-powerd -f   # logs
```

**Manually, for testing** (Linux/Pi only — refuses to start on Windows):

```bash
python3 -m chatterbox.power.daemon
```

There is no `chatterbox-powerd` console script — this repo has no `setup.py`/`pyproject.toml`, so
every subsystem here (`tools/monitoring/profiling/sampler.py`, etc.) is `python -m package.module`-
invoked; the systemd unit's `ExecStart` already does this.

Reload config without restarting: `sudo systemctl reload chatterbox-powerd` (or `kill -HUP <pid>`,
or send `{"type":"reload"}` over the socket).

## Configuring: `chatterbox/config/user_prefs.yaml`

| Section | Field | Default | Meaning |
|---|---|---|---|
| `power` | `t_dim_s` / `t_dark_s` / `t_deep_s` | 30 / 180 / 1200 | Idle seconds before DIM/DARK/DEEP. `t_deep_s: 0` or `null` disables the DEEP timer backstop. |
| `power` | `deep_manual_only` | `false` | If `true`, only the `put_away` command reaches DEEP — the timer never does. |
| `display` | `backlight` | `auto` | `auto` = first node under `/sys/class/backlight`, or an explicit node name. |
| `display` | `brightness_active` / `brightness_dim` | 255 / 60 | Clamped to `[1, max_brightness]` (sysfs-read at startup) — never 0, which is "dimmest", not "off". |
| `amp` | `sd_pin` | 23 | BCM pin for the amp SD line — **confirm against your wiring.** |
| `amp` | `enable_active_high` | `true` | `true`: HIGH = amp enabled — **confirm SD polarity on your board.** |
| `amp` | `on_watchdog_s` | 30 | Force amp OFF if left on this long (crashed-playback backstop). |
| `amp` | `settle_ms` / `preroll_ms` / `tail_ms` | 80 / 50 / 50 | Playback-side delays around the amp handshake (see "Integration points"). Not in the original spec's YAML schema — added here since the spec's prose names these timings but didn't give them config keys. |
| `switches` | list of `{pin, action, pull_up, bounce_ms}` | `[]` | Optional physical buttons. `pull_up`/`bounce_ms` default `true`/`50` if omitted. |
| `evdev` | `devices` | `auto` | Auto-detect touch/keyboard, or a list of explicit `/dev/input/*` paths. |
| `socket` | `path` / `group` | `/run/chatterbox/powerd.sock` / `chatterbox` | Client-visible socket location and its group ownership. |

Validation is per-field (`chatterbox/power/config.py`): a missing file, malformed YAML, or one bad
value never crashes the daemon — that one field falls back to its default and a warning is logged;
a totally unparseable file falls back to all defaults. Safe to hand-edit and reload.

## Integration points (how the rest of the app talks to powerd)

- **`chatterbox/audio/playback.py`**: `play_audio()` wraps the actual platform playback with
  `amp_on → await ack → settle+preroll → play → tail → amp_off`
  (`chatterbox/power/client.py`'s shared `get_client()`). If powerd isn't reachable, the amp
  request returns `False` immediately and this reduces to exactly the old, no-powerd behavior —
  no added latency, no exception.
- **`chatterbox/gui/app.py`**: sends `activity` (throttled to ~1/s) on any click/keypress, has a
  "Ranger" (put away) button sending `put_away`, and polls a queue fed by powerd-forwarded switch
  presses (`handle_power_input()` — currently just logs; the actual switch-press→GUI-action
  dispatcher is a separately specced component, not yet implemented).

Both integration points use the **same** `PowerdClient` singleton
(`chatterbox.power.client.get_client()`), since playback and the GUI run in the same process
(`chatterbox/cli.py`).

**v0.1 limitation:** the client does not auto-reconnect. If the initial connection fails, or an
established one drops (e.g. powerd restarts), the client becomes a permanent no-op for the rest of
that process — restart the GUI/CLI process to reconnect.

## Testing

**Runs anywhere (no hardware, no Linux needed)** — pure logic, unit-tested directly:

```bash
.venv/Scripts/python.exe -m pytest tests/test_power_fsm.py tests/test_power_config.py tests/test_power_backlight.py tests/test_power_amp.py tests/test_power_ipc.py -v
```

Covers: FSM state transitions/thresholds/`deep_manual_only` (`fsm.py` has zero hardware imports,
fully fake-injectable), config load/validate/defaults-fallback, backlight node resolution +
brightness clamping (real file I/O against a `tmp_path`, no real sysfs needed), the amp watchdog
decision function, and the socket protocol's message encode/decode framing.

**Needs a real Linux box (unix sockets)**: `test_power_ipc.py` also has a `PowerdServer` +
`PowerdClient` live-loopback test, skipped on Windows
(`@pytest.mark.skipif(sys.platform.startswith("win"))`) — **this repo's dev checkout is Windows,
so that test has only been confirmed to skip cleanly here, not to pass.** Run the full suite on
Linux to actually execute it.

**Needs real Pi 5 hardware — not verifiable from this dev checkout at all** (per the spec's own
§10 test plan, reproduced here for reference):
- Backlight: confirm the resolved sysfs node; measure ON/DIM/OFF power.
- Amp: confirm SD polarity; verify OFF at boot; watchdog forces OFF after `on_watchdog_s`;
  DARK/DEEP force OFF; tune `settle_ms`/`preroll_ms`/`tail_ms` for an inaudible pop.
- DEEP: measure halted power (~0.47 W expected) and wake→interactive boot time; set `t_deep_s`
  from the real number.
- Reliability: kill the GUI mid-synthesis (powerd unaffected); kill playback with amp on (watchdog
  recovers); kill powerd (systemd restarts within `RestartSec`).
- Physical switches / touchscreen / keyboard activity detection end-to-end.

None of the above has been run on real hardware as part of writing this daemon — treat the Pi-side
behavior as implemented-per-spec but hardware-unverified until someone runs it there.
