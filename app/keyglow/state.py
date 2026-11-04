"""The keyboard's lighting, as the firmware keeps it (firmware/keyglow/keyglow.h), and what it
looks like: the ALT's keys and edge lights, and each effect worked out as the firmware draws it,
so the app's picture shows what the keyboard shows."""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field

STATE_VERSION = 2
PROTOCOL = 1
STATE_SIZE = 250
OLD_SIZE = 222      # version 1's state, which Keyglow's first firmware (0.1.0-0.1.1) keeps
FIRMWARE = 4        # the firmware Keyglow carries (KG_FIRMWARE); a keyboard on less is offered it

KEYS = 67           # LEDs 0-66, under the keys in layout order
EDGE = 38           # LEDs 67-104, round the edge
ON_KEYS, ON_EDGE = 0x01, 0x02
X_CAPS, X_FN = 0x01, 0x02     # State.extras: Caps Lock's light, the Fn layer's lights
SPARE = 20
IDLE_CHOICES = (1, 2, 5, 10, 15, 30, 60)     # minutes

# Effects, by the firmware's numbers. 0 is "off", which the app shows as a part switched off.
KEY_EFFECTS = {
    1: 'Solid colour',
    2: 'Per key',
    3: 'Breathing',
    4: 'Rainbow wave',
    5: 'Colour cycle',
    6: 'Gradient',
    7: 'Light up when pressed',
}
EDGE_EFFECTS = {
    1: 'Solid colour',
    3: 'Rainbow',
    2: 'Breathing',
    4: 'Colour cycle',
    5: 'Gradient',
    6: 'Chase',
}
KEY_SOLID, KEY_CUSTOM, KEY_BREATHING, KEY_RAINBOW, KEY_CYCLE, KEY_GRADIENT, KEY_REACTIVE = range(1, 8)
EDGE_SOLID, EDGE_BREATHING, EDGE_RAINBOW, EDGE_CYCLE, EDGE_GRADIENT, EDGE_CHASE = range(1, 7)

# What each effect uses: (first colour's name, second colour's name, speed). None: not used.
KEY_NEEDS = {
    KEY_SOLID: ('Colour', None, False),
    KEY_CUSTOM: (None, None, False),
    KEY_BREATHING: ('Colour', None, True),
    KEY_RAINBOW: (None, None, True),
    KEY_CYCLE: (None, None, True),
    KEY_GRADIENT: ('Left', 'Right', False),
    KEY_REACTIVE: ('When pressed', 'Background', True),
}
EDGE_NEEDS = {
    EDGE_SOLID: ('Colour', None, False),
    EDGE_BREATHING: ('Colour', None, True),
    EDGE_RAINBOW: (None, None, True),
    EDGE_CYCLE: (None, None, True),
    EDGE_GRADIENT: ('Left', 'Right', False),
    EDGE_CHASE: ('Streak', 'Background', True),
}

RGB = tuple  # (r, g, b), 0-255


@dataclass
class Zone:
    mode: int = 4
    speed: int = 96
    bright: int = 255
    a: RGB = (255, 209, 220)
    b: RGB = (194, 37, 92)

    def pack(self) -> bytes:
        return bytes((self.mode, self.speed, self.bright, *self.a, *self.b))

    @classmethod
    def unpack(cls, data: bytes) -> 'Zone':
        return cls(data[0], data[1], data[2], tuple(data[3:6]), tuple(data[6:9]))


@dataclass
class State:
    on: int = ON_KEYS | ON_EDGE
    master: int = 255
    keys: Zone = field(default_factory=lambda: Zone(mode=KEY_RAINBOW))
    edge: Zone = field(default_factory=lambda: Zone(mode=EDGE_RAINBOW))
    perkey: list = field(default_factory=lambda: [(255, 255, 255)] * KEYS)
    # version 2: the firmware's defaults (kg_extra_defaults)
    extras: int = X_CAPS | X_FN
    caps: RGB = (255, 255, 255)
    fn: RGB = (255, 209, 220)
    idle: int = 10                  # minutes without a key before the lights go off; 0 never
    spare: bytes = bytes(SPARE)     # kept as the keyboard has it

    def pack(self) -> bytes:
        data = bytes((STATE_VERSION, self.on, self.master)) + self.keys.pack() + self.edge.pack()
        data += b''.join(bytes(c) for c in self.perkey)
        data += bytes((self.extras, *self.caps, *self.fn, self.idle)) + bytes(self.spare)
        assert len(data) == STATE_SIZE
        return data

    @classmethod
    def unpack(cls, data: bytes) -> 'State':
        """A state as the keyboard keeps it: version 2's, or version 1's (whose extras are then
        the defaults)."""
        if len(data) not in (STATE_SIZE, OLD_SIZE):
            raise ValueError(f'a lighting state is {STATE_SIZE} bytes, not {len(data)}')
        perkey = [tuple(data[21 + i * 3:24 + i * 3]) for i in range(KEYS)]
        state = cls(data[1], data[2], Zone.unpack(data[3:12]), Zone.unpack(data[12:21]), perkey)
        if len(data) == STATE_SIZE:
            x = data[OLD_SIZE:]
            state.extras, state.caps, state.fn, state.idle = x[0], tuple(x[1:4]), tuple(x[4:7]), x[7]
            state.spare = bytes(x[8:8 + SPARE])
        return state

    def copy(self) -> 'State':
        return State.unpack(self.pack())


# The keys that light while Fn is held: those that do something on layer 1 of the firmware's
# keymap (keymap.c), and Fn itself. The tests check this against the keymap.
FN_KEYS = frozenset(
    list(range(0, 13)) + [14]                   # ` F1-F12, Mute
    + [17, 22, 23, 25, 26, 27, 29]              # brighter, USB port, USB power, PrtSc, ScrLk, Pause, End
    + [32, 43]                                  # dimmer, volume up
    + [45, 49, 50, 51, 56, 57]                  # lit parts, bootloader, NKRO, debug, PgUp, volume down
    + [63, 64, 65, 66])                         # Fn, Home, PgDn, End
CAPS_KEY = 30
# Lit for Caps Lock: its own key, and the keys right of it (A) and below it (Left Shift), whose
# light shows round its keycap where its own, under an opaque cap, doesn't (firmware 4).
CAPS_KEYS = (CAPS_KEY, 31, 44)


# --- the board -----------------------------------------------------------------------------

# (x, y, width, label) in key units, LED 0-66 in order: Drop's ALT, the 65% ANSI blocker layout.
def _row(y: float, keys) -> list:
    out, x = [], 0.0
    for item in keys:
        if isinstance(item, (int, float)):        # a gap
            x += item
            continue
        label, w = item if isinstance(item, tuple) else (item, 1.0)
        out.append((x, y, w, label))
        x += w
    return out


LAYOUT = (
    _row(0, ['Esc', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', ('Backspace', 2), 'Del'])
    + _row(1, [('Tab', 1.5), 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '[', ']', ('\\', 1.5), 'Home'])
    + _row(2, [('Caps', 1.75), 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ';', "'", ('Enter', 2.25), 'PgUp'])
    + _row(3, [('Shift', 2.25), 'Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', '/', ('Shift', 1.75), '↑', 'PgDn'])
    + _row(4, [('Ctrl', 1.25), ('Win', 1.25), ('Alt', 1.25), ('', 6.25), ('Alt', 1.25), ('Fn', 1.25), 0.5,
               '←', '↓', '→'])
)
WIDTH, HEIGHT = 16.0, 5.0       # the keys' span, in key units
assert len(LAYOUT) == KEYS

# Each LED's place as the firmware sees it (config_led.c): x 0-224 left to right, y 0-64 with
# the top row high. The effects work from these.
POINTS = [
    (8, 56), (22, 56), (35, 56), (49, 56), (63, 56), (77, 56), (91, 56), (105, 56), (118, 56), (132, 56),
    (146, 56), (160, 56), (174, 56), (195, 56), (215, 56),
    (11, 44), (28, 44), (42, 44), (56, 44), (70, 44), (84, 44), (98, 44), (112, 44), (125, 44), (139, 44),
    (153, 44), (167, 44), (181, 44), (198, 44), (215, 44),
    (13, 32), (32, 32), (46, 32), (60, 32), (73, 32), (87, 32), (101, 32), (115, 32), (129, 32), (143, 32),
    (156, 32), (170, 32), (193, 32), (215, 32), (16, 19),
    (39, 19), (53, 19), (67, 19), (80, 19), (94, 19), (108, 19), (122, 19), (136, 19), (150, 19), (163, 19),
    (182, 19), (201, 19), (215, 19), (9, 7), (27, 7),
    (44, 7), (96, 7), (148, 7), (165, 7), (188, 7), (201, 7), (215, 7),
    # the edge, from the corner by Ctrl along the front, up the right, back along the top, down the left
    (1, 1), (15, 0), (31, 0), (47, 0), (63, 0), (79, 0), (95, 0), (112, 0), (128, 0), (144, 0), (160, 0),
    (176, 0), (192, 0), (208, 0), (222, 1),
    (224, 13), (224, 25), (224, 38), (224, 50), (222, 62), (191, 64), (179, 64), (167, 64), (153, 64),
    (139, 64), (125, 64), (112, 64), (98, 64), (84, 64), (70, 64),
    (56, 64), (42, 64), (28, 64), (1, 62), (0, 50), (0, 38), (0, 25), (0, 13),
]
assert len(POINTS) == KEYS + EDGE


# --- the effects, as the firmware draws them (rgb_matrix_user.inc) --------------------------

def tick(ms: int, speed: int) -> int:
    """A zone's clock, 0-255 going round: QMK's scale16by8(timer, speed / 4 + 1), which
    multiplies by one more than it is given (FASTLED_SCALE8_FIXED)."""
    return ((ms & 0xFFFF) * (min(255, speed // 4 + 1) + 1) >> 8) & 0xFF


def _mix(a: int, b: int, w: int) -> int:
    return int(a + (b - a) * w / 255)


def lerp(a: RGB, b: RGB, w: int) -> RGB:
    return tuple(_mix(a[c], b[c], w) for c in range(3))


def hue(h: int) -> RGB:
    r, g, b = colorsys.hsv_to_rgb((h & 0xFF) / 256, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def breath(t: int) -> int:
    s = int(128 + 127 * math.sin(t / 256 * 2 * math.pi))     # QMK's sin8
    return min(255, abs(s - 128) * 2)


def fade_ms(speed: int) -> int:
    """How long a pressed key keeps glowing."""
    return 2000 - speed * 7


BLACK = (0, 0, 0)


def key_color(state: State, i: int, ms: int, pressed_ago: float | None = None) -> RGB:
    z = state.keys
    x = POINTS[i][0]
    if z.mode == KEY_SOLID:
        return z.a
    if z.mode == KEY_CUSTOM:
        return state.perkey[i]
    if z.mode == KEY_BREATHING:
        return lerp(BLACK, z.a, breath(tick(ms, z.speed)))
    if z.mode == KEY_RAINBOW:
        return hue(x - tick(ms, z.speed))
    if z.mode == KEY_CYCLE:
        return hue(tick(ms, z.speed))
    if z.mode == KEY_GRADIENT:
        return lerp(z.a, z.b, x * 255 // 224)
    if z.mode == KEY_REACTIVE:
        w = 0
        if pressed_ago is not None and pressed_ago < fade_ms(z.speed):
            w = 255 - int(pressed_ago * 255 / fade_ms(z.speed))
        return lerp(z.b, z.a, w)
    return BLACK


def edge_color(state: State, j: int, ms: int) -> RGB:
    """j: the edge light's place round the ring, 0-37."""
    z = state.edge
    if z.mode == EDGE_SOLID:
        return z.a
    if z.mode == EDGE_BREATHING:
        return lerp(BLACK, z.a, breath(tick(ms, z.speed)))
    if z.mode == EDGE_RAINBOW:
        return hue(j * 256 // EDGE - tick(ms, z.speed))
    if z.mode == EDGE_CYCLE:
        return hue(tick(ms, z.speed))
    if z.mode == EDGE_GRADIENT:
        return lerp(z.a, z.b, POINTS[KEYS + j][0] * 255 // 224)
    if z.mode == EDGE_CHASE:
        head = tick(ms, z.speed) * EDGE >> 8
        back = (head + EDGE - j) % EDGE
        return lerp(z.b, z.a, 255 - back * 32 if back < 8 else 0)
    return BLACK


def _scale(c: RGB, bright: int) -> RGB:
    return tuple(v * bright // 255 for v in c)


def colors(state: State, ms: int, pressed: dict | None = None, caps: bool = False,
           fn: bool = False) -> list:
    """Every LED's colour at a moment, as the keyboard shows it: the keys' 67, then the edge's 38.
    pressed: LED -> ms since it was pressed, for the effect that lights pressed keys. caps: Caps
    Lock is on; fn: Fn is held (each shown only if the state lights it)."""
    pressed = pressed or {}
    fn = fn and bool(state.extras & X_FN)
    caps = caps and bool(state.extras & X_CAPS)
    out = []
    for i in range(KEYS):
        if fn:
            out.append(_scale(state.fn, state.master) if i in FN_KEYS else BLACK)
        elif caps and i in CAPS_KEYS:
            out.append(_scale(state.caps, state.master))
        elif state.on & ON_KEYS:
            bright = state.keys.bright * state.master // 255
            out.append(_scale(key_color(state, i, ms, pressed.get(i)), bright))
        else:
            out.append(BLACK)
    for j in range(EDGE):
        if state.on & ON_EDGE:
            bright = state.edge.bright * state.master // 255
            out.append(_scale(edge_color(state, j, ms), bright))
        else:
            out.append(BLACK)
    return out


def moving(state: State) -> bool:
    """Whether the picture changes over time, so it needs drawing again and again."""
    keys = state.on & ON_KEYS and KEY_NEEDS.get(state.keys.mode, (0, 0, False))[2]
    edge = state.on & ON_EDGE and EDGE_NEEDS.get(state.edge.mode, (0, 0, False))[2]
    return bool(keys or edge)
