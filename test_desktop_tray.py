"""Tray lifecycle checks: restore state, exit cleanup, and safe setup failure."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from desktop_tray import DesktopTray


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler(None, None)


class TrayTests(unittest.TestCase):
    def setUp(self):
        self.form = NS(WindowState='normal', IsDisposed=False, ShowInTaskbar=True, Resize=Event(), FormClosed=Event(), FormClosing=Event(),
                       Hide=Mock(), Show=Mock(), BringToFront=Mock(), Activate=Mock())
        self.window = NS(native=self.form, destroy=Mock(side_effect=self.form.FormClosed.fire))
        self.icon = Mock()
        self.notify = NS(Visible=False, DoubleClick=Event(), Dispose=Mock())
        self.items = []
        self.menu = NS(Items=NS(Add=self.items.append), Dispose=Mock())
        modules = {'System.Drawing': NS(Icon=Mock(return_value=self.icon)),
                   'System.Windows.Forms': NS(NotifyIcon=Mock(return_value=self.notify),
                       ContextMenuStrip=Mock(return_value=self.menu),
                       ToolStripMenuItem=lambda text:NS(Text=text, Click=Event()),
                       FormWindowState=NS(Minimized='minimized',Normal='normal'),CloseReason=NS(UserClosing='user'))}
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tray = DesktopTray(self.window, Path('SonarEdge.ico'))

    def test_minimize_and_restore_preserve_normal_or_maximized_state(self):
        self.tray.attach()
        for state in ('normal', 'maximized'):
            self.form.WindowState = state
            self.form.Resize.fire()
            self.form.WindowState = 'minimized'
            self.form.Resize.fire()
            self.form.Hide.assert_called()
            self.assertTrue(self.notify.Visible)
            self.notify.DoubleClick.fire()
            self.assertEqual(self.form.WindowState, state)
            self.form.Show.assert_called()
            self.form.Activate.assert_called()
            self.assertFalse(self.form.ShowInTaskbar)

    def test_open_menu_restores_and_exit_disposes_the_tray(self):
        self.tray.attach()
        self.items[0].Click.fire()
        self.form.Show.assert_called_once()
        self.items[1].Click.fire()
        self.window.destroy.assert_called_once()
        self.assertFalse(self.notify.Visible)
        self.notify.Dispose.assert_called_once()
        self.menu.Dispose.assert_called_once()
        self.icon.Dispose.assert_called_once()

    def test_restore_does_not_rehide_a_minimized_window_during_show(self):
        self.form.WindowState = 'minimized'
        self.tray.attach()
        self.form.Show.side_effect = self.form.Resize.fire
        self.tray.restore()
        self.assertEqual(self.form.WindowState,'normal')
        self.form.Hide.assert_not_called()
        self.tray.dispose()  # Repeated cleanup is harmless.
        self.icon.Dispose.assert_called_once()

    def test_tray_setup_failure_never_installs_the_window_hide_handler(self):
        with patch.object(self.menu.Items, 'Add', side_effect=OSError('Tray unavailable')):
            with self.assertRaises(OSError):
                self.tray.attach()
        self.form.WindowState = 'minimized'
        self.form.Resize.fire()
        self.form.Hide.assert_not_called()
        self.assertFalse(self.notify.Visible)
        self.notify.Dispose.assert_called_once()
        self.assertTrue(self.form.ShowInTaskbar)

    def test_close_hides_the_window_but_explicit_exit_and_windows_shutdown_can_quit(self):
        self.tray.attach()
        event = NS(CloseReason='user', Cancel=False)
        self.tray.on_closing(None,event)
        self.assertTrue(event.Cancel)
        self.form.Hide.assert_called_once()
        self.assertTrue(self.notify.Visible)
        shutdown = NS(CloseReason='shutdown', Cancel=False)
        self.tray.on_closing(None,shutdown)
        self.assertFalse(shutdown.Cancel)
        self.tray.exiting = True
        explicit = NS(CloseReason='user', Cancel=False)
        self.tray.on_closing(None,explicit)
        self.assertFalse(explicit.Cancel)


if __name__ == '__main__':
    unittest.main()
