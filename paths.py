#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repo-root-anchored path resolution.

Every path below is derived from this file's own location, not the process's current working
directory -- see docs/REORG_PROPOSAL.md, Phase 0. This is a temporary root-level module; it moves
to chatterbox/config/paths.py in Phase 3 of that plan.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FASTSPEECH2_DIR = ROOT / "assets" / "models" / "FastSpeech2"
HIFIGAN_DIR = ROOT / "assets" / "models" / "hifi-gan-master"
WAVEGLOW_DIR = ROOT / "assets" / "models" / "Waveglow"
FLAUBERT_DIR = ROOT / "assets" / "models" / "flaubert" / "flaubert_large_cased"

CUSTOM_REGEX_RULES = ROOT / "custom_regex_rules.csv"
SYMBOLS_REGEX_RULES = ROOT / "symbols_regex_rules.csv"
URL_REGEX_RULES = ROOT / "url_regex_rules.csv"
