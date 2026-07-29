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
# Z 轴保留旧标定
Z_AXIS_PULSES_PER_MM = 6407.801478


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

    DEFAULT_CONFIG = {
        'offset': '0',
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
            with open(self.config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if ':' in line:
                        key, value = line.split(':', 1)
                        self._config[key.strip()] = value.strip()
            for key, value in self.DEFAULT_CONFIG.items():
                self._config.setdefault(key, value)
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

    @property
    def offset(self) -> float:
        return self.get_float('offset', 0.0)

    @offset.setter
    def offset(self, value: float) -> None:
        self.set('offset', value)

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
