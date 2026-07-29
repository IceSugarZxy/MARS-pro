# -*- coding: utf-8 -*-
"""
串口通信模块 - 优化版本
实现串口的连接、断开、发送和接收功能
"""
from typing import Optional
import queue
import time

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtSerialPort import QSerialPort

from .logger import get_logger

logger = get_logger('SerialManager')

SERIAL_WRITE_INTERVAL_SECONDS = 0.02
SERIAL_WRITE_DRAIN_TIMEOUT_MS = 50
SERIAL_LOG_PREVIEW_LIMIT = 180
SERIAL_BINARY_RX_SUMMARY_SECONDS = 1.0
SERIAL_LIGHT_ADC_RX_SUMMARY_SECONDS = 2.0
SERIAL_UI_RX_EMIT_INTERVAL_MS = 120
SERIAL_UI_RX_BUFFER_FLUSH_BYTES = 4096
SERIAL_BAUDRATE = 115200


class SerialManager(QObject):
    """串口管理器"""

    # 信号定义
    signal_data_received = pyqtSignal(bytes)
    signal_connection_status_changed = pyqtSignal(bool)

    def __init__(self, read_queue: queue.Queue, write_queue: queue.Queue, thread_manager=None):
        super().__init__()
        self.serial_port: Optional[QSerialPort] = None
        self.is_connected = False
        self.running = False
        self.data_queue = read_queue
        self.write_queue = write_queue
        self.thread_manager = thread_manager
        self.timer: Optional[QTimer] = None
        self.connection_check_timer: Optional[QTimer] = None
        self._ui_rx_emit_timer: Optional[QTimer] = None
        self._pending_write_item = None
        self._last_write_time = 0.0
        self._binary_rx_bytes = 0
        self._binary_rx_chunks = 0
        self._last_binary_rx_log_time = time.time()
        self._active_tx_meta = None
        self._light_adc_rx_bytes = 0
        self._light_adc_rx_chunks = 0
        self._last_light_adc_rx_log_time = time.time()
        self._ui_rx_buffer = bytearray()

        logger.info("SerialManager 初始化完成")

    @staticmethod
    def _normalize_serial_value(value: str, default: str) -> str:
        text = str(value or default).strip().strip('"').strip("'")
        return text or default

    @staticmethod
    def _coerce_payload(data) -> bytes:
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, str):
            return data.encode("utf-8")
        return bytes(data)

    @classmethod
    def _item_payload(cls, item) -> bytes:
        if isinstance(item, dict):
            return cls._coerce_payload(item.get("data", b""))
        return cls._coerce_payload(item)

    @staticmethod
    def _is_mostly_printable(data: bytes) -> bool:
        if not data:
            return True
        printable = sum(1 for b in data if b in (9, 10, 13) or 32 <= b <= 126)
        return printable / len(data) >= 0.85

    @staticmethod
    def _payload_preview(data: bytes, limit: int = SERIAL_LOG_PREVIEW_LIMIT) -> str:
        text = data.decode("utf-8", errors="replace")
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    def _queue_ui_rx_payload(self, payload: bytes) -> None:
        self._ui_rx_buffer.extend(payload)
        if len(self._ui_rx_buffer) >= SERIAL_UI_RX_BUFFER_FLUSH_BYTES:
            self._flush_ui_rx_buffer()

    def _flush_ui_rx_buffer(self) -> None:
        if not self._ui_rx_buffer:
            return
        payload = bytes(self._ui_rx_buffer)
        self._ui_rx_buffer.clear()
        self.signal_data_received.emit(payload)

    def _log_rx_payload(self, payload: bytes) -> None:
        """记录串口接收数据：开头内容（hex）+ 长度（INFO 级别，便于排查丢数据）"""
        preview_len = min(16, len(payload))
        hex_preview = payload[:preview_len].hex(' ')
        ascii_preview = ''.join(chr(b) if 32 <= b < 127 else '.' for b in payload[:preview_len])
        # 首字节 > 127 为二进制数据，用 INFO；ASCII 文本用 DEBUG
        is_binary = len(payload) > 0 and payload[0] > 127
        log_fn = logger.info if is_binary else logger.debug
        log_fn(
            f"Serial RX: {len(payload)}B | {hex_preview} | {ascii_preview} | q={self.data_queue.qsize()}"
        )

        if not self._is_mostly_printable(payload):
            self._binary_rx_bytes += len(payload)
            self._binary_rx_chunks += 1
            now = time.time()
            if now - self._last_binary_rx_log_time >= SERIAL_BINARY_RX_SUMMARY_SECONDS:
                logger.debug(
                    "Serial RX binary summary: "
                    f"chunks={self._binary_rx_chunks}, bytes={self._binary_rx_bytes}, "
                    f"queue_size={self.data_queue.qsize()}"
                )
                self._binary_rx_bytes = 0
                self._binary_rx_chunks = 0
                self._last_binary_rx_log_time = now
            return

        text = payload.decode("utf-8", errors="replace")
        preview = self._payload_preview(payload)
        if "Self Detect" in text or "Finished" in text:
            logger.info(
                "Serial RX event: "
                f"bytes={len(payload)}, queue_size={self.data_queue.qsize()}, preview={preview}"
            )
        elif text.lstrip().startswith("X:"):
            logger.debug(
                "Serial RX position: "
                f"bytes={len(payload)}, queue_size={self.data_queue.qsize()}, preview={preview}"
            )
        else:
            logger.debug(
                "Serial RX text: "
                f"bytes={len(payload)}, queue_size={self.data_queue.qsize()}, preview={preview}"
            )

    def drop_pending_writes(self, command_prefix: str, reason: str = "") -> int:
        kept = []
        dropped = 0
        prefix = command_prefix.encode("utf-8")

        while True:
            try:
                item = self.write_queue.get_nowait()
            except queue.Empty:
                break

            try:
                payload = self._item_payload(item)
            except Exception:
                kept.append(item)
                continue

            if payload.startswith(prefix):
                dropped += 1
            else:
                kept.append(item)

        for item in kept:
            self.write_queue.put(item)

        if dropped:
            logger.info(
                "Serial TX queue drop: "
                f"prefix={command_prefix}, dropped={dropped}, kept={len(kept)}, "
                f"queue_size={self.write_queue.qsize()}, reason={reason}"
            )
        return dropped

    def connect_serial(
        self,
        port: str,
    ) -> bool:
        """连接串口"""
        try:
            port = self._normalize_serial_value(port, "")

            if self.serial_port:
                try:
                    if self.serial_port.isOpen():
                        self.serial_port.flush()
                        self.serial_port.close()
                    self.serial_port.deleteLater()
                except Exception:
                    pass
                self.serial_port = None

            self.serial_port = QSerialPort()
            self.serial_port.setPortName(port)
            self.serial_port.setBaudRate(SERIAL_BAUDRATE)
            self.serial_port.setDataBits(QSerialPort.Data8)
            self.serial_port.setStopBits(QSerialPort.OneStop)
            self.serial_port.setParity(QSerialPort.NoParity)
            self.serial_port.setFlowControl(QSerialPort.NoFlowControl)

            # 连接 readyRead 信号到数据接收处理（高频接收）
            self.serial_port.readyRead.connect(self._on_ready_read)
            self.serial_port.bytesWritten.connect(self._on_bytes_written)
            if hasattr(self.serial_port, "errorOccurred"):
                self.serial_port.errorOccurred.connect(self._on_error_occurred)

            if self.serial_port.open(QSerialPort.ReadWrite):
                self.is_connected = True

                # 启动写定时器（发信及时）
                if not self.timer:
                    self.timer = QTimer()
                    self.timer.setInterval(5)  # Fast poll; actual writes are paced below.
                    self.timer.timeout.connect(self._process_write)
                self.timer.start()

                if not self._ui_rx_emit_timer:
                    self._ui_rx_emit_timer = QTimer()
                    self._ui_rx_emit_timer.setInterval(SERIAL_UI_RX_EMIT_INTERVAL_MS)
                    self._ui_rx_emit_timer.timeout.connect(self._flush_ui_rx_buffer)
                self._ui_rx_emit_timer.start()

                # 启动连接状态检查定时器
                if not self.connection_check_timer:
                    self.connection_check_timer = QTimer()
                    self.connection_check_timer.setInterval(500)  # 每 0.5s 检查
                    self.connection_check_timer.timeout.connect(self._check_connection_status)
                self.connection_check_timer.start()

                self.signal_connection_status_changed.emit(True)
                logger.info(f"串口连接成功: {port}")
                return True
            else:
                logger.error(f"打开串口失败: {port}")
                self.is_connected = False
                return False

        except Exception as e:
            logger.error(f"连接串口失败: {e}")
            self.is_connected = False
            return False

    def disconnect_serial(self) -> None:
        """断开串口连接"""
        if self.timer and self.timer.isActive():
            self.timer.stop()

        if self.connection_check_timer and self.connection_check_timer.isActive():
            self.connection_check_timer.stop()

        if self._ui_rx_emit_timer and self._ui_rx_emit_timer.isActive():
            self._flush_ui_rx_buffer()
            self._ui_rx_emit_timer.stop()

        # 停止位置查询定时器
        if self.thread_manager:
            if hasattr(self.thread_manager, 'serial_command') and self.thread_manager.serial_command:
                self.thread_manager.serial_command.disable_position_query_timer()

        if self.serial_port:
            try:
                if self.serial_port.isOpen():
                    try:
                        self.serial_port.readyRead.disconnect()
                    except Exception:
                        pass  # 信号可能未连接
                    try:
                        self.serial_port.bytesWritten.disconnect()
                    except Exception:
                        pass
                    try:
                        if hasattr(self.serial_port, "errorOccurred"):
                            self.serial_port.errorOccurred.disconnect()
                    except Exception:
                        pass
                    self.serial_port.flush()  # 刷新缓冲区
                    self.serial_port.close()
                # 使用deleteLater确保对象被彻底清理
                self.serial_port.deleteLater()
                self.serial_port = None
            except Exception as e:
                logger.error(f"断开串口失败: {e}")

        self.is_connected = False
        self.signal_connection_status_changed.emit(False)
        logger.info("串口已断开")

    def flush_write_queue(self) -> int:
        """
        同步清空写队列，将所有待发指令立即写入串口。
        返回写入的指令数。用于测量等关键操作前确保 B~ 等指令已实际发出。
        """
        if not self.is_connected or not self.serial_port:
            return 0

        flushed = 0
        try:
            while True:
                # 处理滞留的分片写入
                if self._pending_write_item is not None:
                    item = self._pending_write_item
                    self._pending_write_item = None
                else:
                    try:
                        item = self.write_queue.get_nowait()
                    except queue.Empty:
                        break

                if isinstance(item, dict):
                    data = self._coerce_payload(item.get("data", b""))
                    tx_id = item.get("id")
                    source = item.get("source", "")
                else:
                    data = self._coerce_payload(item)
                    tx_id = None
                    source = "raw_queue"

                if not data:
                    continue

                written = self.serial_port.write(data)
                self.serial_port.flush()
                self._last_write_time = time.monotonic()
                flushed += 1
                logger.info(
                    f"Serial TX flush: id={tx_id}, source={source}, "
                    f"bytes={len(data)}, written={written}, "
                    f"preview={self._payload_preview(data)}"
                )

                if written < len(data):
                    remaining = data[int(written):]
                    self._pending_write_item = {
                        "id": tx_id,
                        "source": f"{source}:partial",
                        "data": remaining,
                        "enqueued_at": time.time(),
                    }
                    logger.warning(
                        f"Serial TX flush partial: written={written}/{len(data)}, "
                        f"remaining={len(remaining)}"
                    )

        except Exception as e:
            logger.error(f"flush_write_queue 失败: {e}")

        if flushed > 0:
            logger.info(f"Write queue flushed: {flushed} commands sent synchronously")
        return flushed

    def _process_write(self) -> None:
        """处理写队列（发信及时）"""
        if not self.is_connected or not self.serial_port:
            return

        try:
            if not self.serial_port.isOpen():
                return
        except RuntimeError:
            logger.warning("QSerialPort对象已被删除")
            self.serial_port = None
            self.is_connected = False
            return

        try:
            now = time.monotonic()
            if now - self._last_write_time < SERIAL_WRITE_INTERVAL_SECONDS:
                return

            if self.serial_port.bytesToWrite() > 0:
                return

            if self._pending_write_item is not None:
                item = self._pending_write_item
                self._pending_write_item = None
            else:
                try:
                    item = self.write_queue.get_nowait()
                except queue.Empty:
                    return

            if isinstance(item, dict):
                tx_id = item.get("id")
                source = item.get("source", "")
                enqueued_at = item.get("enqueued_at")
                data = self._coerce_payload(item.get("data", b""))
            else:
                tx_id = None
                source = "raw_queue"
                enqueued_at = None
                data = self._coerce_payload(item)

            if not data:
                logger.warning(f"Serial TX skipped empty payload: id={tx_id}, source={source}")
                return

            tx_meta = {
                "id": tx_id,
                "source": source,
                "bytes": len(data),
                "preview": self._payload_preview(data),
                "write_started_at": time.time(),
            }
            self._active_tx_meta = tx_meta

            written = self.serial_port.write(data)
            flush_result = self.serial_port.flush()
            self._last_write_time = now
            latency_ms = (time.time() - enqueued_at) * 1000 if enqueued_at else None

            if written < 0:
                self._active_tx_meta = None
                logger.error(
                    "Serial TX failed: "
                    f"id={tx_id}, source={source}, bytes={len(data)}, "
                    f"error={self.serial_port.errorString()}, preview={self._payload_preview(data)}"
                )
                return

            if written < len(data):
                remaining = data[int(written):]
                self._pending_write_item = {
                    "id": tx_id,
                    "source": f"{source}:partial",
                    "data": remaining,
                    "enqueued_at": time.time(),
                }
                logger.warning(
                    "Serial TX partial: "
                    f"id={tx_id}, source={source}, written={written}/{len(data)}, "
                    f"remaining={len(remaining)}, preview={self._payload_preview(data)}"
                )
            else:
                bytes_to_write_before_wait = self.serial_port.bytesToWrite()
                drain_wait_result = None
                if bytes_to_write_before_wait > 0:
                    drain_wait_result = self.serial_port.waitForBytesWritten(SERIAL_WRITE_DRAIN_TIMEOUT_MS)
                bytes_to_write_after_wait = self.serial_port.bytesToWrite()
                latency_text = f"{latency_ms:.1f}ms" if latency_ms is not None else "n/a"
                tx_log = logger.debug
                tx_log(
                    "Serial TX write: "
                    f"id={tx_id}, source={source}, bytes={written}, "
                    f"queue_remaining={self.write_queue.qsize()}, latency={latency_text}, "
                    f"preview={self._payload_preview(data)}"
                )
                wait_text = "n/a" if drain_wait_result is None else str(drain_wait_result)
                drain_logger = logger.debug if bytes_to_write_after_wait == 0 else logger.warning
                drain_logger(
                    "Serial TX drain: "
                    f"id={tx_id}, source={source}, flush_result={flush_result}, "
                    f"wait_result={wait_text}, bytes_to_write_before={bytes_to_write_before_wait}, "
                    f"bytes_to_write_after={bytes_to_write_after_wait}, "
                    f"error={self.serial_port.errorString()}, preview={self._payload_preview(data)}"
                )
                if bytes_to_write_after_wait > 0:
                    try:
                        self.serial_port.clear(QSerialPort.Output)
                        logger.warning("Serial TX output buffer force-cleared after drain failure")
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"处理写队列失败: {e}", exc_info=True)

    def _on_bytes_written(self, byte_count: int) -> None:
        meta = self._active_tx_meta or {}
        started_at = meta.get("write_started_at")
        elapsed_text = "n/a"
        if started_at:
            elapsed_text = f"{(time.time() - started_at) * 1000:.1f}ms"

        bytes_to_write = "n/a"
        try:
            if self.serial_port:
                bytes_to_write = self.serial_port.bytesToWrite()
        except Exception:
            pass

        logger.debug(
            "Serial TX bytesWritten: "
            f"id={meta.get('id')}, source={meta.get('source')}, bytes={byte_count}, "
            f"bytes_to_write={bytes_to_write}, elapsed={elapsed_text}, "
            f"preview={meta.get('preview')}"
        )

    def _on_error_occurred(self, error) -> None:
        if error == QSerialPort.NoError:
            return

        # 硬件移除直接触发断连处理
        if error in (QSerialPort.ResourceError,):
            logger.warning(f"Serial resource error (device removed)")
            self._handle_connection_lost()
            return

        meta = self._active_tx_meta or {}
        error_code = error
        try:
            error_code = int(error)
        except Exception:
            pass

        bytes_to_write = "n/a"
        error_string = ""
        try:
            if self.serial_port:
                bytes_to_write = self.serial_port.bytesToWrite()
                error_string = self.serial_port.errorString()
        except Exception:
            pass

        logger.error(
            "Serial errorOccurred: "
            f"error={error_code}, error_string={error_string}, "
            f"last_tx_id={meta.get('id')}, last_tx_source={meta.get('source')}, "
            f"bytes_to_write={bytes_to_write}, last_tx_preview={meta.get('preview')}"
        )

        # 错误恢复：清空TX缓冲区，重置写状态，防止后续写入永久阻塞
        try:
            if self.serial_port and self.serial_port.bytesToWrite() > 0:
                self.serial_port.clear(QSerialPort.Output)
                logger.warning("Serial TX buffer cleared after error")
        except Exception:
            pass
        self._active_tx_meta = None
        self._pending_write_item = None

    def _on_ready_read(self) -> None:
        """串口数据到达（高频接收）"""
        if not self.is_connected or not self.serial_port:
            return

        try:
            while self.serial_port.bytesAvailable() > 0:
                data = self.serial_port.read(1024)  # 每次最多读1KB
                if not data:
                    continue

                payload = self._coerce_payload(data)
                self.data_queue.put(payload)
                self._queue_ui_rx_payload(payload)
                self._log_rx_payload(payload)

        except RuntimeError:
            logger.warning("QSerialPort读取异常")
            self.serial_port = None
            self.is_connected = False
            self.signal_connection_status_changed.emit(False)
        except Exception as e:
            logger.error(f"读取数据失败: {e}")

    def _check_connection_status(self) -> None:
        """检查串口连接状态"""
        if not self.is_connected:
            return

        try:
            if self.serial_port is None:
                self._handle_connection_lost()
                return

            if not self.serial_port.isOpen():
                self._handle_connection_lost()
                return

            # 检查端口错误状态（物理断开时 errorString 非空或 error 非 NoError）
            if self.serial_port.error() != QSerialPort.NoError:
                err_str = self.serial_port.errorString()
                logger.warning(f"串口错误: {err_str}")
                self._handle_connection_lost()
                return

        except Exception as e:
            logger.warning(f"检查连接状态异常: {e}")
            self._handle_connection_lost()

    def _handle_connection_lost(self) -> None:
        """处理连接丢失"""
        if not self.is_connected:
            return  # 避免重复处理

        logger.warning("串口连接丢失")
        self.is_connected = False

        if self.connection_check_timer and self.connection_check_timer.isActive():
            self.connection_check_timer.stop()

        if self.timer and self.timer.isActive():
            self.timer.stop()

        if self._ui_rx_emit_timer and self._ui_rx_emit_timer.isActive():
            self._flush_ui_rx_buffer()
            self._ui_rx_emit_timer.stop()

        if self.serial_port:
            try:
                if self.serial_port.isOpen():
                    self.serial_port.close()
                self.serial_port.deleteLater()
                self.serial_port = None
            except Exception:
                pass

        self.signal_connection_status_changed.emit(False)
        logger.info("连接丢失信号已发送")

    def start(self) -> None:
        """启动串口管理器"""
        self.running = True

    def stop(self) -> None:
        """停止串口管理器"""
        self.running = False
        self.disconnect_serial()

    def get_connection_status(self) -> bool:
        """获取连接状态"""
        return self.is_connected
