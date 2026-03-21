# -*- coding: utf-8 -*-
"""
MARS - 旋转体表磁测量分析系统
"""
__version__ = "1.0.0"
__author__ = "IceSugarZxy"

from .logger import init_logging, get_logger
from .config_manager import ConfigManager, get_config_manager

__all__ = [
    'init_logging',
    'get_logger',
    'ConfigManager',
    'get_config_manager',
]
