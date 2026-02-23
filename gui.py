import sys
import os
import re
from typing import List, Optional, Dict, Any
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QCheckBox, QListWidget, QListWidgetItem,
    QTextEdit, QLabel, QFileDialog, QSplitter, QStatusBar,
    QProgressBar, QGroupBox, QFormLayout, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QSize

# Import logic from main.py
import main

class SearchWorker(QThread):
    finished = Signal(list)
    error = Signal(str)
    progress = Signal(int)

    def __init__(self, conversations, query, regex, case_sensitive, search_titles, search_messages, title_filter_str, only_with_code, start_date, end_date):
        super().__init__()
        self.conversations = conversations
        self.query = query
        self.regex = regex
        self.case_sensitive = case_sensitive
        self.search_titles = search_titles
        self.search_messages = search_messages
        self.title_filter_str = title_filter_str
        self.only_with_code = only_with_code
        self.start_date = start_date
        self.end_date = end_date

    def run(self):
        try:
            query_pat = main.compile_query(self.query, self.regex, self.case_sensitive)
            title_filter = main.compile_query(self.title_filter_str, False, False) if self.title_filter_str else None
            
            start = main.parse_date(self.start_date) if self.start_date else None
            end = main.parse_date(self.end_date) if self.end_date else None
            
            # Since main.search_export doesn't report progress via a callback (it uses tqdm),
            # we might want to modify it if we want progress updates.
            # For now, just call it.
            hits = main.search_export(
                conversations=self.conversations,
                query_pat=query_pat,
                search_titles=self.search_titles,
                search_messages=self.search_messages,
                title_filter=title_filter,
                only_with_code=self.only_with_code,
                start=start,
                end=end,
            )
            
            # Sort: best-effort by timestamp descending if present, otherwise stable
            def sort_key(h: main.MatchHit):
                try:
                    return datetime.fromisoformat(h.message_time).timestamp() if h.message_time else -1
                except Exception:
                    return -1

            hits.sort(key=sort_key, reverse=True)
            self.finished.emit(hits)
        except Exception as e:
            self.error.emit(str(e))

class LoadWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, input_path):
        super().__init__()
        self.input_path = input_path

    def run(self):
        try:
            data = main.load_conversations(self.input_path)
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))

class ChatGPTVaultGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChatGPT Vault Search")
        self.setMinimumSize(QSize(1000, 700))
        
        self.conversations = []
        self.hits = []
        
        self.init_ui()
        self.load_stylesheet()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # File Selection Area
        file_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to ChatGPT export ZIP or folder...")
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_file)
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.load_data)
        
        file_layout.addWidget(QLabel("Export Path:"))
        file_layout.addWidget(self.path_edit)
        file_layout.addWidget(self.browse_btn)
        file_layout.addWidget(self.load_btn)
        main_layout.addLayout(file_layout)

        # Search Options
        search_group = QGroupBox("Search Options")
        search_form = QVBoxLayout(search_group)
        
        query_layout = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Enter search query...")
        self.query_edit.returnPressed.connect(self.start_search)
        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("search_btn")
        self.search_btn.clicked.connect(self.start_search)
        query_layout.addWidget(self.query_edit)
        query_layout.addWidget(self.search_btn)
        search_form.addLayout(query_layout)

        options_layout = QHBoxLayout()
        self.regex_cb = QCheckBox("Regex")
        self.case_cb = QCheckBox("Case Sensitive")
        self.titles_cb = QCheckBox("Search Titles")
        self.titles_cb.setChecked(True)
        self.messages_cb = QCheckBox("Search Messages")
        self.messages_cb.setChecked(True)
        self.only_code_cb = QCheckBox("Only with Code")
        
        options_layout.addWidget(self.regex_cb)
        options_layout.addWidget(self.case_cb)
        options_layout.addWidget(self.titles_cb)
        options_layout.addWidget(self.messages_cb)
        options_layout.addWidget(self.only_code_cb)
        options_layout.addStretch()
        search_form.addLayout(options_layout)

        # Filters
        filter_layout = QHBoxLayout()
        self.title_filter_edit = QLineEdit()
        self.title_filter_edit.setPlaceholderText("Filter by conversation title...")
        self.start_date_edit = QLineEdit()
        self.start_date_edit.setPlaceholderText("Start date (YYYY-MM-DD)")
        self.end_date_edit = QLineEdit()
        self.end_date_edit.setPlaceholderText("End date (YYYY-MM-DD)")
        
        filter_layout.addWidget(QLabel("Title Filter:"))
        filter_layout.addWidget(self.title_filter_edit)
        filter_layout.addWidget(QLabel("Date Range:"))
        filter_layout.addWidget(self.start_date_edit)
        filter_layout.addWidget(self.end_date_edit)
        search_form.addLayout(filter_layout)

        main_layout.addWidget(search_group)

        # Results and Preview
        splitter = QSplitter(Qt.Horizontal)
        
        # Results List
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_list = QListWidget()
        self.results_list.itemSelectionChanged.connect(self.preview_selected)
        results_layout.addWidget(QLabel("Matches:"))
        results_layout.addWidget(self.results_list)
        splitter.addWidget(results_widget)
        
        # Preview Panel
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(QLabel("Preview:"))
        preview_layout.addWidget(self.preview_text)
        
        # Actions in Preview
        preview_actions = QHBoxLayout()
        self.export_btn = QPushButton("Export Results...")
        self.export_btn.clicked.connect(self.export_results)
        self.extract_code_btn = QPushButton("Extract Code Blocks...")
        self.extract_code_btn.clicked.connect(self.extract_code)
        preview_actions.addWidget(self.export_btn)
        preview_actions.addWidget(self.extract_code_btn)
        preview_layout.addLayout(preview_actions)
        
        splitter.addWidget(preview_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(splitter)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumSize(200, 15)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def load_stylesheet(self):
        style_path = os.path.join(os.path.dirname(__file__), "style.qss")
        if os.path.exists(style_path):
            with open(style_path, "r") as f:
                self.setStyleSheet(f.read())

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select ChatGPT Export ZIP", "", "ZIP Files (*.zip);;All Files (*)"
        )
        if not file_path:
            file_path = QFileDialog.getExistingDirectory(self, "Select ChatGPT Export Folder")
        
        if file_path:
            self.path_edit.setText(file_path)

    def load_data(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Error", "Please select an export path.")
            return

        self.status_bar.showMessage(f"Loading {path}...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.load_btn.setEnabled(False)

        self.load_worker = LoadWorker(path)
        self.load_worker.finished.connect(self.on_load_finished)
        self.load_worker.error.connect(self.on_load_error)
        self.load_worker.start()

    def on_load_finished(self, data):
        self.conversations = data
        self.status_bar.showMessage(f"Loaded {len(data)} conversations.", 5000)
        self.progress_bar.setVisible(False)
        self.load_btn.setEnabled(True)
        QMessageBox.information(self, "Success", f"Successfully loaded {len(data)} conversations.")

    def on_load_error(self, error_msg):
        self.status_bar.showMessage("Failed to load data.")
        self.progress_bar.setVisible(False)
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to load data: {error_msg}")

    def start_search(self):
        if not self.conversations:
            QMessageBox.warning(self, "Error", "Please load data first.")
            return
        
        query = self.query_edit.text().strip()
        if not query:
            # Maybe show all?
            pass
            
        self.status_bar.showMessage("Searching...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.search_btn.setEnabled(False)
        self.results_list.clear()

        self.search_worker = SearchWorker(
            self.conversations,
            query,
            self.regex_cb.isChecked(),
            self.case_cb.isChecked(),
            self.titles_cb.isChecked(),
            self.messages_cb.isChecked(),
            self.title_filter_edit.text().strip(),
            self.only_code_cb.isChecked(),
            self.start_date_edit.text().strip(),
            self.end_date_edit.text().strip()
        )
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.error.connect(self.on_search_error)
        self.search_worker.start()

    def on_search_finished(self, hits):
        self.hits = hits
        self.status_bar.showMessage(f"Found {len(hits)} matches.", 5000)
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        
        for i, hit in enumerate(hits):
            title = hit.conversation_title or "Untitled"
            when = hit.message_time or hit.conversation_create_time or "Unknown"
            role = f" [{hit.author_role}]" if hit.author_role else ""
            item_text = f"{title}\n{when}{role}\n{hit.snippet}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, i)
            self.results_list.addItem(item)

    def on_search_error(self, error_msg):
        self.status_bar.showMessage("Search failed.")
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Search failed: {error_msg}")

    def preview_selected(self):
        selected = self.results_list.selectedItems()
        if not selected:
            self.preview_text.clear()
            return
        
        idx = selected[0].data(Qt.UserRole)
        hit = self.hits[idx]
        
        text = f"Title: {hit.conversation_title}\n"
        text += f"ID: {hit.conversation_id}\n"
        if hit.conversation_create_time:
            text += f"Conversation Created: {hit.conversation_create_time}\n"
        if hit.message_id:
            text += f"Message ID: {hit.message_id}\n"
            text += f"Author: {hit.author_role}\n"
            text += f"Time: {hit.message_time}\n"
        text += "=" * 40 + "\n\n"
        text += hit.full_text
        
        if hit.code_blocks:
            text += "\n\n" + "=" * 40 + "\n"
            text += "CODE BLOCKS:\n"
            for b in hit.code_blocks:
                text += f"--- {b['language']} ---\n"
                text += b['code'] + "\n"
                
        self.preview_text.setPlainText(text)

    def export_results(self):
        if not self.hits:
            QMessageBox.warning(self, "Error", "No results to export.")
            return
            
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Results", "results.md", "Markdown (*.md);;JSON (*.json);;Text (*.txt)"
        )
        if not file_path:
            return
            
        try:
            if file_path.endswith(".json"):
                main.export_json(self.hits, file_path)
            elif file_path.endswith(".txt"):
                main.export_txt(self.hits, file_path)
            else:
                # Default to MD
                if not file_path.endswith(".md"):
                    file_path += ".md"
                main.export_md(self.hits, file_path)
            QMessageBox.information(self, "Success", f"Exported results to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def extract_code(self):
        if not self.hits:
            QMessageBox.warning(self, "Error", "No results to extract code from.")
            return
            
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory for Extracted Code")
        if not dir_path:
            return
            
        try:
            count = main.extract_code_to_dir(self.hits, dir_path)
            QMessageBox.information(self, "Success", f"Extracted {count} code block(s) to {dir_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to extract code: {e}")

def main_gui():
    app = QApplication(sys.argv)
    window = ChatGPTVaultGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main_gui()
