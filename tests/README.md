# `tests/` — L3

Pytest suite. Like `research/`, **not required to run the demonstrator** — deleting this directory
leaves a working device.

```bash
.venv/Scripts/python.exe -m pytest tests/         # Windows
python3 -m pytest tests/                          # Linux/Pi
python3 -m pytest tests/test_layer_boundary.py    # just the boundary check
```

No pretrained weights and no Tk instance are needed: synthesis is monkeypatched, GUI widgets are
fake-injected, and the power tests use injected FSM/backlight/amp fakes. The one live unix-socket
test in `test_power_ipc.py` is skipped on Windows.

## What is covered — and what is not

Read this before treating a green run as reassurance.

| Area | Files | Rough share |
|---|---|---|
| Research tooling (profiling, sweeps, exports) | `test_profiling`, `test_p4_sweep`, `test_export_xlsx`, `test_compare_runs`, `test_benchmark` | ~40 % |
| Power daemon | `test_power_*` | ~25 % |
| GUI | `test_gui_*`, `test_i18n`, `test_theme` | ~16 % |
| Synthesis and audio | `test_synth`, `test_backend_describe_controls`, `test_piper_*`, `test_registry_backend_proxy`, `test_audio_postprocess` | ~17 % |
| Layer boundary | `test_layer_boundary` | — |

**Nearly half the suite tests code that is not needed to make the device speak**, and the core
compute path is barely covered: `chatterbox/synth.py` is ~280 lines, and no test executes any of it
past the empty-input guard. Three of `test_synth.py`'s five tests construct an `AudioResult` by
hand and assert on the object they just built — they would pass if `synthesize()` were deleted.

Modules with no dedicated test file: `cli.py`, `gui/app.py` (the largest file in the repository),
`audio/playback.py`, `audio/denoise.py`, `synthesis/subtitles.py`, both backends' text pipelines,
`config/paths.py`.

`conftest.py` puts the repository root on `sys.path`, so the suite tests a **source checkout, never
an installed package** — it cannot catch packaging or path-anchoring regressions.

The full sceptical assessment is in `docs/release/STRUCTURE_AUDIT.md` §8. Historically, real bugs
here passed this suite; one unit test asserted the same wrong return value as the bug it covered.

> **Green pytest tells you the tooling and the state machines still work. It does not tell you the
> device still speaks.** Verify changes to the synthesis path on real hardware.

## `test_layer_boundary.py`

The exception to the above: it tests something the suite genuinely can prove. Two checks — a static
AST walk (via `scripts/check_layers.py`) and a dynamic one that removes the `research` package from
`sys.meta_path` and imports each runtime module for real. It also asserts that the checker itself
fails on a planted violation, so it cannot silently degrade into a test that always passes.
