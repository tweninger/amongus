// ui.js
import { apiFetch, formatColorName, displayColor } from './helpers.js';
import { roomCoordinates } from './config.js';
import { state } from './state.js';

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
        const skeldLayer = document.getElementById('skeld-player-layer');
        const locationHeader = document.getElementById('location-header');

        if (locationHeader){
            locationHeader.innerText = contextData.current_room;
        }

        const formattedRoom = contextData.current_room.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join('_');
        const bgPath = `/assets/map/rooms/The_Skeld_${formattedRoom}.webp`;

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
    }
    catch (error) {
        console.error("Failed to update Room UI:", error);
    }
}

export { showRoleReveal, updateTaskProgressBar, updateMapUI };
