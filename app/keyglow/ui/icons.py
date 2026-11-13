"""Keyglow's icon, drawn the suite's way: a blossom-pink tile filling the canvas, its corners
rounded to 42/192 of its width, and one deep-rose mark - a keycap with light rising off it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

APP_ICON_COLOR = '#ffd1dc'      # the suite's blossom pink, fixed: never the Windows accent
APP_ICON_MARK = '#c2255c'
APP_ICON_CORNER = 42 / 192


def render_app_icon(size: int) -> QPixmap:
    """The app icon at one size, drawn for that size so small ones stay crisp."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(APP_ICON_COLOR))
    corner = size * APP_ICON_CORNER
    p.drawRoundedRect(QRectF(0, 0, size, size), corner, corner)
    p.scale(size / 64.0, size / 64.0)
    mark = QColor(APP_ICON_MARK)
    small = size <= 24
    # the keycap, seen from the front: a wide top on a slightly wider base
    stroke = 4.2 if small else 3.4
    pen = QPen(mark, stroke)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    base = QPainterPath()
    base.addRoundedRect(QRectF(16, 30, 32, 20), 5, 5)
    p.drawPath(base)
    p.setBrush(mark)
    p.drawRoundedRect(QRectF(21, 33, 22, 10), 3, 3)
    # light rising off it: three rays, the middle one tallest
    if small:
        p.drawLine(QPointF(32, 13), QPointF(32, 22))
        p.drawLine(QPointF(19, 18), QPointF(23, 23))
        p.drawLine(QPointF(45, 18), QPointF(41, 23))
    else:
        p.drawLine(QPointF(32, 12), QPointF(32, 22))
        p.drawLine(QPointF(19.5, 16.5), QPointF(24, 22.5))
        p.drawLine(QPointF(44.5, 16.5), QPointF(40, 22.5))
    p.end()
    return pixmap


def app_icon() -> QIcon:
    """The window icon - and the one in the exe, from the same drawing."""
    result = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        result.addPixmap(render_app_icon(size))
    return result


def _own_icons() -> None:
    """Keyglow's device icons, beside the suite's (suiteicons): Lucide's memory-stick,
    circuit-board and refresh-ccw-dot (lucide-static 1.57.0, ISC, as the suite's own)."""
    from . import suiteicons
    suiteicons.SHAPES.setdefault('memory', (
        '<path d="M12 12v-2"/><path d="M12 18v-2"/><path d="M16 12v-2"/><path d="M16 18v-2"/>'
        '<path d="M2 11h1.5"/><path d="M20 18v-2"/><path d="M20.5 11H22"/><path d="M4 18v-2"/>'
        '<path d="M8 12v-2"/><path d="M8 18v-2"/><rect x="2" y="6" width="20" height="10" rx="2"/>'))
    suiteicons.SHAPES.setdefault('motherboard', (
        '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M11 9h4a2 2 0 0 0 2-2V3"/>'
        '<circle cx="9" cy="9" r="2"/><path d="M7 21v-4a2 2 0 0 1 2-2h4"/><circle cx="15" cy="15" r="2"/>'))
    suiteicons.SHAPES.setdefault('sync', (
        '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>'
        '<path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>'
        '<circle cx="12" cy="12" r="1"/>'))


_own_icons()
