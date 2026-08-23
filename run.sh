#!/bin/bash
# Jarvis launcher. Uses the project venv so system Python stays untouched.
#   ./run.sh            text mode
#   ./run.sh doctor     environment check
#   ./run.sh legacy     the original clap demo

cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "No virtualenv found. Run:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -e '.[voice]'"
  exit 1
fi

exec .venv/bin/python -m jarvis "$@"
