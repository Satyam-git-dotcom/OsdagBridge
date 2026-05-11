"""Bridge analysis and design structured logger."""
import logging
import time
from datetime import datetime
from typing import Callable, Optional

log = logging.getLogger("osdagbridge")

_SEP = "-" * 45


class BridgeLogger:
    """
    Singleton logger for the plate-girder analysis/design pipeline.

    Emits timestamped, stage-numbered messages through a registered callback so
    the UI layer (LogDock) can display them without the core depending on Qt.

    Pipeline stages
    ---------------
    1  Input Parsing
    2  Bridge Layout Solving
    3  DTO Construction
    4  Grillage Setup
    5  Dead Load Application
    6  Live Load Application
    7  Structural Analysis
    8  Design Checks
    """

    TOTAL_STAGES = 8
    STAGE_NAMES = [
        "INPUT PARSING",
        "BRIDGE LAYOUT SOLVING",
        "DTO CONSTRUCTION",
        "GRILLAGE SETUP",
        "DEAD LOAD APPLICATION",
        "LIVE LOAD APPLICATION",
        "STRUCTURAL ANALYSIS",
        "DESIGN CHECKS",
    ]

    _instance: Optional["BridgeLogger"] = None

    def __init__(self) -> None:
        self._callback: Optional[Callable[[str, str], None]] = None
        self._start_time: float = 0.0
        self._cancelled: bool = False

    @classmethod
    def get_instance(cls) -> "BridgeLogger":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def set_callback(self, callback: Callable[[str, str], None]) -> None:
        """
        Register the UI receiver.

        The callback signature is ``(message: str, level: str) -> None``
        where level is one of: "info", "success", "error", "warning", "progress".

        "progress" messages carry a special token ``__progress__<pct>`` that
        the UI can intercept to update a progress bar (future use).
        """
        self._callback = callback

    # ------------------------------------------------------------------
    # Internal emit
    # ------------------------------------------------------------------

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _emit(self, raw: str, level: str = "info") -> None:
        log.info(raw)
        if self._callback:
            self._callback(raw, level)

    def _blank(self) -> None:
        self._emit(f"[{self._ts()}]", "info")

    # ------------------------------------------------------------------
    # Pipeline-level markers
    # ------------------------------------------------------------------

    def analysis_start(self) -> None:
        self._start_time = time.time()
        self._blank()
        self._emit(f"[{self._ts()}] {_SEP} S T A R T I N G   A N A L Y S I S", "info")
        self._blank()

    def analysis_complete(self) -> None:
        elapsed = time.time() - self._start_time
        self._blank()
        self._emit(f"[{self._ts()}] {_SEP} A N A L Y S I S   C O M P L E T E", "success")
        self._emit(f"[{self._ts()}]   TOTAL SOLUTION TIME .. : {elapsed:.2f} [SEC]", "success")
        self._emit(f"[{self._ts()}] {'=' * 60}", "success")
        self._blank()

    def analysis_failed(self, reason: str) -> None:
        elapsed = time.time() - self._start_time
        self._blank()
        self._emit(f"[{self._ts()}] {_SEP} A N A L Y S I S   F A I L E D", "error")
        self._emit(f"[{self._ts()}]   REASON  .. : {reason}", "error")
        self._emit(f"[{self._ts()}]   ELAPSED .. : {elapsed:.2f} [SEC]", "error")
        self._blank()

    # ------------------------------------------------------------------
    # Stage markers
    # ------------------------------------------------------------------

    def stage_start(self, stage: int, **details) -> None:
        """
        Log the start of a numbered pipeline stage.

        Parameters
        ----------
        stage:
            Stage number 1–8.
        **details:
            Optional key=value pairs printed as indented sub-lines,
            e.g. ``span_m=25.0, n_girders=4``.
        """
        name = self._stage_name(stage)
        pct = int((stage - 1) / self.TOTAL_STAGES * 100)
        self._blank()
        self._emit(
            f"[{self._ts()}]   STAGE {stage}/{self.TOTAL_STAGES} : {name}  [{pct}%]",
            "info",
        )
        for key, val in details.items():
            label = key.replace("_", " ").upper()
            self._emit(f"[{self._ts()}]     {label:<35} : {val}", "info")
        self._emit_progress(stage - 1)

    def stage_complete(self, stage: int) -> None:
        name = self._stage_name(stage)
        pct = int(stage / self.TOTAL_STAGES * 100)
        self._emit(
            f"[{self._ts()}]   STAGE {stage} COMPLETE [{pct}%] : {name}",
            "success",
        )
        self._emit_progress(stage)

    # ------------------------------------------------------------------
    # Sub-step helpers (used inside a stage)
    # ------------------------------------------------------------------

    def sub_step(self, message: str, count: int = None, total: int = None) -> None:
        """Log a named sub-step, optionally with a running counter."""
        if count is not None and total is not None:
            self._emit(f"[{self._ts()}]     {message:<44} {count} / {total}", "info")
        else:
            self._emit(f"[{self._ts()}]     {message}", "info")

    def info(self, message: str) -> None:
        self._emit(f"[{self._ts()}]   {message}", "info")

    def success(self, message: str) -> None:
        self._emit(f"[{self._ts()}]   {message}", "success")

    def warning(self, message: str) -> None:
        self._emit(f"[{self._ts()}]   WARNING : {message}", "warning")

    def error(self, message: str) -> None:
        self._emit(f"[{self._ts()}]   ERROR : {message}", "error")

    # ------------------------------------------------------------------
    # Progress token (Step 6 – loading dialog integration)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Cancellation support
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Signal that the user has requested cancellation."""
        self._cancelled = True

    def check_cancel(self) -> None:
        """Raise RuntimeError if cancel() was called since the last check."""
        if self._cancelled:
            self._cancelled = False
            raise RuntimeError("Analysis cancelled by user")

    # ------------------------------------------------------------------

    def _emit_progress(self, stages_done: int) -> None:
        """
        Emit a special progress token that the UI can intercept.

        Format: ``__progress__<pct>`` where pct is 0–100.
        The log dock ignores this text and forwards pct to the loading dialog.
        """
        pct = int(stages_done / self.TOTAL_STAGES * 100)
        if self._callback:
            self._callback(f"__progress__{pct}", "progress")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stage_name(self, stage: int) -> str:
        if 1 <= stage <= len(self.STAGE_NAMES):
            return self.STAGE_NAMES[stage - 1]
        return "UNKNOWN"


bridge_logger = BridgeLogger.get_instance()
