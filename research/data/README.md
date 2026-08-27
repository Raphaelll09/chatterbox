# `research/data/` — archived measurement runs

Committed historical output from profiled runs. **Archive material: read-only, never overwritten.**

Live runs do *not* write here. They write to `profile/` at the repository root, which is gitignored
in its entirety. Material that is worth keeping gets copied into `archive/` deliberately.

## Why these are committed at all

They are the evidence behind the power and latency figures in `docs/research/CHANGELOG.md`. Each
run directory is named exactly as the development log refers to it — including the spaces, which is
why they were not renamed to something more script-friendly.

## `archive/`

| Run | What it measured |
|---|---|
| `P4 - First Full try/`, `P4 - Second Full try/` | Cadence sweeps fitting `P_use(N) = P_idle + k·N`, at 0/1/2/5/10/max utterances per minute. Two passes ~40 min apart in the same configuration, to check drift. |
| `Step 7B - 2/`, `- 3/`, `- 4/` | Repeated benchmark passes over the fixed 10-sentence set. |
| `Step 7C - ondemand 257mWh/`, `- performance 275mWh/` | The same workload under two CPU governors. The energy figure is in the directory name. |
| `Step 7D - 1 try/`, `- 2 try 490mWh/` | Later full passes with playback enabled. |

## Files in a run directory

| File | Written by | Contents |
|---|---|---|
| `meta.json` | `research/profiling` at session start | Governor, sample rates, host/platform, calibration in force |
| `per_sample.csv` | `research/profiling/sampler.py` | Background time series: PMIC power, CPU load/frequency, temperature, INA226 amp branch |
| `per_sentence.jsonl` | `research/profiling/recorder.py` | One record per synthesised sentence: stage timings, character/word counts, audio duration |
| `per_sentence_results.csv` | `research/profiling/join.py` | The two above joined: energy, mean/peak power, RTF per sentence |
| `per_stage_results.csv` | `research/profiling/join.py` | Same, split by pipeline stage (tts / vocoder / denoiser) |
| `sweep_summary.csv`, `calibration.json` | `p4_sweep.py`, `pmic_calibrate.py` | Sweep fit results; the PMIC→wattmeter calibration used |
| `*.xlsx` | `export_to_xlsx.py` | Paste-ready spreadsheet export |
| `sampler.pid` | sampler | Stale process id. Harmless leftover, kept only because it was part of the original run. |

## Reading a run

```bash
python3 -m research.profiling.join --profile-dir "research/data/archive/Step 7B - 2"
python3 -m research.benchmark.compare_runs \
    "research/data/archive/Step 7C - ondemand 257mWh" \
    "research/data/archive/Step 7C - performance 275mWh" --out compare.csv
```

**Caveat on the power numbers.** PMIC readings are a proxy, recalibrated against an external
wattmeter via `calibration.json`. That calibration's `offset` term absorbs the screen, amplifier
and unmetered chips, so it is only valid for the exact hardware configuration it was captured in.
Comparing runs calibrated under different configurations is not meaningful. See
`research/calibration/pmic_calibrate.py`.
