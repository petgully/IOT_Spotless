/**
 * Petgully Spotless - Kiosk Main Application
 * 
 * Handles:
 * - Barcode/QR scanner input
 * - WebSocket communication
 * - Session initiation
 */

// =============================================================================
// Configuration
// =============================================================================
const CONFIG = {
    inputTimeout: 1500,  // ms to wait before auto-submit (for barcode scanners)
    minCodeLength: 1,   // Minimum valid code length (allow any length)
    maxCodeLength: 30,  // Maximum valid code length
};

// =============================================================================
// State
// =============================================================================
let socket = null;
let inputBuffer = '';
let inputTimer = null;

// =============================================================================
// DOM Elements
// =============================================================================
const elements = {
    qrInput: document.getElementById('qrInput'),
    startButton: document.getElementById('startButton'),
    errorMessage: document.getElementById('errorMessage'),
    errorText: document.getElementById('errorText'),
    statusIndicator: document.getElementById('statusIndicator'),
    loadingOverlay: document.getElementById('loadingOverlay'),
    currentTime: document.getElementById('currentTime'),
    quickButtons: document.querySelectorAll('.quick-btn'),
};

// =============================================================================
// Initialization
// =============================================================================
document.addEventListener('DOMContentLoaded', () => {
    initializeSocket();
    initializeInputHandlers();
    initializeQuickAccess();
    updateClock();
    setInterval(updateClock, 1000);
    
    // Keep input focused for barcode scanner
    keepInputFocused();
});

// =============================================================================
// WebSocket Connection
// =============================================================================
function initializeSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('Connected to server');
        updateStatus('online', 'Ready');
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        updateStatus('offline', 'Offline');
    });
    
    socket.on('scan_success', (data) => {
        console.log('Scan success:', data);
        hideError();
        // Redirect to session page
        window.location.href = `/session?type=${data.session_type}&qr=${data.qr_code}`;
    });
    
    socket.on('scan_failed', (data) => {
        console.log('Scan failed:', data);
        hideLoading();
        showError(data.message || 'QR code validation failed. Please contact management.');
        clearInput();
    });
    
    socket.on('session_error', (data) => {
        console.log('Session error:', data);
        hideLoading();
        showError(data.message || 'An error occurred. Please contact management.');
        clearInput();
    });
}

// =============================================================================
// Input Handlers
// =============================================================================
function initializeInputHandlers() {
    // Input change handler
    elements.qrInput.addEventListener('input', handleInput);
    
    // Enter key handler
    elements.qrInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            startSession();
        }
    });
    
    // Start button handler
    elements.startButton.addEventListener('click', startSession);
    
    // Global key handler for barcode scanner
    document.addEventListener('keypress', handleGlobalKeypress);
}

function handleInput(e) {
    const value = e.target.value.trim();
    
    // Enable/disable start button (allow any non-empty input)
    elements.startButton.disabled = value.length === 0;
    
    // Hide error when typing
    if (value.length > 0) {
        hideError();
    }
    
    // Auto-submit timer for barcode scanners
    // Clear any pending timer (resets on each keystroke)
    if (inputTimer) {
        clearTimeout(inputTimer);
    }
    
    // Set timer to auto-submit only if user stops typing for 1.5 seconds
    // This allows manual typing without auto-submitting, but still works for scanners
    if (value.length > 0) {
        inputTimer = setTimeout(() => {
            const currentValue = elements.qrInput.value.trim();
            // Only auto-submit if input hasn't changed and is still non-empty
            if (currentValue.length > 0 && currentValue === value) {
                // Auto-submit for barcode scanners (after pause)
                startSession();
            }
        }, CONFIG.inputTimeout);
    }
}

function handleGlobalKeypress(e) {
    // If not focused on input, redirect keypresses to input
    if (document.activeElement !== elements.qrInput) {
        // Ignore special keys
        if (e.key === 'Escape' || e.key === 'Tab') {
            return;
        }
        
        // Focus input and let the character be typed
        elements.qrInput.focus();
    }
}

function keepInputFocused() {
    // Re-focus input periodically (for kiosk mode)
    setInterval(() => {
        if (document.activeElement !== elements.qrInput && 
            !elements.loadingOverlay.classList.contains('hidden')) {
            elements.qrInput.focus();
        }
    }, 1000);
    
    // Focus on click anywhere
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.quick-btn') && !e.target.closest('.start-button')) {
            elements.qrInput.focus();
        }
    });
}

// =============================================================================
// Session Management
// =============================================================================
async function startSession(sessionType = null) {
    const qrCode = sessionType || elements.qrInput.value.trim();
    
    // Only check if code is empty (no minimum length requirement)
    if (!qrCode || qrCode.length === 0) {
        showError('Please scan or enter a QR code');
        return;
    }
    
    // Check maximum length
    if (qrCode.length > CONFIG.maxCodeLength) {
        showError(`Code too long (max ${CONFIG.maxCodeLength} characters)`);
        return;
    }
    
    console.log('Starting session with code:', qrCode);
    showLoading();
    hideError();
    
    try {
        const response = await fetch('/api/session/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ qr_code: qrCode }),
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Success - redirect will happen via WebSocket event
            console.log('Session started:', data);
            // Store session data for the session page
            sessionStorage.setItem('currentSession', JSON.stringify(data));
            // Redirect to session page
            window.location.href = `/session?type=${data.session_type}&qr=${data.qr_code}`;
        } else {
            hideLoading();
            showError(data.error || 'Failed to start session');
            clearInput();
        }
    } catch (error) {
        console.error('Error starting session:', error);
        hideLoading();
        showError('Connection error. Please try again.');
        clearInput();
    }
}

// =============================================================================
// Quick Access
// =============================================================================
function initializeQuickAccess() {
    elements.quickButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const sessionType = btn.dataset.type;
            elements.qrInput.value = sessionType.toUpperCase();
            elements.startButton.disabled = false;
            startSession(sessionType);
        });
    });
}

// =============================================================================
// UI Helpers
// =============================================================================
function showError(message) {
    elements.errorText.textContent = message;
    elements.errorMessage.classList.remove('hidden');
}

function hideError() {
    elements.errorMessage.classList.add('hidden');
}

function showLoading() {
    elements.loadingOverlay.classList.remove('hidden');
}

function hideLoading() {
    elements.loadingOverlay.classList.add('hidden');
}

function clearInput() {
    elements.qrInput.value = '';
    elements.startButton.disabled = true;
    elements.qrInput.focus();
}

function updateStatus(status, text) {
    const dot = elements.statusIndicator.querySelector('.status-dot');
    const span = elements.statusIndicator.querySelector('span:last-child');
    
    dot.className = `status-dot ${status}`;
    span.textContent = text;
}

function updateClock() {
    const now = new Date();
    const options = { 
        hour: '2-digit', 
        minute: '2-digit',
        hour12: true,
        weekday: 'short',
        month: 'short',
        day: 'numeric'
    };
    elements.currentTime.textContent = now.toLocaleString('en-US', options);
}

// =============================================================================
// Error Handling
// =============================================================================
window.onerror = function(msg, url, lineNo, columnNo, error) {
    console.error('Error:', msg, url, lineNo, columnNo, error);
    hideLoading();
    return false;
};
