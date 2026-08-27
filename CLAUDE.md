# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

This file used to duplicate the repository's structure and architecture. It no longer does — that
material drifted out of date twice, which is exactly the failure this split avoids. **Structure now
lives in one place**, and this file holds only what an agent needs *in addition* to it.

## Read these first

| Read | For |
|---|---|
| **[`docs/CODEMAP.md`](docs/CODEMAP.md)** | **Start here.** Where the code for X lives, which language governs which aspect, the invented syntaxes, the invariants, the "I want to change X" index, the key-symbol table |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How a subsystem works internally |
| [`chatterbox/synthesis/README.md`](chatterbox/synthesis/README.md) | The backend contract — required before touching any backend |
| [`README.md`](README.md) | Install, run modes, CLI flags, the GUI, maintenance |
| [`docs/research/CHANGELOG.md`](docs/research/CHANGELOG.md) | Why something is the way it is. Grep it; do not read it front to back |

`docs/CODEMAP.md` is verified by `tests/test_codemap.py` — its paths and symbol names are checked
against the code, so trust it over any recollection.

## The one rule that must not break

```
chatterbox/  (L1 RUN)    must NEVER import research/  (L3 STUDY)
research/                may import chatterbox/ freely
```

Deleting `research/` and `tests/` must leave a working demonstrator. The only bridge is
`chatterbox/instrumentation.py`, an inert seam that `research.profiling` installs itself into.

Enforced by `scripts/check_layers.py` and `tests/test_layer_boundary.py`. If you need profiling
from L1, add a passthrough to `instrumentation.py` — never an `import research.*` in `chatterbox/`.

## Working here

- **Run commands from the repository root.** Model paths in `config_tts.yaml` are relative to the
  working directory.
- **Python invocation:** bare `python`/`python3` resolve to the Windows Store stub on this checkout.
  Use `.venv/Scripts/python.exe` (Windows) or activate the venv.
- **Before committing:** `python3 -m pytest tests/` and `python3 scripts/check_layers.py`.
- **Green tests do not mean the device speaks.** Synthesis is mocked throughout; `chatterbox/synth.py`
  has no test executing it past the empty-input guard. Changes to the synthesis path need real
  hardware verification. See [`tests/README.md`](tests/README.md).
- **Do not add a second compute path.** CLI and GUI both call `chatterbox.synth.synthesize()`.
- **Keep dependencies minimal** — this targets an embedded Pi 5, not a workstation.
- **Instrumentation is opt-in and off by default**, mirroring the `postprocess.enabled` pattern.

## Documentation ownership

One fact, one place. When something changes, update the owning document only:

| Owns | Document |
|---|---|
| Where code lives, key symbols, tasks | `docs/CODEMAP.md` |
| How subsystems work | `docs/ARCHITECTURE.md` |
| The backend contract | `chatterbox/synthesis/README.md` |
| Install / run / GUI / maintenance | `README.md` (English), `README.fr.md` (French reference) |
| Per-directory orientation | that directory's `README.md` |
| History and rationale | `docs/research/CHANGELOG.md` |
| The pre-release audit and its follow-ups | `docs/release/` — **dated records, do not update** |

## After completing a change

1. Append a `docs/research/CHANGELOG.md` entry (template at the top of that file).
2. Update `docs/CODEMAP.md` if you added, moved or renamed a key symbol — `tests/test_codemap.py`
   will fail if you don't.
3. Update the owning document from the table above if behaviour changed.

## Accuracy

Treat existing documentation as evidence, not proof, and verify claims against the code. Two
documented "facts" turned out to be false: `chatterbox/synthesis/base.py` was described as the
operative backend contract while nothing imported, subclassed or constructed it, and `§` was
documented as the sub-utterance separator while the code split on `|`. Both had stood for months.
Where a document and the code disagree, the code wins — then fix the document.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
