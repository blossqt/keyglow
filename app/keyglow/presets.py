"""Ready-made lighting: a theme sets both parts' effects and colours in one go. The overall
brightness stays as the user set it, and so do their own per-key colours, unless the theme
paints keys itself."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

from . import state as st

PINK, ROSE = (255, 209, 220), (194, 37, 92)


@dataclass(frozen=True)
class Theme:
    name: str
    on: int
    keys: st.Zone
    edge: st.Zone
    perkey: tuple | None = None     # the theme's own per-key colours, for a "per key" theme
    own: bool = False               # saved by the user (it can be renamed and deleted)

    def apply(self, state: st.State) -> st.State:
        """The state with this theme: master brightness (and per-key colours it doesn't set) kept."""
        new = state.copy()
        new.on = self.on
        new.dark = 0                # a theme chosen is a theme to see
        new.keys = st.Zone(**vars(self.keys))
        new.edge = st.Zone(**vars(self.edge))
        if self.perkey is not None:
            new.perkey = list(self.perkey)
        return new

    def shown_by(self, state: st.State) -> bool:
        """Whether the keyboard is lit as this theme lights it (brightness aside)."""
        mine = self.apply(state)
        mine.master = state.master
        return mine.pack() == state.pack()


def _zone(mode: int, a=PINK, b=ROSE, speed: int = 96, bright: int = 255) -> st.Zone:
    return st.Zone(mode=mode, speed=speed, bright=bright, a=tuple(a), b=tuple(b))


def _painted(base, picks: dict) -> tuple:
    """Per-key colours: every key `base`, and the keys labelled in `picks` their own colour."""
    out = []
    for x, y, w, label in st.LAYOUT:
        colour = base
        for labels, picked in picks.items():
            if label in labels:
                colour = picked
        out.append(tuple(colour))
    return tuple(out)


def _two_tone(letters, others) -> tuple:
    """Letters, numbers and punctuation one colour; the keys round them another."""
    return tuple(tuple(letters if len(label) == 1 and label not in '←↑→↓' else others)
                 for x, y, w, label in st.LAYOUT)


BOTH = st.ON_KEYS | st.ON_EDGE
RED = (255, 30, 60)

THEMES = (
    Theme('Blossom', BOTH, _zone(st.KEY_SOLID), _zone(st.EDGE_SOLID, ROSE)),
    Theme('Sakura', BOTH, _zone(st.KEY_GRADIENT, PINK, ROSE),
          _zone(st.EDGE_BREATHING, (255, 110, 165), speed=60)),
    Theme('Rainbow', BOTH, _zone(st.KEY_RAINBOW), _zone(st.EDGE_RAINBOW)),
    Theme('Colour cycle', BOTH, _zone(st.KEY_CYCLE, speed=40), _zone(st.EDGE_CYCLE, speed=40)),
    Theme('Ocean', BOTH, _zone(st.KEY_GRADIENT, (0, 213, 255), (42, 90, 255)),
          _zone(st.EDGE_CHASE, (0, 255, 230), (0, 24, 90), speed=120)),
    Theme('Sunset', BOTH, _zone(st.KEY_GRADIENT, (255, 122, 0), (255, 50, 160)),
          _zone(st.EDGE_GRADIENT, (255, 200, 0), ROSE)),
    Theme('Forest', BOTH, _zone(st.KEY_GRADIENT, (150, 255, 90), (0, 140, 70)),
          _zone(st.EDGE_BREATHING, (61, 220, 90), speed=50)),
    Theme('Lavender', BOTH, _zone(st.KEY_SOLID, (190, 160, 255)),
          _zone(st.EDGE_GRADIENT, (139, 61, 255), (255, 61, 216))),
    Theme('Ember', BOTH, _zone(st.KEY_BREATHING, (255, 70, 0), speed=70),
          _zone(st.EDGE_CHASE, (255, 180, 0), (90, 0, 0), speed=100)),
    Theme('Ice', BOTH, _zone(st.KEY_SOLID, (215, 238, 255)), _zone(st.EDGE_SOLID, (0, 160, 255))),
    Theme('Two tone', BOTH, _zone(st.KEY_CUSTOM), _zone(st.EDGE_SOLID, ROSE),
          _two_tone(PINK, ROSE)),
    Theme('Gaming', BOTH, _zone(st.KEY_CUSTOM), _zone(st.EDGE_SOLID, RED),
          _painted((70, 40, 160), {('W', 'A', 'S', 'D', '↑', '←', '↓', '→', 'Esc'): RED})),
    Theme('Typing', BOTH, _zone(st.KEY_REACTIVE, PINK, (40, 8, 20), speed=128),
          _zone(st.EDGE_SOLID, ROSE, bright=150)),
    Theme('Base light only', st.ON_EDGE, _zone(st.KEY_SOLID), _zone(st.EDGE_RAINBOW, speed=60)),
)


# --- the user's own themes -----------------------------------------------------------------
# Kept in Keyglow's data folder as themes.json: a name and the lighting (the state's first,
# version 1 part, as the keyboard keeps it) for each, in the order they were saved.

def _file():
    from . import flasher
    return flasher.data_folder() / 'themes.json'


def own(name: str, state: st.State) -> Theme:
    return Theme(name, state.on, st.Zone(**vars(state.keys)), st.Zone(**vars(state.edge)),
                 tuple(tuple(c) for c in state.perkey), own=True)


def saved() -> list:
    """The user's themes, oldest first; none if the file is missing or unreadable."""
    try:
        rows = json.loads(_file().read_text(encoding='utf-8'))
        return [own(row['name'], st.State.unpack(bytes.fromhex(row['lighting']))) for row in rows]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _write(themes: list) -> None:
    rows = [{'name': t.name, 'lighting': t.apply(st.State()).pack()[:st.OLD_SIZE].hex()} for t in themes]
    path = _file()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(rows, indent=1), encoding='utf-8')
    os.replace(temp, path)


def save(name: str, state: st.State) -> None:
    """Saves the lighting as a theme, replacing one of the same name where it was."""
    themes = saved()
    theme = own(name, state)
    for n, old in enumerate(themes):
        if old.name == name:
            themes[n] = theme
            break
    else:
        themes.append(theme)
    _write(themes)


def rename(name: str, new: str) -> None:
    _write([replace(t, name=new) if t.name == name else t for t in saved() if t.name != new or name == new])


def delete(name: str) -> None:
    _write([t for t in saved() if t.name != name])
