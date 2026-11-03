#!/usr/bin/env bash
# Puerta de calidad: formato, estilo, tipos estrictos y pruebas (nunca tocan el hardware).
# Usa las herramientas del PATH o las de VENV=/ruta/al/venv/bin.
set -euo pipefail
cd "$(dirname "$0")/.."
V=${VENV:+$VENV/}
"${V}ruff" format --check src tests
"${V}ruff" check src tests
"${V}mypy"
"${V}pytest" -q
bash -n despliegue/*.sh
