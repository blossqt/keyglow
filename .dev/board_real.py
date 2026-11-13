"""On the real ASRock board (changes its lights: check nothing full screen is in front): each zone
shown pink for 2 s, not committed, then put back as it was."""
import sys, time
sys.path.insert(0, r'C:\Users\haoch\Documents\Keyglow\app')
from keyglow import polychrome as poly
board = poly.find()
before = {z.number: board.read(z) for z in board.zones}
print('zones', [(z.number, z.name, z.leds, z.swapped) for z in board.zones])
print('before', before)
t = time.perf_counter(); board.set(poly.STATIC, (255, 105, 160), 0xE0); took = (time.perf_counter() - t) * 1000
print(f'set in {took:.0f} ms ->', {z.number: board.read(z) for z in board.zones})
time.sleep(2)
for z in board.zones:
    mode, rgb, speed = before[z.number]
    board.link.transact(board._packet(z, mode, rgb, speed))
print('after', {z.number: board.read(z) for z in board.zones})
board.close()
