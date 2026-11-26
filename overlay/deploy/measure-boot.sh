#!/usr/bin/env bash
set -euo pipefail
: "${IIR_DEPLOY_DIR:?}"
"$IIR_DEPLOY_DIR/health.sh"
python3 -c 'import time; print(f"health check at {time.clock_gettime(time.CLOCK_BOOTTIME):.3f} seconds after boot")'
