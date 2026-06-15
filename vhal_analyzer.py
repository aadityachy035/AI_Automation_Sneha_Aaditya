"""
VHAL Analyzer Script
====================
Usage:
    python vhal_analyzer.py

The script will prompt for:
    1. propertyname  - either  "VHAL_<MessageName>"
                         or    "<MessageName>__<SignalName>_rx_v"  /  "_tx_v"
    2. timestamp     - format: MM-DD HH:MM:SS.mmm  (e.g. "06-01 17:50:04.803")
    3. ucl_log_path  - full path to the UCL log file

Outputs produced (in same directory as this script):
    latest_testing.txt       - log lines ±30 s around the timestamp
    test_results_output.json - produced by running latest_test_model.py
    result1.json             - skylark_messages match + test_results_output match
    result2.json             - skylark_signals  match  (isCAN=false)
                               OR output2.json  match  (isCAN=true)
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime, timedelta

# ── Path helpers ────────────────────────────────────────────────────────────────
SCRIPT_DIR            = os.path.dirname(os.path.abspath(__file__))
SKYLARK_MESSAGES_FILE = os.path.join(SCRIPT_DIR, "skylark_messages.json")
SKYLARK_SIGNALS_FILE  = os.path.join(SCRIPT_DIR, "skylark_signals.json")
OUTPUT2_FILE          = os.path.join(SCRIPT_DIR, "output 2.json")
TEST_RESULTS_FILE     = os.path.join(SCRIPT_DIR, "test_results_output.json")
LATEST_TESTING_FILE   = os.path.join(SCRIPT_DIR, "latest_testing.txt")
MODEL_SCRIPT          = os.path.join(SCRIPT_DIR, "latest_test_model.py")
RESULT1_FILE          = os.path.join(SCRIPT_DIR, "result1.json")
RESULT2_FILE          = os.path.join(SCRIPT_DIR, "result2.json")
RESULT3_FILE          = os.path.join(SCRIPT_DIR, "result3.json")
UCL_LOG_PATH          = os.path.join(SCRIPT_DIR, "ucl_90 1.log")

WINDOW_SECONDS = 5   # seconds above and below the target timestamp

# ── Timestamp parsing ────────────────────────────────────────────────────────────
# Log timestamps look like: "06-01 17:50:04.803"
LOG_TS_RE = re.compile(
    r"^\s*(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)"
)

def parse_log_timestamp(ts_str: str) -> datetime | None:
    """Parse 'MM-DD HH:MM:SS.mmm' into a datetime (year=1900, irrelevant)."""
    ts_str = ts_str.strip()
    # Accept both 3-digit and 6-digit milliseconds
    for fmt in ("%m-%d %H:%M:%S.%f", "%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            pass
    return None


def extract_log_window(ucl_log_path: str, target_ts_str: str) -> list[str]:
    """
    Read *ucl_log_path*, find the first line whose timestamp matches
    *target_ts_str* exactly (or nearest), then collect all lines whose
    timestamp is within ±WINDOW_SECONDS.
    Returns the collected lines (as strings, newline stripped).
    """
    target_dt = parse_log_timestamp(target_ts_str)
    if target_dt is None:
        raise ValueError(f"Cannot parse timestamp: {target_ts_str!r}")

    window_delta = timedelta(seconds=WINDOW_SECONDS)
    low_dt  = target_dt - window_delta
    high_dt = target_dt + window_delta

    collected: list[str] = []

    print(f"[1/5] Scanning UCL log: {ucl_log_path}")
    with open(ucl_log_path, "r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\r\n")
            m = LOG_TS_RE.match(line)
            if not m:
                # Lines without a timestamp (e.g. header lines) are included
                # only if we are already inside the window.
                if collected:
                    collected.append(line)
                continue

            line_dt = parse_log_timestamp(m.group(1))
            if line_dt is None:
                if collected:
                    collected.append(line)
                continue

            if low_dt <= line_dt <= high_dt:
                collected.append(line)
            elif line_dt > high_dt and collected:
                # Past the upper window; stop scanning early
                break

    print(f"      Collected {len(collected)} lines in the ±{WINDOW_SECONDS}s window.")
    return collected


# ── File helpers ─────────────────────────────────────────────────────────────────
def load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)

def save_json(path: str, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=4, ensure_ascii=False)
    print(f"      Saved: {path}")


# ── skylark_messages lookup ───────────────────────────────────────────────────────
def find_skylark_message(messagename: str, skylark_messages: list) -> dict | None:
    """Case-insensitive search on 'messagename' field."""
    mn_lower = messagename.lower()
    for entry in skylark_messages:
        if entry.get("messagename", "").lower() == mn_lower:
            return entry
    return None


# ── test_results_output matching ─────────────────────────────────────────────────
def match_test_results(skylark_entry: dict, test_results: list) -> list[dict]:
    """
    Match on serviceid, methodid, direction (type in test_results).
    skylark_messages uses 'service id' and 'method id' (with space).
    test_results_output uses 'serviceId', 'methodId', 'type'.
    """
    svc_id  = skylark_entry.get("service id")
    mth_id  = skylark_entry.get("method id")
    dirn    = skylark_entry.get("direction", "").lower()  # "tx" or "rx"

    matches = []
    for entry in test_results:
        if (
            entry.get("serviceId") == svc_id
            and entry.get("methodId") == mth_id
            and entry.get("type", "").lower() == dirn
        ):
            matches.append(entry)
    return matches


# ── skylark_signals lookup ────────────────────────────────────────────────────────
def find_skylark_signals(messagename: str, skylark_signals: list) -> dict | None:
    """Return the signals entry whose messageName matches (case-insensitive)."""
    mn_lower = messagename.lower()
    for entry in skylark_signals:
        if entry.get("messageName", "").lower() == mn_lower:
            return entry
    return None


# ── output2.json lookup ───────────────────────────────────────────────────────────
def find_output2_entry(direction: str, messagename: str, signalname: str, output2: dict) -> dict | None:
    """
    output2 structure:
        { "rx": { "Skylark": { "<messageName>": { "<signalName>": {...} } } },
          "tx": { ... } }

    direction is 'rx' or 'tx'.
    Returns the inner signal dict if found, else None.
    """
    mn_lower = messagename.lower()
    sn_lower = signalname.lower()

    dir_block = output2.get(direction, {})
    for namespace, messages in dir_block.items():
        for msg_key, signals in messages.items():
            if msg_key.lower() == mn_lower:
                for sig_key, sig_val in signals.items():
                    if sig_key.lower() == sn_lower:
                        return {
                            "namespace": namespace,
                            "messageName": msg_key,
                            "signalName": sig_key,
                            **sig_val
                        }
    return None


# ── Property-name parsing ─────────────────────────────────────────────────────────
VHAL_PREFIX_RE = re.compile(r"^VHAL_(.+)$", re.IGNORECASE)
SIGNAL_RE      = re.compile(r"^(.+?)__(.+?)_(rx|tx)_v$", re.IGNORECASE)


def parse_propertyname(propertyname: str):
    """
    Returns one of:
        ("vhal",   messagename)
        ("signal", messagename, signalname, direction)
    Raises ValueError if the format is unrecognised.
    """
    # Try VHAL_ prefix first
    m = VHAL_PREFIX_RE.match(propertyname)
    if m:
        return ("vhal", m.group(1))

    # Try <messagename>__<signalname>_rx_v or _tx_v
    m = SIGNAL_RE.match(propertyname)
    if m:
        return ("signal", m.group(1), m.group(2), m.group(3).lower())

    raise ValueError(
        f"Unrecognised propertyname format: {propertyname!r}\n"
        "Expected either  'VHAL_<MessageName>'  or  '<MessageName>__<SignalName>_rx_v / _tx_v'"
    )


# ── CAN signal decoding ──────────────────────────────────────────────────────────
def decode_can_signal(payload_str: str, result2_entry: dict) -> dict:
    """
    Decode a single CAN signal from the payload string using metadata in result2_entry.

    Payload format: space-separated hex bytes, e.g. "02 c6 01 ff 1b 2b c1 19 12 02 6c"

    Steps:
      1. Take first 2 bytes → concat → compare with msgid (case-insensitive).
         Return {"skip": "msgid mismatch"} if not matching.
      2. Take 3rd byte (index 2). If not 0x01, return {"skip": "status byte is not 01"}.
      3. Read start_byte (n), start_bit, length from result2_entry.
      4. Target byte index in payload = 3 + n  (skip: 2 msgid + 1 status + n offset).
      5. Convert that byte to 8 bits (MSB-first string, 0-indexed from right means
         bit position = index within that 8-char string counted from right).
      6. Read 'length' bits starting from start_bit downward, spanning extra bytes
         if needed.
      7. Convert bit sequence to int → map to choices.
    Returns a dict with decode results (or a 'skip' key if filtering out).
    """
    raw_bytes = payload_str.strip().split()

    # ── Step 1: msgid check ──────────────────────────────────────────────
    if len(raw_bytes) < 2:
        return {"skip": "payload too short for msgid"}

    payload_msgid = (raw_bytes[0] + raw_bytes[1]).upper()
    expected_msgid = result2_entry.get("msgid", "").upper().replace(" ", "")
    if payload_msgid != expected_msgid:
        return {"skip": f"msgid mismatch (payload={payload_msgid}, expected={expected_msgid})"}

    # ── Step 2: status byte check ────────────────────────────────────────
    if len(raw_bytes) < 3:
        return {"skip": "payload too short for status byte"}

    status_byte = int(raw_bytes[2], 16)
    if status_byte != 0x01:
        return {"skip": f"status byte is 0x{status_byte:02X} (not 0x01), skipping"}

    # ── Step 3: signal metadata ──────────────────────────────────────────
    start_byte = result2_entry.get("start_byte", 0)   # n
    start_bit  = result2_entry.get("start_bit", 0)    # bit position in first byte (from right, 0-indexed)
    length     = result2_entry.get("length", 1)        # total number of bits to read

    # ── Step 4: target byte index ────────────────────────────────────────
    # Layout: [0]=byte0_of_msgid  [1]=byte1_of_msgid  [2]=status  [3..3+n-1]=skipped  [3+n]=first signal byte
    target_idx = 3 + start_byte

    if target_idx >= len(raw_bytes):
        return {"skip": f"payload too short: need index {target_idx}, have {len(raw_bytes)} bytes"}

    # ── Step 5 & 6: bit extraction ───────────────────────────────────────
    # We collect bits as a list (MSB first) of '0'/'1' characters.
    # 'start_bit' is the bit position from the right (0 = LSB) of the first byte.
    # We read from start_bit downward (toward LSB) in the current byte,
    # then continue into subsequent bytes (reading from bit 7 downward) until
    # we have collected 'length' bits total.

    bits_collected = []
    bits_needed    = length
    byte_idx       = target_idx
    current_bit    = start_bit   # bit position from the right in the current byte

    while bits_needed > 0:
        if byte_idx >= len(raw_bytes):
            return {"skip": f"payload too short while reading bits (need {length} bits, ran out at byte {byte_idx})"}

        byte_val = int(raw_bytes[byte_idx], 16)
        # Bits available from current_bit down to 0 in this byte
        bits_in_this_byte = current_bit + 1   # e.g. start_bit=7 → 8 bits available

        if bits_needed <= bits_in_this_byte:
            # All remaining bits are in this byte
            # Extract 'bits_needed' bits from current_bit down to (current_bit - bits_needed + 1)
            low_bit = current_bit - bits_needed + 1
            for b in range(current_bit, low_bit - 1, -1):
                bits_collected.append(str((byte_val >> b) & 1))
            bits_needed = 0
        else:
            # Consume all bits from current_bit down to 0
            for b in range(current_bit, -1, -1):
                bits_collected.append(str((byte_val >> b) & 1))
            bits_needed -= bits_in_this_byte
            # Move to next byte, starting from bit 7
            byte_idx   += 1
            current_bit = 7

    # ── Step 7: convert bits → integer ──────────────────────────────────
    bit_string  = "".join(bits_collected)   # MSB first
    signal_value = int(bit_string, 2)

    # ── Step 8: map to choices ───────────────────────────────────────────
    choices = result2_entry.get("choices", {})
    if choices:
        choice_label = choices.get(str(signal_value))
        if choice_label is None:
            chosen = f"no match for value {signal_value} in choices"
        else:
            chosen = {str(signal_value): choice_label}
    else:
        chosen = "choices is empty"

    return {
        "decoded_bits"  : bit_string,
        "signal_value"  : signal_value,
        "matched_choice": chosen,
    }


def build_result3_can(result1: list, result2) -> list:
    """
    For each entry in result1 where isCAN is True, decode the CAN signal
    using the result2 signal definition and build a result3 document.

    result2 can be:
      - A single dict  (one signal definition)
      - A list of dicts (multiple signal definitions for the same message)

    Returns a list of result3 documents.
    """
    # Normalise result2 to a list so we always iterate
    if isinstance(result2, dict):
        result2_list = [result2]
    elif isinstance(result2, list):
        result2_list = result2
    else:
        print("⚠  result2 has unexpected type; cannot decode CAN signals.")
        return []

    result3 = []

    for idx, entry in enumerate(result1):
        skylark_msg = entry.get("skylark_message", {})
        test_result = entry.get("test_result")

        # Only process isCAN = true entries
        if not skylark_msg.get("isCAN", False):
            continue

        if test_result is None:
            result3.append({
                "note": f"entry {idx}: test_result is None, skipping"
            })
            continue

        payload = test_result.get("payload", "")
        if not payload:
            result3.append({
                "note": f"entry {idx}: payload is empty, skipping"
            })
            continue

        # Decode against every signal definition in result2
        for sig_def in result2_list:
            decode = decode_can_signal(payload, sig_def)

            if "skip" in decode:
                print(f"      [entry {idx}] Skipped: {decode['skip']}")
                continue

            # Build result3 document
            choices_val = sig_def.get("choices", {})

            result3.append({
                "messageName"   : sig_def.get("messageName", ""),
                "signalName"    : sig_def.get("signalName", ""),
                "msgid"         : sig_def.get("msgid", ""),
                "start_byte"    : sig_def.get("start_byte"),
                "start_bit"     : sig_def.get("start_bit"),
                "length"        : sig_def.get("length"),
                "matched_choice": decode["matched_choice"],
                "choices"       : choices_val if choices_val else "empty",
                "isCAN"         : skylark_msg.get("isCAN"),
                "service_id"    : skylark_msg.get("service id"),
                "method_id"     : skylark_msg.get("method id"),
                "direction"     : skylark_msg.get("direction"),
                "payload"       : payload,
                "time"          : test_result.get("time"),
            })

    return result3


# ── Main pipeline ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  VHAL Analyzer")
    print("=" * 65)

    # ── User inputs ──────────────────────────────────────────────────────
    propertyname = input("\nEnter propertyname: ").strip()
    timestamp    = input("Enter timestamp (MM-DD HH:MM:SS.mmm): ").strip()
    ucl_log_path = UCL_LOG_PATH

    if not os.path.isfile(ucl_log_path):
        print(f"\n❌  UCL log not found: {ucl_log_path}")
        sys.exit(1)

    # ── Parse property name ──────────────────────────────────────────────
    try:
        parsed_prop = parse_propertyname(propertyname)
    except ValueError as exc:
        print(f"\n❌  {exc}")
        sys.exit(1)

    prop_type = parsed_prop[0]
    if prop_type == "vhal":
        messagename = parsed_prop[1]
        print(f"\n  Mode       : VHAL prefix")
        print(f"  MessageName: {messagename}")
    else:
        messagename = parsed_prop[1]
        signalname  = parsed_prop[2]
        direction   = parsed_prop[3]
        print(f"\n  Mode       : Signal")
        print(f"  MessageName: {messagename}")
        print(f"  SignalName : {signalname}")
        print(f"  Direction  : {direction}")

    print(f"  Timestamp  : {timestamp}")
    print(f"  UCL Log    : {ucl_log_path}")
    print()

    # ── Step 1: Extract ±30s log window ─────────────────────────────────
    window_lines = extract_log_window(ucl_log_path, timestamp)
    if not window_lines:
        print("⚠  No lines found in the ±5s window. Check the timestamp format and log content.")

    with open(LATEST_TESTING_FILE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(window_lines) + "\n")
    print(f"[1/5] Written {len(window_lines)} lines → {LATEST_TESTING_FILE}")

    # ── Step 2: Run latest_test_model.py ────────────────────────────────
    print(f"\n[2/5] Running model: {MODEL_SCRIPT} …")
    if not os.path.isfile(MODEL_SCRIPT):
        print(f"❌  Model script not found: {MODEL_SCRIPT}")
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, MODEL_SCRIPT],
        cwd=SCRIPT_DIR,
        capture_output=False,   # show output live
    )
    if result.returncode != 0:
        print(f"❌  Model script exited with code {result.returncode}")
        sys.exit(result.returncode)

    if not os.path.isfile(TEST_RESULTS_FILE):
        print(f"❌  Model did not produce {TEST_RESULTS_FILE}")
        sys.exit(1)

    print(f"[2/5] Model finished → {TEST_RESULTS_FILE}")

    # ── Step 3: Load all reference JSON files ───────────────────────────
    print(f"\n[3/5] Loading reference JSON files …")
    skylark_messages = load_json(SKYLARK_MESSAGES_FILE)
    test_results     = load_json(TEST_RESULTS_FILE)
    print(f"      skylark_messages : {len(skylark_messages)} entries")
    print(f"      test_results     : {len(test_results)} entries")

    # ── Step 4: Look up messagename in skylark_messages.json ────────────
    print(f"\n[4/5] Looking up '{messagename}' in skylark_messages.json …")
    skylark_entry = find_skylark_message(messagename, skylark_messages)

    if skylark_entry is None:
        print(f"⚠  '{messagename}' not found in skylark_messages.json")
        print("   result1.json will contain an empty list.")
        result1 = []
    else:
        print(f"      Found: {skylark_entry}")
        is_can = skylark_entry.get("isCAN", False)

        # Match with test_results_output.json on serviceId, methodId, direction
        matched_test = match_test_results(skylark_entry, test_results)
        print(f"      Matched {len(matched_test)} entry/entries in test_results_output.json")

        result1 = [
            {
                "skylark_message": skylark_entry,
                "test_result"    : tr,
            }
            for tr in matched_test
        ] if matched_test else [{"skylark_message": skylark_entry, "test_result": None}]

    save_json(RESULT1_FILE, result1)

    # ── Step 5: Build result2 ────────────────────────────────────────────
    print(f"\n[5/5] Building result2.json …")

    result2 = None

    if skylark_entry is None:
        print("⚠  Cannot build result2 — skylark_messages entry not found.")
        result2 = {"error": f"'{messagename}' not found in skylark_messages.json"}

    elif prop_type == "vhal":
        # VHAL_<MessageName> path
        # If isCAN == false → use skylark_signals.json
        if not is_can:
            skylark_signals = load_json(SKYLARK_SIGNALS_FILE)
            sig_entry = find_skylark_signals(messagename, skylark_signals)
            if sig_entry:
                print(f"      isCAN=false → skylark_signals match: {sig_entry}")
                result2 = sig_entry
            else:
                print(f"⚠  '{messagename}' not found in skylark_signals.json")
                result2 = {"error": f"'{messagename}' not found in skylark_signals.json"}
        else:
            # isCAN == true → for VHAL_ mode we don't have a signalname to look up
            # Inform the user; store the raw skylark_messages entry
            print(f"⚠  isCAN=true for VHAL_ mode — no signal-level lookup performed.")
            result2 = {
                "note": "isCAN is true; signal-level lookup requires a signal-typed propertyname.",
                "skylark_message": skylark_entry,
            }

    else:
        # <MessageName>__<SignalName>_(rx|tx)_v path
        if is_can:
            # isCAN == true → use output 2.json
            output2 = load_json(OUTPUT2_FILE)
            o2_entry = find_output2_entry(direction, messagename, signalname, output2)
            if o2_entry:
                print(f"      isCAN=true → output2.json match found.")
                result2 = o2_entry
            else:
                print(f"⚠  No match in output2.json for msg='{messagename}', sig='{signalname}', dir='{direction}'")
                result2 = {
                    "error": (
                        f"No match in output2.json for messageName='{messagename}', "
                        f"signalName='{signalname}', direction='{direction}'"
                    )
                }
        else:
            # isCAN == false → use skylark_signals.json (by messagename only)
            skylark_signals = load_json(SKYLARK_SIGNALS_FILE)
            sig_entry = find_skylark_signals(messagename, skylark_signals)
            if sig_entry:
                print(f"      isCAN=false → skylark_signals match: {sig_entry.get('messageName')}")
                result2 = sig_entry
            else:
                print(f"⚠  '{messagename}' not found in skylark_signals.json")
                result2 = {"error": f"'{messagename}' not found in skylark_signals.json"}

    save_json(RESULT2_FILE, result2)

    # ── Step 6: Build result3 (isCAN=true CAN signal decode) ────────────
    print(f"\n[6/6] Building result3.json (CAN signal decode) …")

    # Determine if this run is isCAN=true
    is_can_run = skylark_entry is not None and skylark_entry.get("isCAN", False)

    if not is_can_run:
        print("      isCAN=false — result3.json not applicable. Writing empty list.")
        save_json(RESULT3_FILE, [])
    else:
        # Load the result1 and result2 we just produced
        r1 = load_json(RESULT1_FILE)
        r2 = load_json(RESULT2_FILE)
        result3 = build_result3_can(r1, r2)
        print(f"      Produced {len(result3)} decoded signal record(s).")
        save_json(RESULT3_FILE, result3)

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  PIPELINE COMPLETE")
    print("=" * 65)
    print(f"  latest_testing.txt    → {LATEST_TESTING_FILE}")
    print(f"  test_results_output   → {TEST_RESULTS_FILE}")
    print(f"  result1.json          → {RESULT1_FILE}")
    print(f"  result2.json          → {RESULT2_FILE}")
    print(f"  result3.json          → {RESULT3_FILE}")
    print("=" * 65)


if __name__ == "__main__":
    main()
