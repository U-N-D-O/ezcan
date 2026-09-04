const params = new URLSearchParams(window.location.search);
const token = params.get('token');
const mode = params.get('mode');
const desktopView = document.querySelector('#desktop-view');
const phoneView = document.querySelector('#phone-view');
const missingView = document.querySelector('#missing-view');
const connectionPill = document.querySelector('#connection-pill');
const saveLocation = document.querySelector('#save-location');

function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function setConnected() {
  connectionPill.textContent = 'Connected';
  connectionPill.classList.add('ready');
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes;
  let unit = -1;
  do { value /= 1024; unit += 1; } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function fileType(name) {
  const extension = name.split('.').pop();
  return extension && extension.length <= 5 ? extension : 'file';
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Request failed');
  return response.json();
}

function renderFiles(files) {
  const list = document.querySelector('#file-list');
  document.querySelector('#file-count').textContent = files.length;
  if (!files.length) {
    list.innerHTML = '<div class="empty-state">Nothing has arrived yet. The next file will appear here.</div>';
    return;
  }
  list.innerHTML = files.map((file) => `
    <article class="file-row">
      <span class="file-type">${fileType(file.name)}</span>
      <div class="file-info">
        <p class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</p>
        <p class="file-meta">${formatSize(file.size)} &middot; ${formatDate(file.receivedAt)}</p>
      </div>
    </article>`).join('');
}

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

async function loadDesktop() {
  try {
    const session = await requestJson('/api/session');
    document.querySelector('#phone-url').textContent = session.phoneUrl;
    saveLocation.textContent = session.receivedFolder;
    setConnected();
    await loadFiles();
    window.setInterval(loadFiles, 5000);
  } catch (error) {
    connectionPill.textContent = 'Link expired';
    document.querySelector('#phone-url').textContent = error.message;
  }
}

async function loadFiles() {
  const data = await requestJson('/api/files');
  renderFiles(data.files);
}

function uploadFile(file) {
  return new Promise((resolve) => {
    const row = document.createElement('div');
    row.className = 'upload-row';
    row.innerHTML = `<span class="upload-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span><div class="progress"><span></span></div><span class="upload-state">Sending</span>`;
    document.querySelector('#upload-list').prepend(row);
    const progress = row.querySelector('.progress span');
    const state = row.querySelector('.upload-state');
    const request = new XMLHttpRequest();
    request.open('POST', '/api/upload');
    request.setRequestHeader('Authorization', `Bearer ${token}`);
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) progress.style.width = `${(event.loaded / event.total) * 100}%`;
    });
    request.addEventListener('load', () => {
      if (request.status >= 200 && request.status < 300) {
        progress.style.width = '100%';
        state.textContent = 'Received';
        state.classList.add('done');
      } else {
        state.textContent = 'Failed';
        state.classList.add('error');
      }
      resolve();
    });
    request.addEventListener('error', () => {
      state.textContent = 'Failed';
      state.classList.add('error');
      resolve();
    });
    const form = new FormData();
    form.append('upload_file', file, file.name);
    request.send(form);
  });
}

function setupPhone() {
  setConnected();
  const input = document.querySelector('#file-input');
  const zone = document.querySelector('#drop-zone');
  input.addEventListener('change', () => uploadFiles(input.files));
  zone.addEventListener('dragover', (event) => { event.preventDefault(); zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    zone.classList.remove('dragging');
    uploadFiles(event.dataTransfer.files);
  });
}

async function uploadFiles(files) {
  for (const file of files) await uploadFile(file);
}

async function start() {
  if (!token) {
    missingView.hidden = false;
    connectionPill.textContent = 'No link';
    return;
  }
  if (mode === 'phone') {
    phoneView.hidden = false;
    setupPhone();
  } else {
    desktopView.hidden = false;
    await loadDesktop();
  }
}

document.querySelector('#copy-link').addEventListener('click', async () => {
  const link = document.querySelector('#phone-url').textContent;
  await navigator.clipboard.writeText(link);
  document.querySelector('#copy-link').textContent = 'Copied';
  window.setTimeout(() => { document.querySelector('#copy-link').textContent = 'Copy link'; }, 1600);
});
document.querySelector('#refresh-files').addEventListener('click', loadFiles);
start();
