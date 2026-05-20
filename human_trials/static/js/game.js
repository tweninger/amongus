// game.js
// Entry point for the game screen. 
// Handles lobby flow, initializes game UI, and sets up WebSocket handlers for game events.

import { state } from './state.js';
import { apiFetch, addLogMessage, formatColorName, displayColor } from './helpers.js';
import { handleSendChat } from './meeting.js';
import { showRoleReveal, updateTaskProgressBar, updateMapUI } from './ui.js';
import { refreshRoomContext } from './actions.js';
import { connectWebSocket } from './websocket.js';

document.addEventListener('DOMContentLoaded', () => {

    // --- DOM Refs ---
    state.actionPanel = document.getElementById('action-panel');
    state.phaseDisplay = document.getElementById('current-phase');
    state.sendChatBtn = document.getElementById('send-chat-btn');
    state.chatInput = document.getElementById('chat-input');

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
        state.playerToken = data.token;
        state.myColor = data.color;
        state.myRole = data.role;
        connectWebSocket(); // Connect WS after entering waiting room

        // Show user their color in the sidebar
        if (userDisplay){
            userDisplay.innerText = formatColorName(data.color);
        }
        if (state.phaseDisplay){
            state.phaseDisplay.innerText = "Staging";
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
        if (state.actionPanel) state.actionPanel.classList.add('d-none');
        showRoleReveal(state.myRole, myColor); // Role Modal
        state.gameStarted = true;
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
            renderWaitingRoster(msg.roster, state.myColor);
        }
        else if (msg.type === 'game_started') {
            await enterGame(state.myColor);
        }
        else if (msg.type === 'room_closed') {
            alert('The host left. This room is closed.');
            window.location.reload();
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
            }
            catch (e) {
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
                        <img src="/assets/player_sprites/alive/player_${lobby.host_color}.png" style="width:30px;">
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
    // Load lobbies immediately if user clicks browse before hosting or joining
    if (browseBtn){
        browseBtn.addEventListener('click', () => {
        matchmakingPanel.classList.add('d-none');
        browsePanel.classList.remove('d-none');
        loadLobbies();
        });
    }
    // Back to the main matchmaking panel
    if (backBtn){
        backBtn.addEventListener('click', () => {
        browsePanel.classList.add('d-none');
        matchmakingPanel.classList.remove('d-none');
    });
    }
    // Refresh lobby list if user is on the browse panel
    if (refreshBtn){
        refreshBtn.addEventListener('click', loadLobbies);
    }

    // --- Chat Handler ---
    if (state.sendChatBtn) {
        state.sendChatBtn.onclick = handleSendChat;
    }
});
