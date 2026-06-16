import json
import os

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
INPUT_FILE = os.path.join(os.path.dirname(__file__), "output 2.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "signal_names.txt")

# ─────────────────────────────────────────────
# LOAD JSON
# ─────────────────────────────────────────────
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

signal_names = []

# ─────────────────────────────────────────────
# EXTRACT SIGNALS
# JSON structure:
#   { "<direction>": { "<variant>": { "<ECU>": { "<Signal>": {...} } } } }
#
# Naming format:   <ECU>__<Signal>_<direction>_v
#   e.g.  AT5__TxmnOverheatedAT_rx_v
# ─────────────────────────────────────────────
for direction, variants in data.items():           # "rx", "tx", etc.
    for variant, ecus in variants.items():         # "Skylark", etc.
        for ecu, signals in ecus.items():          # "AT5", "BCM5", etc.
            for signal_name in signals.keys():     # "TxmnOverheatedAT", etc.
                formatted = f"{ecu}__{signal_name}_{direction}_v"
                signal_names.append(formatted)

# ─────────────────────────────────────────────
# PRINT & SAVE
# ─────────────────────────────────────────────
print(f"[OK]  Total signals found: {len(signal_names)}\n")
for name in signal_names:
    print(name)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(signal_names))

print(f"\n[SAVED]  Saved to: {OUTPUT_FILE}")
