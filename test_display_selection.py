"""Startup routing must work from the EXE without special shortcut arguments."""
from types import SimpleNamespace as Screen
import unittest
from display_selection import startup_display


class StartupDisplayTests(unittest.TestCase):
    def test_default_launch_finds_edge_without_command_line_options(self):
        screens = [Screen(width=3840, height=2160), Screen(width=2560, height=720)]
        self.assertEqual(startup_display(screens), (1, screens[1]))

    def test_native_edge_wins_over_other_ultrawide_monitors(self):
        screens = [Screen(width=7680, height=2160), Screen(width=2560, height=720)]
        self.assertEqual(startup_display(screens), (1, screens[1]))

    def test_disabled_setting_and_windowed_launch_skip_automatic_placement(self):
        screens = [Screen(width=2560, height=720)]
        self.assertEqual(startup_display(screens, auto_edge=False), (None, None))
        self.assertEqual(startup_display(screens, windowed=True), (None, None))

    def test_no_edge_falls_back_without_taking_over_a_regular_monitor(self):
        screens = [Screen(width=3840, height=2160), Screen(width=3440, height=1440)]
        self.assertEqual(startup_display(screens), (None, None))

    def test_reduced_resolution_and_single_pass_screen_enumeration(self):
        screens = [Screen(width=1920, height=1080), Screen(width=1280, height=360)]
        self.assertEqual(startup_display(iter(screens)), (1, screens[1]))


if __name__ == '__main__':
    unittest.main()
