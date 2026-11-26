# XZCIT-IIR 巡检机器人现代化重构与系统集成执行规划书（AI Agent Execution Spec）

> **致执行本规划书的 AI 开发助手**：
> 本文档是 `inspection-robot`（对应 `XZCIT-IIR` `feat/differential` 架构基线）巡检机器人项目的最高级工程执行规范。
> 本仓库采用**“下位机固件从零洁净重构 + 上位机 `Master/` 增量保留演进”**策略：STM32F407 HAL + CMake 固件在本地骨架（`Core/`, `Drivers/`, `App/`, `cmake/`, `tests/`）中对照 `../robot/WHEELTEC_C50X_2026.05.29霍尔编码器/` 与 `C50C_V4.3原理图.pdf` 从零构建；上位机 `Master/`（及 `.github/` ROS 2 基线工具，引自 `XZCIT-IIR@feat/differential` `97e74d6`）严禁推倒重写，必须零退化演进。
> 请严格遵守本文档中的**编码与双语注释规范**、**硬件引脚定义**、**架构红线（Invariants）**与**分阶段工单（WP1 - WP5）**。每次会话仅专注完成一个工单（或子任务），修改代码前必须先读取现有实现，完成后必须运行对应验收命令确保全部通过。

---

## 1. 强制代码编码与双语注释规范（全局最高优先级）

为彻底消除旧版嵌入式工程（GBK/GB2312）带来的跨平台乱码问题，并确保固件、ROS 2 与 Web 端代码具备统一的国际化可维护性，所有 AI 生成、重构或修改的文件**必须无条件遵守以下规范**：

### 1.1 文件编码与换行符标准

1. **字符编码**：所有源码、配置文件、构建脚本与文档（`.c`, `.h`, `.cpp`, `.hpp`, `.py`, `.ts`, `.tsx`, `.yaml`, `.xml`, `.json`, `.cmake`, `CMakeLists.txt`, `.md`）**必须统一使用 `UTF-8`（无 BOM / UTF-8 without BOM）**。严禁产生 GBK、GB2312、UTF-16 或带 BOM 的文件。
2. **换行符**：统一使用 Unix 风格 **`LF`（`\n`）**，禁止混入 `CRLF`（`\r\n`）。
3. **旧代码迁移清理**：从旧版 `WHEELTEC_C50X` 或现有 `App/` 迁移文件时，必须先将原始 GBK 编码转换为 UTF-8（无 BOM），并按下方注释规则重写乱码或纯中文注释。
4. **工程约束**：必须在仓库根目录配置 `.editorconfig`，并在 `.github/workflows/ci.yml` 中增加 UTF-8（无 BOM）编码检查门禁。

### 1.2 双语注释强制规则（English-First, Then Chinese Translation）

1. **严禁直接编写纯中文注释**，也**严禁“先中文、后英文”**。
2. **所有注释（文件头、函数 Doxygen/Docstring、结构体字段、关键算法与行内逻辑注释）必须先用清晰、地道的英文撰写，再紧跟将该英文准确翻译而来的中文注释**。
3. 禁止使用无意义的复读机式注释（如 `i++` 写 `Increment i`）；注释应解释“意图（Why）”、“单位/量纲（Units）”或“硬件约束（Hardware Constraint）”。
4. 各语言标准格式模板如下（AI 必须严格照搬格式）：

**C / C++ 示例（固件与 ROS 2 C++ 节点）**：

~~~c
/**
 * @brief Measure distance using TIM1_CH1 hardware input capture on PE9.
 *        使用 PE9 上的 TIM1_CH1 硬件输入捕获进行超声波测距。
 *
 * @param[out] distance_m Measured distance in meters (valid range: 0.02 to 4.50 m).
 *                        测得的距离值，单位为米（有效量程：0.02 至 4.50 米）。
 * @return true if a fresh valid echo was captured; false on timeout or invalid pulse.
 *         若成功捕获有效回波则返回 true；超时或脉宽无效则返回 false。
 */
bool HC_SR04_GetDistance(float *distance_m)
{
    /* Guard against null pointer before accessing output buffer.
     * 在访问输出缓冲区之前防范空指针。 */
    if (distance_m == NULL) {
        return false;
    }

    // Timeout after 28 ms to cover the 4.50 m full-scale echo round-trip.
    // 超过 28 ms 判定为超时，以覆盖 4.50 米满量程的回波往返时间。
    if (s_echo_timeout_flag) {
        return false;
    }
    ...
}
~~~

**Python 示例（ROS 2 Python 节点与网关）**：

~~~python
def clamp_velocity(vx: float, max_speed: float = 1.3) -> float:
    """Clamp linear velocity within the tender-specified safety envelope.
    将线速度限制在标书规定的安全包络范围内。

    Args:
        vx: Target linear velocity along the X axis in m/s.
            沿 X 轴的目标线速度，单位为 m/s。
        max_speed: Maximum permitted linear velocity in m/s.
            允许的最大线速度，单位为 m/s。
    """
    # Enforce hard upper and lower bounds to comply with Tender Clause 7.1.3.
    # 强制执行上下限幅，以满足标书第 7.1.3 条要求。
    return max(-max_speed, min(max_speed, vx))
~~~

**CMake / YAML / TypeScript 示例**：

~~~cmake
# Configure Cortex-M4F hardware floating-point flags for STM32F407VET6.
# 为 STM32F407VET6 配置 Cortex-M4F 硬件浮点编译标志。
set(CPU_FLAGS "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard")
~~~

---

## 2. 项目背景与标书验收指标

### 2.1 软硬件平台与现有资产

* **底盘控制器**：STM32F407VET6（WHEELTEC C50C-V4.3 集成板，四轮差速底盘，13 线霍尔编码器 $\times 4$ 倍频）。
* **上位机（边缘计算）**：Orange Pi 5 Pro（RK3588S，内置 6 TOPS NPU，Ubuntu + ROS 2）。
* **外接传感器与执行器**：2D 激光雷达、普通单目相机（USB UVC / MIPI CSI，经内参标定后兼顾视觉协同导航避障/地标辅助定位、AI 电力设备缺陷识别与 WebRTC 实时视频流）、宽压版 HC-SR04 超声波模块（DC $2.8 \sim 5.5\text{ V}$，量程 $2 \sim 450\text{ cm}$，波束角 $\le 15^\circ$）、CAN 自动回充模块（4 路红外）、RS485 D50A 电机驱动监控、功放喇叭与麦克风。
* **下位机固件工程策略（从零洁净构建）**：
  * `Core/`, `Drivers/`, `App/`, `cmake/`, `tests/firmware_unit/`：在本仓库空白骨架中直接采用 STM32CubeMX HAL + CMake + Ninja 构建四轮差速固件（按模块化分层一次成型，不保留旧 Keil `MDK-ARM/` 或 `STM32F407_StdPeriph` 历史包袱）。
  * **永久移除 PS2 手柄体系**：新固件及系统架构彻底删除旧版 PS2 手柄初始化、手柄控制逻辑（`ps2_classic` / `PS2_Control`）及 PS2 手柄断链安全门（`g_rear_ps2_valid`）；外部手动遥控仅通过 Wi-Fi / Web-Next / ROS 2 `c50c_uart3` `arbiter` 下发。
* **已导入的上位机核心代码资产（必须保留与增量演进，严禁推倒重来，源自 `XZCIT-IIR@feat/differential` `97e74d6`）**：
  * `Master/ROS/ros2_ws/src/c50c_uart3/`：已成熟的 ROS 2 串口桥（含 `protocol_v3`、`arbiter`、`ownership`、`motion_guard` 及 40+ 项 `firmware_harness` 仿真测试）。
  * `Master/ROS/ros2_ws/src/c50c_odom/`、`Master/ROS/nav2/`、`Master/ROS/config/`、`Master/ROS/systemd/`：实车验证过的里程计、EKF、Nav2 参数、地图与 systemd 服务单元。
  * `Master/ROS/ros2_ws/src/opi_robot/` & `Master/Web/opi_robot/`：包含 `lidar_node`、`cam_node`、`fusion_node`、`web_node`（含 `web_debug.py`）。
  * `Master/Web-Next/`：新一代 Web 管理平台（Rust Axum 后端 `src/` + 原生前端 `web/` + `deploy/ros_bridge_shim.py`）。
  * `.github/ros2-test-baseline.txt` & `.github/scripts/compare_ros2_tests.py`：ROS 2 测试回归比对基线（`ci.yml` 将在 WP1 接入并适配本仓 CMake 固件链路）。
* **旧版参考源码与硬件资料**：位于 `../robot/` 下的 `WHEELTEC_C50X_2026.05.29霍尔编码器/`、`C50C_V4.3原理图.pdf` 与 `C50C-V4.3集成板资源分配.pdf`（仅作为 `ICM20948`、`driver_d50a`、`auto_recharge`、引脚定义与差速参数表的逻辑参考，**禁止直接复制 StdPeriph 寄存器代码与阻塞式 `delay_us`**）。

### 2.2 标书硬性验收指标（所有设计必须对齐）

1. **7.1.3 速度范围**：$0.01 \sim 1.3\text{ m/s}$。底盘固件与 Nav2 双端硬限幅最大线速度为 $1.3\text{ m/s}$；极低速段需做低速非线性补偿或 M/T 法测速优化，避免量化抖动。
2. **7.1.6 导航方式**：2D 激光雷达 + 超声波 + 普通单目相机三模块协同导航与避障（2D 激光负责主力平面定位与几何避障，宽压版 HC-SR04 超声波负责近距防撞与玻璃/反光面补盲，普通单目相机通过轻量化 RKNN 语义障碍物检测 + 地平面投影及可选 AprilTag 地标实现视觉协同）。
3. **7.1.8 通信方式**：Wi-Fi 局域网通信。
4. **7.1.9 旋转半径**：$\ge 0.8\text{ m}$（**验收注意**：四轮差速底盘物理支持原地旋转，但标书字面要求 $\ge 0.8\text{ m}$，Nav2 控制器必须暴露可配置的 `min_turning_radius` 参数，支持一键切换至 $0.8\text{ m}$ 以应对字面验收）。
5. **7.2.1 自主巡逻**：2D 激光雷达 + 里程计/ICM-20948 IMU 融合定位（可选配普通单目相机 AprilTag/ArUco 视觉地标辅助消除长走廊漂移），结合三传感器协同避障保证长期定位精度与最优安全路径规划。
6. **7.2.2 自主充电**：电量低于设定阈值自动导航至充电桩预备点，移交 STM32 红外精对接完成自动充电，充满后离桩复巡（配合 $< 3\text{ h}$ 快充、$6\text{ h}$ 续航硬件）。
7. **7.2.3 远程操作**：支持外部干预（遥控优先级高于自主导航）；触发 SOS 后本体声光报警；支持平台端与机器人端**双向远程对讲**，支持平台端主动控制**远程音频喊话**。
8. **7.2.4 交互服务**：支持巡逻语音引导播报、物理**一键呼救报警（SOS）**及本地智能人机语音交互。
9. **7.2.5 AI 电力视觉**：支持现场图像抓拍，抓拍画面与 RKNN AI 算法电力设备缺陷研判结果联动推送至管理端与**学生智能终端**。

---

## 3. 硬件资源映射表（C50C-V4.3 已确认接线基准）

执行固件开发时，**必须严格以此表与 `C50C_HAL.ioc` 为准，严禁臆造或擅改引脚**：

| 功能模块 | 外设 / 通道 | STM32F407 引脚 | 硬件与电气配置要点 |
| :--- | :--- | :--- | :--- |
| 电机 PWM (A/B/C/D) | `TIM8 CH4/3/2/1` | `PC9, PC8, PC7, PC6` | 方向 IO 见 `Drivers/BSP/motor/motor.h` |
| 编码器 A / B / C / D | `TIM2 / TIM3 / TIM4 / TIM5` | `PA15/PB3`, `PA6/PA7`, `PB6/PB7`, `PA0/PA1` | 四倍频正交编码器模式 |
| **超声波测距（已接好）** | **`TIM1_CH1` + `GPIO_Output`** | **`PE9` (`ECHO`), `PE11` (`TRIG`)** | **宽压版 HC-SR04（$2.8 \sim 5.5\text{ V}$），VCC 接 `HDR2` `3V3`（避开航模口 ESD 芯片 `TPD4E02B04DQAR` 钳位区），GND 共地；必须停用原航模遥控 `TIM1` 捕获逻辑；使用 `TIM1_CH1` 硬件输入捕获测脉宽** |
| 9 轴 IMU (ICM-20948) | `GPIO 软件 I2C (400 kHz 开漏)` + `EXTI` | `PB8 (SDA), PB9 (SCL), PD3 (INT)` | 经 RS0102 电平转换；板载器件为 **ICM-20948**（非 MPU6050）；**硬件核验注意**：`C50C_V4.3原理图.pdf`（Sheet 2/4 `U19 RS0102YH8`）与出厂代码将 `PB9` 接 `SCL`、`PB8` 接 `SDA`，与 STM32F407 硬件 `I2C1` AF4（`PB8=SCL`, `PB9=SDA`）物理反接，故不可启用硬件 `I2C1`，须使用 400 kHz 开漏软件 I2C（DWT 周期定时 + 总线卡死 9 时钟恢复） |
| 上位机通信串口 | `USART1` / `USART3` | `PA9/PA10` (UART1), `PB10/PB11` (UART3) | CH9102F Type-C；修改前核对 `uartx_callback.c` 与 `c50c_uart3` 当前实际绑定端口 |
| D50A 驱动器监控 | `USART2` (RS485) | `PD5 (TX), PD6 (RX)` | 经 SP485EEN 芯片，遵循单任务队列独占总线 |
| 自动回充（红外对接） | `CAN1` | `PD0 (RX), PD1 (TX)` | 板载 SN65HVD230；接收 4 路红外与充电电流状态 |
| 电池电压采样 | `ADC1_IN8` | `PB0` | 滑动均值滤波，低电量阈值告警 |
| 蜂鸣器 & RGB 灯带 | `GPIO` / `TIM12, TIM9` | `PD11 (Buzzer)`, `PB15(R), PE6(G), PB14(B)` | RGB 经 AT8236 驱动，用于状态指示与 SOS 爆闪 |
| OLED / 使能开关 / 按键 | `GPIO` | `PD4/PE0/PE10/PD7` (OLED), `PE4` (EN), `PC5` (KEY) | 保留本地状态显示与硬件使能（核验提示：资源表写 `PD4/PE0/PE10/PD7`，原理图 `J4/U11` 标示为 `PD4/PE0/PE1/PD7`，移植驱动前须以实物/`oled.h` 核对） |
| **物理 SOS 一键呼救** | `EXTI5` | **`PE5`（预留空闲引出脚）** | 上拉输入 + 下降沿外部中断 + $20\text{ ms}$ 消抖 |

---

## 4. 全局工程红线（AI 必须遵守的 Invariants）

1. **禁止推倒重写 `c50c_uart3`**：所有上下位机通信扩展必须在现有 `protocol_v3` 上向后兼容地新增帧/字段，**必须保证 `.github/ros2-test-baseline.txt` 全部基线测试零退化**。
2. **底盘安全本地优先（Fail-Closed）**：
   * 已永久取消 PS2 手柄断链安全门；本地 Fail-Closed 安全门控仅检查物理急停（`PE4`）、物理 SOS（`PE5`，WP2 接入）、`USART3` 上位机指令失联超时（$> 500\text{ ms}$）、电池严重欠压及 `D50A` 驱动器报警（WP2 接入），无需 PS2 接收机或手柄在位即可由 ROS 2 `c50c_uart3` 直接驱动。上述任一安全事件发生时，必须在 STM32 本地直接切断电机 PWM，不得依赖 ROS 2 或 Wi-Fi。
   * 底盘固件**只允许存在唯一一个电机 PWM 输出出口**（`Motor_ApplyOutput`），任何任务不得绕过安全状态机直接写定时器 CCR 寄存器。
3. **禁止阻塞式外设驱动**：
   * 在 FreeRTOS 任务中严禁使用轮询死等 `delay_us()` 采集传感器。
   * 由于 `C50C-V4.3` 原理图 `PB8(SDA)`/`PB9(SCL)` 与 STM32F407 硬件 `I2C1` 引脚物理反接，`ICM-20948` 须在独立 $100\text{ Hz}$ IMU 任务中使用 **400 kHz 开漏软件 I2C**（基于 `DWT->CYCCNT` 微秒级节拍、不关全局中断、单次读 14 字节约 $0.35\text{ ms}$，并具备超时与 9 时钟总线恢复），严禁低速死等或长时间锁中断。
   * `HC-SR04`（`PE9`/`PE11`）必须使用 **`TIM1_CH1` 硬件输入捕获中断**完成脉宽测量（仅 `TRIG` 拉高脉冲为 $10 \sim 15\text{ }\mu\text{s}$ 极短延时或单脉冲定时器触发），并带 $28\text{ ms}$ 硬件超时保护与中值滤波。
   * 上位机串口收发必须使用 DMA + 空闲中断（IDLE）。
4. **停用航模遥控与 PS2 手柄逻辑**：由于 `PE9` / `PE11` 已改作超声波 `ECHO` / `TRIG`，且系统已取消 PS2 手柄控制，在 WP1–WP5 固件构建与初始化中必须彻底禁用原航模遥控器 `TIM1` 捕获代码（`remote.c` / `timx_callback.c`）以及原 PS2 手柄初始化、控制与断链安全门逻辑，防止中断向量与控制权冲突。
5. **音视频与控制流严格分离**：严禁通过 `rosbridge` 或 Python WebSocket JSON 传输高清视频流/音频流。视频、双向对讲、远程喊话必须走 **MediaMTX + WebRTC**；遥测、控制、告警、抓拍元数据走 **Gateway WebSocket/REST**。
6. **音频输出优先级仲裁**：`SOS 本地警报声（最高） > 平台远程喊话 / 双向对讲 > 巡逻语音播报 / 本地语音交互`。
7. **编码与注释门禁**：每次提交前必须确保所有新建/改动文件均为 **UTF-8（无 BOM）+ LF**，且严格符合第 1.2 节**先英文、后中文翻译**的双语注释要求。
8. **单相机采集源唯一与多路复用**：普通单目相机同时服务于 WP3 导航视觉、WP4 电力缺陷抓拍与 WP5 WebRTC 推流；必须由唯一采集/分发进程（如统一 `cam_node` 或 GStreamer/RK3588 MPP 分发管道）独占打开 `/dev/video*` 并向各消费者分发图像/码流，严禁多个 ROS 节点或守护进程并发争抢同一相机设备。

---

## 5. 目标目录结构规划

~~~text
XZCIT-IIR/
├── .editorconfig                    # [WP1] 强制 UTF-8 (无 BOM)、LF 换行与缩进规范
├── CMakeLists.txt                   # [WP1] 顶层 STM32 固件 CMake（替代 Makefile）
├── CMakePresets.json                # [WP1] stm32-diff-debug / stm32-diff-release / host-test
├── cmake/
│   └── arm-none-eabi.cmake          # [WP1] Cortex-M4F 交叉编译工具链
├── scripts/
│   └── check_encoding.py            # [WP1] CI 门禁脚本：检查 UTF-8 无 BOM 与 LF
├── protocol/
│   └── protocol_v3_ext.md           # [WP2] 协议 v3 扩展契约（单一事实来源）
├── Core/                            # 保留 CubeMX HAL 核心
├── Drivers/
│   ├── STM32F4xx_HAL_Driver/
│   └── BSP/
│       ├── hc_sr04/                 # [WP2] 重构为 PE9(TIM1_CH1 硬件捕获) + PE11(TRIG)
│       ├── icm20948/                # [WP2] 替换 MPU6050，按原理图 PB8(SDA)/PB9(SCL) 采用 400 kHz 开漏软件 I2C（受硬件 I2C1 反接约束）
│       ├── d50a_rs485/              # [WP2] 迁自 C50X，USART2 状态轮询
│       ├── can_auto_dock/           # [WP2] 迁自 C50X，CAN1 四路红外回充
│       ├── sos_button/              # [WP2] PE5 EXTI + 声光报警联动
│       └── ...                      # 保留现有 motor, encoder, oled, adc, buzzer, bsp_RGBLight, uartx
├── App/
│   ├── kinematics/                  # [WP1] 纯 C 差速运动学（无 HAL 依赖，可宿主机单测）
│   ├── control/                     # [WP1] 纯 C 增量式 PI + 速度平滑 + 0.01~1.3 m/s 限幅
│   ├── safety/                      # [WP2] 安全状态机（SOS/急停/超时/欠压/D50A故障）
│   ├── protocol/                    # [WP1/WP2] protocol_v3 编解码与打包
│   └── tasks/                       # [WP1] 精简后的 FreeRTOS 任务编排
├── tests/firmware_unit/             # [WP1] 宿主机 GCC + CTest 单元测试
├── Master/
│   ├── ROS/
│   │   ├── config/ & nav2/          # [WP3] 融合定位 + 2D激光/超声波/单目视觉地面投影三模块协同代价地图 + 转弯半径参数
│   │   └── ros2_ws/src/
│   │       ├── c50c_uart3/          # [WP2] 增量扩展回充/SOS/超声波话题与服务
│   │       ├── c50c_odom/           # 保留
│   │       ├── opi_robot/           # [WP3] 接入回充状态机；冻结 web_debug.py
│   │       ├── iir_interfaces/      # [WP2/WP4] 自定义 msg/srv/action
│   │       ├── iir_vision_rknn/     # [WP4] RK3588S NPU 电力缺陷检测 + 抓拍归档
│   │       └── iir_interaction/     # [WP5] 离线 TTS 巡逻播报 + ASR 交互 + 音频仲裁
│   ├── Gateway/                     # [WP4] 从 web_debug.py 抽离的 FastAPI/Axum 网关
│   └── Web-Next/                    # [WP4/WP5] 管理平台 + 学生智能终端页面 + WebRTC 对讲
└── deploy/                          # [WP5] MediaMTX 配置、udev 规则、systemd 自启服务
~~~

---

## 6. 分阶段执行工单（Work Packages）

> **执行指引**：按 `WP1 -> WP2 -> WP3 -> WP4 -> WP5` 顺序推进，每个 WP 独立提交 PR，合并前必须通过对应验收命令。

### WP1：工程规范基建、CMake + HAL 固件底座与模块化运动控制核心

* **目标**：建立 UTF-8 与双语注释门禁；在本地空白骨架中从零搭建基于 STM32CubeMX HAL + FreeRTOS + CMake + Ninja 的 STM32F407 固件底座；参照 `WHEELTEC_C50X_2026.05.29霍尔编码器` 参数表与已导入的 `Master/ROS/ros2_ws/src/c50c_uart3/` 协议契约，构建解耦可单测的 `App/` 核心模块与 `tests/firmware_unit/` 宿主机单测。
* **具体任务**：
  1. **编码规范基建**：
     * 在根目录新增 `.editorconfig`（全仓默认 `charset = utf-8`、`end_of_line = lf`）。
     * 新增 `scripts/check_encoding.py`，检测变更/核心源码文件是否为合法 UTF-8（无 BOM）及 LF 换行，并接入 `.github/workflows/ci.yml`。
  2. **CMake + STM32 HAL 固件底座搭建**：
     * 编写 `cmake/arm-none-eabi.cmake`（配置 Cortex-M4F 硬浮点 `-mfpu=fpv4-sp-d16 -mfloat-abi=hard`、链接脚本、`.elf/.hex/.bin` 产物生成与 `arm-none-eabi-size` 体积打印）。
     * 编写顶层 `CMakeLists.txt` 与 `CMakePresets.json`，提供 `stm32-diff-release`、`stm32-diff-debug` 与宿主机 `host-test` 三套预设，通过 `-DCHASSIS_TYPE=DIFF` 显式配置差速车型。
     * 补齐 `Core/`（时钟树、`main.c`、中断向量与 FreeRTOS 配置）、`Drivers/STM32F4xx_HAL_Driver/`、`Drivers/BSP/` 基础外设（`motor/` 唯一 PWM 出口、`encoder/`、`uartx/` DMA+IDLE、`adc/`、`oled/`、`buzzer/`、`bsp_RGBLight/`）及启动文件/链接脚本（基于 CubeMX HAL 标准初始化与 `C50C-V4.3` 引脚表，禁止引入旧 Keil `MDK-ARM/` 或 `STM32F407_StdPeriph`）。
  3. **模块化 `App/` 核心构建（零 HAL 依赖，支持宿主机单测）**：
     * 构建四轮差速正逆运动学至 `App/kinematics/`（纯 C11，零 HAL 依赖，参数对齐 `WHEELTEC_C50X` 差速参数表）。
     * 构建增量式 PI、速度平滑与低速非线性补偿（覆盖 $0.01 \sim 1.3\text{ m/s}$）至 `App/control/`。
     * 构建串口协议编解码至 `App/protocol/`，严格对照已导入的 `Master/ROS/ros2_ws/src/c50c_uart3/` 实现 `protocol_v3` 字节级兼容。
     * 构建精简 FreeRTOS 任务编排 `App/tasks/`，串接底盘控制闭环。
     * 在 `tests/firmware_unit/` 中编写宿主机单元测试（运动学正逆解、速度限幅、PI 饱和、协议编解码）。
     * **所有新建文件必须严格执行 UTF-8 无 BOM + 先英文后中文双语注释**。
  4. **创建并接入 CI**：参照 `XZCIT-IIR@feat/differential` 的分路径门禁设计编写 `.github/workflows/ci.yml`，接入 `check_encoding.py`、CMake 交叉编译、`host-test` 单元测试，以及 `Master/ROS`（`compare_ros2_tests.py` + `ros2-test-baseline.txt`）与 `Master/Web-Next` 检查。
* **验收标准**：
  * `python3 scripts/check_encoding.py` 通过。
  * `cmake --preset stm32-diff-release && cmake --build --preset stm32-diff-release` 零错误产出 `.elf/.bin`。
  * `cmake --preset host-test && cmake --build --preset host-test && ctest --preset host-test` 100% 通过。
  * 实车烧录后 OLED 及现有 `c50c_uart3` 联调零回归（不依赖 PS2 手柄，纯上位机串口/Wi-Fi 直接驱动）。

### WP2：补齐 C50C-V4.3 硬件驱动（含 PE9/PE11 超声波）、SOS 安全与 `protocol_v3` 扩展

* **目标**：完成底盘全部标书硬件驱动迁移与开发，并同步扩展 `protocol_v3` 与 `c50c_uart3`。
* **具体任务**：
  1. **HC-SR04 硬件捕获驱动 (`Drivers/BSP/hc_sr04/`)**：
     * 彻底移除原航模遥控 `TIM1` 捕获逻辑，避免与 `PE9`/`PE11` 冲突。
     * 配置 **`TIM1_CH1`（`PE9`, `ECHO`）** 为硬件输入捕获模式，定时器计数频率分频至 $1\text{ MHz}$（$1\text{ }\mu\text{s}$ 分辨率），自动测量上升沿至下降沿脉宽（支持单通道翻转极性或双通道 PWM Input 模式，正确处理计数器溢出）。
     * 配置 **`PE11`（`TRIG`）** 为普通推挽输出，周期触发 $10 \sim 15\text{ }\mu\text{s}$ 高电平脉冲（触发周期 $60\text{ ms}$，防回波串扰）。
     * 增加 **$28\text{ ms}$ 硬件超时保护**（覆盖 $4.50\text{ m}$ 满量程）、有效量程过滤（$0.02 \sim 4.50\text{ m}$）与 3\~5 点中值滤波；超时或无效时输出无效标记（`NaN` 或 `0xFFFF`）。
  2. **ICM-20948 400 kHz 开漏软件 I2C 驱动 (`Drivers/BSP/icm20948/`)**：
     * 因已核验 `C50C_V4.3原理图.pdf` 将 `PB9` 接 `SCL`、`PB8` 接 `SDA`（与 STM32F407 硬件 `I2C1` AF4 引脚反接），不可启用硬件 `I2C1`；须使用 HAL GPIO 开漏模式 + `DWT->CYCCNT` 精准微秒节拍实现 **400 kHz 软件 I2C**（附超时与 9 时钟总线卡死恢复），配合 `PD3` `INT1` 外部中断通知或 $100\text{ Hz}$ 独立 IMU 任务完成稳定采样与开机静置陀螺仪零偏校准，替换旧版 MPU6050。
  3. **D50A RS485 驱动器监控 (`Drivers/BSP/d50a_rs485/`)**：
     * 迁移 `WHEELTEC_C50X` 的 `driver_d50a` 单任务队列独占架构至 HAL `USART2`（`PD5`/`PD6`），$10\text{ Hz}$ 轮询电流、温度与过流/过温/欠压/过压报警位。
  4. **CAN1 自动回充 (`Drivers/BSP/can_auto_dock/`)**：
     * 迁移 `CAN1`（`PD0`/`PD1`）接收回调，解析 4 路红外信号（`L_A/L_B/R_A/R_B`）、充电电流与充电标志位，实现差速车红外对接闭环控制逻辑。
  5. **物理 SOS 按钮与声光报警 (`Drivers/BSP/sos_button/` + `App/safety/`)**：
     * 配置 `PE5` 为上拉输入 + 下降沿外部中断（$20\text{ ms}$ 消抖）。
     * 触发 SOS 后 `App/safety/` 立即在唯一电机出口切断 PWM，RGB 灯带进入最高优先级 `RGB_SOS_ALARM`（红灯高频爆闪），蜂鸣器（`PD11`）急促鸣响。
  6. **扩展 `protocol_v3` 与 `c50c_uart3` 对齐**：
     * 在 `protocol/protocol_v3_ext.md` 定义新增帧/字段：
       * 下行：`SET_AUTO_DOCK(enable)`、`SET_SOS(active)`、`SET_LED_BEEP(mode)`。
       * 上行：`charging_state / charging_current / ir_mask`、`sos_active / d50a_alarm_mask`、`ultrasonic_range_m`（主超声波 `PE9`/`PE11` 测距值，预留多路扩展）。
     * 在 `c50c_uart3` 中增量支持上述消息，发布标准 `/ultrasonic/front`（`sensor_msgs/Range`：`radiation_type = ULTRASOUND`, `field_of_view = 0.2618`, `min_range = 0.02`, `max_range = 4.50`）、`/chassis/safety_status`、`/chassis/dock_status` 及对应 ROS 2 Service。
     * **必须同步更新 `test/firmware_harness/fw_v3_harness.py` 及新增单元测试**。
* **验收标准**：
  * `colcon test --packages-select c50c_uart3` 全绿，且通过 `.github/scripts/compare_ros2_tests.py` 基线比对无退化。
  * 实车测试：超声波在 $20\text{ cm} \sim 200\text{ cm}$ 范围内读数稳定准确、无明显抖动；按下 `PE5` SOS 按钮 $50\text{ ms}$ 内断电停机并声光报警；上位机可实时收到状态并远程复位。

### WP3：2D 激光雷达 + 超声波 + 普通单目相机三模块协同导航与自主回充闭环

* **目标**：满足标书 7.1.6、7.1.9、7.2.1、7.2.2，基于普通单目 RGB 相机硬件配置，实现 2D 激光雷达、超声波与普通单目相机三模块协同导航、避障与低电量全自动回充。
* **具体任务**：
  1. **传感器标定、TF 与三模块协同代价地图**：
     * 完成普通单目相机内参与畸变标定（产出 `camera_info.yaml`），固化 `base_link` 到 2D 激光雷达、普通单目相机（`camera_link` / `camera_optical_frame`）、前置超声波（`ultrasonic_front_link`）的静态 TF。
     * 建立**单相机唯一采集与多路分发管道**（`cam_node` / GStreamer + RK3588 MPP 分发，满足全局红线第 8 条），确保 WP3 导航视觉、WP4 电力缺陷抓拍与 WP5 WebRTC 视频推流共用同一相机流而不争抢 `/dev/video*`。
     * 更新 `Master/ROS/nav2/nav2_params_20261120.yaml`（采用 2D 代价层与地平面投影点云层组合，不启用 3D 体素图层），在 `local_costmap` 同时启用三传感器协同图层：
       * `ObstacleLayer`（2D LiDAR，主力平面几何避障）；
       * `RangeSensorLayer`（订阅 `/ultrasonic/front`，室内建议 `obstacle_max_range` 设为 $1.5 \sim 2.0\text{ m}$，负责近距硬防撞与玻璃门/反光面补盲）；
       * 辅助视觉 `ObstacleLayer`（订阅 `/vision/ground_obstacles` `sensor_msgs/PointCloud2`：由普通单目相机经轻量化 RKNN 语义障碍物/行人检测 + 内参标定地平面单应性投影 IPM 生成，限距 $0.5 \sim 3.0\text{ m}$ 防止远距投影误差污染代价地图，近距仍以激光与超声波为硬底线）。
     * 显式暴露 `min_turning_radius` 参数（支持配置为 $0.8\text{ m}$ 满足 7.1.9 验收）和最大速度 $1.3\text{ m/s}$（7.1.3）。
  2. **融合定位增强**：核对 `Master/ROS/config/ekf.yaml`，确认稳定融合 `c50c_odom` 与 `ICM-20948` 航向角速度，并接入 2D 激光雷达 AMCL/SLAM；在长走廊（激光退化段）、充电桩及关键巡检点可选配普通单目相机 `AprilTag / ArUco` PnP 视觉地标辅助重定位。
  3. **两段式自主回充状态机**：
     * 电量低于阈值或收到远程回充指令时，中断巡逻并由 Nav2 导航至充电桩前 $0.8 \sim 1.0\text{ m}$ 预备点（可选配单目 `AprilTag` 视觉确认预备点对准精度）。
     * 到达预备点后暂停 Nav2 速度输出，调用 `c50c_uart3` 回充服务移交 STM32 执行 `CAN1` 四路红外精对接。
     * 监测 `charging == 1` 且电流稳定；充满后执行安全退桩动作，退出回充并恢复巡逻。
* **验收标准**：
  * 多点自主巡逻连续运行无定位漂移；面对玻璃门由超声波可靠防撞，面对行人/低矮杂物可由单目语义投影 + 激光/超声波安全绕行；相机多路复用期间无 `/dev/video*` 冲突；低电量完整走通“返航 -> 红外对接 -> 充电 -> 离桩复巡”闭环。

### WP4：RKNN 电力设备缺陷视觉识别与 Web-Next / 学生终端联动

* **目标**：满足标书 7.2.5，利用 RK3588S NPU 实现 AI 缺陷识别，并解耦 `web_debug.py` 对接 `Master/Web-Next`。
* **具体任务**：
  1. **新建 `iir_interfaces` 与 `iir_vision_rknn`**：
     * 基于 `rknn-toolkit-lite2` 在 RK3588S NPU 上运行电力设备缺陷检测模型（YOLOv8/v11 `.rknn` INT8 量化模型；若专属权重暂未就绪，先保留标准 RKNN 推理抽象并提供默认测试权重确保端到端链路跑通）；图像输入须订阅统一单相机采集管道（满足全局红线第 8 条，禁止直接打开 `/dev/video*`）。
     * 提供 `/inspection/capture` ROS 2 Service，支持巡检点自动抓拍与远程手动抓拍，输出原图 + 检测框标注图 + 结构化 JSON（时间、点位、坐标、缺陷类别、置信度）。
  2. **构建 `Master/Gateway`（解耦 142KB 的 `web_debug.py`）**：
     * 冻结 `opi_robot/web_node/web_debug.py` 仅作底层调试用。
     * 使用 FastAPI（或 Rust Axum）提供轻量业务网关：WebSocket 推送位姿（$5\text{ Hz}$）、电量、巡逻进度、SOS 紧急弹窗、AI 抓拍与缺陷告警；REST API 承接遥控（走 `c50c_uart3` `arbiter` 最高遥控优先级）、巡逻编排、手动抓拍、回充与历史记录查询。
  3. **完善 `Master/Web-Next`（管理端 + 学生智能终端视图）**：
     * 管理端：地图监控、虚拟摇杆遥控、巡检点编排、SOS 报警弹窗与复位、回充控制、缺陷告警中心。
     * **学生智能终端视图（移动端响应式 H5 路由 `/student`）**：实时联动接收现场抓拍画面与 AI 电力设备缺陷研判报告，支持历史回看。
* **验收标准**：
  * RKNN 推理帧率 $\ge 15\text{ FPS}$ 且上位机 CPU 占用 $< 30\%$。
  * 巡检点触发抓拍后 $2\text{ s}$ 内，管理端与 `/student` 学生端均可见标注图像与研判结果。
  * `Master/Web-Next` 的 CI `lint` 与 `build` 全绿。

### WP5：WebRTC 双向对讲、远程喊话、离线语音交互与整机部署

* **目标**：满足标书 7.2.3（双向对讲/远程喊话）、7.2.4（巡逻播报/本地人机交互），实现整机上电自启。
* **具体任务**：
  1. **WebRTC 音视频与双向对讲 (`deploy/mediamtx/` + `Web-Next`)**：
     * 在 Orange Pi 5 Pro 部署 `MediaMTX`，视频流从统一单相机采集管道取流（满足全局红线第 8 条，禁止独占/争抢 `/dev/video*`），经 RK3588 MPP 硬件 H.264 编码推流，Web 端通过 WHEP 低延迟拉流。
     * 部署车端音频守护进程：车端麦克风通过 WebRTC 回传平台端；平台端 WHIP 音频经回声消除（AEC，如 PipeWire/PulseAudio `module-echo-cancel`）后输出至功放喇叭。
     * 在 `Web-Next` 中提供“双向对讲”与“远程喊话（一键抢占）”功能。
  2. **离线语音交互节点 (`iir_interaction`)**：
     * 集成离线 TTS（如 `Sherpa-ONNX` VITS/Piper）实现出发、转弯、避障、到点、低电量回充、SOS 等巡逻语音引导播报。
     * 集成离线 ASR 关键词唤醒，支持本地基础语音指令（“暂停巡逻”、“继续巡逻”、“报告电量”、“呼叫管理员”）。
     * 实现严格音频仲裁器：`SOS 警报 > 远程喊话/对讲 > 巡逻播报/本地交互`。
  3. **运维自启脚本 (`deploy/`)**：
     * 编写 `udev` 规则固定底盘串口（`/dev/iir_chassis`）、雷达串口（`/dev/iir_lidar`）与相机设备名。
     * 编写 `systemd` 服务单元实现整机开机按依赖顺序自动拉起全部服务。
* **验收标准**：
  * Wi-Fi 局域网下双向对讲端到端延迟 $< 400\text{ ms}$，无明显啸叫；远程喊话可立即抢占当前巡逻播报。
  * 整机上电无需人工 SSH 干预，$60\text{ s}$ 内全链路自动上线。

---

## 7. 给其他 AI 助手的会话启动 Prompt 模板

向其他 AI 派发具体阶段任务时，请直接复制并附带以下指令：

> “请仔细阅读根目录的 `AI_EXECUTION_PLAN.md`。本次会话我们只执行 **WPx（请替换为具体工单编号，如 WP1）**。
>
> 1. 先检查仓库中与本工单相关的所有现有文件，列出修改清单与影响评估，确认不违反第 3 节硬件引脚表和第 4 节的任何工程红线；
> 2. **严格遵守第 1 节编码与注释规范**：所有新建或修改的文件必须保存为 **UTF-8（无 BOM）+ LF**，所有代码注释必须**先写英文注释，再紧跟其准确的中文翻译**，严禁直接写纯中文注释；
> 3. 逐步完成代码实现与对应单元测试；
> 4. 运行本工单的全部验收命令（含编码检查、编译与测试）并贴出真实输出，未全部通过前不要声称完成。”
