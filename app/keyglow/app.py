"""Starting Keyglow: one window, opened when asked for and gone when closed. It is used now and
then, to set the lighting up, so it keeps nothing running in the tray; the keyboard keeps the
lighting itself."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import __version__, device, flasher


def _self_test() -> int:
    """For the build: the window is made and drawn (never shown: a game may be in front), it finds
    a stand-in keyboard, and the firmware and Drop's loader are in place. The answer goes to the
    file given after --self-test, as a windowed exe has nowhere to print: the version (Hanami's
    installer and the release script read it first), or 'FAILED <why>'."""
    from .link import Link
    from .ui.window import Window
    from .ui import theme
    args = sys.argv[sys.argv.index('--self-test') + 1:]
    answer = args[0] if args else ''
    app = QApplication(sys.argv[:1])
    theme.install(app)
    fake = device.FakeAlt()
    link = Link(look=lambda: (device.READY, None), opener=lambda _: _opened(fake))
    pc_link = _fake_pc()
    window = Window(link, pc_link)
    link.start()
    pc_link.start()
    problems = []
    if not flasher.firmware().is_file():
        problems.append('firmware missing')
    if not flasher.mdloader().is_file():
        problems.append('mdloader missing')

    def check():
        if window.status != device.READY:
            problems.append('the stand-in keyboard was not found')
        if window.grab().isNull():
            problems.append('the window did not draw')
        if not pc_link.lights.asked:
            problems.append('the stand-in memory was not set')
        link.stop(save=False)
        pc_link.stop()
        said = __version__ if not problems else 'FAILED ' + ', '.join(problems)   # the version first
        if answer:
            Path(answer).write_text(said, encoding='utf-8')
        else:
            print('self-test:', said)
        app.exit(1 if problems else 0)
    QTimer.singleShot(2500, check)
    return theme.leave(app.exec())


def _fake_pc():
    """The PC's lights with a stand-in motherboard and memory."""
    from . import polychrome, ram
    from .pclink import PcLink
    return PcLink(find_board=lambda: polychrome.Board(polychrome.FakeBoard()), lights=ram.FakeLights(),
                  icue=lambda: False)


def _opened(fake):
    keyboard = device.Keyboard(fake)
    keyboard.hello()
    return keyboard


SERVER_NAME = os.environ.get('KEYGLOW_INSTANCE') or f'keyglow-{os.environ.get("USERNAME", "user")}'
_mutex = None


def _first_copy() -> bool:
    """Takes Keyglow's mutex for as long as this process lives; False if another copy has it."""
    global _mutex
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    _mutex = kernel32.CreateMutexW(None, False, 'Local\\' + SERVER_NAME) or 0
    return bool(_mutex) and ctypes.get_last_error() != 183      # ERROR_ALREADY_EXISTS


def _send(message: str) -> bool:
    """Hands a message to the copy of Keyglow already running."""
    from PySide6.QtNetwork import QLocalSocket
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(1500):
        return False
    socket.write(message.encode('utf-8'))
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


class _Hub(QObject):
    """What reaches Keyglow from outside: a second start of it (bring the window up), and its
    menu in Hanami's tray, which is there only while Keyglow is open."""

    asked = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        from PySide6.QtNetwork import QLocalServer
        from . import suitelink
        from .ui.icons import app_icon
        from .ui import theme  # noqa: F401
        self.window = window
        QLocalServer.removeServer(SERVER_NAME)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._connection)
        self.server.listen(SERVER_NAME)
        self.asked.connect(self._do)
        self.link = suitelink.SuiteLink('Keyglow', _png(app_icon()), on_click=self.asked.emit)
        self.link.set_menu([{'id': 'open', 'text': 'Open Keyglow', 'default': True},
                            {'separator': True},
                            {'id': 'quit', 'text': 'Quit Keyglow'}], tooltip='Keyglow')
        self.link.start()

    def _connection(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket) -> None:
        message = bytes(socket.readAll()).decode('utf-8', 'replace').strip()
        if message:
            self._do(message)

    def _do(self, message: str) -> None:
        if message in ('open', 'show'):
            window = self.window
            window.showNormal()
            window.raise_()
            window.activateWindow()
        elif message == 'quit':
            self.window.close()

    def stop(self) -> None:
        self.link.stop()
        self.server.close()


def _png(icon) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    icon.pixmap(32, 32).save(buffer, 'PNG')
    return bytes(buffer.data())


def main() -> int:
    if '--self-test' in sys.argv:
        return _self_test()
    from . import suitelog
    suitelog.start('Keyglow')
    QGuiApplication.setApplicationName('Keyglow')
    QGuiApplication.setOrganizationName('blossqt')
    QGuiApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    if not _first_copy():
        _send('show')           # one Keyglow at a time: the one running comes up instead
        return 0
    from .link import Link
    from .ui.window import Window
    from .ui import theme
    theme.install(app)
    if os.environ.get('KEYGLOW_FAKE'):
        fake = device.FakeAlt()
        link = Link(look=lambda: (device.READY, None), opener=lambda _: _opened(fake))
        pc_link = _fake_pc()
    else:
        from .pclink import PcLink
        link = Link()
        pc_link = PcLink()
    window = Window(link, pc_link)
    hub = _Hub(window)
    window.show()
    link.start()
    pc_link.start()
    app.setQuitOnLastWindowClosed(True)
    app.aboutToQuit.connect(link.stop)
    app.aboutToQuit.connect(pc_link.stop)
    app.aboutToQuit.connect(hub.stop)
    return theme.leave(app.exec())
