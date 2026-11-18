"""LAMZU mice: the 64-byte protocol against a stand-in dongle that answers as the real one, the
thread that keeps the mouse in step, and the Mouse page.

Run: <KeyglowBuild venv>\\Scripts\\python.exe tests\\test_mouse.py"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KEYGLOW_DATA'] = tempfile.mkdtemp(prefix='keyglow-mouse-test-')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtCore import QCoreApplication, QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from keyglow import lamzu, mouselink  # noqa: E402


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


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.dongle = lamzu.FakeDongle()
        self.mouse = lamzu.fake_mouse(self.dongle)

    def test_reads_what_the_real_maya_x_held(self):
        # As read off the user's Maya X through its 8K dongle on 2026-11-18.
        settings = self.mouse.read()
        self.assertEqual(settings.profile, 2)
        self.assertEqual([s.dpi for s in settings.stages], [800, 1600])
        self.assertEqual(settings.stages[0].color, (208, 0, 103))
        self.assertEqual((settings.active, settings.polling, settings.lod, settings.sleep), (1, 1000, 2.0, 30))
        self.assertEqual(self.mouse.battery(), lamzu.Battery(22, False))

    def test_requests_are_framed_as_lamzus(self):
        self.mouse.read()
        frames = {bytes(r[2:7]) for r in self.dongle.requests}
        self.assertIn(bytes([2, 1, 0, 0x85, 0]), frames, 'the active profile, no profile named')
        self.assertIn(bytes([2, 10, 1, 0x81, 2]), frames, 'the DPI table of profile 2, size 10')
        self.assertIn(bytes([2, 2, 1, 0x80, 2]), frames, 'the polling rate')
        self.assertIn(bytes([2, 3, 0, 0x87, 2]), frames, 'the sleep time')

    def test_writes_only_what_changed_to_the_active_profile(self):
        before = self.mouse.read()
        self.dongle.requests.clear()
        after = before.with_(polling=4000, switches={**before.switches, 'motion_sync': True})
        self.mouse.apply(before, after)
        self.assertEqual([bytes(r[2:8]) for r in self.dongle.requests],
                         [bytes([2, 2, 1, 0x00, 2, 64]), bytes([2, 2, 1, 0x09, 2, 1])])
        self.assertEqual(self.mouse.read(), after)

    def test_stages_and_colours(self):
        before = self.mouse.read()
        stages = before.stages + (lamzu.Stage(3200, (255, 209, 220)),)
        after = before.with_(stages=stages, active=2, lod=0.7, sleep=60, debounce=4)
        self.mouse.apply(before, after)
        self.assertEqual(self.mouse.read(), after)
        self.assertEqual(self.dongle.dpis, [800, 1600, 3200])
        self.assertEqual(self.dongle.values[(1, 0x08)], 0x87, '0.7 mm as LAMZU writes it')

    def test_codes(self):
        self.assertEqual([lamzu.lod_code(mm) for mm in (0.7, 1.0, 1.3, 2.0)], [0x87, 1, 0x13, 2])
        for code in (0x87, 1, 0x13, 2):
            self.assertEqual(lamzu.lod_code(lamzu.lod_mm(code)), code)
        self.assertEqual(lamzu.lod_mm(3), 0.7)

    def test_out_of_range_is_refused_before_anything_is_sent(self):
        before = self.mouse.read()
        self.dongle.requests.clear()
        for bad in (before.with_(polling=125), before.with_(stages=()),
                    before.with_(stages=(lamzu.Stage(40000),)), before.with_(sleep=45)):
            with self.assertRaises(ValueError):
                self.mouse.apply(before, bad)
        self.assertEqual(self.dongle.requests, [])

    def test_an_older_answer_is_not_taken_for_a_new_one(self):
        self.mouse.read()
        self.dongle.asleep = True
        self.mouse.link.WAIT = 0.2
        self.mouse.link.RESEND_AT = ()
        with self.assertRaises(TimeoutError):
            self.mouse.profile()

    def test_a_refusal_says_so(self):
        with self.assertRaises(lamzu.MouseError):
            self.mouse.link.ask(1, 0x80, bytes([3]))          # a profile not active

    def test_answers_must_match(self):
        answer = bytes([0xA1, 0, 2, 2, 1, 0x80, 2, 1]).ljust(64, b'\0')
        self.assertEqual(lamzu.Link._answers(answer, 2, 1, 0x80, bytes([2])), bytes([2, 1]))
        self.assertIsNone(lamzu.Link._answers(answer, 2, 1, 0x80, bytes([1])), 'another profile')
        self.assertIsNone(lamzu.Link._answers(answer, 2, 1, 0x88, bytes([2])), 'another command')
        self.assertIsNone(lamzu.Link._answers(answer, 2, 0, 0x80, bytes([2])), 'another group')
        self.assertIsNone(lamzu.Link._answers(bytes([0xA1, 0, 2, 90, 1, 0x80]).ljust(64, b'\0'),
                                              2, 1, 0x80, bytes([2])), 'longer than the report')


class MouseLinkTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.dongle = lamzu.FakeDongle()
        self.views = []
        self.link = mouselink.MouseLink(opener=lambda: lamzu.fake_mouse(self.dongle))
        self.link.changed.connect(self.views.append)

    def tearDown(self):
        self.link.stop()

    def test_found_read_and_written(self):
        self.link.start()
        self.assertTrue(_wait_until(lambda: self.link.view.status == mouselink.READY))
        view = self.link.view
        self.assertEqual(view.name, 'LAMZU Maya X')
        self.assertEqual(view.battery, lamzu.Battery(22, False))
        self.link.want(view.settings.with_(polling=8000))
        self.assertTrue(_wait_until(lambda: self.dongle.values[(1, 0x00)] == 128))
        self.assertTrue(_wait_until(lambda: self.link.view.settings.polling == 8000))

    def test_absent_then_unplugged(self):
        present = []
        link = mouselink.MouseLink(opener=lambda: lamzu.fake_mouse(self.dongle) if present else None)
        link.start()
        try:
            self.assertTrue(_wait_until(lambda: link.view.status == mouselink.ABSENT))
            present.append(True)
            self.assertTrue(_wait_until(lambda: link.view.status == mouselink.READY, 5))
            self.dongle.closed = True
            link.want(link.view.settings.with_(polling=2000))
            self.assertTrue(_wait_until(lambda: link.view.status == mouselink.ABSENT))
        finally:
            link.stop()

    def test_asleep(self):
        self.dongle.asleep = True

        def sleepy():
            mouse = lamzu.fake_mouse(self.dongle)
            mouse.link.WAIT, mouse.link.RESEND_AT = 0.2, ()
            return mouse
        link = mouselink.MouseLink(opener=sleepy)
        link.start()
        try:
            self.assertTrue(_wait_until(lambda: link.view.status == mouselink.ASLEEP))
        finally:
            link.stop()


class MousePageTest(unittest.TestCase):
    def setUp(self):
        app = _app()
        from keyglow.ui import theme
        if not getattr(app, '_keyglow_themed', False):
            theme.install(app)
            app._keyglow_themed = True
        from keyglow.ui.mouse import MousePage
        self.page = MousePage()
        self.wanted = []
        self.page.changed.connect(self.wanted.append)
        mouse = lamzu.fake_mouse()
        self.model = mouse.model
        self.settings = mouse.read()
        self.page.show_view(mouselink.View(mouselink.READY, 'LAMZU Maya X', True, self.settings, self.model,
                                           lamzu.Battery(22, False)))

    def test_shows_the_mouse(self):
        page = self.page
        self.assertEqual(page.where.text(), 'LAMZU Maya X · Profile 2 · Battery 22%')
        self.assertEqual([row[1].value() for row in page.rows], [800, 1600])
        self.assertTrue(page.rows[1][0].isChecked())
        self.assertEqual(page.polling.currentText(), '1000 Hz')
        self.assertEqual([page.polling.itemText(i) for i in range(page.polling.count())],
                         ['1000 Hz', '2000 Hz', '4000 Hz', '8000 Hz'])
        self.assertEqual(page.lod.currentText(), '2 mm')
        self.assertEqual(page.sleep.currentText(), '30 s')
        self.assertEqual(self.wanted, [], 'showing is not changing')

    def test_changes_are_wanted(self):
        page = self.page
        page.polling.setCurrentIndex(page.polling.findData(4000))
        self.assertEqual(self.wanted[-1].polling, 4000)
        page.rows[0][1].setValue(400)
        page.rows[0][1].editingFinished.emit()
        self.assertEqual([s.dpi for s in self.wanted[-1].stages], [400, 1600])
        page.rows[0][0].click()
        self.assertEqual(self.wanted[-1].active, 0)
        page.switches['ripple'][1].setChecked(True)
        self.assertTrue(self.wanted[-1].switches['ripple'])

    def test_stages_added_and_removed(self):
        page = self.page
        page.add.click()
        self.assertEqual([s.dpi for s in self.wanted[-1].stages], [800, 1600, 3200])
        self.assertEqual(len(page.rows), 3)
        page.rows[0][3].click()
        self.assertEqual([s.dpi for s in self.wanted[-1].stages], [1600, 3200])
        self.assertEqual(self.wanted[-1].active, 0, 'the stage in use stays in use')

    def test_absent_and_asleep(self):
        page = self.page
        page.show_view(mouselink.View(mouselink.ABSENT))
        self.assertIn('No supported mouse detected', page.where.text())
        self.assertFalse(page.dpi_frame.isVisibleTo(page))
        page.show_view(mouselink.View(mouselink.ASLEEP, 'LAMZU Maya X', True, model=self.model))
        self.assertIn('not responding', page.where.text())
        self.assertFalse(page.sensor_frame.isVisibleTo(page))

    def test_words(self):
        # Professional wording: no contractions, no app narrating itself.
        from keyglow.ui import mouse
        words = ' '.join([mouse.SUPPORTED] + [about for _, _, about in mouse.SWITCHES])
        for bad in ("n't", "'s ", 'Keyglow '):
            self.assertNotIn(bad, words)

    def test_in_the_window(self):
        from keyglow import device, link as linkmod
        from keyglow.ui.window import Window
        fake = device.FakeAlt()
        link = linkmod.Link(look=lambda: (device.ABSENT, None), opener=lambda _: None)
        mouse_link = mouselink.MouseLink(opener=lamzu.fake_mouse)
        window = Window(link, None, mouse_link)
        try:
            self.assertIn(window.MOUSE_PAGE, window._nav_pages)
            self.assertEqual(window._nav_pages.index(window.MOUSE_PAGE), 1, 'after the keyboard')
            mouse_link.start()
            self.assertTrue(_wait_until(lambda: window.mouse.view.settings is not None))
            window.show_device(window.MOUSE_PAGE)
            self.assertFalse(window.grab().isNull())
        finally:
            mouse_link.stop()
            window.close()
            window.deleteLater()
        del fake


if __name__ == '__main__':
    unittest.main(verbosity=2)
