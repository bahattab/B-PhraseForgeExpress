"""Full-screen overlay for dragging a capture rectangle (used for OCR).

select_region() returns (x1, y1, x2, y2) in physical screen pixels, or None.
"""
from __future__ import annotations

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from phraseforge.ui.theme import ACCENT


class _ScreenOverlay(QWidget):
    """One overlay per monitor so per-screen DPI scaling is exact."""

    def __init__(self, screen, owner: "RegionSelector"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.screen_ = screen
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen.geometry())
        self.start: QPoint | None = None
        self.end: QPoint | None = None

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self.start and self.end:
            r = QRect(self.start, self.end).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.fillRect(r, QColor(255, 255, 255, 1))  # keep mouse events inside
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRect(r)
        else:
            p.setPen(QColor("white"))
            p.drawText(self.rect(), Qt.AlignCenter, "Drag to select a region · Esc to cancel")

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.RightButton:
            self.owner.finish(None)
            return
        self.start = self.end = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self.start is not None:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.start is None:
            return
        self.end = e.position().toPoint()
        r = QRect(self.start, self.end).normalized()
        if r.width() < 4 or r.height() < 4:
            self.start = self.end = None
            self.update()
            return
        self.owner.finish(self.to_physical(r))

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape:
            self.owner.finish(None)

    def to_physical(self, r: QRect) -> tuple[int, int, int, int]:
        return logical_to_physical(self.screen_, r)


def logical_to_physical(screen, r: QRect) -> tuple[int, int, int, int]:
    """Map a rect in widget coords on `screen` to physical desktop pixels.

    Qt's high-DPI scaling keeps each screen's origin unchanged and scales only
    the offsets inside the screen, so physical = origin + offset * dpr.
    """
    dpr = screen.devicePixelRatio()
    g = screen.geometry()
    ox, oy = g.x(), g.y()
    x1 = int(round(ox + r.left() * dpr))
    y1 = int(round(oy + r.top() * dpr))
    x2 = int(round(ox + (r.right() + 1) * dpr))
    y2 = int(round(oy + (r.bottom() + 1) * dpr))
    return x1, y1, x2, y2


class RegionSelector:
    def __init__(self):
        self.result: tuple[int, int, int, int] | None = None
        self.loop = QEventLoop()
        self.overlays = [_ScreenOverlay(s, self) for s in QGuiApplication.screens()]

    def finish(self, result) -> None:
        self.result = result
        for o in self.overlays:
            o.close()
        self.loop.quit()

    def run(self) -> tuple[int, int, int, int] | None:
        for o in self.overlays:
            o.show()
            o.raise_()
        if self.overlays:
            self.overlays[0].activateWindow()
            self.loop.exec()
        return self.result


def select_region() -> tuple[int, int, int, int] | None:
    return RegionSelector().run()
