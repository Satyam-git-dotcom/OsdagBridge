"""
Analysis progress dialog – MIDAS Civil-inspired layout with Osdag styling.

Architecture
------------
Windows/macOS : dialog runs in a child process (avoids blocking the main UI).
Linux         : dialog runs in-process.

The main process sends structured messages via ``mp.Queue``.
The child process also exposes a ``cancel_event`` (``mp.Event``) that the
dialog's Stop button sets, which the main process checks between pipeline
stages to abort gracefully.
"""
import sys
import multiprocessing as mp

from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QTextEdit,
)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QIcon, QMouseEvent


# ──────────────────────────────────────────────────────────────────────────────
# Inline title bar  (self-contained — no QSS or resource files needed in child
# process)
# ──────────────────────────────────────────────────────────────────────────────

class _TitleBar(QWidget):
    """
    Minimal Osdag-style title bar:
    - White background
    - #90AF13 bottom separator line (2 px)
    - Osdag brand label + dialog title
    - No window-control buttons (loading dialog is not user-resizable)
    Supports click-drag to move the parent window.
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self._drag_pos = QPoint()

        self.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border: none;
            }
            QLabel#brand {
                color: #90AF13;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#title {
                color: #1F1F1F;
                font-size: 11px;
                font-weight: 600;
            }
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 12, 2)
        row.setSpacing(6)

        brand = QLabel("Osdag")
        brand.setObjectName("brand")
        row.addWidget(brand)

        sep = QLabel("·")
        sep.setStyleSheet("color: #CCCCCC; font-size: 12px;")
        row.addWidget(sep)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("title")
        row.addWidget(title_lbl)
        row.addStretch()

    def paintEvent(self, event):
        super().paintEvent(event)
        # Draw the #90AF13 bottom separator line
        p = QPainter(self)
        p.setPen(QPen(QColor(0x90, 0xAF, 0x13), 2))
        y = self.height() - 1
        p.drawLine(0, y, self.width(), y)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)


# ──────────────────────────────────────────────────────────────────────────────
# Spinning arc widget (used inside the title bar area)
# ──────────────────────────────────────────────────────────────────────────────

class _SpinnerLabel(QLabel):
    """28 × 28 rotating arc in Osdag green."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.setFixedSize(24, 24)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self.angle = (self.angle - 6) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(3, 3, -3, -3)
        pen = QPen(QColor(0x90, 0xAF, 0x13))
        pen.setWidthF(2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, int(self.angle * 16), 80 * 16)

    def stop(self):
        self._timer.stop()


# ──────────────────────────────────────────────────────────────────────────────
# Main dialog
# ──────────────────────────────────────────────────────────────────────────────

class AnalysisProgressDialog(QDialog):
    """
    MIDAS Civil-inspired analysis progress dialog.

    Layout
    ------
    ┌──────────────────────────────────────────────┐
    │ Osdag · Analysis in Progress          ⟳      │  ← title bar
    │══════════════════════════════════════════════│  ← #90AF13 line
    │  Stage 3/8 : DTO CONSTRUCTION   [37%]         │
    │  ████████████░░░░░░░░░░░░░░░░░░░             │
    │  Building grillage mesh: 7 long × 11 trans …  │
    │  ╔══════════════════════════════════════════╗  │
    │  ║ [12:10:53]  SPAN : 25.0 m              ║  │
    │  ║ [12:10:53]  STAGE 2 COMPLETE [25%] … ║  │
    │  ╚══════════════════════════════════════════╝  │
    │               [ Stop Analysis ]               │
    └──────────────────────────────────────────────┘
    """

    def __init__(self, cancel_event, is_light_theme: bool = True, parent=None):
        super().__init__(parent)
        self._cancel_event = cancel_event
        self._is_light = is_light_theme

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(False)
        self.setFixedSize(500, 400)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        try:
            self.setWindowIcon(QIcon(":/images/osdag_logo.png"))
        except Exception:
            pass

        self._build_ui()
        self._center()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self):
        bg       = "#FFFFFF" if self._is_light else "#2C2C2C"
        fg       = "#1F1F1F" if self._is_light else "#D0D0D0"
        sub_fg   = "#777777" if self._is_light else "#A0A0A0"
        log_bg   = "#F8F8F8" if self._is_light else "#1E1E1E"
        log_fg   = "#555555" if self._is_light else "#A0A0A0"
        log_bdr  = "#DDDDDD" if self._is_light else "#444444"
        btn_bdr  = "#CCCCCC" if self._is_light else "#555555"
        bar_bg   = "#E8E8E8" if self._is_light else "#444444"

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                border: 1px solid #90AF13;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title bar + spinner ───────────────────────────────────────────
        title_row = QWidget()
        title_row.setStyleSheet(f"background-color: {bg}; border-bottom: 2px solid #90AF13;")
        title_row.setFixedHeight(36)
        tr_layout = QHBoxLayout(title_row)
        tr_layout.setContentsMargins(10, 0, 10, 2)
        tr_layout.setSpacing(8)

        self._spinner = _SpinnerLabel()
        tr_layout.addWidget(self._spinner)

        brand_lbl = QLabel("Osdag")
        brand_lbl.setStyleSheet(
            "color: #90AF13; font-weight: 700; font-size: 12px; "
            "letter-spacing: 1px; border: none; background: transparent;"
        )
        tr_layout.addWidget(brand_lbl)

        dot_lbl = QLabel("·")
        dot_lbl.setStyleSheet(f"color: #CCCCCC; font-size: 13px; border: none; background: transparent;")
        tr_layout.addWidget(dot_lbl)

        title_lbl = QLabel("Analysis in Progress")
        title_lbl.setStyleSheet(
            f"color: {fg}; font-weight: 600; font-size: 11px; "
            "border: none; background: transparent;"
        )
        tr_layout.addWidget(title_lbl)
        tr_layout.addStretch()

        # Drag-to-move support via title row
        title_row._drag_pos = QPoint()

        def _press(ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                title_row._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def _move(ev):
            if ev.buttons() == Qt.MouseButton.LeftButton:
                self.move(ev.globalPosition().toPoint() - title_row._drag_pos)

        title_row.mousePressEvent = _press
        title_row.mouseMoveEvent = _move

        root.addWidget(title_row)

        # ── Content ───────────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet(f"background-color: {bg};")
        c = QVBoxLayout(content)
        c.setContentsMargins(16, 14, 16, 14)
        c.setSpacing(8)

        # Stage label
        self._stage_lbl = QLabel("Initialising…")
        self._stage_lbl.setStyleSheet(
            f"color: {fg}; font-weight: 600; font-size: 11px; background: transparent;"
        )
        self._stage_lbl.setWordWrap(True)
        c.addWidget(self._stage_lbl)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(10)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {bar_bg};
                border-radius: 5px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: #90AF13;
                border-radius: 5px;
            }}
        """)
        c.addWidget(self._progress)

        # Sub-step label
        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet(
            f"color: {sub_fg}; font-size: 9px; background: transparent;"
        )
        self._sub_lbl.setWordWrap(True)
        self._sub_lbl.setFixedHeight(26)
        c.addWidget(self._sub_lbl)

        # Mini log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Courier New", 8))
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background-color: {log_bg};
                color: {log_fg};
                border: 1px solid {log_bdr};
                border-radius: 3px;
            }}
        """)
        c.addWidget(self._log)

        # Stop button
        self._stop_btn = QPushButton("Stop Analysis")
        self._stop_btn.setFixedHeight(30)
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {btn_bdr};
                border-radius: 5px;
                font-size: 11px;
                font-weight: 500;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: #90AF13;
                color: white;
                border-color: #90AF13;
            }}
            QPushButton:pressed {{
                background-color: #6B7D20;
                color: white;
            }}
            QPushButton:disabled {{
                background-color: {"#F0F0F0" if self._is_light else "#3A3A3A"};
                color: {"#AAAAAA" if self._is_light else "#666666"};
                border-color: {"#DDDDDD" if self._is_light else "#444444"};
            }}
        """)
        self._stop_btn.clicked.connect(self._on_stop)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        c.addLayout(btn_row)

        root.addWidget(content)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_message(self, msg: str, level: str) -> None:
        """Dispatch one message from the queue to the appropriate widgets."""
        if level == "progress":
            try:
                pct = int(msg.replace("__progress__", ""))
                self._progress.setValue(pct)
            except ValueError:
                pass
            return

        # Append to mini log with colour coding
        color = {
            "error":   "#FF4444",
            "success": "#00BB00",
            "warning": "#FFA500",
        }.get(level, "#888888")
        html_msg = (
            msg.replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;")
        )
        self._log.append(
            f'<span style="color:{color}; white-space:pre;">{html_msg}</span>'
        )
        self._log.ensureCursorVisible()

        # Extract bare text (strip leading timestamp [ts])
        bare = msg.split("]", 1)[-1].strip() if "]" in msg else msg.strip()
        if not bare:
            return

        if "STAGE" in bare and "/" in bare:
            # Stage start or complete line → update stage label
            self._stage_lbl.setText(bare)
            if "COMPLETE" in bare:
                self._sub_lbl.setText("")
        else:
            # All other non-blank lines → sub-step label (capped at 100 chars)
            self._sub_lbl.setText(bare[:100])

    # ── Internals ─────────────────────────────────────────────────────────────

    def _on_stop(self):
        self._cancel_event.set()
        self._stage_lbl.setText("Stopping analysis…")
        self._sub_lbl.setText("Please wait for the current step to finish.")
        self._stop_btn.setEnabled(False)

    def closeEvent(self, event):
        self._spinner.stop()
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Child-process entry-point
# ──────────────────────────────────────────────────────────────────────────────

def run_loading_dialog_process(stop_event, label_queue, cancel_event, is_light_theme=True):
    """
    Runs in a child process (Windows/macOS).

    Parameters
    ----------
    stop_event   : mp.Event — set by main process to close the dialog
    label_queue  : mp.Queue — receives dicts ``{"msg": str, "level": str}``
    cancel_event : mp.Event — set by dialog's Stop button; polled by main process
    is_light_theme : bool
    """
    app = QApplication(sys.argv)
    dialog = AnalysisProgressDialog(cancel_event, is_light_theme=is_light_theme)

    def check_events():
        if stop_event.is_set():
            dialog.close()
            return
        while not label_queue.empty():
            try:
                item = label_queue.get_nowait()
                dialog.handle_message(item["msg"], item["level"])
            except Exception:
                pass

    timer = QTimer()
    timer.timeout.connect(check_events)
    timer.start(80)   # ~12 updates/sec is plenty

    dialog.show()
    app.exec()


# ──────────────────────────────────────────────────────────────────────────────
# Manager (used by template_page.py)
# ──────────────────────────────────────────────────────────────────────────────

class LoadingDialogManager:
    """
    Controls the analysis progress dialog.

    Windows/macOS : separate process (non-blocking UI).
    Linux         : in-process dialog.

    Usage
    -----
    mgr = LoadingDialogManager()
    mgr.show()
    ...
    mgr.send_message("[ts] STAGE 1/8 …", "info")
    mgr.send_message("__progress__12", "progress")
    ...
    if mgr.is_cancelled():
        abort()
    mgr.hide()
    """

    def __init__(self, is_light_theme: bool = True):
        self.process     = None
        self.stop_event  = None
        self.label_queue = None
        self.cancel_event = mp.Event()
        self.is_light_theme = is_light_theme
        self._dialog     = None          # in-process mode only

        import platform
        self._use_process = platform.system() != "Linux"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def show(self) -> None:
        self.cancel_event.clear()
        if self._use_process:
            if self.process is not None and self.process.is_alive():
                return
            self.stop_event  = mp.Event()
            self.label_queue = mp.Queue()
            self.process = mp.Process(
                target=run_loading_dialog_process,
                args=(self.stop_event, self.label_queue, self.cancel_event, self.is_light_theme),
            )
            self.process.start()
        else:
            if self._dialog is None:
                self._dialog = AnalysisProgressDialog(
                    self.cancel_event, is_light_theme=self.is_light_theme
                )
            self._dialog.show()

    def hide(self) -> None:
        if self._use_process:
            if self.process is not None and self.process.is_alive():
                self.stop_event.set()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.terminate()
            self.process     = None
            self.stop_event  = None
            self.label_queue = None
        else:
            if self._dialog is not None:
                self._dialog.hide()
                self._dialog._spinner.stop()
                self._dialog = None

    # ── Messaging ─────────────────────────────────────────────────────────────

    def send_message(self, msg: str, level: str) -> None:
        """Forward a bridge_logger message to the dialog."""
        if self._use_process:
            if self.label_queue is not None:
                try:
                    self.label_queue.put_nowait({"msg": msg, "level": level})
                except Exception:
                    pass
        else:
            if self._dialog is not None:
                self._dialog.handle_message(msg, level)

    def update_label(self, text: str) -> None:
        """Legacy helper — wraps send_message as a plain info line."""
        self.send_message(text, "info")

    # ── Cancel ────────────────────────────────────────────────────────────────

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def __del__(self):
        self.hide()
