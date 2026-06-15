"""
batch_test_model.py  –  Client for the persistent SOME/IP model server
=======================================================================
BEFORE running this, start the server in a separate terminal:
    python model_server.py        ← loads model once, stays running

Then run this script as many times as you want — NO model loading delay!

Optimization: Lines are sorted by payload byte count before batching.
              Each batch sends a dynamic max_new_tokens based on the
              longest payload in that batch → no wasted GPU token budget.
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))   # Indian Standard Time (UTC+5:30)

# ==============================================================================
SERVER_URL       = "http://127.0.0.1:8765"   # Must match HOST:PORT in model_server.py
INPUT_TXT_FILE   = "latest_testing.txt"
OUTPUT_JSON_FILE = "test_results_output_batch.json"
BATCH_SIZE       = 8     # Lines per server call. Reduce to 4 if CUDA OOM occurs.

# Max log-line length (chars) we feed to the model.
# compute_max_new_tokens(795) == 700, which is the hard token cap.
# Any line longer than this is trimmed from the tail (payload end) before
# being sent, so the model always has enough room to emit a complete JSON.
MAX_LINE_LEN     = 795
# ==============================================================================


def is_someip(line: str) -> bool:
    """Return True if line is a SOME/IP RX or TX message."""
    return "SomeipCOmm :: RX Message" in line or "TX Message SomeipComm::send" in line


def compute_max_new_tokens(line_len: int) -> int:
    """
    Estimate max_new_tokens directly from the total log line character length.
    No regex needed — longer line = more payload bytes = more output tokens.

    Derivation:
      log line = fixed prefix (~175 chars) + payload_bytes × 3 chars ("XX ")
      ∴ payload_bytes ≈ (line_len - 175) / 3
      max_new_tokens = 80 (JSON overhead) + payload_bytes × 2.5 × 1.2
                     = 80 + (line_len - 175) / 3 × 3   (simplified)
                     ≈ line_len - 95

    Examples (same values as regex approach):
      len=175 (1 byte)    → 150  (minimum)
      len=300 (40 bytes)  → 205
      len=500 (100 bytes) → 405
      len=775 (200 bytes) → 680
    """
    return int(max(150, min(line_len - 95, 700)))


def trim_log_line(line: str) -> tuple[str, int]:
    """
    If *line* is longer than MAX_LINE_LEN characters, trim it from the back
    so that compute_max_new_tokens() stays within the 700-token cap.

    The trim snaps backward to the nearest space so we never cut a hex byte
    in half (payload bytes are separated by spaces, e.g. "06 03 00 ...").

    Returns (trimmed_line, chars_removed).  chars_removed == 0 means no trim.
    """
    if len(line) <= MAX_LINE_LEN:
        return line, 0

    trimmed = line[:MAX_LINE_LEN]
    # Snap back to the nearest space so we don't split a hex byte
    last_space = trimmed.rfind(" ")
    if last_space > 0:
        trimmed = trimmed[:last_space]

    return trimmed, len(line) - len(trimmed)


def build_prompt(raw_log_line: str) -> str:
    """Build the instruction prompt for a single log line."""
    return (
        "### Instruction:\n"
        "You are a senior Vehicle Hardware Abstraction Layer (VHAL) developer in Skylark project. "
        "Parse this SOME/IP log line from the vehicle service. Extract the timestamp, transmission direction (RX/TX), "
        "serviceId (converting hex to decimal for RX; keeping decimal for TX), methodId (converting hex to decimal for RX; "
        "keeping decimal for TX), and payload. Output the parsed fields strictly as a validated JSON object matching the VHAL signal schema. "
        "If the line is NOT a SOME/IP RX or TX message (for example UCL internal logs, heartbeat stats, or any other non-SOME/IP line), "
        'output exactly: {"type": "ignore"}\n\n'
        f"### Input:\n{raw_log_line}\n\n"
        "### Response:\n"
    )


def clean_response(text: str) -> str:
    """Strip markdown code fences if the model wrapped its output."""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def check_server():
    """Make sure the model server is up before starting. Fail fast with a clear message."""
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("model_loaded"):
            print("❌ Server is running but model is NOT loaded yet. Wait a moment and retry.")
            sys.exit(1)
        print(f"✅ Model server is ready at {SERVER_URL}")
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Cannot connect to model server at {SERVER_URL}")
        print("   → Start the server first:  python model_server.py")
        print("   → Keep that terminal open, then run this script.\n")
        sys.exit(1)


def infer_batch(prompts: list, max_new_tokens: int) -> list:
    """
    Send a batch of prompts + dynamic token budget to the server.
    Returns list of raw response strings.
    """
    payload = {
        "prompts": prompts,
        "max_new_tokens": max_new_tokens,
    }
    resp = requests.post(f"{SERVER_URL}/predict", json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()["responses"]


def main():
    print("=" * 60)

    # Record start time in IST
    start_time = datetime.now(IST)
    print(f"  Start time : {start_time.strftime('%d-%b-%Y  %I:%M:%S %p IST')}")
    print("=" * 60)

    # ── 1. Verify server is up ─────────────────────────────────────
    check_server()

    # ── 2. Load input file ─────────────────────────────────────────
    if not os.path.exists(INPUT_TXT_FILE):
        print(f"\n❌ Input file '{INPUT_TXT_FILE}' not found.")
        sys.exit(1)

    print(f"Reading input file: {INPUT_TXT_FILE}")
    with open(INPUT_TXT_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    print(f"--> Found {len(lines)} log lines.")

    # ── 3. Pre-filter: keep only SOME/IP lines ─────────────────────
    someip_lines = [line for line in lines if is_someip(line)]
    skipped = len(lines) - len(someip_lines)
    print(f"--> Pre-filter : {len(someip_lines)} SOME/IP lines, {skipped} non-SOME/IP skipped")

    # ── 4. Sort by log line length (ascending) ────────────────────────────
    #  Longer line = more payload bytes = needs more output tokens.
    #  Short lines batch together → small token budget
    #  Long lines batch together  → large token budget (only when needed)
    annotated = [(line, len(line)) for line in someip_lines]
    annotated.sort(key=lambda x: x[1])

    sorted_lines  = [a[0] for a in annotated]
    line_lengths  = [a[1] for a in annotated]

    print(f"--> Line length range: {line_lengths[0]} chars (min) → {line_lengths[-1]} chars (max)")
    print(f"--> Token budget range: {compute_max_new_tokens(line_lengths[0])} → {compute_max_new_tokens(line_lengths[-1])} tokens")
    print(f"--> Batch size : {BATCH_SIZE}  →  ~{(len(sorted_lines) + BATCH_SIZE - 1) // BATCH_SIZE} server calls")
    print("=" * 60)

    total_parsed   = 0
    total_rejected = 0
    total_error    = 0
    parsed_results = []   # collect all valid parsed dicts; sort by time at the end

    print(f"Processing SOME/IP lines in batches of {BATCH_SIZE} (sorted by payload length)...")

    for batch_start in range(0, len(sorted_lines), BATCH_SIZE):
        batch        = sorted_lines [batch_start : batch_start + BATCH_SIZE]
        batch_lens   = line_lengths [batch_start : batch_start + BATCH_SIZE]
        batch_end    = batch_start + len(batch)

        # Dynamic token budget: based on the longest line in THIS batch
        max_len_in_batch = max(batch_lens)
        dyn_tokens       = compute_max_new_tokens(max_len_in_batch)

        print(
            f"  Batch [{batch_start + 1:>3}-{batch_end:>3}/{len(sorted_lines)}] "
            f"| line ≤ {max_len_in_batch:>4} chars "
            f"| max_new_tokens = {dyn_tokens}",
            end="\r"
        )

        # Trim oversized lines from the back before building prompts
        trimmed_batch = []
        for line_idx_local, line in enumerate(batch):
            trimmed_line, chars_cut = trim_log_line(line)
            if chars_cut > 0:
                global_idx = batch_start + line_idx_local + 1
                print(
                    f"\n  ✂ Line {global_idx}: trimmed {chars_cut} chars from tail "
                    f"(original {len(line)} → {len(trimmed_line)} chars)"
                )
            trimmed_batch.append(trimmed_line)

        # Re-compute dynamic token budget using trimmed lengths
        trimmed_lens = [len(l) for l in trimmed_batch]
        dyn_tokens   = compute_max_new_tokens(max(trimmed_lens))

        # Build prompts and send to server with dynamic token budget
        prompts = [build_prompt(line) for line in trimmed_batch]
        try:
            raw_responses = infer_batch(prompts, dyn_tokens)
        except Exception as e:
            print(f"\n⚠ Batch [{batch_start + 1}-{batch_end}]: server error: {e}")
            total_error += len(batch)
            continue

        # Process each response in the batch
        for i, (raw_log_line, response_text) in enumerate(zip(batch, raw_responses)):
            line_idx      = batch_start + i + 1
            response_text = clean_response(response_text)

            try:
                parsed = json.loads(response_text)
            except Exception:
                total_error += 1
                print(f"\n⚠ Line {line_idx}: Could not parse model output as JSON")
                print(f"  Raw output    : {response_text[:120]}")
                print(f"  Line length   : {batch_lens[i]} chars  |  max_new_tokens used: {dyn_tokens}")
                continue

            msg_type = parsed.get("type", "")

            if msg_type == "ignore":
                total_rejected += 1
                continue

            elif msg_type in ("rx", "tx"):
                total_parsed += 1
                parsed_results.append(parsed)   # collect — will sort later

            else:
                total_error += 1
                print(f"\n⚠ Line {line_idx}: Unexpected type '{msg_type}' in model output")
                continue

    # ── Sort collected results by timestamp (ascending) ────────────
    # Timestamp format: "MM-DD HH:MM:SS.mmm" — lexicographic sort works correctly
    # Try common field names the model might output
    def get_timestamp(entry: dict) -> str:
        for key in ("time", "timestamp", "Time", "Timestamp"):
            if key in entry:
                return entry[key]
        return ""   # missing timestamp → sorts to front

    parsed_results.sort(key=get_timestamp)
    print(f"\n--> Sorted {len(parsed_results)} entries by timestamp (ascending)")

    # ── Write sorted results to JSON file ──────────────────────────
    with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as out_f:
        out_f.write("[\n")
        for idx, entry in enumerate(parsed_results):
            json_str = json.dumps(entry, ensure_ascii=False, indent=4)
            indented  = "\n".join("    " + ln for ln in json_str.splitlines())
            if idx < len(parsed_results) - 1:
                out_f.write(indented + ",\n")
            else:
                out_f.write(indented + "\n")
        out_f.write("]\n")

    # ── Summary ────────────────────────────────────────────────────
    end_time     = datetime.now(IST)
    elapsed_secs = (end_time - start_time).total_seconds()
    elapsed_min  = int(elapsed_secs // 60)
    elapsed_sec  = int(elapsed_secs % 60)

    print(f"\n\n{'=' * 60}")
    print("PIPELINE COMPLETE!")
    print("-" * 60)
    print(f"  Stage 1 \u2014 Pre-filter  (before model):")
    print(f"    Total log lines read  : {len(lines)}")
    print(f"    SOME/IP lines found   : {len(someip_lines)}  \u2190 sent to model")
    print(f"    Non-SOME/IP skipped   : {skipped}  \u2190 never reached model (UclDL, status logs etc.)")
    print("-" * 60)
    print(f"  Stage 2 \u2014 Model parsing:")
    print(f"    Successfully parsed   : {total_parsed}  \u2190 saved in output file")
    print(f"    Model said 'ignore'   : {total_rejected}  \u2190 model output {{\"type\":\"ignore\"}}")
    print(f"    Parse errors          : {total_error}  \u2190 model output was incomplete/invalid JSON")
    print("-" * 60)
    print(f"  Output saved to : {os.path.abspath(OUTPUT_JSON_FILE)}")
    print("-" * 60)
    print(f"  Start time  : {start_time.strftime('%d-%b-%Y  %I:%M:%S %p IST')}")
    print(f"  End time    : {end_time.strftime('%d-%b-%Y  %I:%M:%S %p IST')}")
    print(f"  Time taken  : {elapsed_min} min  {elapsed_sec} sec")
    print("=" * 60)


if __name__ == "__main__":
    main()
