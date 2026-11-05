// SPDX-License-Identifier: GPL-2.0-or-later (as QMK, which this keymap is built into)
// Keyglow's one effect: the keys and the edge, each drawn from its own zone of kg_state.
RGB_MATRIX_EFFECT(keyglow)

#ifdef RGB_MATRIX_CUSTOM_EFFECT_IMPLS

#include "action_layer.h"
#include "host.h"
#include "keyglow.h"

// A zone's clock: 0-255 going round, about 64 s a turn at speed 0 and 1 s at 255.
static uint8_t kg_tick(uint8_t speed) {
    return (uint8_t)scale16by8((uint16_t)g_rgb_timer, qadd8(speed / 4, 1));
}

static uint8_t kg_mix(uint8_t from, uint8_t to, uint8_t w) {
    return (uint8_t)(from + (((int16_t)to - (int16_t)from) * w) / 255);
}

static void kg_lerp(const uint8_t *a, const uint8_t *b, uint8_t w, uint8_t *out) {
    for (uint8_t c = 0; c < 3; c++) out[c] = kg_mix(a[c], b[c], w);
}

static void kg_hue(uint8_t hue, uint8_t *out) {
    HSV hsv = {hue, 255, 255};
    RGB rgb = hsv_to_rgb(hsv);
    out[0]  = rgb.r;
    out[1]  = rgb.g;
    out[2]  = rgb.b;
}

static void kg_copy(const uint8_t *from, uint8_t *out) {
    out[0] = from[0];
    out[1] = from[1];
    out[2] = from[2];
}

static uint8_t kg_breath(uint8_t tick) {
    return (uint8_t)(abs8(sin8(tick) - 128) * 2);
}

// How long a pressed key keeps glowing: 2 s at speed 0, about 0.2 s at 255.
static uint16_t kg_fade_ms(uint8_t speed) {
    return 2000 - (uint16_t)speed * 7;
}

static void kg_key(uint8_t i, uint8_t *out) {
    const kg_zone_t *z = &kg_state.keys;
    uint8_t          x = g_led_config.point[i].x;
    switch (z->mode) {
        case KG_KEY_SOLID:
            kg_copy(z->a, out);
            break;
        case KG_KEY_CUSTOM:
            kg_copy(kg_state.perkey[i], out);
            break;
        case KG_KEY_BREATHING: {
            uint8_t black[3] = {0, 0, 0};
            kg_lerp(black, z->a, kg_breath(kg_tick(z->speed)), out);
            break;
        }
        case KG_KEY_RAINBOW:
            kg_hue(x - kg_tick(z->speed), out);
            break;
        case KG_KEY_CYCLE:
            kg_hue(kg_tick(z->speed), out);
            break;
        case KG_KEY_GRADIENT:
            kg_lerp(z->a, z->b, (uint8_t)((uint16_t)x * 255 / 224), out);
            break;
        case KG_KEY_REACTIVE: {
            uint8_t w = 0;
            if (kg_hits[i]) {
                uint16_t gone = timer_elapsed(kg_hits[i]);
                uint16_t fade = kg_fade_ms(z->speed);
                if (gone < fade) {
                    w = 255 - (uint8_t)((uint32_t)gone * 255 / fade);
                } else {
                    kg_hits[i] = 0;
                }
            }
            kg_lerp(z->b, z->a, w, out);
            break;
        }
        default:
            out[0] = out[1] = out[2] = 0;
            return;
    }
}

static void kg_edge(uint8_t i, uint8_t *out) {
    const kg_zone_t *z = &kg_state.edge;
    uint8_t          j = i - KG_FIRST_EDGE;  // place round the ring, 0 at the corner by Ctrl
    switch (z->mode) {
        case KG_EDGE_SOLID:
            kg_copy(z->a, out);
            break;
        case KG_EDGE_BREATHING: {
            uint8_t black[3] = {0, 0, 0};
            kg_lerp(black, z->a, kg_breath(kg_tick(z->speed)), out);
            break;
        }
        case KG_EDGE_RAINBOW:
            kg_hue((uint8_t)((uint16_t)j * 256 / KG_EDGE) - kg_tick(z->speed), out);
            break;
        case KG_EDGE_CYCLE:
            kg_hue(kg_tick(z->speed), out);
            break;
        case KG_EDGE_GRADIENT:
            kg_lerp(z->a, z->b, (uint8_t)((uint16_t)g_led_config.point[i].x * 255 / 224), out);
            break;
        case KG_EDGE_CHASE: {
            uint8_t head = (uint8_t)(((uint16_t)kg_tick(z->speed) * KG_EDGE) >> 8);
            uint8_t back = (uint8_t)((head + KG_EDGE - j) % KG_EDGE);  // how far behind the head
            uint8_t w    = back < 8 ? 255 - back * 32 : 0;
            kg_lerp(z->b, z->a, w, out);
            break;
        }
        default:
            out[0] = out[1] = out[2] = 0;
            return;
    }
}

static bool keyglow(effect_params_t *params) {
    RGB_MATRIX_USE_LIMITS(led_min, led_max);
    bool idle = kg_state.idle && timer_elapsed32(kg_awake_at) > (uint32_t)kg_state.idle * 60000;
    bool fn   = (kg_state.extras & KG_X_FN) && layer_state_is(1);
    bool caps = (kg_state.extras & KG_X_CAPS) && host_keyboard_led_state().caps_lock;
    for (uint8_t i = led_min; i < led_max; i++) {
        uint8_t rgb[3] = {0, 0, 0};
        uint8_t bright = 0;
        if (idle || kg_state.dark) {
            // every light off: until the next key (idle), or until Fn+X again (dark)
        } else if (i < KG_FIRST_EDGE && fn) {
            // the Fn layer: its keys in its colour, the rest dark, whatever the keys' lighting
            if (kg_fn_keys[i]) {
                kg_copy(kg_state.fn, rgb);
                bright = 255;
            }
        } else if (caps && (i == kg_caps_leds[0] || i == kg_caps_leds[1] || i == kg_caps_leds[2])) {
            kg_copy(kg_state.caps, rgb);
            bright = 255;
        } else if (i < KG_FIRST_EDGE) {
            if (kg_state.on & KG_ON_KEYS) {
                kg_key(i, rgb);
                bright = kg_state.keys.bright;
            }
        } else if (kg_state.on & KG_ON_EDGE) {
            kg_edge(i, rgb);
            bright = kg_state.edge.bright;
        }
        bright = scale8(bright, kg_state.master);
        rgb_matrix_set_color(i, scale8(rgb[0], bright), scale8(rgb[1], bright), scale8(rgb[2], bright));
    }
    return rgb_matrix_check_finished_leds(led_max);
}

#endif // RGB_MATRIX_CUSTOM_EFFECT_IMPLS
