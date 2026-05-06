// game.js

import { roomCoordinates } from "./config.js";
let processedMessageCount = 0;
let gameStarted = false;
let playerToken = null; // The session ID for the server to identify
let myColor = null;
let ws = null; // Holds live websocket connection
let myRole = null;

let actionPanel, phaseDisplay, sendChatBtn, chatInput;
let lastPhase = "active";
let actionLocked = false; // Global Lock for human actions
let waitingForStep = false; // True when this current client submitted an action but other players haven't yet
let lastTimestep = 0; // Used to detect when a new step is run
let chatInputLocked = false; // True after human sends in discussion. Unlocked when messages arrive
let lastDiscussionTurnSeq = -1; // Server-issued counter. Increments each time the baton passes to a new human in meetings
let pendingActionLog = null; // Stores { message, type, observations, ventObservations } while waiting for step
let meetingCountdownTimer = null;

// --- HELPERS ---
// Wrapper around fetch that gives session token for auth
// URL is the api endpoint we are hitting
function apiFetch(url, options = {}) {
    const headers = {
        'Content-Type': 'application/json', ...(options.headers || {})
    };

    // Include the token in header for authentication
    if (playerToken){
        headers['X-Player-Token'] = playerToken;
    }
    return fetch(url, { ...options, headers });
}

// Lock to prevent repeated action button presses
function lockActions() {
    if (actionLocked){
        return false;
    }
    actionLocked = true;
    const panel = document.getElementById('action-panel');
    if (panel){
        panel.querySelectorAll('button').forEach(btn => btn.disabled = true);
    }
    return true;
}

function unlockActions() {
    actionLocked = false;
    const panel = document.getElementById('action-panel');
    if (panel){
        panel.querySelectorAll('button').forEach(btn => btn.disabled = false);
    }
}

// Standardize sending messages to on-screen game log.
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

function showEjectionBanner(voteResult) {
    const chatBox = document.getElementById('discussion-chat');
    if (!chatBox){
        return;
    }

    const banner = document.createElement('div');
    banner.className = 'text-center p-3 my-2 animate__animated animate__fadeIn';
    banner.style.cssText = 'background: rgba(0,0,0,0.6); border-radius: 12px;';

    const ejected = voteResult.ejected;
    if (ejected) {
        banner.innerHTML = `
            <img src="/static/assets/player_${ejected}.png" style="width:60px;height:60px;opacity:0.5;transform:rotate(90deg);margin-bottom:8px;"><br>
            <span class="fw-bold text-warning" style="font-size:1.1rem;">${ejected.charAt(0).toUpperCase() + ejected.slice(1)} was ejected.</span>`;
    }
    else {
        banner.innerHTML = `<span class="fw-bold text-warning" style="font-size:1.1rem;">No one was ejected.</span>`;
    }

    chatBox.appendChild(banner);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function renderMeetingChat(messages) {
    // Only render new chats
    if (!messages || messages.length <= processedMessageCount){
        return;
    }
    const chatBox = document.getElementById('discussion-chat');
    if (!chatBox){
        return;
    }
    const newMessages = messages.slice(processedMessageCount);

    newMessages.forEach(msg => {
        const msgDiv = document.createElement('div');
        msgDiv.className = "d-flex align-items-start mb-3 p-2 animate__animated animate__fadeInUp";
        msgDiv.style.cssText = `background-color: rgba(255,255,255,0.05); border-radius: 8px; border-left: 4px solid ${displayColor(msg.sender_color)};`;
        msgDiv.innerHTML = `
            <img src="/static/assets/player_${msg.sender_color}.png" style="width: 40px; height: 40px; margin-right: 12px; border-radius: 50%;">
            <div style="flex-grow: 1;">
                <div class="d-flex justify-content-between">
                    <strong style="color: ${displayColor(msg.sender_color)}; font-size: 0.85rem;">${msg.sender_name}</strong>
                </div>
                <p class="mb-0 text-light" style="font-size: 0.95rem;">${msg.text}</p>
            </div>`;
        chatBox.appendChild(msgDiv);
    });
    chatBox.scrollTop = chatBox.scrollHeight;
    processedMessageCount = messages.length;
}

// --- WEBSOCKET ---
// Open persistent connection to the server.
// Allows server to send real-time game state and lobby updates without client requesting them
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

    ws = new WebSocket(`${protocol}//${window.location.host}/ws?token=${playerToken}`);

    ws.onopen = () => console.log('[WS] Connected');

    // Event: Message Received
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        // Game logic like movement and tasks
        if (msg.type === 'state_update'){
            handleWsStateUpdate(msg);
        }
        // Events like new person joining room
        else if (window._wsLobbyHandler){
            window._wsLobbyHandler(msg);
        }
    };

    ws.onclose = () => {
        console.log('[WS] Disconnected - Attempting to reconnect in 2 seconds');
        setTimeout(connectWebSocket, 2000);
    };
}

async function handleWsStateUpdate(data) {
    if (!gameStarted){
        return;
    }

    // Check if server sent winner string
    if (data.winner) {
        alert("GAME OVER: " + data.winner);
        window.location.reload();
        return;
    }

    // Update timestep counter
    const stepCounter = document.getElementById('step-counter');
    if (stepCounter){
        stepCounter.innerText = data.timestep;
    }

    // Update task progress bar
    updateTaskProgressBar(data.task_progress);

    // Unlock and refresh for players who submitted and were waiting for others
    // AKA: Everyone submitted and action and the turn is up
    if (waitingForStep && data.timestep > lastTimestep) {
        waitingForStep = false;
        lastTimestep = data.timestep;
        document.getElementById('waiting-indicator')?.classList.add('d-none');
        unlockActions();

        // Emit the deferred log entry now that the step has resolved
        if (pendingActionLog) {
            const { message, type, observations, ventObservations } = pendingActionLog;
            addLogMessage(`[Step ${data.timestep}] ${message}`, type);
            observations?.forEach(observation => addLogMessage(`[Step ${data.timestep}] ${observation}`, 'info'));
            ventObservations?.forEach(observation => addLogMessage(`[Step ${data.timestep}] ${observation}`, 'danger'));
            pendingActionLog = null;
        }

        if (data.phase !== "meeting") {
            await refreshRoomContext();
            await updateMapUI();
        }
    }

    // Phase Transition Logic. Task -> Meeting
    if (data.phase !== lastPhase) {
        lastPhase = data.phase;
        await handleGlobalPhaseTransition(data);
    }

    if (data.phase === "meeting") {
        renderMeetingChat(data.meeting_messages);
        updateMeetingUI(data);
        // The background game_step handles all AI and human turns during meetings.
        // No nudge needed here.
    }
}

// --- PHASE TRANSITIONS ---

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
        processedMessageCount = 0;
        chatInputLocked = false;
        lastDiscussionTurnSeq = -1;
        pendingActionLog = null;
        // Start 10 second countdown timer
        startMeetingCountdown();
    }

    else if (phase === "task") {
        // Cancel any in-progress countdown if available
        if (meetingCountdownTimer !== null) {
            clearTimeout(meetingCountdownTimer);
            meetingCountdownTimer = null;
        }
        // Ejection results
        if (vote_result !== undefined && vote_result !== null) {
            showEjectionBanner(vote_result);
            await new Promise(timer => setTimeout(timer, 5000)); // Show results for 5s
            if (lastPhase !== "task"){
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
    if (meetingCountdownTimer !== null) {
        clearTimeout(meetingCountdownTimer);
        meetingCountdownTimer = null;
    }

    function countDown(secondsLeft) {
        const countdownText = document.getElementById('meeting-countdown-text');
        if (countdownText){
            countdownText.innerText = `Emergency meeting starting in ${secondsLeft}s...`;
        }

        if (secondsLeft <= 0) {
            meetingCountdownTimer = null;
            const overlay = document.getElementById('meeting-overlay');
            if (overlay){
                overlay.classList.remove('d-none');
            }
            apiFetch('/api/next-step', { method: 'POST' }); // intentionally not awaited
            return;
        }
        // Recursively call countDown until 0
        meetingCountdownTimer = setTimeout(() => countDown(secondsLeft - 1), 1000);
    }

    countDown(10);
}

// --- MEETING ---

// Manages transition between chat and voting views
// Called each time the meeting-context poll returns updated status
function updateMeetingUI(data) {
    const chatInputGroup = document.getElementById('chat-input-group');
    const votingRoster = document.getElementById('voting-roster-container');
    const sendBtn = document.getElementById('send-chat-btn');
    const chatInput = document.getElementById('chat-input');

    if (data.is_my_turn) {
        const meetingOverlayEl = document.getElementById('meeting-overlay');
        if (meetingOverlayEl && meetingOverlayEl.classList.contains('d-none')) {
            meetingOverlayEl.classList.remove('d-none');
        }
        
        if (data.discussion_turn_seq !== lastDiscussionTurnSeq) {
            chatInputLocked = false;
        }

        if (data.can_vote && data.is_alive) {
            // Voting phase: hide chat, show voting roster
            if (chatInputGroup) chatInputGroup.style.display = 'none';
            if (votingRoster && votingRoster.innerHTML.trim() === '') {
                populateVotingRoster();
            }
        }
        else if (!chatInputLocked) {
            // Discussion phase: show turn prompt and chat input
            const turnPrompt = document.getElementById('turn-prompt');
            if (turnPrompt) {
                turnPrompt.style.display = 'block';
                turnPrompt.innerText = data.is_alive ? "It's your turn to speak." : "You are a ghost. Pass your turn.";
            }
            if (chatInputGroup) chatInputGroup.style.display = 'flex';
            if (sendBtn) {
                sendBtn.disabled = false;
                sendBtn.innerText = data.is_alive ? "Send" : "Pass Turn";
            }
            if (chatInput && !data.is_alive) {
                chatInput.value = "Observing Discussion...";
                chatInput.disabled = true;
            } else if (chatInput) {
                chatInput.disabled = false;
            }
        }
    }
    // Not your turn
    else {
        const turnPrompt = document.getElementById('turn-prompt');
        if (turnPrompt) turnPrompt.style.display = 'none';
        if (chatInputGroup) chatInputGroup.style.display = 'none';
    }

    lastDiscussionTurnSeq = data.discussion_turn_seq;
}


// Create and handle voting roster during voting phase
async function populateVotingRoster() {
    const response = await apiFetch('/api/player-states');
    const data = await response.json();
    const container = document.getElementById('voting-roster-container');
    const userDisplayEl = document.getElementById('user-display');
    const myColor = userDisplayEl ? userDisplayEl.innerText.toLowerCase() : "";
    if (!container || !data.players){
        return;
    }
    container.innerHTML = '';

    data.players.forEach(player => {
        if (player.color === myColor){
            return;
        }

        if (!player.is_alive){
            return;
        }

        const btn = document.createElement('button');
        btn.className = 'list-group-item list-group-item-action bg-dark text-light border-secondary d-flex align-items-center mb-1';
        btn.style.cursor = "pointer";
        btn.innerHTML = `<img src="/static/assets/player_${player.color}.png" style="width: 30px; margin-right: 15px;"><span>Vote for <strong>${player.name}</strong></span>`;

        // Handles voting when target is clicked
        btn.onclick = async () => {
            container.querySelectorAll('button').forEach(b => b.disabled = true);
            btn.classList.add('bg-danger', 'text-white');
            await apiFetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: player.color })
            });
        };
        container.appendChild(btn);
    });

    const skipBtn = document.getElementById('skip-vote-btn');
    if (skipBtn) {
        skipBtn.onclick = async () => {
            container.querySelectorAll('button').forEach(b => b.disabled = true);
            skipBtn.disabled = true;
            await apiFetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: "none" })
            });
        };
    }
}

// Handles the Send / Pass Turn button in the discussion panel.
// Alive players submit a chat message
// Ghosts send a nudge to pass their turn.
async function handleSendChat() {
    const isGhost = chatInput.disabled || chatInput.value === "Observing Discussion...";
    const message = chatInput.value.trim();

    // Alive players must type something before submitting
    if (!isGhost && !message){
        return;
    }

    // Lock the input — the meeting game_step is long-running; we just queue the action and wait.
    // renderMeetingChat will unlock once others' messages arrive.
    chatInputLocked = true;
    sendChatBtn.disabled = true;
    sendChatBtn.innerText = "Sent! Waiting...";
    if (chatInput) chatInput.disabled = true;

    try {
        if (!isGhost) {
            // Queue the speak action — the running game_step picks it up automatically
            await apiFetch('/api/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });
            chatInput.value = '';
        }
        else {
            // Ghost mode: queue a nudge action
            await apiFetch('/api/set-nudge', { method: 'POST' });
        }
        // No /api/next-step here — the meeting game_step is already running as a background task.
        // The periodic broadcast loop will push state updates as agents act.
    }
    catch (error) {
        console.error("Chat Error:", error);
        // Unlock on error so the player can retry
        chatInputLocked = false;
        sendChatBtn.disabled = false;
        sendChatBtn.innerText = isGhost ? "Pass Turn" : "Send";
        if (chatInput) chatInput.disabled = false;
    }
}

// --- GAME UI ---

// Create and show role reveal modal in UI
function showRoleReveal(role, color){
    const roleDisplay = document.getElementById('role-display');
    const colorDisplay = document.getElementById('color-name-display');
    const imgDisplay = document.getElementById('color-img-display');
    const userDisplay = document.getElementById('user-display');
    if (roleDisplay){
        roleDisplay.innerText = role;
        // Assign role display color as red for impostor, blue for crewmate
        roleDisplay.className = `display-3 fw-bold text-uppercase mb-5 ${role.toLowerCase() === 'impostor' ? 'text-danger' : 'text-info'}`;
    }
    if (colorDisplay){
        colorDisplay.innerText = formatColorName(color);
        colorDisplay.style.color = displayColor(color);
    }
    if (imgDisplay){
        imgDisplay.src = `/static/assets/player_${color.toLowerCase()}.png`;
    }
    if (userDisplay){
        userDisplay.innerText = formatColorName(color);
    }
    const roleModal = new bootstrap.Modal(document.getElementById('role-reveal-modal'));

    roleModal.show();
}

// Updates UI related to task bar progress (tasks completed / total tasks)
function updateTaskProgressBar(progress_dec) {
    const progressBar = document.getElementById('total-task-bar');
    const progressText = document.getElementById('task-percent-text');

    if (!progressBar || !progressText){
        return;
    }

    // Convert dec to int
    const percentage = Math.min(100, Math.max(0, Math.round(progress_dec * 100)));

    // Fill bar
    progressBar.style.width = `${percentage}%`;
    progressText.innerText = `${percentage}%`;

    progressBar.classList.add('bg-success');
}

// Fetch and update ROOM CONTEXT (movement options, tasks available, and who is in the room with you)
async function refreshRoomContext() {

    // Data Acquisition
    const response = await apiFetch('/api/room-context');
    const data = await response.json();
    const isAlive = data.is_alive;

    // --- Global UI State ---
    if (gameStarted && lastPhase !== "meeting") {
        if (actionPanel) actionPanel.classList.remove('d-none');
    }

    // --- Update Location, Timestep, Phase ---
    document.getElementById('location-display').innerText = data.current_room;
    document.getElementById('step-counter').innerText = data.timestep;
    const phaseDisplayEl = document.getElementById('current-phase');

    if (data.phase.toLowerCase() === "meeting"){
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = "MEETING CALLED!";
            phaseDisplayEl.className = "text-danger fw-bold";
        }
    }
    else{
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = isAlive ? "Active" : "Spectating as Ghost";
            phaseDisplayEl.className = "text-success fw-bold";
        }
    }

    // --- Personal Task Tracking ---
    // Renders the persistent list of TODO tasks for the human player
    const personalTasksList = document.getElementById('personal-tasks');
    if (personalTasksList){
        personalTasksList.innerHTML = '';
        if (data.personal_tasks.length === 0){
            personalTasksList.innerHTML= '<li class="list-group-item text-dark bg-transparent">No tasks left!</li>';
        }
        else{
            data.personal_tasks.forEach(task => {
                const li = document.createElement('li');
                li.className = 'list-group-item py-1 text-dark fw-bold';
                const location = data.task_locations[task.name] || "Unknown";
                const progress = task.max_duration > 1 ? ` (${task.steps_done}/${task.max_duration})` : ''; // Some tasks have duration > 1
                li.innerText = `${task.name}${progress} - ${location}`;
                personalTasksList.appendChild(li);
            })
        }
    }

    // --- In Current Room Task Tracking ---
    // Generates buttons for tasks specifically available in the current room
    const tasksInRoom = document.getElementById('task-list');
    if (tasksInRoom) {
        tasksInRoom.innerHTML = '';
        data.tasks_in_room.forEach(taskName => {
            const btn = document.createElement('button');
            const taskInfo = data.personal_tasks.find(t => t.name === taskName);
            if (taskInfo) {
                const progress = taskInfo.max_duration > 1 ? ` (${taskInfo.steps_done}/${taskInfo.max_duration})` : '';
                btn.className = 'btn-task';
                btn.innerText = `✓ ${taskName}${progress}`;
                btn.onclick = () => completeTask(taskName);
            }
            else {
                btn.className = 'btn-task unavailable';
                btn.innerText = taskName;
                btn.disabled = true;
            }
            tasksInRoom.appendChild(btn);
        });
    }

    // --- IMPOSTOR MECHANICS (VENTING)
    const ventPanel = document.getElementById('vent-panel');
    const ventContainer = document.getElementById('vent-options');
    const roleDisplayEl = document.getElementById('role-display');
    const isImpostor = roleDisplayEl && roleDisplayEl.innerText.toLowerCase() === 'impostor';

    if (isImpostor && isAlive){
        const ventResponse = await fetch ('/api/vent-options');
        const ventData = await ventResponse.json();

        if (ventData.can_vent){
            if (ventPanel){
                ventPanel.classList.remove('d-none');
            }

            // Contains all vent target rendered buttons
            if (ventContainer) {
                ventContainer.innerHTML= '';
                ventData.options.forEach(room => {
                    const btn = document.createElement('button');
                    btn.className = 'btn-vent';
                    btn.innerText = room.replace(/_/g, ' ');
                    btn.onclick = () => {
                        ventContainer.querySelectorAll('button').forEach(b => b.disabled = true);
                        performVent(room);
                    };
                    ventContainer.appendChild(btn);
                });
            }
        }

        // Cannot Vent - No Targets
        else{
            if (ventPanel){
                ventPanel.classList.add('d-none');
            }
        }
    }

    // Cannot Vent - Dead or Crewmate
    else{
        if (ventPanel) ventPanel.classList.add('d-none');
    }


    // --- MOVEMENT NAVIGATION ---
    // Render buttons for all adjacent rooms the player can walk to
    const moveContainer = document.getElementById('movement-options');
    if (moveContainer) {
        moveContainer.innerHTML = '';
        data.adjacent.forEach(room => {
            const btn = document.createElement('button');
            btn.className = 'btn-move';
            btn.innerText = room.replace(/_/g, ' ');
            btn.onclick = () => performMove(room);
            moveContainer.appendChild(btn);
        });
    }

    // --- LOCAL PLAYER LIST ---
    const playersInRoomList = document.getElementById('players-in-room-list');
    const reportBtn = document.getElementById('report-btn');
    const humanRole = roleDisplayEl ? roleDisplayEl.innerText.toLowerCase() : "";
    let freshBodyFound = false;

    if (playersInRoomList){
        playersInRoomList.innerHTML= '';
        if (data.players_in_room.length === 0){
            playersInRoomList.innerHTML = '<li class="list-group-item bg-dark text-white small"> You are alone here. </li>';
        }
        else{
            data.players_in_room.forEach(player => {
                const li = document.createElement('li');
                li.className = 'list-group-item bg-dark border-secondary d-flex align-items-center';
                if (player.is_alive){

                    // Reveal fellow impostors
                    const impostorTag = (humanRole === 'impostor' && player.identity === 'Impostor')
                        ? '<span class="text-danger small fw-bold ms-2">(Impostor)</span>' : '';
                    li.innerHTML = `<img src="/static/assets/player_${player.color}.png" title="${player.name}" style="width: 35px; height: 35px;">${impostorTag}<span class="ms-2">${player.name}</span>`;
                    // If you're the impostor, create kill btn pinned to right
                    if (humanRole === 'impostor' && isAlive){
                        const killBtn = document.createElement('button');
                        killBtn.className = 'btn-kill';
                        killBtn.innerText = '☠ KILL';
                        killBtn.onclick = () => performKill(player.color);
                        li.appendChild(killBtn);
                    }
                }
                // Handle corpse detection
                // Only render fresh unreported bodies
                else if (!player.reported_death){
                    freshBodyFound = true;
                    li.classList.add('text-muted');
                    li.innerHTML = `<img src="/static/assets/player_${player.color}.png" title="${player.name} (Dead)" style="width: 35px; height: 35px; opacity: 0.5; transform: rotate(90deg);"> <span class="ms-2 small">(Dead)</span>`;
                }
                else {
                    return; // Reported dead body. Skip.
                }
                playersInRoomList.appendChild(li);
            });
        }
    }

    // --- REPORTING DEAD BODIES ---
    if (reportBtn){
        if (freshBodyFound && isAlive){
            reportBtn.classList.remove('disabled');
            reportBtn.style.opacity = '1';
            reportBtn.onclick = () => triggerReport();
        }

        else{
            reportBtn.classList.add('disabled');
            reportBtn.style.opacity = '0.5';
            reportBtn.onclick = null;
        }
    }
}

// Adds player sprites to room with jitter for visual indicator of who is present
async function updateMapUI() {
    try {
        const response = await apiFetch('/api/player-states');
        const data = await response.json();
        const roomContextResponse = await apiFetch('/api/room-context');
        const contextData = await roomContextResponse.json();

        if (data.error){
            return;
        }

        const roomView = document.getElementById('room-view');
        const roomPlayerLayer = document.getElementById('room-player-layer');
        const skeldLayer = document.getElementById('skeld-player-layer');
        const locationHeader = document.getElementById('location-header');

        if (locationHeader){
            locationHeader.innerText = contextData.current_room;
        }

        const formattedRoom = contextData.current_room.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join('_');
        const bgPath = `/static/assets/The_Skeld_${formattedRoom}.webp`;

        if (roomView){
            roomView.style.backgroundImage = `url('${bgPath}')`;
            roomView.style.backgroundSize = 'cover';
            roomView.style.backgroundPosition = 'center';
        }

        if (skeldLayer){
            skeldLayer.innerHTML = ''
        }
        if (roomPlayerLayer){
            roomPlayerLayer.innerHTML = '';
            }

        const currentRoomStr = contextData.current_room.toLowerCase();
        const userDisplayEl = document.getElementById('user-display');
        const myColor = userDisplayEl ? userDisplayEl.innerText.toLowerCase() : "";

        // Render player images over minimap and room map with jitter
        data.players.forEach(player => {
            const playerLoc = player.location.toLowerCase();

            const isStaleCorpse = !player.is_alive && player.reported_death && player.color !== myColor;
            if (isStaleCorpse) return;

            // FOR MASTER VIEW OR GHOST MODE - Delete master view later
            if (skeldLayer){
                const coords = roomCoordinates[playerLoc];
                if (coords){
                    const miniImg = document.createElement('img');
                    miniImg.src = `/static/assets/player_${player.color}.png`;
                    miniImg.style.position = 'absolute';
                    const miniJitterX = (Math.random() * 4) - 2;
                    const miniJitterY = (Math.random() * 4) - 2;
                    miniImg.style.top = `${coords.top + miniJitterY}%`;
                    miniImg.style.left = `${coords.left + miniJitterX}%`;
                    miniImg.style.width = '40px';
                    miniImg.style.transform = 'translate(-50%, -50%)';
                    if (!player.is_alive) {
                        miniImg.style.filter = "grayscale(100%) opacity(0.5)";
                        miniImg.style.transform = "translate(-50%, -50%) rotate(90deg)";
                    }
                    miniImg.style.zIndex = '10'
                    skeldLayer.appendChild(miniImg);
                }
            }

            if (playerLoc === currentRoomStr && roomPlayerLayer) {
                const img = document.createElement('img');
                img.src = `/static/assets/player_${player.color}.png`;
                img.className = 'player-sprite';
                const horizontalPos = 20 + (Math.random() * 60);
                const verticalPos = 40 + (Math.random() * 40);
                img.style.position = 'absolute';
                img.style.top = `${verticalPos}%`;
                img.style.left = `${horizontalPos}%`;
                img.style.width = '50px';
                if (!player.is_alive) {
                    img.style.filter = "grayscale(100%) brightness(70%)";
                    img.style.transform = "translate(-50%, -50%) rotate(90deg)";
                    img.style.opacity = "0.8";
                }
                else {
                    img.style.transform = "translate(-50%, -50%)";
                }
                img.style.transition = 'all 0.5s ease';
                img.title = player.name;
                roomPlayerLayer.appendChild(img);
            }
        });
    }
    catch (error) {
        console.error("Failed to update Room UI:", error);
    }
}

// --- PLAYER ACTIONS ---

async function performMove(destination) {
    const source = document.getElementById('location-display')?.innerText || 'Unknown';
    if (!lockActions()){
        return;
    }
    try {
        const response = await apiFetch('/api/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination: destination })
        });
        // Construct Game Logs
        if (response.ok) {
            const data = await response.json();
            // Waiting for other players to act
            if (data.status === "pending") {
                waitingForStep = true;
                pendingActionLog = { message: `You moved from ${source} to ${destination}`, type: 'info', observations: [], ventObservations: [] };
                document.getElementById('waiting-indicator')?.classList.remove('d-none');
                return;
            }
            lastTimestep = data.timestep;
            addLogMessage(`[Step ${data.timestep}] You moved from ${source} to ${destination}`, 'info');
            // Log who was seen leaving the room
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Step ${data.timestep}] ${observation}`, 'info');
                });
            }
            // Log who was seen venting from room
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(observation => {
                    addLogMessage(`[Step ${data.timestep}] ${observation}`, 'danger');
                });
            }


            await refreshRoomContext();
            await updateMapUI();
        }
    }
    catch (e) {
        console.error('performMove error:', e);
    }
    finally {
        if (!waitingForStep){
            unlockActions();
        }
    }
}

async function performVent(destination) {
    if (!lockActions()){
        return;
    }
    try {
        const response = await apiFetch('/api/vent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination: destination })
        });

        if (response.ok) {
            const data = await response.json();
            if (data.status === "pending") {
                waitingForStep = true;
                pendingActionLog = { message: `You vented to ${destination}`, type: 'danger', observations: [], ventObservations: [] };
                document.getElementById('waiting-indicator')?.classList.remove('d-none');
                return;
            }
            lastTimestep = data.timestep;
            addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'danger');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Step ${data.timestep}] ${observation}`, 'info');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(`[Step ${data.timestep}] ${obs}`, 'danger');
                });
            }

            await refreshRoomContext();
            await updateMapUI();
        }
    }
    catch (e) {
        console.error('performVent error:', e);
    }
    finally {
        if (!waitingForStep){
            unlockActions();
        }
    }
}

async function completeTask(taskName) {
    if (!lockActions()){
        return;
    }
    try {
        const response = await apiFetch('/api/do-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: taskName })
        });

        if (response.ok) {
            const data = await response.json();
            if (data.status === "pending") {
                waitingForStep = true;
                pendingActionLog = { message: `Working on ${taskName}...`, type: 'success', observations: [], ventObservations: [] };
                document.getElementById('waiting-indicator')?.classList.remove('d-none');
                return;
            }
            lastTimestep = data.timestep;
            addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'success');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Step ${data.timestep}] ${observation}`, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(`[Step ${data.timestep}] ${obs}`, 'danger');
                });
            }

            await refreshRoomContext();
            await updateMapUI();
        }
    }
    catch (e) {
        console.error('completeTask error:', e);
    }
    finally {
        if (!waitingForStep){
            unlockActions();
        }
    }
}

async function triggerReport() {
    if (!lockActions()){
        return;
    }
    try {
        const response = await apiFetch('/api/report', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'danger');
        }
    }
    catch (e) {
        console.error('triggerReport error:', e);
    }
    finally {
        unlockActions();
    }
}

async function performKill(targetColor){
    if (!lockActions()){
        return;
    }
    try {
        const response = await apiFetch('/api/kill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: targetColor })
        });

        if (response.ok){
            const data = await response.json();
            if (data.status === "pending") {
                waitingForStep = true;
                pendingActionLog = { message: `You killed ${formatColorName(targetColor)}`, type: 'danger', observations: [], ventObservations: [] };
                document.getElementById('waiting-indicator')?.classList.remove('d-none');
                return;
            }
            lastTimestep = data.timestep;
            addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'danger');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Step ${data.timestep}] ${observation}`, 'info');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(`[Step ${data.timestep}] ${obs}`, 'danger');
                });
            }

            await refreshRoomContext();
            await updateMapUI();
        }
    }
    catch (e) {
        console.error('performKill error:', e);
    }
    finally {
        if (!waitingForStep){
            unlockActions();
        }
    }
}

// --- Begin JS Logic ---
document.addEventListener('DOMContentLoaded', () => {

    // --- DOM Refs ---
    actionPanel = document.getElementById('action-panel');
    phaseDisplay = document.getElementById('current-phase');
    sendChatBtn = document.getElementById('send-chat-btn');
    chatInput = document.getElementById('chat-input');

    const lobbyScreen = document.getElementById('lobby-screen-wrapper');
    const gameScreen = document.getElementById('game-screen');
    const userDisplay = document.getElementById('user-display');

    // Lobby Screen Panels
    const matchmakingPanel = document.getElementById('matchmaking-panel');
    const browsePanel = document.getElementById('browse-panel');
    const waitingPanel = document.getElementById('waiting-panel');
    const readyChecklist = document.getElementById('ready-checklist');
    const startGameBtn = document.getElementById('start-game-btn');
    const waitingHint = document.getElementById('waiting-hint');

    // --- Game Size selector (host only) ---
    const sizeButtons = document.querySelectorAll('#count-selector .btn');
    sizeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            sizeButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // --- Render Waiting Room Roster ---
    function renderWaitingRoster(roster, myColor) {
        if (!readyChecklist){
            return;
        }
        readyChecklist.innerHTML = '';

        roster.forEach(player => {
            const li = document.createElement('li');
            li.className = 'list-group-item bg-dark text-light d-flex justify-content-between align-items-center';
            const isMe = player.color === myColor;
            const label = isMe ? `${player.name} (you)` : player.name;
            const badge = player.is_human ? `<span class="badge bg-success">Joined</span>` : `<span class="badge bg-secondary">Waiting...</span>`;
            li.innerHTML = `<span style="color:${displayColor(player.color)};font-weight:bold;">${label}</span>${badge}`;
            readyChecklist.appendChild(li);
        });
    }

    // --- Waiting Room after Joining or Hosting ---
    function enterWaitingRoom(data) {
        playerToken = data.token;
        myColor = data.color;
        myRole = data.role;
        connectWebSocket(); // establish connection for the game

        // Show user their color in the sidebar
        if (userDisplay){
            userDisplay.innerText = formatColorName(data.color);
        }
        if (phaseDisplay){
            phaseDisplay.innerText = "Staging";
        }

        renderWaitingRoster(data.roster, data.color);

        // Switch from main menu / browse games panel to the waiting room
        matchmakingPanel.classList.add('d-none');
        browsePanel.classList.add('d-none');
        waitingPanel.classList.remove('d-none');

        // Host sees Start Game button
        // Non-hosts see "waiting for host"
        if (data.is_host) {
            startGameBtn.classList.remove('d-none');
            startGameBtn.onclick = async () => {
                startGameBtn.disabled = true;
                startGameBtn.innerText = 'Starting...';
                await apiFetch('/api/start', { method: 'POST' });
            };
        }
        else {
            waitingHint.classList.remove('d-none');
        }
    }

    // --- Enter Game Screen ---
    // Host presses Start and all clients receive the game_started WS event.
    // Hides lobby, shows game screen, runs initial room and map fetch.
    async function enterGame(myColor) {
        if (lobbyScreen){
            lobbyScreen.classList.add('d-none');
        }
        if (gameScreen){
            gameScreen.classList.remove('d-none');
        }
        if (actionPanel) actionPanel.classList.add('d-none');
        showRoleReveal(myRole, myColor); // Role Modal
        gameStarted = true;
        addLogMessage(`Welcome to Skeld, ${formatColorName(myColor)}`, 'success');
        await apiFetch('/api/next-step', { method: 'POST' });
        await refreshRoomContext();
        await updateMapUI();
    }

    // --- WS: handle lobby events ---
    // Handles two specific lobby events
    // 1) lobby_update: someone new joined, re-render the roster
    // 2) game_started: host pressed start -> setup game
    window._wsLobbyHandler = async (msg) => {
        if (msg.type === 'lobby_update') {
            // New player joined. Rerender roster
            renderWaitingRoster(msg.roster, myColor);
        }
        else if (msg.type === 'game_started') {
            // Host pressed start, call enterGame
            await enterGame(myColor);
        }
    };

    // --- HOST GAME button ---
    const hostBtn = document.getElementById('host-btn');
    if (hostBtn) {
        hostBtn.addEventListener('click', async () => {
            const activeSize = document.querySelector('#count-selector .btn.active').dataset.value;
            hostBtn.disabled = true;
            hostBtn.innerText = 'Creating...';
            try {
                const response = await fetch('/api/host', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ size: activeSize }),
                });
                if (response.ok) {
                    const data = await response.json();
                    enterWaitingRoom(data);
                }
                // Re-enable if things break
                else {
                    hostBtn.disabled = false;
                    hostBtn.innerText = 'Host Game';
                }
            }catch (e) {
                console.error('Host error:', e);
                hostBtn.disabled = false;
                hostBtn.innerText = 'Host Game';
            }
        });
    }

    // --- BROWSE and BACK buttons ---
    // Browse switches to the lobby list panel and finds open games.
    const browseBtn = document.getElementById('browse-btn');
    const backBtn = document.getElementById('back-btn');
    const refreshBtn = document.getElementById('refresh-btn');

    async function loadLobbies() {
        const lobbyList = document.getElementById('lobby-list');
        if (!lobbyList){
            return;
        }
        lobbyList.innerHTML = '<p class="text-muted text-center small">Loading...</p>';
        try {
            const res = await fetch('/api/lobbies');
            const data = await res.json();
            lobbyList.innerHTML = '';
            if (data.lobbies.length === 0) {
                lobbyList.innerHTML = '<p class="text-muted text-center small">No open games.</p>';
                return;
            }
            // Host color, slot count, Join button
            data.lobbies.forEach(lobby => {
                const div = document.createElement('div');
                div.className = 'd-flex align-items-center justify-content-between p-2 mb-2 border border-secondary rounded';
                div.innerHTML = `
                    <div class="d-flex align-items-center gap-2">
                        <img src="/static/assets/player_${lobby.host_color}.png" style="width:30px;">
                        <span style="color:${displayColor(lobby.host_color)};font-weight:bold;">${formatColorName(lobby.host_color)}'s game</span>
                        <span class="text-muted small">${lobby.human_count}/${lobby.total_slots} players</span>
                    </div>
                    <button class="btn btn-sm btn-success fw-bold join-lobby-btn" data-code="${lobby.code}">Join</button>`;
                lobbyList.appendChild(div);
            });

            // Handle each join btn
            lobbyList.querySelectorAll('.join-lobby-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    btn.disabled = true;
                    btn.innerText = 'Joining...';
                    try {
                        const res = await fetch('/api/join', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ code: btn.dataset.code }),
                        });
                        const data = await res.json();
                        if (data.status === 'error') {
                            btn.disabled = false;
                            btn.innerText = 'Join';
                            return;
                        }
                        enterWaitingRoom(data);
                    }
                    catch (e) {
                        console.error('Join error:', e);
                        btn.disabled = false;
                        btn.innerText = 'Join';
                    }
                });
            });
        }
        catch (e) {
            lobbyList.innerHTML = '<p class="text-danger text-center small">Failed to load lobbies.</p>';
        }
    }

    if (browseBtn){
        browseBtn.addEventListener('click', () => {
        matchmakingPanel.classList.add('d-none');
        browsePanel.classList.remove('d-none');
        loadLobbies();
        });
    }

    if (backBtn){
        backBtn.addEventListener('click', () => {
        browsePanel.classList.add('d-none');
        matchmakingPanel.classList.remove('d-none');
    });
    }

    if (refreshBtn){
        refreshBtn.addEventListener('click', loadLobbies);
    }

    // --- Chat Handler ---
    if (sendChatBtn) {
        sendChatBtn.onclick = handleSendChat;
    }
});
