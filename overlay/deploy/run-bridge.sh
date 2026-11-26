#!/usr/bin/env bash
# Start the ROS Web bridge unless the deployment deliberately runs without it.
# 启动 ROS Web 桥接；部署明确不启用时正常退出。
#
# An empty IIR_WEB_BRIDGE means "no bridge in this deployment" (the legacy 8088
# service already owns that role), so the unit must not report a failure.
# IIR_WEB_BRIDGE 为空表示本部署不启用桥接（8088 旧服务已承担该职责），
# 单元应以成功结束而不是失败退出。
set -euo pipefail
if [ -z "${IIR_WEB_BRIDGE:-}" ]; then
    printf '%s\n' 'IIR_WEB_BRIDGE is empty: ROS Web bridge disabled for this deployment'
    exit 0
fi
: "${IIR_ROS_SETUP:?}" "${IIR_ROS_WS_SETUP:?}"
set +u
source "$IIR_ROS_SETUP"
source "$IIR_ROS_WS_SETUP"
set -u
exec python3 "$IIR_WEB_BRIDGE" --server http://127.0.0.1:8088
