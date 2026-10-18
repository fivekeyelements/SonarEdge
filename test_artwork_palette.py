import unittest
from artwork_palette import palette_from_pixels, from_image

class PaletteTests(unittest.TestCase):
    def test_dark_borders_do_not_overwhelm_album_colors(self):
        palette=palette_from_pixels([(0,0,0)]*500+[(220,25,45)]*80+[(20,50,190)]*40)
        accent=palette['accent']
        self.assertGreater(int(accent[1:3],16),int(accent[3:5],16))
        self.assertNotEqual(palette['accent'],palette['secondary'])

    def test_monochrome_has_a_neutral_readable_fallback(self):
        self.assertEqual(palette_from_pixels([(0,0,0),(255,255,255),(100,100,100)])['accent'],'#d5dce5')

    def test_broken_artwork_does_not_break_media_controls(self):
        self.assertIsNone(from_image(b'not an image'))

if __name__=='__main__':unittest.main(verbosity=2)
