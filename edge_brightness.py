"""Hardware brightness for identified XENEON EDGE monitors through Windows DDC/CI."""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import hashlib
import threading


class MonitorInfo(c.Structure):
    _fields_ = [('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),
                ('flags',w.DWORD),('device',w.WCHAR*32)]


class DisplayDevice(c.Structure):
    _fields_ = [('size',w.DWORD),('name',w.WCHAR*32),('description',w.WCHAR*128),
                ('flags',w.DWORD),('identity',w.WCHAR*128),('key',w.WCHAR*128)]


class PhysicalMonitor(c.Structure):
    _fields_ = [('handle',w.HANDLE),('description',w.WCHAR*128)]


def is_edge(device):
    identity = device['identity'].upper().replace('\\', '#')
    return '#CRXED00#' in identity or 'XENEON EDGE' in device['description'].upper()


def device_id(device):
    return hashlib.sha256(device['identity'].encode('utf-8')).hexdigest()[:24]


class WindowsDDC:
    def __init__(self):
        self.user = c.WinDLL('user32',use_last_error=True)
        self.ddc = c.WinDLL('dxva2',use_last_error=True)
        self.callback_type = c.WINFUNCTYPE(w.BOOL,w.HMONITOR,w.HDC,c.POINTER(w.RECT),w.LPARAM)
        self.user.EnumDisplayMonitors.argtypes = [w.HDC,c.POINTER(w.RECT),self.callback_type,w.LPARAM]
        self.user.GetMonitorInfoW.argtypes = [w.HMONITOR,c.POINTER(MonitorInfo)]
        self.user.EnumDisplayDevicesW.argtypes = [w.LPCWSTR,w.DWORD,c.POINTER(DisplayDevice),w.DWORD]
        self.ddc.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [w.HMONITOR,c.POINTER(w.DWORD)]
        self.ddc.GetPhysicalMonitorsFromHMONITOR.argtypes = [w.HMONITOR,w.DWORD,c.POINTER(PhysicalMonitor)]
        self.ddc.DestroyPhysicalMonitors.argtypes = [w.DWORD,c.POINTER(PhysicalMonitor)]
        self.ddc.GetMonitorBrightness.argtypes = [w.HANDLE,c.POINTER(w.DWORD),c.POINTER(w.DWORD),c.POINTER(w.DWORD)]
        self.ddc.SetMonitorBrightness.argtypes = [w.HANDLE,w.DWORD]

    def devices(self):
        result = []
        def collect(handle, *_):
            info = MonitorInfo(); info.size = c.sizeof(info)
            device = DisplayDevice(); device.size = c.sizeof(device)
            if self.user.GetMonitorInfoW(handle,c.byref(info)) and self.user.EnumDisplayDevicesW(info.device,0,c.byref(device),1):
                result.append({'handle':handle,'identity':device.identity or info.device,'description':device.description})
            return True
        callback = self.callback_type(collect)
        if not self.user.EnumDisplayMonitors(None,None,callback,0):
            raise OSError('Windows could not read the connected displays. Try again.')
        return result

    @contextmanager
    def physical(self, device):
        count = w.DWORD()
        if not self.ddc.GetNumberOfPhysicalMonitorsFromHMONITOR(device['handle'],c.byref(count)) or not 0 < count.value <= 16:
            raise OSError('The EDGE display is not ready. Reconnect it and try again.')
        monitors = (PhysicalMonitor*count.value)()
        if not self.ddc.GetPhysicalMonitorsFromHMONITOR(device['handle'],count,monitors):
            raise OSError('The EDGE display is not ready. Reconnect it and try again.')
        try:
            if count.value != 1:
                raise OSError('Use the EDGE as an extended display to control its brightness.')
            yield monitors[0].handle
        finally:
            self.ddc.DestroyPhysicalMonitors(count,monitors)

    def read(self, handle):
        minimum,current,maximum = w.DWORD(),w.DWORD(),w.DWORD()
        if not self.ddc.GetMonitorBrightness(handle,c.byref(minimum),c.byref(current),c.byref(maximum)):
            raise OSError('Brightness control is unavailable. Check the EDGE connection and try again.')
        return minimum.value,current.value,maximum.value

    def write(self, handle, value):
        if not self.ddc.SetMonitorBrightness(handle,value):
            raise OSError('The EDGE did not accept the brightness change. Try again.')


class EdgeBrightness:
    def __init__(self, backend=None):
        self.backend = backend or WindowsDDC()
        self.lock = threading.Lock()

    @staticmethod
    def percent(values):
        minimum,current,maximum = values
        if not minimum <= current <= maximum or maximum <= minimum:
            raise OSError('The EDGE reported an invalid brightness range. Try again.')
        return round((current-minimum)*100/(maximum-minimum))

    def info(self):
        with self.lock:
            displays = []
            try:
                for device in self.backend.devices():
                    if not is_edge(device):
                        continue
                    item = {'id':device_id(device),'name':'XENEON EDGE','brightness':None}
                    try:
                        with self.backend.physical(device) as handle:
                            item['brightness'] = self.percent(self.backend.read(handle))
                    except OSError as error:
                        item['error'] = str(error)
                    displays.append(item)
            except OSError as error:
                return {'displays':[],'message':str(error)}
            return {'displays':displays,'message':None if displays else 'Connect a XENEON EDGE as an extended Windows display to adjust brightness.'}

    def command(self, data):
        value = data.get('value')
        if data.get('action') != 'brightness' or type(value) is not int or not 0 <= value <= 100:
            raise ValueError('Choose a brightness from 0 to 100%.')
        with self.lock:
            device = next((d for d in self.backend.devices() if is_edge(d) and device_id(d) == data.get('id')),None)
            if device is None:
                raise ValueError('That EDGE display is no longer connected. Reopen Display settings.')
            with self.backend.physical(device) as handle:
                values = self.backend.read(handle)
                self.percent(values)  # Validate the current hardware range before any write.
                minimum,_,maximum = values
                self.backend.write(handle,round(minimum+(maximum-minimum)*value/100))
                return {'id':device_id(device),'brightness':self.percent(self.backend.read(handle))}
