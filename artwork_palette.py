"""Small, cached album palettes; uses the Windows image decoder already present."""
import colorsys
from collections import Counter


def palette_from_pixels(pixels):
    bins = Counter()
    for r, g, b in pixels:
        hue, light, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if .10 < light < .92 and saturation > .12:
            bins[(r // 24, g // 24, b // 24)] += .25 + saturation
    if not bins:
        # Monochrome artwork remains neutral instead of inventing a bright hue.
        return {'accent': '#d5dce5', 'secondary': '#9faab8', 'background': '#252b35'}
    choices = sorted(bins, key=bins.get, reverse=True)
    def hls(bucket):
        return colorsys.rgb_to_hls(*[min(1, (c * 24 + 12) / 255) for c in bucket])
    first = hls(choices[0])
    second = next((hls(c) for c in choices[1:] if min(abs(hls(c)[0]-first[0]), 1-abs(hls(c)[0]-first[0])) > .10), first)
    def hex_color(hue, light, saturation):
        return '#' + ''.join(f'{round(v*255):02x}' for v in colorsys.hls_to_rgb(hue, light, saturation))
    return {'accent': hex_color(first[0], .74, max(.35, min(.78, first[2]))),
            'secondary': hex_color(second[0], .64, max(.3, min(.75, second[2]))),
            'background': hex_color(first[0], .18, min(.55, first[2]))}


def from_image(body):
    if not body:
        return None
    stream = original = small = None
    try:
        import clr
        clr.AddReference('System.Drawing')
        from System import Array, Byte
        from System.IO import MemoryStream
        from System.Drawing import Bitmap
        stream = MemoryStream(Array[Byte](body))
        original = Bitmap(stream)
        if original.Width * original.Height > 24_000_000:
            return None
        small = Bitmap(original, 24, 24)
        pixels = []
        for y in range(24):
            for x in range(24):
                color = small.GetPixel(x, y)
                if color.A > 128:
                    pixels.append((color.R, color.G, color.B))
        return palette_from_pixels(pixels)
    except Exception:
        return None
    finally:
        for resource in (small, original, stream):
            if resource is not None:
                resource.Dispose()
