"""The ALT running Keyglow's firmware, over its raw HID channel (firmware/keyglow/keymap.c).

Every packet is 32 bytes both ways; byte 0 is the command, echoed back in the answer."""

from __future__ import annotations

from . import state as st

VID, PID = 0x04D8, 0xEED3           # Drop (Massdrop) ALT v1
RAW_PAGE, RAW_USAGE = 0xFF60, 0x61  # QMK's raw HID interface
PACKET = 32
CHUNK = 28

HELLO, READ, WRITE, SAVE, RELOAD, BOOTLOADER, DEFAULTS = range(1, 8)

ABSENT = 'absent'       # no ALT plugged in
STOCK = 'stock'         # an ALT, but without Keyglow's firmware (no raw HID channel)
READY = 'ready'         # an ALT running Keyglow's firmware


class DeviceError(OSError):
    pass


class Keyboard:
    """The protocol, over anything that can send a packet and give back the answer (a HID
    device, or FakeAlt in tests)."""

    def __init__(self, link):
        self.link = link
        self.protocol = 0
        self.state_version = 0
        self.firmware = 0               # KG_FIRMWARE: 0 from Keyglow's first, which didn't say
        self.size = st.STATE_SIZE       # how much of the state this firmware keeps

    def close(self) -> None:
        close = getattr(self.link, 'close', None)
        if close:
            close()

    def _ask(self, *data: int, payload: bytes = b'') -> bytes:
        packet = (bytes(data) + payload).ljust(PACKET, b'\0')
        answer = self.link.transact(packet)
        if not answer or answer[0] != data[0]:
            raise DeviceError(f'the keyboard answered command {data[0]} with {answer[:1].hex() or "nothing"}')
        return answer

    def hello(self) -> None:
        answer = self._ask(HELLO)
        if answer[1:3] != b'KG':
            raise DeviceError('this keyboard is not running Keyglow firmware')
        self.protocol = answer[3]
        keys, edge = answer[4], answer[5]
        size = answer[6] | answer[7] << 8
        self.state_version = answer[8]
        self.firmware = answer[9]
        known = {(st.STATE_SIZE, st.STATE_VERSION), (st.OLD_SIZE, 1)}
        if (keys, edge) != (st.KEYS, st.EDGE) or (size, self.state_version) not in known:
            raise DeviceError('the keyboard runs a different version of Keyglow firmware')
        self.size = size

    @property
    def outdated(self) -> bool:
        """Whether the firmware Keyglow carries is newer than the keyboard's."""
        return self.firmware < st.FIRMWARE

    def read_state(self) -> st.State:
        data = bytearray()
        for off in range(0, self.size, CHUNK):
            n = min(CHUNK, self.size - off)
            answer = self._ask(READ, off, n)
            if answer[1] != off or answer[2] != n:
                raise DeviceError('the keyboard sent back the wrong part of its lighting')
            data += answer[3:3 + n]
        return st.State.unpack(bytes(data))

    def write(self, off: int, data: bytes) -> None:
        """Bytes of the lighting state, from off: shown at once, not yet saved."""
        for start in range(0, len(data), CHUNK):
            part = data[start:start + CHUNK]
            if not self._ask(WRITE, off + start, len(part), payload=part)[1]:
                raise DeviceError('the keyboard refused a change')

    def write_changes(self, before: bytes, after: bytes) -> int:
        """Sends only the runs of bytes that differ; returns how many packets went. Only what the
        keyboard's firmware keeps goes."""
        before, after = before[:self.size], after[:self.size]
        if len(before) != len(after):
            self.write(0, after)
            return -(-len(after) // CHUNK)
        runs: list[list[int]] = []
        for i in range(len(after)):
            if before[i] == after[i]:
                continue
            # a run takes in short stretches that are the same, up to what one packet holds
            if runs and i - runs[-1][1] <= 4 and i - runs[-1][0] < CHUNK:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        for start, end in runs:
            self.write(start, after[start:end + 1])
        return len(runs)

    def save(self) -> None:
        self._ask(SAVE)

    def reload(self) -> None:
        self._ask(RELOAD)

    def defaults(self) -> None:
        self._ask(DEFAULTS)

    def bootloader(self) -> None:
        """Restarts the keyboard into its bootloader, ready for new firmware."""
        self._ask(BOOTLOADER)


class _HidLink:
    def __init__(self, device):
        self.device = device

    def transact(self, packet: bytes) -> bytes:
        self.device.write(packet)
        return self.device.read()

    def close(self) -> None:
        self.device.close()


def look() -> tuple[str, object]:
    """What is plugged in: (ABSENT, None), (STOCK, None) or (READY, the raw HID interface)."""
    from . import hid
    found = hid.interfaces(VID, PID)
    if not found:
        return ABSENT, None
    for interface in found:
        if interface.usage_page == RAW_PAGE and interface.usage == RAW_USAGE:
            return READY, interface
    return STOCK, None


def open_keyboard(interface) -> Keyboard:
    from . import hid
    keyboard = Keyboard(_HidLink(hid.Device(interface)))
    try:
        keyboard.hello()
    except Exception:
        keyboard.close()
        raise
    return keyboard


class FakeAlt:
    """Keyglow's firmware, in Python: tests talk to it as they would to the keyboard."""

    def __init__(self, saved: st.State | None = None, old: bool = False):
        self.size = st.OLD_SIZE if old else st.STATE_SIZE      # old: Keyglow's first firmware
        self.firmware = 0 if old else st.FIRMWARE
        self.saved = (saved or st.State()).pack()[:self.size]
        self.live = bytearray(self.saved)
        self.packets = 0
        self.saves = 0
        self.booted = False
        self.closed = False

    def transact(self, packet: bytes) -> bytes:
        assert len(packet) == PACKET
        self.packets += 1
        out = bytearray(PACKET)
        out[0] = packet[0]
        cmd = packet[0]
        if cmd == HELLO:
            out[1:10] = b'KG' + bytes((st.PROTOCOL, st.KEYS, st.EDGE, self.size & 0xFF, self.size >> 8,
                                       1 if self.size == st.OLD_SIZE else st.STATE_VERSION, self.firmware))
        elif cmd == READ:
            off, n = packet[1], packet[2]
            if n > CHUNK or off + n > self.size:
                n = 0
            out[1], out[2] = off, n
            out[3:3 + n] = self.live[off:off + n]
        elif cmd == WRITE:
            off, n = packet[1], packet[2]
            if n <= CHUNK and off + n <= self.size:
                self.live[off:off + n] = packet[3:3 + n]
                self.live[0] = 1 if self.size == st.OLD_SIZE else st.STATE_VERSION
                out[1] = 1
        elif cmd == SAVE:
            self.saved = bytes(self.live)
            self.saves += 1
            out[1] = 1
        elif cmd == RELOAD:
            self.live = bytearray(self.saved)
            out[1] = 1
        elif cmd == BOOTLOADER:
            self.booted = True
            out[1] = 1
        elif cmd == DEFAULTS:
            self.live = bytearray(st.State().pack()[:self.size])
            out[1] = 1
        else:
            out[0] = 0xFF
        return bytes(out)

    def close(self) -> None:
        self.closed = True

    @property
    def state(self) -> st.State:
        return st.State.unpack(bytes(self.live))
