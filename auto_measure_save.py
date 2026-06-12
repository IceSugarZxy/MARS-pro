# -*- coding: utf-8 -*-
"""
Automated repeated measurement entry point.

This script starts the normal MARS application, waits for the serial port to be
connected, then repeats:

1. start rotation measurement
2. wait until measurement data has been processed and analyzed
3. save plot data
4. wait for a configured delay
5. start the next measurement

Run from the project root, for example:
    python auto_measure_save.py --count 10 --delay 3
"""

import argparse
import os
import sys
import time

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSlot
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_DIR, "src")
sys.path.insert(0, SRC_DIR)

from core import get_logger  # noqa: E402
from main import MainApplication, application_path  # noqa: E402


class AutoMeasureSaveRunner(QObject):
    def __init__(
        self,
        main_app: MainApplication,
        count: int,
        delay_seconds: float,
        serial_wait_seconds: float,
        measure_timeout_seconds: float,
        save_delay_seconds: float,
        quit_when_done: bool,
    ):
        super().__init__()
        self.main_app = main_app
        self.measure_panel = main_app.main_panel.get_panel("measure")
        self.thread_manager = main_app.thread_manager
        self.count = count
        self.delay_ms = int(delay_seconds * 1000)
        self.serial_wait_ms = int(serial_wait_seconds * 1000)
        self.measure_timeout_ms = int(measure_timeout_seconds * 1000)
        self.save_delay_ms = int(save_delay_seconds * 1000)
        self.quit_when_done = quit_when_done

        self.logger = get_logger("AutoMeasureSave")
        self.started_count = 0
        self.saved_count = 0
        self.failed_count = 0
        self.waiting_for_analysis = False
        self.current_cycle = 0
        self.serial_wait_started_at = time.monotonic()

        self.thread_manager.data_process.signal_measure_analysis_finished.connect(
            self._on_measure_analysis_finished,
            Qt.QueuedConnection,
        )

    def start(self):
        self.logger.info(
            "Auto measure/save started: "
            f"count={self.count or 'infinite'}, delay_ms={self.delay_ms}, "
            f"serial_wait_ms={self.serial_wait_ms}, "
            f"measure_timeout_ms={self.measure_timeout_ms}, "
            f"save_delay_ms={self.save_delay_ms}"
        )
        QTimer.singleShot(500, self._wait_for_serial_and_start)

    def _is_serial_connected(self) -> bool:
        serial_manager = self.thread_manager.serial_manager
        return bool(serial_manager and serial_manager.get_connection_status())

    def _wait_for_serial_and_start(self):
        if self._is_serial_connected():
            self.logger.info("Serial connected; starting automatic measurement loop.")
            self._start_next_measurement()
            return

        elapsed_ms = int((time.monotonic() - self.serial_wait_started_at) * 1000)
        if elapsed_ms >= self.serial_wait_ms:
            self.logger.error("Serial connection timeout; automatic loop aborted.")
            self._finish()
            return

        self.logger.info("Waiting for serial connection...")
        QTimer.singleShot(1000, self._wait_for_serial_and_start)

    def _start_next_measurement(self):
        if self.count > 0 and self.started_count >= self.count:
            self.logger.info(
                f"Automatic loop finished: started={self.started_count}, "
                f"saved={self.saved_count}, failed={self.failed_count}"
            )
            self._finish()
            return

        if self.measure_panel.is_testing:
            self.logger.info("Measure panel is still testing; retry start shortly.")
            QTimer.singleShot(500, self._start_next_measurement)
            return

        if not self._is_serial_connected():
            self.logger.error("Serial disconnected before next measurement; automatic loop aborted.")
            self.failed_count += 1
            self._finish()
            return

        self.started_count += 1
        self.current_cycle = self.started_count
        self.waiting_for_analysis = True
        self.logger.info(f"Automatic cycle {self.current_cycle}: start measurement.")

        self.measure_panel._start_rotation_button_clicked()
        if not self.measure_panel.is_testing:
            self.waiting_for_analysis = False
            self.failed_count += 1
            self.logger.error(f"Automatic cycle {self.current_cycle}: measurement did not start.")
            self._finish()
            return

        QTimer.singleShot(self.measure_timeout_ms, self._on_measure_timeout)

    def _on_measure_timeout(self):
        if not self.waiting_for_analysis:
            return

        self.waiting_for_analysis = False
        self.failed_count += 1
        self.logger.error(f"Automatic cycle {self.current_cycle}: measurement timeout.")
        self.measure_panel._stop_rotation_button_clicked()
        self._finish()

    @pyqtSlot(object, object, object)
    def _on_measure_analysis_finished(self, angle_data, mag_data, analysis_results):
        if not self.waiting_for_analysis:
            return

        self.waiting_for_analysis = False
        self.logger.info(
            f"Automatic cycle {self.current_cycle}: analysis finished, "
            f"points={len(angle_data or [])}, has_results={bool(analysis_results)}"
        )
        QTimer.singleShot(self.save_delay_ms, self._save_after_panel_update)

    def _save_after_panel_update(self):
        if self.measure_panel.is_testing:
            QTimer.singleShot(200, self._save_after_panel_update)
            return

        if not self.measure_panel.angle_data or not self.measure_panel.mag_data:
            self.failed_count += 1
            self.logger.error(f"Automatic cycle {self.current_cycle}: no processed data to save.")
            QTimer.singleShot(self.delay_ms, self._start_next_measurement)
            return

        self.logger.info(f"Automatic cycle {self.current_cycle}: saving data.")
        success = self.measure_panel.save_plot_data()
        if success:
            self.saved_count += 1
            self.measure_panel._update_status("自动测量：数据保存成功", auto_recover=True)
            self.logger.info(
                f"Automatic cycle {self.current_cycle}: save success; "
                f"waiting {self.delay_ms} ms before next cycle."
            )
        else:
            self.failed_count += 1
            self.measure_panel._update_status("自动测量：数据保存失败", is_error=True, auto_recover=True)
            self.logger.error(
                f"Automatic cycle {self.current_cycle}: save failed; "
                f"waiting {self.delay_ms} ms before next cycle."
            )

        QTimer.singleShot(self.delay_ms, self._start_next_measurement)

    def _finish(self):
        if self.quit_when_done:
            QApplication.instance().quit()


def parse_args():
    parser = argparse.ArgumentParser(description="Automatically repeat MARS measurement and save data.")
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of cycles to run. Use 0 for infinite loop. Default: 0.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Seconds to wait after each save before starting the next measurement. Default: 3.",
    )
    parser.add_argument(
        "--serial-wait",
        type=float,
        default=30.0,
        help="Maximum seconds to wait for automatic serial connection. Default: 30.",
    )
    parser.add_argument(
        "--measure-timeout",
        type=float,
        default=180.0,
        help="Maximum seconds to wait for one measurement to finish. Default: 180.",
    )
    parser.add_argument(
        "--save-delay",
        type=float,
        default=0.5,
        help="Seconds to wait after the analysis signal before saving. Default: 0.5.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the application open after the requested cycles finish.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    app = QApplication(sys.argv)
    icon_path = os.path.join(application_path, "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    app.setApplicationName("MARS Auto Measure Save")
    app.setApplicationVersion("2.0.0")
    app.setStyle("Fusion")

    main_app = MainApplication()
    if not main_app.initialize():
        return 1

    main_app.main_panel.setWindowFlags(Qt.FramelessWindowHint)
    main_app.main_panel.showMaximized()

    runner = AutoMeasureSaveRunner(
        main_app=main_app,
        count=args.count,
        delay_seconds=args.delay,
        serial_wait_seconds=args.serial_wait,
        measure_timeout_seconds=args.measure_timeout,
        save_delay_seconds=args.save_delay,
        quit_when_done=not args.keep_open,
    )
    runner.start()

    exit_code = app.exec_()
    main_app.cleanup()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
