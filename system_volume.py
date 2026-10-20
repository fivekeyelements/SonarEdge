"""Windows default playback endpoint volume; no keyboard hooks or Sonar writes."""
import ctypes as c
import math
import time
from audio_meters import GUID, CoreAudio


def check(result):
    if result < 0:
        raise OSError(f'Windows audio is unavailable (0x{result & 0xffffffff:08X})')


class Endpoint:
    """Keep each COM lifetime on its calling thread, including after output changes."""
    call = staticmethod(CoreAudio.call)
    release = staticmethod(CoreAudio.release)

    def __init__(self):
        self.enumerator,self.device,self.volume = c.c_void_p(),c.c_void_p(),c.c_void_p()
        self.initialized = False
        self.ole = c.WinDLL('ole32')
        self.ole.CoInitializeEx.argtypes = [c.c_void_p,c.c_uint32]
        self.ole.CoInitializeEx.restype = c.c_long
        self.ole.CoTaskMemFree.argtypes = [c.c_void_p]
        self.ole.PropVariantClear.argtypes = [c.c_void_p]
        self.ole.CoCreateInstance.argtypes = [c.POINTER(GUID),c.c_void_p,c.c_uint32,c.POINTER(GUID),c.POINTER(c.c_void_p)]
        self.ole.CoCreateInstance.restype = c.c_long
        result = self.ole.CoInitializeEx(None,0)
        if result >= 0:
            self.initialized = True
        elif result & 0xffffffff != 0x80010106:  # Existing STA may also call these interfaces.
            check(result)
        try:
            check(self.ole.CoCreateInstance(c.byref(GUID('bcde0395-e52f-467c-8e3d-c4579291692e')),None,1,
                c.byref(GUID('a95664d2-9614-4f35-a746-de8db63617e6')),c.byref(self.enumerator)))
            # eRender, eConsole: the default output used for system volume keys.
            check(self.call(self.enumerator,4,c.c_long,(c.c_int,c.c_int,c.POINTER(c.c_void_p)),0,0,c.byref(self.device)))
            pointer = c.c_void_p()
            check(self.call(self.device,5,c.c_long,(c.POINTER(c.c_void_p),),c.byref(pointer)))
            try:
                self.id = c.wstring_at(pointer)
            finally:
                self.ole.CoTaskMemFree(pointer)
            self.name = self.friendly_name()
            check(self.call(self.device,3,c.c_long,(c.POINTER(GUID),c.c_uint32,c.c_void_p,c.POINTER(c.c_void_p)),
                c.byref(GUID('5cdf2c82-841e-4546-9722-0cf74078229a')),23,None,c.byref(self.volume)))
        except Exception:
            self.close()
            raise

    def friendly_name(self):
        class PROPERTYKEY(c.Structure):
            _fields_ = [('fmtid',GUID),('pid',c.c_uint32)]
        store,value = c.c_void_p(),(c.c_uint64*3)()
        try:
            check(self.call(self.device,4,c.c_long,(c.c_uint32,c.POINTER(c.c_void_p)),0,c.byref(store)))
            key = PROPERTYKEY(GUID('a45c254e-df1c-4efd-8020-67d146a850e0'),14)
            check(self.call(store,5,c.c_long,(c.POINTER(PROPERTYKEY),c.c_void_p),c.byref(key),c.byref(value)))
            propsys = c.WinDLL('propsys')
            propsys.PropVariantToStringWithDefault.argtypes = [c.c_void_p,c.c_wchar_p]
            propsys.PropVariantToStringWithDefault.restype = c.c_wchar_p
            return propsys.PropVariantToStringWithDefault(c.byref(value),'Windows default output')
        except OSError:
            return 'Windows default output'
        finally:
            self.ole.PropVariantClear(c.byref(value))
            self.release(store)

    def read(self):
        volume,muted = c.c_float(),c.c_int()
        check(self.call(self.volume,9,c.c_long,(c.POINTER(c.c_float),),c.byref(volume)))
        check(self.call(self.volume,15,c.c_long,(c.POINTER(c.c_int),),c.byref(muted)))
        return {'connected':True,'available':True,'enabled':True,'deviceId':self.id,
                'deviceName':self.name,'volume':round(volume.value,6),'muted':bool(muted.value),'updated':time.time()}

    def set_volume(self,value):
        check(self.call(self.volume,7,c.c_long,(c.c_float,c.c_void_p),value,None))

    def set_mute(self,value):
        check(self.call(self.volume,14,c.c_long,(c.c_int,c.c_void_p),value,None))

    def close(self):
        for pointer in (self.volume,self.device,self.enumerator):
            self.release(pointer)
        self.enumerator,self.device,self.volume = c.c_void_p(),c.c_void_p(),c.c_void_p()
        if self.initialized:
            self.ole.CoUninitialize()
            self.initialized = False

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class SystemVolume:
    def __init__(self,factory=Endpoint):self.factory=factory

    def state(self):
        try:
            with self.factory() as endpoint:return endpoint.read()
        except OSError as error:
            return {'connected':False,'available':False,'enabled':False,'message':str(error),'updated':time.time()}

    def command(self,data):
        action,value = data.get('action'),data.get('value')
        if action=='volume':
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
                raise ValueError('Volume must be between 0 and 100%')
        elif action=='mute':
            if not isinstance(value,bool):raise ValueError('Invalid mute value')
        else:
            raise ValueError('Unknown Windows volume action')
        if not isinstance(data.get('deviceId'),str) or not data['deviceId']:
            raise ValueError('Wait for the Windows default output to connect')
        with self.factory() as endpoint:
            if data['deviceId']!=endpoint.id:
                raise ValueError('Windows output changed. Try the volume control again.')
            if action=='volume':endpoint.set_volume(value)
            else:endpoint.set_mute(value)
            return endpoint.read()
