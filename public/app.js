const form = document.querySelector("#downloadForm");
const urlsInput = document.querySelector("#urls");
const browserInput = document.querySelector("#browser");
const startButton = document.querySelector("#startButton");
const statusList = document.querySelector("#statusList");
const fileList = document.querySelector("#fileList");
const jobStatus = document.querySelector("#jobStatus");
const refreshFiles = document.querySelector("#refreshFiles");
const downloadDir = document.querySelector("#downloadDir");

let pollTimer = null;

function linesToUrls(value) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function setStatus(text) {
  jobStatus.textContent = text;
}

function renderJob(job) {
  setStatus(job.status || "Sin trabajo");

  if (!job.items || !job.items.length) {
    statusList.className = "status-list empty";
    statusList.textContent = "Pega enlaces y empieza una descarga.";
    return;
  }

  statusList.className = "status-list";
  statusList.innerHTML = "";

  job.items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "item";

    const head = document.createElement("div");
    head.className = "item-head";

    const url = document.createElement("div");
    url.className = "url";
    url.textContent = item.url;

    const state = document.createElement("span");
    state.className = `state ${item.status}`;
    state.textContent = item.status;

    const message = document.createElement("div");
    message.className = "message";
    message.textContent = item.file ? `${item.message}: ${item.file}` : item.message;

    if (item.downloadUrl) {
      const link = document.createElement("a");
      link.className = "download-link";
      link.href = item.downloadUrl;
      link.download = "";
      link.textContent = "Descargar MP4";
      message.append(document.createElement("br"), link);
    }

    head.append(url, state);
    row.append(head, message);
    statusList.append(row);
  });
}

function renderFiles(payload) {
  downloadDir.textContent = payload.downloadDir || "";
  const files = payload.files || [];

  if (!files.length) {
    fileList.className = "file-list empty";
    fileList.textContent = "Todavia no hay archivos descargados.";
    return;
  }

  fileList.className = "file-list";
  fileList.innerHTML = "";

  files.forEach((file) => {
    const row = document.createElement("article");
    row.className = "item";

    const name = document.createElement(file.Url ? "a" : "div");
    name.className = "file-name";
    name.textContent = file.Name;
    if (file.Url) {
      name.href = file.Url;
      name.download = "";
    }

    const size = document.createElement("div");
    size.className = "file-meta";
    size.textContent = `${formatBytes(file.Length)} · ${new Date(file.LastWriteTime).toLocaleString()}`;

    row.append(name, size);
    fileList.append(row);
  });
}

function formatBytes(bytes) {
  if (!Number(bytes)) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(bytes);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

async function refreshDownloadList() {
  const response = await fetch("/api/downloads");
  renderFiles(await response.json());
}

async function pollJob(jobId) {
  let job;
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    job = await response.json();
    if (!response.ok) {
      throw new Error(job.error || "No se pudo consultar el estado.");
    }
  } catch (error) {
    clearInterval(pollTimer);
    pollTimer = null;
    setStatus("Error");
    statusList.className = "status-list empty";
    statusList.textContent = error.message;
    startButton.disabled = false;
    startButton.textContent = "Descargar";
    return;
  }

  renderJob(job);

  if (["done", "finished_with_errors"].includes(job.status)) {
    clearInterval(pollTimer);
    pollTimer = null;
    startButton.disabled = false;
    startButton.textContent = "Descargar";
    await refreshDownloadList();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const urls = linesToUrls(urlsInput.value);

  if (!urls.length) {
    setStatus("Pega enlaces");
    urlsInput.focus();
    return;
  }

  startButton.disabled = true;
  startButton.textContent = "Iniciando";
  setStatus("Enviando");

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls, browser: browserInput.value }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "No se pudo iniciar la descarga.");
    }

    renderJob(payload);
    await pollJob(payload.id);
    pollTimer = setInterval(() => pollJob(payload.id), 1800);
    startButton.textContent = "Descargando";
  } catch (error) {
    setStatus("Error");
    statusList.className = "status-list empty";
    statusList.textContent = error.message;
    startButton.disabled = false;
    startButton.textContent = "Descargar";
  }
});

refreshFiles.addEventListener("click", refreshDownloadList);
refreshDownloadList();
