# VHAL SOME/IP Log Analyzer & AI Extraction Tool

This project is a comprehensive toolset for parsing, analyzing, and visualizing SOME/IP and CAN signal logs from the Skylark project. It leverages a locally downloaded and fine-tuned LLM (Qwen) for fast payload extraction from unstructured logs and includes a suite of Python scripts to manage the data pipeline, model fine-tuning, and signal decoding/visualization.

## Table of Contents
1. [Prerequisites & Environment](#prerequisites--environment)
2. [Project Structure](#project-structure)
3. [Local Model Information](#local-model-information)
4. [How to Run (Inference & Analysis)](#how-to-run-inference--analysis)
5. [Data Generation & Fine-tuning](#data-generation--fine-tuning)

---

## Prerequisites & Environment

The project relies on a pre-configured Python virtual environment (`venv`) located in the root directory. This environment already contains all required dependencies, including:
- PyTorch with CUDA support (`torch`)
- HuggingFace ecosystem (`transformers`, `peft`, `accelerate`, `bitsandbytes`)
- Server and API (`fastapi`, `uvicorn`, `requests`)
- Data processing and visualization (`matplotlib`, `pandas`)

**No extra installation is required if you use the provided `venv`.** If you need to recreate the environment on a new machine, refer to the `requirements.txt` file.

---

## Project Structure

The codebase is divided into two main categories: **Inference & Analysis** (for day-to-day use) and **Data Prep & Fine-Tuning** (for training the local model).

### 1. Inference & Analysis Pipeline
- **`model_server.py`**: A FastAPI server that loads the fine-tuned local Qwen model into GPU memory and exposes it via a REST API for fast inference.
- **`batch_test_model.py`**: Client script that sends raw log lines to the model server in batches to extract payload information.
- **`vhal_analyzer.py`**: The main interactive pipeline. It searches logs around a specific timestamp, queries the local model server, and fully decodes the CAN/Non-CAN signals.
- **`vhal_viewer.py` / `run_viewer.bat`**: A Graphical User Interface (GUI) to visually inspect the decoded logs and signals.
- **`vhal_analyzer_map.py`**: A standalone CLI tool for parsing and printing payloads to the terminal from generated output files.

### 2. Data Preparation & Model Fine-Tuning
- **`extract_signals.py`, `dbc_to_json 1.py`, `parse_catalogue.py`, `parse_signals_only.py`**: Tools to parse the TATA Skylark `.xlsx` catalogue and `.dbc` files into JSON schemas (`skylark_messages.json`, `skylark_signals.json`, `output 2.json`).
- **`latest_generate_dataset.py`**: Generates the training and validation datasets (`train_someip.jsonl`, `val_someip.jsonl`) from raw logs.
- **`latest_finetune.py`**: Script to fine-tune the local Qwen model using LoRA adapters.
- **`accuracy_test.py`**: Validates and tests the accuracy of the fine-tuned model against a test dataset.

---

## Local Model Information

This project uses a **local, downloaded, and fine-tuned LLM**. 
- The trained LoRA weights and configurations are stored in the `qwen_someip_2k_final` directory.
- Because the model runs locally on your machine, it ensures data privacy and fast inference without needing an internet connection to third-party APIs.
- The model is primarily responsible for identifying SOME/IP messages from raw text logs and cleanly extracting their payloads.

---

## How to Run (Inference & Analysis)

The standard workflow involves running the persistent model server and then executing the analyzer or GUI viewer.

### Step 1. Start the Model Server
The local AI model must be loaded into GPU memory first. Start the server and **leave this terminal open**.

**Command Prompt / PowerShell:**
```cmd
cd \path\to\Vhal
venv\Scripts\activate
python model_server.py
```
*The server will load the base model and local LoRA adapter from `qwen_someip_2k_final`, then listen on `http://127.0.0.1:8765`.*

### Step 2. Run the Full VHAL Analyzer Pipeline
Extract a specific time window from `ucl_90 1.log`, process it with the local model, and decode the CAN signals automatically:

**Open a NEW terminal:**
```cmd
cd \path\to\Vhal
venv\Scripts\activate
python vhal_analyzer.py
```
The script will prompt you for:
- **Propertyname:** e.g., `VHAL_<MessageName>` or `<MessageName>__<SignalName>_rx_v`
- **Timestamp:** e.g., `06-01 17:50:04.803`

The script will generate:
- `latest_testing.txt` (the ±5s window logs)
- `test_results_output_batch.json` (raw LLM parse results)
- `result1.json`, `result2.json`, `result3.json` (fully mapped and decoded signals)

*(Alternatively, use `python vhal_analyzer_map.py` to manually print and debug the parsed results from the terminal).*

### Step 3. Launch the VHAL Viewer GUI
To visually inspect the decoded logs and signals in a rich graphical interface:
```cmd
run_viewer.bat
```
*(This batch file automatically uses the `venv` to start `vhal_viewer.py` without needing to manually activate it).*

---

## Data Generation & Fine-tuning

If you need to update the catalogue or retrain the model with new data:

1. Update the `.xlsx` catalogue and run the parsers (e.g., `parse_catalogue.py`) to generate updated JSON databases.
2. Run `latest_generate_dataset.py` to create new `.jsonl` training data.
3. Execute `latest_finetune.py` to train a new LoRA adapter.
4. Replace the old weights in `qwen_someip_2k_final` with your new checkpoints.
5. Use `accuracy_test.py` to verify the new model's extraction accuracy.
