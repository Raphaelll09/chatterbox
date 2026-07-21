#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chatterbox-powerd: the power-state daemon (FSM, backlight, amp, inputs, IPC).

See chatterbox-powerd_spec_v0.1.md and docs/power/POWERD.md. Run with
`python3 -m chatterbox.power.daemon`. Pi-only beyond fsm.py/config.py (hardware modules guard
their imports so this package still imports cleanly on a PC dev checkout).
"""
