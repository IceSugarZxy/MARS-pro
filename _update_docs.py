import os

path = r"e:\Python_project\旋转体表磁测量分析系统\当前版本\MARS\用户手册.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. 测试位置操作说明
content = content.replace(
    '-\u2003\u201c自动下压\u201d：执行 Z 轴贴靠。\n-\u2003\u201c自动左压 / 自动右压\u201d：执行 X 轴左右贴靠。\n-\u2003\u201c回弹距离\u201d：设置贴靠完成后的回弹距离。',
    '-\u2003\u201c自动下压\u201d：执行 Z 轴贴靠（探头下压触碰工件后自动停止并回弹）。\n-\u2003\u201c自动左压\u201d：执行 X 轴左贴靠。\n-\u2003\u201c回弹距离\u201d：贴靠完成后反向回退的距离，默认 0.3 mm（可在测试配置界面调整）。'
)

# 2. 偏置校准时间
content = content.replace(
    '系统发送定时采集命令，采集约 `3` 秒，并预留约 `0.5` 秒处理时间。',
    '系统发送定时采集命令，采集约 `8` 秒，取中间 `3` 秒稳定段计算偏置值。'
)

# 3. 配置文件新增探头量程和测试速度
old_config = '| retract_distance | 贴靠回弹距离，单位 mm |\n| test_type_schemes | 各测试类型的测试/挂起流程配置 |'
new_config = '| sensor_range | 探头量程（0=80mT量程, 1=160mT量程） |\n| test_speed | 测试速度（0=高速测量, 1=高分辨率测量） |\n| retract_distance | 贴靠回弹距离，单位 mm |\n| test_type_schemes | 各测试类型的测试/挂起流程配置 |'
content = content.replace(old_config, new_config)

# 4. 常见问题新增
old_q = '### Q: 打包后配置文件在哪里？\n\n打包运行时，配置文件位于'
new_q = '### Q: 测量较大磁场时波形削顶？\n\n测量 ~120mT 以上磁场时需切换到 160mT 量程。若在 ±100mT 处削顶，说明量程配置不匹配。切换量程后需重新执行偏置校准。\n\n### Q: 数据比对表格中文件名字太长？\n\n表头显示的是 CSV 文件名。可在比对前将文件重命名为更有辨识度的名称。\n\n### Q: 打包后配置文件在哪里？\n\n打包运行时，配置文件位于'
content = content.replace(old_q, new_q)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("用户手册更新完成")
