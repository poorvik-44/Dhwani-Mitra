#pragma once

#include "driver/gpio.h"

/* TB6612FNG channel A pins validated with the existing one-shot test. */
#define MOTOR_PWMA_GPIO GPIO_NUM_10
#define MOTOR_AIN1_GPIO GPIO_NUM_11
#define MOTOR_AIN2_GPIO GPIO_NUM_18
#define MOTOR_STBY_GPIO GPIO_NUM_21
