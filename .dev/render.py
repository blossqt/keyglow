"""Pictures of Keyglow's window with real fonts, never shown on screen (safe with a game in
front): python .dev\\render.py <folder>"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
os.environ['SUITE_PLACES'] = '0'
import tempfile  # noqa: E402
os.environ['KEYGLOW_DATA'] = tempfile.mkdtemp(prefix='keyglow-render-')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from keyglow import device, link as linkmod, state as st  # noqa: E402
from keyglow.ui import theme  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else '.')
app = QApplication(sys.argv)
theme.install(app)
from keyglow.ui.window import Window  # noqa: E402

fake = device.FakeAlt()


def opened(_):
    keyboard = device.Keyboard(fake)
    keyboard.hello()
    return keyboard


def settle(seconds=0.4):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


link = linkmod.Link(look=lambda: (device.READY, None), opener=opened)
window = Window(link)
window.resize(1040, 800)
link.start()
for _ in range(100):
    settle(0.05)
    if window.status == device.READY:
        break
settle()
window.grab().save(str(out / 'keyglow-themes.png'))
window.save_theme('Evening')
window.zone_pages.widget(0).verticalScrollBar().setValue(10000)
settle()
window.grab().save(str(out / 'keyglow-own-themes.png'))
window.keyboard_tab.setChecked(True)
window.board.show_light('fn')
settle()
window.grab().save(str(out / 'keyglow-keyboard.png'))
window.board.show_light('')

window.keys_tab.setChecked(True)
keys = window.keys_controls
keys.effect.setCurrentIndex(keys.effect.findData(st.KEY_CUSTOM))
window.board._pick(set(range(15, 30)))
window.paint_keys((255, 209, 220))
window.board._pick(set(range(30, 44)))
window.paint_keys((194, 37, 92))
window.board._pick({16, 31, 32, 33})
window.edge_controls.effect.setCurrentIndex(window.edge_controls.effect.findData(st.EDGE_GRADIENT))
settle()
window.grab().save(str(out / 'keyglow-perkey.png'))
window.edge_tab.setChecked(True)
settle()
window.grab().save(str(out / 'keyglow-base.png'))

old = device.FakeAlt(old=True)
link3 = linkmod.Link(look=lambda: (device.READY, None), opener=lambda _: (lambda k: (k.hello(), k)[1])(device.Keyboard(old)))
outdated = Window(link3)
outdated.resize(1040, 800)
link3.start()
settle(0.6)
outdated.keyboard_tab.setChecked(True)
settle()
outdated.grab().save(str(out / 'keyglow-outdated.png'))
link3.stop(save=False)

link2 = linkmod.Link(look=lambda: (device.STOCK, None))
setup = Window(link2)
setup.resize(1040, 800)
link2.start()
settle(0.6)
setup.grab().save(str(out / 'keyglow-setup.png'))
link.stop(save=False)
link2.stop()
print('rendered to', out)
theme.leave(0)
