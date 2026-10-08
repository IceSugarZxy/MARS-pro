# -*- coding: utf-8 -*-
"""Shared offset calibration timing configuration.

2026-09-29：偏置校准改用固件 H~ 连续 Hall 流（ASCII 行 :hall16,curr16,hall24,curr24），
不再用 B~ 整圈采集。H~ 一按即出数据（无需 R 轴先回参考位），所以一轮固定 5 s 即可。
"""

# H~ 连续流开关指令（第一次发送开始流，第二次发送停止流）
OFFSET_STREAM_COMMAND = "H~"
# H~ 标称输出速率，仅用于进度估算与平滑窗口换算
OFFSET_HALL_STREAM_HZ = 600.0
# 平滑窗口时长（秒）：偏置为直流分量，取短窗移动平均即可
OFFSET_HALL_SMOOTH_SECONDS = 0.1

# 一轮偏置采集时长（H~ 流持续时间）
OFFSET_COLLECTION_SECONDS = 5.0
# 取中段稳定窗口用于求均值：保留中间 3 s
OFFSET_STABLE_WINDOW_SECONDS = 3.0
OFFSET_COLLECTION_COMMAND_SECONDS = int(OFFSET_COLLECTION_SECONDS)
OFFSET_PROCESS_GRACE_SECONDS = 0.0
OFFSET_MAX_PROCESS_SECONDS = OFFSET_COLLECTION_SECONDS + OFFSET_PROCESS_GRACE_SECONDS
OFFSET_PROGRESS_SECONDS = OFFSET_MAX_PROCESS_SECONDS
OFFSET_STOP_GUARD_DELAY_MS = int(OFFSET_MAX_PROCESS_SECONDS * 1000)
