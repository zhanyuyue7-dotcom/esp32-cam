// Camera pin map and MJPEG approach: Espressif arduino-esp32 CameraWebServer.
#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "secrets.h"

static esp_err_t cameraError = ESP_FAIL;
static uint16_t sensorPid = 0;
static volatile uint32_t framesSent = 0;
static httpd_handle_t webServer = nullptr, streamServer = nullptr;

static const char PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>岳大师 · 实时摄像头</title><style>
:root{color-scheme:light;--bg:#faf9f5;--fg:#3d3929;--accent:#c96442;--line:#dad9d4}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1040px;margin:36px auto;padding:0 20px}header{display:flex;align-items:center;justify-content:space-between;gap:16px}h1{font-size:clamp(22px,4vw,32px);margin:4px 0}small{color:#83827d;letter-spacing:.06em}.badge{border:1px solid var(--line);border-radius:24px;padding:7px 14px;white-space:nowrap}.view{background:#171716;border-radius:16px;overflow:hidden;min-height:220px;display:grid;place-items:center;margin:22px 0;aspect-ratio:4/3}.view img{width:100%;height:100%;object-fit:contain}.controls{display:flex;gap:10px;flex-wrap:wrap}button,a.button{font:inherit;cursor:pointer;border:1px solid var(--line);border-radius:9px;padding:10px 18px;background:#e9e6dc;color:var(--fg);text-decoration:none}button:first-child{background:var(--accent);color:white;border-color:var(--accent)}p{color:#83827d;font-size:14px}#detail{overflow-wrap:anywhere}@media(min-width:900px){.view{max-height:68vh;aspect-ratio:auto;height:640px}}:fullscreen{background:#171716}
</style><main><header><div><small>YUE / LIVE CAMERA</small><h1>看看此刻，正在发生什么。</h1></div><span class="badge" id="state">正在连接</span></header>
<div class="view" id="view"><img id="video" alt="正在加载实时画面"></div>
<div class="controls"><button id="toggle">暂停画面</button><button id="retry">重新连接</button><button id="mirror">左右镜像</button><button id="rotate">旋转画面</button><button id="full">全屏查看</button><a class="button" href="/capture" target="_blank" rel="noopener">拍一张照片</a></div>
<p id="detail">正在读取摄像头状态…</p><p>连接与摄像头相同的 Wi-Fi，即可实时查看。画面由摄像头直接传到浏览器。</p></main><script>
const video=document.getElementById('video'),state=document.getElementById('state');let playing=true,angle=0,mirror=1;
function start(){video.src='http://'+location.hostname+':81/stream?t='+Date.now();playing=true;document.getElementById('toggle').textContent='暂停画面';state.textContent='实时画面'}
function stop(){video.removeAttribute('src');playing=false;document.getElementById('toggle').textContent='继续播放';state.textContent='已暂停'}
document.getElementById('toggle').onclick=()=>playing?stop():start();document.getElementById('retry').onclick=start;
function transform(){video.style.transform=`rotate(${angle}deg) scaleX(${mirror})`}
document.getElementById('mirror').onclick=()=>{mirror*=-1;transform()};document.getElementById('rotate').onclick=()=>{angle=(angle+90)%360;transform()};document.getElementById('full').onclick=()=>document.getElementById('view').requestFullscreen?.();
video.onerror=()=>{if(playing)state.textContent='画面中断，请重新连接'};
async function status(){try{let s=await(await fetch('/status',{cache:'no-store',signal:AbortSignal.timeout(4000)})).json();document.getElementById('detail').textContent=`${s.sensor} · 640 × 480 · Wi-Fi ${s.rssi} dBm · 已传送 ${s.frames} 帧 · 已运行 ${s.uptime_s} 秒`;if(!s.camera_ok){state.textContent='摄像头初始化失败';document.getElementById('detail').textContent='错误码：'+s.camera_error}}catch(e){state.textContent='连接中断，请检查 Wi-Fi'}}start();status();setInterval(status,5000);
</script></html>)HTML";

static esp_err_t indexHandler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t statusHandler(httpd_req_t *req) {
  char json[512];
  const char *sensor = sensorPid == OV5640_PID ? "OV5640" : sensorPid == OV2640_PID ? "OV2640" : "Camera";
  snprintf(json, sizeof(json), "{\"camera_ok\":%s,\"camera_error\":%d,\"sensor\":\"%s\",\"pid\":%u,\"psram\":%u,\"heap\":%u,\"frames\":%u,\"uptime_s\":%u,\"rssi\":%d,\"ip\":\"%s\",\"ap_ip\":\"%s\"}",
           cameraError == ESP_OK ? "true" : "false", cameraError, sensor, sensorPid, ESP.getPsramSize(), ESP.getFreeHeap(),
           (unsigned)framesSent, millis()/1000, WiFi.RSSI(), WiFi.localIP().toString().c_str(), WiFi.softAPIP().toString().c_str());
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t captureHandler(httpd_req_t *req) {
  if (cameraError != ESP_OK) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera initialization failed");
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "No camera frame");
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=camera.jpg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t result = httpd_resp_send(req, reinterpret_cast<const char *>(fb->buf), fb->len);
  esp_camera_fb_return(fb);
  return result;
}

static esp_err_t streamHandler(httpd_req_t *req) {
  if (cameraError != ESP_OK) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera initialization failed");
  httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=frame");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t result = ESP_OK;
  uint32_t sessionFrames = 0, began = millis();
  while (result == ESP_OK) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) { result = ESP_FAIL; break; }
    char header[96];
    int n = snprintf(header, sizeof(header), "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", (unsigned)fb->len);
    result = httpd_resp_send_chunk(req, header, n);
    if (result == ESP_OK) result = httpd_resp_send_chunk(req, reinterpret_cast<const char *>(fb->buf), fb->len);
    esp_camera_fb_return(fb);
    if (result == ESP_OK) { ++framesSent; ++sessionFrames; }
    delay(1);
  }
  Serial.printf("STREAM_END frames=%u elapsed_ms=%u\n", (unsigned)sessionFrames, millis()-began);
  return result;
}

static void addRoute(httpd_handle_t server, const char *uri, esp_err_t (*handler)(httpd_req_t *)) {
  httpd_uri_t route = {};
  route.uri = uri; route.method = HTTP_GET; route.handler = handler;
  ESP_ERROR_CHECK(httpd_register_uri_handler(server, &route));
}

static void startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.stack_size = 8192;
  config.lru_purge_enable = true;
  config.send_wait_timeout = 5;
  ESP_ERROR_CHECK(httpd_start(&webServer, &config));
  addRoute(webServer, "/", indexHandler);
  addRoute(webServer, "/status", statusHandler);
  addRoute(webServer, "/capture", captureHandler);
  config.server_port = 81; config.ctrl_port += 1;
  ESP_ERROR_CHECK(httpd_start(&streamServer, &config));
  addRoute(streamServer, "/stream", streamHandler);
}

static void initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = 5; c.pin_d1 = 18; c.pin_d2 = 19; c.pin_d3 = 21;
  c.pin_d4 = 36; c.pin_d5 = 39; c.pin_d6 = 34; c.pin_d7 = 35;
  c.pin_xclk = 0; c.pin_pclk = 22; c.pin_vsync = 25; c.pin_href = 23;
  c.pin_sccb_sda = 26; c.pin_sccb_scl = 27; c.pin_pwdn = 32; c.pin_reset = -1;
  c.xclk_freq_hz = 20000000; c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = psramFound() ? FRAMESIZE_UXGA : FRAMESIZE_VGA;
  c.jpeg_quality = 12; c.fb_count = psramFound() ? 2 : 1;
  c.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  cameraError = esp_camera_init(&c);
  Serial.printf("CAMERA_INIT result=0x%x PSRAM=%u\n", cameraError, ESP.getPsramSize());
  if (cameraError != ESP_OK) return;
  sensor_t *s = esp_camera_sensor_get();
  sensorPid = s->id.PID;
  s->set_framesize(s, FRAMESIZE_VGA);
  Serial.printf("CAMERA_SENSOR pid=0x%04x\n", sensorPid);
  for (int i = 0; i < 5; ++i) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) { Serial.printf("CAMERA_FRAME %ux%u bytes=%u\n", fb->width, fb->height, (unsigned)fb->len); esp_camera_fb_return(fb); }
    else Serial.println("CAMERA_FRAME_FAILED");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nYUE_ESP32_CAM build=20260909-v1");
  pinMode(4, OUTPUT); digitalWrite(4, LOW);
  initCamera();
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  wifi_country_t country = {"CN", 1, 13, 20, WIFI_COUNTRY_POLICY_MANUAL};
  esp_wifi_set_country(&country);
  WiFi.setSleep(false);
  WiFi.setHostname("esp32cam");
  WiFi.setAutoReconnect(true);
  WiFi.softAP(AP_SSID, AP_PASSWORD, 1, false, 4);
  Serial.printf("CAMERA_AP ssid=%s url=http://%s/\n", AP_SSID, WiFi.softAPIP().toString().c_str());
  int count = WiFi.scanNetworks();
  int best = -1;
  for (int i = 0; i < count; ++i) {
    if (WiFi.SSID(i) == STA_SSID && (best < 0 || WiFi.RSSI(i) > WiFi.RSSI(best))) best = i;
  }
  if (best >= 0) {
    uint8_t bssid[6]; memcpy(bssid, WiFi.BSSID(best), sizeof(bssid));
    int channel = WiFi.channel(best);
    Serial.printf("STA_CONNECT ssid=%s channel=%d rssi=%d\n", STA_SSID, channel, WiFi.RSSI(best));
    WiFi.begin(STA_SSID, STA_PASSWORD, channel, bssid);
  } else { Serial.println("STA_NOT_FOUND using AP; station will retry"); WiFi.begin(STA_SSID, STA_PASSWORD); }
  WiFi.scanDelete();
  startServers();
}

void loop() {
  static uint32_t lastRetry = 0, lastLog = 0;
  static IPAddress announced;
  if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != announced) {
    announced = WiFi.localIP();
    MDNS.begin("esp32cam"); MDNS.addService("http", "tcp", 80);
    Serial.printf("CAMERA_READY http://%s/ RSSI=%d\n", announced.toString().c_str(), WiFi.RSSI());
  }
  if (WiFi.status() != WL_CONNECTED && millis()-lastRetry > 30000) { lastRetry = millis(); WiFi.reconnect(); }
  if (millis()-lastLog > 10000) {
    lastLog = millis();
    Serial.printf("HEALTH uptime=%u wifi=%d ip=%s frames=%u heap=%u\n", millis()/1000, WiFi.status(), WiFi.localIP().toString().c_str(), (unsigned)framesSent, ESP.getFreeHeap());
  }
  delay(100);
}
