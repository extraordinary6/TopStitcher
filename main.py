"""TopStitcher - Verilog Top Module Generator."""

import sys
import logging

from PyQt6.QtWidgets import QApplication
from topstitcher.gui.main_window import MainWindow


def main():
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    app.setApplicationName("TopStitcher")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
