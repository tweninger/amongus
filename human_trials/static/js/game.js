// game.js

import { roomCoordinates } from "./config.js";
let isHumanReady = false;
let readyPlayers = 0;
let totalPlayers = 0;
let processedMessageCount = 0;
let stepInProgress = false;
let gameStarted = false

let stagingPanel, actionPanel, phaseDisplay, sendChatBtn, chatInput;
let lastPhase = "active";

// --- HELPERS ---
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

function getPlayerImg(color){
    return `/static/assets/player_${color.toLowerCase()}.png`;
}

// Simply capitalize a color string
function formatColorName(color){
    return color.charAt(0).toUpperCase() + color.slice(1).toLowerCase();
}

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
        colorDisplay.style.color = color;
    }
    if (imgDisplay){
        imgDisplay.src = getPlayerImg(color);
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

// Manage transition between game phases by resetting chat and voting UI for meetings
// OR refreshing room and map context for tasks
async function handleGlobalPhaseTransition(data) {
    handlePhaseChange(data.phase, data.is_alive);

    if (data.phase === "meeting") {
        const chatBox = document.getElementById('discussion-chat');
        const votingRoster = document.getElementById('voting-roster-container');
        if (chatBox){
            chatBox.innerHTML = '';
        }
        if (votingRoster){
            votingRoster.innerHTML = '';
        }
        processedMessageCount = 0;
    } 
    else if (data.phase === "task") {
        await refreshRoomContext();
        await updateMapUI();
    }
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
        msgDiv.style.cssText = `background-color: rgba(255,255,255,0.05); border-radius: 8px; border-left: 4px solid ${msg.sender_color};`;
        msgDiv.innerHTML = `
            <img src="/static/assets/player_${msg.sender_color}.png" style="width: 40px; height: 40px; margin-right: 12px; border-radius: 50%;">
            <div style="flex-grow: 1;">
                <div class="d-flex justify-content-between">
                    <strong style="color: ${msg.sender_color}; font-size: 0.85rem;">${msg.sender_name}</strong>
                    <small class="text-muted" style="font-size: 0.7rem;">Step ${msg.timestep}</small>
                </div>
                <p class="mb-0 text-light" style="font-size: 0.95rem;">${msg.text}</p>
            </div>`;
        chatBox.appendChild(msgDiv);
    });
    chatBox.scrollTop = chatBox.scrollHeight;
    processedMessageCount = messages.length;
}

// Manages transition between chat and voting views
// Unlocks interaction status when its the humans turn
function updateMeetingUI(data) {
    const chatInputGroup = document.getElementById('chat-input-group');
    const votingRoster = document.getElementById('voting-roster-container');
    const sendBtn = document.getElementById('send-chat-btn');
    const chatInput = document.getElementById('chat-input');
    const proceedBtnEl = document.getElementById('proceed-to-vote-btn');

    if (proceedBtnEl) {
        proceedBtnEl.disabled = false;
        proceedBtnEl.classList.remove('disabled');
    }

    if (data.is_my_turn) {

        // Only show voting roster if alive and can vote
        if (data.can_vote && data.is_alive){
            if (chatInputGroup){
                chatInputGroup.style.display = 'none';
            }
            if (votingRoster && votingRoster.innerHTML.trim() === ''){
                populateVotingRoster();
            }
        }

        // Human turn but not voting, re-show chatInputGroup for sending msgs
        else{
            if (chatInputGroup){
                chatInputGroup.style.display = 'flex';
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.innerText = data.is_alive ? "Send" : "Pass Turn"; // Ghosts / spectators see pass turn
                }

                if (chatInput && !data.is_alive){
                    chatInput.value = "Observing Discussion..."; // Ghosts / spectators see Observing Discussion and cant type in bar
                    chatInput.disabled = true;
                }
                else if (chatInput){
                    chatInput.disabled = false;
                }
            }
        }
        stepInProgress = false; // Turn Handover
    }
    // Hide send msg bar. Not human turn to vote or speak anymore.
    else {
        if (chatInputGroup){
            chatInputGroup.style.display = 'none';
        }
    }
}

// Nudge AI forward
async function executeAiStep() {
    if (stepInProgress){
        return;
    }
    stepInProgress = true;
    try {
        await fetch('/api/next-step', { method: 'POST' });
    }
    finally {
        stepInProgress = false;
    }
}


// Handles screen transitions when transitioning from active <-> meeting
function handlePhaseChange(newPhase, isAlive) {
    const actionPanelEl = document.getElementById('action-panel');
    const discussionPanelEl = document.getElementById('discussion-panel');
    const meetingOverlayEl = document.getElementById('meeting-overlay');
    const phaseDisplayEl = document.getElementById('current-phase');
    const chatInputGroupEl = document.getElementById('chat-input-group');
    const skipBtnEl = document.getElementById('skip-vote-btn');
    const proceedBtnEl = document.getElementById('proceed-to-vote-btn');

    if (newPhase.toLowerCase() === "meeting") {
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = "MEETING CALLED!";
            phaseDisplayEl.className = "text-danger fw-bold";
        }
        // Ghost logic for meetings. Must acknolwedge observe AI discussion.
        if (!isAlive) {
            if (chatInputGroupEl){
                chatInputGroupEl.style.display = 'none';
            }
            if (skipBtnEl){
                skipBtnEl.style.display = 'none';
            }
            if (proceedBtnEl) {
                proceedBtnEl.innerText = "Observe Discussion";
                proceedBtnEl.classList.remove('btn-primary');
                proceedBtnEl.classList.add('btn-info');
            }
        }
        else {
            // Re-show elements if player is alive
            if (chatInputGroupEl){
                chatInputGroupEl.style.display = 'flex';
            }
            if (skipBtnEl){
                skipBtnEl.style.display = 'block';
            }
            
            if (proceedBtnEl) {
                proceedBtnEl.innerText = "Proceed to Discussion";
                proceedBtnEl.classList.remove('btn-info');
                proceedBtnEl.classList.add('btn-primary');
            }
        }

        // Hide active game screen elements
        if (actionPanelEl){
            actionPanelEl.classList.add('d-none');
        }
        if (discussionPanelEl){
            discussionPanelEl.classList.remove('d-none');
        }

        // Nudge Handler
        if (proceedBtnEl) {
            proceedBtnEl.onclick = async () => {
                // Prevent double clicks
                proceedBtnEl.disabled = true;
                const originalText = proceedBtnEl.innerText;
                proceedBtnEl.innerText = "Waiting...";

                if (meetingOverlayEl){
                    meetingOverlayEl.classList.remove('d-none');
                }

                await fetch('/api/next-step', { method: 'POST' });

                // Re-enable after the fetch returns
                proceedBtnEl.disabled = false;
                proceedBtnEl.innerText = originalText;
            };
        }
    }
    // We are in active phase
    else {
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
            phaseDisplayEl.innerText = isAlive ? "Active" : "Spectating (Ghost Mode)";
            phaseDisplayEl.className = "text-success fw-bold";
        }
    }
}

// Fetch and update room context (movement options, tasks available, and who is in the room with you)
async function refreshRoomContext() {
    const response = await fetch('/api/room-context');
    const data = await response.json();

    const isAlive = data.is_alive;

    if (gameStarted) {
        if (actionPanel) actionPanel.classList.remove('d-none');
    } 
    else {
        if (actionPanel) actionPanel.classList.add('d-none');
    }

    // Update Location
    document.getElementById('location-display').innerText = data.current_room;

    // Update the Clock
    document.getElementById('step-counter').innerText = data.timestep;

    const phaseDisplayEl = document.getElementById('current-phase');

    if (data.phase.toLowerCase() === "meeting"){
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = "Meeting";
            phaseDisplayEl.className = "text-danger fw-bold";
        }
    }
    else{
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = isAlive ? "Active" : "Spectating as Ghost";
            phaseDisplayEl.className = "text-success fw-bold";
        }
    }

    // Render player's personal tasks
    const humanTasksList = document.getElementById('personal-tasks');
    if (humanTasksList){
        humanTasksList.innerHTML = '';
        if (data.personal_tasks.length === 0){
            humanTasksList.innerHTML= '<li class="list-group-item text-dark bg-transparent">No tasks left!</li>';
        }
        else{
            data.personal_tasks.forEach(task => {
                const li = document.createElement('li');
                li.className = 'list-group-item py-1 text-dark fw-bold';
                const location = data.task_locations[task] || "Unknown";
                li.innerText = `${task} - ${location}`;
                humanTasksList.appendChild(li);
            })
        }
    }

    // Update and render tasks - "What can I do here now?"
    const taskContainer = document.getElementById('task-list');    
    if (taskContainer) {
        taskContainer.innerHTML = '';
        data.tasks.forEach(taskName => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm text-start m-1';
            btn.innerText = taskName;

            if (data.personal_tasks.includes(taskName)){
                btn.classList.add('btn-outline-success');
                btn.onclick = () => completeTask(taskName);
            }
            else{
                btn.classList.add('btn-outline-secondary', 'disabled');
                btn.style.opacity = '0.5';
            }
            taskContainer.appendChild(btn);
        });
    }

    // Venting as Impostor Only
    const ventPanel = document.getElementById('vent-panel');
    const ventContainer = document.getElementById('vent-options');
    const roleDisplayEl = document.getElementById('role-display');
    const isImpostor = roleDisplayEl && roleDisplayEl.innerText.toLowerCase() === 'impostor';

    if (isImpostor && isAlive){
        const ventResponse = await fetch ('/api/vent-options');
        const ventData = await ventResponse.json();

        if (ventData.can_vent){
            if (ventPanel) ventPanel.classList.remove('d-none');
            
            if (ventContainer) {
                ventContainer.innerHTML= '';
                ventData.options.forEach(room => {
                    const btn = document.createElement('button');
                    btn.className = 'btn btn-danger btn-sm fw-bold';
                    btn.innerText = room.replace('_', ' ');
                    btn.onclick = () => {
                        ventContainer.querySelectorAll('button').forEach(b => b.disabled = true);
                        performVent(room);
                    };
                    ventContainer.appendChild(btn);
                });
            }
        }

        // Cannot Vent
        else{
            if (ventPanel) ventPanel.classList.add('d-none');
        }
    }

    // Dead or non-impostors can never vent
    else{
        if (ventPanel) ventPanel.classList.add('d-none');
    }

    // Update movement options
    const moveContainer = document.getElementById('movement-options');
    if (moveContainer) {
        moveContainer.innerHTML = '';
        data.adjacent.forEach(room => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-outline-info btn-sm m-1';
            btn.innerText = room;
            btn.onclick = () => performMove(room);
            moveContainer.appendChild(btn);
        });
    }

    // Render players in current room
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
                    li.innerHTML = `<img src="/static/assets/player_${player.color}.png" title="${player.name}" style="width: 35px; height: 35px;">`;

                    // If you're the impostor, create kill btn for each player in room
                    if (humanRole === 'impostor' && isAlive){
                        const killBtn = document.createElement('button');
                        killBtn.className = 'btn btn-danger btn-sm fw-bold';
                        killBtn.innerText = 'KILL!';
                        killBtn.onclick = () => performKill(player.color);
                        li.appendChild(killBtn);
                    }
                }

                // Render body in list as dead, flipped 90% and greyed out
                else{
                    if (!player.reported_death){
                        freshBodyFound = true;
                    }
                    li.classList.add('text-muted');
                    li.innerHTML = `<img src="/static/assets/player_${player.color}.png" title="${player.name} (Dead)" style="width: 35px; height: 35px; opacity: 0.5; transform: rotate(90deg);"> <span class="ms-2 small">(Dead)</span>`;
                }
                playersInRoomList.appendChild(li);
            });
        }
    }

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

async function performMove(destination) {
    const response = await fetch('/api/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination: destination })
    });

    if (response.ok) {
        const data = await response.json();
        addLogMessage(`[Step ${data.timestep}] Moved to ${destination}`, 'info');
        // Log who you saw leaving each room
        if (data.observations && data.observations.length > 0){
            data.observations.forEach(observation => {
                addLogMessage(observation, 'info');
            });
        }
        await refreshRoomContext();
        await updateMapUI();
    }
}

async function performVent(destination) {
    const ventContainer = document.getElementById('vent-options');
    if (ventContainer) {
        ventContainer.querySelectorAll('button').forEach(btn => btn.disabled = true);
    }
    const response = await fetch('/api/vent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination: destination })
    });

    if (response.ok) {
        const data = await response.json();
        addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'danger');
         if (data.observations && data.observations.length > 0){
            data.observations.forEach(observation => {
                addLogMessage(observation, 'info');
            });
        }
        await refreshRoomContext();
        await updateMapUI();
    }
}

async function completeTask(taskName) {
    const response = await fetch('/api/do-task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskName })
    });

    if (response.ok) {
        const data = await response.json();
        addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'success')
        // Log who you saw leaving each room
        if (data.observations && data.observations.length > 0){
            data.observations.forEach(observation => {
                addLogMessage(observation, 'warning');
            })
        }
        document.getElementById('step-counter').innerText = data.timestep;
        await refreshRoomContext();
        await updateMapUI();
    }
}

// Adds player sprites to room with jitter for visual indicator of who is present
async function updateMapUI() {
    try {
        const response = await fetch('/api/map-state');
        const data = await response.json();
        const roomContextResponse = await fetch('/api/room-context');
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

        // Render player images over minimap and room map with jitter
        data.players.forEach(player => {
            const playerLoc = player.location.toLowerCase();
            
            // FOR MASTER VIEW OR GHOST MODE - Modify later
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

async function triggerReport() {
    const response = await fetch('/api/report', { method: 'POST' });
    if (response.ok) {
        const data = await response.json();
        addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'danger');
        const phaseEl = document.getElementById('current-phase');
        if (data.new_phase === "meeting" && phaseEl) {
            phaseEl.innerText = "Meeting";
            phaseEl.className = "text-danger fw-bold";
        }
        await refreshRoomContext();
        await updateMapUI();
    }
}

async function performKill(targetColor){
    const response = await fetch('/api/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: targetColor })
    });

    if (response.ok){
        const data = await response.json();
        addLogMessage(`[Step ${data.timestep}] ${data.message}`, 'danger');
        await refreshRoomContext();
        await updateMapUI();
    }
}

async function populateVotingRoster() {
    const response = await fetch('/api/map-state');
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
            const voteResponse = await fetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: player.color })
            });
            // Transition back to active phase
            if (voteResponse.ok) {
                const overlay = document.getElementById('meeting-overlay');
                const discPanel = document.getElementById('discussion-panel');
                if (overlay){
                    overlay.classList.add('d-none');
                }
                if (discPanel){
                    discPanel.classList.add('d-none');
                }
                if (actionPanel){
                    actionPanel.classList.remove('d-none');
                }
                await refreshRoomContext();
                await updateMapUI();
                container.innerHTML = '';
            }
        };
        container.appendChild(btn);
    });

    // FIX
    const skipBtn = document.getElementById('skip-vote-btn');
    if (skipBtn) {
        skipBtn.onclick = async () => {
            container.querySelectorAll('button').forEach(b => b.disabled = true);
            skipBtn.disabled = true;
            const skipResponse = await fetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: "none" })
            });
            if (skipResponse.ok) {
                const overlay = document.getElementById('meeting-overlay');
                const discPanel = document.getElementById('discussion-panel');
                if (overlay){
                    overlay.classList.add('d-none');
                }
                if (discPanel){
                    discPanel.classList.add('d-none');
                }
                if (actionPanel){
                    actionPanel.classList.remove('d-none');
                }
                await refreshRoomContext();
                await updateMapUI();
                container.innerHTML = '';
            }
        };
    }
}


// Polls server every second
// Checks for game winner, tracks phase transitions, updates meeting UI + task progres
async function startPhaseWatcher() {
    setInterval(async () => {
        if (stepInProgress && lastPhase !== "meeting"){
            return;
        }
        try {
            const response = await fetch('/api/meeting-context');
            const data = await response.json();

            // Check for potential winner
            if (data.winner) {
                alert("GAME OVER: " + data.winner);
                window.location.reload();
                return;
            }

            // Check for phase changes
            if (data.phase !== lastPhase) {
                await handleGlobalPhaseTransition(data);
                lastPhase = data.phase;
            }

            if (data.phase === "meeting") {
                renderMeetingChat(data.meeting_messages);
                updateMeetingUI(data);

                // Only Auto-Run AI when its not human turn and we are not waiting for a response
                if (!data.is_my_turn && !stepInProgress && data.is_alive){
                    executeAiStep();
                }
            }

            // Task Progress
            else if (gameStarted) {
                const stateResponse = await fetch('/api/game-state');
                if (stateResponse.ok) {
                    const stateData = await stateResponse.json();
                    updateTaskProgressBar(stateData.task_progress);
                }
            }
        }
        catch (err) {
            console.error("Error with startPhaseWatcher:", err);
            stepInProgress = false; 
        }
    }, 1000);
}

// --- Begin JS Logic ---
document.addEventListener('DOMContentLoaded', () => {

    stagingPanel = document.getElementById('staging-panel');
    actionPanel = document.getElementById('action-panel');
    phaseDisplay = document.getElementById('current-phase');
    sendChatBtn = document.getElementById('send-chat-btn');
    chatInput = document.getElementById('chat-input');

    const startBtn = document.getElementById('start-btn');
    const playerCountDisplay = document.getElementById('player-count-display');
    const readyChecklist = document.getElementById('ready-checklist');
    const readyUpBtn = document.getElementById('ready-up-btn');
    const lobbyScreen = document.getElementById('lobby-screen');
    const gameScreen = document.getElementById('game-screen');
    const userDisplay = document.getElementById('user-display');

    // Waits random time, updates badge of AI player to ready, then increments readyCounter
    function simulateAiReady(playerId) {
        const delay = Math.floor(Math.random() * 7000) + 3000;
        setTimeout(() => {
            const badge = document.getElementById(`badge-${playerId}`);
            if (badge) {
                badge.className = 'badge bg-success';
                badge.innerText = 'Ready';
                readyPlayers++;
                checkAllReady(); 
            }
        }, delay);
    }

    // Move from Lobby / Staging screen to task screen and start the game
    async function checkAllReady() {
        if (readyPlayers === totalPlayers && isHumanReady) {
            const response = await fetch('/api/ready', { method: 'POST' });
            if (response.ok) {
                gameStarted = true;
                if (stagingPanel){
                    stagingPanel.classList.add('d-none');
                }
                if (actionPanel){
                    actionPanel.classList.remove('d-none');
                }
                const myTasks = document.getElementById('my-tasks-panel');
                if (myTasks){
                    myTasks.classList.remove('d-none');
                }
                if (phaseDisplay) {
                    phaseDisplay.innerText = "Active";
                    phaseDisplay.className = "text-success fw-bold";
                }
                addLogMessage('All players are ready. Game has started!', 'success');
                await refreshRoomContext(); 
                await updateMapUI();
            }
        }
    }

    const sizeButtons = document.querySelectorAll('#count-selector .btn');
    const updatePlayerCountDisplay = () => {
        const activeBtn = document.querySelector('#count-selector .btn.active');
        const totalPlayerCount = parseInt(activeBtn.innerText);
        if (playerCountDisplay){
            playerCountDisplay.innerText = `Current Setup ${totalPlayerCount} Players`;
        }
    };

    sizeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            sizeButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updatePlayerCountDisplay();
        });
    });

    if (startBtn) {
        startBtn.addEventListener('click', async () => {
            const activeSize = document.querySelector('#count-selector .btn.active').dataset.value;
            try {
                const response = await fetch('/api/join', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ size: activeSize})
                });

                if (response.ok) {
                    const data = await response.json();
                    if (userDisplay){
                        userDisplay.innerText = data.color.charAt(0).toUpperCase() + data.color.slice(1);
                    }
                    if (phaseDisplay){
                        phaseDisplay.innerText = "Staging";
                    }
                    showRoleReveal(data.role, data.color);
                    totalPlayers = data.roster.length;
                    if (readyChecklist) {
                        readyChecklist.innerHTML = ''; 
                        data.roster.forEach(player => {
                            const li = document.createElement('li');
                            li.className = 'list-group-item bg-dark text-light d-flex justify-content-between align-items-center';
                            li.id = `player-status-${player.id}`;
                            const nameLabel = player.is_human ? `${player.name} (me)` : player.name;
                            li.innerHTML = `<span style="color: ${player.color}; font-weight: bold;">${nameLabel}</span><span class="badge bg-secondary" id="badge-${player.id}">Waiting...</span>`;
                            readyChecklist.appendChild(li);

                            // Get AI to ready up, artificially adding delay
                            if (!player.is_human){
                                simulateAiReady(player.id);
                            }
                        });
                    }
                    // Human ready up
                    if (readyUpBtn) {
                        readyUpBtn.onclick = () => {
                            if (isHumanReady){
                                return;
                            }
                            isHumanReady = true;
                            const humanBadge = document.getElementById('badge-0');
                            if (humanBadge) {
                                humanBadge.className = 'badge bg-success';
                                humanBadge.innerText = 'Ready';
                            }
                            readyUpBtn.className = 'btn btn-success btn-lg w-100 disabled';
                            readyUpBtn.innerText = 'Waiting...';
                            readyPlayers++;
                            checkAllReady();
                        };
                    }

                    const enterMapBtn = document.getElementById('enter-map-btn');

                    // Load gameplay active phase screen
                    if (enterMapBtn) {
                        enterMapBtn.addEventListener('click', async () => {
                            if (lobbyScreen) lobbyScreen.classList.add('d-none');
                            if (gameScreen) gameScreen.classList.remove('d-none');
                            gameStarted = false;
                            const myTasks = document.getElementById('my-tasks-panel');
                            if (myTasks) myTasks.classList.add('d-none');
                            if (actionPanel) actionPanel.classList.add('d-none');
                            await fetch('/api/next-step', { method: 'POST' });
                            await refreshRoomContext();
                            await updateMapUI();
                        });
                    }
                    addLogMessage(`Welcome to Skeld, ${data.color.charAt(0).toUpperCase() + data.color.slice(1)}`, 'success');
                }
            }
            catch (error) {
                console.error("Failed to start:", error);
            }
        });
    }

    if (sendChatBtn) {
        sendChatBtn.onclick = async () => {
            const isGhost = chatInput.disabled || chatInput.value === "Observing Discussion...";
            const message = chatInput.value.trim();

            // Living players must have a msg before clicking send
            if (!isGhost && !message){
                return;
            }
            sendChatBtn.disabled = true;
            sendChatBtn.innerText = "Wait...";

            try{
               // Submit human msg to discussion log
               if (!isGhost) {
                    await fetch('/api/speak', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: message })
                    });
                    chatInput.value = '';
                }
                else{
                    // Ghost mode: Send nudge to pass turn
                    await fetch('/api/set-nudge', { method: 'POST' });
                }
                // Step game engine
                stepInProgress = true;
                await fetch('/api/next-step', { method: 'POST' });

                // Reset interaction state and lock for next turn
                stepInProgress = false;
                sendChatBtn.disabled = false;
                sendChatBtn.innerText = isGhost ? "Pass Turn" : "Send";
            }
            catch(error){
                console.error("Chat Error:", error);
                sendChatBtn.disabled = false;
                sendChatBtn.innerText = isGhost ? "Pass Turn" : "Send";
            }
        };
    }
    startPhaseWatcher();
});