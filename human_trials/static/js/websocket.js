// websocket.js
import { state } from './state.js';
import { apiFetch, addLogMessage } from './helpers.js';
import { hideMeetingVoteModals, showEjectionBanner, renderMeetingChat, updateMeetingUI } from './meeting.js';
import { showKilledModal, updateTaskProgressBar, updateMapUI } from './ui.js';
import { refreshRoomContext } from './actions.js';

// --- WEBSOCKET ---
// Open persistent connection to the server.
// Allows server to send real-time game state and lobby updates without client requesting them
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

    // Include playerToken in query params for server authentication when establishing ws connection
    state.ws = new WebSocket(`${protocol}//${window.location.host}/ws?token=${state.playerToken}`);

    state.ws.onopen = () => console.log('[WS] Connected'); // Debug for successful connection

    // Event: Message Received from Server
    // event example { type: 'state_update', timestep: 1, phase: 'task', ... }
    state.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        // Game logic like movement and tasks
        if (msg.type === 'state_update'){
            handleWsStateUpdate(msg);
        }
        // Lobby updates like player join/leave while in lobby
        else if (window._wsLobbyHandler){
            window._wsLobbyHandler(msg);
        }
    };

    state.ws.onclose = (event) => {
        if (event.code === 4003) {
            console.log('[WS] Stale session: Reloading');
            window.location.reload();
            return;
        }
        console.log('[WS] Disconnected - Attempting to reconnect in 2 seconds');
        setTimeout(connectWebSocket, 2000);
    };
}

// --- TURN TIMER ---
// Tracks last-seen values to detect when new timer period starts.
// Only resets the countdown when a distinct server-managed timer period begins.
let _turnTimerInterval = null;
let _timerLastTimestep = -1;
let _timerLastPhase = null;
let _timerLastTurnSeq = -1;
let _timerLastCanVote = null;
let _lastPlayerStateSignature = null;
let _matchClockInterval = null;
let _matchClockDeadline = null;

function formatCountdown(totalSeconds) {
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const minuteSecond = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    return hours ? `${hours}:${minuteSecond}` : minuteSecond;
}

function stopMatchClock() {
    if (_matchClockInterval !== null) {
        clearInterval(_matchClockInterval);
        _matchClockInterval = null;
    }
}

function updateMatchClock(data) {
    const clockEl = document.getElementById('game-clock-strip');
    const valueEl = document.getElementById('game-clock-val');
    if (!clockEl || !valueEl || !state.gameStarted) {
        return;
    }

    const secondsLeft = data.match_seconds_left || 0;
    if (data.match_clock_paused) {
        stopMatchClock();
        _matchClockDeadline = null;
        valueEl.innerText = formatCountdown(secondsLeft);
        clockEl.classList.remove('d-none');
        return;
    }

    _matchClockDeadline = Date.now() + (secondsLeft * 1000);
    const render = () => {
        const secondsLeft = Math.max(0, Math.ceil((_matchClockDeadline - Date.now()) / 1000));
        valueEl.innerText = formatCountdown(secondsLeft);
    };

    clockEl.classList.remove('d-none');
    render();
    if (_matchClockInterval === null) {
        _matchClockInterval = setInterval(render, 1000);
    }
}

function _renderTimer(s) {
    const colorClass = s <= 10 ? 'text-danger' : 'text-warning';
    const stripEl = document.getElementById('turn-timer-strip');
    const stripValEl = document.getElementById('turn-timer-val');
    const meetingEl = document.getElementById('turn-timer-meeting');
    if (stripEl) stripEl.classList.remove('d-none');
    if (stripValEl) { stripValEl.innerText = s; stripValEl.className = `fw-bold ${colorClass}`; }
    if (meetingEl) { meetingEl.style.display = 'block'; meetingEl.innerText = `${s}s remaining`; meetingEl.className = `fw-bold small text-center mb-1 ${colorClass}`; }
}

// Called when the countdown hits 0.
// Later, the server processes the auto-submit and the next WS message arrives.
function _renderTimerExpired() {
    const stripEl = document.getElementById('turn-timer-strip');
    const stripValEl = document.getElementById('turn-timer-val');
    const meetingEl = document.getElementById('turn-timer-meeting');
    if (stripEl) stripEl.classList.remove('d-none');
    if (stripValEl) { stripValEl.innerText = '…'; stripValEl.className = 'fw-bold text-danger'; }
    if (meetingEl) { meetingEl.style.display = 'block'; meetingEl.innerText = 'Submitting…'; meetingEl.className = 'fw-bold small text-center mb-1 text-danger'; }
}

function _hideTimer() {
    if (_turnTimerInterval !== null) { clearInterval(_turnTimerInterval); _turnTimerInterval = null; }
    const stripEl = document.getElementById('turn-timer-strip');
    const meetingEl = document.getElementById('turn-timer-meeting');
    if (stripEl) stripEl.classList.add('d-none');
    if (meetingEl) meetingEl.style.display = 'none';
}

function updateTurnTimer(data) {
    const isMeeting = data.phase === 'meeting';
    const shouldShow = isMeeting && data.is_alive && (data.discussion_open || data.can_vote);

    if (!shouldShow) {_hideTimer(); return;}

    // Detect genuine timer resets
    // shouldReset if we enter a new timestep, phase, discussion turn, or voting state. 
    const newTimestep = data.timestep !== _timerLastTimestep;
    const newPhase = data.phase !== _timerLastPhase;
    const newTurnSeq = (data.discussion_turn_seq ?? -1) !== _timerLastTurnSeq;
    const newVoting = data.can_vote !== _timerLastCanVote;
    const shouldReset = newTimestep || newPhase || (isMeeting && newTurnSeq) || (isMeeting && newVoting);

    _timerLastTimestep = data.timestep;
    _timerLastPhase = data.phase;
    _timerLastTurnSeq = data.discussion_turn_seq ?? -1;
    _timerLastCanVote = data.can_vote;

    if (!shouldReset) return;

    // Reset timer
    if (_turnTimerInterval !== null) { clearInterval(_turnTimerInterval); _turnTimerInterval = null; }
    let remaining = data.turn_seconds_left ?? 60;

    _renderTimer(remaining);
    _turnTimerInterval = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
            _renderTimerExpired();
            clearInterval(_turnTimerInterval);
            _turnTimerInterval = null;
        }
        else {
            _renderTimer(remaining);
        }
    }, 1000);
}
// Display game over screen with winner and player statuses.
function handleGameOver(data) {
    if (!data.winner){
        return false;
    }
    // Let a vote-triggered end show its ejection result before the game-over
    // overlay replaces the meeting view.
    if (data.phase === 'task' && data.vote_result && state.lastPhase === 'meeting') {
        return false;
    }
    stopMatchClock();
    const overlay = document.getElementById('gameover-overlay');
    const title = document.getElementById('gameover-title');
    const playersDiv = document.getElementById('gameover-players');
    const completionLink = document.getElementById('participation-completion-link');

    const impostorWin = data.winner.toLowerCase().includes('impostor');
    title.className = `fw-bold mb-4 ${impostorWin ? 'text-danger' : 'text-success'}`;
    title.innerText = data.winner.split('(')[0].trim();

    if (completionLink) {
        const completionUrl = data.participation_completion_url;
        if (completionUrl) {
            completionLink.href = completionUrl;
            completionLink.classList.remove('d-none');
        } else {
            completionLink.href = '#';
            completionLink.classList.add('d-none');
        }
    }
    
    playersDiv.innerHTML = '';
    // For each player, show their name, color, alive/dead status, and role (impostor or crewmate)
    data.players.forEach(player => {
        const isImpostor = player.identity.toLowerCase() === 'impostor';

        const img = document.createElement('img');
        img.src = player.is_alive
            ? `/assets/player_sprites/alive/player_${player.color}.png`
            : `/assets/player_sprites/dead/${player.color}_body.png`;
        img.alt = player.name;

        const nameSpan = document.createElement('span');
        nameSpan.className = 'gameover-player-name';
        nameSpan.textContent = player.name;

        const roleBadge = document.createElement('span');
        roleBadge.className = `gameover-badge ${isImpostor ? 'impostor' : 'crewmate'}`;
        roleBadge.textContent = isImpostor ? 'IMPOSTOR' : 'CREWMATE';

        const statusBadge = document.createElement('span');
        statusBadge.className = `gameover-badge ${player.is_alive ? 'alive' : 'dead'}`;
        statusBadge.textContent = player.is_alive ? 'ALIVE' : 'DEAD';

        const row = document.createElement('div');
        row.className = 'gameover-player-row';
        row.append(img, nameSpan, roleBadge, statusBadge);
        playersDiv.appendChild(row);
    })

    if (overlay){
        overlay.classList.remove('d-none');
    }
    return true;
}

// Update the shared task progress bar.
function updateHUD(data) {
    updateTaskProgressBar(data.task_progress);
}

function renderGameEvents(data) {
    if (!Array.isArray(data.game_events)) {
        return;
    }

    data.game_events.forEach((event) => {
        if (!event || state.processedGameEventIds.has(event.id)) {
            return;
        }
        state.processedGameEventIds.add(event.id);
        addLogMessage(event.message, event.type || 'info');
    });
}

async function refreshImmediatePlayerState(data) {
    const signature = (data.players || [])
        .map((player) => `${player.color}:${player.is_alive}:${player.body_location || ''}:${player.reported_death}`)
        .sort()
        .join('|');
    const changed = signature !== _lastPlayerStateSignature;
    _lastPlayerStateSignature = signature;

    // A kill can change player/body state without advancing the shared turn.
    // Refresh the map in that case so every client sees the body immediately.
    if (!changed || data.timestep > state.lastTimestep) {
        return;
    }

    if (state.isAlive && !data.is_alive) {
        state.isAlive = false;
        state.wasAlive = false;
        addLogMessage('YOU WERE KILLED', 'danger');
        showKilledModal();
    }
    await refreshRoomContext();
    await updateMapUI();
}

// Apply each independently executed map action as it arrives.
async function resolveStepIfReady(data) {
    if (data.timestep <= state.lastTimestep) return;
    state.lastTimestep = data.timestep;

    // Differentiate between being killed vs ejected: killed_by is null for ejections
    if (state.wasAlive && !data.is_alive) {
        if (!data.killed_by) {
            addLogMessage('YOU WERE EJECTED', 'danger');
        }
        else {
            const killer = data.killed_by.charAt(0).toUpperCase() + data.killed_by.slice(1);
            addLogMessage(`YOU WERE KILLED BY ${killer.toUpperCase()}`, 'danger');
            showKilledModal();
        }
    }
    state.wasAlive = data.is_alive;
    state.isAlive = data.is_alive;

    // Every applied action can change the local room, available actions, or map.
    await refreshRoomContext();
    await updateMapUI();
}

// Phase Transition Logic. Task -> Meeting, Meeting -> Task, etc.
async function handlePhaseUpdate(data) {
    if (data.phase !== state.lastPhase) {
        state.lastPhase = data.phase;
        await handleGlobalPhaseTransition(data);
    }

    if (data.phase === "meeting") {
        renderMeetingChat(data.meeting_messages);
        updateMeetingUI(data);
    }
}

// Main handler for incoming websocket messages of type 'state_update'
// Handles the main game loop updates, including game over detection, HUD updates, turn timer management, step resolution, and phase transitions.
async function handleWsStateUpdate(data) {
    if (!state.gameStarted) return;
    if (handleGameOver(data)) return;
    updateHUD(data);
    updateMatchClock(data);
    renderGameEvents(data);
    updateTurnTimer(data);
    await refreshImmediatePlayerState(data);
    await resolveStepIfReady(data);
    await handlePhaseUpdate(data);
}

// --- PHASE TRANSITIONS ---
// Handles UI and state changes needed when transitioning between phases like task, meeting, etc...
async function handleGlobalPhaseTransition(data) {
    const { phase, is_alive, vote_result } = data;

    const actionPanelEl = document.getElementById('action-panel');
    const meetingOverlayEl = document.getElementById('meeting-overlay');
    const chatInputGroupEl = document.getElementById('chat-input-group');
    const skipBtnEl = document.getElementById('skip-vote-btn');

    if (phase === "meeting") {
        // Chat input visibility
        // Ghost observe only
        if (!is_alive) {
            if (chatInputGroupEl) chatInputGroupEl.style.display = 'none';
        }
        else {
            if (chatInputGroupEl) chatInputGroupEl.style.display = 'flex';
        }
        if (skipBtnEl) {
            skipBtnEl.style.display = 'none';
            skipBtnEl.disabled = false;
            skipBtnEl.classList.remove('vote-skip-selected', 'text-dark');
            skipBtnEl.classList.add('btn-outline-warning');
        }
        // Hide action panel, show countdown banner
        if (actionPanelEl){
            actionPanelEl.classList.add('d-none');
        }
        if (meetingOverlayEl){
            meetingOverlayEl.classList.remove('d-none');
        }
        // Reset meeting state
        const chatBox = document.getElementById('discussion-chat');
        const votingRoster = document.getElementById('voting-roster-container');
        if (chatBox){
            chatBox.innerHTML = '';
        }
        if (votingRoster){
            votingRoster.innerHTML = '';
        }
        // Init meeting vars
        state.processedMessageCount = 0;
        state.chatInputLocked = false;
        state.lastDiscussionTurnSeq = -1;
        // Advance the engine after a short visible meeting-intro beat.
        startMeetingCountdown();
    }

    else if (phase === "task") {
        hideMeetingVoteModals();
        // Cancel any in-progress countdown if available
        if (state.meetingCountdownTimer !== null) {
            clearTimeout(state.meetingCountdownTimer);
            state.meetingCountdownTimer = null;
        }
        // Ejection results
        if (vote_result !== undefined && vote_result !== null) {
            showEjectionBanner(vote_result);
            await new Promise(timer => setTimeout(timer, 5000)); // Show results for 5s
            if (state.lastPhase !== "task"){
                return;
            }
            if (data.winner) {
                handleGameOver(data);
                return;
            }
        }
        // Restore task screen
        if (actionPanelEl){
            actionPanelEl.classList.remove('d-none');
        }
        if (skipBtnEl) {
            skipBtnEl.style.display = 'none';
            skipBtnEl.disabled = false;
            skipBtnEl.classList.remove('vote-skip-selected', 'text-dark');
            skipBtnEl.classList.add('btn-outline-warning');
        }
        if (meetingOverlayEl){
            meetingOverlayEl.classList.add('d-none');
        }
        await refreshRoomContext();
        await updateMapUI();
    }
}

// Short randomized meeting intro, then start the discussion step.
function startMeetingCountdown() {
    // Reset timer from previous meeting if needed
    if (state.meetingCountdownTimer !== null) {
        clearTimeout(state.meetingCountdownTimer);
        state.meetingCountdownTimer = null;
    }

    const introMs = 500 + Math.floor(Math.random() * 2501);

    function countDown(msLeft) {
        const secondsLeft = Math.max(0, msLeft / 1000);
        const turnPrompt = document.getElementById('turn-prompt');
        if (turnPrompt){
            turnPrompt.style.display = 'block';
            turnPrompt.className = 'text-danger fw-bold small text-center mb-1';
            turnPrompt.innerText = `Emergency meeting starting in ${secondsLeft.toFixed(1)}s...`;
        }

        if (msLeft <= 0) {
            state.meetingCountdownTimer = null;
            const overlay = document.getElementById('meeting-overlay');
            if (overlay){
                overlay.classList.remove('d-none');
            }
            if (turnPrompt){
                turnPrompt.style.display = 'none';
            }
            apiFetch('/api/next-step', { method: 'POST' }); // intentionally not awaited
            return;
        }
        const nextDelay = Math.min(100, msLeft);
        state.meetingCountdownTimer = setTimeout(() => countDown(msLeft - nextDelay), nextDelay);
    }

    countDown(introMs);
}

export { connectWebSocket };
