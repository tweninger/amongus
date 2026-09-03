// ui.js
import { apiFetch, formatColorName, displayColor } from './helpers.js';
import { movementEdgeCoordinates, roomCoordinates, roomViewBounds, ventCoordinates } from './config.js';
import { state } from './state.js';

const SKELD_MAP_PATH = '/assets/map/The_Skeld_map_hq.webp';
const SKELD_MAP_WIDTH = 1000;
const SKELD_MAP_HEIGHT = 560;
let lastMapActionContextKey = null;
const roomSpritePlacements = new Map();
let roomSpritePlacementScope = null;
let mapRenderRequestId = 0;
const lastKnownPlayerLocations = new Map();
const pendingRoomEntries = new Map();
const pendingVentEntries = new Map();
const processedVentEventIds = new Set();
const processedKillEventIds = new Set();
let killCooldownTooltipTimer = null;

function getRoomViewProjection(roomView, roomName) {
    const bounds = roomViewBounds[roomName.toLowerCase()];
    if (!roomView || !bounds) {
        return null;
    }

    const viewWidth = roomView.clientWidth || 1;
    const viewHeight = roomView.clientHeight || 1;
    // Preserve the entire room instead of cropping its edges to fill the stage.
    const scale = Math.min(viewWidth / bounds.width, viewHeight / bounds.height);
    const offsetX = -bounds.x * scale + ((viewWidth - (bounds.width * scale)) / 2);
    const offsetY = -bounds.y * scale + ((viewHeight - (bounds.height * scale)) / 2);

    return { bounds, viewWidth, viewHeight, scale, offsetX, offsetY };
}

function setRoomViewBackground(roomView, roomName) {
    if (!roomView) {
        return null;
    }

    roomView.dataset.room = roomName.toLowerCase();

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

function getMovementEdgePoint(roomA, roomB) {
    const normalizedKey = edgeKey(roomA, roomB).toLowerCase();
    return Object.entries(movementEdgeCoordinates).find(
        ([key]) => key.toLowerCase() === normalizedKey,
    )?.[1];
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
    const activeTask = state.activeTask;

    roomTasks.forEach((taskName) => {
        const taskStatus = assignedTaskMap.get(taskName);
        const isActiveTask = Boolean(
            activeTask
            && activeTask.name === taskName
            && activeTask.location === contextData.current_room,
        );
        const chip = document.createElement(taskStatus && !taskStatus.completed ? 'button' : 'div');
        chip.className = 'room-task-chip';
        const progress = isActiveTask
            ? ` (${Math.max(0, Math.ceil((activeTask.deadline - Date.now()) / 1000))}s)`
            : taskStatus && taskStatus.max_duration > 1
            ? ` (${taskStatus.steps_done}/${taskStatus.max_duration})`
            : '';
        chip.textContent = `${taskName}${progress}`;

        if (!taskStatus) {
            chip.classList.add('room-task-unassigned');
        } else if (taskStatus.completed) {
            chip.classList.add('room-task-complete');
        } else {
            chip.classList.add('room-task-active');
            chip.classList.add(isActiveTask || taskStatus.steps_done > 0 ? 'room-task-in-progress' : 'room-task-ready');
            if (chip instanceof HTMLButtonElement) {
                chip.type = 'button';
                chip.disabled = state.actionLocked || Boolean(activeTask);
                if (isActiveTask) {
                    chip.dataset.activeTaskName = taskName;
                    const remainingMilliseconds = Math.max(0, activeTask.deadline - Date.now());
                    const elapsedMilliseconds = Math.max(0, (activeTask.durationSeconds * 1000) - remainingMilliseconds);
                    const progressPercent = Math.min(100, (elapsedMilliseconds / (activeTask.durationSeconds * 1000)) * 100);
                    chip.classList.add('room-task-timing');
                    chip.style.setProperty('--task-progress', `${progressPercent}%`);
                    chip.setAttribute('aria-label', `${taskName}: ${Math.ceil(remainingMilliseconds / 1000)} seconds remaining`);
                    chip.title = `${taskName}: ${Math.ceil(remainingMilliseconds / 1000)} seconds remaining`;
                } else {
                    chip.title = `Complete ${taskName}`;
                    chip.setAttribute('aria-label', `Complete ${taskName}`);
                }
                chip.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    commitRoomTaskSelection(chip);
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

function commitRoomTaskSelection(button) {
    const overlay = button.closest('#room-task-overlay');
    if (!overlay) {
        return;
    }

    overlay.querySelectorAll('.room-task-active').forEach((task) => {
        task.disabled = true;
        task.classList.remove('committed');
    });
    button.classList.add('committed');
}

function commitRoomPlayerActionSelection(button) {
    document.querySelectorAll('.room-hover-action-button').forEach((action) => {
        action.disabled = true;
        action.classList.remove('committed');
    });
    button.classList.add('committed');
}

function syncMapActionHotspots(contextKey) {
    const hotspots = document.querySelectorAll('.map-action-hotspot');
    const moveCooldownActive = Date.now() < state.moveCooldownUntil;
    const shouldResetCommit = contextKey !== lastMapActionContextKey;

    hotspots.forEach((hotspot) => {
        const isMovementArrow = hotspot.classList.contains('move-arrow-hotspot');
        hotspot.disabled = state.actionLocked || (isMovementArrow && moveCooldownActive);
        if (shouldResetCommit) {
            hotspot.classList.remove('committed');
        }
    });

    lastMapActionContextKey = contextKey;
}

function syncKillCooldownTooltips(cooldownSeconds) {
    if (killCooldownTooltipTimer !== null) {
        window.clearInterval(killCooldownTooltipTimer);
        killCooldownTooltipTimer = null;
    }
    if (!cooldownSeconds) {
        return;
    }

    const deadline = Date.now() + (cooldownSeconds * 1000);
    const refresh = () => {
        const secondsLeft = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        document.querySelectorAll('.room-kill-button:disabled').forEach((button) => {
            button.title = secondsLeft ? `Kill available in ${secondsLeft}s` : 'Kill';
        });
        if (!secondsLeft) {
            window.clearInterval(killCooldownTooltipTimer);
            killCooldownTooltipTimer = null;
            updateMapUI();
        }
    };

    refresh();
    killCooldownTooltipTimer = window.setInterval(refresh, 250);
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
    button.disabled = state.actionLocked || Date.now() < state.moveCooldownUntil;

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
            detail: { destination, targetPoint: point },
        }));
    });

    return button;
}

function createEmergencyHotspot(point) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'map-action-hotspot emergency-hotspot';
    button.style.left = `${point.x}px`;
    button.style.top = `${point.y}px`;
    button.title = 'Call emergency meeting';
    button.setAttribute('aria-label', 'Call emergency meeting');
    button.disabled = state.actionLocked;
    button.textContent = '!';

    button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        commitMapActionSelection(button);
        document.dispatchEvent(new CustomEvent('amongus:emergency-request'));
    });

    return button;
}

function getMovementArrowPoints(contextData, roomView) {
    if (!contextData?.adjacent?.length || !roomView) {
        return [];
    }

    return contextData.adjacent
        .map((destination) => movementEdgeCoordinates[edgeKey(contextData.current_room, destination)])
        .filter(Boolean)
        .map((point) => projectMapPoint(contextData.current_room, point, roomView))
        .filter(Boolean);
}

function getPlayerPlacementArea(contextData, roomView) {
    const arrowPoints = getMovementArrowPoints(contextData, roomView);
    const viewCenter = {
        x: (roomView?.clientWidth || 1) / 2,
        y: (roomView?.clientHeight || 1) / 2,
    };
    const anchors = arrowPoints.length === 1 ? [...arrowPoints, viewCenter] : arrowPoints;

    if (anchors.length === 0) {
        return {
            left: viewCenter.x * 0.3,
            right: viewCenter.x * 1.7,
            top: viewCenter.y * 0.35,
            bottom: viewCenter.y * 1.65,
        };
    }

    const inset = 64;
    const left = Math.max(inset, Math.min(...anchors.map((point) => point.x)) + inset);
    const right = Math.min(roomView.clientWidth - inset, Math.max(...anchors.map((point) => point.x)) - inset);
    const top = Math.max(inset, Math.min(...anchors.map((point) => point.y)) + inset);
    const bottom = Math.min(roomView.clientHeight - inset, Math.max(...anchors.map((point) => point.y)) - inset);

    return {
        left: Math.min(left, right),
        right: Math.max(left, right),
        top: Math.min(top, bottom),
        bottom: Math.max(top, bottom),
    };
}

function getRoomSpritePlacement(player, renderLoc, placementArea) {
    const placementKey = `${player.color}:${renderLoc}`;
    const existing = roomSpritePlacements.get(placementKey);
    if (existing) {
        return existing;
    }

    const placement = {
        x: placementArea
            ? placementArea.left + (Math.random() * (placementArea.right - placementArea.left))
            : 50,
        y: placementArea
            ? placementArea.top + (Math.random() * (placementArea.bottom - placementArea.top))
            : 50,
    };
    roomSpritePlacements.set(placementKey, placement);
    return placement;
}

function createRoomPlayerSprite(player, renderSrc, renderFilter, actionConfig = null, placement = null, isSelf = false) {
    const wrapper = document.createElement('div');
    wrapper.className = 'room-player-sprite-wrap';
    wrapper.style.position = 'absolute';
    wrapper.style.top = `${placement?.y ?? 50}px`;
    wrapper.style.left = `${placement?.x ?? 50}px`;
    wrapper.style.transform = 'translate(-50%, -50%)';
    wrapper.dataset.playerColor = player.color;

    const img = document.createElement('img');
    img.src = renderSrc;
    if (renderFilter) img.style.filter = renderFilter;
    img.className = 'player-sprite';
    img.style.width = '65px';
    img.style.height = '65px';
    img.style.objectFit = 'contain';
    img.style.transition = 'all 0.5s ease';
    img.title = player.name;
    wrapper.appendChild(img);

    if (isSelf) {
        const marker = document.createElement('span');
        marker.className = 'room-current-player-marker';
        marker.textContent = '(YOU)';
        wrapper.appendChild(marker);
    }

    if (player.is_tasking && player.is_alive) {
        const marker = document.createElement('span');
        marker.className = 'room-tasking-marker';
        marker.append('TASK');
        const dots = document.createElement('span');
        dots.className = 'room-tasking-dots';
        dots.append(document.createElement('i'), document.createElement('i'), document.createElement('i'));
        marker.appendChild(dots);
        wrapper.appendChild(marker);
    }

    if (actionConfig) {
        const actionBtn = document.createElement('button');
        actionBtn.type = 'button';
        actionBtn.className = `room-hover-action-button ${actionConfig.className}`;
        actionBtn.textContent = actionConfig.label;
        actionBtn.title = actionConfig.title || actionConfig.label;
        actionBtn.disabled = Boolean(actionConfig.disabled) || (
            !actionConfig.allowWhilePending && state.actionLocked
        );
        actionBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            commitRoomPlayerActionSelection(actionBtn);
            document.dispatchEvent(new CustomEvent(actionConfig.eventName, {
                detail: actionConfig.detail || {},
            }));
        });
        wrapper.appendChild(actionBtn);
    }

    return wrapper;
}

function animateLocalPlayerMove(targetPoint) {
    if (!targetPoint || state.localMovementAnimation) {
        return Promise.resolve();
    }

    const playerLayer = document.getElementById('room-player-layer');
    const wrapper = [...(playerLayer?.querySelectorAll('.room-player-sprite-wrap') || [])]
        .find((element) => element.dataset.playerColor === state.myColor);
    if (!wrapper) {
        return Promise.resolve();
    }

    state.localMovementAnimation = { wrapper, targetPoint };
    wrapper.classList.add('room-player-moving');

    return new Promise((resolve) => {
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                wrapper.style.left = `${targetPoint.x}px`;
                wrapper.style.top = `${targetPoint.y}px`;
            });
        });
        window.setTimeout(resolve, 580);
    });
}

function finishLocalPlayerMove() {
    state.localMovementAnimation?.wrapper?.classList.remove('room-player-moving');
    state.localMovementAnimation = null;
}

function getVisiblePlayerDepartures(players, currentRoom, roomView) {
    const departures = [];
    const playerLayer = document.getElementById('room-player-layer');
    if (!playerLayer) {
        return departures;
    }

    players.forEach((player) => {
        const nextRoom = player.location?.toLowerCase();
        const wrapper = [...playerLayer.querySelectorAll('.room-player-sprite-wrap')]
            .find((element) => element.dataset.playerColor === player.color);
        if (
            player.color.toLowerCase() === (state.myColor || '').toLowerCase()
            || !player.is_alive
            || !nextRoom
            || nextRoom === currentRoom
            || !wrapper
            || wrapper.dataset.room !== currentRoom
        ) {
            return;
        }

        const doorway = getMovementEdgePoint(currentRoom, nextRoom);
        const targetPoint = doorway && projectMapPoint(currentRoom, doorway, roomView);
        if (wrapper && targetPoint) {
            departures.push({ wrapper, targetPoint });
        }
    });

    return departures;
}

function collectRoomEntries(players, currentRoom, roomView) {
    players.forEach((player) => {
        const previousRoom = lastKnownPlayerLocations.get(player.color);
        const nextRoom = player.location?.toLowerCase();
        if (
            !player.is_alive
            || !previousRoom
            || previousRoom === nextRoom
            || nextRoom !== currentRoom
        ) {
            return;
        }

        const doorway = getMovementEdgePoint(currentRoom, previousRoom);
        const entryPoint = doorway && projectMapPoint(currentRoom, doorway, roomView);
        if (entryPoint) {
            pendingRoomEntries.set(player.color, entryPoint);
        }
    });
}

function rememberPlayerLocations(players) {
    players.forEach((player) => {
        if (player.is_connected !== false && player.location) {
            lastKnownPlayerLocations.set(player.color, player.location.toLowerCase());
        }
    });
}

function animateRoomPlayerEntry(wrapper, entryPoint, placement) {
    if (!entryPoint || !placement) {
        return;
    }

    wrapper.style.left = `${entryPoint.x}px`;
    wrapper.style.top = `${entryPoint.y}px`;
    wrapper.classList.add('room-player-moving');
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            wrapper.style.left = `${placement.x}px`;
            wrapper.style.top = `${placement.y}px`;
        });
    });
    window.setTimeout(() => wrapper.classList.remove('room-player-moving'), 580);
}

function animateVisiblePlayerDepartures(departures) {
    if (departures.length === 0) {
        return;
    }

    state.roomDepartureAnimation = departures;
    departures.forEach(({ wrapper }) => wrapper.classList.add('room-player-moving'));
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            departures.forEach(({ wrapper, targetPoint }) => {
                wrapper.style.left = `${targetPoint.x}px`;
                wrapper.style.top = `${targetPoint.y}px`;
            });
        });
    });

    window.setTimeout(() => {
        departures.forEach(({ wrapper }) => wrapper.remove());
        state.roomDepartureAnimation = null;
        updateMapUI();
    }, 580);
}

function getVentPoint(roomName, roomView) {
    const mapPoint = ventCoordinates[roomName?.toLowerCase()]?.[0];
    return mapPoint && projectMapPoint(roomName, mapPoint, roomView);
}

function revealVent(roomView, roomName) {
    const interactionLayer = document.getElementById('room-interaction-layer');
    const point = getVentPoint(roomName, roomView);
    if (!interactionLayer || !point) {
        return null;
    }

    const flare = document.createElement('div');
    flare.className = 'vent-reveal-animation';
    flare.textContent = 'VENT';
    flare.style.left = `${point.x}px`;
    flare.style.top = `${point.y}px`;
    interactionLayer.appendChild(flare);
    return { flare, point };
}

function playVentEvents(events) {
    if (!Array.isArray(events) || state.ventAnimation) {
        return;
    }

    const roomView = document.getElementById('room-view');
    const displayedRoom = roomView?.dataset.room;
    if (!roomView || !displayedRoom) {
        return;
    }

    for (const event of events) {
        if (!event || processedVentEventIds.has(event.id)) {
            continue;
        }

        const sourceRoom = event.source_room?.toLowerCase();
        const destinationRoom = event.destination_room?.toLowerCase();
        if (displayedRoom !== sourceRoom && displayedRoom !== destinationRoom) {
            processedVentEventIds.add(event.id);
            continue;
        }

        processedVentEventIds.add(event.id);
        const visibleRoom = displayedRoom === sourceRoom ? sourceRoom : destinationRoom;
        const reveal = revealVent(roomView, visibleRoom);
        if (!reveal) {
            return;
        }

        state.ventAnimation = event.id;
        const playerLayer = document.getElementById('room-player-layer');
        const venter = [...(playerLayer?.querySelectorAll('.room-player-sprite-wrap') || [])]
            .find((sprite) => sprite.dataset.playerColor === event.player_color);

        if (displayedRoom === sourceRoom && venter) {
            venter.classList.add('room-player-moving');
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    venter.style.left = `${reveal.point.x}px`;
                    venter.style.top = `${reveal.point.y}px`;
                });
            });
        }
        if (displayedRoom === destinationRoom) {
            pendingVentEntries.set(event.player_color, reveal.point);
        }

        window.setTimeout(() => {
            reveal.flare.remove();
            if (displayedRoom === sourceRoom) {
                venter?.remove();
            }
            state.ventAnimation = null;
            updateMapUI();
        }, 700);
        return;
    }
}

function playKillEvents(events) {
    if (!Array.isArray(events) || state.killAnimation) {
        return;
    }

    const roomView = document.getElementById('room-view');
    const displayedRoom = roomView?.dataset.room;
    if (!roomView || !displayedRoom) {
        return;
    }

    for (const event of events) {
        if (!event || processedKillEventIds.has(event.id)) {
            continue;
        }
        if (event.room?.toLowerCase() !== displayedRoom) {
            processedKillEventIds.add(event.id);
            continue;
        }

        const playerLayer = document.getElementById('room-player-layer');
        const interactionLayer = document.getElementById('room-interaction-layer');
        const killer = [...(playerLayer?.querySelectorAll('.room-player-sprite-wrap') || [])]
            .find((sprite) => sprite.dataset.playerColor === event.killer_color);
        const target = [...(playerLayer?.querySelectorAll('.room-player-sprite-wrap') || [])]
            .find((sprite) => sprite.dataset.playerColor === event.target_color);
        if (!killer || !target || !interactionLayer) {
            return;
        }

        processedKillEventIds.add(event.id);
        state.killAnimation = event.id;
        const targetPoint = {
            x: Number.parseFloat(target.style.left),
            y: Number.parseFloat(target.style.top),
        };
        const settlePoint = {
            x: Math.min((roomView.clientWidth || targetPoint.x) - 38, targetPoint.x + 38),
            y: Math.min((roomView.clientHeight || targetPoint.y) - 38, targetPoint.y + 8),
        };
        killer.classList.add('room-player-moving');
        target.classList.add('room-player-killed');
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                killer.style.left = `${targetPoint.x}px`;
                killer.style.top = `${targetPoint.y}px`;
            });
        });

        window.setTimeout(() => {
            const impact = document.createElement('div');
            impact.className = 'kill-impact-animation';
            impact.style.left = `${targetPoint.x}px`;
            impact.style.top = `${targetPoint.y}px`;
            interactionLayer.appendChild(impact);

            window.setTimeout(() => {
                killer.style.left = `${settlePoint.x}px`;
                killer.style.top = `${settlePoint.y}px`;
            }, 100);

            window.setTimeout(() => {
                impact.remove();
                target.remove();
                roomSpritePlacements.set(`${event.killer_color}:${displayedRoom}`, settlePoint);
                state.killAnimation = null;
                updateMapUI();
            }, 360);
        }, 520);
        return;
    }
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

function renderEmergencyHotspot(contextData, roomView, interactionLayer) {
    if (!interactionLayer || !roomView || !state.isAlive) {
        return;
    }

    if (contextData.current_room.toLowerCase() !== 'cafeteria') {
        return;
    }

    const projectedPoint = projectMapPoint(contextData.current_room, { x: 564, y: 123 }, roomView);
    if (!projectedPoint) {
        return;
    }

    interactionLayer.appendChild(createEmergencyHotspot(projectedPoint));
}

// --- GAME UI ---

// Create and show role reveal modal in UI
function showRoleReveal(role, color){
    const roleDisplay = document.getElementById('role-display');
    const colorDisplay = document.getElementById('color-name-display');
    const imgDisplay = document.getElementById('color-img-display');
    const userDisplay = document.getElementById('user-display');
    const roleReminder = document.getElementById('role-reminder');
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
    if (roleReminder) {
        roleReminder.innerText = ` (${role})`;
        roleReminder.className = `fw-bold ${role.toLowerCase() === 'impostor' ? 'text-danger' : 'text-info'}`;
    }
    const roleModalEl = document.getElementById('role-reveal-modal');
    const roleModal = new bootstrap.Modal(roleModalEl);

    roleModal.show();
}

function showKilledModal() {
    if (state.deathModalShown) {
        return;
    }
    const modalEl = document.getElementById('killed-modal');
    if (!modalEl || typeof bootstrap === 'undefined') {
        return;
    }
    state.deathModalShown = true;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
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
    const requestId = ++mapRenderRequestId;
    try {
        const response = await apiFetch('/api/player-states');
        const data = await response.json();
        const roomContextResponse = await apiFetch('/api/room-context');
        const contextData = await roomContextResponse.json();

        if (requestId !== mapRenderRequestId || data.error){
            return;
        }

        const roomView = document.getElementById('room-view');
        const roomPlayerLayer = document.getElementById('room-player-layer');
        const roomInteractionLayer = document.getElementById('room-interaction-layer');
        const skeldLayer = document.getElementById('skeld-player-layer');
        const currentRoomStr = contextData.current_room.toLowerCase();

        // Let the local player finish walking to the chosen doorway before any
        // incoming state update rebuilds the room scene.
        if (state.localMovementAnimation || state.roomDepartureAnimation || state.ventAnimation || state.killAnimation) {
            return;
        }

        const departures = getVisiblePlayerDepartures(data.players, currentRoomStr, roomView);
        collectRoomEntries(data.players, currentRoomStr, roomView);
        rememberPlayerLocations(data.players);
        if (departures.length > 0) {
            animateVisiblePlayerDepartures(departures);
            return;
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

        const myColor = (state.myColor || '').toLowerCase();
        const isHumanImpostor = state.myRole && state.myRole.toLowerCase() === 'impostor' && state.isAlive;

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

        const playerPlacementArea = getPlayerPlacementArea(contextData, roomView);
        const placementScope = [roomView?.clientWidth, roomView?.clientHeight].join(':');
        if (placementScope !== roomSpritePlacementScope) {
            roomSpritePlacements.clear();
            roomSpritePlacementScope = placementScope;
        }
        data.players.forEach(player => {
            if (player.is_connected === false) {
                return;
            }
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

            // The minimap shows only the current living player's position.
            if (skeldLayer && isAlivePlayer && isSelf){
                const coords = roomCoordinates[renderLoc];
                if (coords){
                    const miniImg = document.createElement('img');
                    miniImg.src = renderSrc;
                    if (renderFilter) miniImg.style.filter = renderFilter;
                    miniImg.style.position = 'absolute';
                    miniImg.style.top = `${coords.top}%`;
                    miniImg.style.left = `${coords.left}%`;
                    miniImg.style.width = '26px';
                    miniImg.style.height = '26px';
                    miniImg.style.objectFit = 'contain';
                    miniImg.style.transform = 'translate(-50%, -50%)';
                    miniImg.style.zIndex = '10';
                    skeldLayer.appendChild(miniImg);
                }
            }

            if (renderLoc === currentRoomStr && roomPlayerLayer) {
                const placement = getRoomSpritePlacement(player, renderLoc, playerPlacementArea);
                let actionConfig = null;
                if (isHumanImpostor && player.is_alive && !isSelf) {
                    const killCooldownSeconds = contextData.kill_cooldown_seconds || 0;
                    actionConfig = {
                        className: 'room-kill-button',
                        label: 'KILL',
                        eventName: 'amongus:kill-request',
                        detail: { targetColor: player.color },
                        disabled: contextData.can_kill === false,
                        title: killCooldownSeconds > 0
                            ? `Kill available in ${killCooldownSeconds}s`
                            : 'Kill',
                    };
                } else if (!player.is_alive && !player.reported_death && state.isAlive) {
                    actionConfig = {
                        className: 'room-report-button',
                        label: 'REPORT',
                        eventName: 'amongus:report-request',
                        allowWhilePending: true,
                    };
                }
                const roomSprite = createRoomPlayerSprite(
                    player, renderSrc, renderFilter, actionConfig, placement, isSelf,
                );
                roomSprite.dataset.room = renderLoc;
                roomPlayerLayer.appendChild(roomSprite);
                const ventEntryPoint = pendingVentEntries.get(player.color);
                const entryPoint = pendingRoomEntries.get(player.color);
                if (ventEntryPoint) {
                    pendingVentEntries.delete(player.color);
                    pendingRoomEntries.delete(player.color);
                    animateRoomPlayerEntry(roomSprite, ventEntryPoint, placement);
                } else if (entryPoint) {
                    pendingRoomEntries.delete(player.color);
                    animateRoomPlayerEntry(roomSprite, entryPoint, placement);
                }
            }
        });

        renderMovementArrows(contextData, roomView, roomInteractionLayer);
        renderEmergencyHotspot(contextData, roomView, roomInteractionLayer);
        await renderVentArrows(contextData, roomView, roomInteractionLayer);
        syncMapActionHotspots(`${contextData.timestep}:${contextData.current_room}`);
        syncKillCooldownTooltips(contextData.kill_cooldown_seconds || 0);
    }
    catch (error) {
        console.error("Failed to update Room UI:", error);
    }
}

export {
    animateLocalPlayerMove,
    finishLocalPlayerMove,
    playKillEvents,
    playVentEvents,
    showRoleReveal,
    showKilledModal,
    updateTaskProgressBar,
    updateMapUI,
};
