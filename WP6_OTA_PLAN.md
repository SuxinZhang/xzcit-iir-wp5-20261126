# XZCIT-IIR 整车远程 OTA 升级专项执行规划书（WP6: OTA Agent Execution Spec）

> **致执行本规划书的 AI 开发助手**：
> 本文档是对 `AI_EXECUTION_PLAN.md`（WP1–WP5）与 `WP_INTEGRATION_FIX.md` 的增量扩展，专门用于落地整车 **远程 OTA 升级能力**。
> 硬件已锁定采用 **C50C-V4.3 `USART1`（`USB1.2` Type-C，板载 CH9102F + `DTR/RTS -> BOOT0/NRST` 一键下载电路）** 连接香橙派（Orange Pi 5 Pro）。
>
> **核心原则**：采用 **ST 官方出厂 ROM ISP（`stm32flash`）代理烧录 + 上位机软链接原子切换回滚 + RKNN 模型独立热更新**，**严禁**开发自研 STM32 Flash Bootloader，避免刷机变砖风险。

## 0. 全局硬性约束

1. **编码与双语注释红线（与主任务书完全一致）**：

   * 所有新建与修改的文件必须为 **UTF-8（无 BOM）+ LF（`\n`）** 换行。

   * 所有代码注释必须严格遵循 **“先写英文注释，再紧跟其准确的中文翻译”**（English-First, Then Chinese Translation），严禁直接写纯中文注释。

2. **独立存活原则（OTA Agent 独立于业务集群）**：

   * `iir-ota-agent.service` **必须独立于 `iir.target` 运行**，不得绑定在 `iir.target` 的 `PartOf=` 下。即使上位机主业务升级失败崩溃，OTA 代理与 HTTPS 入口依然保持在线，可自动或手动救砖回滚。

3. **支持纯局域网离线升级（标书场景刚需）**：

   * 校园实验室及电力巡检现场通常无公网访问权限，OTA 必须同时支持 **Web-Next 离线上传升级包（主模式）** 与 **在线检查发布清单（可选模式）**。

## 1. 硬件接口确认与 `USART1` 自动下载电路防坑红线（CRITICAL）

### 1.1 物理链路基准（C50C-V4.3 原理图第 3 页）

* **硬件通道**：Orange Pi 5 Pro USB ↔ C50C-V4.3 `USB1.2`（Type-C）↔ `CH9102F` ↔ STM32F407VET6 `USART1`（`PA9` TX / `PA10` RX）。

* **一键下载电路**：`CH9102F` 的 `DTR` 与 `RTS` 经板载三极管电路（`Q5 S8050`、`SS8550`）控制 `BOOT0` 与 `NRST`。

* **固定设备别名**：通过 `deploy/` 中的 `udev` 规则将此串口绑定为唯一固定路径 `/dev/iir_chassis`。

### 1.2 两条必须代码级落实的 `USART1` 红线

1. **固件与上位机通信口对齐**：

   * 核对 STM32 固件 `App/protocol/` 与 `Drivers/BSP/uartx/`，确认 `protocol_v3` 运行时主通道已绑定至 **`USART1`（`PA9`/`PA10`）**（原 `USART3` 保留作本地调试口或空闲）。

   * 上位机串口节点（`c50c_uart3`）默认连接 `/dev/iir_chassis`，运行期与 OTA 刷机期**严格分时互斥独占同一物理串口**。

2. **禁止普通运行期间误触发 `BOOT0` / `NRST`（极重要）**：

   * Linux 默认串口驱动在 `open()` / `close()` 时会置位 `HUPCL` 并拉动 `DTR`/`RTS`，极易在 ROS 节点启动或重启瞬间把 STM32 拉入复位或 ISP 模式导致底盘假死。

   * **强制修复**：

     * 在 `udev` 规则或串口初始化中禁用 `HUPCL`（`termios.HUPCL` 清零）；

     * 在 `c50c_uart3/chassis_cmd/serial_port.py` 打开串口时显式设置 `dsrdtr=False`、`rtscts=False`，并在打开前/后保持 `DTR`/`RTS` 处于使 `BOOT0=0, NRST=High` 的安全空闲电平（具体高低极性通过配置参数 `serial_idle_dtr` / `serial_idle_rts` 可调，见第 6 节实机标定）。

## 2. 统一 OTA 升级包规范与版本标识

### 2.1 发布包清单规范（`manifest.json`）

复用并扩展 `.github/workflows/release.yml`，每次发布或本地打包均生成标准 `.tar.gz` 升级包，包内根目录必须包含 `manifest.json`：

```json
{
  "schema_version": 1,
  "release_version": "1.2.0",
  "created_at": "2026-11-26T12:00:00Z",
  "target": {
    "mcu": "STM32F407VET6",
    "chassis_type": "DIFF",
    "host_arch": "aarch64"
  },
  "artifacts": {
    "firmware": {
      "path": "firmware/xzcit_iir_diff.bin",
      "version": "1.2.0",
      "sha256": "<64-hex-sha256>",
      "size_bytes": 128400
    },
    "master_bundle": {
      "path": "master/xzcit_iir_master.tar.gz",
      "version": "1.2.0",
      "sha256": "<64-hex-sha256>",
      "size_bytes": 45200000
    },
    "rknn_model": {
      "path": "models/power_defect_v1.rknn",
      "labels_path": "models/labels.txt",
      "version": "1.2.0",
      "sha256": "<64-hex-sha256>",
      "size_bytes": 8400000
    }
  }
}
```

> 说明：`artifacts` 中的 `firmware`、`master_bundle`、`rknn_model` 三个字段均设为可选，支持**全量升级**，也支持**仅刷 STM32 固件**、**仅更新上位机代码**或**仅热更新电力缺陷 RKNN 模型**。

### 2.2 STM32 固件版本编译注入与心跳回显

* 在根目录 `CMakeLists.txt` 中通过 `-DIIR_FW_VERSION="1.2.0"` 与自动提取的 `GIT_SHORT_SHA` 生成版本头文件（如 `App/protocol/fw_version.h`）。

* 在 `protocol_v3` 的心跳/系统信息帧中上报 `fw_major`、`fw_minor`、`fw_patch`、`chassis_type`（`DIFF`）与 `git_sha_u32`，供上位机与 Web-Next 实时展示及升级后版本校验。

## 3. 五重安全互锁（OTA Pre-flight Interlocks）

在执行任何底盘刷机或上位机重启之前，`iir-ota-agent` 必须强制校验以下 **5 条硬锁**，任一项不满足直接返回 `409 Conflict` 并给出精确拦截原因：

| 互锁编号 | 互锁名称 | 判定条件 | 兜底措施 |
| :--- | :--- | :--- | :--- |
| **LOCK-1** | **静止锁** | 底盘上报线速度 $|v_x| < 0.01\text{ m/s}$、角速度 $|v_z| < 0.02\text{ rad/s}$，且 Nav2 巡逻/导航均处于非运行态 | 若仍在巡逻，拒绝升级并提示先停止巡逻任务 |
| **LOCK-2** | **安全态锁** | 当前未处于 `SOS` 报警态；进入升级态后立即向 `c50c_uart3` 申请独占锁并禁止 Web 遥控与语音指令 | 升级失败或退出时自动释放独占锁 |
| **LOCK-3** | **电量锁** | 电池电量 $\ge 30\%$ **或** `charging == 1`（正在充电桩充电） | 防止刷写中途欠压掉电 |
| **LOCK-4** | **防误刷锁** | `manifest.json` 校验通过：`mcu == "STM32F407VET6"`、`chassis_type == "DIFF"`、`host_arch == "aarch64"`，且全部文件 SHA256 与字节数精确匹配 | 拒绝错误车型（如麦轮）或损坏包进入刷写流程 |
| **LOCK-5** | **版本回显锁** | 刷写/重启完成后 $15\text{ s}$ 内，STM32 心跳上报的新版本号与目标版本一致（或上位机 `health.sh` 全绿） | 未通过回显锁直接标记升级失败并触发自动回滚 |

## 4. 三类资产的升级与自动回滚流程

### 4.1 STM32 底盘固件 OTA 流程（USART1 ST ROM ISP）

```text
[Web-Next 上传/确认] -> [iir-ota-agent 校验 5 重锁 + SHA256]
  -> [备份当前可用固件到 /var/lib/iir-ota/firmware/last_good.bin]
  -> [暂停底层串口占用: 停止 c50c_uart3 或触发串口释放服务]
  -> [执行 stm32flash: DTR/RTS 进 ISP -> 115200 8E1 刷写 + 读回校验(-v) -> 复位运行(-g 0x0)]
  -> [恢复 c50c_uart3 串口节点]
  -> [等待 15s 验证 protocol_v3 新版本号回显]
      ├── 版本匹配 -> 写入审计日志，标记 SUCCESS
      └── 刷写异常/心跳超时 -> 自动用 last_good.bin 再走一次 ST ROM ISP 救砖并上报 FAILED_ROLLED_BACK
```

* **串口释放机制**：为了避免直接 `systemctl stop` 整套 ROS 导致导航与 Web 状态全断，优先在 `c50c_uart3`（或 `systemd` 独立单元 `iir-chassis-bridge.service`）中提供清晰的串口生命周期控制（如停止独立串口服务，刷完后拉起，确保 `/dev/iir_chassis` 无任何残留进程句柄，用 `fuser` / `lsof` 检查确认零占用后再调用 `stm32flash`）。

* **防无限重试**：自动救砖最多重试 2 次；即使 2 次均失败，因为 ST ROM Bootloader 永不损坏，Web-Next 仍可显示“底盘处于待恢复态，请检查串口供电后点击重试刷写”。

### 4.2 香橙派上位机软件 OTA 流程（原子软链接 + 自动回滚）

* **目标部署目录布局**：

  ```text
  /opt/iir/
  ├── releases/
  │   ├── v1.1.0/
  │   └── v1.2.0/
  ├── current -> /opt/iir/releases/v1.2.0   # 原子切换点
  ├── previous -> /opt/iir/releases/v1.1.0  # 回滚目标
  └── shared/                               # 跨版本持久化目录（地图、抓拍图片、历史库、wp5.env）
  ```

* **原子切换与健康回滚**：

  1. 解压新版本至 `/opt/iir/releases/vX.Y.Z/` 并校验全部依赖与权限。

  2. 记录当前 `current` 目标到 `previous`，通过 `ln -sfn` 原子切换 `/opt/iir/current`。

  3. 执行 `systemctl restart iir.target`。

  4. 在 $30\text{ s}$ 窗口内轮询 `deploy/health.sh`（验证 ROS 关键节点、Gateway、Web-Next、MediaMTX 全部就绪）。

  5. 若超时未就绪，自动执行 `ln -sfn $(readlink /opt/iir/previous) /opt/iir/current && systemctl restart iir.target`，将错误日志回传至 Web-Next。

### 4.3 RKNN 电力设备缺陷模型热更新流程

* 电力巡检场景经常需要迭代优化 YOLO 缺陷检测权重，支持**独立上传 `.rknn` + `labels.txt`**，无需重启整车导航：

  1. 校验 SHA256 与非空标签文件，写入 `/opt/iir/shared/models/<version>/`。

  2. 原子切换 `/opt/iir/shared/models/current` 软链接。

  3. 仅重启 `iir-vision-rknn.service`，等待 $10\text{ s}$ 检查模型加载成功状态；加载失败则自动切回上一版模型并重启恢复。

## 5. 分步实施工单（OTA-01 ~ OTA-05）

### OTA-01：STM32 版本号注入与 `USART1` 防误复位加固

* **涉及文件**：`CMakeLists.txt`、`App/protocol/protocol_v3.{c,h}`、`Drivers/BSP/uartx/bsp_uartx.{c,h}`、`Master/ROS/ros2_ws/src/c50c_uart3/c50c_uart3/chassis_cmd/serial_port.py`、`deploy/generate-udev.py`

* **任务要求**：

  1. 在 `CMakeLists.txt` 中生成版本信息（`IIR_FW_VERSION_MAJOR/MINOR/PATCH`、`IIR_GIT_SHA`、`IIR_CHASSIS_TYPE`），通过 `protocol_v3` 上报并在 `c50c_uart3` 解析发布至 `/chassis/version`（或纳入 `/chassis/status`）。

  2. 核对并确保 STM32 `protocol_v3` 运行于 **`USART1`（`PA9`/`PA10`）**。

  3. 在 `c50c_uart3` 的 `serial_port.py` 中增加防误复位配置：关闭 `HUPCL`、显式支持可配置的 `idle_dtr` / `idle_rts` 空闲电平，确保普通运行期间打开/关闭 `/dev/iir_chassis` 不会复位 STM32 或拉高 `BOOT0`。

  4. 为版本编解码与串口 `DTR/RTS` 参数编写单元测试。

### OTA-02：独立升级代理服务 `Master/OTA/`（`iir-ota-agent`）

* **新增目录**：`Master/OTA/`（推荐与 `Master/Gateway` 一致的 Python FastAPI + Pydantic，轻量独立虚拟环境，易维护且零编译依赖）

* **核心模块设计**：

  * `app/interlocks.py`：实现 5 重安全互锁（支持通过 ROS 2/Gateway 查询车速、电量、充电态、SOS、巡逻态，并提供 Mock 注入以便单元测试）。

  * `app/manifest.py`：升级包解压、目录遍历漏洞防护（防 ZipSlip/TarSlip 路径穿越）、`manifest.json` 校验与 SHA256 核验。

  * `app/stm32_flasher.py`：封装 `stm32flash` 子进程调用、串口进程占用检查、超时终止、实时进度百分比解析、失败自动刷回 `last_good.bin`；提供 `MockFlasherBackend` 供 CI 离线测试。

  * `app/host_updater.py`：实现 `/opt/iir/current` 原子软链接切换、`systemctl restart iir.target`、`health.sh` 探针与自动回滚；提供 `MockSystemdBackend` 供 CI 测试。

  * `app/model_updater.py`：实现 `.rknn` + `labels.txt` 独立热更新与失败回滚。

  * `app/main.py`：暴露 REST 与 WebSocket 接口：

    * `GET /api/ota/status`：当前底盘/上位机/模型版本号、5 重安全互锁实时状态、历史升级审计记录。

    * `POST /api/ota/upload`：流式接收离线 `.tar.gz` 升级包并执行预检（校验 SHA256、解析将要更新的组件列表）。

    * `POST /api/ota/apply`：确认执行指定任务的升级（可选范围：`all` / `firmware` / `master` / `model`）。

    * `POST /api/ota/rollback`：手动触发上位机/模型/底盘回滚至上一稳定版本。

    * `WS /ws/ota/progress`：实时推送阶段状态（`PRECHECK -> BACKUP -> FLASHING -> VERIFYING -> DONE / ROLLED_BACK`）、进度百分比与刷写日志流。

### OTA-03：部署编排、`Caddyfile` 路由与 Release CI 打包

* **涉及文件**：`deploy/systemd/iir-ota-agent.service`、`deploy/Caddyfile`、`deploy/install.sh`、`deploy/wp5.env.example`、`.github/workflows/release.yml`、`deploy/test/test_deployment.py`

* **任务要求**：

  1. 新增 `deploy/systemd/iir-ota-agent.service`（监听 `127.0.0.1:8090`），设为 `WantedBy=multi-user.target`（**独立于 `iir.target`**），配置最小必要权限（操作串口、切换 `/opt/iir` 软链接及重启指定 `iir-*` 单元）。

  2. 在 `deploy/Caddyfile` 中新增反代规则：`/api/ota/*` 与 `/ws/ota/*` 转发至 `127.0.0.1:8090`，并放宽上传体积限制（如支持最大 $512\text{ MB}$ 升级包）。

  3. 在 `deploy/wp5.env.example` 中显式配置 `STM32FLASH_INIT_SEQ`（`DTR/RTS` 进 ISP 时序）与 `STM32FLASH_EXIT_SEQ`（复位运行模式时序），避免硬编码。

  4. 更新 `.github/workflows/release.yml`：构建 STM32 `.bin` 与上位机部署包，自动计算 SHA256 并打包生成符合第 2.1 节规范的 `xzcit-iir-ota-vX.Y.Z.tar.gz`。

  5. 更新 `deploy/test/test_deployment.py`，校验 `iir-ota-agent.service` 独立性（不得受 `iir.target` 级联停止）与 Caddy 路由正确性。

### OTA-04：`Master/Web-Next` 远程升级管理界面

* **涉及文件**：`Master/Web-Next/web/index.html`、`Master/Web-Next/web/js/ota.js`（新增）、`Master/Web-Next/web/js/app.js`、`Master/Web-Next/web/styles/`

* **功能要求**：

  1. 在管理端新增“系统升级（OTA）”抽屉/标签页（学生端 `/student` **严禁暴露** OTA 入口）。

  2. 展示当前三端版本卡片：**STM32 底盘固件版本**、**上位机软件版本**、**RKNN 缺陷模型版本**。

  3. 实时展示 **5 重安全互锁状态指示灯**（任一绿灯未亮时，“开始升级”按钮置灰并显示阻塞原因）。

  4. 支持拖拽上传离线 `.tar.gz` 升级包、展示预检结果（版本变化 + 组件勾选）、点击“开始升级”后二次确认弹窗、实时滚动日志终端与进度条，以及“回滚上一版本”紧急按钮。

### OTA-05：全套离线测试与 CI 接入

* **新增测试**：`Master/OTA/tests/` 与前端 `Master/Web-Next/web/test/ota.test.cjs`

* **必测场景**：

  1. 5 重安全锁拦截测试（行驶中、SOS 中、电量 $20\%$ 且未充电、车型 `MECANUM` 不匹配、SHA256 篡改、路径穿越 `../../etc/passwd` 全部必须拦截）。

  2. STM32 刷写完整状态机测试（Mock `stm32flash` 成功回显新版本；Mock 刷写中途失败触发 `last_good.bin` 自动救砖）。

  3. 上位机原子切换与健康探针失败自动回滚软链接测试。

  4. RKNN 模型热更新与加载失败回滚测试。

  5. 将 `pytest Master/OTA/tests` 与 `node --test Master/Web-Next/web/test/ota.test.cjs` 接入 `.github/workflows/ci.yml`。

## 6. 实机上电 `USART1` `DTR/RTS` 极性首次标定 SOP（供人类工程师上机核对）

由于不同批次 C50C-V4.3 的 `S8050` / `SS8550` 与 CH9102F `DTR/RTS` 电平逻辑在实际 Linux 驱动下可能存在反相，**首次上机必须先执行一次 3 分钟标定**，把测出的序列写入 `/etc/iir/wp5.env`：

```bash
# 1. Install stm32flash on Orange Pi 5 Pro / 在香橙派安装 stm32flash
sudo apt-get update && sudo apt-get install -y stm32flash

# 2. Stop chassis ROS bridge to release USART1 / 暂停底盘串口节点以释放 USART1
sudo systemctl stop iir-chassis-bridge.service

# 3. Test entering ST ROM ISP and reading chip ID (must return STM32F40xxx/0x413)
# 测试通过 DTR/RTS 进入 ST 官方 ISP 并读取芯片 ID（正常应识别为 STM32F40xxx / 0x413）
# Candidate A (standard FlyMcu circuit: DTR->BOOT0, RTS->NRST):
stm32flash -b 115200 -i "rts,-dtr,dtr:-rts,-dtr,dtr" /dev/iir_chassis
# Candidate B (if polarity inverted on board):
# stm32flash -b 115200 -i "-rts,dtr,-dtr:rts,dtr,-dtr" /dev/iir_chassis

# 4. Verify MCU exits ISP and boots user firmware normally after reset
# 验证退出 ISP 后底盘 OLED 正常点亮且心跳恢复
sudo systemctl start iir-chassis-bridge.service
```

将第 3 步成功读出 `STM32F40xxx` 芯片 ID 的 `-i` 序列填入 `deploy/wp5.env` 的 `STM32FLASH_GPIO_SEQ`，之后所有 Web-Next 远程刷机即可 100% 全自动稳定执行。

## 7. 验收命令清单

```bash
# 1. Encoding & line-ending check / 编码与换行符门禁
python3 scripts/check_encoding.py

# 2. Firmware build with injected version / 带版本号注入的固件编译
cmake --preset stm32-diff-release -DIIR_FW_VERSION="1.0.0"
cmake --build --preset stm32-diff-release

# 3. Firmware & ROS 2 unit tests / 固件与 ROS 2 单元测试
ctest --preset host-test --output-on-failure
(cd Master/ROS/ros2_ws && colcon test --packages-select c50c_uart3 && colcon test-result --verbose)

# 4. OTA Agent & Deployment tests / OTA 代理与部署配置单元测试
pytest Master/OTA/tests deploy/test/test_deployment.py

# 5. Web-Next OTA UI tests / 前端 OTA 逻辑单元测试
node --test Master/Web-Next/web/test/ota.test.cjs
```

## 8. 派发给编程 AI 的启动 Prompt（直接复制发送）

> “请仔细阅读 `WP6_OTA_PLAN.md`、`WP_INTEGRATION_FIX.md` 与 `AI_EXECUTION_PLAN.md`。本次会话我们执行 **WP6（整车远程 OTA 升级）**，基于 C50C-V4.3 `USART1`（带 CH9102F 一键下载电路）。
>
> 1. 严格按 `OTA-01 -> OTA-05` 顺序推进，采用 **ST ROM ISP（`stm32flash`）代理烧录 + 上位机软链接原子回滚 + RKNN 模型热更新**，不编写自定义 STM32 Bootloader；
>
> 2. **重点落实 `USART1` 防误复位保护**（禁止普通运行开关串口拉动 `DTR/RTS` 导致 MCU 复位或进入 ISP）；
>
> 3. **强制规范**：全仓新建与修改文件必须为 **UTF-8（无 BOM）+ LF**，所有注释必须**先写英文，再紧跟其准确的中文翻译**，严禁直接写纯中文注释；
>
> 4. 全部完成后运行 `WP6_OTA_PLAN.md` 第 7 节全部验收命令并贴出真实输出，全部通过后再报告完成。”