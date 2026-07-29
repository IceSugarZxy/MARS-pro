# -*- coding: utf-8 -*-
"""
串口 B~ 指令响应延迟测试（支持 MODE 切换）

测试各 MODE 下 B~ 发送到首字节返回的耗时及完整传输。
Usage:
    python serial_latency_test.py COM4 3              # 默认 MODE0，3 轮
    python serial_latency_test.py COM4 3 --mode 1     # MODE1，3 轮
    python serial_latency_test.py COM4 2 --all        # 所有 MODE，各 2 轮
"""

import sys
import time
import serial
from collections import defaultdict

# ============================================================================
# 配置
# ============================================================================
DEFAULT_PORT = "COM4"
BAUDRATE = 115200
TIMEOUT = 15.0  # 首字节等待超时（匹配软件 10s + 余量）
DEFAULT_ROUNDS = 3
CHUNK_SIZE = 1024

MODE_INFO = {
    0: {"name": "MODE0", "cmd": b"MODE0~\r\n", "points": 131072, "bytes": 262144},
    1: {"name": "MODE1", "cmd": b"MODE1~\r\n", "points":  65536, "bytes": 131072},
    2: {"name": "MODE2", "cmd": b"MODE2~\r\n", "points":  32768, "bytes":  65536},
}

# ============================================================================
# 工具
# ============================================================================

def format_bytes(data: bytes, max_len: int = 32) -> str:
    if len(data) <= max_len:
        return data.hex(' ')
    return data[:max_len].hex(' ') + f" ... (+{len(data) - max_len}B)"


def set_mode(ser: serial.Serial, mode: int):
    """发送 MODE 切换指令。"""
    info = MODE_INFO[mode]
    ser.reset_input_buffer()
    ser.write(info["cmd"])
    ser.flush()
    print(f"  🔧 {info['name']} 切换中 ... ", end="", flush=True)
    time.sleep(0.5)
    ser.reset_input_buffer()
    print("完成")


def run_single_test(ser: serial.Serial, mode: int, round_num: int) -> dict:
    """单次 B~ 测试。"""
    info = MODE_INFO[mode]
    print(f"\n  {'─'*50}")
    print(f"  {info['name']} 第 {round_num} 轮")
    print(f"  {'─'*50}")

    ser.reset_input_buffer()
    time.sleep(0.1)

    t_send = time.perf_counter()
    ser.write(b"B~\r\n")
    ser.flush()
    print(f"  📤 B~ 已发送")

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
                print(f"  📥 首字节延迟: {(t_first - t_send) * 1000:.1f} ms")
                print(f"     首包: {format_bytes(data)}")

            total_bytes += len(data)
            total_chunks += 1
            last_data_time = now

            if total_chunks % 256 == 0:
                elapsed = now - t_send
                kbps = total_bytes / elapsed / 1024 if elapsed > 0 else 0
                pct = total_bytes / info["bytes"] * 100
                print(f"  ... {total_chunks} 包 / {total_bytes:,} B ({pct:.0f}%), "
                      f"{kbps:.1f} KB/s")
        else:
            if t_first is not None:
                if time.perf_counter() - last_data_time > 2.0:
                    break
            else:
                if time.perf_counter() - t_send > TIMEOUT:
                    print(f"  ❌ 超时: {TIMEOUT}s 内未收到数据")
                    break
            time.sleep(0.01)

    t_end = time.perf_counter()
    first_delay_ms = (t_first - t_send) * 1000 if t_first else None
    total_duration = t_end - t_send
    avg_kbps = total_bytes / total_duration / 1024 if total_duration > 0 else 0
    completeness = total_bytes / info["bytes"] * 100 if info["bytes"] > 0 else 0

    status = "✅" if completeness >= 99 else ("⚠️" if completeness >= 50 else "❌")
    print(f"  {status} 总计: {total_bytes:,} / {info['bytes']:,} B ({completeness:.1f}%), "
          f"耗时 {total_duration:.1f}s, {avg_kbps:.1f} KB/s")

    return {
        "mode": mode, "mode_name": info["name"], "round": round_num,
        "first_byte_delay_ms": first_delay_ms,
        "total_bytes": total_bytes, "expected_bytes": info["bytes"],
        "completeness_pct": round(completeness, 1),
        "total_duration_s": round(total_duration, 3),
        "avg_kbps": round(avg_kbps, 1),
        "first_data_preview": format_bytes(first_data) if first_data else "N/A",
        "status": status,
    }


def test_mode(ser: serial.Serial, mode: int, rounds: int) -> list:
    """对指定 MODE 运行多轮测试。"""
    info = MODE_INFO[mode]
    print(f"\n{'='*60}")
    print(f"  {info['name']}: {info['points']:,} 点, {info['bytes']:,} 字节, {rounds} 轮")
    print(f"{'='*60}")

    set_mode(ser, mode)
    results = []
    for r in range(1, rounds + 1):
        result = run_single_test(ser, mode, r)
        results.append(result)
        if result["first_byte_delay_ms"] is None and result["total_bytes"] == 0:
            print(f"  ⚠️ 无数据，跳过后续轮次")
            break
        if r < rounds:
            print(f"  ⏸️  等待卡盘停止 (3s)...")
            time.sleep(3)
    return results


def print_summary(all_results: list):
    """打印汇总报告。"""
    print(f"\n{'='*70}")
    print(f"  测试报告")
    print(f"{'='*70}")

    if not all_results:
        print("  ❌ 无数据")
        return

    by_mode = defaultdict(list)
    for r in all_results:
        by_mode[r["mode"]].append(r)

    for mode in sorted(by_mode.keys()):
        results = by_mode[mode]
        info = MODE_INFO[mode]
        print(f"\n  [{info['name']}] 期望 {info['bytes']:,} B ({info['points']:,} 点)")
        print(f"  {'轮次':<6} {'首字节延迟':<12} {'实际字节':<12} {'收全率':<10} {'耗时':<10} {'速率':<10}")
        print(f"  {'-'*60}")

        delays = []
        for r in results:
            d = r["first_byte_delay_ms"]
            ds = f"{d:>8.1f} ms" if d else "    N/A   "
            print(f"  {r['round']:<6} {ds:<12} {r['total_bytes']:>10,} B  "
                  f"{r['completeness_pct']:>7.1f}%  {r['total_duration_s']:>7.2f}s  "
                  f"{r['avg_kbps']:>7.1f} KB/s  {r['status']}")
            if d:
                delays.append(d)

        valid = [r for r in results if r["total_bytes"] > 0]
        if valid:
            pct_list = [r["completeness_pct"] for r in valid]
            bytes_list = [r["total_bytes"] for r in valid]
            print(f"  {'─'*60}")
            print(f"  收全率: min={min(pct_list):.1f}%  max={max(pct_list):.1f}%  "
                  f"avg={sum(pct_list)/len(pct_list):.1f}%")
            print(f"  数据量: min={min(bytes_list):,} B  max={max(bytes_list):,} B")
            if delays:
                print(f"  首字节延迟: min={min(delays):.1f} ms  max={max(delays):.1f} ms  "
                      f"avg={sum(delays)/len(delays):.1f} ms")
        else:
            print(f"  ❌ 全部轮次无数据")


def main():
    port = DEFAULT_PORT
    rounds = DEFAULT_ROUNDS
    test_all = False
    target_mode = 0

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--all":
            test_all = True
        elif arg == "--mode" and i + 1 < len(args):
            target_mode = int(args[i + 1])
            i += 1
        elif arg.startswith("COM"):
            port = arg
        else:
            try:
                rounds = int(arg)
            except ValueError:
                pass
        i += 1

    modes_to_test = [0, 1, 2] if test_all else [target_mode]

    print(f"串口延迟测试")
    print(f"  端口: {port}  |  波特率: {BAUDRATE}")
    print(f"  模式: {[MODE_INFO[m]['name'] for m in modes_to_test]}  |  每模式 {rounds} 轮")
    print()

    try:
        ser = serial.Serial(port=port, baudrate=BAUDRATE, timeout=0.1)
        print(f"✅ 串口 {port} 已打开")
    except Exception as e:
        print(f"❌ 无法打开串口 {port}: {e}")
        sys.exit(1)

    print("⏳ 等待固件就绪 (2s)...")
    time.sleep(2)

    all_results = []
    try:
        for mode in modes_to_test:
            results = test_mode(ser, mode, rounds)
            all_results.extend(results)
            if mode != modes_to_test[-1]:
                print(f"\n⏸️  切换到下一模式 (2s)...")
                time.sleep(2)
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
    finally:
        ser.close()
        print(f"\n🔌 串口已关闭")

    print_summary(all_results)


if __name__ == "__main__":
    main()
