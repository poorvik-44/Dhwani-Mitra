#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "hardware_pins.h"

#define AUDIO_SAMPLE_RATE_HZ 16000
#define I2S_READ_BYTES       4096
#define MOTOR_PULSE_MS       180

static const char *TAG = "DM_DIAGNOSTIC";
static i2s_chan_handle_t s_rx_channel;

static void microphone_task(void *arg)
{
    (void)arg;
    static int32_t raw[I2S_READ_BYTES / sizeof(int32_t)];
    uint64_t left_squares = 0;
    uint64_t right_squares = 0;
    uint32_t left_peak = 0;
    uint32_t right_peak = 0;
    uint32_t left_nonzero = 0;
    uint32_t right_nonzero = 0;
    uint32_t left_count = 0;
    uint32_t right_count = 0;
    uint32_t blocks = 0;
    uint32_t first_raw[4] = {0};
    bool first_raw_set = false;
    TickType_t last_report = xTaskGetTickCount();

    while (true) {
        size_t bytes_read = 0;
        esp_err_t err = i2s_channel_read(s_rx_channel, raw, sizeof(raw), &bytes_read, 1000);
        if (err != ESP_OK || bytes_read == 0) {
            ESP_LOGE(TAG, "I2S read failed: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(250));
            continue;
        }

        const size_t sample_count = bytes_read / sizeof(int32_t);
        if (!first_raw_set && sample_count >= 4) {
            for (size_t i = 0; i < 4; i++) first_raw[i] = (uint32_t)raw[i];
            first_raw_set = true;
        }
        for (size_t i = 0; i + 1 < sample_count; i += 2) {
            /* INMP441 sends signed 24-bit samples in 32-bit I2S slots. */
            const int32_t left = raw[i] >> 8;
            const int32_t right = raw[i + 1] >> 8;
            const uint32_t left_abs = (uint32_t)(left < 0 ? -(int64_t)left : left);
            const uint32_t right_abs = (uint32_t)(right < 0 ? -(int64_t)right : right);

            left_squares += (uint64_t)((int64_t)left * left);
            right_squares += (uint64_t)((int64_t)right * right);
            if (left_abs > left_peak) left_peak = left_abs;
            if (right_abs > right_peak) right_peak = right_abs;
            if (left != 0) left_nonzero++;
            if (right != 0) right_nonzero++;
            left_count++;
            right_count++;
        }
        blocks++;

        if (xTaskGetTickCount() - last_report >= pdMS_TO_TICKS(1000)) {
            const float left_rms = left_count ?
                sqrtf((float)left_squares / (float)left_count) / 8388608.0f : 0.0f;
            const float right_rms = right_count ?
                sqrtf((float)right_squares / (float)right_count) / 8388608.0f : 0.0f;
            const bool data_seen = left_peak > 0 || right_peak > 0;

            ESP_LOGI(TAG,
                     "MIC %s | I2S blocks/s=%" PRIu32
                     " | L peak=%" PRIu32 " rms=%.6f nonzero=%" PRIu32
                     " | R peak=%" PRIu32 " rms=%.6f nonzero=%" PRIu32
                     " | raw[0..3]=%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32 ",%08" PRIx32,
                     data_seen ? "DATA" : "NO DATA",
                     blocks, left_peak, left_rms, left_nonzero,
                     right_peak, right_rms, right_nonzero,
                     first_raw[0], first_raw[1], first_raw[2], first_raw[3]);

            left_squares = 0;
            right_squares = 0;
            left_peak = 0;
            right_peak = 0;
            left_nonzero = 0;
            right_nonzero = 0;
            left_count = 0;
            right_count = 0;
            blocks = 0;
            first_raw_set = false;
            last_report = xTaskGetTickCount();
        }
    }
}

static void microphone_init(void)
{
    const i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&channel_config, NULL, &s_rx_channel));

    const i2s_std_config_t std_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE_HZ),
        /* INMP441 uses the Philips I2S protocol (one-bit WS-to-data delay). */
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = MIC_I2S_BCLK_GPIO,
            .ws = MIC_I2S_WS_GPIO,
            .dout = I2S_GPIO_UNUSED,
            .din = MIC_I2S_SD_GPIO,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_rx_channel, &std_config));
    ESP_ERROR_CHECK(i2s_channel_enable(s_rx_channel));
    ESP_LOGI(TAG, "I2S RX ready at %d Hz; proposed pins BCLK=%d WS=%d SD=%d",
             AUDIO_SAMPLE_RATE_HZ, MIC_I2S_BCLK_GPIO, MIC_I2S_WS_GPIO, MIC_I2S_SD_GPIO);
}

static void motor_init_safe(void)
{
#if MOTOR_TEST_PINOUT_CONFIRMED
    const gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << MOTOR_PWMA_GPIO) | (1ULL << MOTOR_AIN1_GPIO) |
                        (1ULL << MOTOR_AIN2_GPIO) | (1ULL << MOTOR_STBY_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_PWMA_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_AIN1_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_AIN2_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 0));
#else
    ESP_LOGW(TAG, "Motor output is LOCKED: confirm PWMA/AIN1/AIN2/STBY wiring, then set MOTOR_TEST_PINOUT_CONFIRMED to 1 in hardware_pins.h");
#endif
}

static void motor_test_once(void)
{
#if MOTOR_TEST_PINOUT_CONFIRMED
    ESP_LOGW(TAG, "Motor test: one %d ms pulse on TB6612 channel A", MOTOR_PULSE_MS);
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 1));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_AIN1_GPIO, 1));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_AIN2_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_PWMA_GPIO, 1));
    vTaskDelay(pdMS_TO_TICKS(MOTOR_PULSE_MS));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_PWMA_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_AIN1_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_AIN2_GPIO, 0));
    ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 0));
    ESP_LOGI(TAG, "Motor test pulse complete; driver returned to standby");
#else
    ESP_LOGE(TAG, "Motor pulse not sent. Confirm the motor control wires and enable the test in hardware_pins.h first.");
#endif
}

static void console_task(void *arg)
{
    (void)arg;
    char line[32];
    ESP_LOGI(TAG, "Console ready. Press M then Enter for one motor test; Q then Enter to show commands.");

    while (true) {
        if (!fgets(line, sizeof(line), stdin)) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (line[0] == 'm' || line[0] == 'M') {
            motor_test_once();
        } else if (line[0] == 'q' || line[0] == 'Q' || line[0] == '?') {
            ESP_LOGI(TAG, "M + Enter: one short motor pulse (only if enabled); mic levels print once per second");
        } else {
            ESP_LOGW(TAG, "Unknown command; use M or Q, followed by Enter");
        }
    }
}

void app_main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    ESP_LOGI(TAG, "Dhvani Mitra mic/motor diagnostic booting");
    microphone_init();
    motor_init_safe();
    xTaskCreate(microphone_task, "mic_monitor", 4096, NULL, 5, NULL);
    xTaskCreate(console_task, "diagnostic_console", 3072, NULL, 4, NULL);
}
