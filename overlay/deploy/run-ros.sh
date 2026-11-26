#!/usr/bin/env bash
set -euo pipefail
: "${IIR_ROS_SETUP:?}" "${IIR_ROS_WS_SETUP:?}"
set +u
source "$IIR_ROS_SETUP"
source "$IIR_ROS_WS_SETUP"
set -u
exec ros2 run iir_interaction interaction_node
