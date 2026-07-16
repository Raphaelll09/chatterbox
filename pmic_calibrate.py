#!/usr/bin/env python3
"""
pmic_calibrate.py  --  Guided PMIC -> meter power calibration  (Chatterbox / Pi 5)
================================================================================
WHAT IT DOES
  The Pi 5 PMIC reports voltage AND current for each INTERNAL rail, but the 5 V
  input (EXT5V) has voltage only -- so there is no direct "input power" reading.
  Summing V x I over the internal rails gives the Pi's INTERNAL power, which is
  less than the true input power because of:
     * the internal regulators' conversion losses,
     * unmetered chips (RP1, USB, Ethernet),
     * everything outside the Pi (screen, DAC, amplifier) drawing from 5V/GPIO.

  Empirically these follow a linear relation:

        P_meter  =  scale * P_pmic_sum  +  offset

  This script holds several CPU-load states, averages the PMIC sum at each,
  asks you for the matching USB-C meter reading, fits the line, and writes
  profile/calibration.json for the offline join to apply.

--------------------------------------------------------------------------------
CRITICAL -- THE CONFIGURATION MUST NOT CHANGE DURING CALIBRATION
  The 'offset' term absorbs the screen + amplifier + unmetered draw. It is only
  constant if that hardware state is constant. So:
     * screen ON, at the SAME brightness you will use when profiling,
     * amplifier powered, full assembly connected,
     * change ONLY the CPU load between states (this script does that for you).
  Do NOT include a "screen off" point: it changes the offset and corrupts the fit.
  The resulting calibration is valid ONLY for this configuration.

--------------------------------------------------------------------------------
HOW TO USE
  1. SSH into the Pi from another machine (you must be able to read the meter
     while the Pi runs; do not use the Pi's own screen to read this output).
  2. Optional but recommended:   sudo apt install stress-ng
  3. Run:                        python3 pmic_calibrate.py
  4. At each state, wait for the meter reading to settle, then type it in.
  5. The script prints scale/offset and writes profile/calibration.json.
================================================================================
"""

import subprocess
import re
import time
import sys
import os
import json
import shutil

# Rails reported with VOLTAGE ONLY (no current channel) -> cannot yield a power.
EXCLUDE = {"EXT5V", "BATT"}

# Matches e.g.  "VDD_CORE_A current(7)=0.57152000A"
#               "3V7_WL_SW_V volt(8)=3.70441600V"
LINE_RE = re.compile(
    r"\s*(.+?)_([VA])\s+(?:current|volt)\s*\(\s*\d+\s*\)\s*=\s*([\d.]+)"
)

OUT_DIR = "profile"
OUT_PATH = os.path.join(OUT_DIR, "calibration.json")


def pmic_rails():
    """Return {rail_name: power_W} for every rail exposing BOTH V and A."""
    out = subprocess.run(["vcgencmd", "pmic_read_adc"],
                         capture_output=True, text=True).stdout
    volts, amps = {}, {}
    for line in out.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        rail, kind, val = m.group(1), m.group(2), float(m.group(3))
        if rail in EXCLUDE:
            continue
        (volts if kind == "V" else amps)[rail] = val
    # a rail counts only if we have both halves of the V x I product
    return {r: volts[r] * amps[r] for r in volts if r in amps}


def average_pmic(seconds, period=0.5):
    """Average the total PMIC internal power over `seconds`. Returns (mean, per_rail_mean)."""
    totals, acc, n = [], {}, 0
    t_end = time.time() + seconds
    while time.time() < t_end:
        rails = pmic_rails()
        if not rails:
            sys.exit("ERROR: could not parse `vcgencmd pmic_read_adc`. Run it manually to inspect.")
        totals.append(sum(rails.values()))
        for k, v in rails.items():
            acc[k] = acc.get(k, 0.0) + v
        n += 1
        left = t_end - time.time()
        time.sleep(min(period, left) if left > 0 else 0)
    per_rail = {k: v / n for k, v in acc.items()}
    return sum(totals) / len(totals), per_rail


def fit(xs, ys):
    """Least-squares fit y = scale*x + offset. Returns (scale, offset, r2)."""
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        sys.exit("ERROR: all PMIC values identical -- the CPU load did not change. "
                 "Install stress-ng or load the CPU manually.")
    scale = (n * sxy - sx * sy) / denom
    offset = (sy - scale * sx) / n
    ybar = sy / n
    ss_tot = sum((y - ybar) ** 2 for y in ys)
    ss_res = sum((y - (scale * x + offset)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return scale, offset, r2


def ask_float(prompt):
    while True:
        s = input(prompt).strip().replace(",", ".")
        try:
            return float(s)
        except ValueError:
            print("  Please type a number, e.g. 5.73")


def main():
    have_stress = shutil.which("stress-ng") is not None

    print(__doc__.split("HOW TO USE")[0])
    print("Configuration check -- all of these must stay TRUE for the whole run:")
    print("  [ ] screen ON, at the brightness you will profile with")
    print("  [ ] amplifier powered, full assembly connected")
    print("  [ ] nothing else running on the Pi")
    print("  [ ] you can read the USB-C meter (you are on SSH, not the Pi's screen)")
    input("\nPress Enter when all four are true... ")

    if not have_stress:
        print("\nNOTE: stress-ng not found. You will be asked to create CPU load manually.")
        print("      Install it with:  sudo apt install stress-ng\n")

    # (label, number of cores to load)
    states = [("idle (no load)", 0),
              ("CPU load: 1 core", 1),
              ("CPU load: 2 cores", 2),
              ("CPU load: 4 cores", 4)]

    xs, ys, rows = [], [], []

    for i, (label, cores) in enumerate(states, 1):
        print("\n" + "=" * 66)
        print(f"STATE {i}/{len(states)}:  {label}")
        print("=" * 66)

        proc = None
        if cores > 0:
            if have_stress:
                proc = subprocess.Popen(
                    ["stress-ng", "--cpu", str(cores), "--timeout", "120"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"  stress-ng started on {cores} core(s).")
            else:
                print(f"  Start a load on {cores} core(s) in another SSH session, e.g.:")
                print(f"    for i in $(seq {cores}); do (while :; do :; done) & done")
                input("  Press Enter once the load is running... ")

        print("  Settling for 15 s (letting power stabilise)...")
        time.sleep(15)

        print("  Averaging PMIC over 30 s...")
        mean_w, per_rail = average_pmic(30)

        # show the breakdown -- VDD_CORE should climb with load
        core = per_rail.get("VDD_CORE", float("nan"))
        mem = sum(per_rail.get(r, 0.0) for r in ("DDR_VDD2", "DDR_VDDQ", "1V1_SYS"))
        print(f"\n  PMIC internal sum : {mean_w:6.3f} W")
        print(f"    VDD_CORE (CPU)  : {core:6.3f} W")
        print(f"    DDR+1V1 (memory): {mem:6.3f} W")

        meter = ask_float("\n  Read the USB-C meter NOW. Enter its power in W: ")

        xs.append(mean_w)
        ys.append(meter)
        rows.append((label, mean_w, core, mem, meter))

        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            print("  stress-ng stopped.")
        elif cores > 0 and not have_stress:
            input("  Stop your manual load, then press Enter... ")

    # ---------------- fit ----------------
    scale, offset, r2 = fit(xs, ys)

    print("\n" + "=" * 66)
    print("CALIBRATION RESULT")
    print("=" * 66)
    print(f"  P_meter = {scale:.4f} * P_pmic + {offset:.4f}      (R^2 = {r2:.4f})")
    print(f"  implied internal efficiency ~ {100/scale if scale else 0:.1f} %")
    print(f"  implied external+unmetered draw ~ {offset:.2f} W  (screen + amp + RP1/USB/Eth)")

    print("\n  Points and residuals:")
    print(f"  {'state':<20} {'PMIC W':>8} {'CPU W':>7} {'mem W':>7} {'meter W':>8} {'fit W':>8} {'resid':>7}")
    for (label, pm, core, mem, meter) in rows:
        pred = scale * pm + offset
        print(f"  {label:<20} {pm:8.3f} {core:7.3f} {mem:7.3f} {meter:8.3f} {pred:8.3f} {meter-pred:+7.3f}")

    # ---------------- sanity warnings ----------------
    print()
    if r2 < 0.98:
        print("  WARNING: R^2 < 0.98 -- the fit is poor. Did the screen brightness or the")
        print("           amp state change mid-run? Redo with the configuration held fixed.")
    if not (1.0 <= scale <= 2.0):
        print(f"  WARNING: scale = {scale:.2f} is outside the plausible 1.0-2.0 range.")
        print("           Check that the meter reads TOTAL input power, not a sub-rail.")
    if offset < 0:
        print("  WARNING: negative offset is unphysical -- the meter should always read")
        print("           MORE than the internal rails. Check the meter units (W, not V).")

    # ---------------- write json ----------------
    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "scale": round(scale, 6),
        "offset": round(offset, 6),
        "r2": round(r2, 6),
        "note": "P_true = scale * pmic_sum + offset. Valid ONLY for the configuration "
                "calibrated in (screen ON at profiling brightness, amp powered).",
        "points": [{"state": l, "pmic_w": round(p, 4), "meter_w": round(m, 4)}
                   for (l, p, _c, _m, m2) in [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
                   for m in [m2]],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  Written: {OUT_PATH}")
    print("  NOTE: check this matches the schema your join script expects")
    print('        (it should read the "scale" and "offset" keys).')
    print("\n  Also copy the PMIC/meter pairs into the Excel Calibration sheet (B11:C14).")


if __name__ == "__main__":
    main()
