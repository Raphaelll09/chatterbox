# `research/` — L3 STUDY

Everything in this directory exists because Chatterbox is a research project: measuring how fast it
synthesises, how much power it draws, and how the two trade off on a Raspberry Pi 5.

**None of it is needed to make the demonstrator speak.** Delete this directory and
`chatterbox/` still runs — that is a guarantee, not an aspiration, and it is enforced by
`scripts/check_layers.py` and `tests/test_layer_boundary.py`.

## The layer rule

```
chatterbox/  (L1 RUN)     must NEVER import research/
research/    (L3 STUDY)   may import chatterbox/ freely
```

The one thing L1 genuinely needs from profiling — timing marks on the synthesis hot path — reaches
it through `chatterbox/instrumentation.py`, an L1-owned seam whose functions are inert no-ops until
`research.profiling` installs itself into them at import time. That inversion is why the rule holds;
read that module's docstring before changing anything here.

`chatterbox/cli.py` imports this package in five places, all inside functions and all behind a mode
flag (`--profile`, `--benchmark`, `--p4-sweep`, `--join`, `--export-xlsx`). Those are the only
tolerated crossings, they are whitelisted by name in `scripts/check_layers.py`, and the whitelist
applies at function scope only.

## Contents

| Directory | What it does |
|---|---|
| `profiling/` | The instrumentation subsystem. `sampler.py` runs as its own OS process sampling PMIC/CPU/thermal/INA226 into `per_sample.csv`; `recorder.py` writes per-sentence timing marks to `per_sentence.jsonl`; `join.py` merges the two offline into `per_sentence_results.csv` / `per_stage_results.csv`. `parsing.py` holds the `vcgencmd`/sysfs parsers. |
| `benchmark/` | `runner.py` drives the fixed 10-sentence French set in `sentences_fr.jsonl` through the *same* synthesis call as free-text mode. `p4_sweep.py` runs the cadence sweep that fits `P_use(N) = P_idle + k·N`. `export_to_xlsx.py` produces a paste-ready spreadsheet; `compare_runs.py` compares runs across backends. |
| `calibration/` | `pmic_calibrate.py` — guided PMIC→wattmeter calibration wizard. Holds CPU load states, prompts for meter readings, fits the line, writes `calibration.json`. |
| `data/archive/` | Committed historical run data (~40 MB). See `data/README.md`. |

## Running it

Profiling is off by default and costs nothing when off. Enable it per run:

```bash
python3 do_tts.py --profile                    # free text, with instrumentation
python3 do_tts.py --benchmark --repeats 3 --join --export-xlsx
python3 do_tts.py --p4-sweep --cadences 0,1,2,5,10,max --duration 600
```

Standalone entry points, all runnable as modules:

```bash
python3 -m research.profiling.join --profile-dir profile/<run>
python3 -m research.benchmark.export_to_xlsx
python3 -m research.benchmark.compare_runs RUN_A RUN_B --out compare.csv
python3 research/calibration/pmic_calibrate.py
```

Install the optional dependencies with `pip install -e '.[research]'` (adds `openpyxl` for the
spreadsheet export and `smbus2` for the INA226 current monitor). Both are imported lazily, so
their absence disables one feature rather than breaking a run.

## Where output goes

Live runs write to `profile/`, which is **gitignored in its entirety** — it is scratch. Historical
runs worth keeping were moved to `data/archive/`. Do not commit new material into `profile/`;
copy it into `data/archive/` deliberately, with a note saying what it measured.
