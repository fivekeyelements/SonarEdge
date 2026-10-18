"""Desktop tray lifecycle. All callbacks run on the owning WinForms UI thread."""
import ctypes
from pathlib import Path


def hide_from_taskbar(form):
    # ShowInTaskbar's setter recreates the WinForms HWND, aborting WebView2's
    # initialization. Change just the existing window's shell styles instead.
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.GetWindowLongW.restype = ctypes.c_long
    user.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    user.SetWindowLongW.restype = ctypes.c_long
    handle = form.Handle.ToInt64()
    style = user.GetWindowLongW(handle, -20)
    hidden_style = (style & ~0x00040000) | 0x00000080  # APPWINDOW off, TOOLWINDOW on.
    if style != hidden_style:
        ctypes.set_last_error(0)
        if not user.SetWindowLongW(handle, -20, hidden_style) and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())


class DesktopTray:
    def __init__(self, window, icon_source, on_view=None, find_widget=None):
        self.window = window
        self.icon_source = Path(icon_source)
        self.icon = None
        self.tray = None
        self.menu = None
        self.restore_state = None
        self.on_view = on_view or (lambda mode: None)
        self.find_widget = find_widget
        self.exiting = False
        self.restoring = False

    def attach(self):
        # pywebview's before_show event runs synchronously on the UI thread.
        from System.Drawing import Icon
        from System.Windows.Forms import ContextMenuStrip, NotifyIcon, ToolStripMenuItem
        form = self.window.native
        self.restore_state = form.WindowState
        try:
            self.icon = (Icon(str(self.icon_source)) if self.icon_source.suffix.lower() == '.ico'
                         else Icon.ExtractAssociatedIcon(str(self.icon_source)))
            self.tray = NotifyIcon()
            self.tray.Icon = self.icon
            self.tray.Text = 'Sonar Edge'
            self.menu = ContextMenuStrip()
            open_item = ToolStripMenuItem('Open Sonar Edge')
            open_item.Click += self.restore
            self.menu.Items.Add(open_item)
            if self.find_widget is not None:
                widget_item = ToolStripMenuItem('Find iCUE widget')
                widget_item.Click += lambda *_: self.find_widget()
                self.menu.Items.Add(widget_item)
            exit_item = ToolStripMenuItem('Exit Sonar Edge')
            exit_item.Click += self.exit
            self.menu.Items.Add(exit_item)
            self.tray.ContextMenuStrip = self.menu
            self.tray.DoubleClick += self.restore
            self.tray.Visible = True
            # Reapply after fullscreen/style changes without replacing the HWND.
            form.StyleChanged += self.keep_off_taskbar
            form.HandleCreated += self.keep_off_taskbar
            self.keep_off_taskbar()
            # Install the hide handler only after a usable tray icon exists.
            form.Resize += self.on_resize
            form.FormClosed += self.dispose
            form.FormClosing += self.on_closing
        except Exception:
            self.dispose()
            raise

    def keep_off_taskbar(self, *_):
        form = self.window.native
        if self.tray is not None and self.tray.Visible and not form.IsDisposed and form.IsHandleCreated:
            hide_from_taskbar(form)

    def on_resize(self, *_):
        from System.Windows.Forms import FormWindowState
        if self.restoring:
            return
        form = self.window.native
        if form.WindowState == FormWindowState.Minimized:
            if self.tray is not None and self.tray.Visible:
                self.hide()
        else:
            self.restore_state = form.WindowState

    def restore(self, *_):
        from System.Windows.Forms import FormWindowState
        form = self.window.native
        if form.IsDisposed:
            return
        state = self.restore_state
        if state == FormWindowState.Minimized:
            state = FormWindowState.Normal
        # Showing a minimized form can synchronously raise Resize. Do not let
        # the minimize handler hide it again before WindowState is restored.
        self.restoring = True
        try:
            form.Show()
            form.WindowState = state
            form.BringToFront()
            form.Activate()
        finally:
            self.restoring = False
        self.restore_state = state
        self.on_view('desktop')

    def hide(self, *_):
        from System.Windows.Forms import FormWindowState
        form = self.window.native
        if form.WindowState != FormWindowState.Minimized:
            self.restore_state = form.WindowState
        form.Hide()  # Hidden windows also disappear from the taskbar.
        self.on_view('iframe')

    def on_closing(self, sender, event):
        from System.Windows.Forms import CloseReason
        if not self.exiting and event.CloseReason == CloseReason.UserClosing:
            event.Cancel = True
            self.hide()

    def exit(self, *_):
        self.exiting = True
        self.window.destroy()

    def dispose(self, *_):
        if self.tray is not None:
            self.tray.Visible = False
            self.tray.Dispose()
            self.tray = None
        if self.menu is not None:
            self.menu.Dispose()
            self.menu = None
        if self.icon is not None:
            self.icon.Dispose()
            self.icon = None
