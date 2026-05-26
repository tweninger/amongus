// actions.js
// This file contains functions for all player actions (move, vent, kill, report, call meeting, do task) and the main function to refresh room context and update UI based on server responses.
// Each action function follows a similar pattern of locking actions, sending request to server, handling pending states, logging results, refreshing UI, and unlocking actions.
import { state } from './state.js';
import { apiFetch, lockActions, unlockActions, addLogMessage, formatColorName } from './helpers.js';
import { updateMapUI } from './ui.js';

// Fetch and update ROOM CONTEXT
//movement options, tasks available, and who is in the room with you
async function refreshRoomContext() {
    const response = await apiFetch('/api/room-context');
    const data = await response.json();
    const isAlive = data.is_alive;

    if (state.gameStarted && data.phase.toLowerCase() !== "meeting") {
        if (state.actionPanel) state.actionPanel.classList.remove('d-none');
    }

    // Update location, adjacent rooms, tasks, and players in room based on server response
    document.getElementById('location-display').innerText = data.current_room;
    document.getElementById('step-counter').innerText = data.timestep;
    const phaseDisplayEl = document.getElementById('current-phase');

    // Meeting started
    if (data.phase.toLowerCase() === "meeting"){
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = "MEETING CALLED!";
            phaseDisplayEl.className = "text-danger fw-bold";
        }
    }
    // Normal gameplay, task phase
    else{
        if (phaseDisplayEl) {
            phaseDisplayEl.innerText = isAlive ? "Active" : "Spectating as Ghost";
            phaseDisplayEl.className = "text-success fw-bold";
        }
    }

    // --- Task Tracking ---
    // Renders the persistent list of TODO tasks for the human player
    const personalTasksList = document.getElementById('personal-tasks');
    if (personalTasksList){
        personalTasksList.innerHTML = '';
        if (data.personal_tasks.length === 0){
            personalTasksList.innerHTML= '<li class="list-group-item text-white bg-transparent">No tasks left!</li>';
        }
        else{
            data.personal_tasks.forEach(task => {
                const li = document.createElement('li');
                li.className = 'list-group-item py-1 text-white fw-bold';
                const location = task.location || "Unknown";
                const progress = task.max_duration > 1 ? ` (${task.steps_done}/${task.max_duration})` : ''; // Some tasks have duration > 1
                li.innerText = `${task.name}${progress} - ${location}`;
                personalTasksList.appendChild(li);
            })
        }
    }

    // Generates buttons for tasks specifically available in the current room
    const tasksInRoom = document.getElementById('task-list');
    if (tasksInRoom) {
        tasksInRoom.innerHTML = '';
        data.tasks_in_room.forEach(taskName => {
            const btn = document.createElement('button');
            const taskInfo = data.personal_tasks.find(task => task.name === taskName && task.location === data.current_room);
            if (taskInfo) {
                const progress = taskInfo.max_duration > 1 ? ` (${taskInfo.steps_done}/${taskInfo.max_duration})` : ''; // Progress on long tasks
                btn.className = 'btn-task';
                btn.innerText = `${taskName}${progress}`;
                btn.disabled = state.actionLocked;
                btn.onclick = () => {
                    btn.classList.add('btn-submitted');
                    completeTask(taskName);
                };
            }
            else {
                btn.className = 'btn-task unavailable';
                btn.innerText = taskName;
                btn.disabled = true;
            }
            tasksInRoom.appendChild(btn);
        });
    }

    // --- IMPOSTOR MECHANICS (Venting) ---
    const ventPanel = document.getElementById('vent-panel');
    const ventContainer = document.getElementById('vent-options');
    const roleDisplayEl = document.getElementById('role-display');
    const isImpostor = roleDisplayEl && roleDisplayEl.innerText.toLowerCase() === 'impostor';

    if (isImpostor && isAlive){
        const ventResponse = await apiFetch('/api/vent-options');
        const ventData = await ventResponse.json();

        if (ventData.can_vent){
            // Show vent panel
            if (ventPanel){
                ventPanel.classList.remove('d-none');
            }

            // Render vent options as buttons if available
            if (ventContainer) {
                ventContainer.innerHTML= '';
                ventData.options.forEach(room => {
                    const btn = document.createElement('button');
                    btn.className = 'btn-vent';
                    btn.innerText = room.replace(/_/g, ' '); // Replace _ with spaces
                    btn.disabled = state.actionLocked;
                    btn.onclick = () => {
                        btn.classList.add('btn-submitted');
                        ventContainer.querySelectorAll('button').forEach(b => b.disabled = true); // Lock vent buttons to prevent repeated presses
                        performVent(room);
                    };
                    ventContainer.appendChild(btn);
                });
            }
        }

        // Cannot Vent. No Targets
        else{
            if (ventPanel) ventPanel.classList.add('d-none');
            
        }
    }

    // Cannot Vent. Dead or Crewmate
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
            btn.disabled = state.actionLocked; // Disable if locked to prevent repeated presses
            btn.onclick = () => {
                btn.classList.add('btn-submitted');
                performMove(room);
            };
            moveContainer.appendChild(btn);
        });
    }

    // --- PLAYERS IN ROOM LIST ---
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
                    li.innerHTML = `<img src="/assets/player_sprites/alive/player_${player.color}.png" title="${player.name}" style="width: 35px; height: 35px;">${impostorTag}<span class="ms-2">${player.name}</span>`;
                    // If you're the impostor, create kill btn pinned to right
                    if (humanRole === 'impostor' && isAlive){
                        const killBtn = document.createElement('button');
                        killBtn.className = 'btn-kill';
                        killBtn.innerText = 'KILL';
                        killBtn.disabled = state.actionLocked;
                        killBtn.onclick = () => {
                            killBtn.classList.add('btn-submitted');
                            performKill(player.color);
                        };
                        li.appendChild(killBtn);
                    }
                }
                // Handle corpse detection
                // Only render fresh unreported bodies
                else if (!player.reported_death){
                    freshBodyFound = true;
                    li.classList.add('text-muted');
                    li.innerHTML = `<img src="/assets/player_sprites/dead/${player.color}_body.png" title="${player.name} (Dead)" style="width: 35px; height: 35px; object-fit: contain;"> <span class="ms-2 small">(Dead)</span>`;
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

    // --- EMERGENCY MEETING BUTTON (Cafeteria only, limited uses) ---
    const emergencyBtn = document.getElementById('emergency-btn');
    if (emergencyBtn) {
        if (data.can_call_meeting) {
            emergencyBtn.classList.remove('d-none');
            emergencyBtn.disabled = state.actionLocked;
            emergencyBtn.onclick = () => {
                emergencyBtn.classList.add('btn-submitted');
                triggerEmergencyMeeting();
            };
        }
        else {
            emergencyBtn.classList.add('d-none');
        }
    }

    return data;
}

// --- PLAYER ACTIONS ---
// performMove, performVent, completeTask, triggerReport, performKill all follow a similar pattern:
// 1) Lock actions to prevent repeated presses
// 2) Send action request to server and await response
// 3) If response indicates "pending", show waiting indicator and queue the action log until step resolves
// 4) If response is successful, log the action and any observations, then refresh room context and map UI
// 5) Unlock actions unless we're waiting for a step to resolve, in which case unlock when new state arrives from the server

async function performMove(destination) {
    const source = document.getElementById('location-display')?.innerText || 'Unknown';
    if (!lockActions()){
        return;
    }
    document.getElementById('waiting-indicator')?.classList.remove('d-none');
    try {
        const response = await apiFetch('/api/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination: destination }) // Send desired destination to server
        });
        
        if (response.ok) {
            const data = await response.json();
            // Waiting for other players to act
            if (data.status === "pending") {
                state.waitingForStep = true;
                state.pendingActionLog = { step: data.timestep, message: `You moved from ${source} to ${destination}`, type: 'info', observations: [], ventObservations: [] };
                return;
            }
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(`[Turn ${data.timestep}] You moved from ${source} to ${destination}`, 'info');

            // Log who was seen leaving the room
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Turn ${data.timestep}] ${observation}`, 'warning');
                });
            }
            // Log who was seen venting from room
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(observation => {
                    addLogMessage(`[Turn ${data.timestep}] ${observation}`, 'danger');
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
        if (!state.waitingForStep){
            unlockActions();
        }
    }
}

// Vent action for impostors. Similar to move.
async function performVent(destination) {
    if (!lockActions()){
        return;
    }
    document.getElementById('waiting-indicator')?.classList.remove('d-none');
    try {
        const response = await apiFetch('/api/vent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination: destination })
        });

        if (response.ok) {
            const data = await response.json();
            if (data.status === "pending") {
                state.waitingForStep = true;
                state.pendingActionLog = { step: data.timestep, message: `You vented to ${destination}`, type: 'danger', observations: [], ventObservations: [] };
                return;
            }
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(`[Turn ${data.timestep}] ${data.message}`, 'danger');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Turn ${data.timestep}] ${observation}`, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(`[Turn ${data.timestep}] ${obs}`, 'danger');
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
        if (!state.waitingForStep){
            unlockActions();
        }
    }
}

async function completeTask(taskName) {
    if (!lockActions()){
        return;
    }
    document.getElementById('waiting-indicator')?.classList.remove('d-none');
    try {
        const response = await apiFetch('/api/do-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: taskName })
        });

        if (response.ok) {
            const data = await response.json();
            if (data.status === "pending") {
                state.waitingForStep = true;
                state.pendingActionLog = { step: data.timestep, message: `Working on ${taskName}...`, type: 'success', observations: [], ventObservations: [], taskName };
                return;
            }
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(`[Turn ${data.timestep}] ${data.message}`, 'success');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Turn ${data.timestep}] ${observation}`, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(`[Turn ${data.timestep}] ${obs}`, 'danger');
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
        if (!state.waitingForStep){
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
            addLogMessage(`[Turn ${data.timestep}] ${data.message}`, 'danger');
        }
    }
    catch (e) {
        console.error('triggerReport error:', e);
    }
    finally {
        unlockActions();
    }
}

async function triggerEmergencyMeeting() {
    if (!lockActions()){
        return;
    }
    try {
        const response = await apiFetch('/api/call-meeting', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            addLogMessage(`[Turn ${data.timestep}] ${data.message}`, 'danger');
        }
    }
    catch (e) {
        console.error('triggerEmergencyMeeting error:', e);
    }
    finally {
        unlockActions();
    }
}

async function performKill(targetColor){
    if (!lockActions()){
        return;
    }
    document.getElementById('waiting-indicator')?.classList.remove('d-none');
    try {
        const response = await apiFetch('/api/kill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: targetColor })
        });

        if (response.ok){
            const data = await response.json();
            if (data.status === "pending") {
                state.waitingForStep = true;
                state.pendingActionLog = { step: data.timestep, message: `You killed ${formatColorName(targetColor)}`, type: 'danger', observations: [], ventObservations: [] };
                return;
            }
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(`[Turn ${data.timestep}] ${data.message}`, 'danger');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(`[Turn ${data.timestep}] ${observation}`, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(`[Turn ${data.timestep}] ${obs}`, 'danger');
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
        if (!state.waitingForStep){
            unlockActions();
        }
    }
}

export { refreshRoomContext, performMove, performVent, completeTask, triggerReport, triggerEmergencyMeeting, performKill };
