#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "hardware_pins.h"

#define WIFI_SSID_MAX 32
#define WIFI_PASSWORD_MAX 63
#define SERVER_HOST_MAX 64
#define WS_URI_MAX 160
#define WS_RX_MAX 4096
#define MAX_PULSES 8
#define MAX_ON_MS 5000
#define MAX_OFF_MS 5000
#define MOTOR_QUEUE_DEPTH 4
#define PWM_FREQUENCY_HZ 20000
#define PWM_RESOLUTION LEDC_TIMER_10_BIT
#define PWM_MAX_DUTY 1023

static const char *TAG = "DHVANI_WRISTBAND";
static const EventBits_t WIFI_READY_BIT = BIT0;

typedef struct {
    char event_id[48];
    char category[32];
    int intensity;
    int pulse_count;
    struct {
        int on_ms;
        int off_ms;
    } pulses[MAX_PULSES];
} haptic_job_t;

static char s_wifi_ssid[WIFI_SSID_MAX + 1];
static char s_wifi_password[WIFI_PASSWORD_MAX + 1];
static char s_server_host[SERVER_HOST_MAX + 1] = "0.0.0.0";
static char s_device_ip[16];
static EventGroupHandle_t s_events;
static QueueHandle_t s_haptic_queue;
static SemaphoreHandle_t s_ws_send_mutex;
static esp_websocket_client_handle_t s_ws_client;
static char s_ws_rx[WS_RX_MAX + 1];
static size_t s_ws_rx_used;
static bool s_wifi_configured;

static bool websocket_connected(void)
{
    return s_ws_client && esp_websocket_client_is_connected(s_ws_client);
}

static bool send_json(cJSON *root)
{
    if (!root || !websocket_connected()) return false;
    char *encoded = cJSON_PrintUnformatted(root);
    if (!encoded) return false;
    xSemaphoreTake(s_ws_send_mutex, portMAX_DELAY);
    const int sent = esp_websocket_client_send_text(s_ws_client, encoded,
                                                     (int)strlen(encoded),
                                                     pdMS_TO_TICKS(3000));
    xSemaphoreGive(s_ws_send_mutex);
    cJSON_free(encoded);
    return sent >= 0;
}

static bool send_status(const char *type, const char *event_id, const char *category)
{
    cJSON *message = cJSON_CreateObject();
    if (!message) return false;
    cJSON_AddStringToObject(message, "type", type);
    if (event_id && event_id[0]) cJSON_AddStringToObject(message, "event_id", event_id);
    if (category && category[0]) cJSON_AddStringToObject(message, "category", category);
    if (strcmp(type, "device_status") == 0 && s_device_ip[0]) {
        cJSON_AddStringToObject(message, "ip", s_device_ip);
    }
    const bool ok = send_json(message);
    cJSON_Delete(message);
    return ok;
}

static void motor_outputs_off(void)
{
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    gpio_set_level(MOTOR_AIN1_GPIO, 0);
    gpio_set_level(MOTOR_AIN2_GPIO, 0);
    gpio_set_level(MOTOR_STBY_GPIO, 0);
}

static void motor_init(void)
{
    const gpio_config_t gpio_cfg = {
        .pin_bit_mask = (1ULL << MOTOR_AIN1_GPIO) | (1ULL << MOTOR_AIN2_GPIO) |
                        (1ULL << MOTOR_STBY_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&gpio_cfg));

    const ledc_timer_config_t timer_cfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = PWM_RESOLUTION,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = PWM_FREQUENCY_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer_cfg));
    const ledc_channel_config_t channel_cfg = {
        .gpio_num = MOTOR_PWMA_GPIO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&channel_cfg));
    motor_outputs_off();
    ESP_LOGI(TAG, "TB6612 channel A ready (PWMA=%d AIN1=%d AIN2=%d STBY=%d)",
             MOTOR_PWMA_GPIO, MOTOR_AIN1_GPIO, MOTOR_AIN2_GPIO, MOTOR_STBY_GPIO);
}

static bool parse_haptic(const cJSON *message, haptic_job_t *job)
{
    if (!cJSON_IsObject(message) || !job) return false;
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(message, "type");
    const cJSON *event_id = cJSON_GetObjectItemCaseSensitive(message, "event_id");
    const cJSON *category = cJSON_GetObjectItemCaseSensitive(message, "category");
    const cJSON *intensity = cJSON_GetObjectItemCaseSensitive(message, "intensity");
    const cJSON *pulses = cJSON_GetObjectItemCaseSensitive(message, "pulses");
    if (!cJSON_IsString(type) ||
        (strcmp(type->valuestring, "haptic_command") != 0 &&
         strcmp(type->valuestring, "haptic_test") != 0) ||
        !cJSON_IsString(category) || !cJSON_IsNumber(intensity) ||
        !cJSON_IsArray(pulses)) return false;

    memset(job, 0, sizeof(*job));
    if (cJSON_IsString(event_id)) snprintf(job->event_id, sizeof(job->event_id), "%s", event_id->valuestring);
    snprintf(job->category, sizeof(job->category), "%s", category->valuestring);
    job->intensity = intensity->valueint;
    if (job->intensity < 1 || job->intensity > 100) return false;

    const int count = cJSON_GetArraySize(pulses);
    if (count < 1 || count > MAX_PULSES) return false;
    cJSON *pulse = NULL;
    cJSON_ArrayForEach(pulse, pulses) {
        const cJSON *on_ms = cJSON_GetObjectItemCaseSensitive(pulse, "on_ms");
        const cJSON *off_ms = cJSON_GetObjectItemCaseSensitive(pulse, "off_ms");
        if (!cJSON_IsNumber(on_ms) || !cJSON_IsNumber(off_ms) ||
            on_ms->valueint < 20 || on_ms->valueint > MAX_ON_MS ||
            off_ms->valueint < 0 || off_ms->valueint > MAX_OFF_MS) return false;
        job->pulses[job->pulse_count].on_ms = on_ms->valueint;
        job->pulses[job->pulse_count].off_ms = off_ms->valueint;
        job->pulse_count++;
    }
    return true;
}

static void play_job(const haptic_job_t *job)
{
    const uint32_t duty = (uint32_t)((uint64_t)job->intensity * PWM_MAX_DUTY / 100);
    ESP_LOGI(TAG, "VIBRATE category=%s intensity=%d%% pulses=%d",
             job->category, job->intensity, job->pulse_count);
    gpio_set_level(MOTOR_STBY_GPIO, 1);
    gpio_set_level(MOTOR_AIN1_GPIO, 1);
    gpio_set_level(MOTOR_AIN2_GPIO, 0);
    for (int i = 0; i < job->pulse_count; ++i) {
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
        vTaskDelay(pdMS_TO_TICKS(job->pulses[i].on_ms));
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
        if (job->pulses[i].off_ms > 0) vTaskDelay(pdMS_TO_TICKS(job->pulses[i].off_ms));
    }
    motor_outputs_off();
    ESP_LOGI(TAG, "Vibration complete category=%s", job->category);
}

static void haptic_task(void *arg)
{
    (void)arg;
    haptic_job_t job;
    while (true) {
        if (xQueueReceive(s_haptic_queue, &job, portMAX_DELAY) == pdTRUE) {
            play_job(&job);
            if (job.event_id[0]) send_status("haptic_complete", job.event_id, job.category);
        }
    }
}

static void process_ws_message(const char *payload)
{
    cJSON *message = cJSON_Parse(payload);
    if (!message) {
        ESP_LOGW(TAG, "Discarding invalid JSON from bridge");
        return;
    }
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(message, "type");
    if (cJSON_IsString(type) &&
        (strcmp(type->valuestring, "haptic_command") == 0 ||
         strcmp(type->valuestring, "haptic_test") == 0)) {
        haptic_job_t job;
        if (parse_haptic(message, &job)) {
            if (xQueueSend(s_haptic_queue, &job, 0) == pdTRUE) {
                ESP_LOGI(TAG, "Queued haptic command category=%s", job.category);
                if (job.event_id[0]) send_status("haptic_ack", job.event_id, job.category);
            } else {
                ESP_LOGE(TAG, "Haptic queue full; command rejected");
            }
        } else {
            ESP_LOGE(TAG, "Rejected malformed/unsafe haptic command");
        }
    } else if (cJSON_IsString(type) && strcmp(type->valuestring, "sync_config") == 0) {
        ESP_LOGI(TAG, "Bridge configuration sync received; each vibration uses the current command pulse data");
    }
    cJSON_Delete(message);
}

static void websocket_event(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    (void)handler_args;
    (void)base;
    esp_websocket_event_data_t *event = (esp_websocket_event_data_t *)event_data;
    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "Connected to FastAPI WebSocket bridge");
        send_status("device_status", NULL, NULL);
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "Bridge disconnected; WebSocket client will reconnect");
        s_ws_rx_used = 0;
        break;
    case WEBSOCKET_EVENT_DATA:
        if (event->op_code != 0x1 || event->data_len <= 0 || event->payload_len > WS_RX_MAX ||
            event->payload_offset != (int)s_ws_rx_used || s_ws_rx_used + (size_t)event->data_len > WS_RX_MAX) {
            s_ws_rx_used = 0;
            break;
        }
        memcpy(s_ws_rx + s_ws_rx_used, event->data_ptr, (size_t)event->data_len);
        s_ws_rx_used += (size_t)event->data_len;
        if (s_ws_rx_used >= (size_t)event->payload_len) {
            s_ws_rx[s_ws_rx_used] = '\0';
            process_ws_message(s_ws_rx);
            s_ws_rx_used = 0;
        }
        break;
    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGE(TAG, "WebSocket transport error");
        break;
    default:
        break;
    }
}

static esp_err_t load_wifi_config(void)
{
    nvs_handle_t nvs;
    esp_err_t err = nvs_open("dhvani", NVS_READONLY, &nvs);
    if (err != ESP_OK) return err;
    size_t ssid_len = sizeof(s_wifi_ssid);
    size_t password_len = sizeof(s_wifi_password);
    size_t host_len = sizeof(s_server_host);
    err = nvs_get_str(nvs, "ssid", s_wifi_ssid, &ssid_len);
    if (err == ESP_OK) err = nvs_get_str(nvs, "password", s_wifi_password, &password_len);
    if (err == ESP_OK && nvs_get_str(nvs, "server", s_server_host, &host_len) != ESP_OK) {
        snprintf(s_server_host, sizeof(s_server_host), "0.0.0.0");
    }
    nvs_close(nvs);
    return err;
}

static esp_err_t save_wifi_config(const char *ssid, const char *password, const char *server)
{
    if (!ssid || !ssid[0] || strlen(ssid) > WIFI_SSID_MAX || !password ||
        strlen(password) < 8 || strlen(password) > WIFI_PASSWORD_MAX ||
        !server || !server[0] || strlen(server) > SERVER_HOST_MAX) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t nvs;
    ESP_RETURN_ON_ERROR(nvs_open("dhvani", NVS_READWRITE, &nvs), TAG, "open nvs");
    esp_err_t err = nvs_set_str(nvs, "ssid", ssid);
    if (err == ESP_OK) err = nvs_set_str(nvs, "password", password);
    if (err == ESP_OK) err = nvs_set_str(nvs, "server", server);
    if (err == ESP_OK) err = nvs_commit(nvs);
    nvs_close(nvs);
    if (err == ESP_OK) {
        snprintf(s_wifi_ssid, sizeof(s_wifi_ssid), "%s", ssid);
        snprintf(s_wifi_password, sizeof(s_wifi_password), "%s", password);
        snprintf(s_server_host, sizeof(s_server_host), "%s", server);
    }
    return err;
}

static void wifi_event(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    (void)arg;
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, WIFI_READY_BIT);
        s_device_ip[0] = '\0';
        ESP_LOGW(TAG, "Wi-Fi disconnected; retrying");
        if (s_wifi_configured) esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = (const ip_event_got_ip_t *)event_data;
        snprintf(s_device_ip, sizeof(s_device_ip), IPSTR, IP2STR(&event->ip_info.ip));
        ESP_LOGI(TAG, "Wi-Fi connected. Device IP: %s", s_device_ip);
        xEventGroupSetBits(s_events, WIFI_READY_BIT);
    }
}

static void wifi_start(void)
{
    if (!s_wifi_ssid[0]) {
        ESP_LOGW(TAG, "Wi-Fi not provisioned. Use: wifi <SSID>|<password>|<laptop IPv4>");
        return;
    }
    s_wifi_configured = true;
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    const wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t wifi_cfg = {0};
    memcpy(wifi_cfg.sta.ssid, s_wifi_ssid, strlen(s_wifi_ssid));
    memcpy(wifi_cfg.sta.password, s_wifi_password, strlen(s_wifi_password));
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_cfg.sta.pmf_cfg.capable = true;
    wifi_cfg.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "Joining Wi-Fi SSID '%s'", s_wifi_ssid);
}

static void websocket_start(void)
{
    if (!s_wifi_configured) return;
    xEventGroupWaitBits(s_events, WIFI_READY_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
    char uri[WS_URI_MAX];
    snprintf(uri, sizeof(uri), "ws://%s:8000/ws/device", s_server_host);
    const esp_websocket_client_config_t ws_cfg = {
        .uri = uri,
        .network_timeout_ms = 10000,
        .reconnect_timeout_ms = 5000,
        .enable_close_reconnect = true,
        .ping_interval_sec = 20,
        .task_stack = 6144,
    };
    s_ws_client = esp_websocket_client_init(&ws_cfg);
    ESP_ERROR_CHECK(s_ws_client ? ESP_OK : ESP_FAIL);
    ESP_ERROR_CHECK(esp_websocket_register_events(s_ws_client, WEBSOCKET_EVENT_ANY, websocket_event, NULL));
    ESP_ERROR_CHECK(esp_websocket_client_start(s_ws_client));
    ESP_LOGI(TAG, "Connecting to %s", uri);
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(15000));
        if (websocket_connected()) send_status("heartbeat", NULL, NULL);
    }
}

static void console_task(void *arg)
{
    (void)arg;
    char line[256];
    ESP_LOGI(TAG, "Console ready. Configure Wi-Fi: wifi <SSID>|<password>|<laptop IPv4>");
    while (true) {
        if (!fgets(line, sizeof(line), stdin)) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        line[strcspn(line, "\r\n")] = '\0';
        if (strncmp(line, "wifi ", 5) == 0) {
            char *ssid = line + 5;
            char *first = strchr(ssid, '|');
            char *second = first ? strchr(first + 1, '|') : NULL;
            if (!first || !second) {
                ESP_LOGE(TAG, "Format: wifi <SSID>|<password>|<laptop IPv4>");
                continue;
            }
            *first = '\0';
            *second = '\0';
            const char *password = first + 1;
            const char *server = second + 1;
            esp_err_t err = save_wifi_config(ssid, password, server);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "Wi-Fi settings not saved: %s", esp_err_to_name(err));
                continue;
            }
            ESP_LOGI(TAG, "Saved Wi-Fi settings locally. Restarting to join network.");
            vTaskDelay(pdMS_TO_TICKS(300));
            esp_restart();
        } else if (strcmp(line, "status") == 0) {
            ESP_LOGI(TAG, "Wi-Fi=%s bridge=%s ip=%s", s_wifi_configured ? "configured" : "not configured",
                     websocket_connected() ? "connected" : "disconnected", s_device_ip[0] ? s_device_ip : "none");
        } else if (strcmp(line, "motor") == 0) {
            haptic_job_t job = {.intensity = 60, .pulse_count = 1, .pulses = {{.on_ms = 150, .off_ms = 0}}};
            snprintf(job.category, sizeof(job.category), "MANUAL_TEST");
            if (xQueueSend(s_haptic_queue, &job, 0) != pdTRUE) ESP_LOGE(TAG, "Haptic queue full");
        } else {
            ESP_LOGI(TAG, "Commands: wifi <SSID>|<password>|<laptop IPv4> | status | motor");
        }
    }
}

void app_main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    esp_err_t nvs_err = nvs_flash_init();
    if (nvs_err == ESP_ERR_NVS_NO_FREE_PAGES || nvs_err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    } else {
        ESP_ERROR_CHECK(nvs_err);
    }
    s_events = xEventGroupCreate();
    s_haptic_queue = xQueueCreate(MOTOR_QUEUE_DEPTH, sizeof(haptic_job_t));
    s_ws_send_mutex = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(s_events && s_haptic_queue && s_ws_send_mutex ? ESP_OK : ESP_ERR_NO_MEM);
    motor_init();
    xTaskCreate(haptic_task, "haptic_worker", 4096, NULL, 6, NULL);
    xTaskCreate(console_task, "serial_console", 4096, NULL, 4, NULL);
    xTaskCreate(heartbeat_task, "bridge_heartbeat", 3072, NULL, 3, NULL);

    if (load_wifi_config() == ESP_OK) {
        wifi_start();
        websocket_start();
    } else {
        ESP_LOGW(TAG, "No saved Wi-Fi configuration; waiting for USB serial provisioning");
    }
}
