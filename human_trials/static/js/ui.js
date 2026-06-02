// ui.js
import { apiFetch, formatColorName, displayColor } from './helpers.js';
import { movementEdgeCoordinates, roomCoordinates, roomViewBounds, ventCoordinates } from './config.js';
import { state } from './state.js';

const SKELD_MAP_PATH = '/assets/map/The_Skeld_map_hq.webp';
const SKELD_MAP_WIDTH = 1000;
const SKELD_MAP_HEIGHT = 560;
let lastMapActionContextKey = null;

function getRoomViewProjection(roomView, roomName) {
    const bounds = roomViewBounds[roomName.toLowerCase()];
    if (!roomView || !bounds) {
        return null;
    }

    const viewWidth = roomView.clientWidth || 1;
    const viewHeight = roomView.clientHeight || 1;
    const scale = Math.max(viewWidth / bounds.width, viewHeight / bounds.height);
    const offsetX = -bounds.x * scale + ((viewWidth - (bounds.width * scale)) / 2);
    const offsetY = -bounds.y * scale + ((viewHeight - (bounds.height * scale)) / 2);

    return { bounds, viewWidth, viewHeight, scale, offsetX, offsetY };
}

function setRoomViewBackground(roomView, roomName) {
    if (!roomView) {
        return null;
    }

    const projection = getRoomViewProjection(roomView, roomName);
    if (!projection) {
        roomView.style.backgroundImage = `url('${SKELD_MAP_PATH}')`;
        roomView.style.backgroundSize = 'contain';
        roomView.style.backgroundRepeat = 'no-repeat';
        roomView.style.backgroundPosition = 'center';
        return null;
    }

    roomView.style.backgroundImage = `url('${SKELD_MAP_PATH}')`;
    roomView.style.backgroundSize = `${SKELD_MAP_WIDTH * projection.scale}px ${SKELD_MAP_HEIGHT * projection.scale}px`;
    roomView.style.backgroundRepeat = 'no-repeat';
    roomView.style.backgroundPosition = `${projection.offsetX}px ${projection.offsetY}px`;
    return projection;
}

function projectMapPoint(roomName, point, roomView) {
    const projection = getRoomViewProjection(roomView, roomName);
    if (!projection) {
        return null;
    }

    const unclampedX = (point.x * projection.scale) + projection.offsetX;
    const unclampedY = (point.y * projection.scale) + projection.offsetY;
    const padding = 36;

    return {
        x: Math.min(projection.viewWidth - padding, Math.max(padding, unclampedX)),
        y: Math.min(projection.viewHeight - padding, Math.max(padding, unclampedY)),
    };
}

function edgeKey(roomA, roomB) {
    return [roomA, roomB].sort().join(' <-> ');
}

function renderRoomTasks(contextData) {
    const overlay = document.getElementById('room-task-overlay');
    if (!overlay) {
        return;
    }

    overlay.innerHTML = '';
    const roomTasks = contextData.tasks_in_room || [];
    const assignedTaskMap = new Map(
        (contextData.room_task_statuses || []).map((task) => [task.name, task]),
    );

    roomTasks.forEach((taskName) => {
        const taskStatus = assignedTaskMap.get(taskName);
        const chip = document.createElement(taskStatus && !taskStatus.completed ? 'button' : 'div');
        chip.className = 'room-task-chip';
        chip.textContent = taskName;

        if (!taskStatus) {
            chip.classList.add('room-task-unassigned');
        } else if (taskStatus.completed) {
            chip.classList.add('room-task-complete');
        } else {
            chip.classList.add('room-task-active');
            if (chip instanceof HTMLButtonElement) {
                chip.type = 'button';
                chip.disabled = state.actionLocked || state.waitingForStep;
                chip.title = `Complete ${taskName}`;
                chip.setAttribute('aria-label', `Complete ${taskName}`);
                chip.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    document.dispatchEvent(new CustomEvent('amongus:task-request', {
                        detail: { taskName },
                    }));
                });
            }
        }

        overlay.appendChild(chip);
    });
}

function commitMapActionSelection(button) {
    const layer = button.closest('#room-interaction-layer');
    if (!layer) {
        return;
    }

    layer.querySelectorAll('.map-action-hotspot').forEach((hotspot) => {
        hotspot.disabled = true;
        hotspot.classList.remove('committed');
    });
    button.classList.add('committed');
}

function syncMapActionHotspots(contextKey) {
    const hotspots = document.querySelectorAll('.map-action-hotspot');
    const shouldEnable = !state.actionLocked && !state.waitingForStep;
    const shouldResetCommit = contextKey !== lastMapActionContextKey;

    hotspots.forEach((hotspot) => {
        hotspot.disabled = !shouldEnable;
        if (shouldResetCommit) {
            hotspot.classList.remove('committed');
        }
    });

    lastMapActionContextKey = contextKey;
}

function createMapArrow({ destination, point, currentRoom, variant = 'move', eventName }) {
    const currentCoords = roomCoordinates[currentRoom.toLowerCase()];
    const destinationCoords = roomCoordinates[destination.toLowerCase()];
    const angle = currentCoords && destinationCoords
        ? Math.atan2(destinationCoords.top - currentCoords.top, destinationCoords.left - currentCoords.left) * (180 / Math.PI)
        : 0;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = `map-action-hotspot move-arrow-hotspot ${variant === 'vent' ? 'vent-arrow-hotspot' : ''}`;
    button.style.left = `${point.x}px`;
    button.style.top = `${point.y}px`;
    button.title = `${variant === 'vent' ? 'Vent' : 'Move'} to ${destination}`;
    button.setAttribute('aria-label', `${variant === 'vent' ? 'Vent' : 'Move'} to ${destination}`);
    button.disabled = state.actionLocked || state.waitingForStep;

    if (variant !== 'vent') {
        const glyph = document.createElement('span');
        glyph.className = 'move-arrow-glyph';
        glyph.textContent = '➜';
        glyph.style.transform = `translate(-50%, -50%) rotate(${angle}deg)`;
        button.appendChild(glyph);
    }

    button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        commitMapActionSelection(button);
        document.dispatchEvent(new CustomEvent(eventName, {
            detail: { destination },
        }));
    });

    return button;
}

function renderMovementArrows(contextData, roomView, interactionLayer) {
    if (!interactionLayer || !roomView || !contextData?.adjacent?.length) {
        return;
    }

    interactionLayer.innerHTML = '';
    const currentRoom = contextData.current_room;

    contextData.adjacent.forEach((destination) => {
        const movePoint = movementEdgeCoordinates[edgeKey(currentRoom, destination)];
        if (!movePoint) {
            return;
        }

        const projectedPoint = projectMapPoint(currentRoom, movePoint, roomView);
        if (!projectedPoint) {
            return;
        }

        interactionLayer.appendChild(createMapArrow({
            destination,
            point: projectedPoint,
            currentRoom,
            variant: 'move',
            eventName: 'amongus:move-request',
        }));
    });
}

async function renderVentArrows(contextData, roomView, interactionLayer) {
    if (!interactionLayer || !roomView || !state.myRole || state.myRole.toLowerCase() !== 'impostor' || !state.isAlive) {
        return;
    }

    const currentRoomKey = contextData.current_room.toLowerCase();
    const roomVentPoints = ventCoordinates[currentRoomKey];
    if (!roomVentPoints || roomVentPoints.length === 0) {
        return;
    }

    const ventResponse = await apiFetch('/api/vent-options');
    const ventData = await ventResponse.json();
    if (!ventData.can_vent || !ventData.options?.length) {
        return;
    }

    ventData.options.forEach((destination, index) => {
        const anchorPoint = roomVentPoints[Math.min(index, roomVentPoints.length - 1)];
        const projectedPoint = projectMapPoint(contextData.current_room, anchorPoint, roomView);
        if (!projectedPoint) {
            return;
        }

        interactionLayer.appendChild(createMapArrow({
            destination,
            point: projectedPoint,
            currentRoom: contextData.current_room,
            variant: 'vent',
            eventName: 'amongus:vent-request',
        }));
    });
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
        imgDisplay.src = `/assets/player_sprites/alive/player_${color.toLowerCase()}.png`;
    }
    if (userDisplay){
        userDisplay.innerText = formatColorName(color);
    }
    const roleModalEl = document.getElementById('role-reveal-modal');
    const roleModal = new bootstrap.Modal(roleModalEl);

    roleModalEl.addEventListener('hidden.bs.modal', () => {
        new bootstrap.Modal(document.getElementById('how-to-play-modal')).show();
    }, { once: true });

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
        const roomInteractionLayer = document.getElementById('room-interaction-layer');
        const skeldLayer = document.getElementById('skeld-player-layer');
        const locationHeader = document.getElementById('location-header');

        if (locationHeader){
            locationHeader.innerText = contextData.current_room;
        }

        if (roomView){
            setRoomViewBackground(roomView, contextData.current_room);
        }

        if (skeldLayer){
            skeldLayer.innerHTML = '';
        }
        if (roomPlayerLayer){
            roomPlayerLayer.innerHTML = '';
        }
        if (roomInteractionLayer) {
            roomInteractionLayer.innerHTML = '';
        }

        renderRoomTasks(contextData);

        const currentRoomStr = contextData.current_room.toLowerCase();
        const userDisplayEl = document.getElementById('user-display');
        const myColor = userDisplayEl ? userDisplayEl.innerText.toLowerCase() : "";

        // Render player images over minimap and room map with jitter
        // Task markers on minimap for rooms with personal tasks (exclamation mark icon)
        if (skeldLayer && contextData.personal_tasks) {
            const taskRooms = new Set();
            contextData.personal_tasks.forEach(t => {
                if (t.location) taskRooms.add(t.location.trim().toLowerCase());
            });
            taskRooms.forEach(room => {
                const coords = roomCoordinates[room];
                if (!coords){
                    return;
                }
                const marker = document.createElement('img');
                marker.src = '/assets/map/task_marker.png';
                marker.style.cssText = `position:absolute; top:${coords.top}%; left:${coords.left}%; width:30px; height:30px; object-fit:contain; transform:translate(-50%,-120%); z-index:20; pointer-events:none;`;
                skeldLayer.appendChild(marker);
            });
        }

        data.players.forEach(player => {
            const isSelf = player.color === myColor;
            const isAlivePlayer = player.is_alive;
            const isReported = player.reported_death;
            const bodyLoc = player.body_location ? player.body_location.toLowerCase() : null;

            // Determine render location and sprite for this player
            // Alive viewers: dead players render as bodies at body_location (not ghost location)
            // Ghost viewers: see everyone at actual location
            let renderLoc, renderSrc, renderFilter;

            if (isAlivePlayer) {
                renderLoc = player.location.toLowerCase();
                renderSrc = `/assets/player_sprites/alive/player_${player.color}.png`;
                renderFilter = null;
            }
            else if (isSelf) {
                // Its you. Render as ghost in your actual location.
                renderLoc = player.location.toLowerCase();
                renderSrc = `/assets/player_sprites/alive/player_${player.color}.png`;
                renderFilter = 'grayscale(80%) opacity(0.5)';
            }
            // For other dead players
            else if (!state.isAlive) {
                // Ghost viewer sees other ghosts at their actual location
                if (isReported){
                    return;
                }
                renderLoc = player.location.toLowerCase();
                renderSrc = `/assets/player_sprites/dead/${player.color}_body.png`;
                renderFilter = null;
            }
            else {
                // Alive viewer: dead players shown as body at body_location only
                if (isReported || !bodyLoc){
                    return;
                }
                renderLoc = bodyLoc;
                renderSrc = `/assets/player_sprites/dead/${player.color}_body.png`;
                renderFilter = null;
            }

            if (skeldLayer){
                const coords = roomCoordinates[renderLoc];
                if (coords){
                    const miniImg = document.createElement('img');
                    miniImg.src = renderSrc;
                    if (renderFilter) miniImg.style.filter = renderFilter;
                    miniImg.style.position = 'absolute';
                    const miniJitterX = (Math.random() * 4) - 2;
                    const miniJitterY = (Math.random() * 4) - 2;
                    miniImg.style.top = `${coords.top + miniJitterY}%`;
                    miniImg.style.left = `${coords.left + miniJitterX}%`;
                    miniImg.style.width = '52px';
                    miniImg.style.height = '52px';
                    miniImg.style.objectFit = 'contain';
                    miniImg.style.transform = 'translate(-50%, -50%)';
                    miniImg.style.zIndex = '10';
                    skeldLayer.appendChild(miniImg);
                }
            }

            if (renderLoc === currentRoomStr && roomPlayerLayer) {
                const img = document.createElement('img');
                img.src = renderSrc;
                if (renderFilter) img.style.filter = renderFilter;
                img.className = 'player-sprite';
                const horizontalPos = 20 + (Math.random() * 60);
                const verticalPos = 40 + (Math.random() * 40);
                img.style.position = 'absolute';
                img.style.top = `${verticalPos}%`;
                img.style.left = `${horizontalPos}%`;
                img.style.width = '65px';
                img.style.height = '65px';
                img.style.objectFit = 'contain';
                img.style.transform = 'translate(-50%, -50%)';
                img.style.transition = 'all 0.5s ease';
                img.title = player.name;
                roomPlayerLayer.appendChild(img);
            }
        });

        renderMovementArrows(contextData, roomView, roomInteractionLayer);
        await renderVentArrows(contextData, roomView, roomInteractionLayer);
        syncMapActionHotspots(`${contextData.timestep}:${contextData.current_room}`);
    }
    catch (error) {
        console.error("Failed to update Room UI:", error);
    }
}

export { showRoleReveal, updateTaskProgressBar, updateMapUI };
