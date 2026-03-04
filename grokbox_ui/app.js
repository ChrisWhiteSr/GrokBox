/* ===================================================================
   GrokBox Display — client JS
   Live: receives socket events from grokbox_server.py, updates UI
   =================================================================== */

// ---------------------------------------------------------------------------
// Socket.IO connection
// ---------------------------------------------------------------------------
const socket = io();

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const statusLabel   = document.getElementById('status-label');
const micIcon       = document.getElementById('mic-icon');
const userText      = document.getElementById('user-text');
const logDrawer     = document.getElementById('log-drawer');
const logLines      = document.getElementById('log-lines');
const imageOverlay  = document.getElementById('image-overlay');
const overlayImg    = document.getElementById('overlay-img');
const modelSelector = document.getElementById('model-selector');
const modelDropdown = document.getElementById('model-dropdown');
const modelName     = document.getElementById('model-name');
const scrim         = document.getElementById('conversation-scrim');

// ---------------------------------------------------------------------------
// State management
// ---------------------------------------------------------------------------
let currentState = 'listening';
let scrimTimeout = null;
let partialText = '';

// State → status label text
const STATE_LABELS = {
  listening:    'listening',
  triggered:    'wake word',
  transcribing: 'transcribing',
  querying:     'thinking',
  responding:   'speaking',
  paused:       'paused',
  idle:         'idle',
};

// State → mic icon behavior
function updateMicState(state) {
  micIcon.classList.remove('pulse', 'inactive');

  if (state === 'paused') {
    micIcon.classList.add('inactive');
  } else if (state === 'transcribing') {
    micIcon.classList.add('pulse');
  }
}

socket.on('state', (data) => {
  currentState = data.state;
  statusLabel.textContent = STATE_LABELS[data.state] || data.state;
  updateMicState(data.state);

  // Show scrim when triggered/transcribing
  if (data.state === 'triggered') {
    scrim.classList.remove('fade-out');
    scrim.classList.add('visible');
    userText.textContent = '';
    partialText = '';
    clearTimeout(scrimTimeout);
  }
});

// ---------------------------------------------------------------------------
// Transcript events (partial + final)
// ---------------------------------------------------------------------------
socket.on('transcript', (data) => {
  if (data.final) {
    userText.textContent = data.text;
    partialText = '';
  } else {
    // Build up partial text — the daemon sends deltas, accumulate them
    if (partialText) {
      partialText += ' ' + data.text;
    } else {
      partialText = data.text;
    }
    userText.textContent = partialText;
  }

  // Make sure scrim is visible
  scrim.classList.remove('fade-out');
  scrim.classList.add('visible');
  clearTimeout(scrimTimeout);
});

// ---------------------------------------------------------------------------
// Response events
// ---------------------------------------------------------------------------
socket.on('response', (data) => {
  // Show the response text on the right side of the scrim
  userText.innerHTML =
    '<span class="user-said">' + escapeHtml(userText.textContent.replace(/^.*$/, userText.textContent)) + '</span>' +
    '<span class="jarvis-said">' + escapeHtml(data.text) + '</span>';

  // Fade out scrim after 10 seconds
  clearTimeout(scrimTimeout);
  scrimTimeout = setTimeout(() => {
    scrim.classList.add('fade-out');
    setTimeout(() => {
      scrim.classList.remove('visible', 'fade-out');
    }, 2000);
  }, 10000);
});

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Image overlay
// ---------------------------------------------------------------------------
let imageTimeout = null;
socket.on('show_image', (data) => {
  // Images served from daemon are local paths — serve them through Flask
  overlayImg.src = '/tmp_image?path=' + encodeURIComponent(data.path);
  imageOverlay.classList.remove('hidden');
  // Auto-dismiss after 8 seconds so the background (which is now this image) shows through
  clearTimeout(imageTimeout);
  imageTimeout = setTimeout(() => closeImages(), 8000);
});

socket.on('close_images', () => {
  closeImages();
});

function closeImages() {
  imageOverlay.classList.add('hidden');
  overlayImg.src = '';
}

// ---------------------------------------------------------------------------
// Live stock ticker
// ---------------------------------------------------------------------------
const tickerContent = document.getElementById('ticker-content');

socket.on('tickers', (data) => {
  const items = data.map(t => {
    const dir = t.pct >= 0 ? 'up' : 'down';
    const sign = t.pct >= 0 ? '+' : '';
    return '<span class="ticker-item">' +
      '<span class="ticker-symbol">' + escapeHtml(t.symbol) + '</span>' +
      '<span class="ticker-price">$' + t.price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</span>' +
      '<span class="ticker-pct ' + dir + '">' + sign + t.pct.toFixed(2) + '%</span>' +
      '</span>';
  }).join('');
  // Duplicate so the scroll loops seamlessly
  tickerContent.innerHTML = items + items;
  // Set speed: ~60px/sec (CNBC pace)
  const halfWidth = tickerContent.scrollWidth / 2;
  const duration = halfWidth / 60;
  tickerContent.style.animationDuration = duration + 's';
});

// ---------------------------------------------------------------------------
// Spotify now-playing widget
// ---------------------------------------------------------------------------
const spotifyWidget = document.getElementById('spotify-widget');
const spotifyArt = document.getElementById('spotify-art');
const spotifyTrack = document.getElementById('spotify-track');
const spotifyArtist = document.getElementById('spotify-artist');
const spotifyAlbum = document.getElementById('spotify-album');
const spPlay = document.getElementById('sp-play');
let spotifyPlaying = false;

socket.on('spotify', (data) => {
  if (!data || !data.track) {
    spotifyWidget.classList.add('hidden');
    return;
  }
  spotifyWidget.classList.remove('hidden');
  spotifyArt.src = data.art_url || '';
  spotifyTrack.textContent = data.track;
  spotifyArtist.textContent = data.artist;
  spotifyAlbum.textContent = data.album;
  spotifyPlaying = data.is_playing;
  spPlay.innerHTML = data.is_playing ? '&#9208;' : '&#9654;';
});

document.getElementById('sp-prev').addEventListener('click', () => {
  fetch('/api/spotify/prev', { method: 'POST' });
});

spPlay.addEventListener('click', () => {
  fetch('/api/spotify/' + (spotifyPlaying ? 'pause' : 'play'), { method: 'POST' });
});

document.getElementById('sp-next').addEventListener('click', () => {
  fetch('/api/spotify/next', { method: 'POST' });
});

// ---------------------------------------------------------------------------
// Shield TV remote widget
// ---------------------------------------------------------------------------
const shieldWidget = document.getElementById('shield-widget');
const shieldPower = document.getElementById('shield-power');
const shieldAppLabel = document.getElementById('shield-app');

socket.on('shield', (data) => {
  if (!data) return;
  // Power indicator
  shieldPower.classList.remove('power-on', 'power-off');
  if (data.is_on === true) {
    shieldPower.classList.add('power-on');
  } else if (data.is_on === false) {
    shieldPower.classList.add('power-off');
  }
  // Current app label
  if (data.current_app) {
    shieldAppLabel.textContent = data.current_app.split('.').pop();
  } else {
    shieldAppLabel.textContent = '';
  }
});

shieldPower.addEventListener('click', () => {
  fetch('/api/shield/power', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'toggle' }),
  });
});

shieldWidget.querySelectorAll('.shield-app-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    fetch('/api/shield/launch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: btn.dataset.app }),
    });
  });
});

shieldWidget.querySelectorAll('.shield-key-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    fetch('/api/shield/key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: btn.dataset.key }),
    });
  });
});

// ---------------------------------------------------------------------------
// Live weather
// ---------------------------------------------------------------------------
const weatherWidget = document.getElementById('weather-widget');

socket.on('weather', (data) => {
  weatherWidget.innerHTML = data.map(d =>
    '<div class="wx-day">' +
      '<div class="wx-label">' + escapeHtml(d.day) + '</div>' +
      '<div class="wx-icon">' + d.icon + '</div>' +
      '<div class="wx-temp">' + d.high + '&deg;/<span class="temp-low">' + d.low + '&deg;</span></div>' +
    '</div>'
  ).join('');
});

// ---------------------------------------------------------------------------
// Log drawer
// ---------------------------------------------------------------------------
const MAX_LOG_LINES = 200;

socket.on('log', (data) => {
  const line = document.createElement('div');
  line.textContent = data.line;
  logLines.appendChild(line);

  // Trim old lines
  while (logLines.children.length > MAX_LOG_LINES) {
    logLines.removeChild(logLines.firstChild);
  }

  // Auto-scroll only when visible
  if (!logDrawer.classList.contains('hidden')) {
    logDrawer.scrollTop = logDrawer.scrollHeight;
  }
});

function toggleLogDrawer() {
  logDrawer.classList.toggle('hidden');
}

// ---------------------------------------------------------------------------
// Model selector dropdown (wired to server)
// ---------------------------------------------------------------------------
modelSelector.addEventListener('click', (e) => {
  e.stopPropagation();
  modelDropdown.classList.toggle('hidden');
});

document.addEventListener('click', () => {
  modelDropdown.classList.add('hidden');
});

modelDropdown.addEventListener('click', (e) => {
  if (e.target.classList.contains('dropdown-item')) {
    modelDropdown.querySelectorAll('.dropdown-item').forEach(el => el.classList.remove('active'));
    e.target.classList.add('active');

    const full = e.target.textContent;
    const short = full.replace('-non-reasoning', '').replace('-fast', '');
    modelName.textContent = short;

    modelDropdown.classList.add('hidden');

    // Persist model selection to server
    fetch('/api/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: full }),
    });
  }
});

// Load current model from server on startup
fetch('/api/model')
  .then(r => r.json())
  .then(data => {
    if (data.model) {
      const items = modelDropdown.querySelectorAll('.dropdown-item');
      items.forEach(el => {
        el.classList.remove('active');
        if (el.textContent === data.model) el.classList.add('active');
      });
      const short = data.model.replace('-non-reasoning', '').replace('-fast', '');
      modelName.textContent = short;
    }
  })
  .catch(() => {});

// ---------------------------------------------------------------------------
// Ticker settings panel
// ---------------------------------------------------------------------------
const tickerSettingsPanel = document.getElementById('ticker-settings-panel');
const tickerSymbolList = document.getElementById('ticker-symbol-list');
const tickerAddInput = document.getElementById('ticker-add-input');
const tickerAddBtn = document.getElementById('ticker-add-btn');
const tickerSaveBtn = document.getElementById('ticker-save-btn');
const tickerGear = document.getElementById('ticker-settings');

let tickerSymbols = [];

tickerGear.addEventListener('click', (e) => {
  e.stopPropagation();
  if (tickerSettingsPanel.classList.contains('hidden')) {
    // Open panel — fetch current symbols
    fetch('/api/ticker-symbols')
      .then(r => r.json())
      .then(data => {
        tickerSymbols = data.symbols || [];
        renderTickerList();
      });
    tickerSettingsPanel.classList.remove('hidden');
  } else {
    tickerSettingsPanel.classList.add('hidden');
  }
});

function renderTickerList() {
  tickerSymbolList.innerHTML = tickerSymbols.map((sym, i) =>
    '<li><span>' + escapeHtml(sym) + '</span>' +
    '<button class="ticker-remove-btn" data-idx="' + i + '">&times;</button></li>'
  ).join('');
}

tickerSymbolList.addEventListener('click', (e) => {
  if (e.target.classList.contains('ticker-remove-btn')) {
    const idx = parseInt(e.target.dataset.idx, 10);
    tickerSymbols.splice(idx, 1);
    renderTickerList();
  }
});

tickerAddBtn.addEventListener('click', () => {
  const val = tickerAddInput.value.trim().toUpperCase();
  if (val && !tickerSymbols.includes(val)) {
    tickerSymbols.push(val);
    renderTickerList();
    tickerAddInput.value = '';
  }
});

tickerAddInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') tickerAddBtn.click();
});

tickerSaveBtn.addEventListener('click', () => {
  fetch('/api/ticker-symbols', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols: tickerSymbols }),
  }).then(() => {
    tickerSettingsPanel.classList.add('hidden');
  });
});

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch (e.key) {
    case 'ArrowUp':
      e.preventDefault();
      fetch('/action/vol_up', { method: 'POST' });
      break;

    case 'ArrowDown':
      e.preventDefault();
      fetch('/action/vol_down', { method: 'POST' });
      break;

    case 'e':
    case 'E':
      fetch('/action/sink_external', { method: 'POST' });
      break;

    case 'm':
    case 'M':
      fetch('/action/sink_monitor', { method: 'POST' });
      break;

    case 'q':
    case 'Q':
      closeImages();
      break;

    case 'w':
    case 'W':
      fetch('/action/next_wallpaper', { method: 'POST' });
      break;

    case 'l':
    case 'L':
      toggleLogDrawer();
      break;

    case 'Escape':
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        document.documentElement.requestFullscreen();
      }
      break;
  }
});

// ---------------------------------------------------------------------------
// Ambient background — crossfade rotation via server wallpaper events
// ---------------------------------------------------------------------------
const ambientImages = document.querySelectorAll('.ambient-img');
let activeAmbient = 0;

// Start with default background
ambientImages[0].style.backgroundImage = "url('/wallpaper/current')";
ambientImages[0].classList.add('active');

// ---------------------------------------------------------------------------
// System health panel
// ---------------------------------------------------------------------------
const HEALTH_MAP = {
  'Daemon':      'h-daemon',
  'Kokoro TTS':  'h-kokoro',
  'xAI Grok':    'h-xai',
  'AssemblyAI':  'h-assemblyai',
  'PipeWire':    'h-pipewire',
  'BT Speaker':  'h-bt',
  'Raspotify':   'h-raspotify',
};

socket.on('health', (data) => {
  for (const [name, elemId] of Object.entries(HEALTH_MAP)) {
    const dot = document.getElementById(elemId);
    if (dot) {
      dot.classList.remove('up', 'down');
      if (data[name] === true) {
        dot.classList.add('up');
      } else if (data[name] === false) {
        dot.classList.add('down');
      }
    }
  }
});

// ---------------------------------------------------------------------------
// Clock — top center, updates every second with blinking colon
// ---------------------------------------------------------------------------
const clockTime = document.getElementById('clock-time');
const clockDate = document.getElementById('clock-date');

function updateClock() {
  const now = new Date();
  let h = now.getHours();
  const m = String(now.getMinutes()).padStart(2, '0');
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;

  // Blinking colon via CSS class
  const colon = '<span class="colon">:</span>';
  clockTime.innerHTML = h + colon + m + ' ' + ampm;

  // Date: "Thu, Feb 27"
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  clockDate.textContent = days[now.getDay()] + ', ' +
    months[now.getMonth()] + ' ' + now.getDate();
}

updateClock();
setInterval(updateClock, 1000);

socket.on('wallpaper', (data) => {
  // Crossfade: load new image into the inactive layer, then swap
  const next = 1 - activeAmbient;
  const img = new Image();
  img.onload = () => {
    ambientImages[next].style.backgroundImage = "url('" + data.url + "')";
    ambientImages[next].classList.add('active');
    ambientImages[activeAmbient].classList.remove('active');
    activeAmbient = next;
  };
  img.src = data.url;
});

