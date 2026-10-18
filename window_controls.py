"""Windows display controls, serialized onto the WinForms UI thread."""
import ctypes
import threading


class WindowControls:
    def __init__(self, window):
        self.window = window
        self._restore = None

    def _ui(self, operation):
        from System import Action
        form = self.window.native
        if form is None or form.IsDisposed:
            raise RuntimeError('The window is still starting')
        if not form.InvokeRequired:
            return operation(form)
        finished = threading.Event()
        result, errors = [], []
        def execute():
            try:
                result.append(operation(form))
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()
        # JS bridge calls run on worker threads. In particular, pywebview's
        # on_top setter does not marshal TopMost to the owning UI thread.
        form.BeginInvoke(Action(execute))
        if not finished.wait(6):
            raise RuntimeError('The window did not respond. Try again.')
        if errors:
            raise errors[0]
        return result[0]

    @staticmethod
    def _frame(form, fullscreen):
        # Windows 11 otherwise adds a one-pixel outline and rounded corners.
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        for attribute, value in ((33, 1 if fullscreen else 0), (34, 0xFFFFFFFE if fullscreen else 0xFFFFFFFF)):
            setting = ctypes.c_uint(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(form.Handle.ToInt64()), attribute,
                                      ctypes.byref(setting), ctypes.sizeof(setting))

    def _fullscreen(self, form, enabled, screen=None):
        from System.Windows.Forms import FormBorderStyle, FormWindowState, Screen
        if enabled:
            screen = screen or Screen.FromControl(form)
            if self._restore is None:
                self._restore = (form.Bounds, form.WindowState, form.FormBorderStyle)
            form.WindowState = FormWindowState.Normal
            form.FormBorderStyle = getattr(FormBorderStyle, 'None')
            # Use the physical bounds of this monitor. Maximizing a borderless
            # form can overscan or leave a border on a mixed-DPI desktop.
            form.Bounds = screen.Bounds
            form.is_fullscreen = True
            self.window.fullscreen = True
            self._frame(form, True)
        elif self._restore is not None:
            bounds, state, style = self._restore
            form.WindowState = FormWindowState.Normal
            form.FormBorderStyle = style
            form.Bounds = bounds
            form.WindowState = state
            form.is_fullscreen = False
            self.window.fullscreen = False
            self._restore = None
            self._frame(form, False)

    def perform(self, action, data=None):
        return self._ui(lambda form: self._perform(form, action, data or {}))

    def _perform(self, form, action, data):
        from System.Drawing import Rectangle
        from System.Windows.Forms import FormWindowState, Screen
        screens = list(Screen.AllScreens)
        if action == 'displays':
            return {'displays': [
                {'id': i, 'name': 'Xeneon Edge' if 3.2 < s.Bounds.Width / s.Bounds.Height < 3.9 else f'Display {i + 1}',
                 'width': s.Bounds.Width, 'height': s.Bounds.Height}
                for i, s in enumerate(screens)], 'onTop': bool(form.TopMost),
                'fullscreen': self._restore is not None}
        if action == 'fullscreen':
            self._fullscreen(form, self._restore is None)
        elif action == 'leave_fullscreen':
            self._fullscreen(form, False)
        elif action == 'move':
            index = int(data.get('display', -1))
            if not 0 <= index < len(screens):
                raise ValueError('That display is no longer connected')
            screen = screens[index]
            self._fullscreen(form, False)
            form.WindowState = FormWindowState.Normal
            area = screen.WorkingArea
            width, height = min(1600, area.Width - 40), min(520, area.Height - 40)
            form.Bounds = Rectangle(area.X + (area.Width - width) // 2,
                                    area.Y + (area.Height - height) // 2, width, height)
            if data.get('fullscreen', True):
                self._fullscreen(form, True, screen)
        elif action == 'on_top':
            self.window.on_top = bool(data.get('value'))
        elif action == 'minimize':
            form.WindowState = FormWindowState.Minimized
        else:
            raise ValueError('Unknown window action')
        return {'onTop': bool(form.TopMost), 'fullscreen': self._restore is not None}
