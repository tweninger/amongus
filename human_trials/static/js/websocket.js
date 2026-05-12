// websocket.js
import { state } from './state.js';
import { apiFetch, addLogMessage, unlockActions } from './helpers.js';
import { showEjectionBanner, renderMeetingChat, updateMeetingUI } from './meeting.js';
import { updateTaskProgressBar, updateMapUI } from './ui.js';
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

    state.ws.onclose = () => {
        console.log('[WS] Disconnected - Attempting to reconnect in 2 seconds');
        setTimeout(connectWebSocket, 2000); // Try to reconnect every 2 seconds if connection is lost
    };
}

// --- TURN TIMER ---
// Tracks last-seen values to detect when new timer period starts.
// Only resets the countdown when the timestep, phase, turn sequence, or voting state changes
let _turnTimerInterval = null;
let _timerLastTimestep = -1;
let _timerLastPhase = null;
let _timerLastTurnSeq = -1;
let _timerLastCanVote = null;

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
    const isTask = data.phase === 'task';
    const isMeeting = data.phase === 'meeting';
    // Task phase: show for everyone
    // Meeting phase: only show when it's your turn
    const shouldShow = isTask || (isMeeting && data.is_my_turn);

    if (!shouldShow) { _hideTimer(); return; }

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
    let remaining = data.turn_seconds_left ?? (isTask ? 60 : 45);

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

// Check if server sent winner string
// Basic win alert.
// TODO - Add more detailed end game screen with stats, voting records, etc.
function handleGameOver(data) {
    if (!data.winner) return false;
    alert("GAME OVER: " + data.winner);
    window.location.reload();
    return true;
}

// Update timestep counter and task progress bar
function updateHUD(data) {
    const timeStepCounter = document.getElementById('step-counter');
    if (timeStepCounter){
        timeStepCounter.innerText = data.timestep;
    }
    updateTaskProgressBar(data.task_progress);
}

// Multiplayer sync. Wait for every player to put in an action.
// The server only runs game_step() once ALL alive humans have queued an action, so we are locked until so.
async function resolveStepIfReady(data) {
    if (!state.waitingForStep || data.timestep <= state.lastTimestep) return; // Rising timestamp means the pending step has resolved

    // Update state. No longer waiting.
    state.waitingForStep = false;
    state.lastTimestep = data.timestep;
    document.getElementById('waiting-indicator')?.classList.add('d-none');
    unlockActions();

    // Emit deferred log entry now with the correct timestep.
    if (state.pendingActionLog) {
        const { step, message, type, observations, ventObservations } = state.pendingActionLog;
        const logStep = step ?? data.timestep;
        addLogMessage(`[Step ${logStep}] ${message}`, type);
        observations?.forEach(observation => addLogMessage(`[Step ${logStep}] ${observation}`, 'warning'));
        ventObservations?.forEach(observation => addLogMessage(`[Step ${logStep}] ${observation}`, 'danger'));
        state.pendingActionLog = null;
    }

    // Refresh room state unless we just entered a meeting
    // Meeting state is handled separately in the meeting UI and doesn't need to be refreshed with the general room context
    if (data.phase !== "meeting") {
        await refreshRoomContext();
        await updateMapUI();
    }
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
    updateTurnTimer(data);
    await resolveStepIfReady(data);
    await handlePhaseUpdate(data);
}

// --- PHASE TRANSITIONS ---
// Handles UI and state changes needed when transitioning between phases like task, meeting, etc...
async function handleGlobalPhaseTransition(data) {
    const { phase, is_alive, vote_result } = data;

    const actionPanelEl = document.getElementById('action-panel');
    const discussionPanelEl = document.getElementById('discussion-panel');
    const meetingOverlayEl = document.getElementById('meeting-overlay');
    const phaseDisplayEl = document.getElementById('current-phase');
    const chatInputGroupEl = document.getElementById('chat-input-group');
    const skipBtnEl = document.getElementById('skip-vote-btn');

    if (phase === "meeting") {
        // Update phase badge
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = "MEETING CALLED!";
            phaseDisplayEl.className = "text-danger fw-bold";
        }
        // Chat input visibility
        // Ghost observe only
        if (!is_alive) {
            if (chatInputGroupEl) chatInputGroupEl.style.display = 'none';
            if (skipBtnEl) skipBtnEl.style.display = 'none';
        }
        else {
            if (chatInputGroupEl) chatInputGroupEl.style.display = 'flex';
            if (skipBtnEl) skipBtnEl.style.display = 'block';
        }
        // Hide action panel, show countdown banner
        if (actionPanelEl){
            actionPanelEl.classList.add('d-none');
        }
        if (discussionPanelEl){
            discussionPanelEl.classList.remove('d-none');
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
        state.pendingActionLog = null;
        // Start 10 second countdown timer
        startMeetingCountdown();
    }

    else if (phase === "task") {
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
        }
        // Restore task screen
        if (actionPanelEl){
            actionPanelEl.classList.remove('d-none');
        }
        if (discussionPanelEl){
            discussionPanelEl.classList.add('d-none');
        }
        if (meetingOverlayEl){
            meetingOverlayEl.classList.add('d-none');
        }
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = is_alive ? "Active" : "Spectating (Ghost Mode)";
            phaseDisplayEl.className = "text-success fw-bold";
        }
        await refreshRoomContext();
        await updateMapUI();
    }
}

// Countdown from 10 then auto-enter the meeting overlay and start meeting step
function startMeetingCountdown() {
    // Reset timer from previous meeting if needed
    if (state.meetingCountdownTimer !== null) {
        clearTimeout(state.meetingCountdownTimer);
        state.meetingCountdownTimer = null;
    }

    function countDown(secondsLeft) {
        const countdownText = document.getElementById('meeting-countdown-text');
        if (countdownText){
            countdownText.innerText = `Emergency meeting starting in ${secondsLeft}s...`;
        }

        if (secondsLeft <= 0) {
            state.meetingCountdownTimer = null;
            const overlay = document.getElementById('meeting-overlay');
            if (overlay){
                overlay.classList.remove('d-none');
            }
            apiFetch('/api/next-step', { method: 'POST' }); // intentionally not awaited
            return;
        }
        // Recursively call countDown until 0
        state.meetingCountdownTimer = setTimeout(() => countDown(secondsLeft - 1), 1000);
    }

    countDown(10);
}

export { connectWebSocket };
