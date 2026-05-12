// ui.js
import { apiFetch, formatColorName, displayColor } from './helpers.js';
import { roomCoordinates } from './config.js';

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
        data.players.forEach(player => {
            const playerLoc = player.location.toLowerCase();

            const isStaleCorpse = !player.is_alive && player.reported_death && player.color !== myColor;
            if (isStaleCorpse) return;

            // FOR MASTER VIEW OR GHOST MODE - Delete master view later
            if (skeldLayer){
                const coords = roomCoordinates[playerLoc];
                if (coords){
                    const miniImg = document.createElement('img');
                    if (!player.is_alive && player.color === myColor) {
                        miniImg.src = `/assets/player_sprites/alive/player_${player.color}.png`;
                        miniImg.style.filter = 'grayscale(80%) opacity(0.5)';
                    }
                    else {
                        miniImg.src = player.is_alive
                            ? `/assets/player_sprites/alive/player_${player.color}.png`
                            : `/assets/player_sprites/dead/${player.color}_body.png`;
                    }
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

            if (playerLoc === currentRoomStr && roomPlayerLayer) {
                const img = document.createElement('img');
                if (!player.is_alive && player.color === myColor) {
                    img.src = `/assets/player_sprites/alive/player_${player.color}.png`;
                    img.style.filter = 'grayscale(80%) opacity(0.5)';
                }
                else {
                    img.src = player.is_alive
                        ? `/assets/player_sprites/alive/player_${player.color}.png`
                        : `/assets/player_sprites/dead/${player.color}_body.png`;
                }
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
