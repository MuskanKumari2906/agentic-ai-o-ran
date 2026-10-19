#!/usr/bin/env bash
# Local Ollama server tuned for the experiment runs: 2 parallel request slots, flash attention,
# models kept in VRAM. Restarts itself if it exits.
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KEEP_ALIVE=60m
export OLLAMA_MAX_LOADED_MODELS=2
while true; do
  "/c/Users/abhij/AppData/Local/Programs/Ollama/ollama.exe" serve
  echo "ollama exited, restarting in 10 s"; sleep 10
done
