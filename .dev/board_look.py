"""Read-only: the ASRock Polychrome USB controller's zone table and each zone's current effect."""
import sys
sys.path.insert(0, r'C:\Users\haoch\Documents\Keyglow\app')
from keyglow import hid

NAMES = ['RGB 1', 'RGB 2', 'ARGB 1', 'ARGB 2', 'PCH', 'IO cover', 'PCB', 'ARGB 3/audio']
dev = hid.Device(hid.interfaces(0x26CE, 0x01A2)[0])

def ask(*b):
    packet = bytes(b)
    dev.write(packet)             # Device.write puts report id 0 in front, pads to 65
    return dev.read()

counts = ask(0x14, 0x00, 0x02)
swap = ask(0x14, 0x00, 0x03)
head = ask(0x14, 0x00, 0x01)
print('counts', counts[:16].hex(' '))
print('rgswap', swap[:8].hex(' '))
print('header1', head[:8].hex(' '))
table = counts[4:12]; mask = head[4]
for z in range(8):
    present = table[z] != 0x1E and (mask >> z) & 1
    if not present:
        continue
    a = ask(0x11, 0x00, z)
    print(f'{NAMES[z]:14} leds {table[z]:3}  mode {a[4]:2}  colour {a[5:8].hex()}  speed {a[8]:3}  raw {a[:12].hex(" ")}')
dev.close()
