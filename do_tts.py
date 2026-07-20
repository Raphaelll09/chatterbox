#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point -- kept at the repo root so `python3 do_tts.py [flags]` (and the Claude Code plugin
that wraps it) keeps working unchanged. Real logic lives in chatterbox/cli.py (Phase 3,
docs/REORG_PROPOSAL.md)."""
import chatterbox.cli as cli

if __name__ == "__main__":
    cli.main()
