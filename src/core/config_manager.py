# -*- coding: utf-8 -*-
"""
配置管理模块
统一管理系统配置，支持配置文件的读写
"""
import os
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器"""

    DEFAULT_CONFIG = {
        'offset': '0',
        'COM': 'COM12',
        'baudrate': '921600',
        # 测试位置
        'test_x': '0',
        'test_z': '0',
        # 挂起位置
        'suspend_x': '0',
        'suspend_z': '0',
    }

    def __init__(self, config_file: str = "configuration.txt"):
        # 使用相对于模块文件的路径，确保无论从哪里运行都能找到配置文件
        if not os.path.isabs(config_file):
            module_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(os.path.dirname(module_dir), config_file)
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
        return self.get('COM', 'COM12')

    @com_port.setter
    def com_port(self, value: str) -> None:
        self.set('COM', value)

    @property
    def baudrate(self) -> int:
        return int(self.get('baudrate', '921600'))

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        self.set('baudrate', str(value))

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


# 全局配置实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
