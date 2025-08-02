# workers.py
import os
import shutil
import logging
from PySide6.QtCore import QObject, Signal

# --- NEW: Import send2trash for Recycle Bin functionality ---
try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

from file_handler import scan_directory, ensure_files_are_local
from visual_duplicate_checker import batch_duplicate_check
from automatic_selector import AutomaticSelector

# --- RENAMED and REFACTORED: From FileSorter/FileMover to a single ActionWorker ---
class ActionWorker(QObject):
    """
    A single worker to process all file actions: sorting, moving, and recycling.
    """
    finished = Signal(str)
    progress_log = Signal(str)

    def __init__(self, action_config):
        super().__init__()
        self.config = action_config

    def run(self):
        # Unpack the configuration dictionary
        files_to_sort = self.config.get('files_to_sort', [])
        remains_to_process = self.config.get('remains_to_process', [])
        remains_action = self.config.get('remains_action', 'none')
        remains_dest_folder = self.config.get('remains_dest_folder')
        base_sort_folder = self.config.get('base_sort_folder')

        originals_folder = os.path.join(base_sort_folder, "Originals")
        edits_folder = os.path.join(base_sort_folder, "Last Edited")

        # --- 1. Perform Sorting ---
        if files_to_sort:
            os.makedirs(originals_folder, exist_ok=True)
            os.makedirs(edits_folder, exist_ok=True)
            for sort_info in files_to_sort:
                original_path = sort_info.get('original')
                edited_path = sort_info.get('edited')
                if original_path:
                    self._move_file(original_path, originals_folder, "SORTED")
                if edited_path and edited_path != original_path:
                    self._move_file(edited_path, edits_folder, "SORTED")

        # --- 2. Process Remaining Files ---
        if remains_action == 'recycle':
            if not send2trash:
                self.progress_log.emit("ERROR: send2trash library not found. Please run 'pip install send2trash'.")
            else:
                for path in remains_to_process:
                    self._recycle_file(path)
        elif remains_action == 'move':
            os.makedirs(remains_dest_folder, exist_ok=True)
            for path in remains_to_process:
                self._move_file(path, remains_dest_folder, "MOVED")
        
        self.finished.emit("All file actions completed.")

    def _move_file(self, file_path, destination_folder, action_verb="MOVED"):
        """Helper to move a single file safely."""
        try:
            if os.path.exists(file_path):
                file_name = os.path.basename(file_path)
                destination_path = os.path.join(destination_folder, file_name)
                if os.path.exists(destination_path):
                    base, ext = os.path.splitext(file_name)
                    i = 1
                    while os.path.exists(destination_path):
                        destination_path = os.path.join(destination_folder, f"{base}_{i}{ext}")
                        i += 1
                shutil.move(file_path, destination_path)
                message = f"{action_verb}: {file_name} to {os.path.basename(destination_folder)}"
                self.progress_log.emit(message)
            else:
                self.progress_log.emit(f"SKIP: File no longer exists at {file_path}")
        except Exception as e:
            self.progress_log.emit(f"ERROR moving {os.path.basename(file_path)}: {e}")

    def _recycle_file(self, file_path):
        """Helper to send a single file to the Recycle Bin."""
        try:
            if os.path.exists(file_path):
                send2trash(file_path)
                self.progress_log.emit(f"RECYCLED: {os.path.basename(file_path)}")
            else:
                self.progress_log.emit(f"SKIP: File no longer exists at {file_path}")
        except Exception as e:
            self.progress_log.emit(f"ERROR recycling {os.path.basename(file_path)}: {e}")


class DuplicateChecker(QObject):
    """
    The main worker for the entire duplicate check process.
    """
    scan_summary_ready = Signal(dict)
    download_progress = Signal(int, int)
    manual_check_finished = Signal(dict, dict, list)
    automatic_selection_finished = Signal(list, list, dict)
    progress_updated = Signal(int, str)
    error_occurred = Signal(str)

    def __init__(self, folder_path, threshold, mode, strategy):
        super().__init__()
        self.folder_path = folder_path
        self.threshold = threshold
        self.mode = mode
        self.strategy = strategy
        self.automatic_selector = AutomaticSelector()

    def run(self):
        try:
            self.progress_updated.emit(0, "Scanning folder...")
            scan_summary = scan_directory(self.folder_path)
            self.scan_summary_ready.emit(scan_summary)
            check_statistics = {"scan_time": scan_summary.get("scan_duration", 0)}
            candidate_paths = scan_summary.get("candidate_paths", [])

            if not candidate_paths:
                self.progress_updated.emit(100, "No image files found.")
                if self.mode == "Manual review":
                    self.manual_check_finished.emit(check_statistics, {}, [])
                else:
                    self.automatic_selection_finished.emit([], [], check_statistics)
                return

            download_duration = ensure_files_are_local(candidate_paths, self.download_progress.emit)
            check_statistics["download_time"] = download_duration

            check_results, all_file_data, groups = batch_duplicate_check(
                candidate_paths, self.threshold, self.progress_updated.emit
            )
            check_statistics.update(check_results)
            check_statistics['groups_found'] = len(groups)

            if not groups:
                if self.mode == "Manual review":
                    self.manual_check_finished.emit(check_statistics, all_file_data, [])
                else:
                    self.automatic_selection_finished.emit([], [], check_statistics)
                return

            if self.mode == "Manual review":
                self.manual_check_finished.emit(check_statistics, all_file_data, groups)
            else:
                start_time_auto = time.monotonic()
                files_for_removal, files_to_sort = self.automatic_selector.run_automatic_selection(
                    groups, self.strategy, all_file_data
                )
                check_statistics["automatic_selection_time"] = time.monotonic() - start_time_auto
                self.automatic_selection_finished.emit(files_for_removal, files_to_sort, check_statistics)

        except Exception as e:
            logging.critical(f"A critical error occurred in the duplicate check thread: {e}", exc_info=True)
            self.error_occurred.emit(f"An error occurred during the duplicate check:\n\n{e}")
