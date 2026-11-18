"""Writes two harmless changes and puts each back: Ripple Control, and stage 1's indicator colour."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from keyglow import lamzu  # noqa: E402

mouse = lamzu.open_first()
before = mouse.read()
print('before', before)
try:
    rippled = before.with_(switches={**before.switches, 'ripple': not before.switches['ripple']})
    t = time.perf_counter()
    mouse.apply(before, rippled)
    print('ripple write', f'{(time.perf_counter() - t) * 1000:.0f} ms')
    print('ripple now', mouse.read().switches['ripple'])
    stages = list(before.stages)
    stages[0] = lamzu.Stage(stages[0].dpi, (255, 209, 220))
    coloured = before.with_(stages=tuple(stages))
    t = time.perf_counter()
    mouse.apply(before, coloured)
    print('colour write', f'{(time.perf_counter() - t) * 1000:.0f} ms')
    print('colour now', mouse.read().stages[0])
finally:
    now = mouse.read()
    mouse.apply(now, now.with_(stages=before.stages, switches=before.switches))
    after = mouse.read()
    print('after ', after)
    print('restored', after == before)
    mouse.close()
