"""
PyChat - LLM Chat Management Application

A desktop application for managing conversations with Large Language Models.
Similar to Cherry Studio and Chatbox.

Features:
- Multi-provider support (OpenAI, Claude, Ollama, etc.)
- Conversation management with JSON import/export
- Message editing (text and images)
- Thinking mode support
- Token statistics and performance metrics
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

from ui.main_window import MainWindow


def main():
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    
    # Set application info
    app.setApplicationName("PyChat")
    app.setOrganizationName("PyChat")
    app.setApplicationVersion("1.0.0")
    
    # Set application icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pycat.ico")
    app.setWindowIcon(QIcon(icon_path))
    
    # Set default font
    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
