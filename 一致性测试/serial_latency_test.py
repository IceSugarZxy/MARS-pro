# -*- coding: utf-8 -*-
"""
串口 B~ 指令响应延迟测试

测试 B~ 发送到首字节数据返回的耗时，以及完整一圈数据的传输时间。
Usage: python serial_latency_test.py [COM_PORT] [ROUNDS]
"""

import sys
import time
import serial
import threading

# ============================================================================
# 配置
# ============================================================================
DEFAULT_PORT = "COM4"
BAUDRATE = 115200
TIMEOUT = 30.0  # 单次测试最大等待时间
ROUNDS = 3      # 默认测试轮数
CHUNK_SIZE = 1024

# ============================================================================
# 工具
# ============================================================================

def format_bytes(data: bytes, max_len: int = 32) -> str:
    """格式化字节预览"""
    if len(data) <= max_len:
        return data.hex(' ')
    return data[:max_len].hex(' ') + f" ... (+{len(data) - max_len}B)"


def is_binary(data: bytes) -> bool:
    """判断是否为二进制测量数据（首字节 > 127）"""
    return len(data) > 0 and data[0] > 127


# ============================================================================
# 测试逻辑
# ============================================================================

def run_single_test(ser: serial.Serial, round_num: int) -> dict:
    """
    单次 B~ 测试，返回延迟统计数据。
    
    流程：
    1. 清空接收缓冲区
    2. 发送 B~
    3. 记录首字节到达时间
    4. 持续接收直到 2 秒无数据
    """
    print(f"\n{'='*60}")
    print(f"  第 {round_num} 轮测试")
    print(f"{'='*60}")

    # ① 清空缓冲区
    ser.reset_input_buffer()
    time.sleep(0.1)

    # ② 发送 B~
    t_send = time.perf_counter()
    ser.write(b"B~\r\n")
    ser.flush()
    print(f"  📤 B~ 已发送 @ {t_send:.3f}s")

    # ③ 等待首字节
    t_first = None
    total_bytes = 0
    total_chunks = 0
    first_data = b""
    last_data_time = time.perf_counter()

    while True:
        waiting = ser.in_waiting
        if waiting > 0:
            data = ser.read(min(waiting, CHUNK_SIZE))
            now = time.perf_counter()

            if t_first is None:
                t_first = now
                first_data = data
                elapsed_ms = (t_first - t_send) * 1000
                print(f"  📥 首字节到达 @ {t_first:.3f}s → 延迟 {elapsed_ms:.1f} ms")
                print(f"     首包: {format_bytes(data)}")

            total_bytes += len(data)
            total_chunks += 1
            last_data_time = now

            # 进度提示（每 256 包）
            if total_chunks % 256 == 0:
                elapsed = now - t_send
                kbps = total_bytes / elapsed / 1024 if elapsed > 0 else 0
                print(f"  ... 已接收 {total_chunks} 包 / {total_bytes} bytes, "
                      f"速率 {kbps:.1f} KB/s")

        else:
            # 无数据等待
            if t_first is not None:
                idle = time.perf_counter() - last_data_time
                if idle > 2.0:  # 2 秒无新数据 → 传输完成
                    break
            else:
                # 首字节还没来
                waited = time.perf_counter() - t_send
                if waited > TIMEOUT:
                    print(f"  ❌ 超时: {TIMEOUT}s 内未收到数据")
                    break
            time.sleep(0.01)

    # ④ 统计
    t_end = time.perf_counter()
    first_delay_ms = (t_first - t_send) * 1000 if t_first else None
    total_duration = t_end - t_send
    avg_kbps = total_bytes / total_duration / 1024 if total_duration > 0 else 0

    result = {
        "round": round_num,
        "send_time": t_send,
        "first_byte_delay_ms": first_delay_ms,
        "total_bytes": total_bytes,
        "total_chunks": total_chunks,
        "total_duration_s": round(total_duration, 3),
        "avg_kbps": round(avg_kbps, 1),
        "first_data_preview": format_bytes(first_data) if first_data else "N/A",
    }
    return result


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else ROUNDS

    print(f"串口延迟测试")
    print(f"  端口: {port}")
    print(f"  波特率: {BAUDRATE}")
    print(f"  测试轮数: {rounds}")
    print(f"  超时: {TIMEOUT}s")
    print()

    # 打开串口
    try:
        ser = serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        )
        print(f"✅ 串口 {port} 已打开")
    except Exception as e:
        print(f"❌ 无法打开串口 {port}: {e}")
        sys.exit(1)

    # 等待固件就绪
    print("⏳ 等待固件就绪 (2s)...")
    time.sleep(2)

    # 运行测试
    results = []
    try:
        for r in range(1, rounds + 1):
            result = run_single_test(ser, r)
            results.append(result)

            if result["first_byte_delay_ms"] is None:
                print(f"  ⚠️ 第 {r} 轮无数据，终止测试")
                break

            # 轮间休息（等卡盘停转）
            print(f"  ⏸️  等待卡盘停止 (3s)...")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
    finally:
        ser.close()
        print(f"\n🔌 串口已关闭")

    # ========================================================================
    # 汇总报告
    # ========================================================================
    print(f"\n{'='*60}")
    print(f"  测试报告")
    print(f"{'='*60}")

    valid = [r for r in results if r["first_byte_delay_ms"] is not None]
    if not valid:
        print("  ❌ 所有轮次均无数据返回")
        return

    delays = [r["first_byte_delay_ms"] for r in valid]
    bytes_list = [r["total_bytes"] for r in valid]
    durations = [r["total_duration_s"] for r in valid]

    print(f"\n  {'轮次':<6} {'首字节延迟':<12} {'总字节':<10} {'总耗时':<10} {'速率':<10}")
    print(f"  {'-'*48}")
    for r in valid:
        d = r["first_byte_delay_ms"]
        print(f"  {r['round']:<6} {d:>8.1f} ms   {r['total_bytes']:>8} B  "
              f"{r['total_duration_s']:>7.2f} s  {r['avg_kbps']:>7.1f} KB/s")

    print(f"\n  📊 统计 (n={len(valid)}):")
    print(f"     首字节延迟:  min={min(delays):.1f} ms  max={max(delays):.1f} ms  "
          f"avg={sum(delays)/len(delays):.1f} ms")
    print(f"     数据总量:    min={min(bytes_list)} B  max={max(bytes_list)} B  "
          f"avg={sum(bytes_list)/len(bytes_list):.0f} B")
    print(f"     总耗时:      min={min(durations):.2f} s  max={max(durations):.2f} s  "
          f"avg={sum(durations)/len(durations):.2f} s")
    print(f"     首包预览:    {valid[0]['first_data_preview']}")


if __name__ == "__main__":
    main()
