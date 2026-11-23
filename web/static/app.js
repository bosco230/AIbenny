/* Benny & 叮當 web edition — page logic (no build step). */
"use strict";

const $ = (id) => document.getElementById(id);
const CHARACTERS = {
  benny: { name: "Benny" },
  dingdong: { name: "叮當" },
};
const state = {
  character: localStorage.getItem("character") || "benny",
  speaking: false,
  busy: false,
  voiceAvailable: false,
};

/* ----------------------------------------------------------- API helper */
async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  let data = {};
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const error = new Error(data.detail || `錯誤 ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}
const postJSON = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

/* -------------------------------------------------------------- avatars */
const Avatar = {
  img: null,
  blinkTimer: null,
  mouthTimer: null,
  holdTimer: null,
  face: "neutral",

  benny(folder, index) { return `/avatar/benny/${folder}/${String(index).padStart(3, "0")}.png`; },
  dingdong(face, level) { return `/avatar/dingdong/${face}/${String(level).padStart(3, "0")}.svg`; },

  preload() {
    const urls = [];
    for (let i = 0; i < 3; i++) urls.push(this.benny("idle", i));
    for (let i = 0; i < 4; i++) urls.push(this.benny("speaking", i));
    for (const face of ["neutral", "smile", "happy", "sad", "angry", "surprised", "worried", "thinking"]) {
      for (let l = 0; l < 4; l++) urls.push(this.dingdong(face, l));
    }
    urls.push("/avatar/dingdong/blink.svg", "/avatar/dingdong/smile_blink.svg");
    for (const url of urls) { const im = new Image(); im.src = url; }
  },

  /** LLM emotion -> 叮當 face (gentle joy smiles, big joy laughs). */
  faceFor(emotion, intensity) {
    switch (emotion) {
      case "happy": return intensity >= 0.6 ? "happy" : "smile";
      case "sad": return "sad";
      case "angry": return "angry";
      case "surprised": return "surprised";
      case "worried": return "worried";
      case "confused": case "focused": return "thinking";
      default: return "neutral";
    }
  },

  show(level = 0) {
    if (state.character === "benny") {
      this.img.src = state.speaking ? this.benny("speaking", level) : this.benny("idle", 0);
      this.img.alt = "Benny";
    } else {
      this.img.src = this.dingdong(this.face, state.speaking ? level : 0);
      this.img.alt = `叮當（${this.face}）`;
    }
  },

  startBlinking() {
    clearTimeout(this.blinkTimer);
    const loop = () => {
      this.blinkTimer = setTimeout(() => {
        if (!state.speaking) {
          if (state.character === "benny") {
            this.img.src = this.benny("idle", 1);
            setTimeout(() => { if (!state.speaking) this.img.src = this.benny("idle", 2); }, 80);
            setTimeout(() => { if (!state.speaking) this.show(); }, 180);
          } else if (this.face === "neutral" || this.face === "smile") {
            this.img.src = this.face === "smile" ? "/avatar/dingdong/smile_blink.svg" : "/avatar/dingdong/blink.svg";
            setTimeout(() => { if (!state.speaking) this.show(); }, 130);
          }
        }
        loop();
      }, 2800 + Math.random() * 3200);
    };
    loop();
  },

  setEmotion(emotion, intensity) {
    clearTimeout(this.holdTimer);
    this.face = this.faceFor(emotion, intensity);
  },

  relaxLater() {
    clearTimeout(this.holdTimer);
    this.holdTimer = setTimeout(() => { this.face = "neutral"; if (!state.speaking) this.show(); }, 4000);
  },

  /** Lip-sync from server RMS frames, timed against the audio clock. */
  speakWithAudio(audio, frames, windowMs) {
    state.speaking = true;
    clearInterval(this.mouthTimer);
    this.mouthTimer = setInterval(() => {
      const index = Math.floor((audio.currentTime * 1000) / windowMs);
      this.show(frames[index] ?? 0);
    }, 40);
  },

  /** No voice: a short natural talking loop sized to the reply. */
  speakWithoutAudio(text) {
    state.speaking = true;
    clearInterval(this.mouthTimer);
    this.mouthTimer = setInterval(() => this.show(1 + Math.floor(Math.random() * 3)), 110);
    return new Promise((resolve) => setTimeout(resolve, Math.min(6000, 400 + text.length * 90)));
  },

  stopSpeaking() {
    clearInterval(this.mouthTimer);
    state.speaking = false;
    this.show();
    this.relaxLater();
  },
};

/* ----------------------------------------------------------------- chat */
function addMessage(kind, text, who) {
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  if (who) {
    const name = document.createElement("span");
    name.className = "who";
    name.textContent = who;
    div.append(name);
  }
  div.append(document.createTextNode(text));
  $("log").append(div);
  $("log").scrollTop = $("log").scrollHeight;
}

function setStatus(text) { $("status").textContent = text; }

/* One reused <audio>: iPhone Safari only lets an element play later if it
   was first started from a tap, so the first tap "unlocks" it. */
const player = new Audio();
const SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
let audioUnlocked = false;
function unlockAudio() {
  if (audioUnlocked) return;
  audioUnlocked = true;
  player.src = SILENCE;
  player.play().then(() => player.pause()).catch(() => { audioUnlocked = false; });
}

let currentAudio = null;
async function speak(text) {
  if (!$("voice").checked || !state.voiceAvailable) {
    await Avatar.speakWithoutAudio(text);
    Avatar.stopSpeaking();
    return;
  }
  try {
    const voice = await postJSON("/api/speak", { text, character: state.character });
    const audio = player;
    audio.src = voice.audio;
    currentAudio = audio;
    await new Promise((resolve) => {
      audio.addEventListener("ended", resolve, { once: true });
      audio.addEventListener("error", resolve, { once: true });
      audio.addEventListener("playing", () => Avatar.speakWithAudio(audio, voice.frames, voice.window_ms), { once: true });
      audio.play().catch(resolve);
    });
  } catch (error) {
    addMessage("system", error.message);
    await Avatar.speakWithoutAudio(text);
  } finally {
    currentAudio = null;
    Avatar.stopSpeaking();
  }
}

async function send(text) {
  text = text.trim();
  if (!text || state.busy) return;
  state.busy = true;
  $("send").disabled = true;
  if (currentAudio) currentAudio.pause();
  addMessage("me", text);
  setStatus("諗緊……");
  if (state.character === "dingdong") { Avatar.face = "thinking"; Avatar.show(); }
  try {
    const result = await postJSON("/api/chat", { text, character: state.character });
    addMessage("them", result.reply, CHARACTERS[result.character].name);
    $("bubble").textContent = result.reply;
    $("bubble").hidden = false;
    Avatar.setEmotion(result.emotion, result.intensity);
    setStatus("講緊……");
    await speak(result.reply);
  } catch (error) {
    if (error.status === 401) return showLogin();
    Avatar.face = "neutral"; Avatar.show();
    addMessage("system", error.message);
  } finally {
    state.busy = false;
    $("send").disabled = false;
    setStatus("準備好");
    setTimeout(() => { $("bubble").hidden = true; }, 6000);
  }
}

function switchCharacter() {
  if (state.busy) return;
  if (currentAudio) currentAudio.pause();
  state.character = state.character === "benny" ? "dingdong" : "benny";
  localStorage.setItem("character", state.character);
  Avatar.face = "neutral";
  Avatar.stopSpeaking();
  $("char-name").textContent = CHARACTERS[state.character].name;
  addMessage("system", `而家同 ${CHARACTERS[state.character].name} 傾偈`);
}

/* ------------------------------------------- microphone -> 16 kHz WAV */
const Recorder = {
  context: null, stream: null, node: null, chunks: [], timer: null, rate: 48000,

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    this.context = new AudioContext();
    this.rate = this.context.sampleRate;
    const source = this.context.createMediaStreamSource(this.stream);
    this.node = this.context.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.node.onaudioprocess = (event) => this.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    source.connect(this.node);
    this.node.connect(this.context.destination);
    this.timer = setTimeout(() => stopRecording(), 15000);  // max 15 s per message
  },

  async stop() {
    clearTimeout(this.timer);
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.context?.close();
    const length = this.chunks.reduce((n, c) => n + c.length, 0);
    const input = new Float32Array(length);
    let offset = 0;
    for (const chunk of this.chunks) { input.set(chunk, offset); offset += chunk.length; }
    return encodeWav(downsample(input, this.rate, 16000), 16000);
  },
};

function downsample(input, from, to) {
  if (from === to) return input;
  const ratio = from / to;
  const output = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < output.length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return output;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

let recording = false;
async function startRecording() {
  if (recording || state.busy) return;
  try {
    await Recorder.start();
    recording = true;
    $("mic").classList.add("recording");
    setStatus("聽緊……放手就傳送");
  } catch {
    addMessage("system", "用唔到咪高峰，請檢查瀏覽器權限。");
  }
}
async function stopRecording() {
  if (!recording) return;
  recording = false;
  $("mic").classList.remove("recording");
  setStatus("認緊你講咩……");
  try {
    const wav = await Recorder.stop();
    if (wav.size < 16000) { setStatus("準備好"); return; }  // < 0.5 s: ignore
    const result = await api("/api/listen", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
    setStatus("準備好");
    if (result.text) await send(result.text);
    else addMessage("system", "聽唔清楚，可唔可以再講一次？");
  } catch (error) {
    setStatus("準備好");
    addMessage("system", error.message);
  }
}

/* ------------------------------------------------------------- startup */
function showLogin() {
  $("app").hidden = true;
  $("login").hidden = false;
  $("passcode").focus();
}

async function showApp() {
  const me = await api("/api/me");
  state.voiceAvailable = Boolean(me.voice);
  $("voice").checked = state.voiceAvailable && localStorage.getItem("voice") !== "off";
  $("voice").disabled = !state.voiceAvailable;
  $("mic").hidden = !state.voiceAvailable;
  $("login").hidden = true;
  $("app").hidden = false;
  $("char-name").textContent = CHARACTERS[state.character].name;
  Avatar.show();
  if (!$("log").childElementCount) {
    addMessage("system", "可以打字或者按住 🎤 講嘢；按 Esc 或者上面個掣可以換角色。");
  }
  $("text").focus();
}

function bind() {
  for (const type of ["pointerdown", "keydown", "touchend"]) {
    window.addEventListener(type, unlockAudio, { passive: true });
  }
  Avatar.img = $("avatar");
  Avatar.preload();
  Avatar.startBlinking();

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("login-error").textContent = "";
    try {
      await postJSON("/api/login", { passcode: $("passcode").value });
      $("passcode").value = "";
      await showApp();
    } catch (error) {
      $("login-error").textContent = error.message;
    }
  });
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("text").value;
    $("text").value = "";
    send(text);
  });
  $("switch").addEventListener("click", switchCharacter);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.repeat && !event.ctrlKey && !event.altKey && !event.metaKey) {
      event.preventDefault();
      switchCharacter();
    }
  });
  const mic = $("mic");
  mic.addEventListener("pointerdown", (event) => { event.preventDefault(); startRecording(); });
  mic.addEventListener("pointerup", stopRecording);
  mic.addEventListener("pointerleave", stopRecording);
  $("voice").addEventListener("change", () => localStorage.setItem("voice", $("voice").checked ? "on" : "off"));
  $("forget").addEventListener("click", async () => {
    if (!confirm("清除 Benny 同叮當記得你嘅所有嘢？呢個動作冇得還原。")) return;
    await api("/api/forget", { method: "POST" });
    $("log").replaceChildren();
    addMessage("system", "已經清除晒你嘅記憶。");
  });
  $("logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    $("log").replaceChildren();
    showLogin();
  });
}

bind();
api("/api/me").then(showApp).catch(showLogin);
