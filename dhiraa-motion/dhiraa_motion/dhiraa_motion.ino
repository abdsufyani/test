// ذراع للتقنية — كاشف الحركة بالواي فاي (ESP32 + CSI)
// الفكرة: القطعة تتصل بالراوتر وترسل له "بنق" باستمرار، ومع كل رد تقرأ
// معلومات القناة (CSI). لما أحد يتحرك تتغير قوة الترددات، ونكشف هالتغير.
// الصفحة: افتح http://dhiraa.local من جوالك وأنت على نفس الشبكة.

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include "esp_wifi.h"
#include "ping/ping_sock.h"
#include "lwip/ip_addr.h"

// ====== عدّل هنا ======
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* HOSTNAME  = "dhiraa";      // الرابط: http://dhiraa.local
const float SENSITIVITY = 4.0;         // أقل = أحسّ (جرّب 3 إلى 6)
const uint32_t CALIB_MS = 10000;       // مدة المعايرة بعد التشغيل
const uint32_t HOLD_MS  = 2000;        // كم تبقى "تم كشف حركة" بعد آخر حركة
const uint32_t PING_INTERVAL_MS = 20;  // 50 قراءة بالثانية
// ======================

WebServer server(80);

static uint8_t routerMac[6];
static float prevAmp[64];
static bool hasPrev = false;
static volatile float level = 0;       // مقدار تغيّر الإشارة (منعّم)
static volatile uint32_t packets = 0;

// إحصائيات المعايرة
static uint32_t calibStart = 0;
static bool calibrating = true;
static double cMean = 0, cM2 = 0;
static uint32_t cCount = 0;
static float threshold = 0;
static uint32_t lastMotion = 0;

const char PAGE[] PROGMEM = R"rawliteral(
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b1020">
<title>ذراع للتقنية | كاشف الحركة</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root { --bg:#0b1020; --card:#141b2e; --txt:#f3f5fa; --mut:#8a93a8; --acc:#3ee0ff; --green:#16a34a; }
  * { box-sizing:border-box; margin:0; padding:0; }
  html, body { height:100%; }
  body {
    font-family:"Cairo", system-ui, -apple-system, "Segoe UI", Tahoma, sans-serif;
    background:var(--bg); color:var(--txt);
    display:flex; flex-direction:column; align-items:center;
    padding:max(28px, env(safe-area-inset-top)) 16px 24px;
    transition:background .25s ease;
  }
  header { text-align:center; }
  .brand { font-size:clamp(30px, 8vw, 46px); font-weight:800; line-height:1.2; }
  .tag { font-size:clamp(13px, 3.6vw, 16px); font-weight:600; color:var(--mut); margin-top:4px; }
  main { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:22px; width:100%; }
  .ring {
    width:clamp(150px, 46vw, 220px); aspect-ratio:1; border-radius:50%;
    border:6px solid var(--mut); display:grid; place-items:center; position:relative;
  }
  .ring svg { width:46%; height:46%; }
  .status { font-size:clamp(34px, 10vw, 60px); font-weight:800; text-align:center; line-height:1.25; }
  .hint { font-size:15px; color:var(--mut); text-align:center; min-height:1.5em; }
  .meter { width:min(320px, 80vw); height:8px; border-radius:8px; background:var(--card); overflow:hidden; }
  .meter i { display:block; height:100%; width:0; background:var(--acc); border-radius:8px; transition:width .2s; }
  footer { display:flex; gap:10px; }
  button {
    font:inherit; font-size:14px; font-weight:600; color:var(--txt);
    background:transparent; border:1.5px solid var(--mut); border-radius:999px; padding:8px 18px; cursor:pointer;
  }
  .person { display:none; }

  /* حالة كشف الحركة: الشاشة خضراء والخط أبيض */
  body.motion { background:var(--green); }
  body.motion, body.motion .tag, body.motion .hint { color:#fff; }
  body.motion .ring { border-color:#fff; }
  body.motion .ring::after {
    content:""; position:absolute; inset:-6px; border-radius:50%; border:6px solid #fff;
    animation:pulse 1.1s ease-out infinite;
  }
  body.motion .person { display:block; }
  body.motion .dash { display:none; }
  body.motion .meter { background:rgba(255,255,255,.25); }
  body.motion .meter i { background:#fff; }
  body.motion button { color:#fff; border-color:#fff; }
  body.calib .ring { border-color:var(--acc); }
  body.offline .ring { border-color:#ff5a6e; }
  @keyframes pulse { from { transform:scale(1); opacity:.8; } to { transform:scale(1.45); opacity:0; } }
</style>
</head>
<body>
  <header>
    <div class="brand">ذراع للتقنية</div>
    <div class="tag">ذراعك الأيمن للتقنية</div>
  </header>

  <main>
    <div class="ring">
      <svg viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="9" stroke-linecap="round">
        <line class="dash" x1="25" y1="50" x2="75" y2="50"/>
        <g class="person">
          <circle cx="50" cy="18" r="10"/>
          <path d="M50 30 V62 M50 38 L28 52 M50 38 L72 52 M50 62 L36 92 M50 62 L64 92"/>
        </g>
      </svg>
    </div>
    <div class="status" id="status">جاري الاتصال…</div>
    <div class="hint" id="hint"></div>
    <div class="meter"><i id="bar"></i></div>
  </main>

  <footer>
    <button id="calib">إعادة المعايرة</button>
  </footer>

<script>
  const $ = id => document.getElementById(id);
  const demo = location.protocol === "file:" || new URLSearchParams(location.search).has("demo");
  let wasMotion = false, fails = 0;

  function render(s) {
    document.body.className = s.calibrating ? "calib" : (s.motion ? "motion" : "");
    if (s.calibrating) {
      $("status").textContent = "جاري المعايرة";
      $("hint").textContent = "اطلع من الغرفة أو لا تتحرك لثواني";
    } else if (s.motion) {
      $("status").textContent = "تم كشف حركة";
      $("hint").textContent = "فيه أحد يتحرك الحين";
    } else {
      $("status").textContent = "لا توجد حركة";
      $("hint").textContent = "المكان هادئ";
    }
    const pct = s.threshold > 0 ? Math.min(100, (s.level / (s.threshold * 2)) * 100) : 0;
    $("bar").style.width = pct + "%";
    if (s.motion && !wasMotion && navigator.vibrate) navigator.vibrate(200);
    wasMotion = s.motion;
  }

  // وضع العرض: يحاكي الحساس لو فتحت الصفحة من جهازك بدون القطعة
  let t0 = Date.now();
  function fakeStatus() {
    const t = (Date.now() - t0) / 1000;
    const calibrating = t < 3, motion = !calibrating && (t % 8) > 4;
    return { calibrating, motion, level: motion ? 0.9 : 0.2, threshold: 0.5 };
  }

  async function poll() {
    try {
      const s = demo ? fakeStatus() : await (await fetch("/status", { cache: "no-store" })).json();
      fails = 0;
      render(s);
    } catch (e) {
      if (++fails > 3) {
        document.body.className = "offline";
        $("status").textContent = "انقطع الاتصال";
        $("hint").textContent = "تأكد إن القطعة شغالة وإنك على نفس الشبكة";
      }
    }
    setTimeout(poll, 250);
  }

  $("calib").onclick = () => demo ? (t0 = Date.now()) : fetch("/calibrate", { method: "POST" });
  poll();
</script>
</body>
</html>
)rawliteral";

// يُستدعى مع كل حزمة واي فاي فيها CSI
void onCsi(void* ctx, wifi_csi_info_t* info) {
  if (!info || !info->buf) return;
  if (memcmp(info->mac, routerMac, 6) != 0) return;  // نقرأ ردود الراوتر بس

  int n = min((int)info->len / 2, 64);
  if (n < 8) return;
  float amp[64];
  float sum = 0;
  for (int i = 0; i < n; i++) {
    float im = info->buf[2 * i];
    float re = info->buf[2 * i + 1];
    amp[i] = sqrtf(re * re + im * im);
    sum += amp[i];
  }
  if (sum < 1) return;
  float mean = sum / n;
  for (int i = 0; i < n; i++) amp[i] /= mean;  // نلغي تأثير تغيّر قوة الإرسال العامة

  if (hasPrev) {
    float d = 0;
    for (int i = 0; i < n; i++) d += fabsf(amp[i] - prevAmp[i]);
    d /= n;
    level = level * 0.9f + d * 0.1f;
  }
  memcpy(prevAmp, amp, sizeof(float) * n);
  hasPrev = true;
  packets++;
}

void startCsi() {
  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;
  cfg.htltf_en = false;
  cfg.stbc_htltf2_en = false;
  cfg.ltf_merge_en = false;
  cfg.channel_filter_en = false;
  cfg.manu_scale = false;
  cfg.shift = 0;
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(onCsi, nullptr));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

// بنق مستمر للراوتر عشان تجينا ردود نقرأ منها الـCSI
void startPing() {
  esp_ping_config_t pc = ESP_PING_DEFAULT_CONFIG();
  IPAddress gw = WiFi.gatewayIP();
  IP_ADDR4(&pc.target_addr, gw[0], gw[1], gw[2], gw[3]);
  pc.count = ESP_PING_COUNT_INFINITE;
  pc.interval_ms = PING_INTERVAL_MS;
  pc.timeout_ms = 1000;
  pc.task_stack_size = 4096;
  esp_ping_callbacks_t cbs = {};
  esp_ping_handle_t h;
  if (esp_ping_new_session(&pc, &cbs, &h) == ESP_OK) esp_ping_start(h);
}

void resetCalibration() {
  calibrating = true;
  calibStart = millis();
  cMean = cM2 = 0;
  cCount = 0;
  lastMotion = 0;
}

void updateDetector() {
  static uint32_t lastSample = 0;
  if (millis() - lastSample < 50) return;
  lastSample = millis();
  float v = level;

  if (calibrating) {
    cCount++;
    double delta = v - cMean;
    cMean += delta / cCount;
    cM2 += delta * (v - cMean);
    if (millis() - calibStart >= CALIB_MS && cCount > 20) {
      float sd = sqrt(cM2 / (cCount - 1));
      threshold = max((float)(cMean + SENSITIVITY * sd), (float)(cMean * 1.5));
      calibrating = false;
      Serial.printf("المعايرة خلصت: المتوسط=%.4f العتبة=%.4f\n", cMean, threshold);
    }
    return;
  }
  if (v > threshold) lastMotion = millis();
}

bool motionNow() {
  return !calibrating && lastMotion != 0 && millis() - lastMotion < HOLD_MS;
}

void handleStatus() {
  char b[160];
  snprintf(b, sizeof(b),
           "{\"motion\":%s,\"calibrating\":%s,\"level\":%.4f,\"threshold\":%.4f,\"packets\":%lu}",
           motionNow() ? "true" : "false", calibrating ? "true" : "false",
           (float)level, threshold, (unsigned long)packets);
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json", b);
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // بدون توفير طاقة عشان نستقبل كل الحزم
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("أتصل بالشبكة");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nمتصل: %s\n", WiFi.localIP().toString().c_str());
  memcpy(routerMac, WiFi.BSSID(), 6);

  if (MDNS.begin(HOSTNAME)) Serial.printf("افتح: http://%s.local\n", HOSTNAME);

  server.on("/", [] { server.send_P(200, "text/html; charset=utf-8", PAGE); });
  server.on("/status", handleStatus);
  server.on("/calibrate", HTTP_POST, [] { resetCalibration(); server.send(200, "text/plain", "ok"); });
  server.begin();

  startCsi();
  startPing();
  resetCalibration();
}

void loop() {
  server.handleClient();
  updateDetector();

  if (WiFi.status() != WL_CONNECTED) {  // لو انقطع الواي فاي نعيد الاتصال
    WiFi.reconnect();
    delay(1000);
  }
}
