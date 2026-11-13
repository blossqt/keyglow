"""RGB Sync, and the PC's own lights beside the keyboard's: the memory sticks (through Keyglow
Lights, ram.py) and the motherboard with its headers (polychrome.py).

RGB Sync is one lighting shared, as peers, by the devices that have it on - the keyboard, the
memory, the motherboard - once two or more do. It is set on its own page (an effect every device
has, or a theme), and each device has its own lighting besides, shown while it isn't synced (the
keyboard's is kept aside while it shows the shared one). The shared lighting is kept in the
keyboard's shape (st.State), the richest of them, and each other device shows it in the nearest
effect it has (follow). RGB Sync starts off on every device.

All of it is kept in %APPDATA%\\Keyglow\\pc.json; the devices keep their lighting themselves."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, replace

from . import polychrome as poly
from . import ram
from . import state as st

PINK, ROSE = (255, 209, 220), (194, 37, 92)

# Each part's effects: number -> (name, the device's own effect, (first colour, second colour, speed))
RAM_SOLID, RAM_BREATHING, RAM_RAINBOW_WAVE, RAM_CYCLE, RAM_GRADIENT, RAM_SHIFT, RAM_WAVE, RAM_VISOR, RAM_RAIN, \
    RAM_MARQUEE, RAM_SEQUENTIAL = range(1, 12)
RAM_EFFECTS = {
    RAM_SOLID: ('Solid colour', ram.STATIC, ('Colour', None, False)),
    RAM_GRADIENT: ('Gradient', ram.STATIC, ('Top', 'Bottom', False)),
    RAM_BREATHING: ('Breathing', ram.COLOR_PULSE, ('Colour', 'Second colour', True)),
    RAM_RAINBOW_WAVE: ('Rainbow wave', ram.RAINBOW_WAVE, (None, None, True)),
    RAM_CYCLE: ('Colour cycle', ram.RAINBOW, (None, None, True)),
    RAM_SHIFT: ('Colour shift', ram.COLOR_SHIFT, ('Colour', 'Second colour', True)),
    RAM_WAVE: ('Colour wave', ram.COLOR_WAVE, ('Colour', 'Second colour', True)),
    RAM_VISOR: ('Visor', ram.VISOR, ('Colour', 'Second colour', True)),
    RAM_RAIN: ('Rain', ram.RAIN, ('Colour', 'Second colour', True)),
    RAM_MARQUEE: ('Marquee', ram.MARQUEE, ('Colour', None, True)),
    RAM_SEQUENTIAL: ('Sequential', ram.SEQUENTIAL, ('Colour', None, True)),
}
BOARD_SOLID, BOARD_BREATHING, BOARD_FLASH, BOARD_CYCLE, BOARD_RAINBOW, BOARD_RANDOM, BOARD_WAVE, BOARD_SPRING, \
    BOARD_STACK, BOARD_CRAM, BOARD_SCAN, BOARD_NEON, BOARD_WATER = range(1, 14)
BOARD_EFFECTS = {
    BOARD_SOLID: ('Solid colour', poly.STATIC, ('Colour', None, False)),
    BOARD_BREATHING: ('Breathing', poly.BREATHING, ('Colour', None, True)),
    BOARD_FLASH: ('Flash', poly.STROBE, ('Colour', None, True)),
    BOARD_RAINBOW: ('Rainbow wave', poly.RAINBOW, (None, None, True)),
    BOARD_CYCLE: ('Colour cycle', poly.SPECTRUM, (None, None, True)),
    BOARD_RANDOM: ('Random', poly.RANDOM, (None, None, True)),
    BOARD_WAVE: ('Wave', poly.WAVE, (None, None, True)),
    BOARD_SPRING: ('Spring', poly.SPRING, (None, None, True)),
    BOARD_STACK: ('Stack', poly.STACK, (None, None, True)),
    BOARD_CRAM: ('Cram', poly.CRAM, (None, None, True)),
    BOARD_SCAN: ('Scan', poly.SCAN, (None, None, True)),
    BOARD_NEON: ('Neon', poly.NEON, (None, None, False)),
    BOARD_WATER: ('Water', poly.WATER, (None, None, True)),
}
EFFECTS = {'ram': RAM_EFFECTS, 'board': BOARD_EFFECTS}


@dataclass(frozen=True)
class Part:
    """One part's lighting: following the keyboard (sync), or its own."""
    sync: bool = False
    on: bool = True
    effect: int = 1
    a: tuple = PINK
    b: tuple = ROSE
    speed: int = 96             # 0-255, as the keyboard's
    bright: int = 255

    @classmethod
    def from_dict(cls, data: dict) -> 'Part':
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        for colour in ('a', 'b'):
            if colour in known:
                known[colour] = tuple(int(c) & 0xFF for c in known[colour])[:3]
        return cls(**known)


# --- the shared lighting --------------------------------------------------------------------

def _common(colours) -> tuple:
    return Counter(tuple(c) for c in colours).most_common(1)[0][0]


# The RGB Sync page's effects: those every device has. number -> (name, keys' effect, base light's
# effect, (first colour, second colour, speed))
SYNC_OFF, SYNC_SOLID, SYNC_BREATHING, SYNC_RAINBOW, SYNC_CYCLE, SYNC_GRADIENT = range(6)
SYNC_EFFECTS = {
    SYNC_SOLID: ('Solid colour', st.KEY_SOLID, st.EDGE_SOLID, ('Colour', None, False)),
    SYNC_BREATHING: ('Breathing', st.KEY_BREATHING, st.EDGE_BREATHING, ('Colour', None, True)),
    SYNC_RAINBOW: ('Rainbow wave', st.KEY_RAINBOW, st.EDGE_RAINBOW, (None, None, True)),
    SYNC_CYCLE: ('Colour cycle', st.KEY_CYCLE, st.EDGE_CYCLE, (None, None, True)),
    SYNC_GRADIENT: ('Gradient', st.KEY_GRADIENT, st.EDGE_GRADIENT, ('Start', 'End', False)),
}


def sync_effect(lighting: st.State) -> int:
    """The RGB Sync page's effect nearest the shared lighting (as follow() reads it)."""
    if lighting.dark or not lighting.on & (st.ON_KEYS | st.ON_EDGE):
        return SYNC_OFF
    zone = lighting.keys if lighting.on & st.ON_KEYS else lighting.edge
    if lighting.on & st.ON_KEYS:
        modes = {st.KEY_BREATHING: SYNC_BREATHING, st.KEY_RAINBOW: SYNC_RAINBOW, st.KEY_CYCLE: SYNC_CYCLE,
                 st.KEY_GRADIENT: SYNC_GRADIENT}
    else:
        modes = {st.EDGE_BREATHING: SYNC_BREATHING, st.EDGE_RAINBOW: SYNC_RAINBOW, st.EDGE_CYCLE: SYNC_CYCLE,
                 st.EDGE_GRADIENT: SYNC_GRADIENT}
    return modes.get(zone.mode, SYNC_SOLID)


def sync_lighting(lighting: st.State, effect: int, a, b, speed: int, bright: int) -> st.State:
    """The shared lighting set from the RGB Sync page: one effect on every part of every device."""
    new = lighting.copy()
    new.dark = 0
    if effect == SYNC_OFF or effect not in SYNC_EFFECTS:
        new.on = 0
        return new
    _, keys, edge, _ = SYNC_EFFECTS[effect]
    new.on, new.master = st.ON_KEYS | st.ON_EDGE, bright
    new.keys = st.Zone(mode=keys, speed=speed, bright=255, a=tuple(a), b=tuple(b))
    new.edge = st.Zone(mode=edge, speed=speed, bright=255, a=tuple(a), b=tuple(b))
    return new


def with_lighting(keyboard: st.State, lighting: st.State) -> st.State:
    """The keyboard with the shared lighting: its effects, colours and brightness; its own
    settings (Caps Lock, Fn, idle, all-off) kept."""
    new = keyboard.copy()
    new.on, new.master = lighting.on, lighting.master
    new.keys = st.Zone(**vars(lighting.keys))
    new.edge = st.Zone(**vars(lighting.edge))
    new.perkey = list(lighting.perkey)
    return new


def follow(part: str, keyboard: st.State) -> Part:
    """A part's view of the shared lighting (kept in the keyboard's shape): the keys' effect - or
    the base light's while the keys are off - in the nearest effect the part has, at the same
    brightness."""
    if keyboard.dark:
        return Part(sync=True, on=False)
    if keyboard.on & st.ON_KEYS:
        zone, keys = keyboard.keys, True
    elif keyboard.on & st.ON_EDGE:
        zone, keys = keyboard.edge, False
    else:
        return Part(sync=True, on=False)
    bright = zone.bright * keyboard.master // 255
    mode, a, b = zone.mode, tuple(zone.a), tuple(zone.b)
    if keys:
        kind = {st.KEY_SOLID: 'solid', st.KEY_CUSTOM: 'solid', st.KEY_BREATHING: 'breathing',
                st.KEY_RAINBOW: 'rainbow', st.KEY_CYCLE: 'cycle', st.KEY_GRADIENT: 'gradient',
                st.KEY_REACTIVE: 'solid'}.get(mode, 'solid')
        if mode == st.KEY_CUSTOM:
            a = _common(keyboard.perkey)
        elif mode == st.KEY_REACTIVE:
            a = b                           # its background: what shows while nothing is pressed
    else:
        kind = {st.EDGE_SOLID: 'solid', st.EDGE_BREATHING: 'breathing', st.EDGE_RAINBOW: 'rainbow',
                st.EDGE_CYCLE: 'cycle', st.EDGE_GRADIENT: 'gradient', st.EDGE_CHASE: 'chase'}.get(mode, 'solid')
    if part == 'ram':
        effect, second = {'solid': (RAM_SOLID, b), 'breathing': (RAM_BREATHING, a), 'rainbow': (RAM_RAINBOW_WAVE, b),
                          'cycle': (RAM_CYCLE, b), 'gradient': (RAM_GRADIENT, b), 'chase': (RAM_VISOR, b)}[kind]
    else:
        effect, second = {'solid': (BOARD_SOLID, b), 'breathing': (BOARD_BREATHING, b),
                          'rainbow': (BOARD_RAINBOW, b), 'cycle': (BOARD_CYCLE, b),
                          'gradient': (BOARD_SOLID, b), 'chase': (BOARD_SCAN, b)}[kind]
    return Part(sync=True, on=True, effect=effect, a=a, b=second, speed=zone.speed, bright=bright)


def resolved(part: str, own: Part, keyboard: st.State) -> Part:
    """What a part shows: the keyboard's lighting if it follows it, else its own."""
    return follow(part, keyboard) if own.sync else own


# --- what each device is sent ---------------------------------------------------------------

def _scale(rgb, bright: int) -> tuple:
    return tuple(c * bright // 255 for c in rgb)


def _mix(a, b, w: float) -> tuple:
    return tuple(round(a[i] + (b[i] - a[i]) * w) for i in range(3))


def ram_request(part: Part) -> ram.Request:
    """The effect the memory is asked for."""
    if not part.on or part.effect not in RAM_EFFECTS:
        return ram.Request(ram.STATIC, 0, 0, (0, 0, 0), (0, 0, 0), ((0, 0, 0),) * ram.LEDS)
    mode = RAM_EFFECTS[part.effect][1]
    speed = 0 if part.speed < 86 else 1 if part.speed < 171 else 2
    if part.effect == RAM_GRADIENT:
        leds = tuple(_mix(part.a, part.b, i / (ram.LEDS - 1)) for i in range(ram.LEDS))
    else:
        leds = (tuple(part.a),) * ram.LEDS
    return ram.Request(mode, speed, part.bright, tuple(part.a), tuple(part.b), leds)


def board_effect(part: Part) -> tuple:
    """(the controller's effect, colour, speed): its speed runs 255 slowest to 0 fastest, and it
    has no brightness of its own, so the colour is dimmed."""
    if not part.on or part.effect not in BOARD_EFFECTS:
        return poly.OFF, (0, 0, 0), 0
    return BOARD_EFFECTS[part.effect][1], _scale(part.a, part.bright), 255 - part.speed


# --- kept on this PC ------------------------------------------------------------------------

def _file():
    from .flasher import data_folder
    return data_folder() / 'pc.json'


def _read() -> dict:
    try:
        data = json.loads(_file().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def load() -> dict:
    """{'ram': Part, 'board': Part}: what was kept, else both with RGB Sync off."""
    parts = {'ram': Part(), 'board': Part()}
    data = _read()
    for name in parts:
        try:
            if isinstance(data.get(name), dict):
                parts[name] = Part.from_dict(data[name])
        except (ValueError, TypeError):
            pass
    return parts


def _state(data: dict, key: str) -> st.State | None:
    try:
        return st.State.unpack(bytes.fromhex(data[key]))
    except (KeyError, ValueError, TypeError):
        return None


def load_sync() -> tuple[bool, st.State | None, st.State | None]:
    """(whether the keyboard's RGB Sync is on, the shared lighting, the keyboard's own lighting -
    kept aside while it shows the shared one); None for one never kept."""
    data = _read()
    return data.get('keyboard_sync') is True, _state(data, 'lighting'), _state(data, 'keyboard_own')


def save(parts: dict, keyboard_sync: bool | None = None, lighting: st.State | None = None,
         keyboard_own: st.State | None = None) -> None:
    """Keeps the parts' settings, and the keyboard's RGB Sync, the shared lighting and the
    keyboard's own lighting if given (else as they were kept)."""
    data = _read()
    data.update({name: asdict(part) for name, part in parts.items()})
    if keyboard_sync is not None:
        data['keyboard_sync'] = keyboard_sync
    if lighting is not None:
        data['lighting'] = lighting.pack().hex()
    if keyboard_own is not None:
        data['keyboard_own'] = keyboard_own.pack().hex()
    try:
        path = _file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1), encoding='utf-8')
    except OSError:
        pass


__all__ = ['Part', 'follow', 'resolved', 'with_lighting', 'ram_request', 'board_effect', 'load', 'load_sync',
           'save', 'replace']
