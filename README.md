# Keyglow

Sets the lighting of a Drop (Massdrop) ALT v1 keyboard live: an effect for the keys or a colour
for each key, and its own effect for the light round the base. The keyboard keeps the lighting
itself, so Keyglow only needs to be open while you change it.

Part of the blossqt suite: [Hanami](https://github.com/blossqt/hanami) installs and updates it.

## How it works

Drop's own firmware has no way for a program to change the lights, so Keyglow puts its own
firmware on the keyboard once (Settings → Set up, then Fn+B or the reset button underneath). The
firmware the keyboard had is read off it first and kept in `%APPDATA%\Keyglow`, and Keyglow can
write it back.

- `firmware/keyglow/` is a QMK keymap for `massdrop/alt`: Drop's default layout, one RGB matrix
  effect that draws the keys and the edge, and a raw HID channel the app talks over. The lighting
  lives in the chip's SmartEEPROM.
- QMK dropped the ALT v1 after 0.26.x, so the firmware is built against QMK 0.26.11.
- Flashing uses Drop's [mdloader](https://github.com/Massdrop/mdloader), built from source.

On the keyboard: Fn+W and Fn+S change the brightness, and Fn+Z goes through all lights, keys only,
base only and off.

## Devices and RGB Sync

The Devices tab lists every lit device: the keyboard, the memory and the motherboard. RGB Sync is
one lighting shared by every device that has it on, as peers. A theme sets it; while the keyboard
is in it, the Keys and Base light tabs set it too. Each device shows it in its nearest effect. A
device with RGB Sync off keeps a lighting of its own: the keyboard's from its own tabs, the memory's
and motherboard's from the Devices tab. Every device keeps its lighting itself.

- **Memory:** Corsair Vengeance RGB and Dominator sticks (DDR4 and DDR5). A stick's lights hang off
  the PC's SMBus, which only a driver reaches, so Keyglow carries a small service of its own,
  Keyglow Lights (`lights/`, C#), installed from the Devices tab with Windows' permission. It reaches
  the SMBus through [PawnIO](https://pawnio.eu) (which FanControl installs too), runs as the system
  only while the lighting changes, and stops itself after a minute. Keyglow talks to it through two
  blocks of shared memory, not a port or a pipe. iCUE sets the memory's lights itself, so quit it.
- **Motherboard:** ASRock's Polychrome controller on USB, which runs the board's own lights and its
  RGB and addressable headers (fans, strips).

## Building

```
powershell -ExecutionPolicy Bypass -File build\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File build\build_app.ps1
```

Tests: `%LOCALAPPDATA%\KeyglowBuild\venv\Scripts\python.exe tests\test_keyglow.py`, and
`tests\test_pc.py` for the PC's lights (its service tests run the built `lights\` service as the
user, with stand-in sticks). The build needs the .NET 10 SDK for `lights\`.
