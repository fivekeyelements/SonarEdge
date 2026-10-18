"""Read-only Windows endpoint peak meters. No audio buffers are recorded."""
import ctypes
import math
import threading
import time
import uuid

CHANNELS = ('master', 'game', 'chat', 'media', 'aux', 'mic')


class GUID(ctypes.Structure):
    _fields_ = [('bytes', ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


def targets_from_devices(devices):
    """Use Sonar's virtual endpoints, never their shared physical output."""
    result = {}
    roles = {'game': 'game', 'chatRender': 'chat', 'media': 'media', 'aux': 'aux', 'chatCapture': 'mic'}
    for device in devices:
        key = roles.get(device.get('role'))
        if not key or device.get('state', 'active') != 'active':
            continue
        if device.get('dataFlow') != ('capture' if key == 'mic' else 'render'):
            continue
        if isinstance(device.get('id'), str) and device['id']:
            result[key] = device['id']
    return result


def normalized(value):
    return round(max(0, min(1, value)), 6) if math.isfinite(value) else None


class CoreAudio:
    """Own all COM references on the single sampling thread."""
    def __init__(self):
        self.ole = ctypes.OleDLL('ole32')
        self.ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.ole.CoInitializeEx(None, 0)
        self.ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32,
                                             ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        self.enumerator = ctypes.c_void_p()
        self.meters = {}
        try:
            self.ole.CoCreateInstance(ctypes.byref(GUID('bcde0395-e52f-467c-8e3d-c4579291692e')), None, 1,
                ctypes.byref(GUID('a95664d2-9614-4f35-a746-de8db63617e6')), ctypes.byref(self.enumerator))
        except Exception:
            self.ole.CoUninitialize()
            raise

    @staticmethod
    def call(pointer, slot, restype, args, *values):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        function = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *args)(table[slot])
        return function(pointer, *values)

    @classmethod
    def release(cls, pointer):
        if pointer:
            cls.call(pointer, 2, ctypes.c_ulong, ())

    def activate(self, endpoint):
        device, meter = ctypes.c_void_p(), ctypes.c_void_p()
        hr = self.call(self.enumerator, 5, ctypes.c_long, (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)), endpoint, ctypes.byref(device))
        if hr < 0:
            raise OSError('Audio endpoint unavailable')
        try:
            iid = GUID('c02216f6-8c67-4b5b-9d00-d008e73e0064')
            hr = self.call(device, 3, ctypes.c_long,
                (ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
                ctypes.byref(iid), 23, None, ctypes.byref(meter))
            if hr < 0:
                raise OSError('Audio peak meter unavailable')
            return meter
        finally:
            self.release(device)

    def sample(self, targets):
        for key in list(self.meters):
            if key not in targets or self.meters[key][0] != targets[key]:
                self.release(self.meters.pop(key)[1])
        levels = dict.fromkeys(CHANNELS)
        for key, endpoint in targets.items():
            try:
                if key not in self.meters:
                    self.meters[key] = (endpoint, self.activate(endpoint))
                value = ctypes.c_float()
                hr = self.call(self.meters[key][1], 3, ctypes.c_long, (ctypes.POINTER(ctypes.c_float),), ctypes.byref(value))
                if hr < 0:
                    raise OSError('Audio device changed')
                levels[key] = normalized(value.value)
            except (OSError, ValueError):
                if key in self.meters:
                    self.release(self.meters.pop(key)[1])
        outputs = [levels[key] for key in ('game', 'chat', 'media', 'aux') if levels[key] is not None]
        # Sonar has multiple physical destinations in Classic mode. This is an
        # activity summary of measured output channels, not a fictitious mix.
        levels['master'] = max(outputs) if outputs else None
        return levels

    def close(self):
        for _, meter in self.meters.values():
            self.release(meter)
        self.meters.clear()
        self.release(self.enumerator)
        self.ole.CoUninitialize()


class AudioMeters:
    def __init__(self, factory=CoreAudio):
        self.factory = factory
        self.targets = {}
        self.current = {'levels': dict.fromkeys(CHANNELS), 'sampledAt': 0}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None

    def configure(self, devices):
        targets = targets_from_devices(devices)
        with self.lock:
            self.targets = targets

    def snapshot(self):
        with self.lock:
            levels, sampled = dict(self.current['levels']), self.current['sampledAt']
        if time.time() - sampled > 1:
            levels = dict.fromkeys(CHANNELS)
        return {'levels': levels, 'sampledAt': sampled, 'connected': any(v is not None for v in levels.values()),
                'source': 'Windows Core Audio', 'masterSource': 'Combined output channel activity', 'preFader': True}

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name='Sonar peak meters', daemon=True)
            self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            reader = None
            try:
                reader = self.factory()
                while not self.stopped.is_set():
                    with self.lock:
                        targets = dict(self.targets)
                    levels = reader.sample(targets)
                    with self.lock:
                        self.current = {'levels': levels, 'sampledAt': time.time()}
                    self.stopped.wait(.05)
            except (OSError, ValueError):
                self.stopped.wait(2)
            finally:
                if reader:
                    reader.close()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(2)
