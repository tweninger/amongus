// meeting.js
// Handles UI updates and interactions during meetings, including chat rendering, voting roster, and ejection announcements.

import { state } from './state.js';
import { apiFetch, displayColor } from './helpers.js';

let typingStopTimer = null;
let humanTypingAnnounced = false;

function removeThinkingIndicator() {
    const existing = document.getElementById('meeting-thinking-indicator');
    if (existing) {
        existing.remove();
    }
}

function renderThinkingIndicator(data) {
    const chatBox = document.getElementById('discussion-chat');
    const players = Array.isArray(data.thinking_players) ? data.thinking_players : [];
    if (!chatBox || data.can_vote || players.length === 0) {
        removeThinkingIndicator();
        return;
    }
    let indicator = document.getElementById('meeting-thinking-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'meeting-thinking-indicator';
        indicator.className = 'meeting-thinking-row';
        chatBox.appendChild(indicator);
    }

    const names = players.map(player => (
        `<strong style="color: ${displayColor(player.color)};">${player.name}</strong>`
    ));
    const nameList = names.length === 1
        ? names[0]
        : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
    indicator.innerHTML = `
        <span class="meeting-thinking-names">${nameList}</span>
        <span class="meeting-thinking-text">${players.length === 1 ? 'is' : 'are'} typing</span>
        <span class="meeting-typing-dots" aria-label="typing"><span></span><span></span><span></span></span>`;
    chatBox.scrollTop = chatBox.scrollHeight;
}

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
    removeThinkingIndicator();

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

// Update the shared-discussion and voting controls for the current meeting state.
function updateMeetingUI(data) {
    const chatInputGroup = document.getElementById('chat-input-group');
    const votingRoster = document.getElementById('voting-roster-container');
    const sendBtn = document.getElementById('send-chat-btn');
    const chatInput = document.getElementById('chat-input');
    renderThinkingIndicator(data);

    const meetingOverlayEl = document.getElementById('meeting-overlay');
    if (meetingOverlayEl) meetingOverlayEl.classList.remove('d-none');
    const turnPrompt = document.getElementById('turn-prompt');
    const skipBtn = document.getElementById('skip-vote-btn');

    if (data.can_vote && data.is_alive) {
        if (chatInputGroup) chatInputGroup.style.display = 'none';
        if (turnPrompt) turnPrompt.style.display = 'none';
        if (skipBtn) skipBtn.style.display = 'block';
        if (votingRoster && votingRoster.innerHTML.trim() === '') populateVotingRoster();
    } else if (data.discussion_open && data.is_alive) {
        if (votingRoster) votingRoster.innerHTML = '';
        if (skipBtn) skipBtn.style.display = 'none';
        if (turnPrompt) {
            turnPrompt.style.display = 'block';
            turnPrompt.innerText = 'Discussion is open. Speak whenever you are ready.';
            turnPrompt.className = 'text-success fw-bold small text-center mb-1';
        }
        if (chatInputGroup) chatInputGroup.style.display = 'flex';
        if (sendBtn) {
            sendBtn.disabled = state.chatInputLocked;
            sendBtn.innerText = state.chatInputLocked ? 'Sending...' : 'Send';
        }
        if (chatInput) chatInput.disabled = false;
    } else if (!data.is_alive) {
        if (chatInputGroup) chatInputGroup.style.display = 'none';
        if (turnPrompt) {
            turnPrompt.style.display = 'block';
            turnPrompt.innerText = 'You are a ghost and cannot speak or vote.';
            turnPrompt.className = 'text-secondary fw-bold small text-center mb-1';
        }
        if (skipBtn) skipBtn.style.display = 'none';
    } else {
        if (chatInputGroup) chatInputGroup.style.display = 'none';
        if (turnPrompt) {
            turnPrompt.style.display = 'block';
            turnPrompt.innerText = 'Discussion is starting...';
            turnPrompt.className = 'text-danger fw-bold small text-center mb-1';
        }
        if (skipBtn) skipBtn.style.display = 'none';
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
            document.getElementById('skip-vote-btn').disabled = true;
            btn.classList.remove('bg-dark', 'border-secondary');
            btn.classList.add('vote-selected', 'text-white');

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
            skipBtn.classList.remove('btn-outline-warning');
            skipBtn.classList.add('vote-skip-selected', 'text-dark');
            await apiFetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target: "none" })
            });
        };
    }
}

// Send a discussion message. The short lock prevents duplicate requests only.
async function handleSendChat() {
    if (state.chatInputLocked) {
        return;
    }
    const message = state.chatInput.value.trim();

    if (!message){
        return;
    }

    clearTimeout(typingStopTimer);
    setHumanTyping(false);

    // Lock chat input and button to prevent repeated presses while waiting for server response
    state.chatInputLocked = true;
    state.sendChatBtn.disabled = true;
    state.sendChatBtn.innerText = "Sending...";
    state.chatInput.value = '';
    state.chatInput.focus();

    try {
        // The server records shared discussion messages immediately.
        const response = await apiFetch('/api/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });
        if (!response.ok) {
            throw new Error('Discussion message was not accepted.');
        }
    }
    catch (error) {
        console.error("Chat Error:", error);
    }
    finally {
        state.chatInputLocked = false;
        state.sendChatBtn.disabled = false;
        state.sendChatBtn.innerText = "Send";
        state.chatInput?.focus();
    }
}

function setHumanTyping(isTyping) {
    if (isTyping === humanTypingAnnounced) {
        return;
    }
    humanTypingAnnounced = isTyping;
    apiFetch('/api/typing', {
        method: 'POST',
        body: JSON.stringify({ is_typing: isTyping }),
    }).catch(() => {
        humanTypingAnnounced = false;
    });
}

function handleChatTyping() {
    if (!state.chatInput || !state.chatInput.value.trim()) {
        clearTimeout(typingStopTimer);
        setHumanTyping(false);
        return;
    }
    setHumanTyping(true);
    clearTimeout(typingStopTimer);
    typingStopTimer = setTimeout(() => setHumanTyping(false), 1200);
}

export { showEjectionBanner, renderMeetingChat, updateMeetingUI, handleSendChat, handleChatTyping };
