// meeting.js
// Handles UI updates and interactions during meetings, including chat rendering, voting roster, and ejection announcements.

import { state } from './state.js';
import { apiFetch, displayColor } from './helpers.js';

// Display visual notification in chat when a vote result is announced at the end of a meeting
function showEjectionBanner(voteResult) {
    const chatBox = document.getElementById('discussion-chat');
    if (!chatBox){
        return;
    }

    const banner = document.createElement('div');
    banner.className = 'text-center p-3 my-2 animate__animated animate__fadeIn';
    banner.style.cssText = 'background: rgba(0,0,0,0.6); border-radius: 12px;';

    const ejected = voteResult.ejected;

    // Did someone get voted out?
    if (ejected) {
        // Then show their color and name in the banner
        banner.innerHTML = `
            <img src="/assets/player_sprites/dead/${ejected}_body.png" style="width:60px;height:60px;object-fit:contain;margin-bottom:8px;"><br>
            <span class="fw-bold text-warning" style="font-size:1.1rem;">${ejected.charAt(0).toUpperCase() + ejected.slice(1)} was ejected.</span>`;
    }
    // Simply show no one was ejected
    else {
        banner.innerHTML = `<span class="fw-bold text-warning" style="font-size:1.1rem;">No one was ejected.</span>`;
    }

    chatBox.appendChild(banner);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Render new chat messages in the meeting discussion panel.
// Called each time the meeting-context poll returns updated messages.
function renderMeetingChat(messages) {
    // Return if no new messages since last render
    if (!messages || messages.length <= state.processedMessageCount){
        return;
    }
    const chatBox = document.getElementById('discussion-chat');
    if (!chatBox){
        return;
    }
    // Get the new messages that haven't been rendered yet
    const newMessages = messages.slice(state.processedMessageCount);

    // Append each new msg to chat box with sender name and color styling 
    newMessages.forEach(msg => {
        const text = msg.text;
        // Strips quotes added by the backend for messages that are purely talking strings
        msg.text = (text.startsWith('"') && text.endsWith('"') && text.length > 1) ? text.slice(1, -1) : text;
        const msgDiv = document.createElement('div');
        msgDiv.className = "d-flex align-items-start mb-3 p-2 animate__animated animate__fadeInUp";
        msgDiv.style.cssText = `background-color: rgba(255,255,255,0.05); border-radius: 8px; border-left: 4px solid ${displayColor(msg.sender_color)};`;
        msgDiv.innerHTML = `
            <img src="/assets/player_sprites/alive/player_${msg.sender_color}.png" style="width: 40px; height: 40px; margin-right: 12px; border-radius: 50%;">
            <div style="flex-grow: 1;">
                <div class="d-flex justify-content-between">
                    <strong style="color: ${displayColor(msg.sender_color)}; font-size: 0.85rem;">${msg.sender_name}</strong>
                </div>
                <p class="mb-0 text-light" style="font-size: 0.95rem;">${msg.text}</p>
            </div>`;
        chatBox.appendChild(msgDiv);
    });
    chatBox.scrollTop = chatBox.scrollHeight;

    // Store the count of processed messages so we only render new ones next time
    state.processedMessageCount = messages.length;
}

// Update the meeting UI based on whether it's the player's turn to speak or vote, and whether they are alive or a ghost.
// Meeting UI includes the chat input area and the voting roster.
function updateMeetingUI(data) {
    const chatInputGroup = document.getElementById('chat-input-group');
    const votingRoster = document.getElementById('voting-roster-container');
    const sendBtn = document.getElementById('send-chat-btn');
    const chatInput = document.getElementById('chat-input');

    if (data.is_my_turn) {
        const meetingOverlayEl = document.getElementById('meeting-overlay');
        if (meetingOverlayEl && meetingOverlayEl.classList.contains('d-none')) {
            meetingOverlayEl.classList.remove('d-none');
        }

        // Unlock chat input if it's new turn for this player
        if (data.discussion_turn_seq !== state.lastDiscussionTurnSeq) {
            state.chatInputLocked = false;
        }

        // Voting turn. Only show voting roster and skip button if player is alive.
        if (data.can_vote && data.is_alive) {
            if (chatInputGroup) chatInputGroup.style.display = 'none';
            const skipBtn = document.getElementById('skip-vote-btn');
            if (skipBtn) skipBtn.style.display = 'block';
            // Populate voting roster if not already populated for this meeting
            if (votingRoster && votingRoster.innerHTML.trim() === '') {
                populateVotingRoster();
            }
        }
        // Discussion turn. Show chat input and turn prompt. 
        // If player is a ghost, disable chat input and change button to "Pass Turn"
        else if (!state.chatInputLocked) {
            const turnPrompt = document.getElementById('turn-prompt');
            if (turnPrompt) {
                turnPrompt.style.display = 'block';
                turnPrompt.innerText = data.is_alive ? "It's your turn to speak." : "You are a ghost. Pass your turn.";
            }
            if (chatInputGroup) chatInputGroup.style.display = 'flex';
            if (sendBtn) {
                sendBtn.disabled = false;
                sendBtn.innerText = data.is_alive ? "Send" : "Pass Turn";
            }
            // If player is a ghost, disable chat input and set placeholder text
            if (chatInput && !data.is_alive) {
                chatInput.value = "Observing Discussion...";
                chatInput.disabled = true;
            } 
            else if (chatInput) {
                chatInput.disabled = false;
            }
        }
    }
    // Not your turn.
    else {
        const turnPrompt = document.getElementById('turn-prompt');
        if (turnPrompt) {
            // Small reminder text to indicate it's not the player's turn
            if (!data.can_vote && data.is_alive) {
                turnPrompt.style.display = 'block';
                turnPrompt.innerText = 'It is currently another player\'s turn to speak';
                turnPrompt.className = 'text-success fw-bold small text-center mb-1';
            } 
            else {
                turnPrompt.style.display = 'none';
            }
        }
        if (chatInputGroup) chatInputGroup.style.display = 'none';
    }

    state.lastDiscussionTurnSeq = data.discussion_turn_seq;
}


// Create and handle voting roster during voting phase
async function populateVotingRoster() {
    const response = await apiFetch('/api/player-states'); // Get current states of all players to populate voting roster with alive players
    const data = await response.json();
    const container = document.getElementById('voting-roster-container');
    const userDisplayEl = document.getElementById('user-display');
    const myColor = userDisplayEl ? userDisplayEl.innerText.toLowerCase() : "";

    if (!container || !data.players){
        return;
    }
    container.innerHTML = '';

    data.players.forEach(player => {
        // Don't show yourself in the voting roster
        if (player.color === myColor){
            return;
        }
        // Only show alive players as voting options
        if (!player.is_alive){
            return;
        }

        // Create the vote button for this player
        const btn = document.createElement('button');
        btn.className = 'list-group-item list-group-item-action bg-dark text-light border-secondary d-flex align-items-center mb-1';
        btn.style.cursor = "pointer";
        btn.innerHTML = `<img src="/assets/player_sprites/alive/player_${player.color}.png" style="width: 30px; margin-right: 15px;"><span>Vote for <strong>${player.name}</strong></span>`;

        // Handles voting when target is clicked
        btn.onclick = async () => {
            container.querySelectorAll('button').forEach(b => b.disabled = true);
            btn.classList.add('bg-danger', 'text-white');

            // Send vote to server.
            await apiFetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: player.color })
            });
        };
        container.appendChild(btn);
    });

    // FIX NEEDED
    const skipBtn = document.getElementById('skip-vote-btn');
    if (skipBtn) {
        skipBtn.onclick = async () => {
            container.querySelectorAll('button').forEach(b => b.disabled = true);
            skipBtn.disabled = true;
            await apiFetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: "none" })
            });
        };
    }
}

// Handle sending chat messages or passing turn if ghost. 
// Locks input until next turn to prevent repeated presses
async function handleSendChat() {
    const isGhost = state.chatInput.disabled || state.chatInput.value === "Observing Discussion...";
    const message = state.chatInput.value.trim();

    // Alive players must type something before submitting
    if (!isGhost && !message){
        return;
    }

    // Lock chat input and button to prevent repeated presses while waiting for server response
    state.chatInputLocked = true;
    state.sendChatBtn.disabled = true;
    state.sendChatBtn.innerText = "Sent!";
    if (state.chatInput) state.chatInput.disabled = true;

    try {
        if (!isGhost) {
            // Queue the speak action with the message for the server to process in the current game step.
            await apiFetch('/api/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });
            state.chatInput.value = '';
        }
        else {
            // Ghost mode: queue a nudge action to pass the turn without a message
            await apiFetch('/api/set-nudge', { method: 'POST' });
        }
    }
    catch (error) {
        console.error("Chat Error:", error);
        // Unlock on error so the player can retry
        state.chatInputLocked = false;
        state.sendChatBtn.disabled = false;
        state.sendChatBtn.innerText = isGhost ? "Pass Turn" : "Send";
        if (state.chatInput) state.chatInput.disabled = false;
    }
}

export { showEjectionBanner, renderMeetingChat, updateMeetingUI, handleSendChat };
