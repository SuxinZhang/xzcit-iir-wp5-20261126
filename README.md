# XZCIT-IIR WP5：WebRTC 对讲、离线语音与整机部署

本仓库是 WP5 的**独立 overlay 仓库**，包含：

- `overlay/Master/ROS/ros2_ws/src/iir_interaction/`：离线 TTS/ASR、关键词唤醒、音频仲裁、ROS 节点
- `overlay/deploy/`：MediaMTX 1.11.3 配置生成、AEC/PulseAudio、Caddy、udev、systemd、安装/卸载/健康检查脚本
- `overlay/Master/Web-Next/`：`interaction.rs`、`interaction.js`、`ws_control.rs`/`ws_video.rs`、Cargo 依赖与测试
- `docs/`：两版任务书、WP1–WP5 对照清单、`WP5_INTERFACES.md`

## 为什么单独建仓库

WP5 与 WP1–WP4 分仓，原因：

1. **系统层依赖完全不同**：WP5 依赖目标机的 PulseAudio/WebRTC AEC、MediaMTX、Caddy、systemd/udev、Piper/Sherpa-ONNX 模型；这些不是固件或 ROS 包的普通依赖，必须独立安装、独立卸载。
2. **部署与回滚边界独立**：音频/媒体/自启服务需要整机断电重启、60 秒上线、400 ms 对讲延迟等验收；单独仓库可以独立打版本、独立回滚，不影响 WP1–WP4 的固件和导航基线。
3. **硬件/模型条件独立**：麦克风、喇叭、AEC 设备名、KWS/ASR 模型、MediaMTX 端口都是现场配置；分仓避免这些目标机参数污染基础工程和 AI 仓库。
4. **依赖方向清晰**：WP5 需要 WP1–WP3 的相机流/SOS/巡逻事件，以及 WP4 的登录会话/告警/媒体入口；用 overlay 仓库显式表达“WP5 是上层”，而不是复制一份完整工程。

## 如何与基础工程组合

本仓库**不是独立可运行工程**。推荐顺序：

1. 先取 WP1–WP3 基础工程；
2. 应用 WP4 overlay；
3. 再应用本仓库 `overlay/`；
4. 对 `Master/Web-Next` 的共享文件（`src/main.rs`、`web/index.html`、`web/js/app.js`、`web/js/ws.js`、`web/styles/layout.css`、`Cargo.toml`/`Cargo.lock`）使用 **三方合并**，不要直接覆盖 WP4 的巡检/学生端改动。

```bash
# 仅示意：共享文件需按三方合并处理
rsync -a overlay/Master/ROS/ros2_ws/src/iir_interaction/ "$BASE/Master/ROS/ros2_ws/src/iir_interaction/"
rsync -a overlay/deploy/ "$BASE/deploy/"
```

## 关键依赖与边界

- WP3 必须提供统一相机源的 **RTSP/H.264** 地址；当前 `IIR_CAMERA_UPSTREAM` 为空，不能声称视频链路完成。
- WP2 必须提供权威 SOS 状态；WP3 必须提供巡逻事件、电量查询、暂停/继续巡逻入口。
- WP4 必须提供登录会话、远程音频请求、告警上报与媒体端点配置。
- 本仓库的 `iir_interaction` 和 `deploy` 不能直接发 `cmd_vel`；语音命令必须经过现有安全授权链。

## 本地验证摘要

| 检查 | 结果 |
| :--- | :--- |
| `iir_interaction` pytest | 66 通过，2 跳过，63 子测试通过 |
| `deploy/test` pytest | 21 通过 |
| `web/test/interaction.test.cjs` | 10/10 |
| WP5 Rust `cargo test -- --test-threads 1` | 53/53 |
| `deploy/WP5_INTERFACES.md` | 接口/部署契约与 Orange Pi 记录 |

## 上机前必读

`docs/WP1-WP5_任务书对照与上机验证清单.md` 的 WP5 条目仍未完成，重点：

- 实际音频设备、PulseAudio/WebRTC AEC、Piper/Sherpa-ONNX 模型
- MediaMTX + RK3588 MPP H.264 + WHEP
- 双向对讲 <400 ms、无啸叫、SOS/喊话抢占
- systemd/udev 冷启动 60 秒、全链路自动上线
- WP2/WP3 的 SOS/电量/巡逻事件/命令接口仍未接通

> 本仓库是本地快照/overlay，不是原仓库，也未向原仓库推送。
