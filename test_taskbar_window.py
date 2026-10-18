"""Real WinForms handle regression: hiding the taskbar must keep child controls alive."""
import ctypes
import unittest
import clr

clr.AddReference('System.Windows.Forms')
from System.Windows.Forms import Control, Form, FormBorderStyle
from desktop_tray import hide_from_taskbar


class TaskbarWindowTests(unittest.TestCase):
    def test_taskbar_styles_keep_existing_window_and_child_handles_through_fullscreen(self):
        user = ctypes.WinDLL('user32')
        user.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user.GetWindowLongW.restype = ctypes.c_long
        form = Form()
        child = Control()
        try:
            form.Controls.Add(child)
            original = form.Handle.ToInt64()
            child_handle = child.Handle.ToInt64()
            hide_from_taskbar(form)
            self.assertEqual(form.Handle.ToInt64(), original)
            self.assertEqual(child.Handle.ToInt64(), child_handle)
            form.StyleChanged += lambda *_: hide_from_taskbar(form)
            for border in (getattr(FormBorderStyle, 'None'), FormBorderStyle.Sizable):
                form.FormBorderStyle = border
                style = user.GetWindowLongW(form.Handle.ToInt64(), -20)
                self.assertFalse(style & 0x00040000, 'APPWINDOW would force a taskbar entry')
                self.assertTrue(style & 0x00000080, 'TOOLWINDOW must suppress the taskbar entry')
            self.assertFalse(child.IsDisposed)
        finally:
            form.Dispose()


if __name__ == '__main__':
    unittest.main()
