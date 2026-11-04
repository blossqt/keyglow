"""Keyglow's window: the keyboard drawn at the top, lit as it is; under it the keys' and the base
light's settings, which the keyboard follows as they change. Until the ALT runs Keyglow's
firmware, the settings make way for setting it up."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from .. import __version__, device, flasher, presets
from .. import state as st
from . import suiteicons, suitesettings as ss
from . import theme
from .board import Board
from .icons import app_icon
from .hotkeys import GROUPS as HOTKEYS, HotkeysPage
from .themes import ThemesPage

SWATCHES = ['#ffffff', '#ffd1dc', '#c2255c', '#ff2a2a', '#ff7a00', '#ffd400', '#3ddc5a', '#00d5ff',
            '#2a6bff', '#8b3dff', '#ff3dd8', '#000000']


class ColorButton(QPushButton):
    """A colour to choose: the button shows it; a click opens a colour picker whose every move the
    keyboard shows at once."""

    def __init__(self, changed):
        super().__init__()
        self._changed = changed
        self._color = QColor('#ffffff')
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        self.setMinimumWidth(120)
        self.clicked.connect(self._choose)
        theme.restyle(self, self._style)

    def set_color(self, rgb) -> None:
        self._color = QColor(*rgb)
        self.setText(self._color.name().upper())
        self.setIcon(self._swatch())
        self.update()

    def _swatch(self):
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._color)
        p.setPen(QColor(0, 0, 0, 60))
        p.drawEllipse(1, 1, 14, 14)
        p.end()
        return QIcon(pixmap)

    def _style(self) -> str:
        return 'QPushButton { text-align: left; padding-left: 10px; }'

    def _choose(self) -> None:
        before = QColor(self._color)
        dialog = QColorDialog(self._color, self.window())
        dialog.setWindowTitle('Choose a colour')
        dialog.setOption(QColorDialog.DontUseNativeDialog, True)
        dialog.currentColorChanged.connect(lambda c: self._changed(c.getRgb()[:3]))
        if dialog.exec() == QColorDialog.Accepted:
            self._changed(dialog.selectedColor().getRgb()[:3])
        else:
            self._changed(before.getRgb()[:3])


def _slider(changed) -> QSlider:
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 255)
    slider.setMinimumWidth(220)
    slider.valueChanged.connect(changed)
    return slider


class ZoneControls(QWidget):
    """The settings of one part: the keys, or the base light."""

    def __init__(self, window: 'Window', part: str):
        super().__init__()
        self.window_ = window
        self.part = part
        self.effects = st.KEY_EFFECTS if part == 'keys' else st.EDGE_EFFECTS
        self.needs = st.KEY_NEEDS if part == 'keys' else st.EDGE_NEEDS
        self._filling = False

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)
        frame, items = ss.section('')
        column.addWidget(frame)
        title = 'Light the keys' if part == 'keys' else 'Light the base'
        row, self.on = ss.switch(title, '', True)
        self.on.toggled.connect(self._changed)
        items.addWidget(row)

        rows = ss.form()
        self.form = rows
        self.effect = QComboBox()
        for number, name in self.effects.items():
            self.effect.addItem(name, number)
        self.effect.currentIndexChanged.connect(self._changed)
        rows.addRow(ss.label('Effect'), self.effect)
        self.a = ColorButton(lambda rgb: self._colour('a', rgb))
        self.a_name = ss.label('Colour')
        rows.addRow(self.a_name, self.a)
        self.b = ColorButton(lambda rgb: self._colour('b', rgb))
        self.b_name = ss.label('Second colour')
        rows.addRow(self.b_name, self.b)
        self.speed = _slider(self._changed)
        self.speed_name = ss.label('Speed')
        rows.addRow(self.speed_name, self.speed)
        self.bright = _slider(self._changed)
        rows.addRow(ss.label('Brightness'), self.bright)
        items.addLayout(rows)

        # per-key colours: keys picked on the picture take a colour from here
        self.per_key = QWidget()
        per = QVBoxLayout(self.per_key)
        per.setContentsMargins(0, 0, 0, 0)
        per.setSpacing(ss.ITEMS)
        self.pick_note = ss.note('Click keys on the picture to pick them. Ctrl or Shift and a click '
                                 'picks more, and dragging a box picks every key in it. Then choose a colour.')
        per.addWidget(self.pick_note)
        swatches = QHBoxLayout()
        swatches.setSpacing(8)
        for colour in SWATCHES:
            swatches.addWidget(self._swatch_button(colour))
        swatches.addSpacing(8)
        self.more = QPushButton('More colours')
        self.more.setIcon(suiteicons.icon('palette', theme.colors().text))
        self.more.setCursor(Qt.PointingHandCursor)
        self.more.clicked.connect(self._more_colours)
        swatches.addWidget(self.more)
        swatches.addStretch(1)
        per.addLayout(swatches)
        picks = QHBoxLayout()
        picks.setSpacing(8)
        self.all_button = QPushButton('Pick all keys')
        self.all_button.clicked.connect(lambda: self.window_.board.pick_all())
        self.none_button = QPushButton('Pick none')
        self.none_button.clicked.connect(lambda: self.window_.board._pick(set()))
        for button in (self.all_button, self.none_button):
            button.setCursor(Qt.PointingHandCursor)
            picks.addWidget(button)
        picks.addStretch(1)
        per.addLayout(picks)
        items.addWidget(self.per_key)
        self.per_key.setVisible(False)
        column.addStretch(1)

    def zone(self) -> st.Zone:
        return getattr(self.window_.state, self.part)

    def fill(self) -> None:
        """Shows the window's state."""
        self._filling = True
        try:
            zone = self.zone()
            bit = st.ON_KEYS if self.part == 'keys' else st.ON_EDGE
            self.on.setChecked(bool(self.window_.state.on & bit))
            index = self.effect.findData(zone.mode)
            self.effect.setCurrentIndex(index if index >= 0 else 0)
            self.a.set_color(zone.a)
            self.b.set_color(zone.b)
            self.speed.setValue(zone.speed)
            self.bright.setValue(zone.bright)
        finally:
            self._filling = False
        self._shown()

    def _shown(self) -> None:
        """Only what the chosen effect uses is shown."""
        on = self.on.isChecked()
        mode = self.effect.currentData()
        first, second, speed = self.needs.get(mode, (None, None, False))
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
        per_key = self.part == 'keys' and mode == st.KEY_CUSTOM
        self.per_key.setVisible(per_key)
        self.per_key.setEnabled(on)
        if self.part == 'keys':
            self.window_.board.set_picking(per_key and on)

    def _changed(self, *_) -> None:
        if self._filling:
            return
        state = self.window_.state
        zone = self.zone()
        zone.mode = self.effect.currentData()
        zone.speed = self.speed.value()
        zone.bright = self.bright.value()
        bit = st.ON_KEYS if self.part == 'keys' else st.ON_EDGE
        state.on = (state.on | bit) if self.on.isChecked() else (state.on & ~bit)
        self._shown()
        self.window_.changed()

    def _colour(self, which: str, rgb) -> None:
        setattr(self.zone(), which, tuple(rgb))
        (self.a if which == 'a' else self.b).set_color(rgb)
        self.window_.changed()

    def _swatch_button(self, colour: str) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(26, 26)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(colour.upper())
        button.setObjectName('swatch')
        button.setStyleSheet(f'QPushButton#swatch {{ background: {colour}; border-radius: 13px; '
                             f'border: 1px solid rgba(128,128,128,110); padding: 0; }}'
                             f'QPushButton#swatch:hover {{ border: 2px solid {theme.ROSE}; }}')
        button.clicked.connect(lambda: self.window_.paint_keys(QColor(colour).getRgb()[:3]))
        return button

    def _more_colours(self) -> None:
        keys = self.window_.board.picked_keys
        start = QColor(*self.window_.state.perkey[min(keys)]) if keys else QColor('#ffffff')
        before = list(self.window_.state.perkey)
        dialog = QColorDialog(start, self.window())
        dialog.setWindowTitle('Choose a colour')
        dialog.setOption(QColorDialog.DontUseNativeDialog, True)
        dialog.currentColorChanged.connect(lambda c: self.window_.paint_keys(c.getRgb()[:3]))
        if dialog.exec() == QColorDialog.Accepted:
            self.window_.paint_keys(dialog.selectedColor().getRgb()[:3])
        else:
            self.window_.state.perkey = before
            self.window_.changed()


class _Hover(QObject):
    """Shows a light on the picture while the pointer is over its setting."""

    def __init__(self, board: Board, which: str, parent):
        super().__init__(parent)
        self.board, self.which = board, which

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Enter:
            self.board.show_light(self.which)
        elif event.type() == QEvent.Leave and self.board.showing == self.which:
            self.board.show_light('')
        return False


def _minutes(n: int) -> str:
    return '1 minute' if n == 1 else f'{n} minutes'


class KeyboardControls(QWidget):
    """Caps Lock's light, the Fn layer's, and lights off when idle - and, on a keyboard whose
    Keyglow firmware is older than these, the update that brings them."""

    def __init__(self, window: 'Window'):
        super().__init__()
        self.window_ = window
        self._filling = False
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)

        self.update_frame, items = ss.section('Firmware update')
        self.update_words = ss.label('', wrap=True)
        items.addWidget(self.update_words)
        items.addWidget(ss.note('The keyboard goes dark and stops typing for about half a minute while the '
                                'firmware is written.'))
        row = QHBoxLayout()
        self.update_button = QPushButton('Update firmware')
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.clicked.connect(window.update_firmware)
        row.addWidget(self.update_button)
        row.addStretch(1)
        items.addLayout(row)
        self.update_problem = ss.label('', ss.SMALL, role='error', wrap=True)
        self.update_problem.hide()
        items.addWidget(self.update_problem)
        column.addWidget(self.update_frame)

        self.caps_frame, items = ss.section('')
        row, self.caps_on = ss.switch('Light Caps Lock while it is on',
                                      'Its colour shows on Caps Lock and on the keys right of it and below it.',
                                      True)
        self.caps_on.toggled.connect(self._changed)
        items.addWidget(row)
        rows = ss.form()
        self.caps = ColorButton(lambda rgb: self._colour('caps', rgb))
        rows.addRow(ss.label('Colour'), self.caps)
        items.addLayout(rows)
        column.addWidget(self.caps_frame)

        self.fn_frame, items = ss.section('')
        row, self.fn_on = ss.switch('Light the Fn layer while Fn is held',
                                    'The keys that do something with Fn light up, and the rest go dark.', True)
        self.fn_on.toggled.connect(self._changed)
        items.addWidget(row)
        rows = ss.form()
        self.fn = ColorButton(lambda rgb: self._colour('fn', rgb))
        rows.addRow(ss.label('Colour'), self.fn)
        items.addLayout(rows)
        column.addWidget(self.fn_frame)

        self.idle_frame, items = ss.section('')
        row, self.idle_on = ss.switch('Turn the lights off when idle',
                                      'They come back on with the next key press.', True)
        self.idle_on.toggled.connect(self._changed)
        items.addWidget(row)
        rows = ss.form()
        self.idle = QComboBox()
        for n in st.IDLE_CHOICES:
            self.idle.addItem(_minutes(n), n)
        self.idle.currentIndexChanged.connect(self._changed)
        rows.addRow(ss.label('After'), self.idle)
        items.addLayout(rows)
        column.addWidget(self.idle_frame)
        column.addStretch(1)

        for frame, which in ((self.caps_frame, 'caps'), (self.fn_frame, 'fn')):
            frame.installEventFilter(_Hover(window.board, which, frame))
        self.set_outdated(False)

    def set_outdated(self, outdated: bool, missing: bool = False) -> None:
        """outdated: Keyglow carries newer firmware than the keyboard's; missing: the keyboard's
        doesn't have these settings at all (Keyglow's first)."""
        self.update_frame.setVisible(outdated)
        self.update_words.setText(
            'These settings need the newer Keyglow firmware on the keyboard. Your lighting stays as it is.'
            if missing else
            'Keyglow has newer firmware for the keyboard: Caps Lock lights in the colour you choose, and on '
            'the keys right of it and below it too, so it shows past its keycap. Your lighting stays as it is.')
        for frame in (self.caps_frame, self.fn_frame, self.idle_frame):
            frame.setEnabled(not missing)

    def fill(self) -> None:
        state = self.window_.state
        self._filling = True
        try:
            self.caps_on.setChecked(bool(state.extras & st.X_CAPS))
            self.fn_on.setChecked(bool(state.extras & st.X_FN))
            self.caps.set_color(state.caps)
            self.fn.set_color(state.fn)
            self.idle_on.setChecked(state.idle > 0)
            index = self.idle.findData(state.idle)
            if index < 0:
                index = self.idle.findData(10)
                if state.idle:          # a number from elsewhere: shown as it is
                    self.idle.addItem(_minutes(state.idle), state.idle)
                    index = self.idle.count() - 1
            self.idle.setCurrentIndex(index)
        finally:
            self._filling = False
        self._shown()

    def _shown(self) -> None:
        self.caps.setEnabled(self.caps_on.isChecked())
        self.fn.setEnabled(self.fn_on.isChecked())
        self.idle.setEnabled(self.idle_on.isChecked())

    def _changed(self, *_) -> None:
        if self._filling:
            return
        state = self.window_.state
        state.extras = (st.X_CAPS if self.caps_on.isChecked() else 0) | (st.X_FN if self.fn_on.isChecked() else 0)
        state.idle = self.idle.currentData() if self.idle_on.isChecked() else 0
        self._shown()
        self.window_.changed()

    def _colour(self, which: str, rgb) -> None:
        setattr(self.window_.state, which, tuple(rgb))
        (self.caps if which == 'caps' else self.fn).set_color(rgb)
        self.window_.board.show_light(which)
        self.window_.changed()


class Window(QWidget):
    def __init__(self, link, parent=None):
        super().__init__(parent)
        self.link = link
        self.state = st.State()
        self.status = device.ABSENT
        self.flash: flasher.Flash | None = None
        self.setWindowTitle('Keyglow')
        self.setWindowIcon(app_icon())
        self.setObjectName('settings')
        self.setFont(theme.font(ss.BODY))
        self.resize(1040, 800)
        self.setMinimumSize(800, 700)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(ss.heading('Keyglow', theme.TYPE['title']))
        top.addStretch(1)
        self.where = ss.label('', ss.SMALL, role='dim')
        top.addWidget(self.where)
        top.addSpacing(8)
        self.master_name = ss.label('Overall brightness')
        top.addWidget(self.master_name)
        self.master = _slider(self._master)
        self.master.setMinimumWidth(160)
        top.addWidget(self.master)
        outer.addLayout(top)

        self.board = Board()
        self.board.setMinimumHeight(250)
        self.board.setMaximumHeight(340)
        outer.addWidget(self.board, 4)

        self.pages = theme.Pages()
        outer.addWidget(self.pages, 5)
        self.pages.addWidget(self._controls_page())     # 0
        self.pages.addWidget(self._setup_page())        # 1
        self.empty = ss.Empty('keyboard', 'Plug in your ALT',
                              'Keyglow looks for a Drop ALT on USB, and finds it as soon as it is plugged in.')
        self.pages.addWidget(self.empty)                # 2
        self.pages.addWidget(self._flash_page())        # 3

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.defaults_button = QPushButton('Reset lighting')
        self.defaults_button.clicked.connect(self._defaults)
        foot.addWidget(self.defaults_button)
        foot.addStretch(1)
        self.restore_button = QPushButton('Put back the original firmware')
        self.restore_button.clicked.connect(self._restore)
        foot.addWidget(self.restore_button)
        version = ss.label(f'Keyglow {__version__}', ss.SMALL, role='dim')
        foot.addSpacing(8)
        foot.addWidget(version)
        outer.addLayout(foot)
        for button in (self.defaults_button, self.restore_button):
            button.setCursor(Qt.PointingHandCursor)

        theme.restyle(self, ss.style)
        theme.frost(self)
        link.status.connect(self._status)
        link.loaded.connect(self._loaded)
        link.failed.connect(lambda words: None)     # a lost keyboard shows as such; nothing to say
        QShortcut(QKeySequence.SelectAll, self, activated=self.board.pick_all)
        ss.shortcut_sheet(self, 'Keyglow', HOTKEYS)
        self._status(device.ABSENT)
        self.keys_controls.fill()
        self.edge_controls.fill()
        self.keyboard_controls.fill()
        self.master.setValue(self.state.master)
        self.themes.mark(self.state)

    # --- pages ------------------------------------------------------------------------------

    def _controls_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        self.themes_tab = QPushButton('Themes')
        self.keys_tab = QPushButton('Keys')
        self.edge_tab = QPushButton('Base light')
        self.keyboard_tab = QPushButton('Keyboard')
        self.hotkeys_tab = QPushButton('Hotkeys')
        self.tabs = ss.Segmented([self.themes_tab, self.keys_tab, self.edge_tab, self.keyboard_tab,
                                  self.hotkeys_tab])
        self.themes_tab.setChecked(True)
        column.addWidget(self.tabs, 0, Qt.AlignLeft)
        self.zone_pages = theme.Pages()
        self.themes = ThemesPage()
        self.themes.chosen.connect(self.use_theme)
        self.themes.save_asked.connect(self._save_theme)
        self.themes.rename_asked.connect(self._rename_theme)
        self.themes.delete_asked.connect(self._delete_theme)
        self.themes.show_saved(presets.saved())
        self.keys_controls = ZoneControls(self, 'keys')
        self.edge_controls = ZoneControls(self, 'edge')
        self.zone_pages.addWidget(ss.scrolled(self.themes))
        self.zone_pages.addWidget(ss.scrolled(self.keys_controls))
        self.zone_pages.addWidget(ss.scrolled(self.edge_controls))
        self.keyboard_controls = KeyboardControls(self)
        self.zone_pages.addWidget(ss.scrolled(self.keyboard_controls))
        self.hotkeys = HotkeysPage()
        self.zone_pages.addWidget(ss.scrolled(self.hotkeys))
        # one tab at a time: without the group, the tab just left stayed checked, and a click on it
        # unchecked it rather than going back to it
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for n, tab in enumerate((self.themes_tab, self.keys_tab, self.edge_tab, self.keyboard_tab,
                                 self.hotkeys_tab)):
            self.tab_group.addButton(tab, n)
            tab.toggled.connect(lambda on, n=n: on and self.zone_pages.setCurrentIndex(n))
        column.addWidget(self.zone_pages, 1)
        return page

    def _setup_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        frame, items = ss.section('Set up your ALT')
        items.addWidget(ss.label(
            'To change the lighting from here, Keyglow puts its own firmware on the keyboard. The keys '
            "stay on Drop's default layout, so any keys you remapped in Drop's configurator go back to "
            'normal. The firmware it has now is saved on this PC first, and you can put it back from '
            'here at any time.', wrap=True))
        items.addWidget(ss.note(
            'After you click Set up, hold Fn and B for a second. The keyboard goes dark and stops typing '
            'for about half a minute while the firmware is written. If it doesn\'t go dark, press the '
            'reset button through the small hole on its underside with a paperclip.'))
        row = QHBoxLayout()
        self.setup_button = QPushButton('Set up')
        self.setup_button.setCursor(Qt.PointingHandCursor)
        self.setup_button.clicked.connect(self._install)
        row.addWidget(self.setup_button)
        row.addStretch(1)
        items.addLayout(row)
        self.setup_problem = ss.label('', ss.SMALL, role='error', wrap=True)
        self.setup_problem.hide()
        items.addWidget(self.setup_problem)
        column.addWidget(frame)
        column.addStretch(1)
        return page

    def _flash_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        frame, items = ss.section('')
        self.flash_title = ss.heading('', theme.TYPE['heading'] + 2)
        items.addWidget(self.flash_title)
        self.flash_step = ss.label('', wrap=True)
        items.addWidget(self.flash_step)
        self.flash_note = ss.note('Leave the keyboard plugged in until this is done.')
        items.addWidget(self.flash_note)
        row = QHBoxLayout()
        self.flash_cancel = QPushButton('Cancel')
        self.flash_cancel.setCursor(Qt.PointingHandCursor)
        self.flash_cancel.clicked.connect(self._cancel_flash)
        row.addWidget(self.flash_cancel)
        row.addStretch(1)
        items.addLayout(row)
        column.addWidget(frame)
        column.addStretch(1)
        return page

    # --- the keyboard -----------------------------------------------------------------------

    def _status(self, status: str) -> None:
        self.status = status
        if self.flash is not None:
            return
        words = {device.ABSENT: 'No ALT found', device.STOCK: 'ALT found, not set up',
                 device.READY: 'ALT connected, new firmware ready' if self.link.outdated else 'ALT connected'}
        self.where.setText(words[status])
        ready = status == device.READY
        self.pages.setCurrentIndex({device.READY: 0, device.STOCK: 1, device.ABSENT: 2}[status])
        self.board.set_dim(not ready)
        for widget in (self.master, self.master_name, self.defaults_button):
            widget.setVisible(ready)
        self.restore_button.setVisible(ready and flasher.backup().is_file())

    def _loaded(self, state: st.State) -> None:
        self.state = state
        self.keys_controls.fill()
        self.edge_controls.fill()
        self.keyboard_controls.fill()
        self.keyboard_controls.set_outdated(self.link.outdated, self.link.missing)
        if self.flash is None and self.status == device.READY:
            self.where.setText('ALT connected, new firmware ready' if self.link.outdated else 'ALT connected')
        self.master.blockSignals(True)
        self.master.setValue(state.master)
        self.master.blockSignals(False)
        self.board.show_state(state)
        self.themes.mark(state)

    def changed(self) -> None:
        """The window's lighting changed: the picture and the keyboard follow."""
        self.board.show_state(self.state)
        self.themes.mark(self.state)
        self.link.want(self.state)

    def use_theme(self, choice) -> None:
        self.state = choice.apply(self.state)
        self.keys_controls.fill()
        self.edge_controls.fill()
        self.changed()

    # --- the user's own themes ----------------------------------------------------------------

    def _ask_name(self, title: str, start: str) -> str:
        name, ok = QInputDialog.getText(self, title, 'Name', QLineEdit.Normal, start)
        return name.strip() if ok else ''

    def _save_theme(self) -> None:
        taken = {t.name for t in presets.saved()}
        n = len(taken) + 1
        while f'My theme {n}' in taken:
            n += 1
        name = self._ask_name('Save theme', f'My theme {n}')
        if not name:
            return
        if name in taken and QMessageBox.question(
                self, 'Save theme', f'Replace your theme "{name}" with the lighting as it is now?') != QMessageBox.Yes:
            return
        self.save_theme(name)

    def save_theme(self, name: str) -> None:
        presets.save(name, self.state)
        self.themes.show_saved(presets.saved())

    def _rename_theme(self, name: str) -> None:
        new = self._ask_name('Rename theme', name)
        if not new or new == name:
            return
        if new in {t.name for t in presets.saved()} and QMessageBox.question(
                self, 'Rename theme', f'You already have a theme called "{new}". Replace it?') != QMessageBox.Yes:
            return
        presets.rename(name, new)
        self.themes.show_saved(presets.saved())

    def _delete_theme(self, name: str) -> None:
        if QMessageBox.question(self, 'Delete theme', f'Delete your theme "{name}"?') != QMessageBox.Yes:
            return
        presets.delete(name)
        self.themes.show_saved(presets.saved())

    def _master(self, value: int) -> None:
        self.state.master = value
        self.changed()

    def paint_keys(self, rgb) -> None:
        keys = self.board.picked_keys
        if not keys:
            self.keys_controls.pick_note.setProperty('role', 'error')
            self.keys_controls.pick_note.style().polish(self.keys_controls.pick_note)
            QTimer.singleShot(1200, self._calm_note)
            return
        perkey = list(self.state.perkey)
        for key in keys:
            perkey[key] = tuple(rgb)
        self.state.perkey = perkey
        self.changed()

    def _calm_note(self) -> None:
        note = self.keys_controls.pick_note
        note.setProperty('role', 'dim')
        note.style().polish(note)

    def _defaults(self) -> None:
        self.link.do('defaults')

    def keyPressEvent(self, event) -> None:
        if not self.board.press(event.nativeScanCode()):
            super().keyPressEvent(event)

    # --- flashing ---------------------------------------------------------------------------

    def _install(self) -> None:
        problem = flasher.ready()
        if problem:
            self._show_setup_problem(problem)
            return
        self.setup_problem.hide()
        steps = flasher.install_steps(take_backup=not flasher.backup().is_file())
        self._run_flash('Setting up your ALT', steps,
                        'Hold Fn and B for a second, until the keyboard goes dark.')

    def update_firmware(self) -> None:
        """Keyglow's newer firmware onto a keyboard running its older one: the keyboard restarts
        into its bootloader when asked, so no Fn and B."""
        problem = flasher.ready()
        controls = self.keyboard_controls
        if problem:
            controls.update_problem.setText(problem)
            controls.update_problem.show()
            return
        controls.update_problem.hide()
        self.link.do('bootloader')
        self._run_flash('Updating the firmware', flasher.install_steps(take_backup=False),
                        'Waiting for the keyboard to restart into its bootloader.')

    def _restore(self) -> None:
        problem = flasher.ready() if not flasher.backup().is_file() else ''
        if not flasher.backup().is_file():
            problem = 'No saved firmware was found on this PC.'
        if problem:
            QMessageBox.warning(self, 'Keyglow', problem)
            return
        answer = QMessageBox.question(
            self, 'Put back the original firmware',
            'The keyboard goes back to the firmware it had before Keyglow, and Keyglow can no longer '
            'change its lighting until it is set up again.')
        if answer != QMessageBox.Yes:
            return
        self.link.do('bootloader')
        self._run_flash('Putting back the original firmware', flasher.restore_steps(),
                        'Waiting for the keyboard to restart into its bootloader.')

    def _run_flash(self, title: str, steps: list, first_words: str) -> None:
        self.flash = flasher.Flash(steps, self)
        self.flash_title.setText(title)
        self.flash_step.setText(first_words)
        self.flash_cancel.setEnabled(True)
        self.pages.setCurrentIndex(3)
        self.where.setText('Writing firmware')
        self.flash.found.connect(lambda words: self.flash_step.setText(words + '...'))
        self.flash.done.connect(self._flash_done)
        # the bootloader request goes out first; then the keyboard is let go of
        QTimer.singleShot(400, lambda: (self.link.pause(True), self.flash and self.flash.start()))

    def _flash_done(self, worked: bool, words: str) -> None:
        flash, self.flash = self.flash, None
        log = flash.log if flash else ''
        self.link.pause(False)
        if worked:
            self.flash_title.setText('Done')
            self.flash_step.setText('The keyboard is restarting. It types again in a few seconds.')
            QTimer.singleShot(4000, lambda: self._status(self.status))
        else:
            self._status(self.status)
            if 'did not show up' in words or "didn't show up" in words:
                words += (' Unplug the keyboard and plug it back in, then try again, pressing the reset '
                          'button on its underside if Fn and B do nothing.')
            self._show_setup_problem(words)
            if log:
                try:
                    (flasher.data_folder() / 'last-flash.log').write_text(log, encoding='utf-8')
                except OSError:
                    pass

    def _show_setup_problem(self, words: str) -> None:
        self.setup_problem.setText(words)
        self.setup_problem.show()

    def _cancel_flash(self) -> None:
        if self.flash:
            self.flash.cancel()

    def closeEvent(self, event) -> None:
        if self.flash is not None:
            event.ignore()      # never leave a keyboard half-written
            return
        super().closeEvent(event)
