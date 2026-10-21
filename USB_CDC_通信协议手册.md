# 3Axis_MARS USB CDC 通信协议手册

## 最新：LIGHT_SW 参数与保护（2026-10-19）

适用构建 `LIGHTSW_CAL_R20`，未由本轮烧录。启用模拟下压保护，与XYZ限位开关无关。旧带数字参数的LSBASE/LSTH接口已取消。

| 指令 | 参数/用途 |
| --- | --- |
| `LSBASE~` | 未下压时发送，捕获当前ADC原始值为静态值，保存Flash |
| `LSTH~` | 压至期望触发位置发送，捕获当前ADC原始值为下压值，保存Flash |
| `LIGHTSW~` | 读取当前状态，不写Flash |
| `M~` | 原状态回信保留LIGHT_SW，并增加LIGHT_CFG |

阈值自动计算为`abs(下压标定值-静态标定值)`，下压判定为`abs(当前值-静态值)>=阈值`。静态值与下压值均为ADC原始计数0..4095。固定基线不自适应、不被ENTER重捕。连续3次处理新样本触发；差值低于阈值70%连续5次恢复，沿用去抖而不是保证精确3ms/5ms。
触发停止XYZR并中止采集；恢复后不自动续传被中止的采集，没有新增清锁命令。

成功设置和查询回信格式：
```text
LIGHTSW: RAW=3805 STATIC=3800 PRESS=3600 THRESH=200 ABS_DIFF=5 TRIGGER=0 SAVED=1 VALID=1
```
`SAVED=1`表示当前参数有有效Flash副本，不保证两点标定完成；`PRESS=65535`表示下压点未标定，使用临时阈值100。`VALID=1`表示ADC后台数据有效。`TRIGGER`为去抖后的状态，可能与瞬时ABS_DIFF不同。上述数值仅为回信示例。
`M~`新增格式：`LIGHT_CFG: STATIC=3800 PRESS=3600 THRESH=200 ABS_DIFF=5 TRIGGER=0 SAVED=1`。

- 三条指令均不得带参数，否则`LIGHTSW RANGE`，不修改参数。
- 当前采样失效：`LIGHTSW ADC INVALID`；未保存静态点先发送LSTH：`LIGHTSW NEED BASE`；两点相同：`LIGHTSW SAME POINT`。均不写Flash、不覆盖原配置。
- 运动中、ADC占用或停止待处理：设置返回`LIGHTSW BUSY`，不写Flash。B采集/XYZ归零期间沿用全局白名单，设置和专用查询静默忽略；归零期间M仍可查询。
- Flash失败：`LIGHTSW SAVE FAIL`，保留原运行值。每条标定将静态值/下压值一起持久化，校验成功后才生效；相同记录不擦写。重新标定静态点保留下压点并重算阈值。
- 首次无有效Flash参数：静态值取上电16点平均，阈值100，SAVED=0。LSBASE保存静态点及未标定标记，随后LSTH保存完整两点。标定时全部电机应停止，不需要解除已有LIGHT_SW触发即可重新标定。查询确认SAVED=1、PRESS为0..4095后再进行实物验证。
- Flash记录格式升级到版本2，旧LIGHTSW_FLASH_R20的“静态值+阈值”记录不作为两点标定加载，升级后重新执行两条标定指令。
- 参数区为`0x0804F000..0x0804FFFF`（Bank2最后两页），链接已预留，不能全片擦除。双页/CRC/提交标志用于失败回退；实机掉电测试尚未完成。

MODE0/1/2保持当前PGA/IDAC，ECSTEP仍仅RAM保存；仅上述LIGHT_SW两项新增持久化。

## 最新：MODE保留激励设置（2026-09-30）

构建`MODE0_KEEP_IDAC_R20`（未烧录）：MODE0/1/2均保留当前PGA、IDAC，只恢复对应运动配置和ADC数据率。上电默认IDAC6，手动设置不写Flash，复位恢复6。例：`IDAC7~` → `MODE0~` → `IDAC~`，应仍返回档位7。需要IDAC6时明确发送`IDAC6~`，不能再依靠MODE0重置。ECSTEP及其他协议不变。

## 2026-09-30：EC11旋钮微动步长

当前源码构建`MODE0_120_ECSTEP_R20`（未烧录），MODE0及ADC参数沿用下方定义。

| 指令 | 说明 | 响应示例 |
|---|---|---|
| `ECSTEP~` | 查询当前旋钮步长 | `ECSTEP: 20` |
| `ECSTEP5~` | 每次有效旋转事件移动5个STEP脉冲 | `ECSTEP: 5` |
| `ECSTEP20~` | 恢复默认步长 | `ECSTEP: 20` |

设置范围1～500000，单位是STEP脉冲而非毫米或驱动器细分档位；500000为底层单次运动上限，不是微调推荐值。XYZ共用，顺/逆时针方向、ENTER切轴、方向键短按100步均不变。运动过程中仍丢弃旋钮事件，不排队。

- 设置错误：`ECSTEP RANGE`；四轴任一运动时设置：`ECSTEP BUSY`，旧值不变。
- B采集或XYZ归零期间，设置和查询均按现有白名单静默忽略；空闲时重发。正常手动运动期间可查询但不可修改。
- 成功设置清掉未消费的旧旋钮事件；只修改RAM，不会自动启动运动。复位恢复20，停止、ENTER切轴、MODE切换不会覆盖设置。
- `M~`新增`ECSTEP: n`。旋钮实际移动仍受VBUS、限位、TMC及采集互斥检查约束。较大步长可能产生较长行程，建议先用小值验证。

## 当前构建（2026-09-29，未烧录）

### 当前MODE0指令与回读

| 指令 | 用途/预期 |
|---|---|
| `F1~` | 开启风扇输出；不代表有转速反馈 |
| `MODE0~` | 恢复起速50、目标120 STEP Hz、2400SPS、AB四边沿、不分频；保留PGA和IDAC |
| `PGA6~` | 可选，明确选择×64；其他增益用PGA0～7，不由MODE写死 |
| `ACQCFG~` | `ACQCFG: 50,120,1,4 samples=131072` |
| `ADCRATE~` / `M~` | 核对2400SPS、构建标识、增益、电流及空闲/故障状态 |
| `B~` | 执行快速寻零、采集一圈、结束回零 |
| `S~` | 停止，无文本响应 |

逐条发送并等待对应响应；B期间仅停止类命令可执行，M查询被静默忽略。正常B数据为131072个大端有符号16位数（262144字节），无正常DONE尾帧。收满字节仍应等待回零结束并用M确认ACQ_STATE=0和计数；B可能在发完数据后回零失败。失败文本可能跟在部分数据后，必须剥离并判失败，不可按ADC值解析。

### 错误与质量判定

| 字段/错误 | 当前含义与处理 |
|---|---|
| `ACQ_STALE > 0` | 没有新转换的角度位置使用上一笔值补点；不触发终止，仍需报告补点比例 |
| `R ACQ ERROR ENCODER FAIL` | 方向/正交错误、点数不匹配，或寻零/回零运动启动被拒绝；不是单指编码器损坏 |
| `ACQ_DIR_ERR > 0` | 观测到反向AB跳变；可能真实回摆或信号干扰，仍终止 |
| `ACQ_QUAD_ERR > 0` | 非法正交跳变，仍终止 |
| `ACQ_COUNT_ERR > 0` | 圈末边沿或存储记录数不匹配 |
| `R ACQ ERROR ADC FAIL` | ADC通信、断流或收尾配置恢复失败；检查ADC_STATE/SPI/Echo |
| `R ACQ ERROR USB OVERFLOW` | ring丢点，及时终止；不使用STALE补点掩盖USB丢数据 |

故障后先发送M保存现场，不先复位或重发B。ACQ_TIMING在首次STALE冻结，不能作为后来方向错误的现场。`completed`、`valid`、`zero_fill`是HostApp结果文件字段，不是板端串口字段；含补点的完整圈为completed=true、zero_fill=false、valid=false，仍导出数据和补点警告。valid=true还须通过其他质量检查。

`MODE0_120_FILL_R20`：`MODE0~`及上电默认恢复`ACQCFG50,120,1,4~`、2400SPS，PGA和IDAC均保留用户设置，快寻1000Hz不变。STALE仍重复上一笔补点、计数但不报错；ADC收尾恢复失败报`R ACQ ERROR ADC FAIL`，ring溢出及时停止并报`R ACQ ERROR USB OVERFLOW`。HostApp实验结果`completed=true`可以含补点，`valid=true`仍要求零补点及全部其他质量检查通过；补点圈保留CSV和补点比例。下方旧构建描述是历史记录。

## 最新变更：STALE补点（2026-09-29）

源码版本`FASTSEEK_STALE_FILL_R20`：B采集出现STALE时不再发送`R ACQ ERROR ADC STALE`，而是在对应角度重复上一笔数据。首点沿用寻零期间最近一次转换，之后遇到新转换即更新。`M~`中的`ACQ_STALE`保留，含义为补点次数；补点比例为`ACQ_STALE / ACQ_STORED`（记录数为0时不计算）。整圈不再因STALE非零判失败，其余错误和ADC断流超时仍有效。裸流仍是大端16位，无逐点有效性标记；收到131072点不等于获得131072次独立测量。上位机应保留补点质量警告，不能把补点数据当作零缺样实验。本次未烧录，请以`M~`的构建标识区分固件。下方板端描述是历史记录。

历史版本FASTSEEK_DIAG2400_R20保留快寻，M增加`FAST_SEEK: 1`和`STALE_HW: PR1=0x... DRDY=... ADC_AGE_CYC=...`。STALE_HW仅在首次STALE锁存，下一次B清零；STALE=0时值0是占位，不表示DRDY实际为低。PR1的bit12对应DRDY，ADC_AGE_CYC除144得到微秒。仅停止后输出诊断，不改变B大端16位裸数据格式；无串口快寻切换命令。

2026-09-29：按当前源码同步默认值、配置失败响应、H流速率和单位换算。设备固件不一定与工作树相同，对接时以 `M~`、`ACQCFG~`、`ADCRATE~` 回读核对；本次文档更新不代表已经烧录。

历史调试记录（不代表当前默认）：COM26已烧录MODE0_RUNUP200_R20。B~包含1000Hz快速寻零、反向216步退让、恢复采集速度后至少200步再由Z启动整圈。早前撤销快速寻零的记录不再代表当前实现。MODE0为50Hz/2400SPS/IDAC6/AB4x/div1，保持131072点；PGA运行时可调。

2026-09-21 新增：[手动采样调参接口 ACQCFG / ADCRATE](../docs/sampling_parameter_commands.md)。自定义分频后整圈数据量动态变化，不能只按 MODE 编号假定长度；以 ACQCFG/M 查询结果为准。

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
| `B~` | 无 | 电流检查→Hall连续→按用户采集速度正转过Z→整圈采集→回零 | 无文本 (成功后进入二进制流模式); 失败返回 `ADC FAIL` / `ADC BUSY` / `R SPEED TOO HIGH` |
| `S~` | 无 | 停止采集 | 无文本 (始终静默) |
| `MODE<0\|1\|2>~` | 模式编号 | 切换采集模式 | `MODE 0 OK (50 Hz, div 1, 131072 edges, 131072 samples/rev)` |
| `MODE~` | 无 | 查询当前模式及安全上限 | `MODE: 0 (max 1200 Hz, div 1, 131072 edges, 131072 samples/rev)` |
| `MODEX~` / 非法 | — | 参数错误 | `MODE ERR` |
| `D~` | 无 | 查询分频 (只读) | `SAMPLE_DIV: 1` |
| `D<num>~` | 任意数字 | 尝试修改分频 | `D READ ONLY, USE ACQCFG OR MODE` |
| `ACQCFG<start>,<target>,<div>,<edges>~` | STEP Hz、分频、边沿1/2/4 | 停止时设置R采集参数；无参数查询 | `ACQCFG: 16,100,8,1 samples=4096` |
| `ADCRATE<SPS>~` | 支持的数据率字符串 | 停止时设置ADS1261数据率；无参数查询 | `ADCRATE: A/H=1200 B=1200 SPS` |

### 2.3 连续流与运行时配置

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `H~` | 无 | 切换连续 Hall+Curr 文本流 (再发停止，速率非固定) | `H ON` / `H OFF`; 数据格式见 5.2 节 |
| `PGA<0~7>~` | 0=×1 ~ 7=×128 | 运行时修改 PGA 增益 | `PGA 5 OK` / `PGA BUSY` / `PGA RANGE (0~7)` / `PGA FAIL` |
| `PGA~` | 无 | 查询当前 PGA | `PGA 5 (x32)` |
| `IDAC<0~9>~` | 0=50µA ~ 9=3000µA (标称) | 运行时修改 IDAC 电流档 | `IDAC 9 OK` / `IDAC BUSY` / `IDAC RANGE (0~9)` / `IDAC FAIL` |
| `IDAC~` | 无 | 查询当前 IDAC 档位 | `IDAC 9 (3000 uA nominal)` |
| `Motor<0~3>~` | 0=X 1=Y 2=Z 3=R | 电机持续运转切换 (再发停止) | `MOTOR0 ON` / `MOTOR0 OFF` |

**注意**: PGA/IDAC 修改在 ADC被占用、B~采集或H~流激活时被拒绝 (`BUSY`)。设置不持久化，复位并成功应用MODE0后为PGA=×64、IDAC=6。写入读回验证成功才返回OK；失败尝试恢复旧配置，恢复失败进入ADC FAULT，不得继续采集。
B~ 的 IDAC 检查与用户档位解耦 (内部固定 ×8 + 0x09 档执行, 检查完恢复用户档位)。
PGA×128是否饱和取决于实际差分输入及共模范围，不能一概判断；调整PGA/IDAC后应检查整圈幅度并保留裕量。B~电流预检使用专用IDAC9，不证明用户所选激励档的实际电流或磁场灵敏度正确。

### 2.4 归零

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `I~` | 无 | XYZ三轴同时各自向限位归零 | `HOME START` (仅成功启动时) |

### 2.5 状态查询

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `M~` | 无 | 系统全状态 | 多行文本 (见第4节) |
| `A~` | 无 | 单次双通道ADC (Hall+Curr) | 4字节二进制: `[Hall_MSB][Hall_LSB][Curr_MSB][Curr_LSB]` |
| `TEST~` | 无 | 双通道电压采集 (含mV换算) | `Hall: xxx raw  x.xxx mV` / `Curr: xxx raw  x.xxx mV` |

### 2.6 其他

| 命令 | 参数 | 功能 | 响应 |
|------|------|------|------|
| `F<0\|1>~` | 0=关, 1=开 | 风扇PF1输出，严格单字符 | `FAN ON` / `FAN OFF` / `FAN RANGE` |
| `TMCLEAR<0..3>~` | 0=X, 1=Y, 2=Z, 3=R | 空闲时条件清驱动故障，不启动运动 | `TMCLEAR <轴号> RC=<结果>` / `TMCLEAR BUSY` / `TMCLEAR RANGE` |

2026-09-29补充：TMCLEAR结果0=核验通过并清锁存，1=仍处理中，2=忙/保护不允许，3=通信失败，4=故障仍在，5=配置异常。运动前可显式执行，但禁止自动循环清故障重试运动；不会清故障累计数或恢复丢步后位置可信度。先发送S~并等M显示空闲，确认散热后执行，例如TMCLEAR3~。M中的DRV/GSTAT平时仍为缓存，TMCLEAR会刷新实时值。

F1~从此版本才实际控制PF1，M的FAN读取输出寄存器，不是风扇转速反馈。M新增FW_BUILD及Z_TRACE_COUNT/Z_TRACE（最多32条最近Z中断），仅空闲时输出，不改变B~裸二进制流。详见[零位诊断](../docs/zero_debug_2026-09-29.md)。

LOWSPEED_R1_R20版M增加`R_CURRENT_CFG: 0x0002140A`，表示R初始化配置IHOLD=10、IRUN=20、IHOLDDELAY=2；这是编译配置值，不是只写寄存器的实时读回。初始化通过IFCNT确认接收。XYZ仍IRUN30，MODE/PGA命令不修改此电流配置。三分钟131072点实测参数见[报告](../Experiments/ultra_3min_report.md)。

当前MODE0_RUNUP200_R20将B~前置寻零独立为200→1000 STEP Hz，反向越零后退让216步，再恢复用户采集速度；正向不足200步的Z不启动采集。ACQCFG/RSPEED仍设置正式采集速度，不设置寻零1000Hz。M新增`SEEK_CFG: 200,1000 PHASE=<n>`，Z_TRACE末尾增加phase；主ACQ_STATE编号和B二进制格式不变。阶段说明与实测状态见[快速寻零说明](../docs/fast_seek_1000_2026-09-29.md)。

M另输出最近16条`ACQ_TIMING: edge=... dt=... age=... adc_dt=... seq=... step=...`：分别是选中角度边沿序号、距上个选中边沿周期数、距最近ADC回调周期数、最近两次ADC回调间隔、转换序号和R步数。时间单位为DWT周期，当前144MHz下除以144得到微秒。仅AB四边沿路径记录，首个STALE冻结，下一次B清零；首条dt为0。日志仅停止后输出，不插入B二进制流。相同seq才表示旧转换，数值相同不等于STALE。上位机应允许M中重复的诊断行，不把它们当采样数据。

当前STALE只补点并计数，不再发送`R ACQ ERROR ADC STALE`；旧版该错误记录保留用于历史分析。终点停STEP后保持EN约200ms再反转，反向Z上升沿停止后再保持100ms释放；不增加上电保持力。新120Hz组合仍需实机验证。

---

## 3. 采集模式 (MODE)

| 模式 | 记录点数/圈 | 目标STEP频率 | 边沿检测 | 分频 | 数据量/圈 |
|------|--------|----------|----------|------|-----------|
| MODE0 | 131072 | 120 Hz | A+B 4x正交 | 1 | 262144 B |
| MODE1 | 65536 | 579 Hz | A+B 4x正交 | 2 | 131072 B |
| MODE2 | 32768 | 879 Hz | A+B 4x正交 | 4 | 65536 B |

2026-09-29更新：MODE0采用50/120Hz、2400SPS方案，圈时未实测；MODE1/2仍起速200Hz。三档ADC A/H/B数据率依次2400/7200/4800SPS，均Sinc4。三档AB四边沿配置上限仍1200Hz（不等于已验证的安全转速），回零反转100→200Hz；前置寻零200→1000Hz独立于采集速度。构建MODE0_120_FILL_R20仅编译验证，未烧录。

MODE均保留当前PGA，所有MODE保留当前IDAC。上电默认MODE0、PGA×64、IDAC6；可用`PGA0~`～`PGA7~`修改增益，之后切换MODE仍保留。IDAC也可手动调整，但再次发送MODE0不会改变当前值。ADC整组写入读回成功后才提交模式，失败返回`MODE ERR ADC <rc>`，不会返回OK；恢复失败则ADC进入FAULT。忙时继续静默拒绝。手动ACQCFG后MODE标识仅表示最近一次预设，实际配置以ACQCFG/ADCRATE/M回读为准。

### 3.1 手动采样参数

- `ACQCFG<start>,<target>,<div>,<edges>~`：LOWSPEED_R1起1 <= start <= target（旧版本最小16）；edges=1/2/4分别为A下降、A双边沿、AB四边沿，目标STEP频率上限分别3500/2000/1200Hz。div必须非零且整除32768×edges，预期点数=(32768×edges)/div。失败返回`ACQCFG RANGE/FORMAT`或`ACQCFG BUSY`。低速TIM4仅在启动时选预分频，不改变编码器点数；主机必须核对R_SPEED回读，不能在旧固件上静默按新下限运行。
- `ADCRATE<SPS>~`支持精确字符串：`2.5, 5, 10, 16.6, 20, 50, 60, 100, 400, 1200, 2400, 4800, 7200, 14400, 19200, 25600, 40000`。没有600SPS档；失败返回`ADCRATE RANGE`、`ADCRATE BUSY`、`ADCRATE FAIL`，非ADS1261构建为`ADCRATE UNSUPPORTED`。
- 数据率同时设置A/H/B；<=7200SPS使用Sinc4，更高档固定Sinc5。电流预检仍为独立配置。当前允许STALE重复旧转换补点，但必须披露补点比例；记录数不代表同数量的新转换。
- B采集为ADC连续转换、编码器边沿锁存最新转换，不是每个边沿触发一次转换。平均记录率低于SPS只是必要条件，瞬时边沿间隔、机械速度纹波仍可能导致STALE。
- 超长采集须延长主机总时限，包含最多近一圈寻零、一圈正式采集和回零。STALE按用户要求补点；方向、计数、ADC断流和超时保护继续保留。
- 2026-09-29实机旧版本仍出现`ACQCFG: 16,16,1,1 samples=131072`，边沿回显与点数矛盾，这是旧版按MODE号推导边沿的已知回显错误。当前源码已修复；旧设备应同时核对`ACQ_EXPECT_EDGE/RECORD`和`SAMPLE_DIV`，不能仅按末字段判断边沿配置。没有新的版本标识时不能仅凭v1.0判断是否含修复。

---

## 4. M~ 状态输出字段说明

| 字段 | 含义 |
|------|------|
| `ADC: ADS1261/ADS8691` | 当前ADC类型 |
| `ADC_OK: 0/1` | ADC连接状态 |
| `ADC_STATE` | ADC状态，3为恢复失败FAULT；不能仅凭ADC_OK判断可采集 |
| `ADCRATE: A/H=... B=... SPS` | 当前A/H和B使用的数据率 |
| `R_SPEED: start=... target=... STEP_HZ` | R轴当前起速和目标频率，不是转/秒 |
| `ACQ_EXPECT_EDGE / ACQ_EXPECT_RECORD` | 本次配置预期边沿数/记录数；接收长度以RECORD×2计算 |
| `SAMPLE_DIV` | 当前分频数 |
| `ACQ_MODE: 0/1/2` | 当前采集模式 |
| `ACQ_QUAD_CHK: ON/OFF` | 正交校验是否启用 |
| `ACQ_STATE: 0~15` | 采集状态机当前状态 (0=IDLE) |
| `ACQ_EDGE` | 编码器边沿计数 |
| `ACQ_RECORD` | 已记录样本数 |
| `ACQ_STORED` | 已入Ring样本数 |
| `ACQ_STALE` | 记录边沿到来时没有新的ADC转换序号；数值相同不等于STALE |
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
| `HOME_OK_MASK / HOME_FAULT_MASK` | XYZ归零成功/故障位掩码，bit0/1/2对应X/Y/Z；当前源码将启动拒绝、非限位停止也计为失败 |
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

上位机应按采集前`ACQ_EXPECT_RECORD × 2`接收并保存原始字节，采集结束后通过`M~`核对空闲、实际入队数、计数/STALE/方向/正交/ring/SPI错误及Echo增量。异常中止可能输出`R ACQ ERROR ...`，该圈无效，不能把错误文本解释为样本。裸流没有CRC，长度及状态检查不替代端到端完整性校验。

### 5.2 H~ 连续流输出格式

- **格式**: 每行 `:hall16,curr16,hall24,curr24\r\n` (ASCII 十进制, 冒号开头)
- **字段**: hall16=Hall 24bit>>8 (int16); curr16=Current 24bit>>8; hall24=Hall 完整 24bit (int32); curr24=Current 完整 24bit
- **速率**: Hall/Current交替单次转换，每16对抽取1对，不是平均；有效文本速率受转换延迟、滤波和通信影响，不能用SPS/32直接视为实测速率。
- **电压换算**: V_µV = raw24 × Vref_µV / (2^23 × PGA增益)；B流raw16对应分母为2^15。历史报告采用Vref=2.442V，须实际校准。
- **磁场换算**: B_mT = (V_µV - 零场偏置_µV) / 标定灵敏度_µV每mT。历史1094.4µV/mT仅为特定激励下的估算，不是HG186A通用常数；更改IDAC必须重新确认灵敏度。未标定只能报告等效读数，不能声称绝对磁场精度。
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

当前XYZ归零没有独立最大行程/时限兜底，光电失效可能持续运动；不得无人值守归零。上位机应检查成功/故障掩码和限位，不能只以HOME_STATE=0判成功。
