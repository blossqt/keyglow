"""Keyglow's tests: the lighting state and protocol against the firmware's own definitions, the
link that keeps a keyboard in step, and the window, all with FakeAlt standing in for the ALT.

Run: <KeyglowBuild venv>\\Scripts\\python.exe tests\\test_keyglow.py"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KEYGLOW_DATA'] = tempfile.mkdtemp(prefix='keyglow-test-')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from keyglow import device, link as linkmod, state as st  # noqa: E402

FIRMWARE = ROOT / 'firmware' / 'keyglow'


def _app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _wait_until(test, seconds: float = 3.0) -> bool:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        if test():
            return True
        time.sleep(0.01)
    return test()


def _keyboard(fake: device.FakeAlt) -> device.Keyboard:
    keyboard = device.Keyboard(fake)
    keyboard.hello()
    return keyboard


class FirmwareMatchesTest(unittest.TestCase):
    """The app and the firmware agree on the state's layout and the effects' numbers."""

    def setUp(self):
        self.header = (FIRMWARE / 'keyglow.h').read_text(encoding='utf-8')

    def _define(self, name: str) -> int:
        return int(re.search(rf'#define {name}\s+(\d+)', self.header).group(1))

    def _enum(self, name: str) -> list:
        body = re.search(rf'enum {name} \{{(.*?)\}};', self.header, re.S).group(1)
        return re.findall(r'^\s*(KG_\w+)', body, re.M)

    def test_sizes(self):
        self.assertEqual(self._define('KG_STATE_SIZE'), st.STATE_SIZE)
        self.assertEqual(self._define('KG_STATE_VERSION'), st.STATE_VERSION)
        self.assertEqual(self._define('KG_KEYS'), st.KEYS)
        self.assertEqual(self._define('KG_EDGE'), st.EDGE)
        config = (FIRMWARE / 'config.h').read_text(encoding='utf-8')
        self.assertIn(f'EECONFIG_USER_DATA_SIZE {st.STATE_SIZE}', config)

    def test_effect_numbers(self):
        keys = self._enum('kg_key_mode')
        self.assertEqual(keys.index('KG_KEY_SOLID'), st.KEY_SOLID)
        self.assertEqual(keys.index('KG_KEY_CUSTOM'), st.KEY_CUSTOM)
        self.assertEqual(keys.index('KG_KEY_REACTIVE'), st.KEY_REACTIVE)
        self.assertEqual(keys.index('KG_KEY_MODES'), max(st.KEY_EFFECTS) + 1)
        edge = self._enum('kg_edge_mode')
        self.assertEqual(edge.index('KG_EDGE_RAINBOW'), st.EDGE_RAINBOW)
        self.assertEqual(edge.index('KG_EDGE_CHASE'), st.EDGE_CHASE)
        self.assertEqual(edge.index('KG_EDGE_MODES'), max(st.EDGE_EFFECTS) + 1)

    def test_led_points_match(self):
        source = (Path(os.environ.get('LOCALAPPDATA', '')) / 'KeyglowBuild' / 'qmk' / 'keyboards' / 'massdrop'
                  / 'alt' / 'config_led.c')
        if not source.is_file():
            self.skipTest('QMK is not set up here')
        text = source.read_text(encoding='utf-8')
        block = text.split('\n}, {')[1]          # the matrix, then the points, then the flags
        points = [(int(x), int(y)) for x, y in re.findall(r'\{\s*(\d+),\s*(\d+)\s*\}', block)]
        self.assertEqual(points, st.POINTS)

    def test_firmware_numbers(self):
        self.assertEqual(self._define('KG_FIRMWARE'), st.FIRMWARE)
        self.assertEqual(self._define('KG_STATE_SIZE_1'), st.OLD_SIZE)
        self.assertIn(f"out[9] = KG_FIRMWARE", (FIRMWARE / 'keymap.c').read_text(encoding='utf-8'))

    def test_fn_keys_match_the_keymap(self):
        """The picture's Fn layer lights the keys the firmware does: those not _______ on layer 1,
        and Fn (MO(1) on layer 0)."""
        keymap = (FIRMWARE / 'keymap.c').read_text(encoding='utf-8')
        layers = re.findall(r'\[(\d)\] = LAYOUT_65_ansi_blocker\((.*?)\n    \)', keymap, re.S)
        keys = {int(n): [k.strip() for k in body.replace('\n', ' ').split(',') if k.strip()] for n, body in layers}
        self.assertEqual(len(keys[0]), st.KEYS)
        self.assertEqual(len(keys[1]), st.KEYS)
        lit = {i for i, k in enumerate(keys[1]) if k not in ('_______', 'KC_TRNS', 'KC_NO', 'XXXXXXX')}
        lit |= {i for i, k in enumerate(keys[0]) if k == 'MO(1)'}
        self.assertEqual(lit, set(st.FN_KEYS))
        self.assertEqual(keys[0].index('KC_CAPS'), st.CAPS_KEY)
        self.assertEqual(st.CAPS_KEYS, tuple(keys[0].index(k) for k in ('KC_CAPS', 'KC_A', 'KC_LSFT')))

    def test_drops_caps_lock_flip_is_off(self):
        """Drop's indicator turned Caps Lock's colour inside out (red came out cyan) after Keyglow
        drew it: the keymap's indicator hook returns false, so it never runs."""
        keymap = (FIRMWARE / 'keymap.c').read_text(encoding='utf-8')
        hook = re.search(r'bool rgb_matrix_indicators_advanced_user\([^)]*\) \{(.*?)\n\}', keymap, re.S)
        self.assertIsNotNone(hook)
        self.assertEqual(hook.group(1).strip(), 'return false;')

    def test_hotkeys_page_matches_the_keymap(self):
        """Every Fn hotkey listed does something on layer 1, and every key that does is listed
        (F2-F12 by Fn+1's line)."""
        from keyglow.ui.hotkeys import KEYBOARD
        keymap = (FIRMWARE / 'keymap.c').read_text(encoding='utf-8')
        body = re.search(r'\[1\] = LAYOUT_65_ansi_blocker\((.*?)\n    \)', keymap, re.S).group(1)
        layer = [k.strip() for k in body.replace('\n', ' ').split(',') if k.strip()]
        labels = [k[3] for k in st.LAYOUT]
        listed = set()
        for _, rows in KEYBOARD:
            for keys, _what in rows:
                key = keys.split('+')[-1]
                index = labels.index(key)
                self.assertNotEqual(layer[index], '_______', keys)
                listed.add(index)
        listed |= set(range(2, 13))
        doing = {i for i, k in enumerate(layer) if k != '_______'}
        self.assertEqual(doing, listed)

    def test_old_state_reads(self):
        """Keyglow's first firmware keeps 222 bytes: its lighting reads, with the new settings'
        defaults."""
        state = st.State()
        state.keys.a = (1, 2, 3)
        old = state.pack()[:st.OLD_SIZE]
        again = st.State.unpack(old)
        self.assertEqual(again.keys.a, (1, 2, 3))
        self.assertEqual((again.extras, again.idle), (st.X_CAPS | st.X_FN, 10))

    def test_state_round_trip(self):
        state = st.State()
        state.perkey[5] = (1, 2, 3)
        state.edge.a = (9, 8, 7)
        again = st.State.unpack(state.pack())
        self.assertEqual(again.perkey[5], (1, 2, 3))
        self.assertEqual(again.edge.a, (9, 8, 7))
        self.assertEqual(len(state.pack()), st.STATE_SIZE)
        state.extras, state.caps, state.fn, state.idle, state.dark = st.X_FN, (1, 1, 1), (2, 2, 2), 30, 1
        again = st.State.unpack(state.pack())
        self.assertEqual((again.extras, again.caps, again.fn, again.idle, again.dark),
                         (st.X_FN, (1, 1, 1), (2, 2, 2), 30, 1))


class ProtocolTest(unittest.TestCase):
    def test_read_and_write(self):
        fake = device.FakeAlt()
        keyboard = _keyboard(fake)
        state = keyboard.read_state()
        self.assertEqual(state.keys.mode, st.KEY_RAINBOW)
        changed = state.copy()
        changed.perkey[66] = (10, 20, 30)
        sent = keyboard.write_changes(state.pack(), changed.pack())
        self.assertEqual(sent, 1)
        self.assertEqual(fake.state.perkey[66], (10, 20, 30))
        self.assertEqual(fake.saves, 0)
        keyboard.save()
        self.assertEqual(st.State.unpack(fake.saved).perkey[66], (10, 20, 30))

    def test_only_changes_go(self):
        fake = device.FakeAlt()
        keyboard = _keyboard(fake)
        before = keyboard.read_state()
        after = before.copy()
        after.keys.bright = 10
        after.perkey[0] = (0, 0, 0)
        after.perkey[60] = (0, 0, 0)
        packets = fake.packets
        keyboard.write_changes(before.pack(), after.pack())
        self.assertLessEqual(fake.packets - packets, 3)
        self.assertEqual(fake.live, bytearray(after.pack()))

    def test_whole_board_painted(self):
        fake = device.FakeAlt()
        keyboard = _keyboard(fake)
        before = keyboard.read_state()
        after = before.copy()
        after.perkey = [(1, 2, 3)] * st.KEYS
        keyboard.write_changes(before.pack(), after.pack())
        self.assertEqual(fake.live, bytearray(after.pack()))

    def test_not_keyglow(self):
        class Stranger:
            def transact(self, packet):
                return bytes([packet[0]]) + b'\0' * 31
        with self.assertRaises(device.DeviceError):
            device.Keyboard(Stranger()).hello()


class EffectsTest(unittest.TestCase):
    def test_parts_off_are_dark(self):
        state = st.State(on=0)
        self.assertTrue(all(c == (0, 0, 0) for c in st.colors(state, 1000)))

    def test_per_key_and_brightness(self):
        state = st.State()
        state.keys.mode = st.KEY_CUSTOM
        state.perkey[3] = (200, 100, 0)
        state.master = 255
        state.keys.bright = 255
        self.assertEqual(st.colors(state, 0)[3], (200, 100, 0))
        state.master = 0
        self.assertEqual(st.colors(state, 0)[3], (0, 0, 0))

    def test_reactive(self):
        state = st.State()
        state.keys.mode = st.KEY_REACTIVE
        state.keys.a, state.keys.b = (255, 0, 0), (0, 0, 0)
        lit = st.colors(state, 0, {7: 0})
        self.assertEqual(lit[7], (255, 0, 0))
        self.assertEqual(lit[8], (0, 0, 0))

    def test_caps_and_fn(self):
        state = st.State()
        state.keys.mode = st.KEY_SOLID
        state.keys.a = (10, 10, 10)
        state.caps, state.fn = (255, 0, 0), (0, 0, 255)
        lit = st.colors(state, 0, caps=True)
        self.assertEqual(lit[st.CAPS_KEY], (255, 0, 0))
        self.assertEqual(lit[31], (255, 0, 0))                 # A, right of it
        self.assertEqual(lit[44], (255, 0, 0))                 # Left Shift, below it
        self.assertEqual(lit[0], (10, 10, 10))
        self.assertEqual(lit[32], (10, 10, 10))                # S
        lit = st.colors(state, 0, fn=True)
        self.assertEqual(lit[63], (0, 0, 255))                 # Fn
        self.assertEqual(lit[16], (0, 0, 0))                   # Q does nothing with Fn
        state.extras = 0
        self.assertEqual(st.colors(state, 0, caps=True, fn=True)[st.CAPS_KEY], (10, 10, 10))

    def test_moving(self):
        state = st.State()
        state.keys.mode, state.edge.mode = st.KEY_SOLID, st.EDGE_SOLID
        self.assertFalse(st.moving(state))
        state.edge.mode = st.EDGE_CHASE
        self.assertTrue(st.moving(state))


class OldFirmwareTest(unittest.TestCase):
    def test_keyboard_on_first_firmware(self):
        fake = device.FakeAlt(old=True)
        keyboard = _keyboard(fake)
        self.assertTrue(keyboard.outdated)
        self.assertEqual(keyboard.size, st.OLD_SIZE)
        state = keyboard.read_state()
        changed = state.copy()
        changed.keys.a = (5, 6, 7)
        changed.idle = 30                       # not kept by that firmware: never sent
        keyboard.write_changes(state.pack(), changed.pack())
        self.assertEqual(len(fake.live), st.OLD_SIZE)
        self.assertEqual(fake.state.keys.a, (5, 6, 7))

    def test_answer_meant_for_another_is_passed_over(self):
        """Another program on the channel: its answers reach Keyglow too, ahead of Keyglow's own."""
        fake = device.FakeAlt()

        class Shared:
            def __init__(self):
                self.waiting = []

            def transact(self, packet):
                stray = fake.transact(bytes([device.READ, 0, 4]).ljust(device.PACKET, b'\0'))
                self.waiting.append(fake.transact(packet))
                return stray                # the other program's answer comes first

            def read_again(self):
                return self.waiting.pop(0) if self.waiting else b''

        keyboard = device.Keyboard(Shared())
        keyboard.hello()
        self.assertEqual(keyboard.read_state().pack(), fake.state.pack())

    def test_current_firmware(self):
        keyboard = _keyboard(device.FakeAlt())
        self.assertFalse(keyboard.outdated)
        self.assertEqual(keyboard.size, st.STATE_SIZE)

    def test_update_takes_no_backup(self):
        from keyglow import flasher
        steps = flasher.install_steps(take_backup=False)
        self.assertEqual(len(steps), 1)
        self.assertNotIn('--upload', steps[0][1])


class LinkTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.fake = device.FakeAlt()
        self.link = linkmod.Link(look=lambda: (device.READY, None), opener=lambda _: _keyboard(self.fake))
        self.loaded = []
        self.link.loaded.connect(self.loaded.append)

    def tearDown(self):
        self.link.stop(save=False)

    def test_finds_follows_and_saves(self):
        self.link.start()
        self.assertTrue(_wait_until(lambda: self.loaded))
        self.assertEqual(self.link.current, device.READY)
        state = self.loaded[0].copy()
        for value in range(0, 250, 5):          # a slider dragged: many changes, one save at the end
            state.keys.bright = value
            self.link.want(state.copy())
        self.assertTrue(_wait_until(lambda: self.fake.state.keys.bright == 245))
        self.assertTrue(_wait_until(lambda: self.fake.saves >= 1, 3), self.fake.saves)
        time.sleep(1.2)
        self.assertEqual(self.fake.saves, 1)

    def test_lost_keyboard(self):
        self.link.start()
        self.assertTrue(_wait_until(lambda: self.loaded))
        statuses = []
        self.link.status.connect(statuses.append)

        def gone(packet):
            raise OSError('unplugged')
        self.fake.transact = gone
        self.link._look = lambda: (device.ABSENT, None)
        state = self.loaded[0].copy()
        state.master = 3
        self.link.want(state)
        self.assertTrue(_wait_until(lambda: device.ABSENT in statuses))

    def test_stock(self):
        link = linkmod.Link(look=lambda: (device.STOCK, None))
        statuses = []
        link.status.connect(statuses.append)
        link.start()
        try:
            self.assertTrue(_wait_until(lambda: device.STOCK in statuses))
        finally:
            link.stop()

    def test_defaults_job(self):
        self.fake.live[3] = st.KEY_SOLID
        self.fake.saved = bytes(self.fake.live)
        self.link.start()
        self.assertTrue(_wait_until(lambda: self.loaded))
        self.link.do('defaults')
        self.assertTrue(_wait_until(lambda: len(self.loaded) == 2))
        self.assertEqual(self.loaded[1].keys.mode, st.KEY_RAINBOW)
        self.assertEqual(st.State.unpack(self.fake.saved).keys.mode, st.KEY_RAINBOW)


class WindowTest(unittest.TestCase):
    def setUp(self):
        app = _app()
        from keyglow.ui import theme
        if not getattr(app, '_keyglow_themed', False):
            theme.install(app)
            app._keyglow_themed = True
        from keyglow.ui.window import Window
        self.fake = device.FakeAlt()
        self.link = linkmod.Link(look=lambda: (device.READY, None), opener=lambda _: _keyboard(self.fake))
        self.window = Window(self.link)
        self.window.show()
        self.link.start()
        self.assertTrue(_wait_until(lambda: self.window.status == device.READY))

    def tearDown(self):
        self.link.stop(save=False)
        self.window.close()
        self.window.deleteLater()

    def test_effect_choice_reaches_keyboard(self):
        controls = self.window.edge_controls
        controls.effect.setCurrentIndex(controls.effect.findData(st.EDGE_CHASE))
        self.assertTrue(_wait_until(lambda: self.fake.state.edge.mode == st.EDGE_CHASE))
        self.assertTrue(controls.form.isRowVisible(controls.speed))
        controls.effect.setCurrentIndex(controls.effect.findData(st.EDGE_SOLID))
        self.assertFalse(controls.form.isRowVisible(controls.speed))
        self.assertFalse(controls.form.isRowVisible(controls.b))

    def test_switching_the_base_off(self):
        self.window.edge_controls.on.setChecked(False)
        self.assertTrue(_wait_until(lambda: not self.fake.state.on & st.ON_EDGE))
        self.assertTrue(self.fake.state.on & st.ON_KEYS)

    def test_painting_keys(self):
        self.window.keys_tab.setChecked(True)
        controls = self.window.keys_controls
        controls.effect.setCurrentIndex(controls.effect.findData(st.KEY_CUSTOM))
        self.assertTrue(self.window.board.picking)
        self.assertTrue(controls.per_key.isVisibleTo(self.window))
        self.window.board._pick({0, 1, 2})
        self.window.paint_keys((255, 0, 0))
        self.assertTrue(_wait_until(lambda: self.fake.state.perkey[2] == (255, 0, 0)))
        self.assertEqual(self.fake.state.perkey[3], (255, 255, 255))
        self.assertEqual(self.fake.state.keys.mode, st.KEY_CUSTOM)

    def test_click_picks_keys(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        controls = self.window.keys_controls
        controls.effect.setCurrentIndex(controls.effect.findData(st.KEY_CUSTOM))
        board = self.window.board
        QCoreApplication.processEvents()
        center = board.key_rect(16).center().toPoint()      # Q
        QTest.mouseClick(board, Qt.LeftButton, Qt.NoModifier, center)
        self.assertEqual(board.picked_keys, {16})
        QTest.mouseClick(board, Qt.LeftButton, Qt.ControlModifier, board.key_rect(17).center().toPoint())
        self.assertEqual(board.picked_keys, {16, 17})
        self.assertEqual(board.key_at(board.key_rect(61).center()), 61)     # the space bar

    def test_theme_reaches_keyboard(self):
        from keyglow import presets
        self.window.master.setValue(120)
        ocean = next(t for t in presets.THEMES if t.name == 'Ocean')
        tile = next(t for t in self.window.themes.tiles if t.choice is ocean)
        tile.click()
        self.assertTrue(_wait_until(lambda: self.fake.state.edge.mode == st.EDGE_CHASE))
        self.assertEqual(self.fake.state.keys.mode, st.KEY_GRADIENT)
        self.assertEqual(self.fake.state.master, 120)                 # brightness kept
        self.assertTrue(tile.current)
        self.assertEqual(self.window.keys_controls.effect.currentData(), st.KEY_GRADIENT)
        # changing anything after: no longer that theme
        self.window.edge_controls.effect.setCurrentIndex(
            self.window.edge_controls.effect.findData(st.EDGE_SOLID))
        self.assertFalse(tile.current)

    def test_per_key_theme_paints_keys(self):
        from keyglow import presets
        gaming = next(t for t in presets.THEMES if t.name == 'Gaming')
        self.window.use_theme(gaming)
        w = next(i for i, k in enumerate(st.LAYOUT) if k[3] == 'W')
        q = next(i for i, k in enumerate(st.LAYOUT) if k[3] == 'Q')
        self.assertTrue(_wait_until(lambda: self.fake.state.keys.mode == st.KEY_CUSTOM))
        self.assertNotEqual(self.fake.state.perkey[w], self.fake.state.perkey[q])

    def test_themes_all_fit_the_firmware(self):
        from keyglow import presets
        names = set()
        for choice in presets.THEMES:
            state = choice.apply(st.State())
            self.assertEqual(len(state.pack()), st.STATE_SIZE)
            self.assertIn(state.keys.mode, st.KEY_EFFECTS, choice.name)
            self.assertIn(state.edge.mode, st.EDGE_EFFECTS, choice.name)
            self.assertTrue(choice.shown_by(state), choice.name)
            names.add(choice.name)
        self.assertEqual(len(names), len(presets.THEMES))
        # every tile draws (the reactive one with its pretend typing too)
        for tile in self.window.themes.tiles:
            tile.grab()

    def test_tabs_change_with_one_click(self):
        """Back to a tab left a moment ago: once, it took a second click (no exclusive group)."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        tabs = [self.window.themes_tab, self.window.keys_tab, self.window.edge_tab, self.window.devices_tab,
                self.window.keyboard_tab, self.window.hotkeys_tab]
        for n in (1, 0, 1, 2, 0, 5, 3, 4, 4, 0):
            QTest.mouseClick(tabs[n], Qt.LeftButton)
            self.assertEqual(self.window.zone_pages.currentIndex(), n)
            self.assertEqual([t.isChecked() for t in tabs], [i == n for i in range(len(tabs))])

    def test_lights_off(self):
        """The switch puts every light out on the keyboard; a theme chosen brings them back."""
        from keyglow import presets
        controls = self.window.keyboard_controls
        self.assertTrue(controls.dark_frame.isEnabled())
        controls.dark_on.setChecked(True)
        self.assertTrue(_wait_until(lambda: self.fake.state.dark == 1))
        self.assertTrue(all(c == (0, 0, 0) for c in st.colors(self.window.state, 0, caps=True, fn=True)))
        self.window.use_theme(presets.THEMES[0])
        self.assertTrue(_wait_until(lambda: self.fake.state.dark == 0))
        self.assertFalse(controls.dark_on.isChecked())

    def test_changes_on_the_keyboard_show(self):
        """Fn+X (or Fn+W, S, Z) on the keyboard: the window follows within a look or two."""
        dark_at = st.OLD_SIZE + 8
        self.fake.live[dark_at] = 1
        self.fake.live[2] = 100                     # master, as Fn+S leaves it
        self.assertTrue(_wait_until(lambda: self.window.keyboard_controls.dark_on.isChecked(), 4))
        self.assertEqual(self.window.master.value(), 100)
        self.assertEqual(self.window.state.dark, 1)

    def test_keyboard_settings_reach_keyboard(self):
        controls = self.window.keyboard_controls
        self.assertTrue(controls.update_frame.isHidden())
        controls.caps_on.setChecked(False)
        controls.idle.setCurrentIndex(controls.idle.findData(30))
        self.assertTrue(_wait_until(lambda: self.fake.state.idle == 30))
        self.assertEqual(self.fake.state.extras, st.X_FN)
        controls.idle_on.setChecked(False)
        self.assertTrue(_wait_until(lambda: self.fake.state.idle == 0))
        controls._colour('fn', (0, 255, 0))
        self.assertTrue(_wait_until(lambda: self.fake.state.fn == (0, 255, 0)))

    def test_saved_themes(self):
        from keyglow import presets
        for t in presets.saved():
            presets.delete(t.name)
        self.window.use_theme(next(t for t in presets.THEMES if t.name == 'Ocean'))
        self.window.state.edge.a = (1, 2, 3)
        self.window.changed()
        self.window.save_theme('Mine')
        page = self.window.themes
        self.assertEqual([t.choice.name for t in page.own_tiles], ['Mine'])
        self.assertTrue(page.own_tiles[0].current)
        self.assertTrue(page.none_note.isHidden())
        self.window.use_theme(presets.THEMES[0])
        self.assertFalse(page.own_tiles[0].current)
        page.own_tiles[0].click()
        self.assertTrue(_wait_until(lambda: self.fake.state.edge.a == (1, 2, 3)))
        presets.rename('Mine', 'Ours')
        self.assertEqual([t.name for t in presets.saved()], ['Ours'])
        presets.delete('Ours')
        page.show_saved(presets.saved())
        self.assertEqual(page.own_tiles, [])
        self.assertFalse(page.none_note.isHidden())

    def test_loaded_lighting_shown(self):
        self.assertEqual(self.window.keys_controls.effect.currentData(), st.KEY_RAINBOW)
        self.assertEqual(self.window.master.value(), 255)

    def test_render(self):
        """A picture of the window for a person to look at (not checked here)."""
        out = os.environ.get('KEYGLOW_RENDER')
        if not out:
            self.skipTest('KEYGLOW_RENDER not set')
        self.window.resize(1040, 760)
        controls = self.window.keys_controls
        controls.effect.setCurrentIndex(controls.effect.findData(st.KEY_CUSTOM))
        self.window.board._pick({16, 17, 18, 19})
        self.window.paint_keys((255, 209, 220))
        _wait_until(lambda: False, 0.3)
        self.window.grab().save(str(Path(out) / 'keyglow-keys.png'))
        self.window.edge_tab.setChecked(True)
        _wait_until(lambda: False, 0.3)
        self.window.grab().save(str(Path(out) / 'keyglow-base.png'))


class OldFirmwareWindowTest(unittest.TestCase):
    """A keyboard on Keyglow's first firmware: the new settings wait for the update it offers."""

    def setUp(self):
        app = _app()
        from keyglow.ui import theme
        if not getattr(app, '_keyglow_themed', False):
            theme.install(app)
            app._keyglow_themed = True
        from keyglow.ui.window import Window
        self.fake = device.FakeAlt(old=True)
        self.link = linkmod.Link(look=lambda: (device.READY, None), opener=lambda _: _keyboard(self.fake))
        self.window = Window(self.link)
        self.window.show()
        self.link.start()
        self.assertTrue(_wait_until(lambda: self.window.status == device.READY))

    def tearDown(self):
        self.link.stop(save=False)
        self.window.close()
        self.window.deleteLater()

    def test_firmware_2_keeps_its_settings(self):
        """A keyboard on firmware 2 has the Keyboard tab's settings: the update is offered, and
        they stay usable."""
        from keyglow.ui.window import Window
        fake = device.FakeAlt()
        fake.firmware = 2
        link = linkmod.Link(look=lambda: (device.READY, None), opener=lambda _: _keyboard(fake))
        window = Window(link)
        link.start()
        try:
            self.assertTrue(_wait_until(lambda: window.status == device.READY))
            _wait_until(lambda: False, 0.2)
            controls = window.keyboard_controls
            self.assertFalse(controls.update_frame.isHidden())
            self.assertTrue(controls.caps_frame.isEnabled())
            self.assertIn('Caps Lock', controls.update_words.text())
        finally:
            link.stop(save=False)
            window.deleteLater()

    def test_update_offered(self):
        controls = self.window.keyboard_controls
        self.assertFalse(controls.update_frame.isHidden())
        self.assertFalse(controls.caps_frame.isEnabled())
        self.assertIn('new firmware', self.window.where.text())
        ran = []
        self.window._run_flash = lambda title, steps, words: ran.append(steps)
        os.environ['KEYGLOW_MDLOADER'] = sys.executable          # any file that is there
        try:
            self.window.update_firmware()
        finally:
            del os.environ['KEYGLOW_MDLOADER']
        self.assertTrue(_wait_until(lambda: self.fake.booted))   # asked for its bootloader: no Fn and B
        self.assertEqual(len(ran), 1)
        self.assertNotIn('--upload', ran[0][0][1])               # never Keyglow's firmware as the "original"


if __name__ == '__main__':
    unittest.main(verbosity=1)
