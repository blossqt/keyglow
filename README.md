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

## Building

```
powershell -ExecutionPolicy Bypass -File build\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File build\build_app.ps1
```

Tests: `%LOCALAPPDATA%\KeyglowBuild\venv\Scripts\python.exe tests\test_keyglow.py`
