#!/usr/bin/env bash
set -euo pipefail
: "${IIR_AEC_SOURCE_MASTER:?}" "${IIR_AEC_SINK_MASTER:?}" "${IIR_AEC_STATE:?}" "${PULSE_SERVER:?}"
pactl=${IIR_PACTL:-pactl}
systemctl=${IIR_SYSTEMCTL:-systemctl}
umask 077
reloaded=0

has_source() {
    "$pactl" list short sources | awk -v name="$1" '$2 == name {found=1} END {exit !found}'
}

# The state file is only a cache. PulseAudio drops the echo-cancel module when
# the USB microphone re-enumerates, but the file survives; the stale id then
# makes parec fail with "No such entity" forever while every unit still reports
# success, so the robot goes deaf with nothing failed to notice.
# 状态文件只是缓存：USB 麦克风重新枚举时 PulseAudio 会卸载回声消除模块而文件还在，
# 残留旧 id 会让 parec 一直报 No such entity，且所有单元都显示成功，机器人静默失聪。
module_id() {
    "$pactl" list short modules |
        awk '$2 == "module-echo-cancel" && $0 ~ /source_name=iir_aec_source( |$)/ {print $1; exit}'
}

# Sets reloaded=1 when the module had to be created, so callers know the
# existing parec stream is now attached to a source that no longer exists.
ensure() {
    local id created
    id=$(module_id) || return 1
    if [ -n "$id" ] && has_source iir_aec_source; then
        printf '%s\n' "$id" > "$IIR_AEC_STATE" || return 1
        reloaded=0
        return 0
    fi
    if [ -n "$id" ]; then
        "$pactl" unload-module "$id" || true
    fi
    rm -f "$IIR_AEC_STATE" || return 1
    has_source "$IIR_AEC_SOURCE_MASTER" || return 1
    "$pactl" list short sinks | awk -v name="$IIR_AEC_SINK_MASTER" '$2 == name {found=1} END {exit !found}' || return 1
    created=$("$pactl" load-module module-echo-cancel source_master="$IIR_AEC_SOURCE_MASTER" sink_master="$IIR_AEC_SINK_MASTER" source_name=iir_aec_source sink_name=iir_aec_sink aec_method=webrtc) || return 1
    [ -n "$created" ] || return 1
    if ! printf '%s\n' "$created" > "$IIR_AEC_STATE"; then
        "$pactl" unload-module "$created" || true
        return 1
    fi
    reloaded=1
}

# The sources the recorder streams are actually attached to. Checking this is
# stricter than checking that the module exists: the module can be present while
# parec is still on the raw microphone, which is the state that degrades the wake
# rate. parec is a symlink to pacat, so PulseAudio reports the client as "pacat".
# 录制流实际挂在哪些源上。这比"模块是否存在"更严格：模块在，parec 仍可能挂在原始
# 麦克风上，而那正是让唤醒率下降的状态。parec 是 pacat 的符号链接，PulseAudio 里
# 客户端名报的是 pacat。
recorder_sources() {
    local clients
    clients=$("$pactl" list short clients 2>/dev/null |
              awk '$3 == "pacat" || $3 == "parec" {print $1}' || true)
    [ -n "$clients" ] || return 1
    "$pactl" list short source-outputs 2>/dev/null |
        awk -v clients=" $clients " 'index(clients, " " $3 " ") {print $2}' || true
}

# A running parec stream does not fail when its source disappears: PulseAudio
# moves it to the raw microphone, so ASR keeps transcribing without echo
# cancellation and hears the robot's own TTS. Restarting ASR is the only thing
# that puts the stream back on iir_aec_source, and nothing else in the deployment
# notices, which is why this has to be a watchdog rather than a one-shot.
# 源消失时正在运行的 parec 不会报错，PulseAudio 会把流挪到原始麦克风上，识别继续但
# 失去回声消除、会听到自己的播报。只有重启 ASR 才能让流回到 iir_aec_source，而部署里
# 没有别的单元会发现，所以这里必须常驻看守而不能只在启动前跑一次。
check() {
    local aec current
    check_reason=
    if ! ensure; then
        check_reason='echo-cancel unavailable, master source or sink is missing'
        echo "aec: $check_reason" >&2
        return 0
    fi
    if [ "$reloaded" -eq 1 ]; then
        # A reload is a definite event: the old source is gone, so the live
        # stream is already on the wrong source and waiting gains nothing.
        # 重载是确定事件：旧源已经没了，正在跑的流肯定挂在错的地方，没必要等。
        echo "aec: reloaded echo-cancel module, restarting asr to reattach parec" >&2
        "$systemctl" --user restart iir-asr.service || true
        return 0
    fi
    aec=$("$pactl" list short sources | awk '$2 == "iir_aec_source" {print $1; exit}')
    current=$(recorder_sources) || current=
    [ -n "$current" ] || return 0
    [ -n "$aec" ] || return 0
    if printf '%s\n' "$current" | awk -v want="$aec" '$1 != want {found=1} END {exit !found}'; then
        check_reason="recorder is on source $(printf '%s' "$current" | tr '\n' ' ')instead of iir_aec_source ($aec)"
    fi
}

# Runs until stopped. An optional round count bounds the loop, which lets the
# unit be exercised without leaving a process behind.
# A restart is only issued on the second consecutive bad round: PulseAudio
# reports transient gaps while a stream is being moved, and reacting to those
# would restart ASR every check interval.
# 常驻运行；可选的轮数参数用于限制循环次数，便于测试时不留下残留进程。
# 只在连续两轮都异常时才重启：PulseAudio 在挪流的过程中会短暂报出空洞，若据此动作
# 就会每个检查周期都重启一次 ASR。
watch() {
    local rounds=${1:-0} round=0 strikes=0 reason=
    while :; do
        round=$((round + 1))
        check
        if [ -n "$check_reason" ]; then
            if [ "$check_reason" = "$reason" ]; then
                strikes=$((strikes + 1))
            else
                strikes=1
                reason=$check_reason
            fi
            if [ "$strikes" -ge 2 ]; then
                echo "aec: $reason, restarting asr to reattach parec" >&2
                "$systemctl" --user restart iir-asr.service || true
                strikes=0
                reason=
            fi
        else
            strikes=0
            reason=
        fi
        if [ "$rounds" -ne 0 ] && [ "$round" -ge "$rounds" ]; then
            break
        fi
        sleep "${IIR_AEC_CHECK_SECONDS:-15}"
    done
}

stop() {
    local id
    id=$(module_id) || return 1
    if [ -n "$id" ]; then
        "$pactl" unload-module "$id"
    fi
    rm -f "$IIR_AEC_STATE"
}

case "${1:?}" in
  start) ensure ;;
  watch) watch "${2:-0}" ;;
  stop) stop ;;
  *) exit 2 ;;
esac
