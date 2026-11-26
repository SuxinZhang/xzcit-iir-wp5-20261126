# WP5 接口与部署契约

本文件记录 WP5 接口和部署方案。代码和实机验收状态见第 7 节。

## 1. 调用链与范围

Web-Next 通过已鉴权 WebSocket 转发交互信令。音频守护进程负责仲裁与媒体会话。ROS 节点转接安全状态、巡逻事件和语音意图。部署文件提供 MediaMTX、AEC、用户级服务和验收脚本。

WP5 启用后，Web-Next 拒绝旧喇叭测试、录音和录音播放入口，并停止通过 WebSocket JSON 发送相机帧。媒体使用 WebRTC。代码实现不证明目标机已安装或通过硬件验收。

## 2. 可直接调用的 Python 接口

包路径：`Master/ROS/ros2_ws/src/iir_interaction/`。

```python
from iir_interaction.arbitration import AudioArbiter
from iir_interaction.contracts import AudioRequest
from iir_interaction.voice import announcement_for, command_from_text

arbiter = AudioArbiter()
decision = arbiter.acquire(AudioRequest('session-001', 'remote_announcement'))
released = arbiter.release('session-001')
text = announcement_for('departure')
intent = command_from_text('暂停巡逻')
```

| 接口 | 输入 | 输出与失败方式 |
| --- | --- | --- |
| `AudioRequest(request_id, source)` | 非空请求标识、下表中的来源 | 不可变请求；无效输入抛出 `ValueError` |
| `AudioArbiter.acquire(request)` | `AudioRequest` | `AudioDecision(accepted, owner, interrupted)`；复用当前所有者标识抛出 `ValueError` |
| `AudioArbiter.release(request_id)` | 非空请求标识 | 释放成功为 `True`；非当前所有者为 `False`；空标识抛出 `ValueError` |
| `AudioArbiter.owner` | 无 | 当前 `AudioRequest`；空闲为 `None` |
| `announcement_for(event)` | 下表中的事件 | 播报文本；未知事件抛出 `ValueError` |
| `command_from_text(text)` | 四条完整识别文本之一 | `VoiceCommand` 枚举；未知文本抛出 `ValueError` |

### 2.1 音频优先级

| `source` | 优先级 | 触发方 |
| --- | --- | --- |
| `sos` | 3 | WP2 安全状态适配器 |
| `remote_announcement` | 2 | WP4 Gateway 远程喊话入口 |
| `intercom` | 2 | WP4 Gateway 双向对讲入口 |
| `patrol_tts` | 1 | WP3 巡逻事件适配器 |
| `local_dialogue` | 1 | WP5 本地语音交互适配器 |

同级和低级请求返回 `accepted=False`，并保留当前所有者。
高级请求返回 `accepted=True`，`interrupted` 为被抢占请求。
没有请求队列。释放所有者后保持空闲，不自动恢复被抢占音频。

请求标识由适配器生成。每个会话使用新标识。
适配器必须在一个事件循环中串行执行完整的申请、停止旧输出、启动新输出流程。
媒体操作尚未结束时，不得并发处理下一条申请或释放事件。
单个仲裁器实例属于车端音频守护进程。不得每个 HTTP 请求创建一个实例。
Gateway 只能提交远程来源，不能接受浏览器自行指定 `sos`。

`accepted=True` 只表示取得逻辑预留，不表示设备已播放。
适配器必须先停止 `interrupted` 对应的输出，再启动新输出。
仲裁器在返回决策时已切换逻辑预留，实际播放状态由适配器单独记录。
停止失败时必须显式报告失败，不启动新输出，并保留被抢占请求的实际输出记录。
此后适配器必须拒绝新播放申请，不再调用 `acquire`，直到确认旧输出停止。
确认旧输出停止后，若新请求仍有效，再执行其启动流程；否则按来源的释放规则取消它。
非 SOS 输出启动失败时，释放新请求并报告失败，不恢复旧音频。
SOS 输出启动失败时，上报失败并保留 SOS 预留，直到权威 SOS 状态解除。
播放完成、会话断开或取消时使用原请求标识释放预留。
旧会话的迟到完成通知不能释放新会话。
SOS 预留只由安全状态适配器在权威 SOS 状态解除后释放。
停止远程会话不得解除 SOS，也不得复位 STM32 安全状态。

### 2.2 巡逻事件与语音意图

| WP3/WP2 输入 `event` | 文本 | 音频来源 |
| --- | --- | --- |
| `departure` | 开始巡逻。 | `patrol_tts` |
| `turning` | 前方转弯，请注意避让。 | `patrol_tts` |
| `obstacle` | 前方有障碍物，暂停通行。 | `patrol_tts` |
| `arrival` | 已到达巡检点。 | `patrol_tts` |
| `low_battery_return` | 电量不足，返回充电。 | `patrol_tts` |
| `sos` | 紧急呼救，请管理员处理。 | `sos` |

| ASR 完整识别文本 | 输出意图 | 消费方 |
| --- | --- | --- |
| 暂停巡逻 | `pause_patrol` | WP3 巡逻状态机 |
| 继续巡逻 | `resume_patrol` | WP3 巡逻状态机 |
| 报告电量 | `report_battery` | WP5 查询电量并播报 |
| 呼叫管理员 | `call_admin` | WP4 告警入口 |

ASR 适配器负责唤醒和识别。命令映射接受四条固定指令的常见 ASR 同音字，并在转发前还原为规范短语；带否定的句子不执行。不做开放式自然语言理解或命令补全。
`resume_patrol` 必须经过现有安全授权链，不能直接发布 `cmd_vel`。
`call_admin` 不等同于解除或触发 STM32 SOS。

## 3. WebSocket 信令与本机 API

浏览器使用已鉴权的 Web-Next WebSocket，发送 `t=interaction` 和非空 `request_id`。响应类型为 `interaction_reply`，包含同一 `request_id`、`ok` 及 `data` 或 `message`。会话所有者由服务端连接确定。

| `action` | 请求字段 | 作用 |
| --- | --- | --- |
| `create` | `mode`：`intercom`、`remote_announcement` 或 `video` | 创建会话预留 |
| `offer` | `session_id`、`kind`、`sdp` | 协商 `publish`、`microphone` 或 `camera` 媒体 |
| `activate` | `session_id` | 发布连接成功后启动车端 RTSP 播放 |
| `delete` | `session_id` | 关闭该连接拥有的会话 |
| `status` | 无 | 查询音频状态 |

Rust 代理使用 Bearer 令牌访问 `127.0.0.1:8095`。音频守护进程提供 `POST /sessions`、`POST /sessions/{sid}/offer`、`POST /sessions/{sid}/activate`、`DELETE /sessions/{sid}`、`POST /owners/{owner}/close`、`GET /status`、`POST /speak`、`POST /sos`、`POST /recognize` 和 `GET /commands/next`。这些接口属于本机服务，不向浏览器直接开放。WebSocket 信令传输 SDP，不传输 PCM、WAV、Base64 音频或视频帧。

发布客户端必须先应用 SDP 应答，等待 WebRTC `connectionState=connected`，再发送 `activate`。服务端不能在返回 SDP 应答之前读取 `platform_voice`；实机已复现该顺序导致 RTSP 404。

## 4. MediaMTX 与统一相机管道预留契约

媒体端点由部署配置提供给 Gateway。浏览器不硬编码主机和端口。
以下是已配置的 MediaMTX 路径，不表示已部署。

| MediaMTX 路径 | 生产者 | 消费者 | 浏览器端接口 |
| --- | --- | --- | --- |
| `camera` | WP3 统一采集/分发管道，H.264 | 管理端视频 | `/camera/whep` |
| `robot_mic` | WP5 音频守护进程，Opus | 平台对讲接收 | `/robot_mic/whep` |
| `platform_voice` | 获授权的平台麦克风，Opus | WP5 车端播放适配器 | `/platform_voice/whip` |

远程喊话只建立平台到车端的音频。
双向对讲还订阅 `robot_mic`。
车端播放适配器消费 `platform_voice`，送入唯一受仲裁的喇叭输出。
AEC 处理车端麦克风采集信号，并使用实际喇叭播放信号作为回声参考。
`robot_mic` 发布 AEC 处理后的采集音频，ASR 也消费处理后的采集音频。
WHIP/WHEP 发布与订阅权限必须和控制会话绑定。
MediaMTX 本身不替代音频所有权仲裁。
结束会话时关闭对应 WebRTC 资源，并停止该会话的车端输出。

WP3 必须向 WP5 提供同一相机采集管道的流地址与编码信息。
WP5 不新增直接打开 `/dev/video*` 的相机进程。
部署前必须核对 MediaMTX 版本、鉴权配置、车端消费方式和 AEC 设备。
配置要求部署者明确提供设备地址。

## 5. ROS 与部署边界

本包使用 `ament_python` 包布局，并提供 ROS 节点和音频守护进程。
WP2/WP3/WP4 的消息定义确定后，在适配层转换为第 2 节的数据。
这样不把尚未确认的 ROS 消息类型写成已存在接口。
当前仓库其他 ROS 源码未提供该节点订阅的 `/chassis/sos_active`、`/interaction/patrol_event`、`/battery_voltage` 生产者，也未提供 `/interaction/command` 消费者。WP2 和 WP3 的实际接口仍需接入。

| 提供方 | WP5 需要的数据或能力 |
| --- | --- |
| WP2 | 权威 SOS 激活/解除状态；固件停车仍由 STM32 本地处理 |
| WP3 | 六种巡逻事件、电量查询、暂停/继续巡逻入口、统一相机流 |
| WP4 | 登录会话、远程音频请求、告警上报、媒体端点配置 |
| WP5 设备联调 | 播放/采集设备标识、AEC 配置、TTS/ASR 模型路径 |

服务依赖：设备与音频会话就绪 → MediaMTX → 车端音频适配器 → Gateway → Web。
统一相机管道就绪后才启动相机推流消费者。
`After=` 只约束 systemd 启动顺序，不证明服务已就绪。
实际启动单元需要服务各自的就绪条件，不能据此声称 60 秒上线。

udev 稳定名称保留为 `/dev/iir_chassis`、`/dev/iir_lidar`、`/dev/iir_camera`。
规则需使用实机的序列号或物理路径匹配。
尚未读取实机属性。规则生成器要求显式选择设备，不替换已有服务。

WP5 启用后，Web-Next 拒绝旧的音频测试、录音及播放入口。还需在目标机验证不存在其他绕过仲裁的音频进程，并验证 SOS 抢占。

## 6. 测试与后续验收

在仓库根目录运行纯契约测试：

```bash
PYTHONPATH=Master/ROS/ros2_ws/src/iir_interaction python3 -m unittest discover -s Master/ROS/ros2_ws/src/iir_interaction/test -p test_interaction.py -v
python3 -m unittest discover -s deploy/test -v
```

音频服务完整测试需要先在虚拟环境安装 `aiohttp`，再运行：

```bash
PYTHONPATH=Master/ROS/ros2_ws/src/iir_interaction "$IIR_PYTHON" -m unittest discover -s Master/ROS/ros2_ws/src/iir_interaction/test -v
```

这些离线测试不能证明实机媒体、音频、ROS 链路、延迟或启动时间。目标机仍需按第 7 节验证。

## 7. 部署实现与实机验收状态

本节记录部署实现和验收状态。已在 Orange Pi 的独立目录部署音频与测试网页。WP5 实机验收尚未完成。板端记录见第 9 节。

`deploy/mediamtx/render.py` 生成 MediaMTX 1.11.3 配置。WebRTC HTTP 和 RTSP 只监听 `127.0.0.1`；WebRTC UDP 使用 8189 端口。`camera` 从 `IIR_CAMERA_UPSTREAM` 拉流，使用 WP3 的唯一相机源；本部署不打开 `/dev/video*`。编码是否使用 RK3588 MPP 必须由 WP3 管道核实。`robot_mic` 使用 AEC 后的 PulseAudio source 发布 Opus。`platform_voice` 由音频守护进程读取并经仲裁播放。

本地已使用 MediaMTX 1.11.3 加载生成的配置并启动监听。合成 WebRTC 客户端的 WHIP 请求返回 201，ICE 和 DTLS 已连接。合成静音音频经 WHIP 发布后，WHEP 接收端收到音频帧；两个会话的 DELETE 均返回 200。匿名 camera WHEP 请求返回 400 和鉴权失败信息。这些回环测试不证明 AEC、声卡、浏览器、400 ms 延迟或实机业务链路。

MediaMTX 本机 HTTP 客户端使用 `iir-interaction` 和 `IIR_MEDIA_AUTH_SECRET`。权限限于发布 `platform_voice`、读取 `camera` 和 `robot_mic`。本机 RTSP 允许发布 `robot_mic`、读取 `platform_voice`。MediaMTX 信令须经 Web-Next 的认证代理。Caddy 使用明确提供的局域网域名和受客户端信任的证书；`IIR_WEB_ORIGIN` 填对应 HTTPS 源。证书必须覆盖该域名，客户端必须信任签发机构。运行 Caddy 的用户还需获得绑定 443 端口的权限。

目标机先安装 MediaMTX 1.11.3、Caddy、PulseAudio 的 WebRTC echo-cancel 模块、GStreamer 的 PulseAudio、Opus 和 RTSP 插件（Debian/Ubuntu 的 `gstreamer1.0-rtsp`）、ROS 2、colcon、Rust 与 Python venv。准备 Piper 和 Sherpa-ONNX 模型文件。Rust 依赖需预先缓存，构建使用 `cargo --offline`。Python 依赖安装需要访问已配置的软件源。

将 `deploy/wp5.env.example` 复制为 `~/.config/iir/wp5.env`，设置文件权限为 0600，填写所有空值。密码和令牌由部署者生成，不能使用空值。`IIR_PYTHON` 指向待创建的虚拟环境中的 `bin/python`；`IIR_AEC_STATE` 和 `IIR_MEDIAMTX_CONFIG` 指向用户可写目录中的文件。AEC 的 master 必须是 `pactl list short sources` 和 `pactl list short sinks` 显示的确切名称。`IIR_WEB_ORIGIN` 与 Caddy 域名一致。安装脚本使用当前环境变量，因此运行前按 shell 语法加载填写好的环境文件。

```bash
set -a
source ~/.config/iir/wp5.env
set +a
./deploy/install.sh
```

脚本创建 venv、安装 Python 包、构建 ROS 节点和离线构建 Web-Next，把 `deploy/kws/keywords.txt` 安装到 `IIR_KWS_KEYWORDS` 指向的路径，并复制新单元。关键词文件是唤醒词检测器实际读取的文件，缺它时检测器只会使用模型自带的默认词条。目标路径已有同名文件且内容不同时不覆盖，只提示仓库内路径，避免重装静默回退现场调参。已有同名用户单元时退出。脚本不启用服务、不替换原有服务。检查现有 Web 服务及端口占用后，由操作员决定何时切换，再执行：

```bash
systemctl --user enable --now iir.target
loginctl enable-linger "$USER"
```

`After=` 只规定顺序。单元使用 socket、PulseAudio 设备和认证 HTTP 请求检查启动前条件。检查失败时单元失败；检查成功也不证明相机流、WebRTC 或物理音频正常。检查等待服务就绪，超时 10 秒即失败。目标机仍需验证启动时序。卸载前加载相同环境文件，运行 `./deploy/uninstall.sh`；脚本停止并移除未被修改的 WP5 用户单元，保留环境文件、模型、venv、构建产物和现有服务。

固定设备名称之前，由操作员在目标机选定三个实际设备：

```bash
./deploy/generate-udev.py --chassis /dev/实际底盘设备 --lidar /dev/实际雷达设备 --camera /dev/实际相机设备 > /tmp/99-iir.rules
```

脚本从 `udevadm` 读取每个设备的 DEVPATH 与子系统，拒绝重复路径和错误子系统。核查生成规则后，由操作员安装到 `/etc/udev/rules.d/` 并按系统流程重新加载。DEVPATH 随物理连接位置变化时必须重新生成。不能把脚本输出视为已安装。

加载环境文件后运行 `./deploy/health.sh` 检查单元状态和音频 HTTP 状态。`./deploy/measure-boot.sh` 输出检查完成时距离本次开机的时间。它只测脚本所检查的条件；只有在实际相机画面、双向音频、ASR、ROS、网关与 Web 均验证可用后，才能用记录的时间评价 60 秒要求。它不是全链路自动验收。

在目标 Wi-Fi 和实际浏览器上分别测量双向端到端音频延迟，并记录测量方法、样本和最大值。验证双向音频无明显啸叫、远程喊话抢占巡逻播报、SOS 抢占及会话关闭。延迟小于 400 ms、60 秒上线和实机安全行为均未由离线检查证明。

现有 WP3 相机只提供 ROS compressed image/MJPEG；仓库当前未确认可用的 RTSP 上游。必须先由 WP3 提供统一相机源的 RTSP 地址与硬件 H.264 编码证据，再启用视频。

## 8. 2026-11-25 本地验证记录

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| `iir_interaction` 的 unittest | 25 项通过 | 鉴权、所有者、进程停止、SOS 优先级、媒体资源清理和 ROS 回调并发 |
| `web/test/interaction.test.cjs` | 8 项通过 | 客户端信令、取消、轨道释放、抢占和失败处理 |
| `deploy/test` | 4 项通过 | 配置权限、设备规则、就绪检查和 AEC 加载失败处理 |
| `cargo test -- --test-threads=1` | 52 项通过 | 现有 Rust 测试与新增代理测试，串行执行 |
| `cargo build` | 通过 | 宿主机构建，不代表 ARM 板端运行 |
| `systemd-analyze --user verify deploy/systemd/*` | 通过 | 单元语法与依赖引用，不证明设备和进程已就绪 |
| Python 包安装与入口元数据 | 通过 | `interaction_service`、`interaction_asr`、`interaction_node` 三个入口已生成 |

真实 WebSocket 测试命令：

```bash
"$IIR_PYTHON" Master/Web-Next/tools/wp5_ws_worker_test.py Master/Web-Next/target/debug/web_next
```

测试音频服务故意等待 3 秒。期间 `ping` 和 `motion_stop` 的回执均在 200 ms 内收到。
该时间是本机测试阈值，不是机器人停车时间。

合成媒体测试需额外安装 `aiortc`，并提供 MediaMTX 1.11.3 二进制：

```bash
"$IIR_PYTHON" Master/Web-Next/tools/wp5_media_test.py /实际路径/mediamtx
```

该测试在本机使用 8554、8889 和 8189 端口，运行前须确认没有生产服务占用。
测试确认合成音频样本经 WHIP/WHEP 到达接收端，并删除两个媒体会话。
它不打开声卡或相机。

默认并行的 Rust 全量测试曾出现 46 项通过、6 项失败。
首个失败包含 `test_cancel_nav_goal_clears_failed_and_active_goal` 的共享队列断言，随后出现锁中毒。
`ros.rs` 本轮零改动；只读检查发现两个既有测试对全局队列有顺序依赖。
同代码串行执行通过，基线两次默认/并行执行未复现。
本次没有修改范围外 ROS 测试，不能报告默认并行全量测试稳定通过。

aiohttp 3.14 对 BasicAuth 发出弃用提示。运行依赖限制为 `aiohttp>=3.9,<4`。
板端模型、设备与 ARM 运行的后续验证见第 9 节。浏览器对讲、AEC 效果、400 ms 和 60 秒要求仍未验收。

## 9. 2026-11-25 Orange Pi 部署记录

提交前相关检查：Python 35 项中 33 项通过、2 项因缺少板端模型样本跳过；前端 10 项、部署 5 项、Rust 串行 53 项通过。此前 ARM64 musl release 构建和板端 systemd 单元校验通过。`git diff --check` 通过。aiohttp BasicAuth 弃用提示仍存在。

目标机 `orangepi@192.168.31.148`，目录 `/home/orangepi/iir-wp5`。源码位于 `src/`，ARM 程序位于 `bin/`，模型位于 `models/`，运行状态位于 `state/`。环境文件为 `~/.config/iir/wp5.env`，权限 0600。没有刷写下位机，没有发送运动命令。

已安装 PulseAudio、WebRTC AEC、GStreamer Opus/RTSP 插件、Python venv、colcon、MediaMTX 1.11.3 和 Caddy 2.11.9。保留原 `/etc/pulse` 配置。WP5 使用 `pulse.pa` 和 `PULSE_SERVER=unix:/run/user/1000/pulse/native`，不使用原匿名 `/tmp/pulse-socket`。

选择输入 `alsa_input.usb-Timesintelli_USB_Audio_Device_123482-00.multichannel-input`，输出 `alsa_output.platform-es8388-sound.stereo-fallback`。已创建 `iir_aec_source` 与 `iir_aec_sink`。3 秒 AEC 录音收到 47,672 个采样，其中 25,417 个非零；该记录不能证明语音清晰度或 AEC 效果。

Piper `zh_CN huayan medium` 在板端生成 94 KB WAV。`POST /speak` 返回 `played:true`，只证明 Piper 和 paplay 正常退出，现场听感未确认。Sherpa 离线模型为 `sherpa-onnx-zipformer-zh-en-2023-11-22` 的 INT8 encoder/joiner。模型文件本机与板端 SHA-256 一致。板端加载耗时 1.585 秒；官方 3.38 秒测试音频解码耗时 0.138 秒。Piper 合成的“小巡，暂停巡逻。”识别结果为“小巡暂停巡逻”，映射为 `pause_patrol`；此测试没有向运动控制链发送命令。实际麦克风唤醒准确率未验收。当前唤醒词为“小巡”。

电脑通过 SSH 隧道向板端音频服务发送信令，媒体走局域网 UDP。合成静音 WHIP 发布连接成功，发送 58 个 RTP 包；WHEP 收到车端麦克风帧，含 960 个采样。`activate` 返回 `starting`。删除会话后 `owner=null`、`sessions={}`、`blocked=null`。这不是浏览器或端到端声学验收。

新网页使用 loopback 8089。Caddy 使用 `https://192.168.31.148:8443`，证书为 `state/wp5.crt`，SAN 包含该 IP。通过明确指定该证书验证 HTTPS，返回 200。浏览器须信任该证书后才能验证安全上下文和麦克风授权。没有修改用户电脑的证书信任。网页复用旧服务登录密码哈希。原 `c50c-web-next` 8088 和原 bridge 均保持活动。新网页没有启动第二个 ROS Web bridge，因此不作为实车控制入口。

已启用 `iir-aec`、`iir-mediamtx`、`iir-audio`、`iir-mic`、`iir-asr`、`iir-interaction-ros`、`iir-web`、`iir-https` 的用户开机启动；`iir-pulse` 由 AEC 依赖启动。检查时九个单元均为 active，用户 Linger=yes。没有重启整机，所以没有证明 60 秒上线。没有启用完整 `iir.target`，以免其正式 8088 bridge 与原服务冲突。测试端口通过 `~/.config/systemd/user/iir-web.service.d/staging.conf` 和 `iir-https.service.d/staging.conf` 指定。

`IIR_CAMERA_UPSTREAM` 明确留空。此时 MediaMTX 不生成 `camera` 路径；视频请求失败，不打开相机设备。WP3 仍须提供统一 RTSP/H.264 源。WP2 SOS、电量，以及 WP3 巡逻事件和命令消费者仍待联调。

部署审查还发现未验收的生命周期条件：设备枚举慢于 AEC 查询时启动失败；PulseAudio 异常退出后的 AEC 状态文件和依赖失活尚未测试。ASR 单元已增加 systemd `Restart=on-failure` 与 2 秒重启间隔；AEC/PulseAudio 仍未增加自动恢复。这些条件阻止报告完整整机部署验收通过。

## 10. 语音联调后的提交状态

用户已确认测试声音播放正常。唤醒短语“小巡小巡”回应“我在”。识别已改用 Silero VAD，默认在停顿 0.4 秒后送离线 ASR（`IIR_ASR_MIN_SILENCE_SECONDS` 可调）。按用户要求，识别文本包含 `小[巡寻群]小[巡寻群]` 时也触发回应，不要求关键词模型同时命中。每个语音片段最多请求一次回应，继续服从现有音频仲裁。

2026-11-25 唤醒率优化：现场唤醒率偏低的主因是关键词模型被当作离线解码器使用，未调用 `input_finished()`、尾部静音仅 0.5 秒且未调用 `reset_stream()`，同时唤醒只能依赖精确 ASR 文本，唤醒后也没有指令窗口。现已修复流式解码调用，补 0.66 秒尾静音，命中后重置流；单次“小巡”静默打开 6 秒指令窗口，连续两次回应“我在”，同一句含唤醒词加指令时直接执行指令不回应；KWS 命中为权威证据，文本侧接受常见同音字并排除“小群体/小群组”；四条指令支持同音字并统一发送规范短语；`/speak` 与 `/recognize` 请求失败只记录 `dispatch_error`，不再终止进程；ASR 单元增加 `Restart=on-failure`。唤醒词文件 `deploy/kws/keywords.txt` 增加“小能”这一独立声学拼写（“小寻/小群”与“小巡”是同一 token 序列，无需另列），并由 `install.sh` 安装到 `IIR_KWS_KEYWORDS`；目标路径已有不同内容时不覆盖，避免重装静默回退现场调参。上述改动通过本地与板端单元测试：`test_wake.py` 16 项、部署 21 项、整包 68 项（跳过 2 项）。

已保存的 5 次试喊转写中，模糊匹配命中 2 次，另外 16 段普通语音转写未触发。该结果不证明现场唤醒率已达标。诊断录音为显式配置启用，当前板端已关闭保存；已有 WAV 保留在板端，不纳入 Git。

USB 描述符暴露四路采集数据，不表示四个物理麦克风。12 秒样本中第 1/3 路完全相同，其余与第 1 路最大差值为 3 个采样计数。后续同步测试发现 AEC source/module 已消失，新 AEC 录音为零字节，无法完成同次发音的原始/AEC 对比。已保留陈旧状态文件并恢复 AEC 模块，确认 ASR 与麦克风发布连接到恢复后的 AEC source。模块消失原因未确定，没有加入自动恢复。
