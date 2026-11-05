"""The hotkeys: the ALT's own, which Keyglow's firmware gives it (layer 1 of firmware/keyglow/keymap.c),
and Keyglow's window's. Shown on a page of the window, and with Ctrl+/ or F1 as the suite's apps
show theirs."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from . import suitesettings as ss

# (group, [(keys, what they do), ...]). The keyboard's must match its keymap: the tests check.
KEYBOARD = [
    ('Lighting', [
        ('Fn+W', 'Brighter'),
        ('Fn+S', 'Dimmer'),
        ('Fn+Z', 'Light everything, only the keys, only the base, or nothing'),
        ('Fn+X', 'Turn every light off, or back on'),
    ]),
    ('Function and media keys', [
        ('Fn+1', 'F1, with Fn+2 to Fn+= for F2 to F12'),
        ('Fn+Esc', '` (backtick)'),
        ('Fn+Del', 'Mute'),
        ('Fn+PgUp', 'Volume up'),
        ('Fn+PgDn', 'Volume down'),
        ('Fn+P', 'Print Screen'),
        ('Fn+[', 'Scroll Lock'),
        ('Fn+]', 'Pause'),
    ]),
    ('Moving around', [
        ('Fn+←', 'Home'),
        ('Fn+→', 'End'),
        ('Fn+↑', 'Page Up'),
        ('Fn+↓', 'Page Down'),
        ('Fn+Home', 'End'),
    ]),
    ('The keyboard', [
        ('Fn+N', 'Switch n-key rollover on or off'),
        ('Fn+Ctrl+Shift+U', 'Second USB-C port: always on, or only when a device is plugged in'),
        ('Fn+Ctrl+Shift+I', 'Second USB-C port: power limited automatically, or not'),
        ('Fn+M', 'Debug messages on or off'),
        ('Fn+B', 'Held half a second: restart into update mode, for new firmware'),
    ]),
]
WINDOW = [
    ('In Keyglow', [
        ('Ctrl+A', 'Pick every key, for per-key colours'),
        ('Ctrl+/', 'Show the hotkeys'),
    ]),
]
GROUPS = KEYBOARD + WINDOW


class HotkeysPage(QWidget):
    """Every group in a section of its own: what a hotkey does on the left, its keys on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ss.ITEMS)
        for name, rows in GROUPS:
            frame, items = ss.section(name)
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(8)
            for n, (keys, what) in enumerate(rows):
                grid.addWidget(ss.label(what, wrap=True), n, 0)
                grid.addWidget(ss.keycaps(keys), n, 1)
            grid.setColumnStretch(0, 1)
            items.addLayout(grid)
            column.addWidget(frame)
        column.addStretch(1)
