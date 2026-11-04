"""The ALT, drawn: its keys lit as the keyboard lights them, the light round its edge glowing out
from under it, and keys to pick for per-key colours (a click, Ctrl or Shift and a click for more,
or a box dragged round them)."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import state as st
from . import theme

CASE_PAD = 0.42         # key units between the keys and the case's edge
GLOW = 0.9              # how far the edge's light reaches out past the case
GAP = 0.07              # between keycaps

# Windows' scan codes (Qt's nativeScanCode: 0x100 for the extended keys) -> the LED under that key,
# so keys pressed while the window has focus light up in the picture as they would on the board.
SCAN_TO_LED = {1: 0, **{code: code - 1 for code in range(2, 14)}, 14: 13, 0x153: 14,
               15: 15, **{code: code for code in range(16, 28)}, 43: 28, 0x147: 29,
               58: 30, **{code: code + 1 for code in range(30, 41)}, 28: 42, 0x149: 43,
               42: 44, **{code: code + 1 for code in range(44, 54)}, 54: 55, 0x148: 56, 0x151: 57,
               29: 58, 0x15B: 59, 56: 60, 57: 61, 0x138: 62, 0x14B: 64, 0x150: 65, 0x14D: 66}


class Board(QWidget):
    picked = Signal(object)     # the set of keys (LED numbers) picked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = st.State()
        self.picking = False                # per-key colours: keys can be picked
        self.dim = False                    # not the keyboard's own lighting (it isn't set up yet)
        self.picked_keys: set[int] = set()
        self._presses: dict[int, float] = {}
        self._drag_from: QPointF | None = None
        self._drag_to: QPointF | None = None
        self._before_drag: set[int] = set()
        self._clock = QTimer(self)
        self._clock.setInterval(33)
        self._clock.timeout.connect(self._tick)
        self._start = time.perf_counter()
        self.setMinimumSize(560, 210)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)

    # --- what it shows ----------------------------------------------------------------------

    def show_state(self, state: st.State) -> None:
        self.state = state
        self._run_clock()
        self.update()

    def set_dim(self, dim: bool) -> None:
        self.dim = dim
        self.update()

    def set_picking(self, on: bool) -> None:
        self.picking = on
        if not on:
            self._pick(set())
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
        self.update()

    def press(self, scan_code: int) -> bool:
        """A key pressed while the window has focus; True if it is one of the ALT's."""
        led = SCAN_TO_LED.get(scan_code)
        if led is None:
            return False
        self._presses[led] = time.perf_counter()
        self._run_clock()
        return True

    def _run_clock(self) -> None:
        busy = st.moving(self.state) or bool(self._presses)
        if busy and not self._clock.isActive() and self.isVisible():
            self._clock.start()
        elif not busy:
            self._clock.stop()

    def _tick(self) -> None:
        now = time.perf_counter()
        fade = st.fade_ms(self.state.keys.speed) / 1000
        self._presses = {led: at for led, at in self._presses.items() if now - at < fade}
        self._run_clock()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._run_clock()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._clock.stop()

    # --- where things are -------------------------------------------------------------------

    def _unit(self) -> float:
        span_w = st.WIDTH + 2 * CASE_PAD + 2 * GLOW
        span_h = st.HEIGHT + 2 * CASE_PAD + 2 * GLOW
        return max(4.0, min(self.width() / span_w, self.height() / span_h))

    def _origin(self) -> QPointF:
        u = self._unit()
        w = (st.WIDTH + 2 * CASE_PAD) * u
        h = (st.HEIGHT + 2 * CASE_PAD) * u
        return QPointF((self.width() - w) / 2, (self.height() - h) / 2)

    def _case(self) -> QRectF:
        u = self._unit()
        o = self._origin()
        return QRectF(o.x(), o.y(), (st.WIDTH + 2 * CASE_PAD) * u, (st.HEIGHT + 2 * CASE_PAD) * u)

    def key_rect(self, i: int) -> QRectF:
        u = self._unit()
        o = self._origin()
        x, y, w, _ = st.LAYOUT[i]
        return QRectF(o.x() + (CASE_PAD + x + GAP / 2) * u, o.y() + (CASE_PAD + y + GAP / 2) * u,
                      (w - GAP) * u, (1 - GAP) * u)

    def _edge_point(self, j: int) -> QPointF:
        case = self._case()
        x, y = st.POINTS[st.KEYS + j]
        return QPointF(case.left() + x / 224 * case.width(), case.bottom() - y / 64 * case.height())

    def key_at(self, point: QPointF) -> int | None:
        for i in range(st.KEYS):
            if self.key_rect(i).contains(point):
                return i
        return None

    # --- picking keys -----------------------------------------------------------------------

    def _pick(self, keys: set[int]) -> None:
        if keys != self.picked_keys:
            self.picked_keys = set(keys)
            self.picked.emit(set(keys))
            self.update()

    def pick_all(self) -> None:
        if self.picking:
            self._pick(set(range(st.KEYS)))

    def mousePressEvent(self, event) -> None:
        if not self.picking or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        point = event.position()
        adding = bool(event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        key = self.key_at(point)
        self._before_drag = set(self.picked_keys) if adding else set()
        if key is not None:
            keys = set(self._before_drag)
            if adding and key in keys:
                keys.discard(key)
            else:
                keys.add(key)
            self._pick(keys)
        else:
            self._pick(self._before_drag)
        self._drag_from = point
        self._drag_to = None

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            return super().mouseMoveEvent(event)
        point = event.position()
        if self._drag_to is None and (point - self._drag_from).manhattanLength() < 6:
            return
        self._drag_to = point
        box = QRectF(self._drag_from, point).normalized()
        inside = {i for i in range(st.KEYS) if box.intersects(self.key_rect(i))}
        self._pick(self._before_drag | inside)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = self._drag_to = None
        self.update()
        super().mouseReleaseEvent(event)

    # --- drawing ----------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        ms = int((time.perf_counter() - self._start) * 1000)
        now = time.perf_counter()
        pressed = {led: (now - at) * 1000 for led, at in self._presses.items()}
        lit = st.colors(self.state, ms, pressed)
        u = self._unit()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.dim:
            p.setOpacity(0.35)
        case = self._case()
        dark = theme.is_dark()

        # the edge's light, spilling out from under the case
        p.setPen(Qt.NoPen)
        for j in range(st.EDGE):
            color = QColor(*lit[st.KEYS + j])
            if color.value() < 8:
                continue
            at = self._edge_point(j)
            glow = QRadialGradient(at, GLOW * u)
            inner = QColor(color)
            inner.setAlpha(170)
            outer = QColor(color)
            outer.setAlpha(0)
            glow.setColorAt(0, inner)
            glow.setColorAt(1, outer)
            p.setBrush(glow)
            p.drawEllipse(at, GLOW * u, GLOW * u)

        # the case
        radius = 0.32 * u
        body = QColor('#26272c') if dark else QColor('#2f3036')
        p.setBrush(body)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawRoundedRect(case, radius, radius)
        # the edge lights themselves, a thin line of colour along the case's rim
        for j in range(st.EDGE):
            color = QColor(*lit[st.KEYS + j])
            if color.value() < 8:
                continue
            at = self._edge_point(j)
            color.setAlpha(230)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(at, 0.09 * u, 0.09 * u)

        # the keys
        legend = QFont(theme.font(9))
        legend.setPixelSize(max(7, int(u * 0.22)))
        p.setFont(legend)
        for i in range(st.KEYS):
            rect = self.key_rect(i)
            r, g, b = lit[i]
            color = QColor(r, g, b)
            # the LED sits under the top of the key: its light spills round the cap
            if color.value() > 8:
                halo = QColor(color)
                halo.setAlpha(110)
                p.setPen(Qt.NoPen)
                p.setBrush(halo)
                p.drawRoundedRect(rect.adjusted(-0.04 * u, -0.04 * u, 0.04 * u, 0.04 * u), 0.14 * u, 0.14 * u)
            cap = QColor('#1b1c20')
            mixed = QColor(int(cap.red() * 0.58 + r * 0.42), int(cap.green() * 0.58 + g * 0.42),
                           int(cap.blue() * 0.58 + b * 0.42))
            p.setBrush(mixed)
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawRoundedRect(rect, 0.1 * u, 0.1 * u)
            top = rect.adjusted(0.08 * u, 0.06 * u, -0.08 * u, -0.16 * u)
            p.setBrush(QColor(int(mixed.red() * 1.08 + 4), int(mixed.green() * 1.08 + 4),
                              int(mixed.blue() * 1.08 + 4)).toRgb())
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(top, 0.08 * u, 0.08 * u)
            label = st.LAYOUT[i][3]
            if label:
                shine = QColor(color) if color.value() > 24 else QColor(120, 122, 130)
                if shine.lightness() < 150:
                    shine = shine.lighter(170)
                p.setPen(shine)
                p.drawText(top.adjusted(0.08 * u, 0.04 * u, 0, 0), Qt.AlignLeft | Qt.AlignTop, label)
            if i in self.picked_keys:
                ring = QPen(QColor(theme.ACCENT), max(2.0, 0.05 * u))
                p.setPen(ring)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-0.02 * u, -0.02 * u, 0.02 * u, 0.02 * u), 0.12 * u, 0.12 * u)

        if self._drag_from is not None and self._drag_to is not None:
            box = QRectF(self._drag_from, self._drag_to).normalized()
            fill = QColor(theme.ACCENT)
            fill.setAlpha(40)
            p.setBrush(fill)
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.drawRoundedRect(box, 4, 4)
        p.end()
