// SPDX-License-Identifier: GPL-2.0-or-later (as QMK, which this keymap is built into)
#pragma once

// Keyglow's lighting state lives in the user datablock (kg_state_t, 222 bytes).
#define EECONFIG_USER_DATA_SIZE 222

// One effect draws everything: Keyglow's own (rgb_matrix_user.inc).
#define RGB_MATRIX_DEFAULT_MODE RGB_MATRIX_CUSTOM_keyglow
#define RGB_MATRIX_SLEEP        // dark while the PC sleeps

// The ALT's raw HID interface is QMK's usual one: usage page 0xFF60, usage 0x61.
