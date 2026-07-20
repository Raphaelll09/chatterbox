#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repo-root-anchored path resolution.

Every path below is derived from this file's own location, not the process's current working
directory -- see docs/REORG_PROPOSAL.md, Phase 0. Lives at chatterbox/config/paths.py (two levels
under the repo root) as of Phase 3 -- ROOT below accounts for that nesting explicitly. If this file
moves again, update the parent count here first, before anything else: an off-by-one here breaks
every path in this module silently (see Phase 2's _PACKAGE_ROOT bug in
tools/monitoring/profiling/__init__.py for exactly this failure mode).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FASTSPEECH2_DIR = ROOT / "assets" / "models" / "FastSpeech2"
HIFIGAN_DIR = ROOT / "assets" / "models" / "hifi-gan-master"
WAVEGLOW_DIR = ROOT / "assets" / "models" / "Waveglow"
FLAUBERT_DIR = ROOT / "assets" / "models" / "flaubert" / "flaubert_large_cased"

_RULES_DIR = ROOT / "chatterbox" / "synthesis" / "backends" / "fastspeech2_hifigan" / "rules"
CUSTOM_REGEX_RULES = _RULES_DIR / "custom_regex_rules.csv"
SYMBOLS_REGEX_RULES = _RULES_DIR / "symbols_regex_rules.csv"
URL_REGEX_RULES = _RULES_DIR / "url_regex_rules.csv"

# audio_keyboards/ hasn't moved yet (planned for Phase 4's assets/audio/prompts/ relocation) --
# anchored here now so gui_utils.py stops hardcoding the bare relative folder name.
AUDIO_KEYBOARDS_DIR = ROOT / "audio_keyboards"
