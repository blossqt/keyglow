"""The Devices tab: every lit device - the keyboard, the memory, the motherboard - with its RGB Sync
switch, and for the memory and motherboard an effect of their own while it is off."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSlider, QVBoxLayout, QWidget

from .. import pc, ram
from . import suitesettings as ss

SYNC = 'RGB Sync'
SYNC_ABOUT = 'Uses the lighting shared by all devices with RGB Sync on.'
KEYBOARD_SYNC_ABOUT = ('Uses the lighting shared by all devices with RGB Sync on. While on, changes on the Keys '
                       'and Base light tabs apply to every synced device.')


def _slider(changed) -> QSlider:
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 255)
    slider.setMinimumWidth(220)
    slider.valueChanged.connect(changed)
    return slider


class PartControls(QWidget):
    """One device: what was detected, its RGB Sync switch, and its own effect while that is off."""

    changed = Signal(str, object)       # the part, its setting (pc.Part)

    def __init__(self, part: str, title: str):
        super().__init__()
        from .window import ColorButton
        self.part = part
        self.effects = pc.EFFECTS[part]
        self._filling = False
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)

        self.frame, items = ss.section(title)
        self.where = ss.label('', ss.SMALL, role='dim', wrap=True)
        items.addWidget(self.where)
        self.problem = ss.label('', ss.SMALL, role='error', wrap=True)
        self.problem.hide()
        items.addWidget(self.problem)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        items.addLayout(self.buttons)

        self.settings = QWidget()
        rows_column = QVBoxLayout(self.settings)
        rows_column.setContentsMargins(0, 0, 0, 0)
        rows_column.setSpacing(ss.ITEMS)
        row, self.sync = ss.switch(SYNC, SYNC_ABOUT, True)
        self.sync.toggled.connect(self._changed)
        rows_column.addWidget(row)
        self.own = QWidget()
        own = QVBoxLayout(self.own)
        own.setContentsMargins(0, 0, 0, 0)
        own.setSpacing(ss.ITEMS)
        row, self.on = ss.switch('Lighting', '', True)
        self.on.toggled.connect(self._changed)
        own.addWidget(row)
        self.form = ss.form()
        self.effect = QComboBox()
        for number, (name, _, _) in self.effects.items():
            self.effect.addItem(name, number)
        self.effect.currentIndexChanged.connect(self._changed)
        self.form.addRow(ss.label('Effect'), self.effect)
        self.a = ColorButton(lambda rgb: self._colour('a', rgb))
        self.a_name = ss.label('Colour')
        self.form.addRow(self.a_name, self.a)
        self.b = ColorButton(lambda rgb: self._colour('b', rgb))
        self.b_name = ss.label('Second colour')
        self.form.addRow(self.b_name, self.b)
        self.speed = _slider(self._changed)
        self.speed_name = ss.label('Speed')
        self.form.addRow(self.speed_name, self.speed)
        self.bright = _slider(self._changed)
        self.form.addRow(ss.label('Brightness'), self.bright)
        own.addLayout(self.form)
        rows_column.addWidget(self.own)
        items.addWidget(self.settings)
        column.addWidget(self.frame)
        self._colours = {'a': pc.PINK, 'b': pc.ROSE}

    def add_button(self, button: QPushButton) -> None:
        button.setCursor(Qt.PointingHandCursor)
        self.buttons.insertWidget(self.buttons.count() - 1, button)

    def found(self, where: str, found: bool, problem: str = '') -> None:
        """What was detected (or why nothing was): the settings show only for a device present."""
        self.where.setText(where)
        self.where.setVisible(bool(where))
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        self.settings.setVisible(found)

    def lighting(self) -> pc.Part:
        return pc.Part(sync=self.sync.isChecked(), on=self.on.isChecked(), effect=self.effect.currentData(),
                       a=self._colours['a'], b=self._colours['b'], speed=self.speed.value(),
                       bright=self.bright.value())

    def fill(self, part: pc.Part) -> None:
        self._filling = True
        try:
            self.sync.setChecked(part.sync)
            self.on.setChecked(part.on)
            index = self.effect.findData(part.effect)
            self.effect.setCurrentIndex(index if index >= 0 else 0)
            self._colours = {'a': tuple(part.a), 'b': tuple(part.b)}
            self.a.set_color(part.a)
            self.b.set_color(part.b)
            self.speed.setValue(part.speed)
            self.bright.setValue(part.bright)
        finally:
            self._filling = False
        self._shown()

    def _shown(self) -> None:
        self.own.setVisible(not self.sync.isChecked())
        first, second, speed = self.effects.get(self.effect.currentData(), (None, None, (None, None, False)))[2]
        on = self.on.isChecked()
        for widget, name, show in ((self.a, self.a_name, first), (self.b, self.b_name, second),
                                   (self.speed, self.speed_name, speed)):
            self.form.setRowVisible(widget, bool(show))
            if isinstance(show, str):
                name.setText(show)
        for i in range(self.form.rowCount()):
            for role in (self.form.ItemRole.LabelRole, self.form.ItemRole.FieldRole):
                item = self.form.itemAt(i, role)
                if item and item.widget():
                    item.widget().setEnabled(on)

    def _changed(self, *_) -> None:
        if self._filling:
            return
        self._shown()
        self.changed.emit(self.part, self.lighting())

    def _colour(self, which: str, rgb) -> None:
        self._colours[which] = tuple(rgb)
        (self.a if which == 'a' else self.b).set_color(rgb)
        if not self._filling:
            self.changed.emit(self.part, self.lighting())


def _sticks(sticks) -> str:
    names = Counter(stick.name for stick in sticks)
    return ', '.join(f'{name} × {count}' for name, count in names.items())


class DevicesPage(QWidget):
    """The keyboard, the memory and the motherboard."""

    lighting = Signal(str, object)      # the memory's or the motherboard's setting changed
    keyboard_sync = Signal(bool)        # the keyboard's RGB Sync switched
    setup_asked = Signal(str)           # '--install' or '--uninstall'

    def __init__(self):
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)

        frame, items = ss.section('Keyboard')
        items.addWidget(ss.label('Drop ALT', ss.SMALL, role='dim'))
        row, self.keyboard = ss.switch(SYNC, KEYBOARD_SYNC_ABOUT, True)
        self.keyboard.toggled.connect(self.keyboard_sync.emit)
        items.addWidget(row)
        column.addWidget(frame)

        self.memory = PartControls('ram', 'Memory')
        self.install = QPushButton('Install service')
        self.install.clicked.connect(lambda: self._setup('--install'))
        self.memory.add_button(self.install)
        self.board = PartControls('board', 'Motherboard')
        for part in (self.memory, self.board):
            part.changed.connect(self.lighting.emit)
            column.addWidget(part)
        column.addStretch(1)
        self._answer = ram.Answer(ram.STARTING)
        self._icue = False
        self._installing = False
        self.show_memory(self._answer)
        self.show_board(None)

    def fill(self, parts: dict, keyboard_sync: bool = True) -> None:
        self.keyboard.blockSignals(True)
        self.keyboard.setChecked(keyboard_sync)
        self.keyboard.blockSignals(False)
        self.memory.fill(parts['ram'])
        self.board.fill(parts['board'])

    def _setup(self, action: str) -> None:
        if not ram.dotnet():
            self.memory.found(self.memory.where.text(), False,
                              'The Keyglow Lights service requires the Microsoft .NET 10 Desktop Runtime, which is '
                              'not installed.')
            return
        self._installing = True
        self.install.setEnabled(False)
        self.memory.found('Waiting for administrator approval.', False)
        self.setup_asked.emit(action)

    def setup_done(self, words: str) -> None:
        self._installing = False
        self.install.setEnabled(True)
        self.show_memory(self._answer, words)

    def show_icue(self, running: bool) -> None:
        self._icue = running
        self.show_memory(self._answer)

    def show_memory(self, answer: ram.Answer, problem: str = '') -> None:
        self._answer = answer
        if self._installing:
            return
        status = answer.status
        found = status == ram.READY
        update = found and ram.outdated()
        self.install.setText('Update service' if update else 'Install service')
        self.install.setVisible(status == ram.NOT_INSTALLED or update)
        if status == ram.READY:
            where = _sticks(answer.sticks)
        elif status == ram.NOT_INSTALLED:
            where = ('Memory lighting requires the Keyglow Lights service, which accesses the SMBus through PawnIO '
                     'and runs only while lighting changes. Installation requires administrator approval.')
        elif status == ram.NO_PAWNIO:
            where = ''
            problem = problem or 'The Keyglow Lights service requires PawnIO, which is not installed (pawnio.eu).'
        elif status == ram.NO_MEMORY:
            where = 'No supported RGB memory detected. Supported: Corsair Vengeance RGB, Dominator Platinum RGB, ' \
                    'Dominator Titanium RGB.'
        elif status == ram.FAILED:
            where = ''
            problem = problem or f'The Keyglow Lights service could not access the memory: {answer.message}.'
        else:
            where = 'Detecting memory.'
        if found and self._icue and not problem:
            problem = 'Corsair iCUE is running and overrides memory lighting. Close iCUE and disable it at startup.'
        self.memory.found(where, found, problem)

    def show_board(self, zones) -> None:
        if zones is None:
            self.board.found('No supported motherboard detected. Supported: ASRock Polychrome RGB.', False)
            return
        self.board.found('ASRock Polychrome RGB: ' + ', '.join(zone.name for zone in zones), True)
