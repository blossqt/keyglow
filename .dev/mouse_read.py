"""Read-only: the LAMZU mouse's settings, battery and firmware. Writes nothing."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from keyglow import lamzu  # noqa: E402

found = lamzu.find()
print('found', [(f'{i.vid:04X}:{i.pid:04X}', m.name) for i, m in found])
mouse = lamzu.open_first()
if mouse is None:
    sys.exit('no mouse')
try:
    for what in ('profile', 'firmware', 'battery'):
        t = time.perf_counter()
        print(what, getattr(mouse, what)(), f'{(time.perf_counter() - t) * 1000:.0f} ms')
    t = time.perf_counter()
    print(mouse.read(), f'{(time.perf_counter() - t) * 1000:.0f} ms')
finally:
    mouse.close()
