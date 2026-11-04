"""The themes to choose from: each a small ALT lit as the theme lights it, moving as it would,
with its name under it. A click puts it on the keyboard."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QSizePolicy, QWidget

from .. import presets
from .. import state as st
from . import theme

COLUMNS = 4
PAD = 0.35          # key units between the keys and the small case's edge
GLOW = 0.55         # how far the edge's light reaches past it
NAME_H = 30         # the name's strip under the picture

# Typing, for the theme that lights pressed keys: these keys, one after another, over and over.
TYPED = [st.LAYOUT.index(next(k for k in st.LAYOUT if k[3] == c)) for c in 'KEYGLOW']
TYPE_EVERY = 260    # ms between them


def _typing(ms: int, speed: int) -> dict:
    """LED -> ms since it was pressed, for keys pressed less than a fade ago."""
    turn = TYPE_EVERY * (len(TYPED) + 3)
    out = {}
    for n, led in enumerate(TYPED):
        ago = (ms - n * TYPE_EVERY) % turn
        if ago < st.fade_ms(speed):
            out[led] = ago
    return out


def draw_mini(p: QPainter, area: QRectF, lit: list) -> None:
    """A small ALT in `area`, its keys and edge lit with `lit` (colours(), keys then edge)."""
    span_w = st.WIDTH + 2 * PAD + 2 * GLOW
    span_h = st.HEIGHT + 2 * PAD + 2 * GLOW
    u = min(area.width() / span_w, area.height() / span_h)
    case = QRectF(0, 0, (st.WIDTH + 2 * PAD) * u, (st.HEIGHT + 2 * PAD) * u)
    case.moveCenter(area.center())
    p.setPen(Qt.NoPen)
    for j in range(st.EDGE):
        colour = QColor(*lit[st.KEYS + j])
        if colour.value() < 8:
            continue
        x, y = st.POINTS[st.KEYS + j]
        at = QPointF(case.left() + x / 224 * case.width(), case.bottom() - y / 64 * case.height())
        glow = QRadialGradient(at, GLOW * u * 1.6)
        inner, outer = QColor(colour), QColor(colour)
        inner.setAlpha(150)
        outer.setAlpha(0)
        glow.setColorAt(0, inner)
        glow.setColorAt(1, outer)
        p.setBrush(glow)
        p.drawEllipse(at, GLOW * u * 1.6, GLOW * u * 1.6)
    p.setBrush(QColor('#2a2b30'))
    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    p.drawRoundedRect(case, 0.3 * u, 0.3 * u)
    p.setPen(Qt.NoPen)
    cap = (27, 28, 32)
    gap = 0.1
    for i, (x, y, w, _) in enumerate(st.LAYOUT):
        r, g, b = lit[i]
        p.setBrush(QColor(int(cap[0] * 0.25 + r * 0.75), int(cap[1] * 0.25 + g * 0.75), int(cap[2] * 0.25 + b * 0.75)))
        key = QRectF(case.left() + (PAD + x + gap / 2) * u, case.top() + (PAD + y + gap / 2) * u,
                     (w - gap) * u, (1 - gap) * u)
        p.drawRoundedRect(key, 0.14 * u, 0.14 * u)


class ThemeTile(QAbstractButton):
    """One theme: its picture and name. Ringed while the keyboard shows it."""

    def __init__(self, choice: presets.Theme, parent=None):
        super().__init__(parent)
        self.choice = choice
        self.current = False
        self.state = choice.apply(st.State())
        self.setText(choice.name)
        self.setToolTip(choice.name)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(122)
        self.setMinimumWidth(150)
        self.setAttribute(Qt.WA_Hover)

    def moving(self) -> bool:
        return st.moving(self.state)

    def set_current(self, current: bool) -> None:
        if current != self.current:
            self.current = current
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(190, 122)

    def paintEvent(self, event) -> None:
        ms = int(time.perf_counter() * 1000) & 0xFFFFFF
        pressed = _typing(ms, self.state.keys.speed) if self.state.keys.mode == st.KEY_REACTIVE else None
        lit = st.colors(self.state, ms, pressed)
        c = theme.colors()
        dark = theme.is_dark()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tile = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hover = self.underMouse()
        fill = QColor(255, 255, 255, 22 if dark else 150) if not hover else QColor(255, 255, 255, 34 if dark else 210)
        p.setBrush(fill)
        if self.current:
            p.setPen(QPen(QColor(theme.ACCENT if dark else theme.ROSE), 2))
        elif self.hasFocus() and self.property('_focus_ring'):
            p.setPen(QPen(QColor(theme.ROSE), 1.5))
        else:
            p.setPen(QPen(theme.colors().border, 1))
        p.drawRoundedRect(tile, 12, 12)
        picture = QRectF(tile.left() + 8, tile.top() + 6, tile.width() - 16, tile.height() - NAME_H - 6)
        draw_mini(p, picture, lit)
        name = QFont(theme.font(theme.TYPE['body']))
        if self.current:
            name.setWeight(QFont.DemiBold)
        p.setFont(name)
        p.setPen(c.text)
        p.drawText(QRectF(tile.left() + 10, tile.bottom() - NAME_H, tile.width() - 20, NAME_H - 6),
                   Qt.AlignCenter, self.text())
        p.end()


class ThemesPage(QWidget):
    """Every theme in a grid; the moving ones are redrawn while the page is in sight."""

    chosen = Signal(object)     # a presets.Theme

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        self.tiles = []
        for n, choice in enumerate(presets.THEMES):
            tile = ThemeTile(choice)
            tile.clicked.connect(lambda _=False, c=choice: self.chosen.emit(c))
            grid.addWidget(tile, n // COLUMNS, n % COLUMNS)
            self.tiles.append(tile)
        grid.setRowStretch(len(presets.THEMES) // COLUMNS + 1, 1)
        self._clock = QTimer(self)
        self._clock.setInterval(33)
        self._clock.timeout.connect(self._tick)

    def mark(self, state: st.State) -> None:
        """Rings the theme the keyboard shows, if any."""
        for tile in self.tiles:
            tile.set_current(tile.choice.shown_by(state))

    def _tick(self) -> None:
        if theme.quiet_now():       # a game in front: the pictures stand still
            return
        for tile in self.tiles:
            if tile.moving():
                tile.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._clock.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._clock.stop()
