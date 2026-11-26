#!/usr/bin/env bash
set -euo pipefail
: "${IIR_DEPLOY_DIR:?}"
systemctl --user is-active iir-pulse.service iir-aec.service iir-aec-watch.service iir-mediamtx.service iir-audio.service iir-mic.service iir-asr.service iir-interaction-ros.service iir-https.service iir-web.service iir-web-bridge.service
python3 "$IIR_DEPLOY_DIR/wait-ready.py" audio
