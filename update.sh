#!/bin/zsh
# Refresh data and rebuild docs/index.html
cd "$(dirname "$0")"
.venv/bin/python -W ignore -m agent.build
