"""Native ShellLink shortcuts with an explicit executable and working directory."""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import secrets
import uuid


class GUID(c.Structure):
    _fields_ = [('data1',w.DWORD),('data2',w.WORD),('data3',w.WORD),('data4',w.BYTE*8)]

    @classmethod
    def parse(cls, text):
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


def check(result):
    if result < 0:
        raise OSError(f'Windows could not save the startup shortcut (0x{result & 0xffffffff:08X}).')


def invoke(pointer, index, arguments, *values):
    table = c.cast(pointer,c.POINTER(c.POINTER(c.c_void_p))).contents
    method = c.WINFUNCTYPE(c.c_long,c.c_void_p,*arguments)(table[index])
    return method(pointer,*values)


@contextmanager
def shell_link():
    ole = c.WinDLL('ole32')
    ole.CoInitializeEx.argtypes = [c.c_void_p,w.DWORD]
    ole.CoInitializeEx.restype = c.c_long
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID),c.c_void_p,w.DWORD,c.POINTER(GUID),c.POINTER(c.c_void_p)]
    ole.CoCreateInstance.restype = c.c_long
    result = ole.CoInitializeEx(None,2)
    initialized = result >= 0
    if not initialized and result & 0xffffffff != 0x80010106:  # Already initialized as MTA is also usable.
        check(result)
    link,persist = c.c_void_p(),c.c_void_p()
    try:
        clsid = GUID.parse('00021401-0000-0000-C000-000000000046')
        iid = GUID.parse('000214F9-0000-0000-C000-000000000046')
        check(ole.CoCreateInstance(c.byref(clsid),None,1,c.byref(iid),c.byref(link)))
        iid = GUID.parse('0000010B-0000-0000-C000-000000000046')
        check(invoke(link,0,[c.POINTER(GUID),c.POINTER(c.c_void_p)],c.byref(iid),c.byref(persist)))
        yield link,persist
    finally:
        if persist: invoke(persist,2,[])
        if link: invoke(link,2,[])
        if initialized: ole.CoUninitialize()


def write_shortcut(path, executable, arguments=''):
    path,executable = Path(path),Path(executable).resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(path.stem+'-'+secrets.token_hex(6)+'.lnk')
    try:
        with shell_link() as (link,persist):
            check(invoke(link,20,[w.LPCWSTR],str(executable)))
            check(invoke(link,9,[w.LPCWSTR],str(executable.parent)))
            check(invoke(link,11,[w.LPCWSTR],arguments))
            check(invoke(link,7,[w.LPCWSTR],'Sonar Edge Windows startup'))
            check(invoke(link,15,[c.c_int],1))
            check(invoke(link,17,[w.LPCWSTR,c.c_int],str(executable),0))
            check(invoke(persist,6,[w.LPCWSTR,w.BOOL],str(temporary),True))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_shortcut(path):
    with shell_link() as (link,persist):
        check(invoke(persist,5,[w.LPCWSTR,w.DWORD],str(Path(path)),0))
        target,arguments,directory = c.create_unicode_buffer(32768),c.create_unicode_buffer(2048),c.create_unicode_buffer(32768)
        check(invoke(link,3,[w.LPWSTR,c.c_int,c.c_void_p,w.DWORD],target,len(target),None,4))
        check(invoke(link,10,[w.LPWSTR,c.c_int],arguments,len(arguments)))
        check(invoke(link,8,[w.LPWSTR,c.c_int],directory,len(directory)))
        return {'target':target.value,'arguments':arguments.value,'directory':directory.value}


def startup_folder():
    shell = c.WinDLL('shell32')
    shell.SHGetFolderPathW.argtypes = [w.HWND,c.c_int,w.HANDLE,w.DWORD,w.LPWSTR]
    shell.SHGetFolderPathW.restype = c.c_long
    folder = c.create_unicode_buffer(32768)
    check(shell.SHGetFolderPathW(None,7,None,0,folder))  # CSIDL_STARTUP for this user.
    return Path(folder.value)
