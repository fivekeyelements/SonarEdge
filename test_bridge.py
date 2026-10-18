"""Contract checks without changing the user's playback or mixer."""
import asyncio
import copy
import math
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock
import server


class PreferenceTests(unittest.TestCase):
    def test_artwork_effects_and_live_controls_round_trip(self):
        prefs=copy.deepcopy(server.DEFAULTS)
        prefs['artworkEffects'].update(colors='all',playerBackground='artwork',mixerBackground='colors',appBackground='colors',motion=False,intensity=.6,blur=65)
        prefs.update(showMeters=False,showChatMix=False)
        self.assertEqual(server.validate_preferences(prefs),prefs)
        prefs['artworkEffects'].update(colors='invalid',intensity=float('nan'),blur=500)
        result=server.validate_preferences(prefs)
        self.assertEqual(result['artworkEffects']['colors'],'music')
        self.assertEqual(result['artworkEffects']['intensity'],.45)
        self.assertEqual(result['artworkEffects']['blur'],90)
    def test_custom_actions_and_artwork_round_trip(self):
        prefs=copy.deepcopy(server.DEFAULTS)
        prefs.update(shortcuts=['next','sonar','playpause'],shortcutLabels=False,
                     shortcutAppearance={'sonar':{'label':'Mixer','icon':'headphones'}})
        prefs['appearance']['artworkSize']=224
        self.assertEqual(server.validate_preferences(prefs),prefs)
        prefs['shortcuts']=[]
        self.assertEqual(server.validate_preferences(prefs)['shortcuts'],[])
        prefs['shortcuts']=['stop']*9
        with self.assertRaises(ValueError):server.validate_preferences(prefs)

    def test_action_content_is_validated(self):
        prefs=copy.deepcopy(server.DEFAULTS)
        prefs['shortcutAppearance']={'sonar':{'label':'A'*50,'icon':'<script>'},'evil':{'icon':'play'}}
        prefs['appearance']['artworkSize']=999
        result=server.validate_preferences(prefs)
        self.assertEqual(result['shortcutAppearance'],{'sonar':{'label':'A'*24}})
        self.assertEqual(result['appearance']['artworkSize'],256)

    def test_text_size_survives_settings_export_and_rejects_invalid_sizes(self):
        prefs = copy.deepcopy(server.DEFAULTS)
        prefs['appearance'].pop('textScale')
        self.assertEqual(server.validate_preferences(prefs)['appearance']['textScale'], 1)
        for scale in (1, 1.12, 1.25):
            prefs['appearance']['textScale'] = scale
            self.assertEqual(server.validate_preferences(prefs)['appearance']['textScale'], scale)
        for scale in (-1, 100, True, '1.25', float('nan')):
            prefs['appearance']['textScale'] = scale
            self.assertEqual(server.validate_preferences(prefs)['appearance']['textScale'], 1)

    def test_auto_edge_defaults_on_for_older_settings_and_can_be_disabled(self):
        prefs = copy.deepcopy(server.DEFAULTS)
        prefs.pop('autoEdge')
        self.assertTrue(server.validate_preferences(prefs)['autoEdge'])
        prefs['autoEdge'] = False
        self.assertFalse(server.validate_preferences(prefs)['autoEdge'])

    def test_complete_default_round_trip(self):
        self.assertEqual(server.validate_preferences(copy.deepcopy(server.DEFAULTS)), server.DEFAULTS)

    def test_older_settings_gain_background_and_player_fields(self):
        old = {k: v for k, v in server.DEFAULTS.items() if k not in ('background', 'appearance', 'playerApp')}
        validated = server.validate_preferences(old)
        self.assertEqual(validated['playerApp'], 'musicbee')
        self.assertEqual(validated['background']['kind'], 'gradient')

    def test_cannot_hide_every_channel(self):
        prefs = copy.deepcopy(server.DEFAULTS)
        for channel in prefs['channels']:
            channel['visible'] = False
        with self.assertRaises(ValueError):
            server.validate_preferences(prefs)

    def test_duplicate_channels_are_rejected(self):
        prefs = copy.deepcopy(server.DEFAULTS)
        prefs['channels'][0]['id'] = 'game'
        with self.assertRaises(ValueError):
            server.validate_preferences(prefs)

    def test_appearance_bounds_and_invalid_color(self):
        prefs = copy.deepcopy(server.DEFAULTS)
        prefs['appearance'].update(panelOpacity=10, roundness=-2, panelColor='javascript:x')
        prefs['background'].update(dim=float('nan'), blur=100)
        validated = server.validate_preferences(prefs)
        self.assertEqual(validated['appearance']['panelOpacity'], 1)
        self.assertEqual(validated['appearance']['roundness'], 0)
        self.assertEqual(validated['appearance']['panelColor'], server.DEFAULTS['appearance']['panelColor'])
        self.assertTrue(math.isfinite(validated['background']['dim']))
        self.assertEqual(validated['background']['blur'], 24)

    def test_script_and_local_file_urls_are_rejected(self):
        for source in ('javascript:alert(1)', 'file:///C:/secret.txt', '/backgrounds/../../secret.png', 'https://name:pass@example.com/a.png'):
            prefs = copy.deepcopy(server.DEFAULTS)
            prefs['background']['source'] = source
            with self.assertRaises(ValueError, msg=source):
                server.validate_preferences(prefs)

    def test_direct_url_and_uploaded_assets_are_accepted(self):
        for source in ('https://example.com/background.jpg', '/backgrounds/' + 'a' * 64 + '.webm'):
            prefs = copy.deepcopy(server.DEFAULTS)
            prefs['background']['source'] = source
            self.assertEqual(server.validate_preferences(prefs)['background']['source'], source)


class SonarTests(unittest.TestCase):
    def test_chatmix_hardware_control_never_writes(self):
        sonar=server.Sonar()
        with patch.object(sonar,'request',return_value={'balance':0,'state':'finiteWheel'}) as request:
            with self.assertRaisesRegex(ValueError,'headset'):
                sonar.command({'action':'chatmix','value':.2})
            self.assertFalse(any(call.args[1:] == ('PUT',) for call in request.call_args_list))

    def test_chatmix_rejects_invalid_values_before_contacting_sonar(self):
        sonar=server.Sonar()
        with patch.object(sonar,'request') as request:
            for value in (-2,2,float('nan'),True,'0'):
                with self.assertRaises(ValueError):sonar.command({'action':'chatmix','value':value})
            request.assert_not_called()

    def test_chatmix_uses_current_version_route_and_can_reset_to_center(self):
        sonar=server.Sonar()
        with patch.object(sonar,'request',return_value={'balance':0,'state':'enabled'}) as request,patch.object(sonar,'state',return_value={}):
            sonar.command({'action':'chatmix','value':.25})
            request.assert_any_call('/v1/chatMix?balance=0.25','PUT')
            sonar.command({'action':'chatmix','value':0})
            request.assert_any_call('/v1/chatMix?balance=0','PUT')

    def test_device_names_follow_selected_endpoint_and_refresh(self):
        sonar=server.Sonar()
        name=['Headphones (OpenRun by Shokz)']
        def response(path):
            if path=='/v1/status':return {'mode':'classic','devices':[{'virtualAudioDevice':'game','streamRedirectionDevice':'physical','isChannelEnabled':True}]}
            if path=='/volumeSettings/classic':return {'masters':{'classic':{'volume':1}},'devices':{'game':{'classic':{'volume':.06}}}}
            if path=='/audioDevices':return [{'id':'physical','friendlyName':name[0],'state':'active','role':'none','dataFlow':'render'}]
            if path=='/configs':return []
            raise AssertionError(path)
        with patch.object(sonar,'request',side_effect=response),patch('server.time.monotonic',return_value=100):
            channel=sonar.state()['channels']['game']
            self.assertEqual(channel['deviceName'],name[0]);self.assertTrue(channel['deviceAvailable'])
            self.assertTrue(channel['canRoute']);self.assertEqual(channel['volume'],.06)
            sonar.catalog_data()
        name[0]='Speakers (Realtek USB Audio)'
        with patch.object(sonar,'request',side_effect=response),patch('server.time.monotonic',return_value=104):
            self.assertEqual(sonar.state()['channels']['game']['deviceName'],name[0])
            self.assertEqual(sonar.catalog_data()['devices'][0]['friendlyName'],name[0])

    def test_device_metadata_failure_keeps_mixer_available(self):
        sonar=server.Sonar()
        with patch.object(sonar,'request',side_effect=[{'mode':'classic','devices':[]},{'masters':{'classic':{'volume':.5}},'devices':{}}]),patch.object(sonar,'audio_devices',side_effect=OSError('offline')):
            state=sonar.state()
        self.assertTrue(state['connected']);self.assertEqual(state['channels']['master']['volume'],.5)
        self.assertEqual(state['channels']['game']['deviceName'],'')
    def test_only_loopback_discovery_is_allowed(self):
        for url in ('http://10.0.0.1:3333', 'https://example.com', 'file:///test', 'https://a:b@localhost'):
            with self.assertRaises(ValueError):
                server.Sonar.loopback_url(url)
        self.assertEqual(server.Sonar.loopback_url('http://127.0.0.1:123/'), 'http://127.0.0.1:123')

    def test_nonfinite_and_out_of_range_volume_never_writes(self):
        for value in (-1, 1.1, float('nan'), float('inf')):
            sonar = server.Sonar()
            with patch.object(sonar, 'request', return_value='classic') as request:
                with self.assertRaises(ValueError):
                    sonar.command({'channel': 'game', 'action': 'volume', 'value': value})
                self.assertFalse(any(c.args[1:] == ('PUT',) for c in request.call_args_list))

    def test_classic_volume_and_stream_mute_use_correct_channels(self):
        for mode, data, expected in [
            ('classic', {'channel':'master','action':'volume','value':.25}, '/volumeSettings/classic/Master/Volume/0.25'),
            ('stream', {'channel':'chat','action':'mute','value':True}, '/volumeSettings/streamer/monitoring/chatRender/isMuted/true'),
        ]:
            sonar = server.Sonar()
            with patch.object(sonar, 'request', return_value=mode) as request, patch.object(sonar, 'state', return_value={}):
                sonar.command(data)
                request.assert_any_call(expected, 'PUT')


class PlayerSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_album_colors_retry_after_a_transient_startup_failure(self):
        import datetime
        import time
        from types import SimpleNamespace as NS
        media=server.Media()
        props=NS(title='Track',artist='Artist',album_title='Album')
        controls=NS(**{key:True for key in ('is_play_pause_toggle_enabled','is_previous_enabled','is_next_enabled','is_stop_enabled','is_playback_position_enabled','is_shuffle_enabled','is_repeat_enabled')})
        info=NS(controls=controls,playback_status=4,is_shuffle_active=None,auto_repeat_mode=None)
        session=NS(source_app_user_model_id='MusicBee.exe',try_get_media_properties_async=AsyncMock(return_value=props),
                   get_playback_info=lambda:info,get_timeline_properties=lambda:NS(position=datetime.timedelta(seconds=10),end_time=datetime.timedelta(seconds=60)))
        media.art_key=('MusicBee.exe','Track','Artist','Album');media.art=b'cached artwork'
        palette={'accent':'#f08989','secondary':'#e85e5e','background':'#471515'}
        clock=[100]
        with patch.object(media,'session',new=AsyncMock(return_value=session)),patch('server.musicbee_bridge.state',return_value=None),patch('server.time',NS(monotonic=lambda:clock[0],time=time.time)),patch('server.artwork_palette.from_image',side_effect=[None,palette]) as decode:
            self.assertIsNone((await media.state())['palette'])
            self.assertIsNone((await media.state())['palette'])
            self.assertEqual(decode.call_count,1)
            clock[0]=104
            self.assertEqual((await media.state())['palette'],palette)
            self.assertEqual((await media.state())['palette'],palette)
            self.assertEqual(decode.call_count,2)
    async def test_musicbee_volume_does_not_control_a_different_selected_player(self):
        from types import SimpleNamespace
        media=server.Media()
        other=SimpleNamespace(source_app_user_model_id='Spotify.exe')
        with patch.object(media,'session',new=AsyncMock(return_value=other)),patch('server.musicbee_bridge.request') as write,patch('server.musicbee_bridge.state') as read:
            with self.assertRaises(ValueError):await media.command({'action':'volume','value':.3})
            read.assert_not_called();write.assert_not_called()

    async def test_musicbee_helper_checks_values_before_writing(self):
        from types import SimpleNamespace
        media=server.Media()
        bee=SimpleNamespace(source_app_user_model_id='MusicBee.exe')
        with patch.object(media,'session',new=AsyncMock(return_value=bee)),patch.object(media,'state',new=AsyncMock(return_value={})),patch('server.musicbee_bridge.state',return_value={'duration':120}),patch('server.musicbee_bridge.request') as write:
            for action,value in [('volume',2),('volume',float('nan')),('volume',True),('seek',121),('seek',-1)]:
                with self.assertRaises(ValueError):await media.command({'action':action,'value':value})
            write.assert_not_called()
            await media.command({'action':'seek','value':60})
            write.assert_called_once_with('seek',60)

    async def test_selected_player_never_falls_back_to_another_app(self):
        class Session:
            def __init__(self, source):
                self.source_app_user_model_id = source
        bee, spotify = Session('MusicBee.exe'), Session('Spotify.exe')
        class Manager:
            def get_sessions(self):
                return [spotify, bee]
            def get_current_session(self):
                return spotify
        media = server.Media()
        media.manager = Manager()
        for selection, expected in [('musicbee', bee), ('Spotify.exe', spotify), ('auto', spotify), ('Unavailable.exe', None)]:
            with patch.dict(server.BRIDGE.preferences, {'playerApp': selection}):
                self.assertIs(await media.session(), expected)

    async def test_running_players_are_listed_without_musicbee_duplicates(self):
        class Session:
            def __init__(self, source):
                self.source_app_user_model_id = source
        class Manager:
            def get_sessions(self):
                return [Session('MusicBee.exe'), Session('Spotify.exe')]
        media = server.Media()
        media.manager = Manager()
        with patch.dict(server.BRIDGE.preferences, {'playerApp': 'musicbee'}):
            players = await media.players()
        self.assertEqual([p['name'] for p in players], ['MusicBee', 'Windows active media app', 'Spotify'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
