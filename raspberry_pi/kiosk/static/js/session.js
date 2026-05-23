/**
 * Petgully Spotless - Session Progress Page
 * 
 * Handles:
 * - Real-time progress updates via WebSocket
 * - Stage timeline display
 * - Timer countdown
 * - Completion/error modals
 */

// =============================================================================
// State
// =============================================================================
let socket = null;
let sessionData = null;
let stages = [];
let currentStageIndex = 0;
let timerInterval = null;

// Safety-net state: ensures the kiosk never gets permanently stuck if a
// WebSocket event is missed (e.g. the Pi rebooted mid-session, the socket
// reconnected to a fresh server, and the session_complete emit landed in
// a void). We poll /api/status periodically and force a redirect when the
// backend reports the session is no longer active.
let sessionHasStarted = false;       // flips true on the first stage_start
let redirectAlreadyArmed = false;    // prevents double-redirects
let serverIdleStreak = 0;            // consecutive polls reporting idle
let safetyPollInterval = null;

// =============================================================================
// DOM Elements
// =============================================================================
const elements = {
    sessionType: document.getElementById('sessionType'),
    qrCode: document.getElementById('qrCode'),
    stageImage: document.getElementById('stageImage'),
    stageLabel: document.getElementById('stageLabel'),
    timerDisplay: document.getElementById('timerDisplay'),
    currentStageName: document.getElementById('currentStageName'),
    stageProgressPercent: document.getElementById('stageProgressPercent'),
    stageProgressBar: document.getElementById('stageProgressBar'),
    overallProgressPercent: document.getElementById('overallProgressPercent'),
    overallProgressBar: document.getElementById('overallProgressBar'),
    stageTimeline: document.getElementById('stageTimeline'),
    currentTime: document.getElementById('currentTime'),
    emergencyStop: document.getElementById('emergencyStop'),
    completionModal: document.getElementById('completionModal'),
    errorModal: document.getElementById('errorModal'),
    errorModalText: document.getElementById('errorModalText'),
    errorOkButton: document.getElementById('errorOkButton'),
    returnCountdown: document.getElementById('returnCountdown'),
};

// =============================================================================
// Initialization
// =============================================================================
document.addEventListener('DOMContentLoaded', () => {
    // Get session data from URL or sessionStorage
    const urlParams = new URLSearchParams(window.location.search);
    const sessionType = urlParams.get('type') || 'small';
    const qrCode = urlParams.get('qr') || 'N/A';
    
    // Try to get full session data from sessionStorage
    const storedSession = sessionStorage.getItem('currentSession');
    if (storedSession) {
        sessionData = JSON.parse(storedSession);
        stages = sessionData.stages || getDefaultStages(sessionType);
    } else {
        stages = getDefaultStages(sessionType);
    }
    
    // Initialize UI
    elements.sessionType.textContent = formatSessionType(sessionType);
    elements.qrCode.textContent = qrCode;
    
    // Initialize WebSocket
    initializeSocket();
    
    // Build timeline
    buildTimeline();
    
    // Update clock
    updateClock();
    setInterval(updateClock, 1000);
    
    // Emergency stop handler
    elements.emergencyStop.addEventListener('click', emergencyStop);
    
    // Error modal button
    elements.errorOkButton.addEventListener('click', () => {
        window.location.href = '/';
    });
});

// =============================================================================
// WebSocket Connection
// =============================================================================
function initializeSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('Connected to server');
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
    });
    
    socket.on('stage_start', (data) => {
        console.log('Stage start:', data);
        handleStageStart(data);
    });
    
    socket.on('stage_progress', (data) => {
        handleStageProgress(data);
    });
    
    socket.on('stage_complete', (data) => {
        console.log('Stage complete:', data);
        handleStageComplete(data);
    });
    
    socket.on('session_complete', (data) => {
        console.log('Session complete:', data);
        handleSessionComplete(data);
    });
    
    socket.on('session_stopped', (data) => {
        console.log('Session stopped:', data);
        handleSessionStopped(data);
    });

    // Backend emits this when a session ends with result.ok == False (e.g.
    // executor abort, exception, or stop mid-flight). Without this handler
    // the kiosk would sit on the last stage forever.
    socket.on('session_aborted', (data) => {
        console.log('Session aborted:', data);
        handleSessionAborted(data);
    });

    socket.on('session_error', (data) => {
        console.log('Session error:', data);
        handleSessionError(data);
    });

    // Start the server-status safety net. It only redirects after the
    // session has actually started AND the server reports idle for two
    // consecutive polls, so it never fires prematurely.
    startSafetyPoll();
}

// =============================================================================
// Safety net: poll /api/status so a missed WebSocket event can't strand us
// =============================================================================
function startSafetyPoll() {
    if (safetyPollInterval) return;
    // 5 second cadence: 2 idle reads in a row = ~10 seconds before redirect.
    safetyPollInterval = setInterval(checkServerStatus, 5000);
}

function stopSafetyPoll() {
    if (safetyPollInterval) {
        clearInterval(safetyPollInterval);
        safetyPollInterval = null;
    }
}

async function checkServerStatus() {
    if (redirectAlreadyArmed) return;
    try {
        const res = await fetch('/api/status', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!data.session_active) {
            // Don't redirect during the initial scan→first-stage window;
            // the session might just not have started yet.
            if (!sessionHasStarted) return;
            serverIdleStreak += 1;
            console.log(`Safety poll: server idle (streak ${serverIdleStreak})`);
            if (serverIdleStreak >= 2) {
                console.warn('Safety net redirecting: server reports idle.');
                armRedirectHome('We hit a small hiccup — returning to home.', 4);
            }
        } else {
            serverIdleStreak = 0;
        }
    } catch (e) {
        // Network blip — don't redirect on a single failed poll.
        console.log('Safety poll fetch failed (will retry):', e);
    }
}

function armRedirectHome(message, seconds) {
    if (redirectAlreadyArmed) return;
    redirectAlreadyArmed = true;
    stopSafetyPoll();
    if (message) {
        // Surface a friendly notice. The error modal element is the cleanest
        // visual we already have; reusing it keeps the bundle small.
        try { showError(message); } catch (_) {}
    }
    setTimeout(() => { window.location.href = '/'; },
               Math.max(0, (seconds || 0) * 1000));
}

// =============================================================================
// Stage Handlers
// =============================================================================
function handleStageStart(data) {
    sessionHasStarted = true;
    serverIdleStreak = 0;
    currentStageIndex = data.stage_index;
    
    // Update stage label
    elements.stageLabel.textContent = data.stage_label;
    elements.currentStageName.textContent = data.stage_label;
    
    // Update stage image
    const imagePath = `/static/images/${data.stage_image}`;
    elements.stageImage.src = imagePath;
    elements.stageImage.onerror = () => {
        elements.stageImage.src = '/static/images/welcome.png';
    };
    
    // Reset stage progress
    elements.stageProgressPercent.textContent = '0%';
    elements.stageProgressBar.style.width = '0%';
    
    // Update timeline
    updateTimeline(data.stage_index);
}

function handleStageProgress(data) {
    // Update timer display
    const remaining = data.remaining;
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    elements.timerDisplay.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    
    // Update stage progress
    elements.stageProgressPercent.textContent = `${data.progress}%`;
    elements.stageProgressBar.style.width = `${data.progress}%`;
    
    // Update overall progress
    const totalStages = stages.length;
    const completedStages = data.stage_index;
    const stageContribution = data.progress / 100;
    const overallProgress = Math.round(((completedStages + stageContribution) / totalStages) * 100);
    
    elements.overallProgressPercent.textContent = `${overallProgress}%`;
    elements.overallProgressBar.style.width = `${overallProgress}%`;
}

function handleStageComplete(data) {
    // Mark stage as complete in timeline
    const timelineItem = document.querySelector(`[data-stage-index="${data.stage_index}"]`);
    if (timelineItem) {
        timelineItem.classList.remove('active');
        timelineItem.classList.add('completed');
        const icon = timelineItem.querySelector('.timeline-icon');
        icon.innerHTML = '✓';
    }
}

function handleSessionComplete(data) {
    if (redirectAlreadyArmed) return;
    redirectAlreadyArmed = true;
    stopSafetyPoll();

    // Show completion modal
    elements.completionModal.classList.remove('hidden');

    // Countdown to redirect
    let countdown = 10;
    elements.returnCountdown.textContent = countdown;

    const countdownInterval = setInterval(() => {
        countdown--;
        elements.returnCountdown.textContent = countdown;

        if (countdown <= 0) {
            clearInterval(countdownInterval);
            window.location.href = '/';
        }
    }, 1000);
}

function handleSessionStopped(data) {
    armRedirectHome('Session was stopped. Returning to home...', 3);
}

function handleSessionAborted(data) {
    // Treated like session_stopped from the customer's perspective — the
    // session ended without completing, kiosk needs to go back home. The
    // backend already turned all relays off before emitting.
    const why = (data && data.reason) ? `Session ended (${data.reason}).`
                                      : 'Session ended. Returning to home...';
    armRedirectHome(why, 3);
}

function handleSessionError(data) {
    showError(data.message || 'An error occurred during the session.');
    // Don't auto-redirect here: the user explicitly clicks OK on the error
    // modal (existing behaviour). But disable the safety-net poll so it
    // doesn't fight the modal.
    stopSafetyPoll();
}

// =============================================================================
// Timeline
// =============================================================================
function buildTimeline() {
    elements.stageTimeline.innerHTML = '';
    
    stages.forEach((stage, index) => {
        const item = document.createElement('div');
        item.className = 'timeline-item pending';
        item.dataset.stageIndex = index;
        
        const duration = formatDuration(stage.duration);
        
        item.innerHTML = `
            <div class="timeline-icon">${index + 1}</div>
            <div class="timeline-label">${stage.label}</div>
            <div class="timeline-duration">${duration}</div>
        `;
        
        elements.stageTimeline.appendChild(item);
    });
    
    // Mark first stage as active
    const firstItem = elements.stageTimeline.querySelector('[data-stage-index="0"]');
    if (firstItem) {
        firstItem.classList.remove('pending');
        firstItem.classList.add('active');
    }
}

function updateTimeline(activeIndex) {
    const items = elements.stageTimeline.querySelectorAll('.timeline-item');
    
    items.forEach((item, index) => {
        item.classList.remove('active', 'completed', 'pending');
        
        if (index < activeIndex) {
            item.classList.add('completed');
            const icon = item.querySelector('.timeline-icon');
            icon.innerHTML = '✓';
        } else if (index === activeIndex) {
            item.classList.add('active');
            const icon = item.querySelector('.timeline-icon');
            icon.innerHTML = index + 1;
        } else {
            item.classList.add('pending');
            const icon = item.querySelector('.timeline-icon');
            icon.innerHTML = index + 1;
        }
    });
    
    // Scroll to active item
    const activeItem = elements.stageTimeline.querySelector('.timeline-item.active');
    if (activeItem) {
        activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// =============================================================================
// Emergency Stop
// =============================================================================
async function emergencyStop() {
    if (!confirm('Are you sure you want to stop the session?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/session/stop', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });
        
        const data = await response.json();
        console.log('Emergency stop response:', data);
        
    } catch (error) {
        console.error('Error stopping session:', error);
    }
    
    // Redirect to home regardless
    window.location.href = '/';
}

// =============================================================================
// Error Handling
// =============================================================================
function showError(message) {
    elements.errorModalText.textContent = message;
    elements.errorModal.classList.remove('hidden');
}

// =============================================================================
// Helpers
// =============================================================================
function formatSessionType(type) {
    const types = {
        'small': 'Small Pet Bath',
        'large': 'Large Pet Bath',
        'custdiy': 'DIY Bath',
        'medsmall': 'Medicated (Small)',
        'medlarge': 'Medicated (Large)',
        'onlydisinfectant': 'Disinfectant',
        'quicktest': 'Relay Test',
        'demo': 'Demo Mode',
        'onlydrying': 'Drying Only',
        'onlywater': 'Water Only',
        'onlyflush': 'Flush Only',
        'onlyshampoo': 'Shampoo Only',
        'empty001': 'Empty Tank',
    };
    return types[type] || type;
}

function formatDuration(seconds) {
    if (seconds >= 60) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
    }
    return `${seconds}s`;
}

function updateClock() {
    const now = new Date();
    const options = { 
        hour: '2-digit', 
        minute: '2-digit',
        hour12: true,
    };
    elements.currentTime.textContent = now.toLocaleString('en-US', options);
}

function getDefaultStages(sessionType) {
    const defaultStages = {
        'small': [
            { name: 'welcome', label: 'Welcome to Spotless', duration: 10, image: 'welcome.png' },
            { name: 'preparing', label: 'Getting Ready', duration: 20, image: 'preparing.png' },
            { name: 'shampoo', label: 'Shampoo Stage', duration: 120, image: 'shampoo.png' },
            { name: 'massage1', label: 'Massage Time', duration: 10, image: 'massage.png' },
            { name: 'rinse1', label: 'Water Rinse', duration: 60, image: 'water.png' },
            { name: 'conditioner', label: 'Conditioner Stage', duration: 120, image: 'conditioner.png' },
            { name: 'massage2', label: 'Massage Time', duration: 10, image: 'massage.png' },
            { name: 'rinse2', label: 'Final Rinse', duration: 60, image: 'water.png' },
            { name: 'toweldry', label: 'Towel Dry', duration: 30, image: 'toweldry.png' },
            { name: 'drying', label: 'Drying Time', duration: 480, image: 'drying.png' },
            { name: 'complete', label: 'Session Complete', duration: 10, image: 'complete.png' },
        ],
        'large': [
            { name: 'welcome', label: 'Welcome to Spotless', duration: 10, image: 'welcome.png' },
            { name: 'preparing', label: 'Getting Ready', duration: 20, image: 'preparing.png' },
            { name: 'shampoo', label: 'Shampoo Stage', duration: 150, image: 'shampoo.png' },
            { name: 'massage1', label: 'Massage Time', duration: 10, image: 'massage.png' },
            { name: 'rinse1', label: 'Water Rinse', duration: 80, image: 'water.png' },
            { name: 'conditioner', label: 'Conditioner Stage', duration: 150, image: 'conditioner.png' },
            { name: 'massage2', label: 'Massage Time', duration: 10, image: 'massage.png' },
            { name: 'rinse2', label: 'Final Rinse', duration: 80, image: 'water.png' },
            { name: 'toweldry', label: 'Towel Dry', duration: 30, image: 'toweldry.png' },
            { name: 'drying', label: 'Drying Time', duration: 600, image: 'drying.png' },
            { name: 'complete', label: 'Session Complete', duration: 10, image: 'complete.png' },
        ],
    };
    
    return defaultStages[sessionType] || defaultStages['small'];
}

// =============================================================================
// Prevent page navigation
// =============================================================================
window.onbeforeunload = function(e) {
    // Only warn if session is in progress
    if (!elements.completionModal.classList.contains('hidden')) {
        return; // Allow navigation after completion
    }
    // Uncomment to warn user before leaving
    // return 'Session is in progress. Are you sure you want to leave?';
};
