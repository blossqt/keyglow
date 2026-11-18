"""Draws Keyglow's window on the Mouse page with a stand-in Maya X, never shown, to .dev/mouse_page.png."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
os.environ['KEYGLOW_DATA'] = str(Path(os.environ['TEMP']) / 'keyglow-render')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from keyglow import device, lamzu, link as linkmod, mouselink  # noqa: E402
from keyglow.ui import theme  # noqa: E402
from keyglow.ui.window import Window  # noqa: E402

theme.install(app)
link = linkmod.Link(look=lambda: (device.ABSENT, None), opener=lambda _: None)
mouse_link = mouselink.MouseLink(opener=lamzu.fake_mouse)
window = Window(link, None, mouse_link)
window.resize(1200, 820)
mouse_link.start()
end = time.perf_counter() + 3
while window.mouse.view.settings is None and time.perf_counter() < end:
    QCoreApplication.processEvents()
    time.sleep(0.01)
window.show_device(window.MOUSE_PAGE)
for _ in range(60):
    QCoreApplication.processEvents()
    time.sleep(0.01)
window.grab().save(str(Path(__file__).with_name('mouse_page.png')))
mouse_link.stop()
print('saved')
