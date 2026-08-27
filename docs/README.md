# `docs/` — documentation index

Split by who needs it.

## Running and understanding the software

| Document | Read it when |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | You want the whole picture: pipeline stages, model registry, state handling. Note its module paths predate the release reorganisation in places. |
| [GUI.md](GUI.md) | Working on the Tkinter interface — threading model, worker contract, manual smoke tests that need real weights. |
| [KIOSK.md](KIOSK.md) | Setting up the Pi as a kiosk: the plain-Xorg autostart mechanism and why cage/wlroots was abandoned. |
| [POWERD.md](POWERD.md) | Working on `chatterbox-powerd` — the power state machine, IPC protocol, hardware control. |

The backend contract lives next to the code it governs:
[`chatterbox/synthesis/README.md`](../chatterbox/synthesis/README.md).

## Research

| Document | Contents |
|---|---|
| [research/CHANGELOG.md](research/CHANGELOG.md) | The development log. Long, detailed, and the authoritative record of why things are the way they are. |
| [research/INTERCHANGEABLE_BACKENDS.md](research/INTERCHANGEABLE_BACKENDS.md) | Write-up of the backend abstraction and what the Piper integration proved about it. |
| [research/PIPER_INTEGRATION_SUMMARY.md](research/PIPER_INTEGRATION_SUMMARY.md) | The Piper backend integration. |
| [research/reference-audio/](research/reference-audio/) | Reference recordings used for crest-factor and operating-level comparison. Not loaded at runtime. |
| [research/history/](research/history/) | Superseded planning documents, kept for provenance. |

## Release

| Document | Contents |
|---|---|
| [release/STRUCTURE_AUDIT.md](release/STRUCTURE_AUDIT.md) | Full read-only audit of the repository as of 2026-08-17, ahead of open-sourcing. |
| [release/REORG_PLAN.md](release/REORG_PLAN.md) | The reorganisation plan derived from it, with the follow-up work not yet done. |

Both are **dated records of the pre-reorganisation state**. Their paths deliberately were not
rewritten when the tree moved — they describe the repository as it was when audited.

## Missing documents

Several specification documents are referenced from code docstrings and from `INSTALL.md` but are
not in this repository: `chatterbox_gui_spec_v0.1.md`, `chatterbox-powerd_spec_v0.1.md`,
`Bring-up_Integration_Test_Protocol_v0.1.md`, and three `cc_prompt_*.md` planning documents.
`INSTALL.md` sends installers to the bring-up protocol as the procedure that catches silent
hardware failures, so this is a real gap. Tracked as F10 in
[release/REORG_PLAN.md](release/REORG_PLAN.md).
