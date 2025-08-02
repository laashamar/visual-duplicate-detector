# file_handler.py
# Handles file system operations, including OneDrive placeholders.

import os
import logging
import ctypes
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import ALLOWED_IMAGE_EXTENSIONS

# Windows file attribute constant for files that are not fully present locally
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

# The number of parallel download triggers to run. This should be tuned to match
# the downstream service's capacity (e.g., the OneDrive client's limit).
# A value of 8 is a safe and effective starting point.
MAX_DOWNLOAD_WORKERS = 8

def is_online_only(file_path):
    """
    Checks if a file is a placeholder (e.g., OneDrive "online-only" file).
    """
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(file_path))
        if attrs == -1:
            return False
        return (attrs & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS) != 0
    except Exception as e:
        logging.warning(f"Could not check file attributes for {file_path}: {e}")
        return False

def scan_directory(folder_path):
    """
    Scans a directory recursively to find all files, categorizing them
    into images and others based on extensions.
    """
    start_time = time.monotonic()
    image_files = Counter()
    other_files = Counter()
    candidate_image_paths = []
    total_files = 0
    logging.info(f"Starting scan of folder: {folder_path}")
    for root, _, files in os.walk(folder_path):
        for filename in files:
            total_files += 1
            ext = os.path.splitext(filename)[1].lower()
            if not ext:
                ext = ".NO_EXT"
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                image_files[ext] += 1
                candidate_image_paths.append(os.path.join(root, filename))
            else:
                other_files[ext] += 1
    scan_duration = time.monotonic() - start_time
    logging.info(f"Folder scan completed in {scan_duration:.2f} seconds.")
    return {
        "total_files": total_files, "image_files": dict(image_files),
        "other_files": dict(other_files), "candidate_paths": candidate_image_paths,
        "scan_duration": scan_duration
    }

def _trigger_download(file_path):
    """
    Helper function to be run in a thread. Triggers the download for a single file.
    Returns the file path on success, or raises an exception on failure.
    """
    try:
        # Reading the first byte of the file triggers the download by the OS.
        with open(file_path, 'rb') as f:
            f.read(1)
        logging.info(f"Download triggered and completed for: {os.path.basename(file_path)}")
        return file_path
    except Exception as e:
        logging.error(f"Could not download the file {os.path.basename(file_path)}: {e}")
        # Re-raise the exception so the main executor knows this task failed.
        raise

def ensure_files_are_local(file_paths, progress_callback):
    """
    Checks a list of files and triggers downloads for any that are online-only
    using a bounded parallel thread pool.
    """
    start_time = time.monotonic()
    online_files = [path for path in file_paths if is_online_only(path)]

    if not online_files:
        logging.info("All files are already available locally.")
        return 0.0

    total_to_download = len(online_files)
    logging.info(f"Found {total_to_download} files that need to be downloaded from the cloud.")
    
    completed_count = 0
    
    # Use a ThreadPoolExecutor to manage a fixed number of download-triggering threads.
    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
        # Create a dictionary to map futures to their file paths for logging.
        future_to_path = {executor.submit(_trigger_download, path): path for path in online_files}

        # Use as_completed to process results as they finish, not in the order they were submitted.
        # This is key for providing smooth, real-time progress updates.
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                # Check if the future completed without raising an exception.
                future.result()
                completed_count += 1
                # The progress_callback is a Qt Signal, which is thread-safe.
                # It emits the progress update back to the GUI thread.
                progress_callback(completed_count, total_to_download)
            except Exception as exc:
                logging.error(f"'{os.path.basename(path)}' failed to download due to: {exc}")

    download_duration = time.monotonic() - start_time
    logging.info(f"Download of {completed_count}/{total_to_download} files completed in {download_duration:.2f} seconds.")
    return download_duration
