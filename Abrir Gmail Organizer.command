#!/usr/bin/env bash
# Duplo-clique neste ficheiro para abrir o Gmail Organizer.
# (macOS e Linux. No Windows usa o "Abrir Gmail Organizer.bat".)
set -euo pipefail

cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Não encontrei o Python. Instala-o em https://www.python.org/downloads/ e tenta outra vez."
  read -r -p "Carrega Enter para fechar."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Primeira utilização: a preparar o ambiente (demora um minuto)…"
  "$PYTHON" -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip --quiet
  ./.venv/bin/python -m pip install -r requirements.txt --quiet
  echo "Pronto."
fi

echo "A abrir o Gmail Organizer no browser…"
echo "Fecha esta janela quando acabares."
./.venv/bin/python -m gmail_organizer ui "$@"
