// actions.js
// This file contains functions for all player actions (move, vent, kill, report, call meeting, do task) and the main function to refresh room context and update UI based on server responses.
// Each action function follows a similar pattern of locking actions, sending request to server, handling pending states, logging results, refreshing UI, and unlocking actions.
import { state } from './state.js';
import { apiFetch, lockActions, unlockActions, addLogMessage, formatColorName } from './helpers.js';
import { updateMapUI } from './ui.js';

document.addEventListener('amongus:move-request', (event) => {
    const destination = event.detail?.destination;
    if (!destination) {
        return;
    }
    performMove(destination);
});

document.addEventListener('amongus:skip-move-request', () => {
    const currentRoom = document.getElementById('location-display')?.innerText;
    if (currentRoom) {
        performMove(currentRoom, true);
    }
});

document.addEventListener('amongus:vent-request', (event) => {
    const destination = event.detail?.destination;
    if (!destination) {
        return;
    }
    performVent(destination);
});

document.addEventListener('amongus:task-request', (event) => {
    const taskName = event.detail?.taskName;
    if (!taskName) {
        return;
    }
    completeTask(taskName);
});

document.addEventListener('amongus:kill-request', (event) => {
    const targetColor = event.detail?.targetColor;
    if (!targetColor) {
        return;
    }
    performKill(targetColor);
});

document.addEventListener('amongus:report-request', () => {
    triggerReport();
});

document.addEventListener('amongus:emergency-request', () => {
    triggerEmergencyMeeting();
});

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
            phaseDisplayEl.innerText = isAlive
                ? (state.waitingForStep ? 'Action entered, waiting for others...' : 'Please make your choice')
                : 'Spectating as Ghost';
            phaseDisplayEl.className = isAlive && state.waitingForStep
                ? 'text-warning fw-bold'
                : (isAlive ? 'text-success fw-bold choice-prompt' : 'text-success fw-bold');
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

    return data;
}

// --- PLAYER ACTIONS ---
// performMove, performVent, completeTask, triggerReport, performKill all follow a similar pattern:
// 1) Lock actions to prevent repeated presses
// 2) Send action request to server and await response
// 3) If response indicates "pending", show waiting indicator and queue the action log until step resolves
// 4) If response is successful, log the action and any observations, then refresh room context and map UI
// 5) Unlock actions unless we're waiting for a step to resolve, in which case unlock when new state arrives from the server

async function performMove(destination, skipMove = false) {
    const source = document.getElementById('location-display')?.innerText || 'Unknown';
    if (!lockActions()){
        return;
    }
    document.getElementById('waiting-indicator')?.classList.remove('d-none');
    try {
        const response = await apiFetch('/api/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination, skip_move: skipMove })
        });
        
        if (response.ok) {
            const data = await response.json();
            // Waiting for other players to act
            if (data.status === "pending") {
                state.waitingForStep = true;
                state.pendingActionLog = {
                    step: data.timestep,
                    message: skipMove ? `You stayed in ${source}` : `You moved from ${source} to ${destination}`,
                    type: 'info',
                    observations: [],
                    ventObservations: [],
                };
                return;
            }
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            const actionMessage = skipMove ? `You stayed in ${source}` : `You moved from ${source} to ${destination}`;
            addLogMessage(`[Turn ${data.timestep}] ${actionMessage}`, 'info');

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
    // A killer may immediately report the body they created. Reporting replaces
    // the queued kill with CallMeeting on the server, so release the local
    // pending-action lock before submitting it.
    if (state.waitingForStep) {
        state.waitingForStep = false;
        state.pendingActionLog = null;
        document.getElementById('waiting-indicator')?.classList.add('d-none');
        unlockActions();
    }
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
        else {
            const error = await response.json().catch(() => ({}));
            addLogMessage(error.detail || error.message || 'Kill was not available.', 'warning');
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
