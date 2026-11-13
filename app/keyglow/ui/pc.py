"""The device pages beside the keyboard's - Memory and Motherboard, each with its RGB Sync switch and
a lighting of its own - and the RGB Sync page, which sets the lighting the synced devices share."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSlider, QVBoxLayout, QWidget

from .. import pc, ram
from .. import state as st
from . import suitesettings as ss

SYNC = 'RGB Sync'
SYNC_ABOUT = 'Uses the lighting shared by all synced devices. Set on the RGB Sync page while two or more ' \
             'devices are synced.'
OFF = 0                 # an Effect list's first choice: the device's lighting off


def _slider(changed, least: int = 160) -> QSlider:
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 255)
    slider.setMinimumWidth(least)
    slider.valueChanged.connect(changed)
    return slider


class _Lighting(QWidget):
    """An effect, its colours, speed and brightness, in two columns: the effect and its colours,
    then its speed and brightness. effects: number -> (name, ..., (first colour, second colour,
    speed)) - the needs last."""

    changed = Signal()

    def __init__(self, effects: dict):
        super().__init__()
        from .window import ColorButton
        self.effects = effects
        self._filling = False
        self._colours = {'a': pc.PINK, 'b': pc.ROSE}
        self.form, self.form2 = ss.form(), ss.form()
        self.effect = QComboBox()
        self.effect.addItem('Off', OFF)
        for number, entry in effects.items():
            self.effect.addItem(entry[0], number)
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
        self.form2.addRow(self.speed_name, self.speed)
        self.bright = _slider(self._changed)
        self.form2.addRow(ss.label('Brightness'), self.bright)
        columns = QHBoxLayout(self)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(32)
        columns.addLayout(self.form, 1)
        columns.addLayout(self.form2, 1)
        columns.setAlignment(self.form, Qt.AlignTop)
        columns.setAlignment(self.form2, Qt.AlignTop)

    @property
    def colours(self) -> tuple:
        return self._colours['a'], self._colours['b']

    def fill(self, effect: int, a, b, speed: int, bright: int) -> None:
        self._filling = True
        try:
            index = self.effect.findData(effect)
            self.effect.setCurrentIndex(index if index >= 0 else 1)
            self._colours = {'a': tuple(a), 'b': tuple(b)}
            self.a.set_color(a)
            self.b.set_color(b)
            self.speed.setValue(speed)
            self.bright.setValue(bright)
        finally:
            self._filling = False
        self._shown()

    def _shown(self) -> None:
        effect = self.effect.currentData()
        first, second, speed = self.effects[effect][-1] if effect in self.effects else (None, None, False)
        on = effect != OFF
        for form, widget, name, show in ((self.form, self.a, self.a_name, first),
                                         (self.form, self.b, self.b_name, second),
                                         (self.form2, self.speed, self.speed_name, speed)):
            form.setRowVisible(widget, bool(show))
            if isinstance(show, str):
                name.setText(show)
        for form in (self.form, self.form2):
            for i in range(form.rowCount()):
                for role in (form.ItemRole.LabelRole, form.ItemRole.FieldRole):
                    item = form.itemAt(i, role)
                    if item and item.widget() and item.widget() is not self.effect:
                        item.widget().setEnabled(on)

    def _changed(self, *_) -> None:
        self._shown()
        if not self._filling:
            self.changed.emit()

    def _colour(self, which: str, rgb) -> None:
        self._colours[which] = tuple(rgb)
        (self.a if which == 'a' else self.b).set_color(rgb)
        if not self._filling:
            self.changed.emit()


class PartControls(QWidget):
    """A device's page: what was detected, its RGB Sync switch, and its own lighting - shown while
    the device isn't showing the shared lighting."""

    changed = Signal(str, object)       # the part, its setting (pc.Part)

    def __init__(self, part: str, title: str):
        super().__init__()
        self.part = part
        self._filling = False
        self._own_shown = True
        self._effect = next(iter(pc.EFFECTS[part]))     # the effect kept while Off is chosen
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
        rows = QVBoxLayout(self.settings)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(ss.ITEMS)
        row, self.sync = ss.switch(SYNC, SYNC_ABOUT, True)
        self.sync.toggled.connect(self._changed)
        rows.addWidget(row)
        items.addWidget(self.settings)
        column.addWidget(self.frame)

        self.own_frame, items = ss.section('Lighting')
        self.own = _Lighting(pc.EFFECTS[part])
        self.own.changed.connect(self._changed)
        items.addWidget(self.own)
        column.addWidget(self.own_frame)
        column.addStretch(1)
        self._found = False
        self._place()

    # kept for the tests and the window: the controls inside the lighting section
    @property
    def effect(self):
        return self.own.effect

    def add_button(self, button: QPushButton) -> None:
        button.setCursor(Qt.PointingHandCursor)
        self.buttons.insertWidget(self.buttons.count() - 1, button)

    def found(self, where: str, found: bool, problem: str = '') -> None:
        """What was detected (or why nothing was): the settings show only for a device present."""
        self._found = found
        self.where.setText(where)
        self.where.setVisible(bool(where))
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        self._place()

    def show_own(self, shown: bool) -> None:
        """Its own lighting shows while it isn't showing the shared one."""
        self._own_shown = shown
        self._place()

    def _place(self) -> None:
        self.settings.setVisible(self._found)
        self.own_frame.setVisible(self._found and self._own_shown)

    def lighting(self) -> pc.Part:
        effect = self.own.effect.currentData()
        on = effect != OFF
        if on:
            self._effect = effect
        a, b = self.own.colours
        return pc.Part(sync=self.sync.isChecked(), on=on, effect=self._effect, a=a, b=b,
                       speed=self.own.speed.value(), bright=self.own.bright.value())

    def fill(self, part: pc.Part) -> None:
        self._filling = True
        try:
            self.sync.setChecked(part.sync)
            if part.effect in pc.EFFECTS[self.part]:
                self._effect = part.effect
            self.own.fill(part.effect if part.on else OFF, part.a, part.b, part.speed, part.bright)
        finally:
            self._filling = False

    def _changed(self, *_) -> None:
        if not self._filling:
            self.changed.emit(self.part, self.lighting())


def _sticks(sticks) -> str:
    names = Counter(stick.name for stick in sticks)
    return ', '.join(f'{name} × {count}' for name, count in names.items())


class Devices(QObject):
    """The Memory and Motherboard pages, and what each shows of its device's state."""

    lighting = Signal(str, object)      # the memory's or the motherboard's setting changed
    setup_asked = Signal(str)           # '--install' or '--uninstall'

    def __init__(self):
        super().__init__()
        self.memory = PartControls('ram', 'Memory')
        self.install = QPushButton('Install service')
        self.install.clicked.connect(lambda: self._setup('--install'))
        self.memory.add_button(self.install)
        self.board = PartControls('board', 'Motherboard')
        for part in (self.memory, self.board):
            part.changed.connect(self.lighting.emit)
        self._answer = ram.Answer(ram.STARTING)
        self._icue = False
        self._installing = False
        self.zones = None
        self.show_memory(self._answer)
        self.show_board(None)

    def fill(self, parts: dict) -> None:
        self.memory.fill(parts['ram'])
        self.board.fill(parts['board'])

    def names(self) -> dict:
        """Each detected device's name, for the RGB Sync page."""
        names = {}
        if self._answer.status == ram.READY:
            names['ram'] = _sticks(self._answer.sticks)
        if self.zones is not None:
            names['board'] = 'ASRock Polychrome RGB'
        return names

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
        self.zones = zones
        if zones is None:
            self.board.found('No supported motherboard detected. Supported: ASRock Polychrome RGB.', False)
            return
        self.board.found('ASRock Polychrome RGB: ' + ', '.join(zone.name for zone in zones), True)


class SyncPage(QWidget):
    """RGB Sync: which devices share the lighting, the lighting itself, and themes for it."""

    changed = Signal(object)            # the shared lighting set here (st.State)

    def __init__(self, themes: QWidget):
        super().__init__()
        self._lighting = st.State()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)
        frame, items = ss.section('Synced devices')
        self.members = ss.label('', ss.SMALL, role='dim', wrap=True)
        items.addWidget(self.members)
        column.addWidget(frame)
        frame, items = ss.section('Lighting')
        self.editor = _Lighting(pc.SYNC_EFFECTS)
        self.editor.changed.connect(self._changed)
        items.addWidget(self.editor)
        column.addWidget(frame)
        frame, items = ss.section('Themes')
        items.addWidget(themes)
        column.addWidget(frame)
        column.addStretch(1)

    def show_members(self, names: list) -> None:
        self.members.setText(', '.join(names))

    def fill(self, lighting: st.State) -> None:
        """Shows the shared lighting: the nearest of this page's effects, and its colours."""
        self._lighting = lighting.copy()
        effect = pc.sync_effect(lighting)
        zone = lighting.keys if lighting.on & st.ON_KEYS or not lighting.on & st.ON_EDGE else lighting.edge
        self.editor.fill(effect, zone.a, zone.b, zone.speed, lighting.master * zone.bright // 255)

    def _changed(self) -> None:
        editor = self.editor
        a, b = editor.colours
        self._lighting = pc.sync_lighting(self._lighting, editor.effect.currentData(), a, b, editor.speed.value(),
                                          editor.bright.value())
        self.changed.emit(self._lighting.copy())
