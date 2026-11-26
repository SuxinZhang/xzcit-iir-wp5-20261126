# XZCIT-IIR 全栈收口合并与上机前整改工单（Pre-Hardware Integration Fix Spec）

> **致执行本工单的 AI 开发助手**：
> 本工单用于在 **STM32 实车上电与 Orange Pi 5 Pro 上机联调之前**，将当前分离的 `WP1-WP3` 主干仓库与 `WP4`、`WP5` 两个 `overlay/` 补丁包彻底整合为一个单一、可编译、无回归、全栈自启的生产基线。
>
> **严禁**直接用 `cp -r` 暴力覆盖 `overlay/` 文件；**严禁**为了 CI 变绿而删减任何已有安全或回归测试。

---

## 0. 全局硬性约束（执行所有 FIX 任务前必读）

1. **编码与双语注释红线（沿用 `AI_EXECUTION_PLAN.md` 第 1 节）**：
   * 全仓新建与修改文件必须为 **UTF-8（无 BOM）+ LF（`\n`）** 换行。
   * 所有新增或修改的代码注释必须遵循 **“先写英文注释，再紧跟其准确中文翻译”**（English-First, Then Chinese Translation），严禁直接写纯中文注释。
2. **需求变更确认 — 彻底移除手柄控制**：
   * 本项目**不再需要**经典 PS2 手柄和 USB HID 游戏手柄控制模块。
   * 全系统控制权优先级收敛为 4 级（从高到低）：
     **`PE4 物理使能开关 / PE5 物理 SOS（硬件最高） > Web-Next 远程遥控 > CAN 自动回充 > Nav2 自主巡逻`**。
3. **单一事实基线**：
   * 最终所有代码必须整合在同一分支下，删除残留的独立 `overlay/` 目录，确保一键即可跑通全部编译、单测、编码检查和部署测试。

---

## 1. 阻塞级整改任务（P0：必须 100% 完成才允许上电）

### FIX-01：WP4 与 WP5 `Master/Web-Next` 冲突文件三方合并

* **背景问题**：WP4 与 WP5 的 `overlay/` 同时修改了 `Master/Web-Next/` 中 4 个核心文件，直接覆盖会导致“电力缺陷抓拍/学生终端”或“WebRTC 双向对讲/语音交互”功能丢失。
* **冲突文件清单**：
  1. `Master/Web-Next/src/main.rs`
  2. `Master/Web-Next/web/index.html`
  3. `Master/Web-Next/web/js/app.js`
  4. `Master/Web-Next/web/js/ws.js`
* **具体执行要求**：
  1. 先将 WP4 的 `overlay/`（`iir_interfaces`、`iir_vision_rknn`、`Master/Gateway`、WP4 版 `Web-Next` 与 `ci.yml`）合入主仓。
  2. 再逐文件三方合并 WP5 的 `overlay/`（`iir_interaction`、`deploy/`、WP5 新增的 `Web-Next` 文件 `Cargo.toml`/`Cargo.lock`/`src/interaction.rs`/`src/ws_control.rs`/`src/ws_video.rs`/`web/js/interaction.js`/`web/styles/layout.css`/`web/test/interaction.test.cjs`）。
  3. 合并上述 4 个冲突文件时，必须同时保留：
     * **WP4 能力**：`inspection.js`、`student.html` / `student.js`（学生智能终端路由 `/student`）、`inspection.css` / `student.css`、抓拍与电力设备缺陷告警展示、Gateway 代理或 API 转发路由。
     * **WP5 能力**：`interaction.js`、WebRTC 双向对讲与平台远程喊话控制、ASR/TTS 状态联动、`ws_control.rs` 与 `ws_video.rs` 路由。
  4. 检查合并后的 Rust 路由表与前端 WebSocket 消息 `type` 字段，确保无路由冲突、无重复 DOM ID、无未定义 JS 函数。
* **验收标准**：
  * `cd Master/Web-Next && cargo test` 全绿。
  * `node --test Master/Web-Next/web/test/interaction.test.cjs` 全绿。
  * 前端同时可渲染主控页 `/`（含巡检面板 + 语音对讲面板）与学生终端页 `/student`。

---

### FIX-02：STM32 固件安全开关、CAN 编译完整性与手柄彻底清理

* **背景问题**：
  * `Drivers/BSP/can_auto_dock/bsp_can_dock.c` 已存在，但 `Drivers/STM32F4xx_HAL_Driver/Src/` 下缺少 `stm32f4xx_hal_can.c`；
  * 原 `enable_key`（`PE4`）目录已消失，需确认物理使能开关是否仍受固件最高优先级保护；
  * `Drivers/STM32F4xx_HAL_Driver/Src/` 仍残留 `stm32f4xx_hal_hcd.c` 与 `stm32f4xx_ll_usb.c`（USB 手柄驱动）；
  * `C50C_HAL.ioc` 未随 `Core/Src/main.c` 同步更新。
* **具体执行要求**：
  1. **核查并修复 CAN1 编译链路**：
     * 检查 `Drivers/BSP/can_auto_dock/bsp_can_dock.c` 与 `CMakeLists.txt`。若其依赖 HAL CAN API，补齐 `Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_can.c` 并在 `Core/Inc/stm32f4xx_hal_conf.h` 中启用 `HAL_CAN_MODULE_ENABLED`；若为纯寄存器操作，核对 `RCC->APB1ENR` 时钟、`PD0`/`PD1` AF9 复用与 NVIC 中断使能完整无误。
  2. **核查本地硬件安全兜底（Fail-Closed）**：
     * 在 `App/safety/safety_manager.c` 与 `App/tasks/app_tasks.c` 中确认：
       * **`PE4` 板载使能开关**（低/高有效极性须与 C50C-V4.3 原理图 `SW1` 完全一致）断开时，必须在本地立即封锁电机 PWM；
       * **`PE5` 物理 SOS 一键呼救**触发后 $\le 50\text{ ms}$ 内封锁电机 PWM、蜂鸣器 `PD11` 鸣响、RGB 灯带红灯高频爆闪，并上报上位机；
       * 上位机串口失联超过 $500\text{ ms}$ 或严重欠压时，本地自动刹停；
       * 全固件仅允许唯一一个电机 PWM 输出出口函数，严禁旁路写入 `TIM8->CCRx`。
  3. **核查超声波 `PE9` / `PE11` 与 `ICM-20948` 驱动**：
     * 核对 `Drivers/BSP/hc_sr04/bsp_hc_sr04.c`：确认使用 `PE9`（`TIM1_CH1` 硬件输入捕获，$1\text{ MHz}$ 计数，$28\text{ ms}$ 超时，$60\text{ ms}$ 触发周期，有效量程 $0.02 \sim 4.50\text{ m}$）和 `PE11`（`TRIG` 推挽输出），且无阻塞轮询等待；原航模 `TIM1` 捕获逻辑已彻底移除。
     * 核对 `Drivers/BSP/icm20948/bsp_icm20948.c`：确认使用硬件 `I2C1`（`PB8`/`PB9`）非阻塞方式读取，带开机零偏校准。
  4. **彻底清理 PS2 与 USB 手柄残留**：
     * 从 `CMakeLists.txt`、`stm32f4xx_hal_conf.h` 及 `App/` 中移除 `HAL_HCD_MODULE_ENABLED`、`stm32f4xx_hal_hcd.c`、`stm32f4xx_ll_usb.c` 以及所有 `_PS2_Control` / USB Gamepad 死代码。
  5. **冻结 `.ioc` 防误覆盖说明**：
     * 在固件根目录 README 或 `Core/Src/main.c` 文件头注明 `C50C_HAL.ioc` 仅为初始引脚参考，现已转为 CMake 手动维护模式，禁止直接用 CubeMX 覆写 `Core/`。
* **验收标准**：
  * `cmake --preset stm32-diff-release && cmake --build --preset stm32-diff-release` 零警告/零错误产出 `.elf`、`.hex`、`.bin` 并输出 Flash/RAM 占用报告。
  * `cmake --preset host-test && cmake --build --preset host-test && ctest --preset host-test --output-on-failure` 100% 通过（需覆盖 `PE4` 失能、`PE5` SOS、$500\text{ ms}$ 失联刹停、$0.01 \sim 1.3\text{ m/s}$ 限幅）。

---

### FIX-03：核查并恢复 `.github/ros2-test-baseline.txt` 缩水的回归用例

* **背景问题**：相比改造前基线（$18\,950\text{ B}$），当前 WP1–WP3 的 `.github/ros2-test-baseline.txt` 缩水至 $12\,680\text{ B}$，且 `c50c_uart3/test/firmware_harness/` 中原有的 `fw_ros_drive_model.py` 与 `fw_ros_mode_model.py` 已消失。
* **具体执行要求**：
  1. 对比原始 `feat/differential` 分支与当前分支的 `.github/ros2-test-baseline.txt` 差异，列出每一条消失的测试项及其原因。
  2. **恢复原则**：
     * 凡是因删掉 PS2 手柄或重构旧 `App/BALANCE/balance_task.c` 而不再适用的用例，须在 PR 说明/注释中逐条说明原因；
     * 凡是涉及底盘直行控制、串口协议对齐、模式切换安全门禁（`fw_ros_drive_model` / `fw_ros_mode_model` 的等效行为）的核心验证，**必须针对新的 `App/kinematics` + `App/control` + `App/safety` + `App/protocol` 恢复或重写等效固件仿真测试**，重新纳入基线。
* **验收标准**：
  * `colcon test --packages-select c50c_odom c50c_uart3 opi_robot iir_navigation iir_navigation_vision iir_interfaces iir_vision_rknn iir_interaction` 全部通过。
  * `python3 .github/scripts/compare_ros2_tests.py` 验证零退化。

---

## 2. 高风险系统集成任务（P1：打通全栈闭环与一键自启）

### FIX-04：统一 Web 入口（Caddy 反向代理）与 `systemd` 全栈自启编排

* **背景问题**：当前存在 `opi_robot/web_node/web_debug.py`、`Master/Gateway`（WP4）和 `Master/Web-Next`（WP5）三套 Web 服务；`deploy/Caddyfile` 仅 $94\text{ B}$ 且 `deploy/systemd/` 未纳入 `Gateway` 与 `iir_vision_rknn`，上机后极易出现端口冲突、跨域（CORS）或部分服务未自启。
* **具体执行要求**：
  1. **明确服务端口与职责边界（写入 `deploy/WP5_INTERFACES.md` 或 `deploy/PORT_MAP.md`）**：
     * `Caddy`（`443` HTTPS，统一对外入口，满足浏览器 WebRTC 麦克风权限要求）；
     * `Master/Web-Next`（Rust 服务，提供静态页面 `/` 与 `/student`、遥控/遥测 WebSocket、语音交互控制）；
     * `Master/Gateway`（FastAPI 服务，承接电力巡检抓拍 API、历史记录、图片静态资源与缺陷告警 WebSocket）；
     * `MediaMTX`（WHEP/WHIP WebRTC 音视频流）；
     * `web_debug.py`（冻结为仅本机 `127.0.0.1` 调试用或由内部桥接调用，不直接暴露给前端跨域直连）。
  2. **完善 `deploy/Caddyfile`**：配置同源反向代理规则，将 `/api/inspection/*`、`/ws/inspection`、`/captures/*` 转发至 `Master/Gateway`，将 `/whep/*`、`/whip/*` 转发至 `MediaMTX`，其余 `/` 与 `/student`、`/ws/*` 转发至 `Master/Web-Next`。消除前端代码中的硬编码端口或跨端口 URL。
  3. **补齐 `deploy/systemd/` 与 `iir.target`**：
     * 新增 `iir-gateway.service`（拉起 `Master/Gateway`）；
     * 新增 `iir-vision-rknn.service`（或在 `run-ros.sh` 中显式纳入 `iir_vision_rknn` 与 `iir_navigation_vision` 并增加健康探针）；
     * 将全部新增服务纳入 `deploy/systemd/iir.target` 与 `deploy/install.sh`、`deploy/health.sh`、`deploy/wait-ready.py`；
     * 同步更新 `deploy/test/test_deployment.py` 验证所有单元语法、端口映射与依赖关系。
* **验收标准**：
  * `pytest deploy/test/test_deployment.py` 全绿。
  * `Master/Gateway/tests/` 全部 `pytest` 通过。
  * 全前端仅通过单一 HTTPS 域名/IP 端口访问即可打通遥控、视频、对讲、抓拍与学生终端，零 CORS 报错。

---

### FIX-05：消除相机与 NPU 资源争抢，打通“巡逻到点 → 自动抓拍 → 学生端推送”闭环

* **背景问题**：
  1. 系统中同时存在 `opi_robot/cam_node`、`iir_navigation_vision`（WP3）和 `iir_vision_rknn`（WP4），且 WP5 还有视频推流，若多进程直接 `open("/dev/video0")` 必导致设备忙报错；
  2. WP4 未将 `/inspection/capture` 接入 `opi_robot/web_node/patrol.py`，巡逻到点自动抓拍与学生端推送尚未自动串联。
* **具体执行要求**：
  1. **相机单点采集与分发**：
     * 明确唯一硬件采集节点（如 `cam_node` 或统一相机驱动）独占 V4L2/深度相机硬件，向 ROS 2 发布标准图像话题（供 `iir_navigation_vision` 与 `iir_vision_rknn` 共同订阅），同时明确 MediaMTX H.264 推流来源，杜绝两个进程抢占同一个 `/dev/video*` 设备。
     * 在配置中为 RK3588S NPU 明确核心分配或并发策略（RK3588S 有 3 个 NPU 核心 `core_0/1/2`：例如避障推理绑定核心 0，电力缺陷识别绑定核心 1/2，或按需触发缺陷推理以降低常驻算力与功耗）。
  2. **打通巡逻自动抓拍闭环（标书 7.2.5）**：
     * 在 `opi_robot/web_node/patrol.py`（或巡检状态机）中增加到达巡检点（Waypoint）后的动作钩子：
       `到达巡检点 -> 触发语音播报（通过 iir_interaction） -> 调用 /inspection/capture 服务 -> 接收抓拍与 AI 缺陷研判结果 -> 经 Gateway WebSocket 实时推送至管理端与 /student 学生智能终端 -> 继续前往下一个点位`。
     * 增加超时与容错保护：即使视觉服务暂时离线，也应记录告警日志而不得阻塞整车巡逻或回充安全逻辑。
     * 为该闭环补充离线单元测试（使用 Mock 图像与 Mock 推理后端验证从巡检到点到 Gateway 广播的完整数据流）。
* **验收标准**：
  * 单测覆盖“到达巡检点 -> 触发 `/inspection/capture` -> 归档原图/标注图/JSON -> Gateway 推送至 `/student`”全链路。
  * 确认所有节点配置中不存在重复直连同一 `/dev/video*` 设备节点的冲突。

---

### FIX-06：统一全栈 CI 流水线与强制编码/注释门禁

* **背景问题**：WP4 更新了 `.github/workflows/ci.yml`，但 WP5 未同步更新 CI；且需确保全仓（含 WP4、WP5 新增文件）100% 满足 UTF-8 无 BOM + LF 与先英文后中文双语注释规范。
* **具体执行要求**：
  1. 完善 `scripts/check_encoding.py`（若 WP1 尚未包含全后缀检查，扩展覆盖 `.c .h .cpp .hpp .py .rs .js .ts .html .css .yaml .yml .xml .json .cmake .sh .service .md`），严格拦截 UTF-8 BOM、非法 UTF-8 字节与 `CRLF` 换行。
  2. 抽查并修复 WP1–WP5 所有新建/修改代码文件中的纯中文注释或“先中后英”注释，统一改为**先英文、后中文翻译**格式。
  3. 整合 `.github/workflows/ci.yml`，确保每次 PR 自动运行全部 6 个 Job：
     * `encoding-check`：`python3 scripts/check_encoding.py`
     * `firmware-build`：`cmake --preset stm32-diff-release` + `arm-none-eabi-size`
     * `firmware-host-test`：`cmake --preset host-test && ctest --preset host-test`
     * `ros2-build-and-test`：`colcon build` + `colcon test`（覆盖全部 8 个包：`c50c_odom`, `c50c_uart3`, `opi_robot`, `iir_navigation`, `iir_navigation_vision`, `iir_interfaces`, `iir_vision_rknn`, `iir_interaction`）+ `compare_ros2_tests.py`
     * `gateway-and-deploy-test`：`pytest Master/Gateway/tests deploy/test/test_deployment.py`
     * `web-next-test`：`cd Master/Web-Next && cargo test` + `node --test Master/Web-Next/web/test/interaction.test.cjs`

---

## 3. 总验收命令清单（AI 宣布完成前必须全部运行并贴出真实输出）

```bash
# 1. Encoding & line-ending gate / 编码与换行符门禁
python3 scripts/check_encoding.py

# 2. STM32 firmware cross-compilation / STM32 固件交叉编译
cmake --preset stm32-diff-release
cmake --build --preset stm32-diff-release

# 3. Firmware host-side unit tests / 固件宿主机单元测试
cmake --preset host-test
cmake --build --preset host-test
ctest --preset host-test --output-on-failure

# 4. ROS 2 full workspace build, test & baseline check / ROS 2 全工作空间编译、测试与基线校验
cd Master/ROS/ros2_ws
colcon build --symlink-install
colcon test --event-handlers console_cohesion+
colcon test-result --verbose
cd ../../..
python3 .github/scripts/compare_ros2_tests.py

# 5. Gateway & deployment unit tests / 网关与部署单元测试
pytest Master/Gateway/tests deploy/test/test_deployment.py

# 6. Web-Next Rust backend & JS frontend tests / Web-Next 后端与前端测试
(cd Master/Web-Next && cargo test)
node --test Master/Web-Next/web/test/interaction.test.cjs
```

---

## 4. 派发给编程 AI 的启动 Prompt（直接复制发送）

> “请阅读根目录的 `WP_INTEGRATION_FIX.md` 与 `AI_EXECUTION_PLAN.md`。本次会话的目标是完成 WP1–WP5 的全栈收口整合，准备上机联调。
>
> 1. 严格按 `FIX-01 -> FIX-06` 的顺序逐项执行，先输出你的冲突分析与修改清单，再动手修改；
> 2. **强制规范**：所有新建或修改的文件必须保存为 **UTF-8（无 BOM）+ LF**，所有新增/改动的注释必须**先写英文，再紧跟其准确的中文翻译**，严禁直接写纯中文注释；
> 3. **彻底移除 PS2 与 USB 手柄相关代码和 HAL HCD 依赖**，但必须保留并验证 `PE4` 物理使能开关与 `PE5` 物理 SOS 的最高硬件安全断电优先级；
> 4. 全部修复完成后，依次执行 `WP_INTEGRATION_FIX.md` 第 3 节的全部 6 组验收命令并贴出真实输出，任何一项失败或未验证前不要声称完成。”