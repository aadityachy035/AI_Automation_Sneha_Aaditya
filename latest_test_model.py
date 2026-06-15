# import os
# import json
# import torch
# from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
# from peft import PeftModel
 
# def main():
#     # ==============================================================================
#     BASE_MODEL_DIR   = r"C:\Users\achoudh4\Desktop\Qwen3B_Local"
#     FINETUNED_ADAP   = "./qwen_someip_2k_final"
#     INPUT_TXT_FILE   = "latest_testing.txt"
#     OUTPUT_JSON_FILE = "test_results_output.json"
#     MAX_LEN          = 2048
#     # ==============================================================================
 
#     print("=" * 60)
#     print("Step 1: Loading tokenizer...")
#     tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_DIR, trust_remote_code=True)
#     if tokenizer.pad_token is None:
#         tokenizer.pad_token = tokenizer.eos_token
#     tokenizer.padding_side = "left"
 
#     print("Step 2: Loading base model in 4-bit...")
#     bnb_config = BitsAndBytesConfig(
#         load_in_4bit=True,
#         bnb_4bit_quant_type="nf4",
#         bnb_4bit_compute_dtype=torch.bfloat16,
#         bnb_4bit_use_double_quant=True,
#     )
#     base_model = AutoModelForCausalLM.from_pretrained(
#         BASE_MODEL_DIR,
#         quantization_config=bnb_config,
#         device_map="auto",
#         trust_remote_code=True
#     )
 
#     print("Step 3: Loading LoRA adapter...")
#     model = PeftModel.from_pretrained(base_model, FINETUNED_ADAP)
#     model.eval()
 
#     if not os.path.exists(INPUT_TXT_FILE):
#         print(f"\n❌ Input file '{INPUT_TXT_FILE}' not found.")
#         return
 
#     print(f"Step 4: Reading input file...")
#     with open(INPUT_TXT_FILE, "r", encoding="utf-8") as f:
#         lines = [line.strip() for line in f if line.strip()]
#     print(f"--> Found {len(lines)} log lines.")
 
#         # ── Pre-filter: only keep SOME/IP lines ──────────────────────────────────
#     someip_lines = [
#         line for line in lines
#         if "SomeipCOmm :: RX Message" in line or "TX Message SomeipComm::send" in line
#     ]
#     skipped = len(lines) - len(someip_lines)
#     print(f"--> Pre-filter: {len(someip_lines)} SOME/IP lines, {skipped} non-SOME/IP skipped (no model call)")
#     print(f"--> Speed gain: {skipped} model calls saved!")
#     print("=" * 60)

#     # ── Results will only contain PARSED SOME/IP entries ─────────────────────
#     results = []          # list of parsed JSON dicts (no wrapper, no rejected)
#     total_parsed   = 0
#     total_rejected = 0
#     total_error    = 0
 
#     for idx, raw_log_line in enumerate(lines, 1):
#         print(f"Processing [{idx}/{len(lines)}]...", end="\r")
 
#         prompt = (
#             "### Instruction:\n"
#             "You are a senior Vehicle Hardware Abstraction Layer (VHAL) developer in Skylark project. "
#             "Parse this SOME/IP log line from the vehicle service. Extract the timestamp, transmission direction (RX/TX), "
#             "serviceId (converting hex to decimal for RX; keeping decimal for TX), methodId (converting hex to decimal for RX; "
#             "keeping decimal for TX), and payload. Output the parsed fields strictly as a validated JSON object matching the VHAL signal schema. "
#             "If the line is NOT a SOME/IP RX or TX message (for example UCL internal logs, heartbeat stats, or any other non-SOME/IP line), "
#             'output exactly: {"type": "ignore"}\n\n'
#             f"### Input:\n{raw_log_line}\n\n"
#             "### Response:\n"
#         )
 
#         inputs = tokenizer(
#             prompt,
#             return_tensors="pt",
#             max_length=MAX_LEN,
#             truncation=True
#         ).to("cuda")
 
#         with torch.no_grad():
#             generated_ids = model.generate(
#                 **inputs,
#                 max_new_tokens=2048,
#                 do_sample=False,
#                 temperature=0.0,
#                 eos_token_id=tokenizer.eos_token_id,
#                 pad_token_id=tokenizer.pad_token_id
#             )
 
#         input_length    = inputs.input_ids.shape[1]
#         response_tokens = generated_ids[0][input_length:]
#         response_text   = tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
 
#         # Clean markdown fences if present
#         if response_text.startswith("```json"):
#             response_text = response_text[7:]
#         if response_text.startswith("```"):
#             response_text = response_text[3:]
#         if response_text.endswith("```"):
#             response_text = response_text[:-3]
#         response_text = response_text.strip()
 
#         # Parse JSON
#         try:
#             parsed = json.loads(response_text)
#         except Exception:
#             # Model output was not valid JSON — log as error, skip
#             total_error += 1
#             print(f"\n⚠ Line {idx}: Could not parse model output as JSON")
#             print(f"  Raw output: {response_text[:100]}")
#             continue
 
#         # ── Filter logic ──────────────────────────────────────────────────────
#         msg_type = parsed.get("type", "")
 
#         if msg_type == "ignore":
#             # Non-SOME/IP line → silently skip, don't add to output
#             total_rejected += 1
#             continue
 
#         elif msg_type in ("rx", "tx"):
#             # Valid SOME/IP line → add ONLY the parsed fields to output
#             results.append(parsed)
#             total_parsed += 1
 
#         else:
#             # Unexpected output — skip
#             total_error += 1
#             print(f"\n⚠ Line {idx}: Unexpected type '{msg_type}' in model output")
#             continue
 
#     # ── Save output ───────────────────────────────────────────────────────────
#     print(f"\n\nStep 5: Saving output...")
#     with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as out_f:
#         json.dump(results, out_f, indent=4, ensure_ascii=False)
 
#     # ── Summary ───────────────────────────────────────────────────────────────
#     print("=" * 60)
#     print("PIPELINE COMPLETE!")
#     print(f"  Total lines processed : {len(lines)}")
#     print(f"  SOME/IP parsed        : {total_parsed}  ← in output file")
#     print(f"  Non-SOME/IP ignored   : {total_rejected}  ← silently skipped")
#     print(f"  Parse errors          : {total_error}")
#     print(f"  Output saved to       : {os.path.abspath(OUTPUT_JSON_FILE)}")
#     print("=" * 60)
 
# if __name__ == "__main__":
#     main()

import os
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
 
def main():
    # ==============================================================================
    BASE_MODEL_DIR   = r"C:\Users\achoudh4\Desktop\Qwen3B_Local"
    FINETUNED_ADAP   = "./qwen_someip_2k_final"
    INPUT_TXT_FILE   = "latest_testing.txt"
    OUTPUT_JSON_FILE = "test_results_output.json"
    MAX_LEN          = 2048
    # ==============================================================================
 
    print("=" * 60)
    print("Step 1: Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_DIR, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
 
    print("Step 2: Loading base model in 4-bit...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_DIR,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
 
    print("Step 3: Loading LoRA adapter...")
    model = PeftModel.from_pretrained(base_model, FINETUNED_ADAP)
    model.eval()
 
    if not os.path.exists(INPUT_TXT_FILE):
        print(f"\n❌ Input file '{INPUT_TXT_FILE}' not found.")
        return
 
    print(f"Step 4: Reading input file...")
    with open(INPUT_TXT_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    print(f"--> Found {len(lines)} log lines.")
 
    # ── Pre-filter: only keep SOME/IP lines ──────────────────────────────────
    someip_lines = [
        line for line in lines
        if "SomeipCOmm :: RX Message" in line or "TX Message SomeipComm::send" in line
    ]
    skipped = len(lines) - len(someip_lines)
    print(f"--> Pre-filter: {len(someip_lines)} SOME/IP lines, {skipped} non-SOME/IP skipped (no model call)")
    print(f"--> Speed gain: {skipped} model calls saved!")
    print("=" * 60)

    # ── Results tracks counts and parsed entries ─────────────────────────────
    results = []          # Optional: Can be removed to save RAM if log files are massive
    total_parsed   = 0
    total_rejected = 0
    total_error    = 0
 
    print("Step 5: Processing logs and streaming directly to JSON file...")
    # Open the file and write the starting bracket of the JSON array
    with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as out_f:
        out_f.write("[\n")
        first_entry = True
 
        # NOTE: Change 'lines' to 'someip_lines' below if you want to apply the pre-filter speedup
        for idx, raw_log_line in enumerate(lines, 1):
            print(f"Processing [{idx}/{len(lines)}]...", end="\r")
     
            prompt = (
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
     
            inputs = tokenizer(
                prompt,
                return_tensors="pt",
                max_length=MAX_LEN,
                truncation=True
            ).to("cuda")
     
            with torch.no_grad():
                generated_ids = model.generate(
                    **inputs,
                    max_new_tokens=2048,
                    do_sample=False,
                    temperature=0.0,
                    eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.pad_token_id
                )
     
            input_length    = inputs.input_ids.shape[1]
            response_tokens = generated_ids[0][input_length:]
            response_text   = tokenizer.decode(response_tokens, skip_special_tokens=True).strip()
     
            # Clean markdown fences if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
     
            # Parse JSON
            try:
                parsed = json.loads(response_text)
            except Exception:
                # Model output was not valid JSON — log as error, skip
                total_error += 1
                print(f"\n⚠ Line {idx}: Could not parse model output as JSON")
                print(f"  Raw output: {response_text[:100]}")
                continue
     
            # ── Filter logic ──────────────────────────────────────────────────────
            msg_type = parsed.get("type", "")
     
            if msg_type == "ignore":
                # Non-SOME/IP line → silently skip, don't add to output
                total_rejected += 1
                continue
     
            elif msg_type in ("rx", "tx"):
                # Valid SOME/IP line → add ONLY the parsed fields to output
                results.append(parsed)
                total_parsed += 1
                
                # Write a comma separator if this isn't the very first JSON block
                if not first_entry:
                    out_f.write(",\n")
                else:
                    first_entry = False
                
                # Format individual entry nicely and preserve array indentation (4 spaces)
                json_str = json.dumps(parsed, ensure_ascii=False, indent=4)
                indented_json_str = "\n".join("    " + line for line in json_str.splitlines())
                
                out_f.write(indented_json_str)
                out_f.flush()  # Force immediate write to disk storage
     
            else:
                # Unexpected output — skip
                total_error += 1
                print(f"\n⚠ Line {idx}: Unexpected type '{msg_type}' in model output")
                continue

        # Close the JSON array properly at the very end of processing
        out_f.write("\n]\n")
 
    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print("PIPELINE COMPLETE!")
    print(f"  Total lines processed : {len(lines)}")
    print(f"  SOME/IP parsed        : {total_parsed}  ← in output file")
    print(f"  Non-SOME/IP ignored   : {total_rejected}  ← silently skipped")
    print(f"  Parse errors          : {total_error}")
    print(f"  Output saved to       : {os.path.abspath(OUTPUT_JSON_FILE)}")
    print("=" * 60)
 
if __name__ == "__main__":
    main()