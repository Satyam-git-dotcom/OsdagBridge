"""
Log dock widget for Osdag GUI.
Displays timestamped analysis/design progress messages from the core pipeline.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QFont

from osdagbridge.core.utils.logger import bridge_logger


class LogDock(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.is_visible = True
        self.setObjectName("logs_dock")
        self.init_ui()
        self.adjust_size()
        # Register this dock as the pipeline's log receiver
        bridge_logger.set_callback(self.append_log)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 0)
        layout.setSpacing(0)

        self.log_window_title = QLabel("Log Window")
        self.log_window_title.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.log_window_title)

        self.log_display = QTextEdit()
        self.log_display.setObjectName("textEdit")
        self.log_display.setReadOnly(True)
        self.log_display.setOverwriteMode(True)
        # Monospace font so MIDAS-style columnar output aligns correctly
        self.log_display.setFont(QFont("Courier New", 8))
        layout.addWidget(self.log_display)

        ts = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        self.append_log(f"[{ts}] Log initialized", "info")

        self.setLayout(layout)
        self.show()

    # ------------------------------------------------------------------
    # Log receiver
    # ------------------------------------------------------------------

    def append_log(self, message: str, log_level: str = "info") -> None:
        """
        Append a pipeline message to the log display.

        Levels
        ------
        info     – grey  (normal progress)
        success  – green (stage complete, analysis done)
        error    – red   (failures)
        warning  – orange (non-fatal issues)
        progress – silent; updates the title bar percentage instead
        """
        if log_level == "progress":
            self._update_progress_title(message)
            return

        color = self._level_color(log_level)
        # Preserve whitespace so columnar MIDAS-style output renders correctly
        html = (
            f'<span style="color:{color}; white-space:pre;">'
            f'{self._escape_html(message)}'
            f'</span>'
        )
        self.log_display.append(html)
        self.log_display.ensureCursorVisible()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _level_color(level: str) -> str:
        return {
            "error":   "#FF4444",
            "success": "#00BB00",
            "warning": "#FFA500",
            "info":    "#A6A6A6",
        }.get(level, "#A6A6A6")

    @staticmethod
    def _escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _update_progress_title(self, token: str) -> None:
        """
        Parse ``__progress__<pct>`` and update the dock title.
        This prepares for Step 6 (loading-dialog integration).
        """
        try:
            pct = int(token.replace("__progress__", ""))
            if pct == 0:
                self.log_window_title.setText("Log Window")
            elif pct >= 100:
                self.log_window_title.setText("Log Window  –  Complete (100%)")
            else:
                self.log_window_title.setText(f"Log Window  –  Analysing… {pct}%")
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Visibility / sizing
    # ------------------------------------------------------------------

    def toggle_log_dock(self):
        self.is_visible = not self.is_visible
        if self.is_visible:
            self.show()
            self.adjust_size()
            self.move(0, self.parent().height() - self.height())
        else:
            self.hide()

    def adjust_size(self):
        parent = self.parent()
        if not parent:
            return
        if parent.input_dock is None or parent.output_dock is None:
            return

        input_dock = parent.input_dock
        output_dock = parent.output_dock

        parent_width = parent.width()
        input_dock_width = input_dock.width() if input_dock.isVisible() else 0
        output_dock_width = output_dock.width() if output_dock.isVisible() else 0
        available_width = parent_width - input_dock_width - output_dock_width

        default_height = 150
        self.setFixedSize(available_width, default_height)

        if self.is_visible:
            self.move(0, parent.height() - default_height)
