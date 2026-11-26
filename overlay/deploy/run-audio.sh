#!/usr/bin/env bash
set -euo pipefail
: "${IIR_PYTHON:?}"
export PATH="$(dirname "$IIR_PYTHON"):$PATH"
exec "$IIR_PYTHON" -m iir_interaction.service
