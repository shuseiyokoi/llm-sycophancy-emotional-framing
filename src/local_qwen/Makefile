# Local Qwen models served with llama.cpp (OpenAI-compatible API on localhost)
#
# Prereqs:
#   - llama.cpp (mac: `brew install llama.cpp`; HPC: build with -DGGML_CUDA=ON)
#
# Usage:
#   make download        # fetch both GGUF models (~9.5GB total)
#   make serve           # serve Qwen2.5-7B-Instruct on :8080
#   make serve-qwen3     # serve Qwen3-8B on :8080
#
# Note: `python call_qwen.py` starts/stops these servers by itself,
# so the serve targets are only needed for manual testing.

LLAMA_SERVER ?= llama-server
PORT ?= 8080
CTX ?= 8192
NGL ?= 99

MODELS_DIR := models
QWEN25 := $(MODELS_DIR)/Qwen2.5-7B-Instruct-Q4_K_M.gguf
QWEN3  := $(MODELS_DIR)/Qwen3-8B-Q4_K_M.gguf

download:
	mkdir -p $(MODELS_DIR)
	curl -L -C - -o $(QWEN25) https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf
	curl -L -C - -o $(QWEN3) https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf

serve:
	$(LLAMA_SERVER) -m $(QWEN25) --port $(PORT) -c $(CTX) -ngl $(NGL)

serve-qwen3:
	$(LLAMA_SERVER) -m $(QWEN3) --port $(PORT) -c $(CTX) -ngl $(NGL) --reasoning-budget 0
