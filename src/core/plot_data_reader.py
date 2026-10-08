# -*- coding: utf-8 -*-
"""plot_data CSV 的读取与扫描（历史数据面板与数据比对面板共用）。

保存格式（data_process.save_plot_measure_data 写入）：

    样品名称,xxx
    保存时间,20260930_103313
    === 分析结果 ===
    N极最大值,336.68
    角度(度),磁场强度
    0.000000,278.20600

本模块只做纯文本解析，不依赖 Qt。
"""

import csv
import glob
import os
import re
from datetime import datetime

# 列表列定义，顺序必须与 history_panel.ui / compare_panel.ui 中表格的列一致
TABLE_COLUMNS = ('sample_name', 'sample_code', 'time_str', 'tester', 'polar_num', 'airgap', 'remark')

# 文件名形如 样品名称_20260930_103313.csv
FILENAME_PATTERN = re.compile(r"(.+?)_(\d{8}_\d{6})\.csv")


def is_plot_data_header(row) -> bool:
    """判断一行是否为波形数据段的表头（角度,磁场强度）。"""
    return len(row) >= 2 and "角度" in row[0] and "磁场" in row[1]


def apply_sample_info_row(sample_info: dict, row) -> None:
    """把一行 key,value 元信息写入 sample_info。"""
    if len(row) < 2:
        return

    key = row[0].strip()
    value = row[1].strip()
    if "样品名称" in key:
        sample_info['sample_name'] = value
    elif "样品编号" in key:
        sample_info['sample_code'] = value
    elif "材料" in key:
        sample_info['material'] = value
    elif "线圈编号" in key:
        sample_info['coil_code'] = value
    elif "备注" in key:
        sample_info['remark'] = value
    elif "保存时间" in key:
        sample_info['save_time'] = value
    elif "极数" in key:
        sample_info['polar_num'] = value
    elif "气隙" in key:
        sample_info['airgap'] = value
    elif "测试员" in key:
        sample_info['tester'] = value
    elif "磁化条件" in key:
        sample_info['mag_condition'] = value
    elif "探头" in key:
        sample_info['probe'] = value


def read_plot_csv_header(file_path: str) -> dict:
    """只读到波形表头为止，返回元信息字典（列表加载用）。"""
    sample_info = {}
    with open(file_path, 'r', encoding='utf-8') as fh:
        for row in csv.reader(fh):
            if is_plot_data_header(row):
                break
            apply_sample_info_row(sample_info, row)
    return sample_info


def read_plot_csv(file_path: str):
    """读整份 CSV，返回 (sample_info, angle_data, mag_data)。"""
    sample_info = {}
    angle_data = []
    mag_data = []

    with open(file_path, 'r', encoding='utf-8') as fh:
        rows = list(csv.reader(fh))

    data_started = False
    for row in rows:
        if is_plot_data_header(row):
            data_started = True
            continue

        if not data_started:
            apply_sample_info_row(sample_info, row)
            continue

        if len(row) >= 2 and row[0].strip():
            try:
                angle_data.append(float(row[0].strip()))
                mag_data.append(float(row[1].strip()))
            except (ValueError, IndexError):
                continue

    return sample_info, angle_data, mag_data


def read_plot_csv_mag(file_path: str):
    """只取磁场列，返回 (mags, sample_info, save_time)。

    与 read_plot_csv 的区别：跳过元信息与“=== 分析结果 ===”段，只解析波形数据行，
    供缺陷指纹比对等只关心波形的场景使用。
    """
    sample_info = {}
    mags = []
    data_started = False

    with open(file_path, 'r', encoding='utf-8-sig', newline='') as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            if not data_started:
                if is_plot_data_header(row):
                    data_started = True
                    continue
                apply_sample_info_row(sample_info, row)
                continue
            try:
                mags.append(float(row[1]))
            except (ValueError, IndexError):
                continue

    return mags, sample_info, sample_info.get('save_time', '')


def time_label(save_time: str, file_path: str = "") -> str:
    """把 20260930_103313 这类时间戳转成 10:33:13；失败时退回文件名。"""
    if len(save_time) >= 15 and save_time[8] == '_':
        return "%s:%s:%s" % (save_time[9:11], save_time[11:13], save_time[13:15])
    if save_time:
        return save_time
    return os.path.basename(file_path)[:16] if file_path else ""


def scan_plot_data_records(plot_data_dir: str) -> list:
    """递归扫描 plot_data 下所有 名称_时间戳.csv，按时间倒序返回记录列表。

    记录字段：sample_name / sample_code / time_str / tester / polar_num /
              airgap / remark / save_time / file_path
    """
    records = []

    csv_files = glob.glob(os.path.join(plot_data_dir, "**", "*.csv"), recursive=True)
    csv_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    for file_path in csv_files:
        filename = os.path.basename(file_path)
        match = FILENAME_PATTERN.match(filename)
        if not match:
            # 命名不规范的 CSV 不进列表（与历史数据面板保持一致）
            continue

        sample_name = match.group(1)
        timestamp_str = match.group(2)
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            time_str = timestamp_str

        try:
            sample_info = read_plot_csv_header(file_path)
        except Exception:
            sample_info = {}

        records.append({
            'sample_name': sample_info.get('sample_name', sample_name),
            'sample_code': sample_info.get('sample_code', ''),
            'time_str': sample_info.get('save_time', time_str),
            'tester': sample_info.get('tester', ''),
            'polar_num': sample_info.get('polar_num', ''),
            'airgap': sample_info.get('airgap', ''),
            'remark': sample_info.get('remark', ''),
            'save_time': sample_info.get('save_time', timestamp_str),
            'file_path': file_path,
        })

    return records


def sort_time_key(record: dict) -> str:
    """按保存时间排序用的键（升序即时间从早到晚）。"""
    stamp = record.get('save_time') or ''
    if len(stamp) == 15 and stamp[8] == '_':
        return stamp
    return record.get('time_str') or ''
