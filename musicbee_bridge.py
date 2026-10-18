"""Bounded local IPC with our MusicBee plugin. No HTTP, subprocess or shell."""
import ctypes
from ctypes import wintypes as w
import json
import math
import time
from functools import lru_cache


@lru_cache(maxsize=1)
def pipe_name():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    token, size = w.HANDLE(), w.DWORD()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        string = w.LPWSTR()
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(string)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return r'\\.\pipe\SonarEdge.MusicBee.' + string.value
        finally:
            kernel.LocalFree(ctypes.cast(string, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def request(action='state', value=None):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Overlapped(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', w.DWORD), ('OffsetHigh', w.DWORD), ('hEvent', w.HANDLE)]
    kernel.WaitNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD]
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
    kernel.CreateEventW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.SetNamedPipeHandleState.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD), ctypes.c_void_p, ctypes.c_void_p]
    kernel.TransactNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(Overlapped)]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.GetOverlappedResult.argtypes = [w.HANDLE, ctypes.POINTER(Overlapped), ctypes.POINTER(w.DWORD), w.BOOL]
    kernel.CancelIoEx.argtypes = [w.HANDLE, ctypes.POINTER(Overlapped)]
    name = pipe_name()
    deadline = time.monotonic() + .25
    while True:
        if kernel.WaitNamedPipeW(name, 50):
            # Overlapped I/O; allow identification only, never server impersonation.
            flags = 0x40000000 | 0x00100000 | 0x00010000
            handle = kernel.CreateFileW(name, 0xC0000000, 0, None, 3, flags, None)
            if handle != ctypes.c_void_p(-1).value:
                break
        if time.monotonic() >= deadline:
            raise OSError('MusicBee helper is not running')
        time.sleep(.01)
    event = None
    try:
        mode = w.DWORD(2)
        if not kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        event = kernel.CreateEventW(None, True, False, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        overlap = Overlapped(hEvent=event)
        payload = json.dumps({'action': action, 'value': value}, allow_nan=False).encode('utf-8')
        reply, count = ctypes.create_string_buffer(16384), w.DWORD()
        ok = kernel.TransactNamedPipe(handle, payload, len(payload), reply, len(reply), ctypes.byref(count), ctypes.byref(overlap))
        if not ok:
            if ctypes.get_last_error() != 997:
                raise ctypes.WinError(ctypes.get_last_error())
            if kernel.WaitForSingleObject(event, 1200) != 0:
                kernel.CancelIoEx(handle, ctypes.byref(overlap))
                kernel.GetOverlappedResult(handle, ctypes.byref(overlap), ctypes.byref(count), True)
                raise TimeoutError('MusicBee helper took too long')
            if not kernel.GetOverlappedResult(handle, ctypes.byref(overlap), ctypes.byref(count), False):
                raise ctypes.WinError(ctypes.get_last_error())
        result = json.loads(reply.raw[:count.value].decode('utf-8'))
        if not isinstance(result, dict):
            raise ValueError('Invalid MusicBee response')
        if result.get('error'):
            raise ValueError(result['error'])
        return result
    finally:
        kernel.CloseHandle(handle)
        if event:
            kernel.CloseHandle(event)


def state():
    try:
        result = request()
        if not result.get('connected'):
            return None
        for name in ('position', 'duration', 'volume'):
            if type(result.get(name)) not in (float, int) or not math.isfinite(result[name]) or result[name] < 0:
                return None
        if result['volume'] > 1 or result['position'] > result['duration']:
            return None
        return result
    except (OSError, ValueError, TypeError):
        return None
