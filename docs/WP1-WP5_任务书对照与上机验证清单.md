# WP1–WP5 任务书对照与上机/板端验证清单

> 生成日期：2026-11-26
> 任务书依据：仓库根目录 `AI_EXECUTION_PLAN.md`（最新版，328 行）与原始 `xzcit_iir.md`（早期版，320 行）。
> 适用本地快照：
> - WP1–WP4：`inspection-robot` 主工作树（`dev/wp4`，含 WP1/WP2 已提交内容与 WP3/WP4 未提交改动）
> - WP5：`/home/snow/.codex/worktrees/wp5-interfaces/inspection-robot`（`dev/wp5` 独立工作树，未提交）
>
> 本文只描述代码与离线验证事实，不把“代码已写”当作“实车验收通过”。

## 0. 图例与任务书版本差异

### 0.1 状态图例

| 标记 | 含义 |
| :--- | :--- |
| ✅ | 纯代码已完成，且本机离线验证通过 |
| 🟡 | 代码已完成，但必须连接板端/实车做联调确认 |
| 🔴 | 代码或配置仍有缺口，需要现场参数、模型、标定或硬件环境才能完成 |
| `[板]` | 必须连接 STM32 板卡、传感器或执行器才能确定 |
| `[车]` | 必须整车上机、实际场景运行才能确定 |
| `[ROS]` | 必须 ROS 2 / `colcon` 环境（可在容器或板端） |
| `[模型]` | 必须提供实测标定文件、RKNN 模型或真实权重 |
| `[人工]` | 必须现场人工确认声、光、方向、手感、听感等主观指标 |

### 0.2 任务书版本差异（必须先统一口径）

任务书存在两个版本，部分硬件与验收口径冲突，必须以最新 `AI_EXECUTION_PLAN.md` 为准，并在上机前与验收方确认：

| 项目 | `xzcit_iir.md`（早期版） | `AI_EXECUTION_PLAN.md`（仓库最新版） | 本地实现/风险 |
| :--- | :--- | :--- | :--- |
| WP1 起点 | 要求拆分 80KB `App/BALANCE/balance_task.c` | 要求在空白骨架中从零构建 HAL + CMake 固件 | 本地按最新版从零构建；`App/BALANCE` 已不存在 |
| ICM-20948 总线 | `I2C1` 硬件 I2C（`PB8/PB9`） | 原理图 `PB8/PB9` 与硬件 I2C1 AF4 反接，必须 400 kHz 开漏 **软件 I2C** | 本地按最新版实现软件 I2C；需 `[板]` 用万用表/示波器确认 PB8/PB9 实际接线与上拉 |
| WP3 视觉传感器 | 深度相机，`VoxelLayer` 3D 点云 | 普通单目 RGB 相机，地面投影 + 2D 视觉 `ObstacleLayer` | 本地按最新版使用单目相机与 2D `vision_layer`；若验收方按旧版检查深度相机，属于硬件范围变更，需另行确认 |
| PS2 手柄 | 旧版仍有手柄描述 | 永久移除 PS2 手柄、控制逻辑与断链安全门 | 本地 `App/Drivers/Core` 未发现 PS2/`remote.c`/`timx_callback` 残留；仍需 `[板]` 确认无旧初始化 |
| WP2 验收 | 仅写 `colcon test` | 追加 CI 基线零退化要求 | 本地只跑纯 Python/宿主测试，`[ROS]` 仍需执行完整基线 |

> **结论**：上机前请先确认按哪一版任务书验收。本文默认按 `AI_EXECUTION_PLAN.md` 逐项对照；旧版差异项会在对应条目中再次标注。

---

## 1. 全局工程红线逐条核对

| 红线 | 本地代码/离线核对 | 上机/板端必须确认 |
| :--- | :--- | :--- |
| 禁止推倒重写 `c50c_uart3`，基线零退化 | 本地仅在现有 `protocol_v3` 上增量扩展；纯 Python 定向测试 19 项通过 | `[ROS]` 必须在 ROS 2 Humble 容器执行 `colcon test --packages-select c50c_uart3`，并与 `.github/ros2-test-baseline.txt` 比对 |
| Fail-Closed：急停/SOS/串口 >500 ms/欠压/D50A 故障本地切 PWM | `App/safety` 与 `App/control` 已有安全状态机；宿主机 `test_safety_and_wp2` 通过 | `[板]` 实测 PE4/PE5 触发到 PWM 断电的延迟、USART3 断流 500 ms、欠压阈值、D50A 报警；必须示波器/逻辑分析仪确认 |
| 唯一电机 PWM 出口 `Motor_ApplyOutput` | `grep` 确认 `App/tasks/app_tasks.c` 只经由 `Motor_ApplyOutput` 输出；`Drivers/BSP/motor/bsp_motor.c` 注册底层回调 | `[板]` 静态检查全部定时器 CCR 写入路径，确认没有任务绕过；实车确认四轮停转 |
| 禁止阻塞式外设驱动 | HC-SR04 使用 TIM1 输入捕获；ICM-20948 软件 I2C；UART DMA + IDLE 设计 | `[板]` 实测 TIM1 捕获 1 MHz 分辨率、28 ms 超时；ICM-20948 100 Hz 采样与总线恢复；UART DMA/IDLE 丢帧率 |
| 停用航模遥控与 PS2 逻辑 | 未发现 `PS2`、`ps2`、`remote.c`、`timx_callback` 残留 | `[板]` 确认旧工程未通过其他方式初始化 TIM1 捕获或 PS2 GPIO |
| 音视频与控制流分离 | WP4 Gateway 只传 JSON/抓拍元数据；WP5 设计为 MediaMTX + WebRTC | `[车]` 浏览器实测：视频/音频不经 WebSocket JSON；WebSocket 只承载控制与遥测 |
| 音频优先级 `SOS > 喊话/对讲 > 巡逻播报/本地交互` | WP5 `iir_interaction.arbitration` 有优先级实现；本地 66 项测试通过 | `[车]` 实车播放中触发 SOS、远程喊话抢占巡逻播报，确认无混音/啸叫 |
| UTF-8 无 BOM + LF + 先英后中注释 | `python3 scripts/check_encoding.py`：PASS，366 文件 | 无（每次提交/上机前重跑） |
| 单相机采集源唯一，多消费者复用 | `cam_node` 为唯一 V4L2 打开者；`iir_vision_rknn`/`fusion_node`/`web_debug` 只订阅 `/image_raw/compressed` | `[板]` `fuser -v /dev/video*`、`lsof` 确认只有 `cam_node` 打开；三消费者同时订阅无花屏/掉帧 |

---

## 2. WP1：工程规范、CMake/HAL 底座、模块化运动控制

### 2.1 任务逐项对照

| ID | 任务书要求 | 本地代码/离线状态 | 需上机/接板确认 |
| :--- | :--- | :--- | :--- |
| WP1-1 | `.editorconfig`：UTF-8、LF、缩进规范 | ✅ 文件存在 | 无 |
| WP1-2 | `scripts/check_encoding.py` 并接入 CI | ✅ 脚本存在；本机 PASS（366 文件） | 无 |
| WP1-3 | `cmake/arm-none-eabi.cmake`：Cortex-M4F 硬浮点、链接脚本、`.elf/.hex/.bin` | ✅ 文件存在；`stm32-diff-release` 构建通过 | `[板]` 烧录后确认启动、时钟、FPU |
| WP1-4 | 顶层 `CMakeLists.txt` / `CMakePresets.json`：debug/release/host-test 三预设，`-DCHASSIS_TYPE=DIFF` | ✅ 文件存在；`host-test` 5/5、`stm32-diff-release` 通过 | `[板]` 确认实际固件版本与调试构建一致 |
| WP1-5 | `Core/`：时钟树、`main.c`、中断向量、FreeRTOS 配置 | 🟡 代码存在，编译通过 | `[板]` 实测 HSE/PLL、SysTick、FreeRTOS 启动、堆栈水位、看门狗 |
| WP1-6 | `Drivers/BSP` 基础外设：motor/encoder/uartx/adc/oled/buzzer/RGB | 🟡 代码存在 | `[板]` 逐个确认设备在位、引脚、极性、PWM 频率、OLED 控制器型号 |
| WP1-7 | `App/kinematics`：四轮差速正逆运动学，纯 C11 零 HAL | ✅ 代码存在；`test_kinematics` 通过 | `[板]` 用实测轮径/轮距/编码器 CPR 校验；前后左右方向 |
| WP1-8 | `App/control`：增量式 PI、速度平滑、低速补偿、0.01–1.3 m/s 限幅 | ✅ 代码存在；`test_control` 通过 | `[板]` 逐档标定 PI、死区、最低稳定速度；确认 1.3 m/s 未在底盘链路被钳制 |
| WP1-9 | `App/protocol`：protocol_v3 编解码，与 `c50c_uart3` 字节兼容 | ✅ 代码存在；`test_protocol_v3` / `test_protocol_interop` 通过 | `[板]` 接 CH9102F 与 `c50c_uart3` 实际联调，核对波特率、校验、粘包/断包 |
| WP1-10 | `App/tasks`：精简 FreeRTOS 任务编排，串接控制闭环 | ✅ 代码存在 | `[板]` 实测任务周期 100 Hz、栈使用、优先级、CPU 占用、看门狗喂狗 |
| WP1-11 | `tests/firmware_unit`：运动学/限幅/PI/协议宿主机测试 | ✅ 5/5 CTest 通过 | 无（宿主机） |
| WP1-12 | CI：encoding + CMake 交叉编译 + host-test + ROS/Web-Next 检查 | ✅ `.github/workflows/ci.yml` 已接入 | `[ROS]` CI 的 ROS 2 job 需在 CI/容器实际跑通（本机无 ROS） |
| WP1-13 | 验收：`check_encoding.py` 通过 | ✅ 本机 PASS | 无 |
| WP1-14 | 验收：`stm32-diff-release` 零错误产出 `.elf/.bin` | ✅ 构建通过，`.elf/.hex/.bin` 存在 | `[板]` 烧录验证 |
| WP1-15 | 验收：`host-test` 100% 通过 | ✅ 5/5 | 无 |
| WP1-16 | 验收：实车烧录后 OLED + `c50c_uart3` 联调零回归 | 🔴 未执行 | `[板][车][人工]` OLED 显示、串口联调、无 PS2 手柄直接驱动 |

### 2.2 WP1 上机/接板结论

- **纯代码/离线部分：完成。**
- **必须上机**：烧录 `xzcit_iir_diff.elf`，确认 OLED、时钟、FreeRTOS、四轮转向、`c50c_uart3` 串口直驱。
- **必须连接板子才能确定**：HSE 晶振频率、PLL 配置、电机方向 IO、编码器 A/B 相序、OLED 控制器、USART1/USART3 实际绑定、PWM 频率与死区。

---

## 3. WP2：C50C-V4.3 硬件驱动、SOS 安全与 protocol_v3 扩展

### 3.1 任务逐项对照

| ID | 任务书要求 | 本地代码/离线状态 | 需上机/接板确认 |
| :--- | :--- | :--- | :--- |
| WP2-1 | HC-SR04：停用航模遥控 TIM1 捕获 | ✅ 未发现 `remote.c`/`timx_callback`/`PS2` 残留 | `[板]` 确认旧固件初始化路径不存在；TIM1 中断向量只被超声波使用 |
| WP2-2 | HC-SR04：PE9=`ECHO`（TIM1_CH1 输入捕获，1 MHz，28 ms 超时） | 🟡 代码存在，宿主机逻辑测试通过 | `[板]` 示波器测 PE9 脉宽、1 MHz 计数、28 ms 超时；PE11 TRIG 10–15 µs/60 ms |
| WP2-3 | HC-SR04：量程 0.02–4.50 m、3–5 点中值滤波、无效标记 | 🟡 代码存在 | `[板]` 20–200 cm 多点实测（任务书验收值），记录抖动/丢帧；玻璃/反光面复测 |
| WP2-4 | ICM-20948：PB8/PB9 软件 I2C 400 kHz、PD3 INT、100 Hz、零偏校准 | 🟡 代码存在（按最新版软件 I2C） | `[板]` 万用表/示波器确认 PB8=SDA、PB9=SCL 与上拉；读 `WHO_AM_I`；静止零偏；100 Hz 采样抖动；9 时钟恢复 |
| WP2-5 | D50A RS485：USART2 PD5/PD6，10 Hz 轮询电流/温度/报警 | 🟡 代码存在 | `[板]` 确认波特率、SP485EEN 使能、终端电阻；核对电流符号与报警位极性 |
| WP2-6 | CAN1 自动回充：PD0/PD1，四路红外/充电电流/充电标志 | 🟡 代码存在 | `[板]` 用充电桩实测 CAN 帧 ID、4 路红外映射、充电电流符号、接触/满电标志 |
| WP2-7 | SOS：PE5 上拉 + 下降沿 EXTI + 20 ms 消抖，切 PWM + RGB 爆闪 + 蜂鸣器 | 🟡 代码存在 | `[板][人工]` 实测 20 ms 消抖、50 ms 内断电停机、RGB 红灯爆闪、PD11 蜂鸣；上位机收到状态并可远程复位 |
| WP2-8 | protocol_v3 扩展：SET_AUTO_DOCK/SET_SOS/SET_LED_BEEP；上行 charging/sos/d50a/ultrasonic | ✅ 契约 `protocol/protocol_v3_ext.md` 存在；`test_protocol_v3_ext` 等通过 | `[板]` 实际 `c50c_uart3` 收发握手；`/ultrasonic/front` `sensor_msgs/Range` 字段核对（radiation_type、FOV 0.2618、0.02–4.50） |
| WP2-9 | 同步更新 `fw_v3_harness.py` 与新增单元测试 | ✅ 已更新；宿主机 `test_safety_and_wp2` / interop 通过 | `[ROS]` `colcon test --packages-select c50c_uart3` 全量与基线比对 |
| WP2-10 | 验收：`colcon test` 全绿且基线无退化 | 🔴 本机未执行（无 ROS 2） | `[ROS]` 必须在 ROS 2 Humble 容器/板端执行 |
| WP2-11 | 验收：超声波 20–200 cm 稳定准确 | 🔴 未执行 | `[板][人工]` 多点标尺实测，记录均值/方差/最大误差 |
| WP2-12 | 验收：PE5 SOS 50 ms 内断电并声光报警 | 🔴 未执行 | `[板][人工]` 示波器测 PWM 关断延迟，录像/记录声光 |

### 3.2 WP2 上机/接板结论

- **纯代码/离线部分：完成。**
- **必须连接板子才能确定**：PE9/PE11 实际接线、HC-SR04 供电（HDR2 3V3 与 ESD 区）、PB8/PB9 物理反接、PD3 INT、D50A 收发器、CAN1 收发器、PE5 按键、PD11 蜂鸣器、RGB 灯带。
- **必须上机**：20–200 cm 超声实测、SOS 50 ms 停机、D50A/CAN 联调、`c50c_uart3` 全量 `colcon test`。

---

## 4. WP3：三传感器协同导航与自主回充

### 4.1 任务逐项对照

| ID | 任务书要求 | 本地代码/离线状态 | 需上机/接板确认 |
| :--- | :--- | :--- | :--- |
| WP3-1 | 相机内参与畸变标定，产出 `camera_info.yaml` | 🔴 仓库未发现 `camera_info.yaml`/标定文件 | `[模型][板]` 用棋盘格实测内参、畸变；实际相机分辨率/焦距 |
| WP3-2 | `base_link`→激光/相机/超声波静态 TF | 🟡 `robot.launch.py` 提供参数入口，`camera_x/y/z/roll/pitch/yaw` 默认为空 | `[板]` 实测安装位置/姿态；确认 `camera_link`→`camera_optical_frame` 轴向 |
| WP3-3 | 单相机唯一采集与多路分发（导航/抓拍/WebRTC 共用） | 🟡 `cam_node` 是唯一 V4L2 打开者，其他节点订阅 `image_raw/compressed`；WP5 需 RTSP 上游 | `[板]` `lsof/fuser /dev/video*` 确认唯一打开；三消费者并发；WP5 需实际 RTSP/H.264 源 |
| WP3-4 | `local_costmap` 三图层：ObstacleLayer + RangeSensorLayer + 视觉 ObstacleLayer | ✅ `nav2_params_20261120.yaml` 已配置 `obstacle_layer`、`ultrasonic_layer`、`vision_layer` | `[板]` 实际 LiDAR/超声/视觉数据驱动图层；调 `obstacle_max_range`/`vision` 限距（0.5–3.0 m） |
| WP3-5 | `min_turning_radius` 可配置 0.8 m | 🟡 `nav2_navigation.launch.py` 暴露参数；`nav_relay.py` 仅对不满足半径的命令输出零速 | `[车]` 实际 Nav2 路径能否满足 0.8 m；拒绝命令是否导致停车/重规划；不能用参数存在代替路径验证 |
| WP3-6 | 最大速度 1.3 m/s 双端硬限幅 | 🔴 `nav2_navigation.launch.py` 的 `max_speed` 默认 0.12；`WP3_IMPLEMENTATION.md` 明确中继仍钳制到 0.15 m/s | `[板][车]` 逐级提速、底盘/导航双端限幅；确认 1.3 m/s 未被 smoother/relay/bridge 钳制；安全制动距离 |
| WP3-7 | EKF 融合 `c50c_odom` + ICM-20948 航向角速度 + AMCL/SLAM | 🟡 `Master/ROS/config/ekf.yaml` 存在；需实际 IMU/里程计 | `[板]` 检查 `/odom`、`/imu/data_raw`、`/odom_candidate` 频率与符号；长走廊定位漂移 |
| WP3-8 | 可选 AprilTag/ArUco 视觉地标辅助重定位 | 🔴 仓库未发现 AprilTag/ArUco 代码或标定 | `[模型][板]` 若需要，补装标签检测、相机内参、标签尺寸；否则作为可选功能向验收方说明 |
| WP3-9 | 两段式回充：低电→预备点→暂停 Nav2→红外精对接→充电稳定→退桩→复巡 | 🟡 `charging.py`、`wp3_charging.yaml`、`charging.py` 状态机、`/charging/request`、`/charging/status` 已实现 | `[板][车]` 预备点坐标、红外方向、充电电流符号/阈值、稳定窗口、满电信号来源、退桩距离/速度/超时、复巡 |
| WP3-10 | 回充参数必须现场标定，`.nan` 不是可用值 | 🔴 `wp3_charging.yaml` 全部为 `.nan`，`enable_autonomous_charging: false` | `[板][车]` 填写实测值并逐项验证；未填前禁止启用 |
| WP3-11 | 验收：多点自主巡逻连续运行无定位漂移 | 🔴 未执行 | `[车]` 实际地图多点巡逻、长时间运行、长走廊/充电桩附近 |
| WP3-12 | 验收：玻璃门/行人/低矮障碍物安全绕行 | 🔴 未执行 | `[车]` 玻璃/反光面、行人、低矮杂物场景；确认激光+超声+视觉融合 |
| WP3-13 | 验收：低电量完整走通返航→对接→充电→离桩复巡 | 🔴 未执行 | `[车]` 全闭环实车测试，记录每阶段状态与电流/电压曲线 |

### 4.2 WP3 上机/接板结论

- **纯代码/离线部分：基本完成。** 19 项 c50c WP3 测试、78 项 opi_robot 回充/巡逻测试、3 项 nav2 中继测试通过。
- **代码明显缺口（非纯上机）**：
  - 相机标定文件缺失（`camera_info.yaml` 未生成）。
  - `max_speed` 默认 0.12 m/s，尚未实现/验证 1.3 m/s。
  - `min_turning_radius` 仅拒绝不满足命令，不保证 Nav2 生成满足 0.8 m 的路径。
  - `wp3_charging.yaml` 全部 `.nan`，未填写现场参数。
  - AprilTag/ArUco 可选功能未实现。
- **必须连接板子才能确定**：相机内参/畸变/安装 TF、LiDAR-IMU 外参、轮径/轮距/编码器 CPR、充电桩 CAN 帧与电流符号、电池分压比、超声波/视觉实际安装位置。
- **必须整车上机**：多点巡逻、玻璃门/行人避障、完整回充闭环、1.3 m/s 提速、0.8 m 转弯半径字面验收。

---

## 5. WP4：RKNN 电力缺陷识别、Gateway、Web-Next/学生端

### 5.1 任务逐项对照

| ID | 任务书要求 | 本地代码/离线状态 | 需上机/接板确认 |
| :--- | :--- | :--- | :--- |
| WP4-1 | `iir_interfaces`：缺陷 msg、抓拍 srv、告警 msg | ✅ 3 msg + 1 srv 已建立 | `[ROS]` `colcon build` 生成 Python/C++ 绑定 |
| WP4-2 | `iir_vision_rknn`：`rknn-toolkit-lite2` / YOLOv8/v11 `.rknn` INT8 | 🟡 代码存在；`RKNNLite` 后端 + `MockBackend` 回退；本机无 NPU，仅纯逻辑测试 | `[模型][板]` 提供实际 `.rknn`、标签文件；确认 RKNN Toolkit Lite2 版本与 NPU 驱动 |
| WP4-3 | 图像输入订阅统一单相机管道，禁止直接打开 `/dev/video*` | ✅ `node.py` 订阅 `/image_raw/compressed`，不打开 V4L2 | `[板]` 确认与 `cam_node` 同一源、QoS 匹配、无二次打开 |
| WP4-4 | `/inspection/capture` ROS Service：自动/手动抓拍，原图+标注图+JSON | ✅ 服务/归档/JSON 代码存在；14 项逻辑测试通过（1 项无 OpenCV 跳过） | `[ROS][板]` 真实 ROS 服务调用；真实相机帧；归档目录写权限 |
| WP4-5 | `Master/Gateway`：FastAPI/Axum，WebSocket 推送位姿 5 Hz/电量/巡逻/SOS/AI 告警；REST 遥控/巡逻/抓拍/回充/历史 | 🟡 `Master/Gateway` 已实现巡检 REST/WS/历史；位姿/电量/巡逻/SOS 仍由现有 Rust Web-Next `/ws` 承载（避免第二控制发布者） | `[板]` 确认 Gateway 与 Web-Next 的端口/来源配置；ROS service 后端联调；控制链路仍走 Web-Next |
| WP4-6 | 管理端：地图/摇杆/巡检点编排/SOS 弹窗/回充/缺陷中心 | 🟡 Web-Next 已有地图/摇杆/巡逻/SOS；新增 `#/inspection` 巡检中心、抓拍、历史、缺陷 | `[车]` 实际浏览器、真实视频/地图、SOS 弹窗、回充按钮联动 |
| WP4-7 | `/student` 移动端响应式 H5：实时抓拍、缺陷报告、历史回看 | ✅ `student.html` + `student.js` + CSS；HTTP 200 冒烟通过 | `[车]` 手机/平板浏览器实测；2 秒内联动 |
| WP4-8 | 验收：RKNN ≥15 FPS，CPU <30% | 🔴 未测（无模型/无 NPU） | `[模型][板]` `rknn_benchmark` / 实测帧率，`top`/`ps` 记录 CPU |
| WP4-9 | 验收：抓拍后 2 s 内管理端与 `/student` 可见 | 🟡 代码 WS 即时推送，fake 冒烟通过 | `[车]` 真实相机+真实推理+PAD/手机同网实测 |
| WP4-10 | 验收：Web-Next CI lint/build 全绿 | ✅ `cargo fmt --check`、`cargo clippy`、`cargo test -- --test-threads 1`、`node --check`、资源注册检查均通过 | `[CI]` 在真实 GitHub Actions 运行（本机无法替代） |

### 5.2 WP4 上机/接板结论

- **纯代码/离线部分：完成。**
- **必须连接板子才能确定**：RK3588S NPU 是否可用、`.rknn` 模型加载、摄像头实际图像、`/inspection/capture` ROS 服务、归档目录、网络端口 8089。
- **必须上机**：≥15 FPS、CPU <30%、抓拍后 2 s 管理端/`/student` 可见、真实缺陷类别/置信度观感。
- **代码缺口**：真实 `.rknn` 模型与标签文件未提供；当前只有 mock 测试权重。Gateway 不重复实现底盘 REST 控制，控制仍由 Web-Next `/ws` 承载（符合单一控制发布者红线，但若验收方要求 Gateway 必须提供控制 REST，需要额外代理层并保证不产生第二个 ROS 发布者）。

---

## 6. WP5：WebRTC、离线语音与整机部署

### 6.1 任务逐项对照

| ID | 任务书要求 | 本地代码/离线状态 | 需上机/接板确认 |
| :--- | :--- | :--- | :--- |
| WP5-1 | MediaMTX 部署，视频从统一单相机管道取流，RK3588 MPP H.264，Web WHEP | 🟡 WP5 工作树 `deploy/mediamtx/render.py`、systemd 单元存在；`IIR_CAMERA_UPSTREAM` 为空 | `[板][模型]` WP3 必须先提供 RTSP/H.264 源；确认 MPP 编码、MediaMTX 1.11.3、WHEP 低延迟 |
| WP5-2 | 车端音频守护进程：麦克风回传、平台 WHIP 音频经 AEC 后输出 | 🟡 WP5 `iir_interaction`、`deploy/run-audio.sh`、`pulse.pa`、`aec.sh` 存在；本地 66 项测试通过 | `[板][人工]` PulseAudio/AEC 实际设备、回声消除效果、无啸叫 |
| WP5-3 | Web-Next 双向对讲 + 远程喊话（一键抢占） | 🟡 `interaction.rs`、`interaction.js`、WS 信令存在；JS 10 项测试通过 | `[车]` 浏览器实测双向对讲、喊话抢占巡逻播报 |
| WP5-4 | 离线 TTS：出发/转弯/避障/到点/低电回充/SOS 播报 | 🟡 `iir_interaction.voice` 与 `announcement_for` 存在；本地测试通过 | `[板][人工]` Piper 模型、实际喇叭、音量/语速/听感 |
| WP5-5 | 离线 ASR 关键词唤醒 + 四条指令（暂停/继续/报告电量/呼叫管理员） | 🟡 `asr.py`、`keywords.py`、`wake.py` 存在；本地测试通过 | `[板][模型][人工]` Sherpa-ONNX 模型、麦克风阵列、实际唤醒率/识别率；命令不直接发 `cmd_vel` |
| WP5-6 | 音频仲裁：SOS > 喊话/对讲 > 巡逻播报/本地交互 | ✅ `arbitration.py` 与测试通过（25 项等） | `[车]` 实测 SOS 抢占、远程喊话抢占、释放后不自动恢复旧音频 |
| WP5-7 | udev 固定 `/dev/iir_chassis`、`/dev/iir_lidar`、`/dev/iir_camera` | 🟡 `deploy/generate-udev.py` 存在，需要实际设备序列号/DEVPATH | `[板]` `udevadm info` 读取真实属性；生成规则并安装；重启验证 |
| WP5-8 | systemd 依赖顺序自启 | 🟡 `deploy/systemd/*.service`、`iir.target` 存在；文档记录 9 个单元已在 Orange Pi active | `[板]` 目标机 `systemd-analyze verify`、断电重启、60 s 全链路；正式 8088 与原服务切换 |
| WP5-9 | 验收：双向对讲端到端延迟 <400 ms，无明显啸叫；喊话立即抢占 | 🔴 未验收 | `[车][人工]` 实际 Wi-Fi/浏览器测量，记录方法/样本/最大值；听感确认 |
| WP5-10 | 验收：整机上电无需 SSH，60 s 内全链路自动上线 | 🔴 未验收 | `[板][车]` 冷启动计时；相机/音频/ROS/网关/Web 全部可用才算通过 |
| WP5-11 | WP2/WP3 接口：SOS 状态、巡逻事件、电量、暂停/继续巡逻、统一相机流 | 🔴 `WP5_INTERFACES.md` 明确当前无 `/chassis/sos_active`、`/interaction/patrol_event`、`/battery_voltage` 生产者/消费者；`IIR_CAMERA_UPSTREAM` 空 | `[板][ROS]` 需 WP2/WP3 产生实际话题/服务；WP5 适配层接通 |
| WP5-12 | 设备与音频依赖：PulseAudio、WebRTC AEC、GStreamer、MediaMTX、Caddy、Piper/Sherpa | 🟡 Orange Pi 文档记录已安装部分组件；本地测试使用 fake/模拟 | `[板]` 逐项 `pactl`/`gst-inspect`/`systemctl` 检查；AEC 模块消失问题需排查（文档已记录） |

### 6.2 WP5 上机/接板结论

- **纯代码/离线部分：已完成，且本地测试通过**（iir_interaction 66 通过/2 跳过、deploy 21 通过、JS 10 通过、Rust 53 通过）。
- **必须连接板子才能确定**：实际音频设备名（Timesintelli USB 麦、es8388 喇叭）、AEC 模块、PulseAudio 状态、MediaMTX 版本/端口、udev 序列号/物理路径、systemd 启动顺序、RK3588 MPP 编码能力。
- **必须整车上机**：双向对讲 <400 ms、无啸叫、SOS/喊话抢占、冷启动 60 s、全链路自动上线、实际唤醒率/识别率。
- **代码/集成缺口**：`IIR_CAMERA_UPSTREAM` 为空（无 WP3 RTSP/H.264 源）；WP2/WP3 的 SOS/电量/巡逻事件/命令接口尚未接入；AEC 模块消失原因未定位、未加入自动恢复。

---

## 7. 汇总：无法仅靠本地代码完成的事项

### 7.1 必须连接 STM32 板卡/传感器/执行器才能确定（`[板]`）

1. **电源与时钟**：24 V/5 V/3.3 V 上电时序、HSE 晶振、PLL、复位、BOOT0、SWD 连接。
2. **引脚/电气**：PE9/PE11 超声波、PB8/PB9 软件 I2C、PD3 IMU INT、PD5/PD6 D50A、PD0/PD1 CAN、PB0 电池 ADC、PE4 急停、PC5 按键、PE5 SOS、PD11 蜂鸣器、PB15/PE6/PB14 RGB。
3. **OLED 引脚冲突**：任务书资源表 `PD4/PE0/PE10/PD7` 与原理图 `PD4/PE0/PE1/PD7` 不一致，必须实物核对。
4. **电机/编码器**：四路 PWM 频率与死区、方向 IO 极性、编码器 A/B 相序、13 线 ×4 倍频 CPR、轮径/轮距。
5. **传感器**：HC-SR04 实际型号/供电/波束角、ICM-20948 `WHO_AM_I`/轴向/零偏、D50A 波特率/终端电阻/报警极性、CAN 四路红外映射、电池分压比。
6. **执行器**：SOS 红灯/蜂鸣器实际声光；电机堵转/空载电流。
7. **相机/雷达**：实际设备路径（`/dev/v4l/by-id`、`/dev/serial/by-id`）、分辨率/帧率、安装位置/外参。
8. **音频**：麦克风/喇叭设备名、AEC 模块、PulseAudio source/sink、Piper/Sherpa 模型路径。
9. **系统**：udev 序列号/DEVPATH、systemd 用户总线、Linger、端口 8088/8089/443/8554/8889/8189 占用。

### 7.2 必须整车上机/实际场景验收（`[车]`）

1. **WP1**：烧录后 OLED、时钟、FreeRTOS、四轮转向、`c50c_uart3` 直驱零回归。
2. **WP2**：超声波 20–200 cm 读数稳定；PE5 SOS 50 ms 断电+声光；D50A/CAN 实车联调；远程复位。
3. **WP3**：多点巡逻无漂移、玻璃门/行人/低矮障碍物绕行、1.3 m/s 逐级提速、0.8 m 转弯半径、完整回充闭环（返航→红外对接→充电→离桩复巡）。
4. **WP4**：真实 RKNN 模型 ≥15 FPS、CPU <30%；抓拍后 2 s 内管理端/学生端可见；真实缺陷研判。
5. **WP5**：双向对讲 <400 ms、无啸叫；SOS/喊话抢占；整机冷启动 60 s 全链路自动上线；实际唤醒率/识别率。

### 7.3 必须 ROS 2/模型/标定环境（`[ROS]`/`[模型]`）

1. `colcon test --packages-select c50c_uart3` 全量与 `.github/scripts/compare_ros2_tests.py` 基线比对（本机无 ROS 2）。
2. `colcon build` 验证 `iir_interfaces`、`iir_vision_rknn`、`iir_interaction`。
3. 相机内参/畸变 `camera_info.yaml`、地面单应矩阵、`base_link`→相机/雷达/超声波 TF。
4. RKNN YOLOv8/v11 `.rknn` 模型、标签文件、INT8 量化校准集；无模型时仅 mock 链路。
5. WP5 的 Sherpa-ONNX / Piper 模型、KWS 关键词文件、AEC 设备配置。
6. 目标机 ROS 2 Humble、Python venv、MediaMTX 1.11.3、Caddy、GStreamer 插件、PulseAudio/WebRTC AEC。

---

## 8. 本地“纯代码已完成”与“仍未完成”总表

### 8.1 纯代码/离线已完成

- WP1：编码门禁、CMake 三预设、HAL/FreeRTOS 底座、`App/kinematics|control|protocol|tasks`、host-test 5/5、STM32 交叉构建通过。
- WP2：HC-SR04/ICM-20948/D50A/CAN 回充/SOS 驱动、`App/safety`、`protocol_v3_ext`、`fw_v3_harness` 更新、host-test 通过。
- WP3：nav2 三图层配置、`min_turning_radius` 参数、两段式 `charging.py` 状态机、`wp3_charging.yaml`、c50c WP3 19 项、opi 78 项、nav2 3 项通过。
- WP4：`iir_interfaces`、`iir_vision_rknn`、`Master/Gateway`、Web-Next `#/inspection` 与 `/student`、CI、49 项 Rust + 7 项 Gateway + 14 项视觉测试通过（1 项无 OpenCV 跳过）。
- WP5：`iir_interaction`、`deploy/`、Web-Next `interaction.rs/js`、systemd/udev/MediaMTX 脚本；iir 66 项、deploy 21 项、JS 10 项、Rust 53 项通过。

### 8.2 仍未完成/需现场补齐

| 类别 | 未完成项 | 类型 |
| :--- | :--- | :--- |
| 固件实车 | 烧录、OLED、四轮方向、`c50c_uart3` 联调 | `[板][车]` |
| 传感器 | 超声 20–200 cm、SOS 50 ms、D50A/CAN 实测 | `[板][车]` |
| 相机 | `camera_info.yaml` 内参/畸变、安装 TF、地面单应 | `[模型][板]` |
| 导航 | 1.3 m/s 真正放开、0.8 m 转弯路径、长走廊定位、玻璃/行人避障 | `[车]` |
| 回充 | `wp3_charging.yaml` 全 `.nan`；预备点/电流/满电/退桩参数 | `[板][车]` |
| AI | 实际 `.rknn` 模型、标签、≥15 FPS、CPU <30%、2 s 联动 | `[模型][板][车]` |
| WP5 | `IIR_CAMERA_UPSTREAM` 空、WP2/WP3 接口未接、AEC 自动恢复、400 ms/60 s | `[板][车]` |
| 可选功能 | AprilTag/ArUco 视觉地标未实现 | `[模型][板]` |
| 仓库状态 | WP3/WP4/WP5 仍是未提交工作树；WP5 独立工作树未合并 | 本地整理 |

---

## 9. 建议上机顺序（按依赖排序）

1. **电源与最小系统**：24 V 输入、5 V/3.3 V、HSE、SWD 烧录、串口输出、OLED。
2. **执行器安全**：电机空载方向、编码器计数、PE4 急停、PE5 SOS、PWM 断电延迟。
3. **传感器**：HC-SR04 20–200 cm、ICM-20948 `WHO_AM_I`/零偏、D50A、CAN 回充四路红外、电池 ADC。
4. **底盘闭环**：`c50c_uart3` 串口联调、速度阶跃、0.01/0.1/0.5/1.0/1.3 m/s 逐级、制动距离、低速补偿。
5. **ROS 2/导航**：`colcon build` + `colcon test`、`/scan` `/odom` `/imu` `/ultrasonic/front`、TF、AMCL、costmap、多点巡逻、0.8 m 半径。
6. **回充闭环**：填写 `wp3_charging.yaml`、预备点、红外对接、电流稳定、满电、退桩、复巡。
7. **AI 视觉**：安装 RKNN 模型、`rknn_benchmark`、`/inspection/capture`、2 s 管理端/学生端联动。
8. **WP5 音频/视频**：PulseAudio/AEC、MediaMTX、WebRTC、双向对讲/喊话、SOS 抢占、400 ms。
9. **整机自启**：udev、systemd、冷启动 60 s、断网/断电恢复。
10. **回归**：编码检查、host-test、STM32 构建、ROS 基线、Web-Next CI、WP4/WP5 测试全部重跑。

## 10. 上机记录模板

| 日期 | 板号/设备 | 固件/镜像版本 | 测试项 | 实测值/现象 | 结论 | 证据（日志/视频/截图） |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
|  |  |  |  |  |  |  |

> 本清单是“待上机/接板确认项”的唯一索引；任何“已验收”结论必须附实测记录，不能只引用本文件或本地单元测试。
