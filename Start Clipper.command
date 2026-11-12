#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print 'One-time setup is needed. Follow the Local dashboard setup in README.md.'
  read '?Press Enter to close.'
  exit 1
fi
.venv/bin/python app.py
clipper_exit=$?
if (( clipper_exit != 0 )); then
  read '?Press Enter to close.'
fi
exit $clipper_exit
