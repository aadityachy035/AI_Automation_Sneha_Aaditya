# generate_dataset.py
import json
import random

random.seed(42)

# ── TARGETS ──────────────────────────────────────────────────────────────────
TOTAL           = 2000
BIG_PAYLOAD_MIN = 201   # "big" = more than your reference log's max (~200 bytes)
BIG_PAYLOAD_MAX = 240
BIG_COUNT       = 400   # 400 samples must have big payloads
RX_COUNT        = 800   # 800 RX  (hex → decimal conversion)
TX_COUNT        = 600   # 600 TX  (already decimal, passthrough)
IGNORE_COUNT    = 200   # 200 non-SOME/IP lines (model learns to output error)
# Total = 800 + 600 + 200 = 1600 base; remaining 400 are all big-payload RX/TX

INSTRUCTION = (
    "You are a senior Vehicle Hardware Abstraction Layer (VHAL) developer "
    "in Skylark project. Parse this SOME/IP log line from the vehicle service. "
    "Extract the timestamp, transmission direction (RX/TX), serviceId "
    "(converting hex to decimal for RX; keeping decimal for TX), methodId "
    "(converting hex to decimal for RX; keeping decimal for TX), and payload. "
    "Output the parsed fields strictly as a validated JSON object matching "
    "the VHAL signal schema. "
    "If the line is NOT a SOME/IP RX or TX message (for example UCL internal "
    "logs, heartbeat stats, or any other non-SOME/IP line), output exactly: "
    "{\"error\": \"not_someip\"}"
)

# ── REAL SERVICE/METHOD FINGERPRINTS FROM YOUR ACTUAL LOGS ───────────────────
# These are the real (serviceId_hex, methodId_hex) pairs seen in your log file.
# Using these makes the model learn REAL Skylark signal patterns.
REAL_RX_FINGERPRINTS = [
    (0xc7, 0x80e5), (0xc7, 0x80e2), (0xc7, 0x80df), (0xc7, 0x80e3),
    (0xc0, 0x8000), (0xc0, 0x8001), (0xc0, 0x8002), (0xc0, 0x8003),
    (0xc0, 0x8004), (0xc0, 0x8005), (0xc0, 0x8006),
    (0xbf, 0x800d), (0xbf, 0x800f), (0xbf, 0x8012), (0xbf, 0x8013),
    (0xbf, 0x8014), (0xbf, 0x8017), (0xbf, 0x801b), (0xbf, 0x801c),
    (0xbf, 0x8022), (0xbf, 0x8023), (0xbf, 0x8024), (0xbf, 0x8025),
    (0xbf, 0x8027), (0xbf, 0x802a), (0xbf, 0x802b), (0xbf, 0x802c),
    (0xbf, 0x802d), (0xbf, 0x802e), (0xbf, 0x802f), (0xbf, 0x8030),
    (0xbf, 0x8031), (0xbf, 0x8032), (0xbf, 0x8033), (0xbf, 0x8034),
    (0xbf, 0x8035), (0xbf, 0x8036), (0xbf, 0x8037), (0xbf, 0x803a),
    (0xbf, 0x803b), (0xbf, 0x803d), (0xbf, 0x8044), (0xbf, 0x8045),
    (0xbf, 0x8046), (0xbf, 0x8051), (0xbf, 0x8055), (0xbf, 0x8057),
    (0xbf, 0x8058), (0xbf, 0x8059), (0xbf, 0x805a), (0xbf, 0x805c),
    (0xbf, 0x805f), (0xbf, 0x806b),
    (0xca, 0x80e4), (0xcb, 0x8007), (0xcb, 0x800a),
    (0xcf, 0x8000), (0xc5, 0x80df),
    (0x102, 0x8000), (0xda, 0x8000),
]

# Real TX (serviceId_decimal, methodId_decimal) pairs from your logs
REAL_TX_FINGERPRINTS = [
    (193, 4), (193, 3), (194, 1), (196, 12), (198, 1),
    (287, 24585), (288, 1), (290, 3),
]

# ── REAL PAYLOAD PATTERNS FROM YOUR ACTUAL LOG ───────────────────────────────
# These are real payload headers extracted directly from your log file.
# They anchor the synthetic data to realistic byte sequences.
REAL_HEADERS = [
    ["02", "00", "00", "01", "0f", "01", "3e", "00", "08", "00"],   # 80e5 payload
    ["08", "04", "02", "02", "01", "02", "00", "00"],               # 80df payload
    ["03", "03", "03", "03", "03", "03", "03", "03", "03", "01"],   # 8005 payload
    ["01", "c6", "01", "00", "00", "00", "00"],                     # 8046 payload
    ["04", "fa", "01", "01", "60", "f5", "00", "00", "00"],         # 806b payload
    ["02", "b5", "01", "82", "77", "a2", "03"],                     # 803d payload
    ["01", "97", "01", "00", "08", "56", "00"],                     # 8017 payload
    ["00", "00", "ff", "1f", "00", "00", "00", "00"],               # 80e4 payload
    ["02", "cb", "01", "85", "00", "00", "00", "61", "80"],         # 802e payload
    ["01", "28", "00", "00", "00", "80", "00", "ff", "f0"],         # 8012 payload
    ["02", "3b", "01", "13", "00", "12", "e0", "00", "08"],         # 8022 payload
    ["1e", "01", "97", "02", "86", "01", "20", "01", "2c"],         # 8007 payload
]

# Real filler/trailer patterns seen in log
REAL_FILLERS = [
    ["03", "03", "03", "03", "01", "00", "00", "00"],
    ["a5", "33", "30", "34", "34"],                  # "3044" in ASCII
    ["0b", "0b", "0b", "a5", "07", "04", "f2"],
    ["0e", "ca", "03", "00", "01", "00"],
    ["a5", "00", "00", "00", "00"],
    ["ff", "ff", "ff", "ff", "00", "00"],
    ["80", "00", "00", "00", "00"],
]

# Repetitive patterns that appear frequently in real SOME/IP traffic
REPEAT_PATTERNS = ["00", "03", "01", "ff", "0f", "a5", "02"]

# ── NON-SOME/IP LOG LINES (for "ignore" training samples) ────────────────────
# Taken directly from your real log — the model must learn to ignore these
NON_SOMEIP_TEMPLATES = [
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## Tx Msgs : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## TxA Msgs : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## TxA TO : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## Rx Msgs : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## Rx HB Msgs : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## Tx Bps : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0 ## Rx Bps : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl: Inst Id : 0  ## Avg Ack Latency : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl_VIP: TxA TO : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl_VIP: Avg Ack Latency : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl_VIP: pollingCntr : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl_TCU: VIP-TCU - txBps : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl_TCU: VIP-TCU - rxBps : {n}",
    "{ts}   {pid}   {tid} I UclDL_Impl_TCU: VIP-TCU - txAckTmo : {n}",
    "{ts}   {pid}   {tid} I UclALOsAndroid_Impl: IUclALOs_Initialize: Success",
    "{ts}   {pid}   {tid} I UclALOsAndroid_Impl: IUclALOs_TimerCreate: Success",
    "{ts}   {pid}   {tid} I UclALOsAndroid_Impl: IUclALOs_MutexCreate: Success",
    "{ts}   {pid}   {tid} I UclALOsAndroid_Impl: IUclALOs_SemCreate: Success",
    "{ts}   {pid}   {tid} I UclGen_SomeIpAdapter: UCL App Created Successfully",
    "{ts}   {pid}   {tid} I UclGen_SomeIpAdapter: UCL- SOMEIP Service is Running",
    "{ts}   {pid}   {tid} I UclILRouter_Impl: IUclILRouter_Initialize: Success 0",
    "{ts}   {pid}   {tid} I UclDL_Impl: NofityLinkStatusChanged 1",
    "{ts}   {pid}   {tid} I UclDL_Impl: SecurityStartKeyNegotiation: Auth State : 0",
    "{ts}   {pid}   {tid} I UclALPhySerialAndroid_Impl_Hw_Initialize: Device /dev/ttyS1 opened",
    "{ts}   {pid}   {tid} I UclALPhySerialAndroid_Impl_TransmitTask: Begins",
    "{ts}   {pid}   {tid} I UclALPhySerialAndroid_Impl_ReceiveTask: Begins",
    "{ts}   {pid}   {tid} I UclSys_Impl: IUclSys_Initialize: Success",
    "{ts}   {pid}   {tid} I UclILSched_Impl: IUclILSched_Initialize: Success 1",
    "{ts}   {pid}   {tid} D vendor.visteon.skylark.hardware.automotive.vehicle@V1-visteon-service: PERIPHERAL_STATUS:: 03 03 03 03 03 03 03 03 03 01 03 03 03 00 00 00 00 00 00 00",
    "{ts}   {pid}   {tid} D vendor.visteon.skylark.hardware.automotive.vehicle@V1-visteon-service: WAKESTATE_STATUS:: 01 01 01",
    "{ts}   {pid}   {tid} D vendor.visteon.skylark.hardware.automotive.vehicle@V1-visteon-service: BULK_MSG_SUBSCRIPTION_REQUEST:: 1e 01 97 02 86 01",
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def rand_ts():
    """Random timestamp matching real log format: MM-DD HH:MM:SS.mmm"""
    return (
        f"{random.randint(1,12):02d}-{random.randint(1,28):02d} "
        f"{random.randint(0,23):02d}:{random.randint(0,59):02d}:"
        f"{random.randint(0,59):02d}.{random.randint(0,999):03d}"
    )

def rand_pid():
    return random.randint(400, 700)


def generate_payload(byte_count):
    """
    Generate a realistic SOME/IP payload of exactly byte_count bytes.

    Strategy — 4 types mirroring real Skylark traffic:

    Type A (40%) — real header + mixed middle + real filler + trailing zeros
        Mirrors the long 80e5/80df payloads in your log.
        Example: 02 00 00 01 0f ... [mixed] ... a5 33 30 34 34 00 00 00 00

    Type B (25%) — real header + long run of 00 bytes
        Mirrors the 100-byte 80df payloads: 08 04 02 02 01 02 + 94× 00

    Type C (20%) — repetitive single byte + short trailer
        Mirrors: 03 03 03 03 03 03 03 03 03 01 03 03 03 00 00 00 ...

    Type D (15%) — pure random bytes
        Ensures model doesn't overfit to patterns.

    For short payloads (≤ 11 bytes): always Type C or random (no room for headers).
    """
    if byte_count <= 0:
        byte_count = 1

    # ── Very short: no room for headers ──────────────────────────────────────
    if byte_count <= 11:
        if random.random() < 0.5:
            # repetitive
            val = random.choice(REPEAT_PATTERNS)
            return " ".join([val] * byte_count)
        else:
            return " ".join(f"{random.randint(0,255):02x}" for _ in range(byte_count))

    r = random.random()

    # ── Type A: header + mixed middle + filler + zeros ────────────────────────
    if r < 0.40:
        header  = random.choice(REAL_HEADERS)[:]
        filler  = random.choice(REAL_FILLERS)[:]
        # clamp header+filler to leave room for at least a few middle bytes
        max_hf  = byte_count - 4
        if len(header) + len(filler) > max_hf:
            header = header[:max(2, max_hf - len(filler))]
        if len(header) + len(filler) > max_hf:
            filler = filler[:max(1, max_hf - len(header))]

        remaining = byte_count - len(header) - len(filler)
        # split remaining into mixed middle + trailing zeros
        zero_count  = remaining // 2
        mid_count   = remaining - zero_count

        mid = []
        for _ in range(mid_count):
            p = random.random()
            if   p < 0.30: mid.append("00")
            elif p < 0.55: mid.append(f"{random.randint(1, 15):02x}")
            elif p < 0.75: mid.append(f"{random.randint(0, 255):02x}")
            else:          mid.append(random.choice(REPEAT_PATTERNS))

        result = header + mid + filler + ["00"] * zero_count
        # pad or trim to exact length
        while len(result) < byte_count:
            result.append("00")
        return " ".join(result[:byte_count])

    # ── Type B: header + run of 00s ───────────────────────────────────────────
    elif r < 0.65:
        header     = random.choice(REAL_HEADERS)[:]
        header     = header[:min(len(header), byte_count // 4)]
        zero_count = byte_count - len(header)
        result     = header + ["00"] * zero_count
        return " ".join(result[:byte_count])

    # ── Type C: repetitive byte + trailer ─────────────────────────────────────
    elif r < 0.85:
        rep_val     = random.choice(REPEAT_PATTERNS)
        rep_count   = random.randint(byte_count // 2, byte_count - 3)
        trailer_len = byte_count - rep_count
        trailer     = [f"{random.randint(0,255):02x}" for _ in range(trailer_len)]
        result      = [rep_val] * rep_count + trailer
        return " ".join(result[:byte_count])

    # ── Type D: pure random ───────────────────────────────────────────────────
    else:
        return " ".join(f"{random.randint(0,255):02x}" for _ in range(byte_count))


def pick_normal_byte_size():
    """
    Payload size distribution for normal (non-big) samples.
    Mirrors real Skylark log distribution.
    """
    r = random.random()
    if   r < 0.10: return random.randint(1,   8)     # very short (single values)
    elif r < 0.20: return random.randint(9,   20)    # short (flag bytes)
    elif r < 0.35: return random.randint(21,  50)    # medium-short
    elif r < 0.55: return random.randint(51,  100)   # medium (common range)
    elif r < 0.75: return random.randint(101, 150)   # medium-long
    else:          return random.randint(151, 200)   # long (up to reference max)


def format_sample(log_line, output_dict):
    """Format one training sample in Alpaca instruction format."""
    return {
        "text": (
            f"### Instruction:\n{INSTRUCTION}\n\n"
            f"### Input:\n{log_line}\n\n"
            f"### Response:\n{json.dumps(output_dict, indent=2)}"
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# RECORD BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def make_rx(svc_int, method_int, byte_size, ts=None):
    """
    Build one RX training sample.
    Key learning signal: serviceId and methodId are in HEX in the log line,
    but the output JSON must have them as DECIMAL integers.
    """
    ts         = ts or rand_ts()
    pid        = rand_pid()
    tid        = rand_pid()
    msg_idx    = random.randint(0, 9999)
    payload    = generate_payload(byte_size)

    svc_hex    = format(svc_int,    'x')   # e.g. 192 → "c0"
    method_hex = format(method_int, 'x')   # e.g. 32773 → "8005"

    log_line = (
        f"{ts}   {pid}   {tid} D "
        f"vendor.visteon.skylark.hardware.automotive.vehicle"
        f"@V1-visteon-service: SomeipCOmm :: RX Message "
        f"[0/{msg_idx:x}]:service:{svc_hex} "
        f",Method:{method_hex},payload:{payload} "
    )
    output = {
        "time":      ts,
        "type":      "rx",
        "serviceId": svc_int,    # DECIMAL in output ← this is what model must learn
        "methodId":  method_int, # DECIMAL in output ← this is what model must learn
        "payload":   payload
    }
    return format_sample(log_line, output)


def make_tx(svc_int, method_int, byte_size, ts=None):
    """
    Build one TX training sample.
    TX logs already have decimal serviceId/methodId — model just passes them through.
    """
    ts      = ts or rand_ts()
    pid     = rand_pid()
    tid     = rand_pid()
    payload = generate_payload(byte_size)

    log_line = (
        f"{ts}   {pid}   {tid} D "
        f"vendor.visteon.skylark.hardware.automotive.vehicle"
        f"@V1-visteon-service: TX Message SomeipComm::send  : "
        f"service:{svc_int},method:{method_int}, response Payload: {payload} "
    )
    output = {
        "time":      ts,
        "type":      "tx",
        "serviceId": svc_int,
        "methodId":  method_int,
        "payload":   payload
    }
    return format_sample(log_line, output)


def make_ignore(ts=None):
    """
    Build one non-SOME/IP sample. The model must output {"error": "not_someip"}.
    These lines come directly from your real log file.
    """
    ts       = ts or rand_ts()
    pid      = rand_pid()
    tid      = rand_pid()
    template = random.choice(NON_SOMEIP_TEMPLATES)
    log_line = template.format(
        ts=ts, pid=pid, tid=tid,
        n=random.randint(0, 50000)
    )
    return format_sample(log_line, {"error": "not_someip"})


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GENERATION
# ─────────────────────────────────────────────────────────────────────────────

print("=" * 60)
print("Generating 2000-sample SOME/IP training dataset")
print("=" * 60)
print(f"  RX samples (hex→decimal learning) : {RX_COUNT}")
print(f"  TX samples (decimal passthrough)  : {TX_COUNT}")
print(f"  Ignore samples (non-SOME/IP)      : {IGNORE_COUNT}")
print(f"  Big payload samples (≥201 bytes)  : {BIG_COUNT}")
print(f"  Total                             : {TOTAL}")
print()

dataset = []

# ── Phase 1: BIG PAYLOAD RX samples (300 of the 400 big ones) ────────────────
# These are crucial — they teach the model to handle payloads larger than
# anything in your reference log, specifically for long message types like 80e5
print("Phase 1: Big-payload RX samples (300)...")
for _ in range(300):
    svc, method = random.choice(REAL_RX_FINGERPRINTS)
    byte_size   = random.randint(BIG_PAYLOAD_MIN, BIG_PAYLOAD_MAX)
    dataset.append(make_rx(svc, method, byte_size))

# ── Phase 2: BIG PAYLOAD TX samples (100 of the 400 big ones) ────────────────
print("Phase 2: Big-payload TX samples (100)...")
for _ in range(100):
    svc, method = random.choice(REAL_TX_FINGERPRINTS)
    byte_size   = random.randint(BIG_PAYLOAD_MIN, BIG_PAYLOAD_MAX)
    dataset.append(make_tx(svc, method, byte_size))

# ── Phase 3: Normal RX samples — REAL fingerprints (400) ─────────────────────
# Uses actual (service, method) pairs from your log — most important for accuracy
print("Phase 3: Normal RX — real fingerprints (400)...")
for _ in range(400):
    svc, method = random.choice(REAL_RX_FINGERPRINTS)
    dataset.append(make_rx(svc, method, pick_normal_byte_size()))

# ── Phase 4: Normal RX samples — EXTENDED hex range (200) ────────────────────
# Random service/method hex values — teaches generalisation beyond real IDs
# Intentionally includes larger hex values so model learns multi-digit conversion
print("Phase 4: Normal RX — extended hex range (200)...")
for _ in range(200):
    # Mix of small, medium, and large hex values
    r = random.random()
    if   r < 0.33: svc = random.randint(0x01,  0xff)     # 1-byte service IDs
    elif r < 0.66: svc = random.randint(0x100, 0xfff)    # 2–3 nibble IDs
    else:          svc = random.randint(0x1000, 0xffff)  # 4 nibble IDs

    method = random.randint(0x8000, 0x8fff)   # real method ID range from your log
    dataset.append(make_rx(svc, method, pick_normal_byte_size()))

# ── Phase 5: Normal TX samples (300) ─────────────────────────────────────────
print("Phase 5: Normal TX samples (300)...")
for _ in range(300):
    # Mix real TX fingerprints and random values
    if random.random() < 0.6:
        svc, method = random.choice(REAL_TX_FINGERPRINTS)
    else:
        svc    = random.randint(1,   500)
        method = random.randint(1, 35000)
    dataset.append(make_tx(svc, method, pick_normal_byte_size()))

# ── Phase 6: Ignore / non-SOME/IP samples (200) ──────────────────────────────
print("Phase 6: Non-SOME/IP ignore samples (200)...")
for _ in range(200):
    dataset.append(make_ignore())

# ─────────────────────────────────────────────────────────────────────────────
# SHUFFLE & SPLIT
# ─────────────────────────────────────────────────────────────────────────────
print("\nShuffling dataset...")
random.shuffle(dataset)

# 90% train / 10% validation
split      = int(len(dataset) * 0.9)
train_data = dataset[:split]
val_data   = dataset[split:]

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT — verify the dataset looks right before saving
# ─────────────────────────────────────────────────────────────────────────────
print("\nRunning audit...")

size_buckets = {
    "1–10":    0, "11–20":  0, "21–50":  0,
    "51–100":  0, "101–150": 0, "151–200": 0,
    "201–240": 0
}
type_counts  = {"rx": 0, "tx": 0, "not_someip": 0, "parse_error": 0}
hex_checks   = {"correct": 0, "wrong": 0}

for rec in dataset:
    try:
        text       = rec["text"]
        resp_start = text.index("### Response:") + len("### Response:")
        resp_str   = text[resp_start:].strip()
        resp       = json.loads(resp_str)

        # count types
        if "error" in resp:
            type_counts["not_someip"] += 1
            continue

        t = resp.get("type", "")
        type_counts[t] = type_counts.get(t, 0) + 1

        # payload size bucket
        bc = len(resp.get("payload", "").split())
        if   bc <= 10:  size_buckets["1–10"]    += 1
        elif bc <= 20:  size_buckets["11–20"]   += 1
        elif bc <= 50:  size_buckets["21–50"]   += 1
        elif bc <= 100: size_buckets["51–100"]  += 1
        elif bc <= 150: size_buckets["101–150"] += 1
        elif bc <= 200: size_buckets["151–200"] += 1
        else:           size_buckets["201–240"] += 1

        # verify hex→decimal conversion is correct for a few RX samples
        if t == "rx" and hex_checks["correct"] + hex_checks["wrong"] < 50:
            inp_start  = text.index("### Input:") + len("### Input:")
            inp_end    = text.index("### Response:")
            inp_line   = text[inp_start:inp_end].strip()

            import re
            m = re.search(r"service:([0-9a-f]+) ,Method:([0-9a-f]+)", inp_line)
            if m:
                svc_from_log  = int(m.group(1), 16)
                meth_from_log = int(m.group(2), 16)
                if (svc_from_log  == resp["serviceId"] and
                    meth_from_log == resp["methodId"]):
                    hex_checks["correct"] += 1
                else:
                    hex_checks["wrong"] += 1

    except Exception as e:
        type_counts["parse_error"] += 1

# Print audit results
total_typed = sum(v for k,v in type_counts.items() if k != "parse_error")
print("\nSample type breakdown:")
for k, v in type_counts.items():
    print(f"  {k:15s}: {v:4d}")

print("\nPayload size distribution (train+val combined):")
total_sized = sum(size_buckets.values())
for label, count in size_buckets.items():
    bar    = "█" * int(30 * count / max(total_sized, 1))
    marker = "  ← BIG (new extended range)" if label == "201–240" else ""
    print(f"  {label:10s} bytes: {count:4d}  ({100*count/max(total_sized,1):5.1f}%)  {bar}{marker}")

print(f"\nHex→decimal conversion check (spot-checked 50 RX samples):")
print(f"  Correct : {hex_checks['correct']}")
print(f"  Wrong   : {hex_checks['wrong']}")
if hex_checks["wrong"] == 0:
    print("  All spot-checked conversions are correct!")

# ─────────────────────────────────────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────────────────────────────────────
def save_jsonl(path, data_list):
    with open(path, "w", encoding="utf-8") as f:
        for item in data_list:
            f.write(json.dumps(item) + "\n")

print("\nSaving files...")
save_jsonl("train_someip.jsonl", train_data)
save_jsonl("val_someip.jsonl",   val_data)

print("=" * 60)
print("Done!")
print(f"  train_someip.jsonl : {len(train_data):,} samples")
print(f"  val_someip.jsonl   : {len(val_data):,} samples")
print(f"  Big payloads (201–240 bytes): exactly {BIG_COUNT}")
print("=" * 60)

# Show one example of each type so you can visually verify
print("\n── EXAMPLE: RX sample (verify hex→decimal) ──")
rx_ex = next(r for r in dataset if '"type": "rx"' in r["text"])
print(rx_ex["text"][:600])

print("\n── EXAMPLE: TX sample ──")
tx_ex = next(r for r in dataset if '"type": "tx"' in r["text"])
print(tx_ex["text"][:400])

print("\n── EXAMPLE: Ignore sample ──")
ig_ex = next(r for r in dataset if '"error": "not_someip"' in r["text"])
print(ig_ex["text"])