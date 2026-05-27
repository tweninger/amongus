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
    const waitingPanel = document.getElementById('waiting-panel');

    // --- Queue countdown ---
    let _countdownInterval = null;

    // Start countdown to game start based on queue deadline.
    // Dynamically updates every second.
    function startQueueCountdown(deadline) { // deadline in unix timestamp (seconds)
        const el = document.getElementById('queue-countdown');
        if (!el){
            return;
        }
        if (_countdownInterval){
            clearInterval(_countdownInterval);
        }
        _countdownInterval = setInterval(() => {
            const timeLeft = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
            el.textContent = `Game starts in ${timeLeft}s`;
            if (timeLeft === 0){
                clearInterval(_countdownInterval); _countdownInterval = null;
            }
        }, 1000);
    }

    // --- Waiting Room after joining the queue ---
    function enterWaitingRoom(data) {
        state.playerToken = data.token;
        state.myColor = data.color;
        state.myRole = data.role;
        connectWebSocket();

        if (userDisplay) userDisplay.innerText = formatColorName(data.color);
        if (state.phaseDisplay) state.phaseDisplay.innerText = "Staging";

        matchmakingPanel.classList.add('d-none');
        waitingPanel.classList.remove('d-none');

        if (data.queue_deadline) startQueueCountdown(data.queue_deadline);
    }

    // --- Enter Game Screen ---
    async function enterGame(myColor) {
        if (_countdownInterval){
            clearInterval(_countdownInterval);
            _countdownInterval = null;
        }
        if (lobbyScreen) lobbyScreen.classList.add('d-none');
        if (gameScreen) gameScreen.classList.remove('d-none');
        if (state.actionPanel) state.actionPanel.classList.add('d-none');
        showRoleReveal(state.myRole, myColor);
        state.gameStarted = true;
        addLogMessage(`Welcome to Skeld, ${formatColorName(myColor)}`, 'success');
        await apiFetch('/api/next-step', { method: 'POST' });
        await refreshRoomContext();
        await updateMapUI();
    }

    // --- WS: handle lobby events ---
    window._wsLobbyHandler = async (msg) => {
        if (msg.type === 'game_started') {
            await enterGame(state.myColor);
        }
    };

    // --- JOIN QUEUE button ---
    const queueBtn = document.getElementById('queue-btn');
    if (queueBtn) {
        queueBtn.addEventListener('click', async () => {
            queueBtn.disabled = true;
            queueBtn.innerText = 'Joining...';
            try {
                const res = await fetch('/api/queue', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ size: 'FIVE_MEMBER_GAME' }),
                });
                if (res.ok) {
                    const data = await res.json();
                    enterWaitingRoom(data);
                }
                else {
                    queueBtn.disabled = false;
                    queueBtn.innerText = 'Join Queue';
                }
            }
            catch (e) {
                console.error('Queue error:', e);
                queueBtn.disabled = false;
                queueBtn.innerText = 'Join Queue';
            }
        });
    }

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
