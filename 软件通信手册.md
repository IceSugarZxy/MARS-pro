# 3Axis_MARS USB CDC 通信协议手册

> 固件版本: v1.x | MCU: STM32G474RBTx | 接口: USB CDC 虚拟串口

## 1. 协议概述

- **物理层**: USB CDC ACM (虚拟串口)
- **帧格式**: 文本命令以 `~` 结尾，支持多字符命令（最长前缀匹配）
- **编码**: ASCII 文本命令 + 二进制数据流
- **响应**: 文本响应行以 `\r\n` 结尾

---

## 2. 命令参考

### 2.1 运动控制

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `X<steps>~` | 带符号步数, 如 `X+1000~` `X-500~` | X轴运动 | `X START 1000` / `X BUSY` / `X RANGE` / `X LIMIT` / `X VBUS LOW` / `X LIGHT TRIGGERED` / `X ADC NOT READY` |
| `Y<steps>~` | 同上 | Y轴运动 | 同上 |
| `Z<steps>~` | 同上 | Z轴运动 | 同上 |
| `R<steps>~` | 同上 | R轴运动 | 同上 |
| `RSPEED<start>,<target>~` | start=起始Hz, target=目标Hz | R轴速度设置 | `R SPEED OK` |
| `RSPEED~` | 无 | 查询R轴速度 | `R SPEED: start=200 target=1000` |
| `O~` | 无 | 全部急停 | `ALL STOP` |
| `XSTOP~` | 无 | O~别名 | `ALL STOP` |
| `XE<0\|1>~` / `EN<0\|1>~` | 0=禁用, 1=使能 | X轴使能/禁用 | `X ENABLED` / `X DISABLED` |

### 2.2 采集控制

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `B~` | 无 | 开始一圈采集 (IDAC检查→Hall连续→4x采集→回零) | 无文本 (成功后进入二进制流模式); 失败返回 `ADC FAIL` / `ADC BUSY` / `R SPEED TOO HIGH` |
| `S~` | 无 | 停止采集 | 无文本 (始终静默) |
| `MODE<0\|1\|2>~` | 模式编号 | 切换采集模式 | `MODE 0 OK (1200 Hz, div 1, 131072 edges, 131072 samples/rev)` |
| `MODE~` | 无 | 查询当前模式 | 同上格式 |
| `MODEX~` / 非法 | — | 参数错误 | `MODE ERR` |
| `D~` | 无 | 查询分频 (只读) | `SAMPLE_DIV: 1` |
| `D<num>~` | 任意数字 | 尝试修改分频 | `D READ ONLY, USE MODE0~MODE2~` |

### 2.3 连续流与运行时配置

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `H~` | 无 | 切换连续 Hall+Curr 流 (~600Hz, 再发停止) | `H ON` / `H OFF`; 数据格式见 5.2 节 |
| `PGA<0~7>~` | 0=×1 ~ 7=×128 | 运行时修改 PGA 增益 | `PGA 5 OK` / `PGA BUSY` / `PGA RANGE (0~7)` |
| `PGA~` | 无 | 查询当前 PGA | `PGA 5 (x32)` |
| `IDAC<0~9>~` | 0=50µA ~ 9=3000µA (标称) | 运行时修改 IDAC 电流档 | `IDAC 9 OK` / `IDAC BUSY` / `IDAC RANGE (0~9)` |
| `IDAC~` | 无 | 查询当前 IDAC 档位 | `IDAC 9 (3000 uA nominal)` |
| `Motor<0~3>~` | 0=X 1=Y 2=Z 3=R | 电机持续运转切换 (再发停止) | `MOTOR0 ON` / `MOTOR0 OFF` |

**注意**: PGA/IDAC 修改在 B~ 采集或 H~ 流激活时被拒绝 (`BUSY`)。修改后复位回默认 (PGA=×32, IDAC=0x09)。
B~ 的 IDAC 检查与用户档位解耦 (内部固定 ×8 + 0x09 档执行, 检查完恢复用户档位)。
IDAC 档 0/1 (50/100µA) 不推荐用于 B~ (低于开路保护阈值)。PGA=×128 下 Hall 采集会饱和, 建议 ≤×64。

### 2.4 归零

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `I~` | 无 | 三轴归零 (X→Y→Z各自向限位运动) | `HOME START` (仅成功启动时) |

### 2.4 状态查询

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `M~` | 无 | 系统全状态 | 多行文本 (见第4节) |
| `A~` | 无 | 单次双通道ADC (Hall+Curr) | 4字节二进制: `[Hall_MSB][Hall_LSB][Curr_MSB][Curr_LSB]` |
| `TEST~` | 无 | 双通道电压采集 (含mV换算) | `Hall: xxx raw  x.xxx mV` / `Curr: xxx raw  x.xxx mV` |

### 2.5 其他

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `F<0\|1>~` | 0=关, 1=开 | 风扇开关 | `FAN ON` / `FAN OFF` |

---

## 3. 采集模式 (MODE)

| 模式 | 分辨率 | 速度上限 | 边沿检测 | 分频 | 数据量/圈 |
|------|--------|----------|----------|------|-----------|
| MODE0 | 131072 | 1200 Hz | A+B 4x正交 | 1 | 262144 B |
| MODE1 | 65536 | 2000 Hz | A+B 4x正交 | 2 | 131072 B |
| MODE2 | 32768 | 3500 Hz | A下降沿 | 1 | 65536 B |

---

## 4. M~ 状态输出字段说明

| 字段 | 含义 |
|------|------|
| `ADC: ADS1261/ADS8691` | 当前ADC类型 |
| `ADC_OK: 0/1` | ADC连接状态 |
| `SAMPLE_DIV` | 当前分频数 |
| `ACQ_MODE: 0/1/2` | 当前采集模式 |
| `ACQ_QUAD_CHK: ON/OFF` | 正交校验是否启用 |
| `ACQ_STATE: 0~15` | 采集状态机当前状态 (0=IDLE) |
| `ACQ_EDGE` | 编码器边沿计数 |
| `ACQ_RECORD` | 已记录样本数 |
| `ACQ_STORED` | 已入Ring样本数 |
| `ACQ_STALE` | Hall数据重复次数 |
| `ACQ_QUAD_ERR` | 正交解码错误 |
| `ACQ_DIR_ERR` | 方向错误 |
| `ACQ_RING_DROP` | Ring溢出丢数 |
| `ADC_SPI_ERR` | SPI通信错误 (超时) |
| `ADC_ECHO_ERR` | SPI 位级传输错误 (RDATA Echo 字节不匹配计数) |
| `PGA: n (xN)` | 当前 PGA 档位 (0=×1 ~ 7=×128) |
| `IDAC: n` | 当前 IDAC 档位 (0=50µA ~ 9=3000µA 标称) |
| `ACQ_COUNT_ERR` | 边沿/样本数不匹配 |
| `USB_TX_BYTE` | USB已发送字节 |
| `USB_TX_BUSY` | USB忙次数 |
| `USB_TX_COMP` | USB发送完成次数 |
| `X/Y/Z/R: IDLE/ACCEL/RUN/DECEL pos=N cnt/target dir=+/- stop=0/1` | 四轴运动状态 |
| `VBUS: xxx mV (raw xxx) [OK/LOW/NOT_READY]` | 24V电源电压 |
| `LIGHT_SW: xxx (init xxx, diff xxx)` | 光电位移传感器当前值/初始值/差值 |
| `FAULT: VBUS LOST` | VBUS掉电故障 (出现过) |
| `FAULT: LIGHT SW TRIGGERED` | 光电探头碰撞故障 (出现过) |
| `HOME_STATE: 0~3` | 归零状态 (0=IDLE, 1=JOG, 2=WAIT, 3=DONE) |
| `HOME_SKIP` | 归零跳过轴数 |
| `ALL_STOP` | 急停总次数 (诊断) |
| `X_LIM/Y_LIM/Z_LIM: 0/1` | XYZ限位开关当前电平 (1=触发) |
| `KEY_REJECT` | 按键运动被拒绝次数 |
| `EC11_CW/EC11_CCW` | EC11顺/逆时针事件计数 (调试) |
| `EC11_ISR` | EC11 中断进入总次数 (调试) |
| `EC11_BOUNCE` | EC11 消抖屏蔽次数 (调试) |
| `EC11_A/EC11_B: 0/1` | EC11当前A/B相电平 |
| `RST: IWDG/BOR/PIN/SFT/OBL` | 本次启动的复位原因 (1=该复位源) |
| `HF_CRASH: PC=... LR=... CFSR=... HFSR=...` | 上次 HardFault 现场 (无则 NONE) |
| `TMCX/Y/Z/R: RAW=... LATCH=... GSTAT=... DRV=...` | TMC2209 DIAG 引脚状态/故障锁存/状态寄存器 |

---

## 5. 二进制数据流 (B~ 采集输出)

采集启动成功后 (IDAC检查通过)，固件进入二进制流模式：

- **格式**: 裸 2 字节 `[Hall_MSB][Hall_LSB]`，无帧头、无CRC、无分隔符
- **速率**: 由 MODE 和编码器边沿决定
- **每圈数据量**: MODE0=262144B, MODE1=131072B, MODE2=65536B
- **结束**: 二次 Z 信号→回零→数据流自然终止
- **流中不混入文本**，所有文本命令静默

### 5.2 H~ 连续流输出格式

- **格式**: 每行 `:hall16,curr16,hall24,curr24\r\n` (ASCII 十进制, 冒号开头)
- **字段**: hall16=Hall 24bit>>8 (int16); curr16=Current 24bit>>8; hall24=Hall 完整 24bit (int32); curr24=Current 完整 24bit
- **速率**: ~600Hz (19.2kSPS 对频 ÷16 分频)
- **物理换算**: V_µV = raw24 × 2.442e6 / (2^23 × PGA)；B_mT = V_µV / (0.72 × I_µA) (HG186A)
- **开关**: 第一次 `H~` 开始, 第二次 `H~` 停止; `S~`/`O~` 也会停止

---

## 6. 运动过程中的可能输出

### 6.1 正常输出

| 输出 | 触发条件 |
|------|---------|
| `X START 1000` | X轴成功启动 |
| `X DONE` | X轴运动完成 (仅USB命令, 按键操作不输出) |
| `HOME START` | 归零成功启动 |
| `ALL STOP` | O~/XSTOP~ 急停 |

### 6.2 错误输出

| 输出 | 触发条件 |
|------|---------|
| `X BUSY` | 轴正在运动中 |
| `X RANGE` | 步数超出范围 (>500000 或 INT32_MIN) |
| `X LIMIT` | 向限位方向运动但已触发限位, 或回零方向预检失败 |
| `X VBUS LOW` | 24V电源 <21V, 拒绝运动 |
| `X ADC NOT READY` | ADC后台模块未就绪 |
| `X LIGHT TRIGGERED` | 光电位移传感器已触发 (探头碰撞) |
| `X ERR` | 未知错误 |
| `VBUS LOST` | 运动中24V掉电 → 全轴急停 (仅M~查看FAULT标志) |
| `LIGHT SW TRIGGERED` | 运动中探头碰撞 → 全轴急停 (仅M~查看FAULT标志) |

### 6.3 采集错误输出 (以 `R ACQ ERROR` 开头)

| 输出 | 含义 |
|------|------|
| `R ACQ ERROR IDAC RANGE` | IDAC电流检查不合格 |
| `R ACQ ERROR ADC FAIL` | ADC通信失败 |
| `R ACQ ERROR ENCODER FAIL` | 编码器正交错误/边沿计数异常 |
| `R ACQ ERROR USB OVERFLOW` | Ring溢出丢数 |
| `R ACQ ERROR TIMEOUT` | 采集超时 (HOMING/SAMPLING阶段) |

---

## 7. 按键操作说明 (不产生USB输出)

| 按键 | 短按 | 长按 (>1s) |
|------|------|------------|
| UP | Y轴 +100步 | Y轴持续点动(松键停止) |
| DOWN | Y轴 -100步 | Y轴持续点动(松键停止) |
| LEFT | X轴 -100步 | X轴持续点动(松键停止) |
| RIGHT | X轴 +100步 | X轴持续点动(松键停止) |
| ENTER | 切换精调轴 X→Y→Z→X | 三轴归零 |
| EC11旋钮 | 当前选中轴微调 10步/格 | — |

**注意**: 按键操作全程静默，不输出USB文本。采集(B~)期间按键无效。归零速度由 `HOME_SPEED_HZ` 宏控制 (默认5000Hz)。

---

## 8. 归零流程

1. 发送 `I~` 或长按 ENTER → `HOME START`
2. XYZ三轴同时向限位方向(-1)运动
3. 各轴触发限位 → PWM ISR自动停止 → position清零
4. 三轴全部停止 → 恢复原始速度 → 归零完成
5. 查看 `M~` → `HOME_STATE: 0`(IDLE), `X/Y/Z_LIM: 1`(已归零)

已在限位的轴直接跳过。`HOME_SPEED_HZ` 控制归零速度。
