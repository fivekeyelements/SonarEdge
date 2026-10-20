"""Default output selection, stale device protection and endpoint-only writes."""
import unittest
import asyncio
from unittest.mock import Mock
from system_volume import SystemVolume


class SystemVolumeTests(unittest.TestCase):
    def setUp(self):
        self.endpoint=Mock()
        self.endpoint.id='current-output'
        self.endpoint.read.return_value={'connected':True,'deviceId':'current-output','volume':.4,'muted':False}
        self.endpoint.__enter__=Mock(return_value=self.endpoint)
        self.endpoint.__exit__=Mock(return_value=False)
        self.factory=Mock(return_value=self.endpoint)
        self.volume=SystemVolume(self.factory)

    def test_reading_system_volume_never_changes_audio(self):
        self.assertEqual(self.volume.state()['volume'],.4)
        self.endpoint.set_volume.assert_not_called();self.endpoint.set_mute.assert_not_called()

    def test_volume_and_mute_write_only_the_current_default_endpoint(self):
        self.volume.command({'action':'volume','value':.3,'deviceId':'current-output'})
        self.endpoint.set_volume.assert_called_once_with(.3)
        self.endpoint.set_mute.assert_not_called()
        self.volume.command({'action':'mute','value':True,'deviceId':'current-output'})
        self.endpoint.set_mute.assert_called_once_with(True)

    def test_old_output_commands_never_change_the_new_default_device(self):
        with self.assertRaisesRegex(ValueError,'output changed'):
            self.volume.command({'action':'volume','value':.7,'deviceId':'previous-output'})
        self.endpoint.set_volume.assert_not_called();self.endpoint.set_mute.assert_not_called()

    def test_invalid_values_are_rejected_before_accessing_windows_audio(self):
        for data in ({'action':'volume','value':v,'deviceId':'current-output'} for v in (-1,2,True,'0.5',float('nan'))):
            with self.assertRaises(ValueError):self.volume.command(data)
        for data in ({'action':'mute','value':1,'deviceId':'current-output'},
                     {'action':'volume','value':.3},{'action':'route','value':.3}):
            with self.assertRaises(ValueError):self.volume.command(data)
        self.factory.assert_not_called()

    def test_no_default_output_reports_offline_without_falling_back_to_sonar(self):
        self.factory.side_effect=OSError('No playback device')
        state=self.volume.state()
        self.assertFalse(state['connected']);self.assertFalse(state['available'])


class SystemVolumeDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_volume_dispatch_never_calls_sonar(self):
        import server
        bridge=server.Bridge()
        bridge.system_volume_lock=asyncio.Lock()
        bridge.system_volume.command=Mock(return_value={'connected':True,'volume':.3})
        bridge.sonar.command=Mock()
        data={'action':'volume','value':.3,'deviceId':'current-output'}
        result=await bridge.dispatch('/api/system-volume',data)
        self.assertEqual(bridge.state['systemVolume'],result)
        bridge.system_volume.command.assert_called_once_with(data)
        bridge.sonar.command.assert_not_called()
        bridge.loop.close()


if __name__=='__main__':unittest.main()
