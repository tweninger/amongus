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
    const lobbyTimer = document.getElementById('lobby-timer');
    const matchmakingStatus = document.getElementById('matchmaking-status');

    function stopLobbyCountdown() {
        if (state.lobbyCountdownTimer) {
            clearInterval(state.lobbyCountdownTimer);
            state.lobbyCountdownTimer = null;
        }
    }

    function setLobbyCountdown(secondsLeft) {
        stopLobbyCountdown();
        if (!lobbyTimer) {
            return;
        }
        if (secondsLeft == null) {
            lobbyTimer.classList.add('d-none');
            return;
        }

        let remaining = Math.max(0, Number(secondsLeft));
        lobbyTimer.classList.remove('d-none');

        const render = () => {
            lobbyTimer.innerText = remaining > 0
                ? `Game Starts In ${remaining}s`
                : 'Game Starts In 0s';
        };

        render();
        state.lobbyCountdownTimer = setInterval(() => {
            remaining = Math.max(0, remaining - 1);
            render();
            if (remaining <= 0) {
                stopLobbyCountdown();
            }
        }, 1000);
    }

    // --- Game Size selector (host only) ---
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
            let badge = '<span class="badge bg-secondary">Waiting...</span>';
            if (player.slot_status !== 'open') {
                badge = '<span class="badge bg-success">Joined</span>';
            }
            li.innerHTML = `<span style="color:${displayColor(player.color)};font-weight:bold;">${label}</span>${badge}`;
            readyChecklist.appendChild(li);
        });
    }

    // --- Waiting Room after Joining or Hosting ---
    async function enterWaitingRoom(data) {
        state.playerToken = data.token;
        state.myColor = data.color;
        state.myRole = data.role;
        connectWebSocket(); // Connect WS after entering waiting room
        setLobbyCountdown(data.lobby_seconds_left);

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
        if (startGameBtn) {
            startGameBtn.classList.add('d-none');
        }
        if (waitingHint) {
            waitingHint.classList.remove('d-none');
        }

        if (data.room_status === 'active') {
            stopLobbyCountdown();
            await enterGame(state.myColor);
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
            setLobbyCountdown(msg.lobby_seconds_left);
        }
        else if (msg.type === 'game_started') {
            stopLobbyCountdown();
            await enterGame(state.myColor);
        }
        else if (msg.type === 'room_closed') {
            stopLobbyCountdown();
            alert('The host left. This room is closed.');
            window.location.reload();
        }
    };

    async function autoMatchmake() {
        try {
            const response = await fetch('/api/matchmake', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ size: 'FIVE_MEMBER_GAME' }),
            });
            if (!response.ok) {
                throw new Error('Failed to matchmake');
            }
            const data = await response.json();
            await enterWaitingRoom(data);
        }
        catch (e) {
            console.error('Matchmake error:', e);
            if (matchmakingStatus) {
                matchmakingStatus.innerText = 'Unable to find a game right now. Refresh to retry.';
            }
        }
    }

    autoMatchmake();

    // --- Chat Handler ---
    if (state.sendChatBtn) {
        state.sendChatBtn.onclick = handleSendChat;
    }
    if (state.chatInput) {
        state.chatInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter'){
                handleSendChat();
            }
        });
    }
});
