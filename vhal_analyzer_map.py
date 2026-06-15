import json
import os
import sys
 
def parse_can_payload(payload_str, result2):
    # payload_str is like "02 c7 00 ff ff ff ff 00 00 00 00"
    payload_bytes = payload_str.strip().split()
    if len(payload_bytes) < 3:
        return "Error: Payload too short"
 
    # First two bytes: msg id
    msg_id = (payload_bytes[0] + payload_bytes[1]).upper()
   
    # Next byte: validity
    validity_byte = payload_bytes[2]
    if validity_byte == "01":
        return "Invalid data (validity byte is 01)"
    elif validity_byte != "00":
        print(f"Warning: Unexpected validity byte '{validity_byte}'")
 
    # CAN data starts at index 3
    can_data = payload_bytes[3:]
   
    start_byte = result2.get("start_byte")
    start_bit = result2.get("start_bit")
    length = result2.get("length")
   
    if start_byte is None or start_bit is None or length is None:
        return "Error: Missing start_byte, start_bit, or length in definition"
   
    if start_byte >= len(can_data):
        return f"Error: start_byte {start_byte} is out of range for data length {len(can_data)}"
 
    target_byte_hex = can_data[start_byte]
    target_byte_val = int(target_byte_hex, 16)
   
    # "find the start bit, counted from rhs of the correct byte and use the lenght and find the value"
    # Assuming start_bit is the MSB of the signal within the byte if we count from RHS (0-7)
    # Standard CAN signal extraction for a simple single byte / partial byte signal
    # If length is 8 and start_bit is 7, it's the full byte.
    # To extract: shift right by (start_bit - length + 1) and mask with (1 << length) - 1
    # Example: start_bit = 7, length = 8 -> shift = 0, mask = 0xFF
    shift = start_bit - length + 1
    if shift < 0:
        # Cross-byte signals might need more complex logic, handling single byte here
        shift = 0
   
    mask = (1 << length) - 1
    extracted_val = (target_byte_val >> shift) & mask
   
    choices = result2.get("choices", {})
    str_val = str(extracted_val)
    if choices and str_val in choices:
        return f"{extracted_val} ({choices[str_val]})"
    return extracted_val
 
def parse_non_can_payload(payload_str, result2):
    payload_bytes = payload_str.strip().split()
    signals = result2.get("signals", [])
   
    output_lines = []
    for i in range(max(len(payload_bytes), len(signals))):
        sig_name = signals[i] if i < len(signals) else f"Unknown_Signal_{i}"
        val = payload_bytes[i] if i < len(payload_bytes) else "N/A"
       
        if val != "N/A":
            decimal_val = int(val, 16)
            output_lines.append(f"  {sig_name:<30}: {decimal_val} (0x{val})")
        else:
            output_lines.append(f"  {sig_name:<30}: N/A")
           
    return "\n".join(output_lines)
 
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # result1_path = os.path.join(script_dir, "data", "output", "result1 1.json")
    # result2_path = os.path.join(script_dir, "data", "output", "result2 1.json")
    result1_path = os.path.join(script_dir, "data", "output", "result1.json")
    result2_path = os.path.join(script_dir, "data", "output", "result2.json")
 
    if not os.path.exists(result1_path) or not os.path.exists(result2_path):
        print("Error: result1.json or result2.json not found in data/output/")
        sys.exit(1)
 
    with open(result1_path, "r", encoding="utf-8") as f:
        result1 = json.load(f)
 
    with open(result2_path, "r", encoding="utf-8") as f:
        result2 = json.load(f)
 
    print("=" * 50)
    print(" PAYLOAD PARSER")
    print("=" * 50)
 
    for idx, item in enumerate(result1):
        skylark_message = item.get("skylark_message", {})
        test_result = item.get("test_result", {})
       
        is_can = skylark_message.get("isCAN", False)
        payload = test_result.get("payload", "")
        message_name = skylark_message.get("messagename", "Unknown")
       
        print(f"\n[Message {idx + 1}] {message_name}")
        print(f"Type: {'CAN' if is_can else 'Non-CAN'}")
        print(f"Payload: {payload}")
       
        if is_can:
            parsed_value = parse_can_payload(payload, result2)
            print(f"Parsed Signal Value: {parsed_value}")
        else:
            mapped_values_str = parse_non_can_payload(payload, result2)
            print("Parsed Non-CAN Data:")
            print(mapped_values_str)
           
    print("\n" + "=" * 50)
 
if __name__ == "__main__":
    main()