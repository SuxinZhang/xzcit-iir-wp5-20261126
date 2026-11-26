#!/usr/bin/env bash
set -euo pipefail
: "${IIR_ASR_SOURCE:?}" "${IIR_RTSP_BASE:?}"
exec gst-launch-1.0 -e pulsesrc device="$IIR_ASR_SOURCE" ! audioconvert ! audioresample ! opusenc ! rtspclientsink location="${IIR_RTSP_BASE%/}/robot_mic" protocols=tcp
