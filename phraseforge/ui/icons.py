"""PhraseForge's own artwork, drawn with QPainter (no external assets).

App icon: a blue rounded tile with a white speech bubble holding a yellow spark
("text, instantly"). The About dialog uses a large version of the same motif.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap, QPolygonF,
    QRadialGradient,
)

BLUE_TOP, BLUE_BOTTOM = "#3a8ad6", "#1d5fa8"
SPARK = "#ffcf3f"


def _bubble_path(r: QRectF) -> QPainterPath:
    """Speech bubble inside rect r, tail at bottom-left."""
    body = QRectF(r.left(), r.top(), r.width(), r.height() * 0.78)
    path = QPainterPath()
    path.addRoundedRect(body, r.width() * 0.22, r.width() * 0.22)
    tail = QPainterPath()
    tail.moveTo(r.left() + r.width() * 0.20, body.bottom() - 2)
    tail.lineTo(r.left() + r.width() * 0.14, r.bottom())
    tail.lineTo(r.left() + r.width() * 0.44, body.bottom() - 2)
    tail.closeSubpath()
    return path.united(tail)


def _spark(cx: float, cy: float, s: float) -> QPolygonF:
    """Lightning spark centred at (cx, cy), size s."""
    pts = [(-0.10, -0.50), (0.30, -0.50), (0.08, -0.08), (0.32, -0.08), (-0.18, 0.55), (-0.02, 0.06),
           (-0.28, 0.06)]
    return QPolygonF([QPointF(cx + x * s, cy + y * s) for x, y in pts])


def paint_mark(p: QPainter, r: QRectF, paused: bool = False, tile: bool = True) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    if tile:
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#9a9a9a" if paused else BLUE_TOP))
        g.setColorAt(1, QColor("#6f6f6f" if paused else BLUE_BOTTOM))
        path = QPainterPath()
        path.addRoundedRect(r, r.width() * 0.22, r.width() * 0.22)
        p.fillPath(path, QBrush(g))
    inner = r.adjusted(r.width() * 0.17, r.height() * 0.17, -r.width() * 0.17, -r.height() * 0.12)
    p.fillPath(_bubble_path(inner), QColor("white"))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#bdbdbd" if paused else SPARK))
    p.drawPolygon(_spark(inner.center().x(), inner.top() + inner.height() * 0.39, inner.height() * 0.62))
    if paused:   # pause bars
        p.setBrush(QColor("#d64545"))
        w = r.width()
        p.drawRoundedRect(QRectF(r.right() - w * 0.36, r.bottom() - w * 0.36, w * 0.12, w * 0.30), 1, 1)
        p.drawRoundedRect(QRectF(r.right() - w * 0.20, r.bottom() - w * 0.36, w * 0.12, w * 0.30), 1, 1)


def _pix(size: int, paused: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_mark(p, QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92), paused)
    p.end()
    return pm


def app_icon(paused: bool = False) -> QIcon:
    icon = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_pix(s, paused))
    return icon


def about_artwork(width: int, height: int) -> QPixmap:
    """Large artwork for the About dialog: soft grey backdrop + big bubble with spark."""
    pm = QPixmap(width, height)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QRadialGradient(QPointF(width * 0.35, height * 0.30), max(width, height) * 0.9)
    bg.setColorAt(0, QColor("#ffffff"))
    bg.setColorAt(1, QColor("#c9ced6"))
    p.fillRect(pm.rect(), bg)
    s = min(width, height) * 0.86
    r = QRectF(-s * 0.10, height * 0.12, s, s)
    shadow = _bubble_path(r.translated(6, 8))
    p.fillPath(shadow, QColor(0, 0, 0, 40))
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#ffffff"))
    g.setColorAt(1, QColor("#e3e7ee"))
    p.fillPath(_bubble_path(r), QBrush(g))
    sg = QLinearGradient(r.center().x(), r.top(), r.center().x(), r.bottom())
    sg.setColorAt(0, QColor(BLUE_TOP))
    sg.setColorAt(1, QColor(BLUE_BOTTOM))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(sg))
    p.drawPolygon(_spark(r.center().x() + s * 0.04, r.top() + s * 0.36, s * 0.52))
    p.end()
    return pm


def dot_icon(color: str, size: int = 12) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)
