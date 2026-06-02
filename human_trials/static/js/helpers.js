// helpers.js
import { state } from './state.js';

// Wrapper around fetch that gives session token for authentication so we don't have to manually add every time.
function apiFetch(url, options = {}) {

    // Set default headers and merge with custom headers if provided
    const headers = {
        'Content-Type': 'application/json', ...(options.headers || {})
    };

    // Include the playerToken in header for authentication
    if (state.playerToken){
        headers['X-Player-Token'] = state.playerToken;
    }
    // Make network request with merged headers
    return fetch(url, { ...options, headers });
}

// Lock to prevent repeated action button presses
function lockActions() {
    if (state.actionLocked){
        return false;
    }
    state.actionLocked = true;
    const panel = document.getElementById('action-panel');
    if (panel){
        panel.querySelectorAll('button').forEach(btn => btn.disabled = true);
    }
    document.querySelectorAll('.map-action-hotspot').forEach((btn) => {
        btn.disabled = true;
    });
    document.querySelectorAll('.room-hover-action-button').forEach((btn) => {
        btn.disabled = true;
    });
    document.querySelectorAll('#room-task-overlay .room-task-active').forEach((btn) => {
        btn.disabled = true;
    });
    return true;
}

// Unlock actions when a new state arrives from server or when appropriate
function unlockActions() {
    state.actionLocked = false;
    const panel = document.getElementById('action-panel');
    if (panel){
        panel.querySelectorAll('button').forEach(btn => btn.disabled = false);
    }
    document.querySelectorAll('.map-action-hotspot').forEach((btn) => {
        btn.disabled = false;
        btn.classList.remove('committed');
    });
    document.querySelectorAll('.room-hover-action-button').forEach((btn) => {
        btn.disabled = false;
    });
    document.querySelectorAll('#room-task-overlay .room-task-active').forEach((btn) => {
        btn.disabled = false;
    });
}

// Send a message to the game log with optional type for color styling ('info', 'success', 'danger')
function addLogMessage(text, type = 'info') {
    const log = document.getElementById('game-log');
    if (!log){
        return;
    }
    // Map types to common Boostrap colors
    const colorMap = {
        'info': 'text-info',
        'success': 'text-success',
        'danger': 'text-danger fw-bold',
        'warning': 'text-warning'
    };

    const colorClass = colorMap[type] || 'text-light';

    // Append msg with a > prefix
    log.innerHTML += `<p class="${colorClass}">> ${text}</p>`;

    // Auto-scroll to the bottom
    log.scrollTop = log.scrollHeight;
}

// Simply capitalize a color string
function formatColorName(color){
    return color.charAt(0).toUpperCase() + color.slice(1).toLowerCase();
}

// Black returns grey text for readability
function displayColor(color){
    return color.toLowerCase() === 'black' ? 'grey' : color;
}

export { apiFetch, lockActions, unlockActions, addLogMessage, formatColorName, displayColor };
