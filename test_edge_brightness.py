"""Brightness range, device isolation, and handle cleanup without touching real displays."""
from contextlib import contextmanager
import unittest
from edge_brightness import EdgeBrightness, device_id


class Backend:
    def __init__(self):
        self.edge={'identity':r'\\?\DISPLAY#CRXED00#edge','description':'Generic PnP Monitor'}
        self.other={'identity':r'\\?\DISPLAY#SAM767D#main','description':'Generic PnP Monitor'}
        self.values=(20,120,220)
        self.opened=[]
        self.closed=[]
        self.writes=[]
        self.fail=False

    def devices(self): return [self.other,self.edge]

    @contextmanager
    def physical(self, device):
        self.opened.append(device)
        try: yield 'handle'
        finally: self.closed.append(device)

    def read(self, handle): return self.values

    def write(self, handle, value):
        if self.fail: raise OSError('Display disconnected')
        self.writes.append(value)
        self.values=(self.values[0],value,self.values[2])


class BrightnessTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend()
        self.service=EdgeBrightness(self.backend)

    def test_only_identified_edge_is_opened_and_hardware_range_is_scaled(self):
        info=self.service.info()
        self.assertEqual(info['displays'],[{'id':device_id(self.backend.edge),'name':'XENEON EDGE','brightness':50}])
        self.assertEqual(self.backend.opened,[self.backend.edge])
        self.assertEqual(self.backend.closed,self.backend.opened)

    def test_changes_only_selected_edge_and_reads_back_actual_brightness(self):
        result=self.service.command({'action':'brightness','id':device_id(self.backend.edge),'value':25})
        self.assertEqual(self.backend.writes,[70])
        self.assertEqual(result['brightness'],25)
        self.assertEqual(self.backend.opened,self.backend.closed)

    def test_missing_or_unrelated_monitor_cannot_be_written(self):
        for identity in ('old-disconnected-id',device_id(self.backend.other)):
            with self.assertRaises(ValueError):
                self.service.command({'action':'brightness','id':identity,'value':50})
        self.assertEqual(self.backend.opened,[])
        self.assertEqual(self.backend.writes,[])

    def test_invalid_requests_cannot_write_hardware(self):
        for value in (True,None,'25',25.5,float('nan'),-1,101):
            with self.assertRaises(ValueError):
                self.service.command({'action':'brightness','id':device_id(self.backend.edge),'value':value})
        with self.assertRaises(ValueError):self.service.command({'action':'reset','value':50})
        self.assertEqual(self.backend.opened,[])

    def test_write_failure_still_closes_monitor_handles(self):
        self.backend.fail=True
        with self.assertRaises(OSError):
            self.service.command({'action':'brightness','id':device_id(self.backend.edge),'value':50})
        self.assertEqual(self.backend.opened,self.backend.closed)

    def test_invalid_hardware_range_disables_the_slider_without_writing(self):
        self.backend.values=(0,150,100)
        info=self.service.info()['displays'][0]
        self.assertIsNone(info['brightness'])
        self.assertIn('invalid brightness range',info['error'])
        with self.assertRaises(OSError):
            self.service.command({'action':'brightness','id':device_id(self.backend.edge),'value':50})
        self.assertEqual(self.backend.writes,[])
        self.assertEqual(self.backend.opened,self.backend.closed)

    def test_no_edge_provides_a_clear_status(self):
        self.backend.edge['identity']=r'\\?\DISPLAY#SNY07E8#second'
        info=self.service.info()
        self.assertEqual(info['displays'],[])
        self.assertIn('Connect a XENEON EDGE',info['message'])
        self.assertEqual(self.backend.opened,[])


if __name__=='__main__': unittest.main()
