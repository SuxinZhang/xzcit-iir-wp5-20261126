# WP5 车端交互服务

`interaction_service` 监听 `127.0.0.1:8095`。所有请求都需要 `Authorization: Bearer` 和 `IIR_INTERACTION_TOKEN`。该令牌只供本机代理及节点使用。

必须配置 `IIR_MEDIAMTX_HTTP_BASE`、`IIR_MEDIA_AUTH_SECRET`、`IIR_RTSP_BASE`、`IIR_AUDIO_SINK`、`IIR_PIPER_MODEL`。MediaMTX HTTP 使用 `iir-interaction` 和 `IIR_MEDIA_AUTH_SECRET` 的 Basic 认证。RTSP 地址使用部署配置的本机读取权限。Piper、GStreamer、PulseAudio 工具必须安装。播放 sink 必须配置为 AEC sink。

安装包时使用 `pip install ".[asr]"`，以安装 `interaction_asr` 所需的 `sherpa-onnx` 和 `numpy`。`interaction_asr`并配置 `IIR_ASR_ENCODER`、`IIR_ASR_DECODER`、`IIR_ASR_JOINER`、`IIR_ASR_TOKENS`、`IIR_ASR_SOURCE`、`IIR_WAKE_WORD`、`IIR_ASR_VAD_MODEL`。识别器读取 16 kHz AEC source。Silero VAD 按 512 个采样持续检测，默认在语音停顿 0.4 秒后送离线识别（`IIR_ASR_MIN_SILENCE_SECONDS` 可调），不再按固定三秒切片。进程异常退出后由 systemd 在 2 秒后重启；连续失败受 `StartLimitBurst=5` 限制。

专用关键词模型同时检测“小巡”和“小巡小巡”，关键词文件示例见 `deploy/kws/keywords.txt`。单次唤醒保持静默并打开 6 秒指令窗口（`IIR_WAKE_WINDOW_SECONDS`），窗口内的下一段语音可以直接说指令；连续两次唤醒立即调用 `/speak` 回应“我在”，使用 `local_dialogue` 优先级。若同一句里同时包含唤醒词和指令，直接执行指令，不再播报“我在”。关键词命中是权威证据，ASR 文本只作补充；文本侧接受 `小[晓筱肖][巡寻群旬询循迅训逊熏勋勳薰]` 等常见同音字，但排除“小群体/小群组”。单独“小区”不触发。四条命令支持常见同音字（如“暂停巡罗”“继续寻逻”“报告电亮”“呼叫管理”），并统一发送规范短语到 `/recognize`；带否定的句子（如“不要暂停巡逻”）不执行。SOS、对讲或远程喊话占用输出时，仲裁器拒绝低优先级回应；播报或识别请求失败只记录 `dispatch_error`，不会终止 ASR 进程。

`interaction_node` 订阅 `/chassis/sos_active`、`/interaction/patrol_event`、`/battery_voltage`，并向 `/interaction/command` 发布业务意图。WP2 的 SOS 适配入口和 WP3 的巡逻事件、暂停及继续接口尚待接入。`call_admin` 只发布意图，WP4 接收端尚待接入。节点不发布速度指令。

会话在媒体进程存活后报告 `starting`。该状态不证明音频已经到达或扬声器已经播放。`video` 不占音频输出。MediaMTX、设备、实际识别和 ROS 链路需要现场验收。

ASR 将识别原文、音频长度、解码耗时、关键词耗时以及 `wake_source`、`woke`、`double`、`command`、`reply` 输出为 JSON 日志；启动时输出 `asr_config`，异步播报结果用 `asr_dispatch_result` 记录，服务请求失败用 `dispatch_error` 记录。默认不保存原始录音。显式设置 `IIR_ASR_RECORD_DIR` 后，保存所有 VAD 语音片段为 16 kHz 单声道 PCM WAV，文件权限 0600；日志用 `recording` 关联路径。该目录必须由部署者预先创建。清空配置并重启 ASR 可停止保存。板端日志位置由 systemd 配置为 `/tmp/iir-asr.log`。现场日志曾识别为“小心脚行”和“小区”；没有将这些常用词直接映射为唤醒，以避免误触发。当前模型直接中文热词编码失败，未启用热词。

关键词模型为 `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`，使用 chunk-8 INT8 encoder/joiner 和 FP32 decoder。必须配置 `IIR_KWS_ENCODER`、`IIR_KWS_DECODER`、`IIR_KWS_JOINER`、`IIR_KWS_TOKENS`、`IIR_KWS_KEYWORDS`。可选 `IIR_KWS_EXTRA_KEYWORDS` 在创建流时追加关键词，无需修改关键词文件；`IIR_KWS_THREADS`、`IIR_KWS_MAX_ACTIVE_PATHS`、`IIR_KWS_SCORE`、`IIR_KWS_THRESHOLD`、`IIR_KWS_TRAILING_BLANKS` 可调。关键词检测与 ASR 共用现有 VAD 音频片段，不新开麦克风。每段音频尾部补 0.66 秒静音并调用 `input_finished()`，命中后调用 `reset_stream()`，修复段尾唤醒未被解码的问题。日志增加 `keyword` 和 `keyword_ms`。板端旧样本集：双唤醒命中，单唤醒加命令、普通中英语音和静音未命中；部署 `deploy/kws/keywords.txt` 后必须在板端重测单唤醒召回率和误触发率。

2026-11-25 现场定位：USB 暴露四路采集数据，12 秒样本中第 1/3 路完全相同，第 2/4 路与第 1 路最大差值 3 个采样计数。后续两分钟同步测试的 AEC 文件为零字节，原因是 AEC source/module 已消失，不能作原始/AEC 对比。已归档陈旧状态并重新加载模块，检查 ASR 与 mic source-output 均连接到恢复后的 AEC source。未证明模块消失原因。
