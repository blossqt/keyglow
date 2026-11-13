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

## The PC's lights

The PC tab sets the memory's and the motherboard's lights too. Each part either takes the keyboard's
lighting (Same as the keyboard: the keys' effect and colours, or the base light's while the keys are
off, in the nearest effect the part has) or has its own effect. The parts keep the lighting
themselves, as the keyboard does.

- **Memory:** Corsair Vengeance RGB and Dominator sticks (DDR4 and DDR5). A stick's lights hang off
  the PC's SMBus, which only a driver reaches, so Keyglow carries a small service of its own,
  Keyglow Lights (`lights/`, C#), installed from the PC tab with Windows' permission. It reaches
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
