#pragma once

#include "driver/gpio.h"

/*
 * Proposed INMP441 wiring from the project handoff. Verify these three wires
 * against the actual prototype before flashing this diagnostic:
 *   SCK/BCLK -> GPIO6, WS/LRCLK -> GPIO7, SD -> GPIO8
 */
#define MIC_I2S_BCLK_GPIO GPIO_NUM_6
#define MIC_I2S_WS_GPIO   GPIO_NUM_7
#define MIC_I2S_SD_GPIO   GPIO_NUM_0

/*
 * Proposed TB6612FNG channel-A wiring from the handoff:
 *   PWMA -> GPIO10, AIN1 -> GPIO11, AIN2 -> GPIO18, STBY -> GPIO21
 * Only STBY -> GPIO21 was explicitly confirmed. Keep the test disabled until
 * all four wires are checked against the actual board.
 */
#define MOTOR_PWMA_GPIO GPIO_NUM_10
#define MOTOR_AIN1_GPIO GPIO_NUM_11
#define MOTOR_AIN2_GPIO GPIO_NUM_18
#define MOTOR_STBY_GPIO GPIO_NUM_21

#define MOTOR_TEST_PINOUT_CONFIRMED 1
