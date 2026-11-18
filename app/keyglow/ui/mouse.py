"""The Mouse page: the LAMZU mouse detected, its DPI stages and its sensor and button settings.
Every change is written to the mouse's active profile at once; the mouse keeps it."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QPushButton, QRadioButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import lamzu, mouselink
from . import icons, suiteicons, theme  # noqa: F401 - icons adds Keyglow's own to suiteicons
from . import suitesettings as ss

SUPPORTED = 'No supported mouse detected. Supported: LAMZU Maya X, LAMZU Maya X V2.'
SWITCHES = (
    ('motion_sync', 'Motion Sync', 'Aligns sensor data with each USB report. Adds slight latency.'),
    ('angle_snap', 'Angle Snapping', 'Straightens near-horizontal and near-vertical movement.'),
    ('ripple', 'Ripple Control', 'Reduces sensor jitter at high DPI.'),
    ('hyper', 'Competition Mode', 'Raises sensor performance. Shortens battery life.'),
)
NEW_STAGE_COLOUR = (255, 255, 255)


def _sleep_name(seconds: int) -> str:
    return f'{seconds} s' if seconds < 60 else f'{seconds // 60} min'


def _lod_name(mm: float) -> str:
    return f'{mm:g} mm'


class MousePage(QWidget):
    changed = Signal(object)            # the settings wanted (lamzu.Settings)

    def __init__(self):
        super().__init__()
        from .window import ColorButton
        self._color_button = ColorButton
        self._filling = False
        self.view = mouselink.View(mouselink.ABSENT)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)

        frame, items = ss.section('Mouse')
        self.where = ss.label('', ss.SMALL, role='dim', wrap=True)
        items.addWidget(self.where)
        self.problem = ss.label('', ss.SMALL, role='error', wrap=True)
        self.problem.hide()
        items.addWidget(self.problem)
        column.addWidget(frame)

        self.dpi_frame, items = ss.section('DPI')
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(ss.ITEMS)
        items.addLayout(self.grid)
        self.active = QButtonGroup(self)
        self.active.idClicked.connect(self._changed)
        self.rows: list[tuple] = []        # (radio, spin, colour button, remove button) per stage
        add_row = QHBoxLayout()
        self.add = QPushButton('Add stage')
        self.add.setIcon(suiteicons.icon('plus', theme.colors().text))
        self.add.setCursor(Qt.PointingHandCursor)
        self.add.clicked.connect(self._add_stage)
        add_row.addWidget(self.add)
        add_row.addStretch(1)
        items.addLayout(add_row)
        column.addWidget(self.dpi_frame)

        self.sensor_frame, items = ss.section('Performance')
        columns = QHBoxLayout()
        columns.setSpacing(32)
        left, right = ss.form(), ss.form()
        self.polling = QComboBox()
        self.lod = QComboBox()
        self.debounce = QSpinBox()
        self.debounce.setRange(0, lamzu.DEBOUNCE_MAX)
        self.debounce.setSuffix(' ms')
        self.sleep = QComboBox()
        left.addRow(ss.label('Polling rate'), self.polling)
        left.addRow(ss.label('Lift-off distance'), self.lod)
        right.addRow(ss.label('Debounce time'), self.debounce)
        right.addRow(ss.label('Sleep after'), self.sleep)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        items.addLayout(columns)
        for combo in (self.polling, self.lod, self.sleep, self.debounce):
            combo.setMinimumWidth(140)
        for combo in (self.polling, self.lod, self.sleep):
            combo.currentIndexChanged.connect(self._changed)
        self.debounce.editingFinished.connect(self._changed)
        self.switches = {}
        for key, name, about in SWITCHES:
            row, box = ss.switch(name, about, False)
            box.toggled.connect(self._changed)
            items.addWidget(row)
            self.switches[key] = (row, box)
        column.addWidget(self.sensor_frame)
        column.addStretch(1)
        self.show_view(self.view)

    # --- from the link ----------------------------------------------------------------------

    def show_view(self, view: mouselink.View) -> None:
        self.view = view
        if view.status == mouselink.ABSENT:
            where = SUPPORTED
        elif view.status == mouselink.ASLEEP:
            where = f'{view.name} wireless receiver connected. The mouse is not responding. Move the mouse to wake it.'
        else:
            parts = [view.name]
            if view.settings is not None:
                parts.append(f'Profile {view.settings.profile}')
            if view.battery is not None:
                parts.append(f'Battery {view.battery.percent}%' + (', charging' if view.battery.charging else ''))
            where = ' · '.join(parts)
        self.where.setText(where)
        self.problem.setText(view.problem)
        self.problem.setVisible(bool(view.problem))
        ready = view.status == mouselink.READY and view.settings is not None
        self.dpi_frame.setVisible(ready)
        self.sensor_frame.setVisible(ready)
        if ready:
            self.fill(view.settings, view.model)

    def fill(self, settings: lamzu.Settings, model: lamzu.Model) -> None:
        self._filling = True
        try:
            self._stage_rows(len(settings.stages), model)
            for i, stage in enumerate(settings.stages):
                radio, spin, colour, _ = self.rows[i]
                radio.setChecked(i == settings.active)
                spin.setValue(stage.dpi)
                colour.set_color(stage.color)
            self._choices(self.polling, model.polling, settings.polling, lambda hz: f'{hz} Hz')
            self._choices(self.lod, model.lod, settings.lod, _lod_name)
            self._choices(self.sleep, model.sleep, settings.sleep, _sleep_name)
            self.debounce.setEnabled(settings.debounce is not None)
            self.debounce.setValue(settings.debounce or 0)
            for key, (row, box) in self.switches.items():
                row.setVisible(key in settings.switches)
                box.setChecked(settings.switches.get(key, False))
            self.add.setEnabled(len(settings.stages) < 5)
        finally:
            self._filling = False

    @staticmethod
    def _choices(combo: QComboBox, values, current, name) -> None:
        if [combo.itemData(i) for i in range(combo.count())] != list(values):
            combo.clear()
            for value in values:
                combo.addItem(name(value), value)
        index = combo.findData(current)
        combo.setEnabled(current is None or index >= 0)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif current is None:
            combo.setCurrentIndex(-1)
        else:
            combo.setCurrentIndex(-1)
            combo.setPlaceholderText(name(current))

    def _stage_rows(self, count: int, model: lamzu.Model) -> None:
        while len(self.rows) > count:
            for widget in self.rows.pop():
                self.active.removeButton(widget) if isinstance(widget, QRadioButton) else None
                widget.deleteLater()
        while len(self.rows) < count:
            i = len(self.rows)
            radio = QRadioButton(f'Stage {i + 1}')
            radio.setCursor(Qt.PointingHandCursor)
            self.active.addButton(radio, i)
            spin = QSpinBox()
            spin.setSingleStep(50)
            spin.setSuffix(' DPI')
            spin.setMinimumWidth(140)
            spin.editingFinished.connect(self._changed)
            colour = self._color_button(lambda rgb, i=i: self._colour(i, rgb))
            remove = QPushButton()
            remove.setIcon(suiteicons.icon('trash', theme.colors().text))
            remove.setToolTip('Remove stage')
            remove.setCursor(Qt.PointingHandCursor)
            remove.clicked.connect(lambda _=False, i=i: self._remove_stage(i))
            for column, widget in enumerate((radio, spin, colour, remove)):
                self.grid.addWidget(widget, i, column)
            self.rows.append((radio, spin, colour, remove))
        self.grid.setColumnStretch(4, 1)
        for radio, spin, colour, remove in self.rows:
            spin.setRange(50, model.dpi_max)
            remove.setEnabled(count > 1)

    # --- to the link ------------------------------------------------------------------------

    def settings(self) -> lamzu.Settings | None:
        """What the page shows, as settings for the mouse."""
        old = self.view.settings
        if old is None:
            return None
        stages = []
        for i, (radio, spin, colour, _) in enumerate(self.rows):
            stages.append(lamzu.Stage(spin.value(), old.stages[i].color if i < len(old.stages) else NEW_STAGE_COLOUR))
        active = max(self.active.checkedId(), 0)
        return old.with_(
            stages=tuple(stages), active=min(active, len(stages) - 1),
            polling=self.polling.currentData() if self.polling.currentIndex() >= 0 else old.polling,
            lod=self.lod.currentData() if self.lod.currentIndex() >= 0 else old.lod,
            sleep=self.sleep.currentData() if self.sleep.currentIndex() >= 0 else old.sleep,
            debounce=self.debounce.value() if old.debounce is not None else None,
            switches={key: box.isChecked() for key, (row, box) in self.switches.items() if key in old.switches})

    def _want(self, settings: lamzu.Settings) -> None:
        if settings != self.view.settings:
            self.view = mouselink.View(self.view.status, self.view.name, self.view.wireless, settings,
                                       self.view.model, self.view.battery)
            self.changed.emit(settings)

    def _changed(self, *_) -> None:
        if not self._filling:
            settings = self.settings()
            if settings is not None:
                self._want(settings)

    def _colour(self, i: int, rgb) -> None:
        settings = self.settings()
        if settings is None or self._filling:
            return
        stages = list(settings.stages)
        stages[i] = lamzu.Stage(stages[i].dpi, tuple(rgb))
        self.rows[i][2].set_color(rgb)
        self._want(settings.with_(stages=tuple(stages)))

    def _add_stage(self) -> None:
        settings = self.settings()
        if settings is None or len(settings.stages) >= 5:
            return
        dpi = min(settings.stages[-1].dpi * 2, self.view.model.dpi_max)
        settings = settings.with_(stages=settings.stages + (lamzu.Stage(dpi, NEW_STAGE_COLOUR),))
        self._want(settings)
        self.fill(settings, self.view.model)

    def _remove_stage(self, i: int) -> None:
        settings = self.settings()
        if settings is None or len(settings.stages) <= 1:
            return
        stages = settings.stages[:i] + settings.stages[i + 1:]
        active = settings.active - (1 if settings.active > i or settings.active == len(stages) else 0)
        settings = settings.with_(stages=stages, active=max(0, min(active, len(stages) - 1)))
        self._want(settings)
        self.fill(settings, self.view.model)
