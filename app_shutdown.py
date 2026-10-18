"""Cooperative exit signal shared by the desktop, tray and installer."""
import ctypes
import threading

EVENT_NAME = 'Local\\SonarEdge.Exit.v1'


def listen(callback):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    event = kernel.CreateEventW(None, True, False, EVENT_NAME)
    if not event:
        return
    def watch():
        try:
            if kernel.WaitForSingleObject(event, 0xFFFFFFFF) == 0:
                callback()
        finally:
            kernel.CloseHandle(event)
    threading.Thread(target=watch, daemon=True, name='SonarEdge-InstallerExit').start()
