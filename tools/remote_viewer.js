// One frame request at a time: a slow link cannot queue an unbounded video backlog.
const video = document.getElementById('video');
const state = document.getElementById('state');
const detail = document.getElementById('detail');
let playing = false, angle = 0, mirror = 1, generation = 0;
let pending = null, currentUrl = null, lastFetchMs = 0, delivered = 0;
let started = performance.now(), camera = null;
let slowLink = false, quickFrames = 0, frameWidth = 640, frameHeight = 480;
let frameTimes = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function updateDetail() {
  const now = performance.now();
  frameTimes = frameTimes.filter(t => now - t < 5000);
  const fps = frameTimes.length / Math.max(1, Math.min(5, (now - started) / 1000));
  detail.textContent = camera
    ? `${camera.sensor} · ${frameWidth} × ${frameHeight} · ${slowLink ? '低带宽模式' : '低延迟模式'} · ${fps.toFixed(1)} 帧/秒 · 最近请求 ${Math.round(lastFetchMs)} ms · Wi-Fi ${camera.rssi} dBm`
    : '正在连接摄像头…';
}

async function pullFrames(myGeneration) {
  while (playing && myGeneration === generation) {
    const controller = new AbortController();
    pending = controller;
    const timeout = setTimeout(() => controller.abort(), 6000);
    const began = performance.now();
    let newUrl = null;
    try {
      const response = await fetch('/capture?t=' + Date.now() + (slowLink ? '&profile=mobile' : ''), {
        cache: 'no-store', signal: controller.signal
      });
      if (!response.ok) throw new Error('Camera unavailable');
      const blob = await response.blob();
      if (!blob.type.startsWith('image/jpeg') || blob.size === 0) throw new Error('Invalid frame');
      if (!playing || myGeneration !== generation) break;
      newUrl = URL.createObjectURL(blob);
      // Decode offscreen so a previous generation cannot overwrite a newer frame.
      const decoded = new Image();
      decoded.src = newUrl;
      await decoded.decode();
      if (!playing || myGeneration !== generation) break;
      video.src = newUrl;
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = newUrl; newUrl = null;
      lastFetchMs = performance.now() - began;
      delivered++;
      frameTimes.push(performance.now());
      frameWidth = decoded.naturalWidth; frameHeight = decoded.naturalHeight;
      if (lastFetchMs > 700) { slowLink = true; quickFrames = 0; }
      else if (slowLink && lastFetchMs < 250) {
        if (++quickFrames >= 30) { slowLink = false; quickFrames = 0; }
      } else quickFrames = 0;
      state.textContent = '实时画面';
      updateDetail();
    } catch (error) {
      if (!playing || myGeneration !== generation) break;
      state.textContent = '画面中断，正在重连';
      slowLink = true; quickFrames = 0;
      detail.textContent = '保留最后一帧，正在重新获取实时画面。';
      await delay(500);
    } finally {
      clearTimeout(timeout);
      if (newUrl) URL.revokeObjectURL(newUrl);
      if (pending === controller) pending = null;
    }
    await delay(Math.max(0, 100 - (performance.now() - began)));
  }
}

function stop() {
  playing = false; generation++;
  if (pending) pending.abort();
  document.getElementById('toggle').textContent = '继续播放';
  state.textContent = '已暂停';
}

function start() {
  stop(); playing = true; generation++;
  delivered = 0; frameTimes = []; started = performance.now();
  document.getElementById('toggle').textContent = '暂停画面';
  state.textContent = '正在连接画面';
  pullFrames(generation);
}

document.getElementById('toggle').onclick = () => playing ? stop() : start();
document.getElementById('retry').onclick = start;
function transform() { video.style.transform = `rotate(${angle}deg) scaleX(${mirror})`; }
document.getElementById('mirror').onclick = () => { mirror *= -1; transform(); };
document.getElementById('rotate').onclick = () => { angle = (angle + 90) % 360; transform(); };
document.getElementById('full').onclick = () => document.getElementById('view').requestFullscreen?.();

async function status() {
  try {
    const response = await fetch('/status', {cache: 'no-store', signal: AbortSignal.timeout(8000)});
    const value = await response.json();
    if (response.ok && value.camera_ok) { camera = value; if (delivered) updateDetail(); }
    else if (playing) { state.textContent = '摄像头未连接'; }
  } catch (error) { if (playing) state.textContent = '正在恢复连接'; }
}
start(); status(); setInterval(status, 5000);
