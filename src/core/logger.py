# -*- coding: utf-8 -*-
"""
日志配置模块
统一管理系统日志输出

- 日志文件按天命名（mars_YYYYMMDD.log），跨零点自动切到新文件
- 消息里的换行/控制字符统一转义，保证一条日志只占一行
- 未捕获异常、子线程异常、原生崩溃都会写进日志
- 打包成无控制台程序时不创建控制台 handler
- 日志目录不可写（如装在 Program Files）时回退到用户目录
"""
import atexit
import faulthandler
import glob
import logging
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta
from typing import Optional

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
LOG_FILE_PREFIX = 'mars_'
LOG_FILE_RE = re.compile(r'^mars_(\d{8})\.log$')
# 设置该环境变量可开启历史日志清理（保留天数），默认不做任何删除
RETENTION_ENV = 'MARS_LOG_RETENTION_DAYS'

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')


def _escape_control_chars(text: str) -> str:
    """转义换行和控制字符（串口原始报文里常见）。"""
    if not text:
        return text
    if '\r' in text or '\n' in text:
        text = text.replace('\r\n', '\\n').replace('\r', '\\r').replace('\n', '\\n')
    return _CONTROL_CHARS_RE.sub(lambda m: '\\x%02x' % ord(m.group(0)), text)


class LogFormatter(logging.Formatter):
    """把消息正文的控制字符转义，避免破坏“一条日志一行”的格式。"""

    def formatMessage(self, record: logging.LogRecord) -> str:
        return _escape_control_chars(super().formatMessage(record))


class DailyFileHandler(logging.FileHandler):
    """按日期切换文件的 handler。

    logging 自带的 TimedRotatingFileHandler 会在文件名后追加日期后缀，
    与既有的 mars_YYYYMMDD.log 命名不一致，这里直接按当前日期重算文件名；
    程序跨零点继续运行时，日志会写到新一天的文件里。
    """

    def __init__(self, log_dir: str, encoding: str = 'utf-8'):
        self.log_dir = os.path.abspath(log_dir)
        self._current_date = date.today()
        super().__init__(self._path_for(self._current_date), mode='a',
                         encoding=encoding, delay=True)

    def _path_for(self, day: date) -> str:
        return os.path.join(self.log_dir, f"{LOG_FILE_PREFIX}{day.strftime('%Y%m%d')}.log")

    @property
    def current_path(self) -> str:
        return self.baseFilename

    def emit(self, record: logging.LogRecord) -> None:
        self._roll_over_if_needed()
        super().emit(record)

    def _roll_over_if_needed(self) -> None:
        today = date.today()
        if today == self._current_date:
            return
        if self.stream:
            try:
                self.stream.close()
            finally:
                self.stream = None
        self._current_date = today
        self.baseFilename = os.path.abspath(self._path_for(today))


def _write_probe(directory: str) -> bool:
    """目录不存在就创建，并实测是否可写。"""
    try:
        os.makedirs(directory, exist_ok=True)
        probe_path = os.path.join(directory, '.write_probe')
        with open(probe_path, 'w', encoding='utf-8'):
            pass
        os.remove(probe_path)
        return True
    except OSError:
        return False


def _resolve_log_dir(log_dir: str) -> Optional[str]:
    """返回一个可写的日志目录，首选目录不可用时回退到用户目录。"""
    candidates = [log_dir]
    local_app_data = os.environ.get('LOCALAPPDATA')
    if local_app_data:
        candidates.append(os.path.join(local_app_data, 'MARS_Pro', 'logs'))
    candidates.append(os.path.join(os.path.expanduser('~'), 'MARS_Pro', 'logs'))
    for candidate in candidates:
        if candidate and _write_probe(candidate):
            return os.path.abspath(candidate)
    return None


def _retention_days() -> int:
    raw = os.environ.get(RETENTION_ENV, '').strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _cleanup_old_logs(log_dir: str, retention_days: int) -> None:
    """删除超过保留天数的 mars_YYYYMMDD.log（retention_days <= 0 时不删除）。"""
    if retention_days <= 0:
        return
    cutoff = date.today() - timedelta(days=retention_days)
    for path in glob.glob(os.path.join(log_dir, f'{LOG_FILE_PREFIX}*.log')):
        match = LOG_FILE_RE.match(os.path.basename(path))
        if not match:
            continue
        try:
            day = datetime.strptime(match.group(1), '%Y%m%d').date()
        except ValueError:
            continue
        if day >= cutoff:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _create_console_handler(level: int, formatter: logging.Formatter) -> Optional[logging.Handler]:
    """创建控制台 handler；无控制台（打包 windowed 程序）时返回 None。"""
    stream = sys.stderr
    if stream is None:
        return None
    try:
        if getattr(stream, 'encoding', None) and stream.encoding.lower().replace('-', '') != 'utf8':
            stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    return console_handler


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    console: bool = True,
    log_dir: Optional[str] = None,
    retention_days: Optional[int] = None
) -> logging.Logger:
    """
    配置日志系统

    Args:
        level: 日志级别
        log_file: 固定日志文件路径（与 log_dir 二选一，优先使用 log_dir）
        console: 是否输出到控制台
        log_dir: 日志目录，文件按天命名并自动切换
        retention_days: 历史日志保留天数，None 时读环境变量（默认不清理）

    Returns:
        配置好的logger对象
    """
    logger = logging.getLogger('MARS')
    logger.setLevel(level)
    logger.propagate = False

    # 清除已有处理器（重复初始化时先关闭旧文件句柄）
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = LogFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    if console:
        console_handler = _create_console_handler(level, formatter)
        if console_handler is not None:
            logger.addHandler(console_handler)

    if log_dir:
        resolved = _resolve_log_dir(log_dir)
        if resolved is not None:
            keep_days = _retention_days() if retention_days is None else retention_days
            _cleanup_old_logs(resolved, keep_days)
            file_handler = DailyFileHandler(resolved)
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    elif log_file:
        parent = os.path.dirname(os.path.abspath(log_file))
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                pass
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            pass

    return logger


def get_logger(name: str = 'MARS') -> logging.Logger:
    """获取logger，子logger会继承父logger的handlers"""
    logger = logging.getLogger(f'MARS.{name}')
    logger.propagate = True
    return logger


# 默认日志配置
_default_logger: Optional[logging.Logger] = None

# 崩溃兜底状态
_crash_hooks_installed = False
_fault_file = None
_original_excepthook = sys.excepthook


def _default_log_dir() -> str:
    """默认日志目录：源码运行时是 src/logs，打包运行时是 exe 同级的 logs。"""
    try:
        from .path_utils import get_runtime_root
        return os.path.join(get_runtime_root(), 'logs')
    except Exception:
        return os.path.join(os.getcwd(), 'logs')


def init_logging(log_dir: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    """
    初始化默认日志系统

    Args:
        log_dir: 日志目录，None 时使用运行时默认目录
        level: 日志级别

    Returns:
        配置好的logger
    """
    global _default_logger

    _default_logger = setup_logging(
        level=level,
        log_dir=log_dir or _default_log_dir(),
        console=True
    )

    return _default_logger


def get_default_logger() -> logging.Logger:
    """获取默认logger"""
    global _default_logger
    if _default_logger is None:
        _default_logger = init_logging()
    return _default_logger


def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    """主线程未捕获异常：写日志后仍交给原始 hook（打包版会弹错误提示）。"""
    if issubclass(exc_type, KeyboardInterrupt):
        _original_excepthook(exc_type, exc_value, exc_tb)
        return
    try:
        get_logger('Crash').critical('未捕获异常', exc_info=(exc_type, exc_value, exc_tb))
    finally:
        _original_excepthook(exc_type, exc_value, exc_tb)


def _log_thread_exception(args) -> None:
    """子线程未捕获异常：写进日志文件，默认实现只会打到 stderr。"""
    if issubclass(args.exc_type, SystemExit):
        return
    thread_name = args.thread.name if args.thread is not None else 'unknown'
    get_logger('Crash').critical(
        f'线程 {thread_name} 未捕获异常',
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
    )


def _release_fault_file() -> None:
    global _fault_file
    try:
        faulthandler.disable()
    except Exception:
        pass
    if _fault_file is not None:
        try:
            _fault_file.close()
        except Exception:
            pass
        _fault_file = None


def install_crash_handlers(logger: Optional[logging.Logger] = None) -> None:
    """安装崩溃兜底：未捕获异常、子线程异常、原生崩溃都写进当天日志。"""
    global _crash_hooks_installed, _fault_file

    if _crash_hooks_installed:
        return
    _crash_hooks_installed = True

    logger = logger or get_default_logger()
    sys.excepthook = _log_uncaught_exception
    threading.excepthook = _log_thread_exception

    log_path = None
    for handler in logger.handlers:
        if isinstance(handler, DailyFileHandler):
            log_path = handler.current_path
            break
    if log_path is None or _fault_file is not None:
        return

    try:
        # 追加模式单独开一个句柄给 faulthandler：段错误时由 C 层直接写入，
        # 不经过 logging 的锁和缓冲。
        _fault_file = open(log_path, 'a', encoding='utf-8', errors='replace')
        faulthandler.enable(file=_fault_file, all_threads=True)
        atexit.register(_release_fault_file)
    except Exception:
        _fault_file = None
