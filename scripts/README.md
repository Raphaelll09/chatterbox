# `scripts/` — provisioning and maintenance

Shell and Python entry points that are run by hand, never imported.

| Script | What it does | When |
|---|---|---|
| `setup_pi.sh` | Provisions a fresh Raspberry Pi 5: apt packages, venv, Python requirements, the powerd systemd unit, the Xorg kiosk autostart. | Once, on a new board. See `INSTALL.md`. |
| `fetch_piper_voices.sh` | Downloads the three Piper voices into `assets/models/Piper/`, verifying each against a recorded sha256. Safe to re-run — skips files that already match. | When using the Piper backend. |
| `kiosk_finalize.sh` | **Opt-in**, run only after a Pi has passed bring-up: disables `getty@tty1`, tunes `config.txt`/`cmdline.txt` (backed up, idempotent), enables and starts the units. Never writes EEPROM. | Last step of a kiosk build. |
| `check_layers.py` | Fails if `chatterbox/` (L1) imports `research/` (L3). Also run by `tests/test_layer_boundary.py`. | CI, and before any commit that moves code between layers. |

Both shell scripts resolve their own location and derive the repository root from it, so they can
be run from anywhere. `check_layers.py` chdirs to the repository root itself.

```bash
./scripts/setup_pi.sh
./scripts/fetch_piper_voices.sh
python3 scripts/check_layers.py     # exit 0 = boundary intact
```

Note: `setup_pi.sh` refers to `requirements-pi-lock.txt` (a `pip freeze` of a known-good Pi
install). That file is not currently in the repository — generate it after a successful install if
you want a reproducible pin set.
