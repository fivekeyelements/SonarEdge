"""Regression checks for UI-thread ownership and mixed-DPI fullscreen bounds."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
import sys
import threading
import unittest
from unittest.mock import patch
from window_controls import WindowControls


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.owner = self.worker.submit(threading.get_ident).result()
        self.top = False
        test = self
        class Form:
            IsDisposed = False
            Bounds = (100, 100, 1600, 510)
            WindowState = 'normal'
            FormBorderStyle = 'sizable'
            is_fullscreen = False
            Handle = NS(ToInt64=lambda: 123)
            @property
            def InvokeRequired(self):
                return threading.get_ident() != test.owner
            def BeginInvoke(self, callback):
                test.worker.submit(callback)
            @property
            def TopMost(self):
                return test.top
            @TopMost.setter
            def TopMost(self, value):
                test.assertEqual(threading.get_ident(), test.owner, 'TopMost must run on its UI thread')
                test.top = value
        self.form = Form()
        class Window:
            native = test.form
            fullscreen = False
            @property
            def on_top(self):
                return test.form.TopMost
            @on_top.setter
            def on_top(self, value):
                test.form.TopMost = value
        self.window = Window()
        self.controls = WindowControls(self.window)
        # Distinct physical origins deliberately differ from logical/DPI-scaled coordinates.
        self.screens = [NS(Bounds=NS(Width=3840, Height=2160), WorkingArea=NS(X=0,Y=0,Width=3840,Height=2100)),
                        NS(Bounds=NS(X=640,Y=2160,Width=2560,Height=720), WorkingArea=NS(X=640,Y=2160,Width=2560,Height=720))]
        modules = {'System': NS(Action=lambda callback: callback),
                   'System.Drawing': NS(Rectangle=lambda *coords: coords),
                   'System.Windows.Forms': NS(Screen=NS(AllScreens=self.screens, FromControl=lambda form:self.screens[1]),
                                              FormBorderStyle=NS(**{'None':'none'}), FormWindowState=NS(Normal='normal',Minimized='minimized'))}
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.frame_patch = patch.object(self.controls, '_frame')
        self.frame_patch.start()

    def tearDown(self):
        self.worker.shutdown()
        self.module_patch.stop()
        self.frame_patch.stop()

    def test_topmost_marshals_to_the_ui_thread_and_remains_responsive(self):
        for value in (True, False, True, False):
            result = self.controls.perform('on_top', {'value':value})
            self.assertEqual(result['onTop'], value)
            self.assertEqual(self.controls.perform('displays')['onTop'], value)

    def test_fullscreen_uses_physical_monitor_bounds_without_maximizing(self):
        original = self.form.Bounds
        self.controls.perform('fullscreen')
        self.assertIs(self.form.Bounds, self.screens[1].Bounds)
        self.assertEqual(self.form.WindowState, 'normal')
        self.assertEqual(self.form.FormBorderStyle, 'none')
        self.assertTrue(self.window.fullscreen)
        self.controls.perform('leave_fullscreen')
        self.controls.perform('leave_fullscreen')
        self.assertEqual(self.form.Bounds, original)
        self.assertEqual(self.form.FormBorderStyle, 'sizable')
        self.assertFalse(self.window.fullscreen)

    def test_move_keeps_topmost_and_fullscreen_can_restore_on_target_display(self):
        self.controls.perform('on_top', {'value':True})
        result = self.controls.perform('move', {'display':1, 'fullscreen':True})
        self.assertEqual(result, {'onTop':True, 'fullscreen':True})
        self.assertIs(self.form.Bounds, self.screens[1].Bounds)
        self.controls.perform('leave_fullscreen')
        self.assertEqual(self.form.Bounds, (1120,2260,1600,520))
        self.assertTrue(self.form.TopMost)

    def test_invalid_display_preserves_current_window(self):
        original = self.form.Bounds
        with self.assertRaises(ValueError):
            self.controls.perform('move', {'display':99})
        self.assertEqual(self.form.Bounds, original)

    def test_minimize_preserves_fullscreen_bounds_for_tray_restore(self):
        self.controls.perform('fullscreen')
        bounds = self.form.Bounds
        self.controls.perform('minimize')
        self.assertEqual(self.form.WindowState, 'minimized')
        self.assertIs(self.form.Bounds, bounds)
        self.assertTrue(self.window.fullscreen)


if __name__ == '__main__':
    unittest.main()
