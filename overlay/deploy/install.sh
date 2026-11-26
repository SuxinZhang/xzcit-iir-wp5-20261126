#!/usr/bin/env bash
set -euo pipefail
: "${IIR_DEPLOY_DIR:?}" "${IIR_PYTHON:?}" "${IIR_MEDIAMTX_BIN:?}" "${IIR_KWS_KEYWORDS:?}"
root=$(cd "$IIR_DEPLOY_DIR/.." && pwd)
unit_dir="$HOME/.config/systemd/user"
for unit in "$IIR_DEPLOY_DIR"/systemd/*; do
    test ! -e "$unit_dir/$(basename "$unit")" || { printf 'Unit exists: %s\n' "$unit" >&2; exit 1; }
done
test "$($IIR_MEDIAMTX_BIN --version)" = v1.11.3
venv_dir=$(dirname "$(dirname "$IIR_PYTHON")")
test ! -e "$venv_dir" || { printf 'Virtual environment path exists: %s\n' "$venv_dir" >&2; exit 1; }
python3 -m venv "$venv_dir"
"$IIR_PYTHON" -m pip install aiohttp numpy sherpa-onnx piper-tts -r "$root/Master/Gateway/requirements.txt" -r "$root/Master/OTA/requirements.txt" "$root/Master/ROS/ros2_ws/src/iir_interaction"
: "${IIR_ROS_SETUP:?}"
set +u
source "$IIR_ROS_SETUP"
set -u
colcon build --base-paths "$root/Master/ROS/ros2_ws/src" --packages-select iir_interfaces iir_vision_rknn iir_interaction iir_navigation_vision --build-base "$root/Master/ROS/ros2_ws/build" --install-base "$root/Master/ROS/ros2_ws/install"
cargo build --offline --release --manifest-path "$root/Master/Web-Next/Cargo.toml"
bash "$IIR_DEPLOY_DIR/install-keywords.sh" "$IIR_DEPLOY_DIR/kws/keywords.txt" "$IIR_KWS_KEYWORDS"
mkdir -p "$unit_dir"
for unit in "$IIR_DEPLOY_DIR"/systemd/*; do
    cp -n "$unit" "$unit_dir/"
done
systemctl --user daemon-reload
printf '%s\n' 'Units installed but not enabled. Review wp5.env and enable iir.target explicitly.' 'For startup without login: loginctl enable-linger USER'
