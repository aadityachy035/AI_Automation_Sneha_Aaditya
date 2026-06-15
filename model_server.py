"""
model_server.py  –  Persistent SOME/IP parsing server
======================================================
Start this ONCE.  The model loads into GPU memory and stays there.
Your test script (batch_test_model.py) then sends HTTP requests
instead of loading the model every run.

Usage:
    python model_server.py

Then in another terminal:
    python batch_test_model.py        ← instant, no loading delay
"""

import json
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
import uvicorn

# ==============================================================================
BASE_MODEL_DIR  = r"C:\Users\achoudh4\Desktop\Qwen3B_Local"
FINETUNED_ADAP  = "./qwen_someip_2k_final"
MAX_LEN         = 2048
MAX_NEW_TOKENS_DEFAULT = 600   # Fallback if client does not send max_new_tokens
MAX_NEW_TOKENS_CAP     = 700   # Hard ceiling — never exceed this regardless of client value
HOST            = "127.0.0.1"   # localhost only (safe, not exposed to network)
PORT            = 8765           # you can change this if 8765 is taken
# ==============================================================================

app = FastAPI(title="SOME/IP Model Server")

# ── Global model state (loaded once, lives forever) ───────────────────────────
tokenizer = None
model     = None


# ── Request / Response schemas ────────────────────────────────────────────────
class InferRequest(BaseModel):
    prompts: List[str]              # List of already-built prompt strings
    max_new_tokens: int = MAX_NEW_TOKENS_DEFAULT   # Client sends dynamic value per batch


class InferResponse(BaseModel):
    responses: List[str]            # One response string per prompt


# ── Startup: load model into GPU once ─────────────────────────────────────────
@app.on_event("startup")
def load_model():
    global tokenizer, model

    print("=" * 60)
    print("[Server] Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_DIR, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"   # Required for decoder-only batched inference

    print("[Server] Loading base model in 4-bit (this takes ~30-60s)...")
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
        trust_remote_code=True,
    )

    print("[Server] Loading LoRA adapter...")
    model = PeftModel.from_pretrained(base_model, FINETUNED_ADAP)
    model.eval()

    print("[Server] ✅ Model ready!  Listening for requests...")
    print("=" * 60)


# ── Inference endpoint ─────────────────────────────────────────────────────────
@app.post("/predict", response_model=InferResponse)
def predict(req: InferRequest):
    """
    Accepts a batch of prompt strings + a dynamic max_new_tokens.
    Client computes max_new_tokens based on the longest payload in the batch.
    """
    if not req.prompts:
        raise HTTPException(status_code=400, detail="prompts list is empty")

    prompts = req.prompts

    # Clamp client value between 150 and hard cap
    dynamic_max_tokens = max(150, min(req.max_new_tokens, MAX_NEW_TOKENS_CAP))

    # Tokenize with left-padding so all sequences align on the right
    inputs = tokenizer(
        prompts,
        return_tensors="pt",
        max_length=MAX_LEN,
        truncation=True,
        padding=True,
    ).to("cuda")

    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=dynamic_max_tokens,  # ← dynamic per batch, not fixed
            do_sample=False,
            temperature=0.0,
            num_beams=1,                        # greedy decode, fastest possible
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )

    input_length = inputs.input_ids.shape[1]
    responses = []
    for i in range(len(prompts)):
        new_tokens   = generated_ids[i][input_length:]
        decoded      = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        responses.append(decoded)

    return InferResponse(responses=responses)


# ── Health-check endpoint ──────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": model is not None}


if __name__ == "__main__":
    print(f"Starting model server on http://{HOST}:{PORT}")
    print("Keep this terminal open. Run batch_test_model.py in a NEW terminal.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
