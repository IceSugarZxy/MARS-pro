# -*- coding: utf-8 -*-
"""
串口通信模块 - 优化版本
实现串口的连接、断开、发送和接收功能
"""
from typing import Optional
import queue

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtSerialPort import QSerialPort

from .logger import get_logger
from .config_manager import get_config_manager

logger = get_logger('SerialManager')


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
        self.config = get_config_manager()

        logger.debug("SerialManager 初始化完成")

    def connect_serial(
        self,
        port: str,
        baudrate: str = "921600",
        bytesize: str = "8",
        stopbits: str = "1",
        parity: str = "无"
    ) -> bool:
        """连接串口"""
        try:
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
            self.serial_port.setBaudRate(int(baudrate))

            # 数据位
            data_bits_map = {
                "5": QSerialPort.Data5,
                "6": QSerialPort.Data6,
                "7": QSerialPort.Data7,
                "8": QSerialPort.Data8,
            }
            self.serial_port.setDataBits(data_bits_map.get(bytesize, QSerialPort.Data8))

            # 停止位
            stop_bits_map = {
                "1": QSerialPort.OneStop,
                "1.5": QSerialPort.OneAndHalfStop,
                "2": QSerialPort.TwoStop,
            }
            self.serial_port.setStopBits(stop_bits_map.get(stopbits, QSerialPort.OneStop))

            # 校验位
            parity_map = {
                "无": QSerialPort.NoParity,
                "奇校验": QSerialPort.OddParity,
                "偶校验": QSerialPort.EvenParity,
                "标记": QSerialPort.MarkParity,
                "空格": QSerialPort.SpaceParity,
            }
            self.serial_port.setParity(parity_map.get(parity, QSerialPort.NoParity))

            # 硬件流控
            self.serial_port.setFlowControl(QSerialPort.HardwareControl)

            if self.serial_port.open(QSerialPort.ReadWrite):
                self.is_connected = True

                # 启动定时器
                if not self.timer:
                    self.timer = QTimer()
                    self.timer.setInterval(10)
                    self.timer.timeout.connect(self._process_io)
                self.timer.start()

                self.signal_connection_status_changed.emit(True)
                logger.info(f"串口连接成功: {port} @ {baudrate}bps")
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
                    self.serial_port.flush()  # 刷新缓冲区
                    self.serial_port.close()
                # 使用deleteLater确保对象被彻底清理
                self.serial_port.deleteLater()
                self.serial_port = None
                logger.debug("QSerialPort已标记删除")
            except Exception as e:
                logger.error(f"断开串口失败: {e}")

        self.is_connected = False
        self.signal_connection_status_changed.emit(False)
        logger.info("串口已断开")

    def _process_io(self) -> None:
        """处理读写操作"""
        self.write_data()
        self.read_data()

    def write_data(self) -> None:
        """处理写队列中的数据"""
        if not self.is_connected or not self.serial_port:
            return

        try:
            if not self.serial_port.isOpen():
                return
        except RuntimeError:
            logger.warning("QSerialPort对象已被删除，重置连接状态")
            self.serial_port = None
            self.is_connected = False
            return

        try:
            while not self.write_queue.empty():
                if self.serial_port.bytesToWrite() > 512:
                    logger.debug("硬件缓冲区已满，暂停发送")
                    break

                data = self.write_queue.get_nowait()
                if isinstance(data, str):
                    data = data.encode('utf-8')

                result = self.serial_port.write(data)
                logger.debug(f"SerialManager: 发送数据, 长度={result}")

        except Exception as e:
            logger.error(f"处理写队列失败: {e}")

    def read_data(self) -> None:
        """读取串口数据"""
        if not self.is_connected or not self.serial_port:
            return

        try:
            if not self.serial_port.isOpen():
                return
        except RuntimeError:
            logger.warning("QSerialPort对象已被删除，重置连接状态")
            self.serial_port = None
            self.is_connected = False
            return

        try:
            bytes_available = self.serial_port.bytesAvailable()
            if bytes_available > 0:
                data = self.serial_port.read(bytes_available)
                if data:
                    logger.debug(f"SerialManager: 收到串口数据, 长度={len(data)}")
                    self.data_queue.put(data)
                    self.signal_data_received.emit(data)
            else:
                logger.debug(f"SerialManager: 轮询串口, bytesAvailable=0")

        except Exception as e:
            logger.error(f"读取数据失败: {e}")

    def start(self) -> None:
        """启动串口管理器"""
        self.running = True
        logger.debug("串口管理器已启动")

    def stop(self) -> None:
        """停止串口管理器"""
        self.running = False
        self.disconnect_serial()
        logger.debug("串口管理器已停止")

    def get_connection_status(self) -> bool:
        """获取连接状态"""
        return self.is_connected
