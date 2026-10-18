import threading
import time
import unittest
from unittest.mock import patch
from audio_meters import AudioMeters, targets_from_devices, normalized


class MeterTests(unittest.TestCase):
    def test_channels_use_distinct_virtual_endpoints_and_mic_capture(self):
        devices=[{'id':'game-id','role':'game','dataFlow':'render'},
                 {'id':'chat-id','role':'chatRender','dataFlow':'render'},
                 {'id':'media-id','role':'media','dataFlow':'render'},
                 {'id':'mic-render','role':'chatCapture','dataFlow':'render'},
                 {'id':'mic-capture','role':'chatCapture','dataFlow':'capture'},
                 {'id':'headphones','role':'none','dataFlow':'render'},
                 {'id':'aux-off','role':'aux','dataFlow':'render','state':'disabled'}]
        self.assertEqual(targets_from_devices(devices),{'game':'game-id','chat':'chat-id','media':'media-id','mic':'mic-capture'})

    def test_stale_or_failed_samples_never_look_like_live_signal(self):
        meters=AudioMeters()
        meters.current={'levels':{'media':.5},'sampledAt':100}
        with patch('audio_meters.time.time',return_value=100.2):
            self.assertEqual(meters.snapshot()['levels']['media'],.5)
        with patch('audio_meters.time.time',return_value=102):
            self.assertFalse(meters.snapshot()['connected'])
            self.assertIsNone(meters.snapshot()['levels']['media'])
        self.assertIsNone(normalized(float('nan')))
        self.assertEqual(normalized(1.1),1)

    def test_sampling_and_release_stay_on_the_worker_thread(self):
        owners=[];seen=threading.Event()
        class Reader:
            def __init__(self):owners.append(threading.get_ident())
            def sample(self,targets):
                owners.append(threading.get_ident());seen.set()
                return {'media':.3,'chat':0,'master':.3}
            def close(self):owners.append(threading.get_ident())
        meters=AudioMeters(Reader)
        meters.configure([{'id':'media-id','role':'media','dataFlow':'render'}])
        meters.start()
        try:
            self.assertTrue(seen.wait(1))
            self.assertEqual(meters.snapshot()['levels']['chat'],0)
        finally:meters.stop()
        self.assertEqual(len(set(owners)),1)
        self.assertNotEqual(owners[0],threading.get_ident())

if __name__=='__main__':unittest.main(verbosity=2)
