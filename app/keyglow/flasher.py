"""Putting firmware on the ALT with Drop's own loader, mdloader (tools\\mdloader.exe, built from
github.com/Massdrop/mdloader by build/bootstrap.ps1).

The ALT takes new firmware only from its bootloader, which the firmware never overwrites, so a
flash that goes wrong is put right by flashing again. In its bootloader the keyboard shows up as a
serial port; mdloader --first waits up to a minute for one. Each run of mdloader leaves the
keyboard in its bootloader, except one asked to --restart it.

mdloader also turns on the chip's SmartEEPROM the first time (the place Keyglow's firmware keeps
the lighting through a power cut), and always exits 0: success is "Complete!" with no "Error:".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

# The firmware after the 16 KB bootloader. 192 KB holds any ALT firmware (Drop's is under 90 KB)
# and stays clear of the SmartEEPROM at the top of the 256 KB flash.
BACKUP_ADDR = 0x4000
BACKUP_SIZE = 0x30000


def _base() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]      # the project folder


def mdloader() -> Path:
    found = os.environ.get('KEYGLOW_MDLOADER')
    if found:
        return Path(found)
    return _base() / 'tools' / 'mdloader.exe'


def firmware() -> Path:
    found = os.environ.get('KEYGLOW_FIRMWARE')
    if found:
        return Path(found)
    return Path(__file__).resolve().parent / 'firmware' / 'keyglow_alt.bin'


def data_folder() -> Path:
    found = os.environ.get('KEYGLOW_DATA')
    folder = Path(found) if found else Path(os.environ.get('APPDATA', Path.home())) / 'Keyglow'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def backup() -> Path:
    """The firmware the keyboard had before Keyglow's, as read off it before the first flash."""
    return data_folder() / 'original-firmware.bin'


def ready() -> str:
    """Why flashing can't happen now, in words, or '' if it can."""
    if not mdloader().is_file():
        return "Keyglow's copy of Drop's loader is missing. Reinstall Keyglow."
    if not firmware().is_file():
        return "Keyglow's firmware is missing. Reinstall Keyglow."
    return ''


class Flash(QObject):
    """Runs mdloader once or a few times in a row: steps of (what it says, arguments)."""

    said = Signal(str)          # a step under way, in words (mdloader may still be waiting for the keyboard)
    found = Signal(str)         # mdloader found the keyboard in its bootloader: the step's words again
    done = Signal(bool, str)    # worked, and what to tell the user

    def __init__(self, steps: list[tuple[str, list[str]]], parent=None):
        super().__init__(parent)
        self._steps = list(steps)
        self._process: QProcess | None = None
        self._output = ''
        self._words = ''
        self._found = False
        self.log = ''

    def start(self) -> None:
        self._next()

    def cancel(self) -> None:
        self._steps = []
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()

    def _next(self) -> None:
        if not self._steps:
            self.done.emit(True, '')
            return
        words, args = self._steps.pop(0)
        self._words = words
        self._found = False
        self.said.emit(words)
        self._output = ''
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.finished.connect(lambda code, status: self._finished(process, code, status))
        process.errorOccurred.connect(lambda error: self._failed_to_start(process, error))
        self._process = process
        process.start(str(mdloader()), args)

    def _read(self, process: QProcess) -> None:
        text = bytes(process.readAllStandardOutput()).decode('utf-8', 'replace')
        self._output += text
        self.log += text
        if not self._found and 'Found MCU' in self._output:
            self._found = True
            self.found.emit(self._words)

    def _failed_to_start(self, process: QProcess, error) -> None:
        if error == QProcess.FailedToStart:
            self.done.emit(False, "Drop's loader didn't start.")

    def _finished(self, process: QProcess, code: int, status) -> None:
        self._read(process)
        process.deleteLater()
        out = self._output
        if status != QProcess.NormalExit:
            self.done.emit(False, 'The flash was stopped.')
            return
        if 'Error:' in out or 'Complete!' not in out:
            self.done.emit(False, _problem(out))
            return
        self._next()


def _problem(out: str) -> str:
    if 'Could not find a valid device port' in out:
        return "The keyboard didn't show up in its bootloader within a minute."
    for line in out.splitlines():
        if line.strip().startswith('Error:'):
            return line.strip()[len('Error:'):].strip().rstrip('!') + '.'
    return "Drop's loader stopped without finishing."


def install_steps(take_backup: bool) -> list:
    """Keyglow's firmware onto a keyboard already in its bootloader, its own firmware read off
    first (only the first time: a later install would read Keyglow's)."""
    steps = []
    if take_backup:
        steps.append(('Saving the firmware it has now', [
            '--first', '--upload', str(backup()), '--addr', hex(BACKUP_ADDR), '--size', hex(BACKUP_SIZE)]))
    steps.append(('Writing Keyglow firmware', ['--first', '--download', str(firmware()), '--restart']))
    return steps


def restore_steps() -> list:
    return [('Writing the original firmware', ['--first', '--download', str(backup()), '--restart'])]
