# -*- coding: utf-8 -*-
"""
配置管理模块
统一管理系统配置，支持配置文件的读写
"""
import copy
import os
import json
from typing import Optional, Dict, Any, List
from PyQt5.QtCore import QObject, pyqtSignal
import logging
from .path_utils import get_config_path

logger = logging.getLogger(__name__)

# X/Y 滑台标定：100000 脉冲 = 156.12 mm → 640.53 脉冲/mm（2026-07-24 更新）
X_AXIS_PULSES_PER_MM = 640.53
# Z 轴（前后）滑台为不同型号：实测“指定 5mm 实际运动 40mm”（8 倍），
# 原系数 6407.801478 ÷ 8 ≈ 800.97518475 脉冲/mm（2026-09-07 复核修正）
Z_AXIS_PULSES_PER_MM = 800.97518475

# PGA 增益档位（对应固件 PGA<0~7>~：0=×1 ~ 7=×128）
PGA_GAIN_VALUES = (1, 2, 4, 8, 16, 32, 64, 128)

# 各档位量程命名（mT）：建议保守线性量程向下取整十（2026-09-07 标定）
PGA_RANGE_TEXTS = (
    "3120mT",  # ×1
    "1570mT",  # ×2
    "780mT",   # ×4
    "390mT",   # ×8
    "190mT",   # ×16
    "90mT",    # ×32
    "40mT",    # ×64
    "20mT",    # ×128
)
# 各档位理论最大量程（mT，16bit 代码满量程 0x7FFF/0x8000 边界，2026-09-07 标定）
PGA_THEORY_MAX_TEXTS = (
    "6399mT",  # ×1
    "3239mT",  # ×2
    "1619mT",  # ×4
    "811mT",   # ×8
    "403mT",   # ×16
    "199mT",   # ×32
    "97mT",    # ×64
    "46mT",    # ×128
)
PGA_OPTION_TEXTS = tuple(
    "{0}量程 (理论{1})".format(range_text, theory_text)
    for range_text, theory_text in zip(PGA_RANGE_TEXTS, PGA_THEORY_MAX_TEXTS)
)
PGA_DEFAULT_INDEX = 5  # ×32（固件默认增益）

# 各 PGA 档位默认零场偏置（原始 ADC 计数，键 0~7 = ×1~×128）
# 来源：2026-09-07 两轮一致性较好的零场标定（10mT 环境）取平均
PGA_OFFSETS_KEY = 'pga_offsets'
PGA_DEFAULT_OFFSETS = {
    '0': -26.762011423190738,
    '1': -53.43753875354281,
    '2': -106.21986176213516,
    '3': -212.25595570273902,
    '4': -423.38122533254596,
    '5': -845.6150033990581,
    '6': -1692.3727071422007,
    '7': -3387.012073047531,
}

# 各 PGA 档位磁场换算系数（ADC counts/mT）
# 来源：2026-09-07 标定报告（10mT 轮确定档位比例 + 238mT 轮 ×1 绝对锚定），
#       仅适用于当前 IDAC 配置；重标定后请同步更新本表。
PGA_MAG_ADC_PER_MT = {
    0: 5.117,    # ×1
    1: 10.10,    # ×2
    2: 20.18,    # ×4
    3: 40.13,    # ×8
    4: 80.2,     # ×16
    5: 160.3,    # ×32
    6: 320.8,    # ×64
    7: 640.9,    # ×128
}


def get_pga_mag_conversion_factor(index: int) -> float:
    """获取指定 PGA 档位的磁场换算系数（ADC counts/mT）。"""
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    if 0 <= index < len(PGA_GAIN_VALUES):
        return float(PGA_MAG_ADC_PER_MT[index])
    logger.warning(f"未知 PGA 档位 {index}，回退使用 ×1 换算系数")
    return float(PGA_MAG_ADC_PER_MT[0])


# 动作类型定义
ACTION_TYPES = ['X', 'Z', 'X+', 'X-', 'Z+', 'Z-']

# 动作类型显示文本
ACTION_TEXT = {
    'X': '移动到X目标',
    'Z': '移动到Z目标',
    'X+': 'X正偏移',
    'X-': 'X负偏移',
    'Z+': 'Z正偏移',
    'Z-': 'Z负偏移',
}

# 动作类型到显示文本的映射
def action_to_text(action: str) -> str:
    return ACTION_TEXT.get(action, action)

def text_to_action(text: str) -> str:
    for k, v in ACTION_TEXT.items():
        if v == text:
            return k
    return text


# 默认方案配置
DEFAULT_SCHEMES = {
    0: {  # 平面旋转测试
        "test_schemes": [
            {"steps": ["X", "Z"]},
        ],
        "suspend_schemes": [
            {"steps": ["Z", "X"]},
        ],
        "active_test_scheme": 0,
        "active_suspend_scheme": 0,
    },
    1: {  # 外侧面旋转测试
        "test_schemes": [
            {"steps": ["Z", "X"]},
        ],
        "suspend_schemes": [
            {"steps": ["X", "Z"]},
        ],
        "active_test_scheme": 0,
        "active_suspend_scheme": 0,
    },
    2: {  # 内侧面旋转测试
        "test_schemes": [
            {"steps": ["X", "X+", "Z", "X"]},
        ],
        "suspend_schemes": [
            {"steps": ["X+", "Z", "X"]},
        ],
        "active_test_scheme": 0,
        "active_suspend_scheme": 0,
    },
    3: {  # 外侧面垂直测试
        "test_schemes": [
            {"steps": ["Z", "X"]},
        ],
        "suspend_schemes": [
            {"steps": ["X", "Z"]},
        ],
        "active_test_scheme": 0,
        "active_suspend_scheme": 0,
    },
}


class ConfigManager(QObject):
    """配置管理器"""

    # 测试类型改变信号
    signal_test_type_changed = pyqtSignal(int)
    # 测试速度改变信号
    signal_test_speed_changed = pyqtSignal(int)
    # 测试/挂起移动方案改变信号
    signal_scheme_changed = pyqtSignal(int)
    # PGA 增益改变信号
    signal_pga_gain_changed = pyqtSignal(int)
    # PGA 档位偏置更新信号（参数为 PGA 档位索引）
    signal_pga_offset_changed = pyqtSignal(int)

    DEFAULT_CONFIG = {
        'offset': '0',
        # 各 PGA 档位零场偏置（原始 ADC 计数）
        PGA_OFFSETS_KEY: json.dumps(PGA_DEFAULT_OFFSETS, ensure_ascii=False),
        'COM': 'COM12',
        # 测试位置
        'test_x': '0',
        'test_z': '0',
        # 挂起位置
        'suspend_x': '0',
        'suspend_z': '0',
        # 测试类型: 0=平面旋转, 1=外侧面旋转, 2=内侧面旋转, 3=外侧面垂直
        'test_type': '0',
        # 测试速度: 0=高速测量, 1=高分辨率测量
        'test_speed': '0',
        # PGA 增益档位: 0=×1 ~ 7=×128（默认 5=×32，与固件默认一致）
        'pga_gain': '5',
        # 测试位置移动方案: x_first=先X后Z, z_first=先Z后X, x_extra=先X+X偏移再Z再X回退
        'test_movement_scheme': 'x_first',
        # 挂起位置移动方案
        'suspend_movement_scheme': 'z_first',
        # X偏移量(mm)
        'inner_x_offset': '5',
        # Z偏移量(mm)
        'inner_z_offset': '1',
        # 贴靠动作回弹距离(mm)
        'retract_distance': '0.3',
        # 方向键短按移动距离(mm)
        'stage_step_distance': '1.0',
    }

    def __init__(self, config_file: str = "configuration.txt"):
        super().__init__()
        # 运行时配置放在源码入口或打包后的 MARS.exe 同级目录。
        if not os.path.isabs(config_file):
            config_file = get_config_path(config_file)
        self.config_file = config_file
        self._config: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            logger.info(f"配置文件不存在，正在创建: {self.config_file}")
            self._config = self.DEFAULT_CONFIG.copy()
            self.save()
            return

        try:
            self._config = {}
            file_keys = set()
            with open(self.config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        self._config[key] = value.strip()
                        file_keys.add(key)
            for key, value in self.DEFAULT_CONFIG.items():
                self._config.setdefault(key, value)
            # 旧版本只有单值 offset：按当前档位增益倍数外推，填充 8 档偏置表
            if PGA_OFFSETS_KEY not in file_keys and 'offset' in file_keys:
                try:
                    base_offset = float(self._config.get('offset', 0.0) or 0.0)
                    if abs(base_offset) > 1e-9:
                        current_index = self.pga_gain
                        current_gain = PGA_GAIN_VALUES[current_index]
                        migrated_offsets = {}
                        for index, gain in enumerate(PGA_GAIN_VALUES):
                            migrated_offsets[str(index)] = base_offset * gain / current_gain
                        self._config[PGA_OFFSETS_KEY] = json.dumps(
                            migrated_offsets, ensure_ascii=False
                        )
                        logger.info(
                            "旧版单值偏置已按增益外推为 8 档偏置表: "
                            f"base={base_offset:.2f} ADC @ PGA{current_index} (×{current_gain})"
                        )
                except (TypeError, ValueError) as e:
                    logger.warning(f"旧版偏置外推失败: {e}")
            logger.info(f"配置文件加载成功: {self.config_file}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self._config = self.DEFAULT_CONFIG.copy()

    def save(self) -> bool:
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                for key, value in self._config.items():
                    f.write(f"{key}:{value}\n")
            logger.info(f"配置文件保存成功: {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取配置值"""
        return self._config.get(key, default)

    @staticmethod
    def _strip_quotes(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip().strip('"').strip("'")

    def set(self, key: str, value: Any) -> bool:
        """设置配置值"""
        self._config[key] = str(value)
        return self.save()

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数配置值"""
        try:
            return int(self._config.get(key, default))
        except ValueError:
            logger.warning(f"配置项 {key} 不是有效的整数: {self._config.get(key)}")
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """获取浮点数配置值"""
        try:
            return float(self._config.get(key, default))
        except ValueError:
            logger.warning(f"配置项 {key} 不是有效的浮点数: {self._config.get(key)}")
            return default

    @property
    def com_port(self) -> str:
        return self._strip_quotes(self.get('COM', 'COM12')) or 'COM12'

    @com_port.setter
    def com_port(self, value: str) -> None:
        self.set('COM', self._strip_quotes(value) or 'COM12')

    # ==================== 零场偏置（按 PGA 档位） ====================

    @property
    def pga_offsets(self) -> Dict[int, float]:
        """全部 PGA 档位的零场偏置（ADC 计数），键为档位索引 0~7。"""
        raw = self.get(PGA_OFFSETS_KEY, '')
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    result: Dict[int, float] = {}
                    for raw_key, raw_value in parsed.items():
                        try:
                            result[int(raw_key)] = float(raw_value)
                        except (TypeError, ValueError):
                            continue
                    if result:
                        return result
            except (ValueError, TypeError) as e:
                logger.warning(f"配置项 {PGA_OFFSETS_KEY} 解析失败，按单值偏置外推: {e}")
        # 兼容：偏置表缺失时按旧单值 offset × 增益倍数外推
        legacy_offset = self.get_float('offset', 0.0)
        if legacy_offset:
            current_gain = PGA_GAIN_VALUES[self.pga_gain]
            return {
                index: legacy_offset * gain / current_gain
                for index, gain in enumerate(PGA_GAIN_VALUES)
            }
        return {
            index: float(PGA_DEFAULT_OFFSETS[str(index)])
            for index in range(len(PGA_GAIN_VALUES))
        }

    def get_offset_for_pga(self, index: int) -> float:
        """获取指定 PGA 档位的零场偏置（ADC 计数）。"""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return 0.0
        if not (0 <= index < len(PGA_GAIN_VALUES)):
            return 0.0
        return float(self.pga_offsets.get(index, 0.0))

    def set_offset_for_pga(self, index: int, value: float) -> bool:
        """保存指定 PGA 档位的零场偏置，并同步旧单值字段 offset。"""
        try:
            index = int(index)
            value = float(value)
        except (TypeError, ValueError):
            return False
        if not (0 <= index < len(PGA_GAIN_VALUES)):
            return False

        offsets = self.pga_offsets
        offsets[index] = value
        self._config[PGA_OFFSETS_KEY] = json.dumps(
            {str(key): val for key, val in offsets.items()}, ensure_ascii=False
        )
        # 旧字段 offset 始终表示“当前档位”的偏置，供历史代码兼容读取
        if index == self.pga_gain:
            self._config['offset'] = str(value)

        ok = self.save()
        if ok:
            self.signal_pga_offset_changed.emit(index)
        return ok

    @property
    def offset(self) -> float:
        """当前 PGA 档位的零场偏置（ADC 计数）。"""
        return self.get_offset_for_pga(self.pga_gain)

    @offset.setter
    def offset(self, value: float) -> None:
        """写入当前 PGA 档位的零场偏置。"""
        self.set_offset_for_pga(self.pga_gain, value)

    @property
    def test_x(self) -> int:
        return self.get_int('test_x', 0)

    @test_x.setter
    def test_x(self, value: int) -> None:
        self.set('test_x', value)

    @property
    def test_z(self) -> int:
        return self.get_int('test_z', 0)

    @test_z.setter
    def test_z(self, value: int) -> None:
        self.set('test_z', value)

    @property
    def suspend_x(self) -> int:
        return self.get_int('suspend_x', 0)

    @suspend_x.setter
    def suspend_x(self, value: int) -> None:
        self.set('suspend_x', value)

    @property
    def suspend_z(self) -> int:
        return self.get_int('suspend_z', 0)

    @suspend_z.setter
    def suspend_z(self, value: int) -> None:
        self.set('suspend_z', value)

    @property
    def test_type(self) -> int:
        return self.get_int('test_type', 0)

    @test_type.setter
    def test_type(self, value: int) -> None:
        self.set('test_type', value)
        self.signal_test_type_changed.emit(value)

    @property
    def test_speed(self) -> int:
        return self.get_int('test_speed', 0)

    @test_speed.setter
    def test_speed(self, value: int) -> None:
        self.set('test_speed', value)
        self.signal_test_speed_changed.emit(value)

    @property
    def test_movement_scheme(self) -> str:
        return self.get('test_movement_scheme', 'x_first')

    @test_movement_scheme.setter
    def test_movement_scheme(self, value: str) -> None:
        self.set('test_movement_scheme', value)

    @property
    def suspend_movement_scheme(self) -> str:
        return self.get('suspend_movement_scheme', 'z_first')

    @suspend_movement_scheme.setter
    def suspend_movement_scheme(self, value: str) -> None:
        self.set('suspend_movement_scheme', value)

    @property
    def inner_x_offset(self) -> float:
        return self.get_float('inner_x_offset', 5.0)

    @inner_x_offset.setter
    def inner_x_offset(self, value: float) -> None:
        self.set('inner_x_offset', value)

    @property
    def inner_z_offset(self) -> float:
        return self.get_float('inner_z_offset', 1.0)

    @inner_z_offset.setter
    def inner_z_offset(self, value: float) -> None:
        self.set('inner_z_offset', value)

    @property
    def retract_distance(self) -> float:
        return max(0.0, self.get_float('retract_distance', 0.3))

    @retract_distance.setter
    def retract_distance(self, value: float) -> None:
        self.set('retract_distance', max(0.0, float(value)))

    @property
    def stage_step_distance(self) -> float:
        """方向键短按移动距离(mm)。"""
        return max(0.0, self.get_float('stage_step_distance', 1.0))

    @stage_step_distance.setter
    def stage_step_distance(self, value: float) -> None:
        self.set('stage_step_distance', max(0.0, float(value)))

    @property
    def pga_gain(self) -> int:
        """PGA 增益档位索引 (0=×1 ~ 7=×128)。"""
        index = self.get_int('pga_gain', PGA_DEFAULT_INDEX)
        if 0 <= index < len(PGA_GAIN_VALUES):
            return index
        return PGA_DEFAULT_INDEX

    @pga_gain.setter
    def pga_gain(self, value: int) -> None:
        try:
            index = int(value)
        except (TypeError, ValueError):
            index = PGA_DEFAULT_INDEX
        index = max(0, min(index, len(PGA_GAIN_VALUES) - 1))
        self.set('pga_gain', index)
        # 同步旧单值字段 offset，使其始终等于当前档位偏置
        try:
            self._config['offset'] = str(self.get_offset_for_pga(index))
        except Exception:
            pass
        self.save()
        self.signal_pga_gain_changed.emit(index)

    # ==================== 移动方案管理 ====================

    @staticmethod
    def _empty_type_scheme() -> Dict[str, Any]:
        return {
            'test_schemes': [],
            'suspend_schemes': [],
            'active_test_scheme': 0,
            'active_suspend_scheme': 0,
        }

    def _build_default_type_scheme(
        self,
        test_type: int,
        schemes: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if test_type in DEFAULT_SCHEMES:
            return copy.deepcopy(DEFAULT_SCHEMES[test_type])

        if schemes:
            fallback = schemes.get(0)
            if fallback is None and schemes:
                fallback = next(iter(schemes.values()))
            if fallback is not None:
                return copy.deepcopy(fallback)

        return self._empty_type_scheme()

    def _normalize_test_type_schemes(self, schemes: Any) -> Optional[Dict[int, Dict[str, Any]]]:
        if not isinstance(schemes, dict):
            return None

        normalized: Dict[int, Dict[str, Any]] = {}
        for raw_key, raw_value in schemes.items():
            try:
                test_type = int(raw_key)
            except (TypeError, ValueError):
                logger.warning(f"Ignore invalid test_type_schemes key: {raw_key}")
                continue

            if not isinstance(raw_value, dict):
                logger.warning(
                    f"Invalid scheme config for test type {test_type}, fallback to defaults."
                )
                normalized[test_type] = self._build_default_type_scheme(test_type, normalized)
                continue

            normalized[test_type] = copy.deepcopy(raw_value)

        return normalized

    def _get_schemes(self) -> Dict:
        """获取所有移动方案配置"""
        schemes_json = self.get('test_type_schemes', '')
        if schemes_json:
            try:
                return self._normalize_test_type_schemes(json.loads(schemes_json))
            except json.JSONDecodeError:
                logger.warning(f"移动方案配置解析失败，使用默认值")
        return None

    def _save_schemes(self, schemes: Dict) -> bool:
        """保存所有移动方案配置"""
        normalized_schemes = self._normalize_test_type_schemes(schemes)
        if normalized_schemes is None:
            normalized_schemes = {}
        schemes_json = json.dumps(normalized_schemes, ensure_ascii=False)
        self._config['test_type_schemes'] = schemes_json
        return self.save()

    def get_test_type_schemes(self) -> Dict:
        """获取所有测试类型的移动方案配置"""
        schemes = self._get_schemes()
        if schemes is None:
            schemes = copy.deepcopy(DEFAULT_SCHEMES)
            self._save_schemes(schemes)
        return schemes

    def get_schemes_for_type(self, test_type: int) -> Dict:
        """获取指定测试类型的移动方案配置"""
        schemes = self.get_test_type_schemes()
        if test_type in schemes:
            return schemes[test_type]
        return self._build_default_type_scheme(test_type, schemes)

    def get_test_schemes(self, test_type: int) -> List[Dict]:
        """获取指定测试类型的测试位置方案列表"""
        type_schemes = self.get_schemes_for_type(test_type)
        return type_schemes.get('test_schemes', [])

    def get_suspend_schemes(self, test_type: int) -> List[Dict]:
        """获取指定测试类型的挂起位置方案列表"""
        type_schemes = self.get_schemes_for_type(test_type)
        return type_schemes.get('suspend_schemes', [])

    def get_active_test_scheme_index(self, test_type: int) -> int:
        """获取指定测试类型的当前测试方案索引"""
        type_schemes = self.get_schemes_for_type(test_type)
        return type_schemes.get('active_test_scheme', 0)

    def get_active_suspend_scheme_index(self, test_type: int) -> int:
        """获取指定测试类型的当前挂起方案索引"""
        type_schemes = self.get_schemes_for_type(test_type)
        return type_schemes.get('active_suspend_scheme', 0)

    def get_active_test_scheme(self, test_type: int) -> Dict:
        """获取指定测试类型的当前测试方案"""
        schemes = self.get_test_schemes(test_type)
        index = self.get_active_test_scheme_index(test_type)
        if index < len(schemes):
            return schemes[index]
        return schemes[0] if schemes else {"name": "x_first", "steps": ["X", "Z"]}

    def get_active_suspend_scheme(self, test_type: int) -> Dict:
        """获取指定测试类型的当前挂起方案"""
        schemes = self.get_suspend_schemes(test_type)
        index = self.get_active_suspend_scheme_index(test_type)
        if index < len(schemes):
            return schemes[index]
        return schemes[0] if schemes else {"name": "z_first", "steps": ["Z", "X"]}

    def set_active_scheme_index(self, test_type: int, is_test: bool, index: int) -> bool:
        """设置当前选中的方案索引"""
        schemes = self.get_test_type_schemes()
        if test_type not in schemes:
            schemes[test_type] = self._build_default_type_scheme(test_type, schemes)

        key = 'active_test_scheme' if is_test else 'active_suspend_scheme'
        schemes[test_type][key] = index
        saved = self._save_schemes(schemes)
        if saved:
            self.signal_scheme_changed.emit(test_type)
        return saved

    def update_scheme(self, test_type: int, is_test: bool, scheme_index: int, scheme: Dict) -> bool:
        """更新指定方案"""
        schemes = self.get_test_type_schemes()
        if test_type not in schemes:
            schemes[test_type] = self._build_default_type_scheme(test_type, schemes)

        key = 'test_schemes' if is_test else 'suspend_schemes'
        if scheme_index < len(schemes[test_type][key]):
            schemes[test_type][key][scheme_index] = scheme
            saved = self._save_schemes(schemes)
            if saved:
                self.signal_scheme_changed.emit(test_type)
            return saved
        return False

    def add_scheme(self, test_type: int, is_test: bool, scheme: Dict) -> bool:
        """添加新方案"""
        schemes = self.get_test_type_schemes()
        if test_type not in schemes:
            # 使用DEFAULT_SCHEMES中对应的类型，如果没有则使用第一个可用的
            schemes[test_type] = self._build_default_type_scheme(test_type, schemes)

        key = 'test_schemes' if is_test else 'suspend_schemes'
        schemes[test_type][key].append(scheme)
        saved = self._save_schemes(schemes)
        if saved:
            self.signal_scheme_changed.emit(test_type)
        return saved

    def delete_scheme(self, test_type: int, is_test: bool, scheme_index: int) -> bool:
        """删除指定方案"""
        schemes = self.get_test_type_schemes()
        if test_type not in schemes:
            return False

        key = 'test_schemes' if is_test else 'suspend_schemes'
        if scheme_index < len(schemes[test_type][key]) and len(schemes[test_type][key]) > 1:
            del schemes[test_type][key][scheme_index]
            # 如果删除的不是最后一个，需要调整active_index
            active_key = 'active_test_scheme' if is_test else 'active_suspend_scheme'
            if schemes[test_type][active_key] >= scheme_index:
                schemes[test_type][active_key] = max(0, schemes[test_type][active_key] - 1)
            saved = self._save_schemes(schemes)
            if saved:
                self.signal_scheme_changed.emit(test_type)
            return saved
        return False

    def get_inner_x_offset_pulse(self) -> int:
        """获取X轴偏移量（脉冲），按实测标定换算"""
        return int(round(self.inner_x_offset * X_AXIS_PULSES_PER_MM))

    def get_inner_z_offset_pulse(self) -> int:
        """获取Z轴偏移量（脉冲），按实测标定换算"""
        return int(round(self.inner_z_offset * Z_AXIS_PULSES_PER_MM))


# 全局配置实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
