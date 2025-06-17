let progress = 0;
let progressInterval = null;
let dotCount = 0;
let dotInterval = null;

function simulateProgressBar() {
  const progressBar = document.getElementById("progressBar");
  if (progress < 95) {
    progress += Math.random() * 2 + 1;
    progressBar.style.width = `${Math.min(progress, 95)}%`;
  }
}

function startDotAnimation() {
  const statusText = document.getElementById("status");
  dotInterval = setInterval(() => {
    dotCount = (dotCount + 1) % 4;
    statusText.innerText = "⏳ Downloading" + ".".repeat(dotCount);
  }, 500);
}

function stopDotAnimation() {
  clearInterval(dotInterval);
  dotCount = 0;
}

async function startDownload() {
  const url = document.getElementById("url").value;
  const format = document.querySelector('input[name="format"]:checked').value;
  const statusText = document.getElementById("status");
  const progressContainer = document.getElementById("progressContainer");
  const progressBar = document.getElementById("progressBar");

  if (!url) {
    alert("Please enter a video URL.");
    return;
  }

  statusText.innerText = "Starting download...";
  startDotAnimation();
  progress = 0;
  progressBar.style.width = "0%";
  progressContainer.style.display = "block";

  try {
    const response = await fetch("/start-download", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ url: url, format: format })
    });

    const data = await response.json();
    progressInterval = setInterval(simulateProgressBar, 700);
    checkStatus(data.file_id);
  } catch (err) {
    stopDotAnimation();
    clearInterval(progressInterval);
    progressContainer.style.display = "none";
    statusText.innerText = "❌ Error starting download.";
  }
}

async function checkStatus(file_id) {
  const statusText = document.getElementById("status");
  const progressContainer = document.getElementById("progressContainer");

  try {
    const res = await fetch(`/status/${file_id}`);
    const data = await res.json();

    if (data.status === "done") {
      stopDotAnimation();
      clearInterval(progressInterval);
      document.getElementById("progressBar").style.width = "100%";
      statusText.innerHTML = `
        <a class="download-btn" style="text-decoration:none;" href="/download/${data.file}" download>Download video</a>`;
    } else if (data.status === "error") {
      stopDotAnimation();
      clearInterval(progressInterval);
      progressContainer.style.display = "none";
      statusText.innerText = "❌ Download failed.";
    } else {
      setTimeout(() => checkStatus(file_id), 1500);
    }
  } catch (err) {
    stopDotAnimation();
    clearInterval(progressInterval);
    progressContainer.style.display = "none";
    statusText.innerText = "⚠️ Error checking status.";
  }
}

function handleSearchKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    startDownload();
  }
}