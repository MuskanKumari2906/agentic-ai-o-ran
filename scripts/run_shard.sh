#!/usr/bin/env bash
# Supervised experiment shard: restarts after any crash; completed runs and LLM calls are reused.
cd "$(dirname "$0")/.."
SHARD="$1"
until PYTHONUNBUFFERED=1 python -W ignore -m sectwin.eval.run_experiments --shard "$SHARD" ${2:+--phases "$2"}; do
  echo "runner $SHARD exited with error, restarting in 30 s"; sleep 30
done
