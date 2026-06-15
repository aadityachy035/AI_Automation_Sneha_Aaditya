import os
import torch
import sys
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
) 
from peft import LoraConfig, get_peft_model, TaskType, PeftModel
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset
 
# ==============================================================================
# ── CONFIGURATION ─────────────────────────────────────────────────────────────
# ==============================================================================
MODEL_NAME  = r"C:\Users\achoudh4\Desktop\Qwen3B_Local"
OUTPUT_DIR  = "./qwen_someip_2k_final"
 
# FIXED: Use absolute paths so it works from any directory
BASE_DIR    = r"C:\Users\achoudh4\Desktop\Aaditya_Choudhury_Kolkata\Vhal"
TRAIN_FILE  = os.path.join(BASE_DIR, "train_someip.jsonl")
VAL_FILE    = os.path.join(BASE_DIR, "val_someip.jsonl")
 
MAX_LEN     = 1024   # FIXED: was 2048, changed to 1024 (covers all 240-byte payloads)
BATCH_SIZE  = 1
GRAD_ACCUM  = 8             # effective batch = 1×8 = 8
LR          = 2e-4
NUM_EPOCHS  = 3
# ==============================================================================
 
# ── PRE-FLIGHT CHECKS ─────────────────────────────────────────────────────────
print("=" * 60)
print("PRE-FLIGHT CHECKS")
print("=" * 60)
 
# Check 1: Dataset files exist
print(f"\n[1/4] Checking dataset files...")
if not os.path.exists(TRAIN_FILE):
    print(f"  ✗ TRAIN FILE NOT FOUND: {TRAIN_FILE}")
    sys.exit(1)
else:
    size = os.path.getsize(TRAIN_FILE) / 1e6
    print(f"  ✓ {TRAIN_FILE} ({size:.1f} MB)")
 
if not os.path.exists(VAL_FILE):
    print(f"  ✗ VAL FILE NOT FOUND: {VAL_FILE}")
    sys.exit(1)
else:
    size = os.path.getsize(VAL_FILE) / 1e6
    print(f"  ✓ {VAL_FILE} ({size:.1f} MB)")
 
# Check 2: Model path exists
print(f"\n[2/4] Checking model path...")
if not os.path.exists(MODEL_NAME):
    print(f"  ✗ MODEL PATH NOT FOUND: {MODEL_NAME}")
    sys.exit(1)
else:
    print(f"  ✓ {MODEL_NAME}")
 
# Check 3: CUDA available
print(f"\n[3/4] Checking CUDA...")
if not torch.cuda.is_available():
    print(f"  ⚠ CUDA not available (will use CPU - VERY SLOW)")
else:
    print(f"  ✓ GPU available: {torch.cuda.get_device_name(0)}")
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"    VRAM: {vram:.1f} GB")
 
# Check 4: Can load dataset
print(f"\n[4/4] Checking dataset can load...")
try:
    from datasets import load_dataset
    test_dataset = load_dataset("json", data_files={"train": TRAIN_FILE, "validation": VAL_FILE})
    train_len = len(test_dataset["train"])
    val_len = len(test_dataset["validation"])
    print(f"  ✓ Dataset loaded: {train_len} train + {val_len} val")
except Exception as e:
    print(f"  ✗ Dataset load failed: {e}")
    sys.exit(1)
 
print("\n" + "=" * 60)
print("ALL PRE-FLIGHT CHECKS PASSED ✓")
print("=" * 60)
 
# ── MAIN TRAINING ─────────────────────────────────────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)
CHECKPOINT_DIR = os.path.join(OUTPUT_DIR, "checkpoints")
os.makedirs(CHECKPOINT_DIR, exist_ok=True)
 
print("\n" + "=" * 60)
print("SOME/IP Fine-tuning  —  2000 samples, single run")
print("=" * 60)
print(f"  Model      : {MODEL_NAME}")
print(f"  Train file : {TRAIN_FILE}")
print(f"  Val file   : {VAL_FILE}")
print(f"  MAX_LEN    : {MAX_LEN}")
print(f"  Epochs     : {NUM_EPOCHS}")
print(f"  Batch size : {BATCH_SIZE}  (grad accum {GRAD_ACCUM} → effective {BATCH_SIZE * GRAD_ACCUM})")
print(f"  Output dir : {OUTPUT_DIR}")
print("=" * 60)
 
# ── Step 1: Tokenizer ─────────────────────────────────────────────────────────
print("\n[1/7] Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
tokenizer.pad_token    = tokenizer.eos_token
tokenizer.padding_side = "right"
print("      Tokenizer loaded OK")
 
# ── Step 2: 4-bit quantisation ────────────────────────────────────────────────
print("\n[2/7] Setting up 4-bit quantisation...")
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
print("      BnB config ready")
 
# ── Step 3: Base model ────────────────────────────────────────────────────────
print("\n[3/7] Loading base model (this takes 1–3 minutes)...")
base_model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)
base_model.config.use_cache = False
base_model.gradient_checkpointing_enable()
print("      Base model loaded OK")
 
# ── Step 4: LoRA adapters ─────────────────────────────────────────────────────
print("\n[4/7] Setting up LoRA adapters...")
 
import glob
 
def get_latest_checkpoint(ckpt_dir):
    """Return the latest checkpoint folder, or None if none exist."""
    pattern = os.path.join(ckpt_dir, "checkpoint-*")
    ckpts   = sorted(
        [c for c in glob.glob(pattern)
         if os.path.isdir(c) and os.path.basename(c).split("-")[-1].isdigit()],
        key=lambda x: int(os.path.basename(x).split("-")[-1])
    )
    return ckpts[-1] if ckpts else None
 
crash_ckpt = get_latest_checkpoint(CHECKPOINT_DIR)
 
if crash_ckpt:
    print(f"      Crash checkpoint found → resuming from: {crash_ckpt}")
    model                  = PeftModel.from_pretrained(base_model, crash_ckpt, is_trainable=True)
    resume_from_checkpoint = crash_ckpt
else:
    print("      No checkpoint found → fresh LoRA adapter")
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj"
        ],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model                  = get_peft_model(base_model, lora_config)
    resume_from_checkpoint = None
 
model.print_trainable_parameters()
 
# ── Step 5: Dataset ───────────────────────────────────────────────────────────
print("\n[5/7] Loading dataset...")
dataset = load_dataset(
    "json",
    data_files={"train": TRAIN_FILE, "validation": VAL_FILE}
)
 
train_dataset = dataset["train"]
val_dataset   = dataset["validation"]
 
print(f"      Train samples : {len(train_dataset):,}")
print(f"      Val samples   : {len(val_dataset):,}")
 
# Quick sanity check — print first sample (trimmed)
print("\n      First training sample (first 300 chars):")
print("      " + train_dataset[0]["text"][:300].replace("\n", "\n      "))
 
# ── Step 6: SFT config ────────────────────────────────────────────────────────
print("\n[6/7] Building SFT config...")
 
sft_config = SFTConfig(
    output_dir                  = CHECKPOINT_DIR,
    num_train_epochs            = NUM_EPOCHS,
    per_device_train_batch_size = BATCH_SIZE,
    per_device_eval_batch_size  = BATCH_SIZE,
    gradient_accumulation_steps = GRAD_ACCUM,
    learning_rate               = LR,
    fp16                        = False,
    bf16                        = True,
    logging_steps               = 10,       # print loss every 10 steps
    eval_strategy               = "steps",
    eval_steps                  = 100,      # evaluate every 100 steps
    save_strategy               = "steps",
    save_steps                  = 100,      # checkpoint every 100 steps
    save_total_limit            = 3,        # keep last 3 checkpoints only
    load_best_model_at_end      = False,
    report_to                   = "none",
    warmup_steps                = 20,
    lr_scheduler_type           = "cosine",
    optim                       = "paged_adamw_8bit",
    max_length                  = MAX_LEN,
    dataset_text_field          = "text",
    remove_unused_columns       = True,
    packing                     = True,     # pack short samples → faster training
)
 
trainer = SFTTrainer(
    model            = model,
    processing_class = tokenizer,
    train_dataset    = train_dataset,
    eval_dataset     = val_dataset,
    args             = sft_config,
)
 
# ── Step 7: Train ─────────────────────────────────────────────────────────────
print("\n[7/7] Starting training...")
print("=" * 60)
print(f"  Total samples   : {len(train_dataset):,}")
print(f"  Epochs          : {NUM_EPOCHS}")
print(f"  Effective batch : {BATCH_SIZE * GRAD_ACCUM}")
print(f"  Checkpoints at  : {CHECKPOINT_DIR}")
print(f"  Final model at  : {OUTPUT_DIR}")
print("=" * 60)
 
trainer.train(resume_from_checkpoint=resume_from_checkpoint)
 
# ── Save final model ──────────────────────────────────────────────────────────
print("\nSaving final model...")
trainer.save_model(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
 
# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TRAINING COMPLETE!")
print(f"  Final model saved to : {OUTPUT_DIR}")
print(f"  Training loss        : {trainer.state.log_history[-1].get('train_loss', 'see logs')}")
print()
print("Next steps:")
print("  1. Test the model  → python test_model.py")
print("=" * 60)