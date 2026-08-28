// game.js
// Entry point for the game screen. 
// Handles lobby flow, initializes game UI, and sets up WebSocket handlers for game events.

import { state } from './state.js';
import { apiFetch, addLogMessage, formatColorName } from './helpers.js';
import { handleChatTyping, handleSendChat } from './meeting.js';
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
    const matchmakingRoster = document.getElementById('matchmaking-roster');
    const browsePanel = document.getElementById('browse-panel');
    const waitingPanel = document.getElementById('waiting-panel');
    const startGameBtn = document.getElementById('start-game-btn');
    const waitingHint = document.getElementById('waiting-hint');
    const lobbyTimer = document.getElementById('lobby-timer');
    const matchmakingStatus = document.getElementById('matchmaking-status');
    const consentAgreeBtn = document.getElementById('consent-agree-btn');
    let hasShownAboutThisGame = false;
    let hasConsented = false;
    let consentToken = null;
    const lobbyFallbackColors = ['red', 'blue', 'green', 'pink', 'orange'];

    function spritePath(color) {
        return `/assets/player_sprites/alive/player_${color.toLowerCase()}.png`;
    }

    function showAboutThisGameOnce() {
        if (hasShownAboutThisGame) {
            return;
        }
        const modalEl = document.getElementById('about-this-game-modal');
        if (!modalEl || typeof bootstrap === 'undefined') {
            return;
        }
        hasShownAboutThisGame = true;
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    async function recordConsent() {
        if (hasConsented && consentToken) {
            return true;
        }
        if (consentAgreeBtn) {
            consentAgreeBtn.disabled = true;
            consentAgreeBtn.innerText = 'Saving...';
        }
        try {
            const response = await fetch('/api/consent', { method: 'POST' });
            if (!response.ok) {
                throw new Error('Unable to record consent');
            }
            const data = await response.json();
            consentToken = data.consent_token;
            hasConsented = true;
            return true;
        }
        catch (error) {
            console.error('Consent error:', error);
            if (matchmakingStatus) {
                matchmakingStatus.innerText = 'Unable to record consent. Please try again.';
            }
            return false;
        }
        finally {
            if (consentAgreeBtn) {
                consentAgreeBtn.disabled = false;
                consentAgreeBtn.innerText = 'I Agree';
            }
        }
    }

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

    function normalizeMatchmakingRoster(roster, totalSlots = lobbyFallbackColors.length) {
        const safeTotal = Math.max(totalSlots || 0, lobbyFallbackColors.length);
        const slots = Array.from({ length: safeTotal }, (_, id) => ({
            id,
            color: lobbyFallbackColors[id] || lobbyFallbackColors[id % lobbyFallbackColors.length],
            slot_status: 'open',
        }));

        if (!Array.isArray(roster) || roster.length === 0) {
            return slots;
        }

        roster.forEach((player, index) => {
            if (!player) {
                return;
            }
            const id = Number.isInteger(player.id) ? player.id : index;
            if (id < 0 || id >= slots.length) {
                return;
            }

            slots[id] = {
                ...slots[id],
                ...player,
                color: player.color || slots[id].color,
                slot_status: player.slot_status || 'open',
            };
        });

        return slots;
    }

    function renderMatchmakingRoster(roster, myColor = null, totalSlots = lobbyFallbackColors.length) {
        if (!matchmakingRoster){
            return;
        }
        const slots = normalizeMatchmakingRoster(roster, totalSlots);
        matchmakingRoster.innerHTML = '';

        slots.forEach(player => {
            const li = document.createElement('li');
            li.className = `lobby-player-slot list-group-item ${player.slot_status === 'open' ? 'is-open' : 'is-filled'}`;
            const isMe = player.color === myColor;
            const img = document.createElement('img');
            img.className = 'lobby-player-sprite';
            img.src = spritePath(player.color);
            img.alt = player.slot_status === 'open'
                ? 'Open player slot'
                : `${formatColorName(player.color)} player`;

            const status = document.createElement('span');
            status.className = 'lobby-player-status';
            status.innerText = player.slot_status === 'open'
                ? 'Waiting'
                : (isMe ? 'You' : formatColorName(player.color));

            li.append(img, status);
            matchmakingRoster.appendChild(li);
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

        renderMatchmakingRoster(data.roster, data.color, data.total_slots);

        // Keep matchmaking visible; it is the visual connection state.
        matchmakingPanel.classList.remove('d-none');
        browsePanel.classList.add('d-none');
        waitingPanel.classList.remove('d-none');
        if (startGameBtn) {
            startGameBtn.classList.add('d-none');
        }
        if (waitingHint) {
            waitingHint.classList.remove('d-none');
        }
        if (matchmakingStatus) {
            matchmakingStatus.innerText = 'Players joining...';
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
            renderMatchmakingRoster(msg.roster, state.myColor, msg.total_slots);
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
                body: JSON.stringify({ size: 'FIVE_MEMBER_GAME', consent_token: consentToken }),
            });
            if (!response.ok) {
                throw new Error('Failed to matchmake');
            }
            const data = await response.json();
            await enterWaitingRoom(data);
        }
        catch (e) {
            console.error('Matchmake error:', e);
            consentToken = null;
            if (matchmakingStatus) {
                matchmakingStatus.innerText = 'Unable to find a game right now. Refresh to retry.';
            }
        }
    }

    if (consentAgreeBtn) {
        consentAgreeBtn.addEventListener('click', async () => {
            const modalEl = document.getElementById('about-this-game-modal');
            if (hasConsented) {
                if (modalEl && typeof bootstrap !== 'undefined') {
                    bootstrap.Modal.getOrCreateInstance(modalEl).hide();
                }
                return;
            }
            const accepted = await recordConsent();
            if (!accepted) {
                return;
            }
            if (modalEl && typeof bootstrap !== 'undefined') {
                bootstrap.Modal.getOrCreateInstance(modalEl).hide();
            }
            autoMatchmake();
        });
    }
    if (matchmakingStatus) {
        matchmakingStatus.innerText = 'Please review and accept the consent form to begin.';
    }
    showAboutThisGameOnce();

    // --- Chat Handler ---
    if (state.sendChatBtn) {
        state.sendChatBtn.onclick = handleSendChat;
    }
    if (state.chatInput) {
        state.chatInput.addEventListener('input', handleChatTyping);
        state.chatInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter'){
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();
                handleSendChat();
            }
        });
    }
});
