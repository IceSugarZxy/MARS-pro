# -*- coding: utf-8 -*-
"""
日志配置模块
统一管理系统日志输出
"""
import logging
import os
from datetime import datetime
from typing import Optional


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    console: bool = True
) -> logging.Logger:
    """
    配置日志系统

    Args:
        level: 日志级别
        log_file: 日志文件路径，如果为None则不写文件
        console: 是否输出到控制台

    Returns:
        配置好的logger对象
    """
    # 创建logger
    logger = logging.getLogger('MARS')
    logger.setLevel(level)

    # 清除已有的处理器
    logger.handlers.clear()

    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台输出
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件输出
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = 'MARS') -> logging.Logger:
    """获取logger，子logger会继承父logger的handlers"""
    logger = logging.getLogger(f'MARS.{name}')
    logger.propagate = True
    return logger


# 默认日志配置
_default_logger: Optional[logging.Logger] = None


def init_logging(log_dir: str = "logs") -> logging.Logger:
    """
    初始化默认日志系统

    Args:
        log_dir: 日志目录

    Returns:
        配置好的logger
    """
    global _default_logger

    # 创建日志目录
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 生成日志文件名
    log_file = os.path.join(
        log_dir,
        f"mars_{datetime.now().strftime('%Y%m%d')}.log"
    )

    _default_logger = setup_logging(
        level=logging.INFO,
        log_file=log_file,
        console=True
    )

    return _default_logger


def get_default_logger() -> logging.Logger:
    """获取默认logger"""
    global _default_logger
    if _default_logger is None:
        _default_logger = init_logging()
    return _default_logger
