"""The PC's lights: following the keyboard's themes or set on their own, what the motherboard's
Polychrome controller and Keyglow Lights are sent, the thread that keeps them in step, the PC tab,
and the service itself (built, run as the user with --console and its stand-in sticks).

Run: <KeyglowBuild venv>\\Scripts\\python.exe tests\\test_pc.py"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KEYGLOW_DATA'] = tempfile.mkdtemp(prefix='keyglow-pc-test-')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtCore import QCoreApplication, QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from keyglow import device, pc, pclink, polychrome as poly, presets, ram, state as st  # noqa: E402
from keyglow import link as linkmod  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def _wait_until(test, seconds: float = 3.0) -> bool:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        if test():
            return True
        time.sleep(0.01)
    return test()


def _theme(name: str) -> st.State:
    return next(t for t in presets.THEMES if t.name == name).apply(st.State())


class FollowTest(unittest.TestCase):
    """A keyboard theme, in the nearest effect each part has."""

    def test_solid_theme(self):
        state = _theme('Blossom')
        memory, board = pc.follow('ram', state), pc.follow('board', state)
        self.assertEqual((memory.effect, memory.a), (pc.RAM_SOLID, pc.PINK))
        self.assertEqual((board.effect, board.a), (pc.BOARD_SOLID, pc.PINK))

    def test_rainbow_and_cycle(self):
        self.assertEqual(pc.follow('ram', _theme('Rainbow')).effect, pc.RAM_RAINBOW_WAVE)
        self.assertEqual(pc.follow('board', _theme('Rainbow')).effect, pc.BOARD_RAINBOW)
        self.assertEqual(pc.follow('ram', _theme('Colour cycle')).effect, pc.RAM_CYCLE)
        self.assertEqual(pc.follow('board', _theme('Colour cycle')).effect, pc.BOARD_CYCLE)

    def test_gradient_runs_along_the_sticks(self):
        state = _theme('Ocean')
        memory = pc.follow('ram', state)
        self.assertEqual((memory.effect, memory.a, memory.b), (pc.RAM_GRADIENT, state.keys.a, state.keys.b))
        request = pc.ram_request(memory)
        self.assertEqual(request.mode, ram.STATIC)
        self.assertEqual((request.leds[0], request.leds[-1]), (state.keys.a, state.keys.b))

    def test_every_theme_maps(self):
        for theme in presets.THEMES:
            state = theme.apply(st.State())
            for part in ('ram', 'board'):
                lighting = pc.follow(part, state)
                self.assertIn(lighting.effect, pc.EFFECTS[part], (theme.name, part))
                pc.ram_request(lighting) if part == 'ram' else pc.board_effect(lighting)

    def test_dark_and_off(self):
        state = _theme('Blossom')
        state.dark = 1
        self.assertFalse(pc.follow('ram', state).on)
        state.dark, state.on = 0, 0
        self.assertFalse(pc.follow('board', state).on)
        self.assertEqual(pc.ram_request(pc.follow('ram', state)).leds, ((0, 0, 0),) * ram.LEDS)
        self.assertEqual(pc.board_effect(pc.follow('board', state))[0], poly.OFF)

    def test_base_light_while_keys_are_off(self):
        state = _theme('Ocean')
        state.on = st.ON_EDGE
        self.assertEqual(pc.follow('ram', state).effect, pc.RAM_VISOR)
        self.assertEqual(pc.follow('board', state).effect, pc.BOARD_SCAN)

    def test_per_key_takes_the_commonest_colour(self):
        state = st.State(keys=st.Zone(mode=st.KEY_CUSTOM))
        state.perkey = [(1, 2, 3)] * 60 + [(9, 9, 9)] * (st.KEYS - 60)
        self.assertEqual(pc.follow('ram', state).a, (1, 2, 3))

    def test_brightness_follows(self):
        state = _theme('Blossom')
        state.master = 128
        self.assertEqual(pc.follow('ram', state).bright, 128)
        self.assertEqual(pc.ram_request(pc.follow('ram', state)).brightness, 128)
        self.assertEqual(pc.board_effect(pc.follow('board', state))[1], tuple(c * 128 // 255 for c in pc.PINK))

    def test_own_lighting_wins_when_not_synced(self):
        own = pc.Part(sync=False, effect=pc.RAM_MARQUEE, a=(1, 2, 3))
        self.assertEqual(pc.resolved('ram', own, _theme('Rainbow')), own)
        self.assertEqual(pc.resolved('ram', pc.Part(sync=True), _theme('Rainbow')).effect, pc.RAM_RAINBOW_WAVE)

    def test_speeds(self):
        self.assertEqual([pc.ram_request(pc.Part(effect=pc.RAM_CYCLE, speed=s)).speed for s in (0, 100, 255)],
                         [0, 1, 2])
        self.assertEqual(pc.board_effect(pc.Part(effect=pc.BOARD_CYCLE, speed=0))[2], 255)      # slowest

    def test_kept(self):
        parts = {'ram': pc.Part(sync=False, effect=pc.RAM_RAIN, a=(1, 2, 3)), 'board': pc.Part()}
        pc.save(parts)
        self.assertEqual(pc.load(), parts)


class BoardTest(unittest.TestCase):
    """The Polychrome protocol, against a stand-in shaped like this PC's board."""

    def setUp(self):
        self.fake = poly.FakeBoard()
        self.board = poly.Board(self.fake)

    def test_zones(self):
        self.assertEqual([z.number for z in self.board.zones], [0, 2, 3, 6, 7])
        self.assertEqual(self.board.zones[1].leds, 80)

    def test_colours_go_in_each_zones_order(self):
        self.fake.swapped = 0x04          # only addressable header 1 takes red first
        board = poly.Board(self.fake)
        board.set(poly.STATIC, (10, 20, 30), 200)
        self.assertEqual(self.fake.live[2], (poly.STATIC, (10, 20, 30), 200))
        self.assertEqual(self.fake.live[0], (poly.STATIC, (20, 10, 30), 200))
        for zone in board.zones:
            self.assertEqual(board.read(zone), (poly.STATIC, (10, 20, 30), 200))

    def test_lost_write_is_sent_again(self):
        """On this PC's board a write right after opening was once lost: each zone is read back."""
        original, dropped = self.fake.transact, []

        def lossy(packet, about=None):
            if packet[0] == poly.SET_ZONE and not dropped:
                dropped.append(packet)
                return bytes(64)
            return original(packet, about)
        self.fake.transact = lossy
        self.board.set(poly.STATIC, (1, 2, 3), 9)
        self.assertTrue(dropped)
        self.assertTrue(all(self.board.read(z) == (poly.STATIC, (1, 2, 3), 9) for z in self.board.zones))

    def test_late_answer_passed_over(self):
        """A read's answer names its zone: one left over from before is not taken for it."""
        original, late = self.fake.transact, [bytes([0x13, 0, 0, 0x01]).ljust(64, b'\0')]

        class Link:
            def transact(self, packet, about=None):
                answer = late.pop() if late else original(packet, about)
                while about is not None and answer[3] != about:
                    answer = original(packet, about)
                return answer
        board = poly.Board(Link())
        self.assertEqual([z.number for z in board.zones], [0, 2, 3, 6, 7])

    def test_commit_keeps_it(self):
        self.board.set(poly.RAINBOW, (0, 0, 0), 100)
        self.assertEqual(self.fake.saved[0][0], poly.OFF)
        self.board.commit()
        self.assertEqual(self.fake.saved[0][0], poly.RAINBOW)


class PcLinkTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.fake = poly.FakeBoard()
        self.lights = ram.FakeLights()
        pclink.COMMIT_AFTER, self._commit = 0.1, pclink.COMMIT_AFTER
        self.link = pclink.PcLink(find_board=lambda: poly.Board(self.fake), lights=self.lights, icue=lambda: False)
        self.zones, self.answers = [], []
        self.link.board.connect(self.zones.append)
        self.link.memory.connect(self.answers.append)
        self.link.start()

    def tearDown(self):
        self.link.stop()
        pclink.COMMIT_AFTER = self._commit

    def test_found_and_set(self):
        self.assertTrue(_wait_until(lambda: self.zones and self.answers))
        self.assertEqual(len(self.zones[-1]), 5)
        self.assertEqual(self.answers[-1].status, ram.READY)
        self.link.want('board', pc.Part(effect=pc.BOARD_SOLID, a=(255, 0, 0)))
        self.link.want('ram', pc.Part(effect=pc.RAM_RAIN, a=(0, 255, 0), b=(0, 0, 255)))
        self.assertTrue(_wait_until(lambda: self.fake.commits and self.lights.asked))
        self.assertEqual(self.fake.saved[0], (poly.STATIC, (255, 0, 0), 255 - 96))       # this board: red first
        self.assertEqual(self.lights.asked[-1].mode, ram.RAIN)

    def test_same_wish_goes_once(self):
        self.assertTrue(_wait_until(lambda: self.answers))
        for _ in range(3):
            self.link.want('ram', pc.Part(effect=pc.RAM_SOLID))
            _wait_until(lambda: False, 0.3)
        self.assertEqual(len(self.lights.asked), 1)

    def test_memory_waits_for_its_service(self):
        """Wanted before Keyglow Lights is installed: set once it is."""
        self.lights.status = ram.NOT_INSTALLED
        self.link.want('ram', pc.Part(effect=pc.RAM_SOLID))
        _wait_until(lambda: False, 0.5)
        self.assertEqual(self.lights.asked, [])
        self.lights.status = ram.READY
        self.assertTrue(_wait_until(lambda: self.lights.asked, pclink.LOOK_EVERY + 2))


class PcTabTest(unittest.TestCase):
    """The device pages and RGB Sync, in the window, with stand-in devices."""

    def setUp(self):
        app = _app()
        from keyglow.ui import theme
        if not getattr(app, '_keyglow_themed', False):
            theme.install(app)
            app._keyglow_themed = True
        from keyglow.ui.window import Window
        pc._file().unlink(missing_ok=True)
        self.fake = device.FakeAlt(_theme('Blossom'))
        self.board = poly.FakeBoard()
        self.lights = ram.FakeLights()
        self.link = linkmod.Link(look=lambda: (device.READY, None),
                                 opener=lambda _: (k := device.Keyboard(self.fake)).hello() or k)
        self.pc_link = pclink.PcLink(find_board=lambda: poly.Board(self.board), lights=self.lights,
                                     icue=lambda: False)
        self.window = Window(self.link, self.pc_link)
        self.window.show()
        self.link.start()
        self.pc_link.start()
        self.assertTrue(_wait_until(lambda: self.window.status == device.READY and self.window._kb_loaded))
        self.assertTrue(_wait_until(lambda: self.lights.asked and self.board.live[0][0] != poly.OFF))

    def tearDown(self):
        self.link.stop(save=False)
        self.pc_link.stop()
        self.window.close()
        self.window.deleteLater()

    def _rainbow(self):
        return next(t for t in presets.THEMES if t.name == 'Rainbow')

    def _sync(self, *names):
        devices = self.window.devices
        for name in names:
            if name == 'keyboard':
                self.window.keyboard_switch.setChecked(True)
            else:
                (devices.memory if name == 'ram' else devices.board).sync.setChecked(True)

    def test_sync_page_only_with_two_synced(self):
        nav = self.window.nav
        self.assertEqual(nav.titles(), ['Keyboard', 'Memory', 'Motherboard'])
        self._sync('keyboard')
        self.assertEqual(nav.titles(), ['Keyboard', 'Memory', 'Motherboard'])
        self._sync('ram')
        self.assertEqual(nav.titles(), ['RGB Sync', 'Keyboard', 'Memory', 'Motherboard'])
        self.assertEqual(self.window.sync_page.members.text(), 'Drop ALT, Corsair Vengeance RGB DDR5 × 2')
        self.window.keyboard_switch.setChecked(False)
        self.assertEqual(nav.titles(), ['Keyboard', 'Memory', 'Motherboard'])

    def test_shared_lighting_reaches_the_synced(self):
        """Memory and motherboard synced, the keyboard not: a theme on the RGB Sync page reaches
        the two, and the keyboard keeps its own lighting."""
        self._sync('ram', 'board')
        self.window.use_sync_theme(self._rainbow())
        self.assertTrue(_wait_until(lambda: self.lights.asked[-1].mode == ram.RAINBOW_WAVE
                                    and self.board.live[0][0] == poly.RAINBOW))
        _wait_until(lambda: False, 0.3)
        self.assertEqual(self.fake.state.keys.mode, st.KEY_SOLID)
        self.assertFalse(self.window.devices.memory.own_frame.isVisibleTo(self.window.devices.memory))

    def test_sync_page_sets_the_lighting(self):
        self._sync('ram', 'board')
        editor = self.window.sync_page.editor
        editor.effect.setCurrentIndex(editor.effect.findData(pc.SYNC_BREATHING))
        self.assertTrue(_wait_until(lambda: self.lights.asked[-1].mode == ram.COLOR_PULSE
                                    and self.board.live[0][0] == poly.BREATHING))
        editor.effect.setCurrentIndex(editor.effect.findData(pc.SYNC_OFF))
        self.assertTrue(_wait_until(lambda: self.lights.asked[-1].brightness == 0
                                    and self.board.live[0][0] == poly.OFF))

    def test_keyboard_joins_and_leaves(self):
        """Synced, the keyboard shows the shared lighting and its lighting tabs make way; leaving,
        it gets its own back."""
        self._sync('keyboard', 'ram')
        self.window.use_sync_theme(self._rainbow())
        self.assertTrue(_wait_until(lambda: self.fake.state.keys.mode == st.KEY_RAINBOW))
        self.assertTrue(self.fake.state.extras & st.X_CAPS)                # its own settings kept
        self.window.keys_tab.setChecked(True)
        self.assertEqual(self.window.zone_pages.currentIndex(), self.window.SYNCED_NOTE)
        self.window.keyboard_tab.setChecked(True)
        self.assertEqual(self.window.zone_pages.currentIndex(), 3)          # its settings stay reachable
        self.window.keyboard_switch.setChecked(False)
        self.assertTrue(_wait_until(lambda: self.fake.state.keys.mode == st.KEY_SOLID))
        self.window.keys_tab.setChecked(True)
        self.assertEqual(self.window.zone_pages.currentIndex(), 1)

    def test_own_lighting(self):
        memory = self.window.devices.memory
        self.assertTrue(memory.own_frame.isVisibleTo(memory))
        memory.effect.setCurrentIndex(memory.effect.findData(pc.RAM_MARQUEE))
        self.assertTrue(_wait_until(lambda: self.lights.asked[-1].mode == ram.MARQUEE))
        memory.effect.setCurrentIndex(memory.effect.findData(0))           # Off
        self.assertTrue(_wait_until(lambda: self.lights.asked[-1].brightness == 0))
        self.window._save()
        self.assertEqual((pc.load()['ram'].on, pc.load()['ram'].effect), (False, pc.RAM_MARQUEE))

    def test_kept(self):
        self._sync('keyboard', 'board')
        self.window.use_sync_theme(self._rainbow())
        self.window._save()
        keyboard_sync, lighting, own = pc.load_sync()
        self.assertTrue(keyboard_sync)
        self.assertEqual(lighting.keys.mode, st.KEY_RAINBOW)
        self.assertEqual(own.keys.mode, st.KEY_SOLID)                       # Blossom, kept aside
        self.assertTrue(pc.load()['board'].sync)

    def test_found_shown(self):
        devices = self.window.devices
        self.assertTrue(_wait_until(lambda: 'Corsair Vengeance RGB DDR5 × 2' in devices.memory.where.text()))
        self.assertTrue(_wait_until(lambda: 'ARGB header 1' in devices.board.where.text()))
        devices.show_memory(ram.Answer(ram.NOT_INSTALLED))
        self.assertFalse(devices.install.isHidden())
        self.assertTrue(devices.memory.settings.isHidden())
        devices.show_board(None)
        self.assertTrue(devices.board.settings.isHidden())

    def test_icue_warned(self):
        devices = self.window.devices
        devices.show_memory(ram.Answer(ram.READY, sticks=self.lights.sticks))
        devices.show_icue(True)
        self.assertIn('iCUE', devices.memory.problem.text())
        self.assertFalse(devices.memory.problem.isHidden())

    def test_words(self):
        devices = self.window.devices
        self.assertEqual(devices.memory.sync.text(), 'RGB Sync')
        self.assertEqual(self.window.keyboard_switch.text(), 'RGB Sync')
        devices.show_memory(ram.Answer(ram.NOT_INSTALLED))
        self.assertEqual(devices.install.text(), 'Install service')

    def test_render(self):
        """Pictures of each page for a person to look at (not checked here)."""
        out = os.environ.get('KEYGLOW_RENDER')
        if not out:
            self.skipTest('KEYGLOW_RENDER not set')
        self.window.resize(1200, 820)
        self._sync('keyboard', 'ram')
        _wait_until(lambda: False, 0.5)
        for page, name in ((self.window.SYNC_PAGE, 'sync'), (self.window.KEYBOARD_PAGE, 'keyboard'),
                           (self.window.MEMORY_PAGE, 'memory'), (self.window.BOARD_PAGE, 'board')):
            self.window.show_device(page)
            _wait_until(lambda: False, 0.5)
            self.window.grab().save(str(Path(out) / f'keyglow-{name}.png'))


def _service_exe() -> Path | None:
    for folder in (ROOT / 'dist' / 'Keyglow' / 'lights', ROOT / '.dev' / 'out' / 'lights'):
        exe = folder / 'service' / 'KeyglowLights.exe'
        if exe.is_file():
            return exe
    return None


class ServiceTest(unittest.TestCase):
    """Keyglow Lights itself, run as the user with its stand-in sticks: no administrator, no SMBus."""

    def setUp(self):
        exe = _service_exe()
        if exe is None:
            self.skipTest('Keyglow Lights is not built (lights\\build.ps1)')
        self.name = f'kgtest{os.getpid()}'
        self.process = subprocess.Popen([str(exe), '--console', self.name, '--fake', '--idle', '3'],
                                        stdout=subprocess.PIPE, text=True)
        self.lights = ram.Lights(rf'Local\{self.name}', rf'Local\{self.name}Ask', rf'Local\{self.name}Wanted',
                                 service=None)
        end = time.monotonic() + 10
        while time.monotonic() < end and self.lights.answer().status == ram.STARTING:
            time.sleep(0.05)

    def tearDown(self):
        self.lights.close()
        self.process.kill()
        self.process.communicate(timeout=5)

    def _applied(self) -> list:
        self.lights.close()
        out, _ = self.process.communicate(timeout=15)
        return [line.split() for line in out.splitlines() if line.startswith('applied')]

    def test_finds_the_sticks(self):
        answer = self.lights.answer()
        self.assertEqual(answer.status, ram.READY)
        self.assertEqual([(s.address, s.pid, s.leds) for s in answer.sticks], [(0x58, 0x0700, 10), (0x5A, 0x0700, 10)])
        self.assertEqual(answer.sticks[0].name, 'Corsair Vengeance RGB DDR5')

    def test_effect_and_colours(self):
        answer = self.lights.ask(pc.ram_request(pc.Part(effect=pc.RAM_GRADIENT, a=(255, 0, 0), b=(0, 0, 255),
                                                        bright=255)))
        self.assertTrue(answer.took, answer)
        applied = self._applied()
        self.assertEqual([(a, b) for _, a, b, _ in applied], [('58', '1'), ('58', '2'), ('5A', '1'), ('5A', '2')])
        effect, colours = bytes.fromhex(applied[0][3]), bytes.fromhex(applied[1][3])
        self.assertEqual(effect[0], ram.STATIC)
        self.assertEqual(len(colours), 40)                      # 10 lights, RGB and 0xFF each
        self.assertEqual(colours[:4], bytes((255, 0, 0, 255)))
        self.assertGreater(colours[-2], 200)                    # blue at the far end

    def test_refuses_what_the_memory_hasnt(self):
        answer = self.lights.ask(ram.Request(0x42))
        self.assertFalse(answer.took)
        self.assertIn('not one the memory has', answer.message)
        answer = self.lights.ask(ram.Request(ram.RAINBOW, speed=7))
        self.assertFalse(answer.took)
        self.assertEqual([line for line in self._applied()], [])

    def test_stops_when_unasked(self):
        self.lights.close()
        self.assertEqual(self.process.wait(10), 0)


if __name__ == '__main__':
    unittest.main(verbosity=1)
