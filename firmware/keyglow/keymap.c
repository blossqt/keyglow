// SPDX-License-Identifier: GPL-2.0-or-later (as QMK, which this keymap is built into)
// Keyglow firmware for the Drop ALT (v1): Drop's default layout, with lighting the Keyglow app
// sets live over raw HID and the keyboard keeps in its SmartEEPROM.
#include QMK_KEYBOARD_H
#include "raw_hid.h"
#include "eeconfig.h"
#include "eeprom.h"
#include "keyglow.h"

enum alt_keycodes {
    U_T_AUTO = SAFE_RANGE, // USB Extra Port Toggle Auto Detect / Always Active
    U_T_AGCR,              // USB Toggle Automatic GCR control
    DBG_TOG,               // DEBUG Toggle On / Off
    DBG_MTRX,              // DEBUG Toggle Matrix Prints
    DBG_KBD,               // DEBUG Toggle Keyboard Prints
    DBG_MOU,               // DEBUG Toggle Mouse Prints
    MD_BOOT,               // Restart into bootloader after hold timeout
    KG_UP,                 // Brighter
    KG_DOWN,               // Dimmer
    KG_PARTS,              // All lit, keys only, edge only, off
    KG_DARK,               // Every light off, or back on
};

// clang-format off
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
    [0] = LAYOUT_65_ansi_blocker(
        KC_ESC,  KC_1,    KC_2,    KC_3,    KC_4,    KC_5,    KC_6,    KC_7,    KC_8,    KC_9,    KC_0,    KC_MINS, KC_EQL,  KC_BSPC, KC_DEL,
        KC_TAB,  KC_Q,    KC_W,    KC_E,    KC_R,    KC_T,    KC_Y,    KC_U,    KC_I,    KC_O,    KC_P,    KC_LBRC, KC_RBRC, KC_BSLS, KC_HOME,
        KC_CAPS, KC_A,    KC_S,    KC_D,    KC_F,    KC_G,    KC_H,    KC_J,    KC_K,    KC_L,    KC_SCLN, KC_QUOT,          KC_ENT,  KC_PGUP,
        KC_LSFT, KC_Z,    KC_X,    KC_C,    KC_V,    KC_B,    KC_N,    KC_M,    KC_COMM, KC_DOT,  KC_SLSH, KC_RSFT,          KC_UP,   KC_PGDN,
        KC_LCTL, KC_LGUI, KC_LALT,                            KC_SPC,                             KC_RALT, MO(1),   KC_LEFT, KC_DOWN, KC_RGHT
    ),
    [1] = LAYOUT_65_ansi_blocker(
        KC_GRV,  KC_F1,   KC_F2,   KC_F3,   KC_F4,   KC_F5,   KC_F6,   KC_F7,   KC_F8,   KC_F9,   KC_F10,  KC_F11,  KC_F12,  _______, KC_MUTE,
        _______, _______, KG_UP,   _______, _______, _______, _______, U_T_AUTO,U_T_AGCR,_______, KC_PSCR, KC_SCRL, KC_PAUS, _______, KC_END,
        _______, _______, KG_DOWN, _______, _______, _______, _______, _______, _______, _______, _______, _______,          _______, KC_VOLU,
        _______, KG_PARTS,KG_DARK, _______, _______, MD_BOOT, NK_TOGG, DBG_TOG, _______, _______, _______, _______,          KC_PGUP, KC_VOLD,
        _______, _______, _______,                            _______,                            _______, _______, KC_HOME, KC_PGDN, KC_END
    ),
};
// clang-format on

kg_state_t kg_state;
uint16_t   kg_hits[KG_KEYS];
uint32_t   kg_awake_at;
bool       kg_fn_keys[KG_KEYS];
uint8_t    kg_caps_leds[3] = {0xFF, 0xFF, 0xFF};

static bool     kg_dirty;        // changed on the keyboard itself (Fn keys): saved a moment later
static uint16_t kg_dirty_at;
static bool     kg_boot_soon;    // the app asked for the bootloader: go once the answer is out
static uint16_t kg_boot_at;

#define KG_SAVE_AFTER 1500       // ms after the last Fn change

// What version 2 added: Caps Lock white, the Fn layer pink, lights off after 10 minutes.
static void kg_extra_defaults(kg_state_t *s) {
    s->extras  = KG_X_CAPS | KG_X_FN;
    s->caps[0] = s->caps[1] = s->caps[2] = 255;
    s->fn[0] = 255, s->fn[1] = 209, s->fn[2] = 220;
    s->idle = 10;
    s->dark = 0;
    memset(s->spare, 0, sizeof(s->spare));
}

static void kg_defaults(kg_state_t *s) {
    memset(s, 0, sizeof(*s));
    s->version     = KG_STATE_VERSION;
    s->on          = KG_ON_KEYS | KG_ON_EDGE;
    s->master      = 255;
    s->keys.mode   = KG_KEY_RAINBOW;
    s->keys.speed  = 96;
    s->keys.bright = 255;
    s->keys.a[0] = 255, s->keys.a[1] = 209, s->keys.a[2] = 220;  // the suite's blossom pink
    s->keys.b[0] = 194, s->keys.b[1] = 37, s->keys.b[2] = 92;
    s->edge        = s->keys;
    s->edge.mode   = KG_EDGE_RAINBOW;
    for (uint8_t i = 0; i < KG_KEYS; i++) {
        s->perkey[i][0] = s->perkey[i][1] = s->perkey[i][2] = 255;
    }
    kg_extra_defaults(s);
}

// Keeps whatever arrives within what the effect can draw.
static void kg_tidy(kg_state_t *s) {
    s->version = KG_STATE_VERSION;
    s->on &= KG_ON_KEYS | KG_ON_EDGE;
    s->extras &= KG_X_CAPS | KG_X_FN;
    s->dark = s->dark ? 1 : 0;
    if (s->keys.mode >= KG_KEY_MODES) s->keys.mode = KG_KEY_OFF;
    if (s->edge.mode >= KG_EDGE_MODES) s->edge.mode = KG_EDGE_OFF;
}

static void kg_save(void) {
    eeconfig_update_user_datablock(&kg_state);
    kg_dirty = false;
}

static void kg_load(void) {
    if (eeconfig_is_user_datablock_valid()) {
        eeconfig_read_user_datablock(&kg_state);
        if (kg_state.version != KG_STATE_VERSION) kg_defaults(&kg_state);
    } else if (eeprom_read_dword(EECONFIG_USER) == KG_STATE_SIZE_1) {
        // left by Keyglow's first firmware (QMK marks a datablock with its size): its lighting
        // is the start of this one, so it is kept, and what came since starts as its defaults
        kg_defaults(&kg_state);
        eeprom_read_block(&kg_state, EECONFIG_USER_DATABLOCK, KG_STATE_SIZE_1);
        kg_state.version = KG_STATE_VERSION;
        kg_tidy(&kg_state);
        kg_save();
    } else {
        kg_defaults(&kg_state);
    }
    kg_tidy(&kg_state);
}

// Which keys light while Fn is held - those that do something on layer 1, and Fn itself - and
// where Caps Lock is, from the keymap, so the lights follow it if it changes.
static void kg_find_keys(void) {
    for (uint8_t row = 0; row < MATRIX_ROWS; row++) {
        for (uint8_t col = 0; col < MATRIX_COLS; col++) {
            uint8_t led = g_led_config.matrix_co[row][col];
            if (led >= KG_KEYS) continue;
            keypos_t at   = {.row = row, .col = col};
            uint16_t base = keymap_key_to_keycode(0, at);
            uint16_t fn   = keymap_key_to_keycode(1, at);
            kg_fn_keys[led] = (fn != KC_TRNS && fn != KC_NO) || base == MO(1);
            if (base == KC_CAPS) kg_caps_leds[0] = led;
            if (base == KC_A) kg_caps_leds[1] = led;
            if (base == KC_LSFT) kg_caps_leds[2] = led;
        }
    }
}

static void kg_wake(void) {
    kg_awake_at = timer_read32();
}

void eeconfig_init_user_datablock(void) {
    kg_state_t fresh;
    kg_defaults(&fresh);
    eeconfig_update_user_datablock(&fresh);
}

void keyboard_post_init_user(void) {
    kg_load();
    kg_find_keys();
    kg_wake();
    rgb_matrix_enable_noeeprom();
    rgb_matrix_mode_noeeprom(RGB_MATRIX_CUSTOM_keyglow);
}

// Drop's own lock-key indicator (md_rgb_matrix_indicators_advanced, called after this unless it
// returns false) turns the Caps Lock key's colour inside out while Caps Lock is on: red came out
// cyan. Keyglow lights Caps Lock itself, in the colour chosen, so Drop's is skipped.
bool rgb_matrix_indicators_advanced_user(uint8_t led_min, uint8_t led_max) {
    return false;
}

static void kg_changed(void) {
    kg_dirty    = true;
    kg_dirty_at = timer_read();
}

void housekeeping_task_user(void) {
    if (kg_dirty && timer_elapsed(kg_dirty_at) > KG_SAVE_AFTER) {
        kg_save();
    }
    if (kg_boot_soon && timer_elapsed(kg_boot_at) > 100) {
        reset_keyboard();
    }
}

// --- the app's channel -------------------------------------------------------------------
//
// Every packet is KG_PACKET (32) bytes, both ways; byte 0 is the command, echoed back.
//   0x01 hello      -> 'K' 'G' protocol keys edge size_lo size_hi version firmware
//   0x02 read  off n        -> off n data[n]          (n <= 28)
//   0x03 write off n data   -> 1 if taken, 0 if not   (applied at once, not saved)
//   0x04 save               -> 1
//   0x05 reload (from the keyboard's memory) -> 1
//   0x06 bootloader         -> 1, then the keyboard restarts into its bootloader
//   0x07 defaults (not saved) -> 1
//   anything else           -> 0xFF

enum { KG_HELLO = 1, KG_READ, KG_WRITE, KG_SAVE, KG_RELOAD, KG_BOOTLOADER, KG_DEFAULTS };

#define KG_CHUNK 28
#define KG_PACKET 32            // the ALT's raw HID reports, both ways

void raw_hid_receive(uint8_t *data, uint8_t length) {
    uint8_t out[KG_PACKET] = {0};
    out[0]                  = data[0];
    uint8_t *state          = (uint8_t *)&kg_state;
    switch (data[0]) {
        case KG_HELLO:
            out[1] = 'K';
            out[2] = 'G';
            out[3] = KG_PROTOCOL;
            out[4] = KG_KEYS;
            out[5] = KG_EDGE;
            out[6] = KG_STATE_SIZE & 0xFF;
            out[7] = KG_STATE_SIZE >> 8;
            out[8] = KG_STATE_VERSION;
            out[9] = KG_FIRMWARE;
            break;
        case KG_READ: {
            uint8_t off = data[1], n = data[2];
            if (n > KG_CHUNK || off + n > KG_STATE_SIZE) n = 0;
            out[1] = off;
            out[2] = n;
            memcpy(out + 3, state + off, n);
            break;
        }
        case KG_WRITE: {
            uint8_t off = data[1], n = data[2];
            if (n <= KG_CHUNK && off + n <= KG_STATE_SIZE) {
                memcpy(state + off, data + 3, n);
                kg_tidy(&kg_state);
                kg_wake();              // a change from the app shows, even after the lights went off
                out[1] = 1;
            }
            break;
        }
        case KG_SAVE:
            kg_save();
            out[1] = 1;
            break;
        case KG_RELOAD:
            kg_load();
            kg_wake();
            kg_dirty = false;
            out[1]   = 1;
            break;
        case KG_BOOTLOADER:
            kg_boot_soon = true;
            kg_boot_at   = timer_read();
            out[1]       = 1;
            break;
        case KG_DEFAULTS:
            kg_defaults(&kg_state);
            kg_wake();
            out[1] = 1;
            break;
        default:
            out[0] = 0xFF;
            break;
    }
    raw_hid_send(out, KG_PACKET);
}

// --- keys ---------------------------------------------------------------------------------

#define MODS_SHIFT (get_mods() & MOD_BIT(KC_LSFT) || get_mods() & MOD_BIT(KC_RSFT))
#define MODS_CTRL (get_mods() & MOD_BIT(KC_LCTL) || get_mods() & MOD_BIT(KC_RCTL))

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    static uint32_t key_timer;

    kg_wake();      // any key, pressed or let go, brings lights that went off when idle back

    if (record->event.pressed && record->event.key.row < MATRIX_ROWS && record->event.key.col < MATRIX_COLS) {
        uint8_t led = g_led_config.matrix_co[record->event.key.row][record->event.key.col];
        if (led < KG_KEYS) kg_hits[led] = timer_read() | 1;
    }

    switch (keycode) {
        case U_T_AUTO:
            if (record->event.pressed && MODS_SHIFT && MODS_CTRL) {
                TOGGLE_FLAG_AND_PRINT(usb_extra_manual, "USB extra port manual mode");
            }
            return false;
        case U_T_AGCR:
            if (record->event.pressed && MODS_SHIFT && MODS_CTRL) {
                TOGGLE_FLAG_AND_PRINT(usb_gcr_auto, "USB GCR auto mode");
            }
            return false;
        case DBG_TOG:
            if (record->event.pressed) {
                TOGGLE_FLAG_AND_PRINT(debug_enable, "Debug mode");
            }
            return false;
        case DBG_MTRX:
            if (record->event.pressed) {
                TOGGLE_FLAG_AND_PRINT(debug_matrix, "Debug matrix");
            }
            return false;
        case DBG_KBD:
            if (record->event.pressed) {
                TOGGLE_FLAG_AND_PRINT(debug_keyboard, "Debug keyboard");
            }
            return false;
        case DBG_MOU:
            if (record->event.pressed) {
                TOGGLE_FLAG_AND_PRINT(debug_mouse, "Debug mouse");
            }
            return false;
        case MD_BOOT:
            if (record->event.pressed) {
                key_timer = timer_read32();
            } else if (timer_elapsed32(key_timer) >= 500) {
                reset_keyboard();
            }
            return false;
        case KG_UP:
            if (record->event.pressed) {
                kg_state.master = kg_state.master > 239 ? 255 : kg_state.master + 16;
                kg_changed();
            }
            return false;
        case KG_DOWN:
            if (record->event.pressed) {
                kg_state.master = kg_state.master < 16 ? 0 : kg_state.master - 16;
                kg_changed();
            }
            return false;
        case KG_DARK:
            if (record->event.pressed) {
                kg_state.dark = !kg_state.dark;
                kg_changed();
            }
            return false;
        case KG_PARTS:
            if (record->event.pressed) {
                // all -> keys only -> edge only -> off -> all, as Drop's own Fn+Z did
                switch (kg_state.on) {
                    case KG_ON_KEYS | KG_ON_EDGE: kg_state.on = KG_ON_KEYS; break;
                    case KG_ON_KEYS:              kg_state.on = KG_ON_EDGE; break;
                    case KG_ON_EDGE:              kg_state.on = 0; break;
                    default:                      kg_state.on = KG_ON_KEYS | KG_ON_EDGE; break;
                }
                kg_changed();
            }
            return false;
        default:
            return true;
    }
}
