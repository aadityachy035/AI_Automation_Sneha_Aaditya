"""
accuracy_test.py  –  Accuracy checker for SOME/IP model parsing
================================================================
Reads every SOME/IP line from latest_testing.txt,
extracts the 5 ground-truth fields using regex,
then looks up in test_results_output_batch.json using a
COMPOSITE KEY: (timestamp + type + serviceId + methodId)

Matching strategy (3 levels):
  Level 1  →  Exact match on all 4 identity fields → only check payload
  Level 2  →  Timestamp matches but serviceId/methodId/type differ → show what's wrong
  Level 3  →  Timestamp not found at all → entry completely missing from model output

Usage:
    python accuracy_test.py
"""

import re
import json
import os
from collections import defaultdict

# ==============================================================================
INPUT_TXT_FILE   = "latest_testing.txt"
INPUT_JSON_FILE  = "test_results_output_batch.json"
# ==============================================================================

# ── Regex to parse ground truth from raw SOME/IP log lines ───────────────────
RX_RE = re.compile(
    r'(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)'       # group 1: timestamp
    r'.*?SomeipCOmm :: RX Message'
    r'.*?service:([0-9a-fA-F]+)\s*'                # group 2: serviceId (hex)
    r',Method:([0-9a-fA-F]+)'                       # group 3: methodId  (hex)
    r',payload:(.*)',                                # group 4: payload
    re.IGNORECASE
)

TX_RE = re.compile(
    r'(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)'       # group 1: timestamp
    r'.*?TX Message SomeipComm::send'
    r'.*?service:(\d+)'                             # group 2: serviceId (decimal)
    r',method:(\d+)'                                # group 3: methodId  (decimal)
    r',\s*response Payload:\s*(.*)',                # group 4: payload
    re.IGNORECASE
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def normalize_payload(raw: str) -> str:
    """Lowercase, strip trailing space, collapse multiple spaces → single space."""
    return " ".join(str(raw).strip().lower().split())


def get_ts(entry: dict) -> str:
    for key in ("time", "timestamp", "Time", "Timestamp"):
        if key in entry:
            return entry[key]
    return ""


def composite_key(time: str, msg_type: str, service_id: int, method_id: int) -> tuple:
    """Unique identity key for one SOME/IP message."""
    return (time, msg_type.lower(), service_id, method_id)


def extract_ground_truth(line: str) -> dict | None:
    """Extract 5 ground truth fields from a raw log line. Returns None if not SOME/IP."""
    m = RX_RE.search(line)
    if m:
        return {
            "time"      : m.group(1).strip(),
            "type"      : "rx",
            "serviceId" : int(m.group(2).strip(), 16),   # hex → decimal
            "methodId"  : int(m.group(3).strip(), 16),   # hex → decimal
            "payload"   : normalize_payload(m.group(4)),
        }
    m = TX_RE.search(line)
    if m:
        return {
            "time"      : m.group(1).strip(),
            "type"      : "tx",
            "serviceId" : int(m.group(2).strip()),        # already decimal
            "methodId"  : int(m.group(3).strip()),        # already decimal
            "payload"   : normalize_payload(m.group(4)),
        }
    return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("  SOME/IP ACCURACY TEST")
    print("  Match key: timestamp + type + serviceId + methodId")
    print("=" * 72)

    # ── Load ground truth from log file ───────────────────────────────────────
    if not os.path.exists(INPUT_TXT_FILE):
        print(f"❌ Not found: {INPUT_TXT_FILE}"); return
    with open(INPUT_TXT_FILE, "r", encoding="utf-8") as f:
        raw_lines = [l.strip() for l in f if l.strip()]

    gt_list = [extract_ground_truth(l) for l in raw_lines]
    gt_list = [g for g in gt_list if g]   # drop None (non-SOME/IP)

    print(f"  Log file     : {INPUT_TXT_FILE}")
    print(f"  Total lines  : {len(raw_lines)}")
    print(f"  SOME/IP found: {len(gt_list)}")

    # ── Load model JSON output ─────────────────────────────────────────────────
    if not os.path.exists(INPUT_JSON_FILE):
        print(f"❌ Not found: {INPUT_JSON_FILE}"); return
    with open(INPUT_JSON_FILE, "r", encoding="utf-8") as f:
        model_list = json.load(f)

    print(f"  Model output : {INPUT_JSON_FILE}")
    print(f"  Model parsed : {len(model_list)} entries")
    print("=" * 72)

    # ── Build two lookups from model output ───────────────────────────────────
    # 1. Composite key → entry (for exact identity match)
    model_by_composite = {}
    # 2. Timestamp      → list of entries (for fallback mismatch reporting)
    model_by_time      = defaultdict(list)

    for entry in model_list:
        ts   = get_ts(entry)
        mtyp = str(entry.get("type", "")).lower()
        sid  = entry.get("serviceId", None)
        mid  = entry.get("methodId",  None)
        if ts and sid is not None and mid is not None:
            ck = composite_key(ts, mtyp, sid, mid)
            model_by_composite[ck] = entry
        if ts:
            model_by_time[ts].append(entry)

    # ── Compare each ground truth entry ───────────────────────────────────────
    level1_correct   = 0   # composite match + payload correct
    level1_wrong_pay = 0   # composite match but payload wrong
    level2_mismatch  = 0   # timestamp found, identity fields wrong
    level3_missing   = 0   # timestamp not in model output at all

    for idx, gt in enumerate(gt_list):
        ts  = gt["time"]
        ck  = composite_key(ts, gt["type"], gt["serviceId"], gt["methodId"])

        # ── Level 1: Composite key match ──────────────────────────────────────
        if ck in model_by_composite:
            model_entry    = model_by_composite[ck]
            model_payload  = normalize_payload(str(model_entry.get("payload", "")))
            gt_payload     = gt["payload"]

            if gt_payload == model_payload:
                level1_correct += 1   # ✅ perfect match
            else:
                level1_wrong_pay += 1
                print(f"\n{'─' * 72}")
                print(f"  ⚠  PAYLOAD MISMATCH  |  Timestamp: {ts}")
                print(f"     type      : {gt['type']}  "
                      f"serviceId: {gt['serviceId']}  "
                      f"methodId: {gt['methodId']}")
                print(f"     Expected  : {gt_payload[:80]}"
                      + ("..." if len(gt_payload) > 80 else ""))
                print(f"     Got       : {model_payload[:80]}"
                      + ("..." if len(model_payload) > 80 else ""))
            continue

        # ── Level 2: Timestamp found but identity fields differ ───────────────
        if ts in model_by_time:
            level2_mismatch += 1
            print(f"\n{'─' * 72}")
            print(f"  ❌ IDENTITY MISMATCH  |  Timestamp: {ts}")
            print(f"     Ground truth:")
            print(f"       type      = {gt['type']}")
            print(f"       serviceId = {gt['serviceId']}")
            print(f"       methodId  = {gt['methodId']}")
            print(f"       payload   = {gt['payload'][:60]}"
                  + ("..." if len(gt['payload']) > 60 else ""))
            print(f"     Model output(s) at this timestamp:")
            for me in model_by_time[ts]:
                mp = normalize_payload(str(me.get("payload", "")))
                print(f"       type      = {me.get('type', '?')}"
                      + ("  ✅" if str(me.get("type","")).lower() == gt["type"] else "  ❌"))
                print(f"       serviceId = {me.get('serviceId', '?')}"
                      + ("  ✅" if me.get("serviceId") == gt["serviceId"] else "  ❌"))
                print(f"       methodId  = {me.get('methodId', '?')}"
                      + ("  ✅" if me.get("methodId") == gt["methodId"] else "  ❌"))
                print(f"       payload   = {mp[:60]}"
                      + ("..." if len(mp) > 60 else "")
                      + ("  ✅" if mp == gt["payload"] else "  ❌"))
            continue

        # ── Level 3: Timestamp not in model output at all ─────────────────────
        level3_missing += 1
        print(f"\n{'─' * 72}")
        print(f"  ❌ MISSING ENTIRELY  |  Timestamp: {ts}")
        print(f"     Expected: type={gt['type']}  "
              f"serviceId={gt['serviceId']}  methodId={gt['methodId']}")
        print(f"     payload : {gt['payload'][:60]}"
              + ("..." if len(gt['payload']) > 60 else ""))

    # ── Summary ───────────────────────────────────────────────────────────────
    total_matched = level1_correct + level1_wrong_pay
    total_errors  = level1_wrong_pay + level2_mismatch + level3_missing

    print(f"\n\n{'=' * 72}")
    print("  ACCURACY REPORT")
    print(f"{'=' * 72}")
    print(f"  Ground truth SOME/IP lines  : {len(gt_list)}")
    print(f"{'─' * 72}")
    print(f"  ✅ Exact match (all 5 fields): {level1_correct:<4}  "
          f"← timestamp + type + serviceId + methodId + payload all correct")
    print(f"  ⚠  Payload mismatch only    : {level1_wrong_pay:<4}  "
          f"← identity correct, payload value differs")
    print(f"  ❌ Identity field mismatch  : {level2_mismatch:<4}  "
          f"← timestamp found but type/serviceId/methodId wrong")
    print(f"  ❌ Completely missing       : {level3_missing:<4}  "
          f"← timestamp not in model output at all")
    print(f"{'─' * 72}")
    accuracy = (level1_correct / len(gt_list) * 100) if gt_list else 0
    print(f"  Full accuracy               : {accuracy:.1f}%  "
          f"({level1_correct}/{len(gt_list)} perfect)")
    print("=" * 72)


if __name__ == "__main__":
    main()
