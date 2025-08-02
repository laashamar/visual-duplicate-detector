# ui_panels.py
# Contains specialized QFrame classes for each section of the GUI.

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QComboBox, QScrollArea, QWidget, QProgressBar, QTextEdit, QGridLayout,
    QCheckBox, QRadioButton, QLineEdit
)
from automatic_selector import SelectionStrategy

class SettingsPanel(QFrame):
    """The panel for all settings before the check starts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        title = QLabel("<b>1. Settings</b>")
        layout.addWidget(title)

        # Folder selection
        self.label_folder = QLabel("Select a folder to begin")
        self.btn_folder = QPushButton("📂 Select Folder")
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.label_folder, 1)
        folder_layout.addWidget(self.btn_folder)
        layout.addLayout(folder_layout)

        # Mode and Strategy
        mode_layout = QGridLayout()
        mode_layout.addWidget(QLabel("<b>Mode:</b>"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Automatic selection", "Manual review"])
        mode_layout.addWidget(self.mode_combo, 0, 1)

        self.strategy_label = QLabel("<b>Strategy:</b>")
        mode_layout.addWidget(self.strategy_label, 0, 2)
        
        self.strategy_combo = QComboBox()
        for strategy in SelectionStrategy:
            self.strategy_combo.addItem(str(strategy), strategy)
        mode_layout.addWidget(self.strategy_combo, 0, 3)
        mode_layout.setColumnStretch(4, 1)
        layout.addLayout(mode_layout)

        # Checkbox for sorting into subfolders
        self.chk_sort_into_folders = QCheckBox("Sort kept files into 'Originals' and 'Last Edited' subfolders")
        self.chk_sort_into_folders.setVisible(False)
        layout.addWidget(self.chk_sort_into_folders)
        
        # --- NEW: Frame for handling remaining files ---
        self.remains_options_frame = QFrame()
        self.remains_options_frame.setVisible(False) # Hidden by default
        remains_layout = QVBoxLayout(self.remains_options_frame)
        remains_layout.setContentsMargins(20, 5, 5, 5) # Indent for clarity
        
        remains_label = QLabel("<b>For the remaining images in the group:</b>")
        remains_layout.addWidget(remains_label)
        
        self.radio_recycle = QRadioButton("Move to Recycle Bin")
        self.radio_move = QRadioButton("Move to a specific folder:")
        self.radio_recycle.setChecked(True)
        remains_layout.addWidget(self.radio_recycle)
        remains_layout.addWidget(self.radio_move)

        move_dest_layout = QHBoxLayout()
        self.remains_dest_path = QLineEdit()
        self.btn_select_remains_dest = QPushButton("...")
        self.btn_select_remains_dest.setFixedWidth(30)
        move_dest_layout.addWidget(self.remains_dest_path)
        move_dest_layout.addWidget(self.btn_select_remains_dest)
        remains_layout.addLayout(move_dest_layout)
        
        layout.addWidget(self.remains_options_frame)

        # Sensitivity (Threshold)
        threshold_layout = QHBoxLayout()
        self.label_threshold = QLabel()
        self.slider_threshold = QSlider(Qt.Horizontal)
        self.slider_threshold.setRange(0, 64)
        self.slider_threshold.setValue(5)
        threshold_layout.addWidget(self.label_threshold)
        threshold_layout.addWidget(self.slider_threshold, 1)
        layout.addLayout(threshold_layout)

        self.help_threshold = QLabel()
        self.help_threshold.setWordWrap(True)
        layout.addWidget(self.help_threshold)

        # Start button
        self.btn_start = QPushButton("🚀 Start Duplicate Check")
        layout.addWidget(self.btn_start)

        # Connect signals to show/hide the new options
        self.strategy_combo.currentIndexChanged.connect(self.on_strategy_changed)
        self.chk_sort_into_folders.stateChanged.connect(self.on_sort_checkbox_changed)
        self.on_strategy_changed() # Set initial state

    def on_strategy_changed(self):
        """Shows or hides the sorting checkbox based on the selected strategy."""
        selected_strategy = self.strategy_combo.currentData(Qt.UserRole)
        is_versions_strategy = (selected_strategy == SelectionStrategy.KEEP_ALL_UNIQUE_VERSIONS)
        self.chk_sort_into_folders.setVisible(is_versions_strategy)
        if not is_versions_strategy:
            self.remains_options_frame.setVisible(False)

    def on_sort_checkbox_changed(self):
        """Shows or hides the options for remaining files."""
        is_checked = self.chk_sort_into_folders.isChecked()
        self.remains_options_frame.setVisible(is_checked)

class StatusPanel(QFrame):
    """The panel for status, log, and the final move button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        title = QLabel("<b>3. Status and Log</b>")
        layout.addWidget(title)
        status_layout = QHBoxLayout()
        scan_scroll_area = QScrollArea()
        scan_scroll_area.setWidgetResizable(True)
        self.scan_summary_label = QLabel("Waiting for folder selection...")
        self.scan_summary_label.setWordWrap(True)
        self.scan_summary_label.setAlignment(Qt.AlignTop)
        scan_scroll_area.setWidget(self.scan_summary_label)
        status_layout.addWidget(scan_scroll_area, 1)
        progress_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status = QLabel("Ready to start")
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.status)
        status_layout.addLayout(progress_layout, 1)
        layout.addLayout(status_layout)
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setFixedHeight(100)
        layout.addWidget(self.log_window)
        self.btn_move_duplicates = QPushButton("🗑️ Process Duplicates")
        self.btn_move_duplicates.setEnabled(False)
        layout.addWidget(self.btn_move_duplicates)
