// SPDX-License-Identifier: GPL-2.0-or-later (as QMK, which this keymap is built into)
// Keyglow's lighting state for the Drop ALT (v1), shared by the keymap and its effect.
//
// The app reads and writes this block byte for byte over raw HID (see keymap.c), so its
// layout is the protocol: change it only together with app/keyglow/device.py, and raise
// KG_STATE_VERSION when you do.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define KG_STATE_VERSION 2
#define KG_PROTOCOL 1
#define KG_FIRMWARE 5           // this firmware's own number, which the app compares with its copy's
#define KG_STATE_SIZE_1 222     // version 1's state (Keyglow 0.1.0-0.1.1): kept as is when found

#define KG_KEYS 67              // LEDs 0-66 sit under the keys, in LAYOUT order
#define KG_EDGE 38              // LEDs 67-104 run round the edge: from the corner by Ctrl along the
                                // front, up the right side, back along the top, down the left
#define KG_FIRST_EDGE KG_KEYS

#define KG_ON_KEYS 0x01         // kg_state.on: which parts are lit
#define KG_ON_EDGE 0x02

#define KG_X_CAPS 0x01          // kg_state.extras: Caps Lock's key lit while Caps Lock is on
#define KG_X_FN 0x02            // the keys that do something with Fn lit while it is held

enum kg_key_mode {
    KG_KEY_OFF = 0,
    KG_KEY_SOLID,               // colour a
    KG_KEY_CUSTOM,              // each key its own colour (perkey)
    KG_KEY_BREATHING,           // colour a, fading in and out
    KG_KEY_RAINBOW,             // a rainbow moving across the board
    KG_KEY_CYCLE,               // every key the same colour, going round the colour wheel
    KG_KEY_GRADIENT,            // colour a on the left to colour b on the right
    KG_KEY_REACTIVE,            // colour b, and a pressed key flashes colour a
    KG_KEY_MODES
};

enum kg_edge_mode {
    KG_EDGE_OFF = 0,
    KG_EDGE_SOLID,              // colour a
    KG_EDGE_BREATHING,          // colour a, fading in and out
    KG_EDGE_RAINBOW,            // a rainbow flowing round the edge
    KG_EDGE_CYCLE,              // the whole edge going round the colour wheel
    KG_EDGE_GRADIENT,           // colour a on the left to colour b on the right
    KG_EDGE_CHASE,              // a streak of colour a running round over colour b
    KG_EDGE_MODES
};

typedef struct __attribute__((packed)) {
    uint8_t mode;
    uint8_t speed;              // 0 slowest, 255 fastest
    uint8_t bright;             // 0-255
    uint8_t a[3];               // r, g, b
    uint8_t b[3];
} kg_zone_t;

typedef struct __attribute__((packed)) {
    uint8_t   version;          // KG_STATE_VERSION
    uint8_t   on;               // KG_ON_KEYS | KG_ON_EDGE
    uint8_t   master;           // brightness over everything, 0-255 (Fn+W / Fn+S)
    kg_zone_t keys;
    kg_zone_t edge;
    uint8_t   perkey[KG_KEYS][3];
    // version 2
    uint8_t   extras;           // KG_X_CAPS | KG_X_FN
    uint8_t   caps[3];          // Caps Lock's colour
    uint8_t   fn[3];            // the Fn layer's colour
    uint8_t   idle;             // minutes without a key before the lights go off; 0 never
    uint8_t   dark;             // every light off (Fn+X), whatever the rest says (firmware 5)
    uint8_t   spare[19];        // for settings to come, without a new layout (zeros: off)
} kg_state_t;

#define KG_STATE_SIZE 250       // EECONFIG_USER_DATA_SIZE in config.h must be this too; the
                                // protocol's offsets are one byte, so it stays under 256

_Static_assert(sizeof(kg_state_t) == KG_STATE_SIZE, "kg_state_t changed size: update KG_STATE_SIZE");

extern kg_state_t kg_state;
extern uint16_t   kg_hits[KG_KEYS];  // when each key was last pressed (timer_read() | 1), 0 for long ago
extern uint32_t   kg_awake_at;       // the last key or change from the app (timer_read32())
extern bool       kg_fn_keys[KG_KEYS];  // the keys that do something on the Fn layer, and Fn itself
extern uint8_t    kg_caps_leds[3];   // lit for Caps Lock: its own LED, and those of the keys right of
                                     // it (A) and below it (Left Shift), whose light shows round its
                                     // keycap where its own, under an opaque cap, does not
