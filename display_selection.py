"""Select the Edge without depending on monitor order or desktop coordinates."""


def startup_display(screens, auto_edge=True, windowed=False):
    if not auto_edge or windowed:
        return None, None
    matches = []
    for index, screen in enumerate(screens):
        width, height = screen.width, screen.height
        if width <= 0 or height <= 0:
            continue
        if (width, height) == (2560, 720):
            return index, screen
        # Retain support for an Edge running at a reduced resolution. Prefer
        # the native resolution over other ultrawide monitors on the same PC.
        if abs(width / height - 2560 / 720) < .04:
            matches.append((abs(width - 2560), index, screen))
    if matches:
        _, index, screen = min(matches, key=lambda item: item[0])
        return index, screen
    return None, None
