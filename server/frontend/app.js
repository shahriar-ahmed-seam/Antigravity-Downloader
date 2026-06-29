// State Management
let activeJobId = null;
let eventSource = null;
let currentNovelId = null;
let libraryData = [];
let novelChaptersList = [];

// DOM Elements
const novelUrlInput = document.getElementById('novel-url');
const novelIdOverrideInput = document.getElementById('novel-id-override');
const btnCheckToken = document.getElementById('btn-check-token');
const tokenIndicator = document.getElementById('token-status-indicator');
const tokenPreviewText = document.getElementById('token-preview-text');
const btnFetchInfo = document.getElementById('btn-fetch-info');

const loadedBookCard = document.getElementById('loaded-book-card');
const bookMetaCover = document.getElementById('book-meta-cover');
const bookMetaTitle = document.getElementById('book-meta-title');
const bookMetaAuthor = document.getElementById('book-meta-author');
const bookMetaStatus = document.getElementById('book-meta-status');
const totalChaptersLbl = document.getElementById('total-chapters-lbl');

const startChapterInput = document.getElementById('start-chapter');
const endChapterInput = document.getElementById('end-chapter');
const startChapterTitle = document.getElementById('start-chapter-title');
const endChapterTitle = document.getElementById('end-chapter-title');
const optRenumber = document.getElementById('opt-renumber');
const optHighlight = document.getElementById('opt-highlight');
const optForce = document.getElementById('opt-force');

const downloadForm = document.getElementById('download-form');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const taskStatusText = document.getElementById('task-status-text');
const chaptersFetchedText = document.getElementById('chapters-fetched-text');
const etaContainer = document.getElementById('eta-container');
const etaText = document.getElementById('eta-text');

const jobControls = document.getElementById('job-controls');
const btnPauseJob = document.getElementById('btn-pause-job');
const btnResumeJob = document.getElementById('btn-resume-job');
const btnAbortJob = document.getElementById('btn-abort-job');

const consoleLogs = document.getElementById('console-logs');
const btnClearLogs = document.getElementById('btn-clear-logs');
const libraryGrid = document.getElementById('library-grid');

// API Helpers
async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    if (body) {
        options.body = JSON.stringify(body);
    }
    
    const response = await fetch(endpoint, options);
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `API error: ${response.statusText}`);
    }
    return response.json();
}

// Log writer for the console GUI
function writeConsole(message, level = 'info') {
    const timeStr = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = `log-line ${level}`;
    line.innerHTML = `<span class="time" style="color: var(--text-dark); margin-right: 0.5rem;">[${timeStr}]</span> ${message}`;
    consoleLogs.appendChild(line);
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

// Token Status — loaded from server config, not user input
async function loadTokenStatus() {
    try {
        const config = await apiCall('/api/config');
        
        if (!config.token_loaded) {
            tokenIndicator.className = 'token-status-badge invalid';
            tokenIndicator.querySelector('.status-text').textContent = 'Not Configured';
            tokenPreviewText.textContent = 'No token in .env — please add FICTIONZONE_TOKEN';
            writeConsole('No token configured in .env file. Edit .env and restart the server.', 'error');
            return;
        }

        // Show preview (non-sensitive)
        tokenPreviewText.textContent = config.token_preview || '';

        if (config.expired) {
            tokenIndicator.className = 'token-status-badge invalid';
            tokenIndicator.querySelector('.status-text').textContent = 'Expired';
            writeConsole('Token in .env has expired. Get a fresh token and update .env, then restart the server.', 'error');
        } else {
            // Optimistically show valid — full gateway probe happens on Verify click
            tokenIndicator.className = 'token-status-badge valid';
            tokenIndicator.querySelector('.status-text').textContent = 'Loaded';
            const expTs = config.expires_at;
            if (expTs) {
                const expDate = new Date(expTs * 1000);
                writeConsole(`Token loaded from .env. Expires: ${expDate.toLocaleString()}`, 'success');
            } else {
                writeConsole('Token loaded from .env.', 'success');
            }
        }
    } catch (err) {
        tokenIndicator.className = 'token-status-badge invalid';
        tokenIndicator.querySelector('.status-text').textContent = 'Error';
        writeConsole(`Could not load server config: ${err.message}`, 'error');
    }
}

// Live gateway probe — verifies the token is accepted by the FictionZone API
async function verifyToken() {
    tokenIndicator.className = 'token-status-badge checking';
    tokenIndicator.querySelector('.status-text').textContent = 'Checking...';
    btnCheckToken.disabled = true;
    
    try {
        const res = await apiCall('/api/check-token', 'POST');
        if (res.valid) {
            tokenIndicator.className = 'token-status-badge valid';
            tokenIndicator.querySelector('.status-text').textContent = 'Valid ✓';
            writeConsole('Token verified: gateway accepted the auth token. Full content access confirmed.', 'success');
        } else {
            tokenIndicator.className = 'token-status-badge invalid';
            tokenIndicator.querySelector('.status-text').textContent = 'Invalid/Expired';
            writeConsole(`Token check failed: ${res.error}`, 'error');
        }
    } catch (err) {
        tokenIndicator.className = 'token-status-badge invalid';
        tokenIndicator.querySelector('.status-text').textContent = 'Error';
        writeConsole(`Token verification request failed: ${err.message}`, 'warn');
    } finally {
        btnCheckToken.disabled = false;
    }
}

btnCheckToken.addEventListener('click', verifyToken);

// Save URL setting to LocalStorage so inputs are preserved on refresh
function persistSettings() {
    localStorage.setItem('fictionzone_url', novelUrlInput.value);
    localStorage.setItem('fictionzone_override_id', novelIdOverrideInput.value);
}

function loadSettings() {
    const cachedUrl = localStorage.getItem('fictionzone_url');
    const cachedOverrideId = localStorage.getItem('fictionzone_override_id');
    if (cachedUrl) novelUrlInput.value = cachedUrl;
    if (cachedOverrideId) novelIdOverrideInput.value = cachedOverrideId;
}

// Analyze Novel Page Meta
btnFetchInfo.addEventListener('click', async () => {
    const url = novelUrlInput.value;

    if (!url) {
        writeConsole("Please fill out the Novel URL field before analyzing.", "warn");
        return;
    }

    persistSettings();
    writeConsole(`Analyzing novel metadata from landing page...`);
    btnFetchInfo.disabled = true;
    btnFetchInfo.textContent = "Analyzing...";

    try {
        const reqBody = { url };
        if (novelIdOverrideInput.value.trim()) {
            reqBody.novel_id = novelIdOverrideInput.value.trim();
        }
        const data = await apiCall('/api/novel/info', 'POST', reqBody);
        currentNovelId = data.novel_id;
        
        // Populate inputs
        bookMetaTitle.textContent = data.metadata.title;
        bookMetaAuthor.textContent = data.metadata.author || "Unknown";
        bookMetaStatus.textContent = data.metadata.status || "Ongoing";
        bookMetaStatus.className = `status-tag ${data.metadata.status === 'Completed' ? 'btn-success' : ''}`;
        
        // Show Cover
        if (data.metadata.cover_url) {
            bookMetaCover.src = data.metadata.cover_url;
            bookMetaCover.classList.remove('hidden');
        } else {
            bookMetaCover.classList.add('hidden');
        }

        totalChaptersLbl.textContent = data.total_chapters;
        startChapterInput.value = 1;
        endChapterInput.value = data.total_chapters;
        startChapterInput.max = data.total_chapters;
        endChapterInput.max = data.total_chapters;

        novelChaptersList = data.chapters || [];
        updateChapterTitles();

        // Reveal card
        loadedBookCard.classList.remove('hidden');
        writeConsole(`Analysis completed! Novel ID: ${currentNovelId}. Total chapters indexed: ${data.total_chapters}.`, "success");
        
    } catch (err) {
        writeConsole(`Analysis failed: ${err.message}`, "error");
    } finally {
        btnFetchInfo.disabled = false;
        btnFetchInfo.textContent = "Analyze Novel";
    }
});

function updateChapterTitles() {
    if (!novelChaptersList || novelChaptersList.length === 0) {
        startChapterTitle.textContent = '';
        endChapterTitle.textContent = '';
        return;
    }
    
    const startIdx = parseInt(startChapterInput.value) || 1;
    const endIdx = parseInt(endChapterInput.value) || 1;
    
    const startChap = novelChaptersList.find(c => c.idx === startIdx) || novelChaptersList[startIdx - 1];
    const endChap = novelChaptersList.find(c => c.idx === endIdx) || novelChaptersList[endIdx - 1];
    
    startChapterTitle.textContent = startChap ? startChap.title : '';
    endChapterTitle.textContent = endChap ? endChap.title : '';
}

startChapterInput.addEventListener('input', updateChapterTitles);
endChapterInput.addEventListener('input', updateChapterTitles);

// Start Downloader Job
downloadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentNovelId) return;

    persistSettings();
    const start_chapter = parseInt(startChapterInput.value) || 1;
    const end_chapter = parseInt(endChapterInput.value) || null;
    const renumber = optRenumber.checked;
    const highlight = optHighlight.checked;
    const force = optForce.checked;

    writeConsole(`Submitting download task request to the worker queue...`);
    
    // Reset Progress panel
    progressBar.style.width = '0%';
    progressText.textContent = '0%';
    taskStatusText.textContent = 'Queued';
    chaptersFetchedText.textContent = '0 / 0';
    progressContainer.classList.remove('inactive');
    jobControls.classList.remove('hidden');
    btnPauseJob.classList.remove('hidden');
    btnResumeJob.classList.add('hidden');
    
    try {
        const job = await apiCall('/api/download/start', 'POST', {
            novel_id: currentNovelId,
            start_chapter,
            end_chapter,
            renumber,
            highlight,
            force
        });

        activeJobId = job.job_id;
        connectSSE(activeJobId);
    } catch (err) {
        writeConsole(`Failed to start download job: ${err.message}`, 'error');
        taskStatusText.textContent = 'Error';
    }
});

// SSE EventSource Streams
let lastProgressTime = null;
let lastProgressCount = 0;

function connectSSE(jobId) {
    if (eventSource) {
        eventSource.close();
    }
    
    lastProgressTime = null;
    lastProgressCount = 0;
    
    writeConsole(`Connecting EventSource stream to job: ${jobId}`);
    eventSource = new EventSource(`/api/download/stream/${jobId}`);

    eventSource.addEventListener('status', (e) => {
        const payload = JSON.parse(e.data);
        const status = payload.status;
        taskStatusText.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        
        if (status === 'completed') {
            writeConsole("Scraper completed all tasks successfully!", "success");
            jobControls.classList.add('hidden');
            etaContainer.classList.add('hidden');
            eventSource.close();
            loadLibrary();
        } else if (status === 'failed') {
            writeConsole(`Scraper aborted: ${payload.error || 'Job failed'}`, "error");
            jobControls.classList.add('hidden');
            etaContainer.classList.add('hidden');
            eventSource.close();
        } else if (status === 'aborted') {
            writeConsole(`Job aborted by user request.`, "warn");
            jobControls.classList.add('hidden');
            etaContainer.classList.add('hidden');
            eventSource.close();
        }
    });

    eventSource.addEventListener('progress', (e) => {
        const payload = JSON.parse(e.data);
        const percent = payload.percentage || 0;
        
        progressBar.style.width = `${percent}%`;
        progressText.textContent = `${percent}%`;
        
        const completed = payload.completed || 0;
        const total = payload.total || 0;
        chaptersFetchedText.textContent = `${completed} / ${total} (Cached skipped: ${payload.skipped || 0})`;

        // Calculate simple ETA based on download rates
        if (completed > lastProgressCount) {
            const now = Date.now();
            if (lastProgressTime) {
                const diffTime = (now - lastProgressTime) / 1000; // seconds
                const diffChapters = completed - lastProgressCount;
                const timePerChapter = diffTime / diffChapters;
                const chaptersLeft = total - completed;
                const etaSeconds = Math.round(chaptersLeft * timePerChapter);
                
                etaContainer.classList.remove('hidden');
                if (etaSeconds > 60) {
                    const mins = Math.floor(etaSeconds / 60);
                    const secs = etaSeconds % 60;
                    etaText.textContent = `${mins}m ${secs}s`;
                } else {
                    etaText.textContent = `${etaSeconds}s`;
                }
            }
            lastProgressTime = now;
            lastProgressCount = completed;
        }
    });

    eventSource.addEventListener('log', (e) => {
        const payload = JSON.parse(e.data);
        writeConsole(payload.message, payload.level);
    });

    eventSource.onerror = (err) => {
        console.error("SSE stream error connection lost.");
        writeConsole("SSE Connection lost. Attempting to reconnect...", "warn");
    };
}

// Scraper Control API bindings
btnPauseJob.addEventListener('click', async () => {
    if (!activeJobId) return;
    try {
        await apiCall(`/api/download/pause/${activeJobId}`, 'POST');
        btnPauseJob.classList.add('hidden');
        btnResumeJob.classList.remove('hidden');
        writeConsole("Scraper pause requested.");
    } catch (err) {
        writeConsole(`Failed to pause scraper: ${err.message}`, 'error');
    }
});

btnResumeJob.addEventListener('click', async () => {
    if (!activeJobId) return;
    try {
        await apiCall(`/api/download/resume/${activeJobId}`, 'POST');
        btnResumeJob.classList.add('hidden');
        btnPauseJob.classList.remove('hidden');
        writeConsole("Scraper resume requested.");
    } catch (err) {
        writeConsole(`Failed to resume scraper: ${err.message}`, 'error');
    }
});

btnAbortJob.addEventListener('click', async () => {
    if (!activeJobId) return;
    if (!confirm("Are you sure you want to stop the downloader execution loop?")) return;
    try {
        await apiCall(`/api/download/abort/${activeJobId}`, 'POST');
        writeConsole("Scraper abort command sent.");
    } catch (err) {
        writeConsole(`Failed to abort scraper: ${err.message}`, 'error');
    }
});

btnClearLogs.addEventListener('click', () => {
    consoleLogs.innerHTML = '';
});

// Library List & Shelf Rendering
async function loadLibrary() {
    try {
        libraryData = await apiCall('/api/library');
        renderLibrary();
    } catch (err) {
        writeConsole(`Failed to load book shelf library: ${err.message}`, 'error');
    }
}

function renderLibrary() {
    libraryGrid.innerHTML = '';
    
    if (libraryData.length === 0) {
        libraryGrid.innerHTML = `
            <div class="empty-library">
                <span>📚 Your local book shelf is currently empty. Start a download above!</span>
            </div>
        `;
        return;
    }

    libraryData.forEach((book) => {
        const card = document.createElement('div');
        card.className = 'book-card';
        
        // Resolve cover image or fallback
        let coverSrc = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="75" height="105" viewBox="0 0 75 105"><rect width="100%" height="100%" fill="%23242730"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="%234b5563" font-size="12" font-family="sans-serif">No Cover</text></svg>';
        if (book.metadata.cover_url) {
            coverSrc = book.metadata.cover_url;
        }

        const downloaded = book.downloaded_chapters;
        const total = book.total_chapters;
        
        card.innerHTML = `
            <img class="book-card-cover" src="${coverSrc}" alt="${book.metadata.title}">
            <div class="book-card-details">
                <div>
                    <h3 title="${book.metadata.title}">${book.metadata.title}</h3>
                    <p class="author" title="By ${book.metadata.author}">By ${book.metadata.author}</p>
                    <p class="stats">Downloaded: <strong>${downloaded} / ${total}</strong></p>
                </div>
                <div class="book-card-actions">
                    ${book.epub_filename ? `
                        <a href="/api/library/${book.novel_id}/epub" class="btn btn-primary btn-sm" download>
                            Download EPUB
                        </a>
                    ` : `
                        <button class="btn btn-warning btn-sm btn-compile" data-id="${book.novel_id}">
                            Compile EPUB
                        </button>
                    `}
                    <button class="btn btn-secondary btn-sm btn-icon-only btn-recompile" title="Force Recompile" data-id="${book.novel_id}">
                        ⚙️
                    </button>
                    <button class="btn btn-danger btn-sm btn-icon-only btn-delete" title="Delete" data-id="${book.novel_id}">
                        🗑️
                    </button>
                </div>
            </div>
        `;

        // Action bindings
        card.querySelector('.btn-delete').addEventListener('click', async (e) => {
            const id = e.currentTarget.dataset.id;
            if (confirm("Are you sure you want to delete this novel and all its cached files?")) {
                try {
                    await apiCall(`/api/library/${id}`, 'DELETE');
                    writeConsole(`Successfully deleted novel ID ${id} cache folder.`, "success");
                    loadLibrary();
                } catch (err) {
                    writeConsole(`Delete failed: ${err.message}`, 'error');
                }
            }
        });

        // Trigger manual compilation
        const compileBtn = card.querySelector('.btn-compile');
        if (compileBtn) {
            compileBtn.addEventListener('click', (e) => triggerCompile(e.currentTarget.dataset.id));
        }

        card.querySelector('.btn-recompile').addEventListener('click', (e) => {
            const id = e.currentTarget.dataset.id;
            const start = prompt("Range compile: Enter start chapter number (or leave blank for all):", "1");
            if (start === null) return;
            const end = prompt("Enter end chapter number (or leave blank for all):");
            if (end === null) return;
            
            const body = {};
            if (start.trim()) body.start_chapter = parseInt(start);
            if (end.trim()) body.end_chapter = parseInt(end);
            
            triggerCompile(id, body);
        });

        libraryGrid.appendChild(card);
    });
}

async function triggerCompile(novelId, body = {}) {
    writeConsole(`Manually initiating EPUB compilation for book ID: ${novelId}...`);
    try {
        const res = await apiCall(`/api/library/${novelId}/compile`, 'POST', body);
        writeConsole(`Compilation completed: ${res.epub_file}`, "success");
        loadLibrary();
    } catch (err) {
        writeConsole(`EPUB compilation failed: ${err.message}`, "error");
    }
}

// App Initialization
window.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadTokenStatus();
    loadLibrary();
});
