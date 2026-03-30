"""Code preview dialog for generated Verilog."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QFileDialog, QMessageBox,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt


class CodePreviewDialog(QDialog):
    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self.code = code
        self.setWindowTitle("Generated Verilog - TopStitcher")
        self.resize(700, 500)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Consolas", 10))
        self.text_edit.setPlainText(self.code)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("Save As...")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._on_copy)
        btn_layout.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _on_save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Verilog File", "top_module.v",
            "Verilog Files (*.v *.sv);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.code)
                QMessageBox.information(self, "Saved", f"File saved to:\n{path}")
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")

    def _on_copy(self):
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.code)
