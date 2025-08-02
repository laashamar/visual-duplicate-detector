# duplicate_gui.py

import sys
import os
import multiprocessing
import logging
import time
from datetime import datetime

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QFileDialog,
    QVBoxLayout, QGraphicsDropShadowEffect, QMessageBox
)
from PySide6.QtGui import QColor
from config import TARGET_BASE_DIR
from workers import DuplicateChecker, ActionWorker
import styles

from logger_setup import setup_global_logger
from performance_logger import PerformanceLogger
from ui_panels import SettingsPanel, StatusPanel
from review_dialog import ReviewDialog
from automatic_selector import SelectionStrategy


class DuplicateWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Duplicate Detection – Group Based")
        self.setMinimumSize(900, 700)

        # --- Instance variables ---
        self.folder_path = None
        self.check_thread = None
        self.action_thread = None
        self.performance_logger = PerformanceLogger()
        self.active_run_stats = {}
        self.start_time = 0
        self.all_file_data = {}
        self.all_groups = []
        self.files_for_manual_removal = set()

        self._setup_styles()
        self.build_ui()
        self.connect_signals()

        setup_global_logger()

        self.set_button_state(self.settings_panel.btn_folder, 'highlight')
        self.set_button_state(self.settings_panel.btn_start, 'disabled')
        self.settings_panel.remains_dest_path.setText(TARGET_BASE_DIR)
        self.on_mode_changed()
        self.update_threshold_info(5)

    def _setup_styles(self):
        self.COLORS = styles.get_colors()
        self.STYLES = {
            **styles.get_button_styles(self.COLORS),
            **styles.get_image_styles(self.COLORS)
        }
        self.setStyleSheet(styles.get_main_stylesheet(self.COLORS))

    def build_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 15, 15, 15)
        self.layout.setSpacing(10)

        self.settings_panel = SettingsPanel()
        self.status_panel = StatusPanel()

        self.layout.addWidget(self.settings_panel)
        self.layout.addWidget(self.status_panel)

    def connect_signals(self):
        self.settings_panel.btn_folder.clicked.connect(self.select_folder)
        self.settings_panel.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.settings_panel.slider_threshold.valueChanged.connect(self.update_threshold_info)
        self.settings_panel.btn_start.clicked.connect(self.start_duplicate_check)
        self.settings_panel.btn_select_remains_dest.clicked.connect(self.select_remains_destination)
        self.status_panel.btn_move_duplicates.clicked.connect(self.start_file_actions)

    def set_button_state(self, button, state):
        button.setStyleSheet(self.STYLES[state])
        button.setEnabled(state != 'disabled')
        if state == 'highlight':
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(self.COLORS['primary_shadow']))
            shadow.setOffset(0, 0)
            button.setGraphicsEffect(shadow)
        else:
            button.setGraphicsEffect(None)

    def on_mode_changed(self):
        is_auto = self.settings_panel.mode_combo.currentText() == "Automatic selection"
        self.settings_panel.strategy_label.setVisible(is_auto)
        self.settings_panel.strategy_combo.setVisible(is_auto)
        if not is_auto:
             self.settings_panel.chk_sort_into_folders.setVisible(False)
             self.settings_panel.remains_options_frame.setVisible(False)
        else:
            self.settings_panel.on_strategy_changed()

    def select_remains_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Destination for Remaining Files")
        if folder:
            self.settings_panel.remains_dest_path.setText(folder)

    def start_duplicate_check(self):
        if not self.folder_path:
            QMessageBox.warning(self, "Folder Missing", "Select a folder before starting.")
            return

        # Disable UI
        self.set_button_state(self.settings_panel.btn_start, 'disabled')
        self.set_button_state(self.settings_panel.btn_folder, 'disabled')
        self.set_button_state(self.status_panel.btn_move_duplicates, 'disabled')
        self.settings_panel.setEnabled(False)

        # Clear previous run data
        self.all_groups.clear()
        self.files_for_manual_removal.clear()
        self.status_panel.progress_bar.setValue(0)
        self.status_panel.log_window.clear()
        self.status_panel.scan_summary_label.setText("Scanning folder, please wait...")

        mode = self.settings_panel.mode_combo.currentText()
        strategy = self.settings_panel.strategy_combo.currentData(Qt.UserRole)
        threshold_value = self.settings_panel.slider_threshold.value()

        self.start_time = time.monotonic()
        self.active_run_stats = { "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "folder": self.folder_path }

        self.check_thread = QThread()
        self.duplicate_checker = DuplicateChecker(self.folder_path, threshold_value, mode, strategy)
        self.duplicate_checker.moveToThread(self.check_thread)

        self.duplicate_checker.scan_summary_ready.connect(self.display_scan_summary)
        self.duplicate_checker.download_progress.connect(self.handle_download_progress)
        self.duplicate_checker.progress_updated.connect(self.handle_progress_updated)
        self.duplicate_checker.error_occurred.connect(self.handle_check_error)

        if mode == "Manual review":
            self.duplicate_checker.manual_check_finished.connect(self.handle_manual_check_finished)
        else:
            self.duplicate_checker.automatic_selection_finished.connect(self.handle_automatic_selection_finished)
        
        self.duplicate_checker.finished.connect(self.check_thread.quit)
        self.check_thread.started.connect(self.duplicate_checker.run)
        self.check_thread.finished.connect(self.check_thread.deleteLater)
        self.check_thread.start()

    def handle_manual_check_finished(self, check_stats, all_file_data, groups):
        self.reactivate_ui_after_check()
        self.active_run_stats.update(check_stats)
        self.all_file_data = all_file_data
        self.all_groups = groups
        
        if self.all_groups:
            self.start_manual_review_session()
        else:
            QMessageBox.information(self, "No Duplicates", "Scan complete. No duplicate groups were found.")
            self.log_performance_if_finished()

    def handle_automatic_selection_finished(self, files_for_removal, files_to_sort, check_stats):
        self.reactivate_ui_after_check()
        self.active_run_stats.update(check_stats)
        
        # Store results for the action phase
        self.files_for_removal = files_for_removal
        self.files_to_sort = files_to_sort
        
        if not self.files_for_removal and not self.files_to_sort:
            QMessageBox.information(self, "No Duplicates", "Scan complete. No duplicates found to process.")
            self.log_performance_if_finished()
            return
            
        self.set_button_state(self.status_panel.btn_move_duplicates, 'highlight')
        QMessageBox.information(self, "Selection Complete", "Automatic selection is complete. Click 'Process Duplicates' to perform file actions.")

    def start_file_actions(self):
        """This single method now handles all automatic and manual file processing."""
        self.set_button_state(self.status_panel.btn_move_duplicates, 'disabled')

        # --- Build the configuration for the ActionWorker ---
        action_config = {}
        
        # Check if we are in the special sorting mode
        is_sorting_mode = (
            self.settings_panel.mode_combo.currentText() == "Automatic selection" and
            self.settings_panel.strategy_combo.currentData(Qt.UserRole) == SelectionStrategy.KEEP_ALL_UNIQUE_VERSIONS and
            self.settings_panel.chk_sort_into_folders.isChecked()
        )

        if is_sorting_mode:
            action_config['files_to_sort'] = self.files_to_sort
            action_config['base_sort_folder'] = self.folder_path
            action_config['remains_to_process'] = self.files_for_removal # In this mode, "removal" list is the "remains"
            
            if self.settings_panel.radio_recycle.isChecked():
                action_config['remains_action'] = 'recycle'
            else:
                action_config['remains_action'] = 'move'
                action_config['remains_dest_folder'] = self.settings_panel.remains_dest_path.text()
        else:
            # Standard removal process (from manual or other auto modes)
            files_to_process = self.files_for_manual_removal if self.settings_panel.mode_combo.currentText() == "Manual review" else self.files_for_removal
            action_config['remains_to_process'] = list(files_to_process)
            action_config['remains_action'] = 'move'
            action_config['remains_dest_folder'] = os.path.join(TARGET_BASE_DIR, "Duplicates")
            
        self.action_thread = QThread()
        self.action_worker = ActionWorker(action_config)
        self.action_worker.moveToThread(self.action_thread)

        self.action_worker.progress_log.connect(self.append_log_message)
        self.action_worker.finished.connect(self.handle_actions_finished)
        self.action_thread.started.connect(self.action_worker.run)
        self.action_thread.finished.connect(self.action_thread.quit)
        self.action_thread.finished.connect(self.action_thread.deleteLater)
        self.action_thread.start()

    def handle_actions_finished(self, message):
        QMessageBox.information(self, "Processing Complete", message)
        self.log_performance_if_finished()
        # Clear data for next run
        self.files_for_manual_removal.clear()
        self.files_for_removal = []
        self.files_to_sort = []

    def reactivate_ui_after_check(self):
        self.settings_panel.setEnabled(True)
        self.set_button_state(self.settings_panel.btn_folder, 'toned_down')
        if self.folder_path:
            self.set_button_state(self.settings_panel.btn_start, 'highlight')
        else:
            self.set_button_state(self.settings_panel.btn_start, 'disabled')

    # ... other methods like display_scan_summary, handle_download_progress, etc. remain the same ...
    # ... manual review methods like start_manual_review_session also remain the same ...

    def display_scan_summary(self, summary):
        total_files = summary.get('total_files', 0)
        image_files = summary.get('image_files', {})
        other_files = summary.get('other_files', {})
        total_images = sum(image_files.values())
        total_other = sum(other_files.values())
        html = f"<b>Folder analysis:</b><br>Total {total_files} files found.<hr>"
        if image_files:
            html += f"<b>Image files ({total_images}):</b><ul>" + "".join([f"<li>{ext.upper()}: {count}</li>" for ext, count in sorted(image_files.items())]) + "</ul>"
        if other_files:
            html += f"<b>Other files ({total_other}):</b><ul>" + "".join([f"<li>{ext.upper()}: {count}</li>" for ext, count in sorted(other_files.items())]) + "</ul>"
        self.status_panel.scan_summary_label.setText(html)

    def handle_download_progress(self, current, total):
        self.status_panel.status.setText(f"Downloading file {current} of {total} from the cloud...")
        self.status_panel.progress_bar.setValue(int(100 * (current / total)))

    def handle_check_error(self, error_message):
        QMessageBox.critical(self, "Error During Check", error_message)
        self.status_panel.status.setText("[ERROR] An error occurred. Check has been aborted.")
        self.reactivate_ui_after_check()

    def start_manual_review_session(self):
        self.current_group_index = 0
        self.process_next_group()

    def process_next_group(self):
        if not (0 <= self.current_group_index < len(self.all_groups)):
            self.status_panel.status.setText(f"[DONE] Finished reviewing all {len(self.all_groups)} groups.")
            if self.files_for_manual_removal:
                self.set_button_state(self.status_panel.btn_move_duplicates, 'highlight')
            else:
                QMessageBox.information(self, "Review Complete", "You finished without selecting any files for removal.")
                self.log_performance_if_finished()
            return
        active_group_paths = self.all_groups[self.current_group_index]
        dialog = ReviewDialog(self.all_file_data, self.STYLES, self)
        dialog.group_approved.connect(self.handle_group_approved)
        dialog.group_skipped.connect(self.handle_group_skipped)
        dialog.review_group(active_group_paths, self.current_group_index, len(self.all_groups))

    def handle_group_approved(self, path_to_keep):
        active_group = self.all_groups[self.current_group_index]
        for file_path in active_group:
            if file_path != path_to_keep:
                self.files_for_manual_removal.add(file_path)
        self.current_group_index += 1
        self.process_next_group()

    def handle_group_skipped(self):
        self.current_group_index += 1
        self.process_next_group()
        
    def log_performance_if_finished(self):
        if self.start_time > 0:
            total_time = time.monotonic() - self.start_time
            self.active_run_stats['total_time'] = total_time
            self.performance_logger.log_run(self.active_run_stats)
            self.start_time = 0

    def closeEvent(self, event):
        if self.check_thread and self.check_thread.isRunning():
            self.check_thread.quit()
            self.check_thread.wait()
        if self.action_thread and self.action_thread.isRunning():
            self.action_thread.quit()
            self.action_thread.wait()
        event.accept()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Add a check for the send2trash library
    try:
        import send2trash
    except ImportError:
        print("ERROR: The 'send2trash' library is required for Recycle Bin functionality.")
        print("Please install it by running: pip install send2trash")
        sys.exit(1)
        
    app = QApplication(sys.argv)
    window = DuplicateWindow()
    window.show()
    sys.exit(app.exec())
