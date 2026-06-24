# VHAL SOME/IP Log Analyzer

This project is a toolset for parsing, analyzing, and visualizing SOME/IP and CAN signal logs from the Skylark project. It leverages a fine-tuned local LLM (Qwen 3B) for fast payload extraction and includes Python scripts to decode and visualize vehicle signals.

## Prerequisites & Environment

The project relies on a pre-configured Python virtual environment (`venv`) located in the root directory. This environment already contains all required dependencies, including:
- `torch` (CUDA)
- `transformers`, `peft`, `accelerate`, `bitsandbytes`
- `fastapi`, `uvicorn`
- `requests`, `matplotlib`, `pandas`

**No extra installation is required if you use the provided `venv`.** If you need to recreate the environment, refer to the `requirements.txt` file.

## How to Run the Project

The workflow involves running a persistent model server and then executing client scripts or the GUI viewer.

### 1. Start the Model Server
The AI model must be loaded into GPU memory first. Start the server and **leave this terminal open**.

**Command Prompt / PowerShell:**
```cmd
cd \path\to\Vhal
venv\Scripts\activate
python model_server.py
```
*The server will load the base model and LoRA adapter (from `qwen_someip_2k_final`), then listen on `http://127.0.0.1:8765`.*

### 2. Run the Full VHAL Analyzer Pipeline
If you want to extract a specific time window from `ucl_90 1.log`, run it through the model, and decode the CAN signals automatically:

**Open a NEW terminal:**
```cmd
cd \path\to\Vhal
venv\Scripts\activate
python vhal_analyzer.py
```
The script will prompt you for:
- **Propertyname:** e.g., `VHAL_<MessageName>` or `<MessageName>__<SignalName>_rx_v`
- **Timestamp:** e.g., `06-01 17:50:04.803`

It generates:
- `latest_testing.txt` (the ±5s window logs)
- `test_results_output_batch.json` (raw LLM parse results)
- `result1.json`, `result2.json`, `result3.json` (final decoded signals)

### 3. Run Batch Inference Manually (Optional)
If you already have a `latest_testing.txt` file and just want to parse it without the analyzer script:
```cmd
venv\Scripts\activate
python batch_test_model.py
```

### 4. Launch the VHAL Viewer GUI
To visually inspect the decoded logs and signals in a graphical interface:
```cmd
run_viewer.bat
```
*(This batch file automatically uses the `venv` to start `vhal_viewer.py`.)*

## Project Structure
- `model_server.py`: FastAPI server hosting the fine-tuned Qwen model.
- `batch_test_model.py`: Client script that sends log lines to the model server in batches.
- `vhal_analyzer.py`: Main interactive pipeline for extracting and decoding specific signal events.
- `vhal_viewer.py` / `run_viewer.bat`: Graphical viewer for the results.
- `skylark_messages.json` / `skylark_signals.json` / `output 2.json`: Signal schema and metadata databases.
