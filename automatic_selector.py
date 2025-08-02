# automatic_selector.py

import os
import logging
import re
from enum import Enum
from functools import cmp_to_key

from data_models import FileMetadata

class SelectionStrategy(Enum):
    """Defines the available, improved strategies for automatic selection."""
    KEEP_BEST_QUALITY = "Keep best quality"
    KEEP_LAST_EDITED = "Keep last edited"
    KEEP_ALL_UNIQUE_VERSIONS = "Keep unique versions (original + edited)"

    def __str__(self):
        return self.value

class AutomaticSelector:
    """
    Implements a robust, hierarchical model for automatic image selection
    based on a comprehensive quality assessment.
    """
    def __init__(self):
        self.format_priority = {
            '.dng': 0, '.tiff': 1, '.png': 2,
            '.jpeg': 3, '.jpg': 3, '.heic': 4, '.webp': 5
        }
        self.edit_suffix_regex = re.compile(r'[-_]\d+$|[-_]edit(ed)?$|[-_]copy$|\(\d+\)$', re.IGNORECASE)

    def _get_file_format_priority(self, path):
        ext = os.path.splitext(path)[1].lower()
        return self.format_priority.get(ext, 99)

    def _is_likely_original_by_name(self, path):
        filename = os.path.splitext(os.path.basename(path))[0]
        return not self.edit_suffix_regex.search(filename)

    def _compare_files(self, meta1: FileMetadata, meta2: FileMetadata):
        if meta1.resolution > meta2.resolution: return -1
        if meta1.resolution < meta2.resolution: return 1
        if meta1.size > meta2.size: return -1
        if meta1.size < meta2.size: return 1
        priority1 = self._get_file_format_priority(meta1.path)
        priority2 = self._get_file_format_priority(meta2.path)
        if priority1 < priority2: return -1
        if priority1 > priority2: return 1
        is_orig1 = self._is_likely_original_by_name(meta1.path)
        is_orig2 = self._is_likely_original_by_name(meta2.path)
        if is_orig1 and not is_orig2: return -1
        if not is_orig1 and is_orig2: return 1
        if meta1.mod_time < meta2.mod_time: return -1
        if meta1.mod_time > meta2.mod_time: return 1
        return 0

    def _get_best_in_group(self, metadata_list):
        if not metadata_list:
            return None
        sorted_list = sorted(metadata_list, key=cmp_to_key(self._compare_files))
        return sorted_list[0]

    def _strategy_keep_best_quality(self, metadata_list):
        if not metadata_list:
            return [], {}
        best_file = self._get_best_in_group(metadata_list)
        files_to_keep = {best_file.path} if best_file else set()
        files_to_remove = [m.path for m in metadata_list if m.path not in files_to_keep]
        return files_to_remove, {}

    def _strategy_keep_last_edited(self, metadata_list):
        if not metadata_list:
            return [], {}
        last_edited = max(metadata_list, key=lambda m: m.mod_time)
        files_to_keep = {last_edited.path}
        files_to_remove = [m.path for m in metadata_list if m.path not in files_to_keep]
        return files_to_remove, {}

    def _strategy_keep_unique_versions(self, metadata_list):
        """
        This strategy now always identifies the original, the last edited, and the rest.
        The calling function will decide what to do with them based on user settings.
        """
        if len(metadata_list) < 2:
            return [], {}

        best_original_file = self._get_best_in_group(metadata_list)
        last_edited_file = max(metadata_list, key=lambda m: m.mod_time)

        files_to_keep = {best_original_file.path, last_edited_file.path}
        
        # Identify the remaining files
        remains = [m.path for m in metadata_list if m.path not in files_to_keep]
        
        # The files to be removed are the "remains"
        files_to_remove = remains
        
        # The files to be sorted are the original and the last edited
        files_to_sort = {'original': best_original_file.path, 'edited': last_edited_file.path}
        
        return files_to_remove, files_to_sort

    def run_automatic_selection(self, groups, strategy, all_file_data):
        all_files_for_removal = set()
        all_files_to_sort = []

        strategy_map = {
            SelectionStrategy.KEEP_BEST_QUALITY: self._strategy_keep_best_quality,
            SelectionStrategy.KEEP_LAST_EDITED: self._strategy_keep_last_edited,
            SelectionStrategy.KEEP_ALL_UNIQUE_VERSIONS: self._strategy_keep_unique_versions
        }

        strategy_func = strategy_map.get(strategy)
        if not strategy_func:
            logging.error(f"Unknown strategy: {strategy}. Cannot perform automatic selection.")
            return [], []

        for group in groups:
            if len(group) < 2:
                continue

            metadata_list = [all_file_data.get(path) for path in group if all_file_data.get(path)]
            if len(metadata_list) < 2:
                continue

            files_to_remove, files_to_sort_for_group = strategy_func(metadata_list)
            
            all_files_for_removal.update(files_to_remove)
            if files_to_sort_for_group:
                all_files_to_sort.append(files_to_sort_for_group)
        
        return list(all_files_for_removal), all_files_to_sort
