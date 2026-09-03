// actions.js
// This file contains functions for all player actions (move, vent, kill, report, call meeting, do task) and the main function to refresh room context and update UI based on server responses.
// Each action function follows a similar pattern of locking actions, sending request to server, handling pending states, logging results, refreshing UI, and unlocking actions.
import { state } from './state.js';
import { apiFetch, lockActions, unlockActions, addLogMessage, formatColorName } from './helpers.js';
import { updateMapUI } from './ui.js';

const MOVE_COOLDOWN_MS = 5_000;

function startMoveCooldown() {
    state.moveCooldownUntil = Date.now() + MOVE_COOLDOWN_MS;
    if (state.moveCooldownTimer !== null) {
        clearTimeout(state.moveCooldownTimer);
    }
    state.moveCooldownTimer = setTimeout(() => {
        state.moveCooldownUntil = 0;
        state.moveCooldownTimer = null;
        updateMapUI();
    }, MOVE_COOLDOWN_MS);
}

document.addEventListener('amongus:move-request', (event) => {
    const destination = event.detail?.destination;
    if (!destination) {
        return;
    }
    performMove(destination);
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
    startTask(taskName);
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

    if (
        state.activeTask
        && (data.phase.toLowerCase() !== 'task' || data.current_room !== state.activeTask.location)
    ) {
        clearActiveTask();
    }

    if (state.gameStarted && data.phase.toLowerCase() !== "meeting") {
        if (state.actionPanel) state.actionPanel.classList.remove('d-none');
    }

    // Update location, adjacent rooms, tasks, and players in room based on server response
    document.getElementById('location-display').innerText = data.current_room;
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
                    startTask(taskName);
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
// 3) If the action succeeds, log it and refresh the immediate game state.
// 4) Unlock once the request completes so the player can keep acting.

async function performMove(destination) {
    const source = document.getElementById('location-display')?.innerText || 'Unknown';
    let moved = false;
    if (!lockActions()){
        return;
    }
    document.getElementById('waiting-indicator')?.classList.remove('d-none');
    try {
        const response = await apiFetch('/api/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination })
        });
        
        if (response.ok) {
            const data = await response.json();
            clearActiveTask();
            startMoveCooldown();
            moved = true;
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            const actionMessage = `You moved from ${source} to ${destination}`;
            addLogMessage(actionMessage, 'info');

            // Log who was seen leaving the room
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(observation, 'warning');
                });
            }
            // Log who was seen venting from room
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(observation => {
                    addLogMessage(observation, 'danger');
                });
            }

            await refreshRoomContext();
            await updateMapUI();
        }
        else {
            const data = await response.json().catch(() => ({}));
            addLogMessage(data.detail || 'Move was not available.', 'warning');
        }
    }
    catch (e) {
        console.error('performMove error:', e);
    }
    finally {
        unlockActions();
        if (moved) {
            await updateMapUI();
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
            clearActiveTask();
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(data.message, 'danger');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(observation, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(obs, 'danger');
                });
            }

            await refreshRoomContext();
            await updateMapUI();
        }
        else {
            const data = await response.json().catch(() => ({}));
            addLogMessage(data.detail || 'Vent was not available.', 'warning');
        }
    }
    catch (e) {
        console.error('performVent error:', e);
    }
    finally {
        unlockActions();
    }
}

function updateTaskCountdownLabel() {
    const activeTask = state.activeTask;
    if (!activeTask) {
        return;
    }
    const secondsLeft = Math.max(0, Math.ceil((activeTask.deadline - Date.now()) / 1000));
    const elapsedMilliseconds = Math.max(0, (activeTask.durationSeconds * 1000) - (activeTask.deadline - Date.now()));
    const progressPercent = Math.min(100, (elapsedMilliseconds / (activeTask.durationSeconds * 1000)) * 100);
    document.querySelectorAll('[data-active-task-name]').forEach((element) => {
        if (element.dataset.activeTaskName === activeTask.name) {
            element.textContent = `${activeTask.name} (${secondsLeft}s)`;
            element.style.setProperty('--task-progress', `${progressPercent}%`);
            element.setAttribute('aria-label', `${activeTask.name}: ${secondsLeft} seconds remaining`);
        }
    });
}

function clearActiveTask() {
    if (state.taskCountdownTimer !== null) {
        clearInterval(state.taskCountdownTimer);
        state.taskCountdownTimer = null;
    }
    state.activeTask = null;
}

function startTaskCountdown(taskName, location, durationSeconds) {
    clearActiveTask();
    state.activeTask = {
        name: taskName,
        location,
        durationSeconds,
        deadline: Date.now() + (durationSeconds * 1000),
        completing: false,
    };
    updateTaskCountdownLabel();
    state.taskCountdownTimer = setInterval(() => {
        const activeTask = state.activeTask;
        if (!activeTask) {
            return;
        }
        updateTaskCountdownLabel();
        if (Date.now() < activeTask.deadline || activeTask.completing) {
            return;
        }
        activeTask.completing = true;
        clearInterval(state.taskCountdownTimer);
        state.taskCountdownTimer = null;
        completeTask(activeTask.name);
    }, 250);
}

async function startTask(taskName) {
    if (state.activeTask || !lockActions()) {
        return;
    }
    try {
        const response = await apiFetch('/api/start-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: taskName }),
        });
        const data = await response.json();
        if (!response.ok) {
            addLogMessage(data.detail || 'That task is not available.', 'warning');
            return;
        }
        const location = document.getElementById('location-display')?.innerText;
        startTaskCountdown(data.task, location, data.duration_seconds);
        await updateMapUI();
    }
    catch (error) {
        console.error('startTask error:', error);
    }
    finally {
        unlockActions();
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
            clearActiveTask();
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(data.message, 'success');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(observation, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(obs, 'danger');
                });
            }

            await refreshRoomContext();
            await updateMapUI();
        }
        else {
            const data = await response.json().catch(() => ({}));
            clearActiveTask();
            addLogMessage(data.detail || 'Task completion was unavailable.', 'warning');
            await refreshRoomContext();
            await updateMapUI();
        }
    }
    catch (e) {
        console.error('completeTask error:', e);
    }
    finally {
        unlockActions();
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
            clearActiveTask();
            addLogMessage(data.message, 'danger');
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
            clearActiveTask();
            addLogMessage(data.message, 'danger');
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
            clearActiveTask();
            document.getElementById('waiting-indicator')?.classList.add('d-none');
            state.lastTimestep = data.timestep;
            addLogMessage(data.message, 'danger');
            if (data.observations && data.observations.length > 0){
                data.observations.forEach(observation => {
                    addLogMessage(observation, 'warning');
                });
            }
            if (data.vent_observations && data.vent_observations.length > 0){
                data.vent_observations.forEach(obs => {
                    addLogMessage(obs, 'danger');
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
        unlockActions();
    }
}

export { refreshRoomContext, performMove, performVent, startTask, triggerReport, triggerEmergencyMeeting, performKill };
