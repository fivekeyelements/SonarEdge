"""Read task XML as native Unicode, independent of the console code page."""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
from windows_shortcuts import GUID, invoke


class EmptyVariant(c.Structure):
    # VARIANT includes a two-pointer record union on x64; all zeros = VT_EMPTY.
    _fields_=[('header',w.WORD*4),('value',c.c_void_p*2)]


def check(result):
    if result < 0:
        raise OSError(f'Windows could not read the startup task (0x{result & 0xffffffff:08X}).')


def task_xml(name):
    ole=c.WinDLL('ole32')
    ole.CoInitializeEx.argtypes=[c.c_void_p,w.DWORD]
    ole.CoInitializeEx.restype=c.c_long
    ole.CoUninitialize.argtypes=[]
    ole.CoCreateInstance.argtypes=[c.POINTER(GUID),c.c_void_p,w.DWORD,c.POINTER(GUID),c.POINTER(c.c_void_p)]
    ole.CoCreateInstance.restype=c.c_long
    automation=c.WinDLL('oleaut32')
    automation.SysAllocString.argtypes=[w.LPCWSTR]
    automation.SysAllocString.restype=c.c_void_p
    automation.SysFreeString.argtypes=[c.c_void_p]
    automation.SysStringLen.argtypes=[c.c_void_p]
    automation.SysStringLen.restype=w.UINT
    @contextmanager
    def bstr(value):
        pointer=automation.SysAllocString(value)
        if not pointer:raise MemoryError('Could not allocate Windows task name')
        try:yield pointer
        finally:automation.SysFreeString(pointer)
    status=ole.CoInitializeEx(None,2)
    initialized=status>=0
    if not initialized and status & 0xffffffff!=0x80010106:check(status)
    service,folder,task,xml=c.c_void_p(),c.c_void_p(),c.c_void_p(),c.c_void_p()
    try:
        clsid=GUID.parse('0f87369f-a4e5-4cfc-bd3e-73e6154572dd')
        iid=GUID.parse('2faba4c7-4da9-4013-9697-20cc3fd40f85')
        check(ole.CoCreateInstance(c.byref(clsid),None,1,c.byref(iid),c.byref(service)))
        # ITaskService::Connect, using the current user's interactive credentials.
        check(invoke(service,10,[EmptyVariant]*4,*[EmptyVariant() for _ in range(4)]))
        with bstr('\\') as path:
            check(invoke(service,7,[c.c_void_p,c.POINTER(c.c_void_p)],path,c.byref(folder)))
        with bstr(name) as path:
            status=invoke(folder,13,[c.c_void_p,c.POINTER(c.c_void_p)],path,c.byref(task))
        if status & 0xffffffff in (0x80070002,0x80070003):return None
        check(status)
        # IRegisteredTask::get_Xml returns a BSTR, preserving Unicode paths.
        check(invoke(task,20,[c.POINTER(c.c_void_p)],c.byref(xml)))
        return c.wstring_at(xml,automation.SysStringLen(xml))
    finally:
        if xml:automation.SysFreeString(xml)
        for pointer in (task,folder,service):
            if pointer:invoke(pointer,2,[])
        if initialized:ole.CoUninitialize()
