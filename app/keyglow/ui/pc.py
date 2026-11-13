"""The PC tab: the memory's and the motherboard's lights, each following the keyboard or set on
its own."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSlider, QVBoxLayout, QWidget

from .. import pc, ram
from . import suitesettings as ss

SYNC_ABOUT = "Takes the keys' effect and colours, or the base light's while the keys are off."


def _slider(changed) -> QSlider:
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 255)
    slider.setMinimumWidth(220)
    slider.valueChanged.connect(changed)
    return slider


class PartControls(QWidget):
    """One part: what was found, whether it follows the keyboard, and its own effect if not."""

    changed = Signal(str, object)       # the part, its own lighting (pc.Part)

    def __init__(self, part: str, title: str, light_words: str):
        super().__init__()
        from .window import ColorButton
        self.part = part
        self.effects = pc.EFFECTS[part]
        self._filling = False
        self._found = False
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
        row, self.sync = ss.switch('Same as the keyboard', SYNC_ABOUT, True)
        self.sync.toggled.connect(self._changed)
        rows_column.addWidget(row)
        self.own = QWidget()
        own = QVBoxLayout(self.own)
        own.setContentsMargins(0, 0, 0, 0)
        own.setSpacing(ss.ITEMS)
        row, self.on = ss.switch(light_words, '', True)
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
        """What was found (or why nothing): the settings show only for a part that is there."""
        self._found = found
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
    return ', '.join(f'{count} {name} stick' + ('s' if count > 1 else '') for name, count in names.items())


class PcPage(QWidget):
    """The memory and the motherboard."""

    lighting = Signal(str, object)      # a part's own lighting changed (sync or not)
    setup_asked = Signal(str)           # '--install' or '--uninstall'

    def __init__(self):
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)
        self.memory = PartControls('ram', 'Memory', 'Light the memory')
        self.install = QPushButton('Install Keyglow Lights')
        self.install.clicked.connect(lambda: self._setup('--install'))
        self.memory.add_button(self.install)
        self.board = PartControls('board', 'Motherboard', 'Light the motherboard')
        for part in (self.memory, self.board):
            part.changed.connect(self.lighting.emit)
            column.addWidget(part)
        column.addStretch(1)
        self._answer = ram.Answer(ram.STARTING)
        self._icue = False
        self._installing = False
        self.show_memory(self._answer)
        self.show_board(None)

    def fill(self, parts: dict) -> None:
        self.memory.fill(parts['ram'])
        self.board.fill(parts['board'])

    def _setup(self, action: str) -> None:
        if not ram.dotnet():
            self.memory.found(self.memory.where.text(), False,
                              "Keyglow Lights runs on Microsoft's .NET 10 runtime, which isn't installed. Install "
                              "the .NET 10 Desktop Runtime from Microsoft, then try again.")
            return
        self._installing = True
        self.install.setEnabled(False)
        self.memory.found('Windows asks for permission to install Keyglow Lights.', False)
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
        install = status == ram.NOT_INSTALLED or (found and ram.outdated())
        self.install.setText('Update Keyglow Lights' if status != ram.NOT_INSTALLED else 'Install Keyglow Lights')
        self.install.setVisible(install)
        if status == ram.READY:
            where = _sticks(answer.sticks)
        elif status == ram.NOT_INSTALLED:
            where = ('Keyglow reaches the memory through Keyglow Lights, a small service of its own that runs '
                     'only while the lighting changes. Windows asks for permission to install it.')
        elif status == ram.NO_PAWNIO:
            where = ''
            problem = problem or ('Keyglow Lights reaches the memory through PawnIO, which isn’t installed. '
                                  'FanControl installs it, or get it from pawnio.eu.')
        elif status == ram.NO_MEMORY:
            where = 'No RGB memory Keyglow knows was found. It knows Corsair Vengeance RGB and Dominator sticks.'
        elif status == ram.FAILED:
            where = ''
            problem = problem or f'Keyglow Lights couldn’t reach the memory: {answer.message}.'
        else:
            where = 'Looking for the memory.'
        if found and self._icue and not problem:
            problem = ('iCUE is running, and it sets the memory’s lights itself over Keyglow’s. Quit it, '
                       'and turn off its start with Windows.')
        self.memory.found(where, found, problem)

    def show_board(self, zones) -> None:
        if zones is None:
            self.board.found('No ASRock Polychrome motherboard found.', False)
            return
        names = [zone.name for zone in zones]
        self.board.found('ASRock Polychrome: ' + ', '.join(names), True)
