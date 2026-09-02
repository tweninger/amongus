// meeting.js
// Handles UI updates and interactions during meetings, including chat rendering, voting roster, and ejection announcements.

import { state } from './state.js';
import { apiFetch, displayColor } from './helpers.js';

let typingStopTimer = null;
let humanTypingAnnounced = false;
let influenceAnchor = null;
let influenceRendered = false;

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

function modal(id) {
    const element = document.getElementById(id);
    return element && typeof bootstrap !== 'undefined' ? bootstrap.Modal.getOrCreateInstance(element) : null;
}

function showModal(id) { modal(id)?.show(); }
function hideModal(id) { modal(id)?.hide(); }

function showInfluenceModal() {
    const element = document.getElementById('vote-influence-modal');
    const dialog = element?.querySelector('.modal-dialog');
    if (!element || !dialog) return;
    showModal('vote-influence-modal');
    if (!influenceAnchor) return;

    requestAnimationFrame(() => {
        const margin = 12;
        const rect = dialog.getBoundingClientRect();
        const left = Math.min(
            Math.max(margin, influenceAnchor.x + margin),
            window.innerWidth - rect.width - margin,
        );
        const top = Math.min(
            Math.max(margin, influenceAnchor.y + margin),
            window.innerHeight - rect.height - margin,
        );
        dialog.classList.add('vote-influence-anchored');
        dialog.style.left = `${left}px`;
        dialog.style.top = `${top}px`;
    });
}

function resetInfluenceModalPosition() {
    const dialog = document.querySelector('#vote-influence-modal .modal-dialog');
    if (!dialog) return;
    dialog.classList.remove('vote-influence-anchored');
    dialog.style.left = '';
    dialog.style.top = '';
}

function playerButton(player, text, { disabled = false, dead = false } = {}) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'vote-modal-option';
    button.disabled = disabled;
    const sprite = dead
        ? `/assets/player_sprites/dead/${player.color}_body.png`
        : `/assets/player_sprites/alive/player_${player.color}.png`;
    button.innerHTML = `<img src="${sprite}" alt=""><span>${text}</span>`;
    return button;
}

function setOptionsDisabled(container) {
    container?.querySelectorAll('button').forEach((button) => { button.disabled = true; });
}

function renderPreVote(data) {
    const timer = document.getElementById('pre-vote-timer');
    if (timer) timer.textContent = `${data.turn_seconds_left ?? 0}s`;
    if (!data.pre_vote_open) {
        hideModal('pre-vote-modal');
        return;
    }
    showModal('pre-vote-modal');
    const options = document.getElementById('pre-vote-options');
    const waiting = document.getElementById('pre-vote-waiting');
    if (!options || !waiting) return;
    if (data.pre_vote_submitted) {
        options.innerHTML = '';
        waiting.classList.remove('d-none');
        return;
    }
    waiting.classList.add('d-none');
    options.innerHTML = '';
    (data.players || []).forEach((player) => {
        const dead = !player.is_alive;
        const isCurrentPlayer = player.color === state.myColor;
        const label = dead
            ? `${player.name} (Ghost)`
            : (isCurrentPlayer ? `${player.name} (You)` : player.name);
        const button = playerButton(player, label, {
            disabled: dead || !data.is_alive,
            dead,
        });
        button.addEventListener('click', async () => {
            setOptionsDisabled(options);
            button.classList.add('vote-modal-selected');
            const response = await apiFetch('/api/pre-vote', {
                method: 'POST', body: JSON.stringify({ target: player.color }),
            });
            if (!response.ok) button.disabled = false;
        });
        options.appendChild(button);
    });
    const unknown = document.createElement('button');
    unknown.type = 'button';
    unknown.className = 'vote-modal-option justify-content-center';
    unknown.textContent = 'I do not know';
    unknown.disabled = !data.is_alive;
    unknown.addEventListener('click', async () => {
        setOptionsDisabled(options);
        unknown.classList.add('vote-modal-selected');
        await apiFetch('/api/pre-vote', { method: 'POST', body: JSON.stringify({ target: 'unknown' }) });
    });
    options.appendChild(unknown);
}

function renderInfluence(data) {
    const options = document.getElementById('vote-influence-options');
    const submit = document.getElementById('submit-vote-influence');
    if (!options || !submit) return;
    options.innerHTML = '';
    (data.players || []).filter((player) => player.is_alive).forEach((player) => {
        const label = document.createElement('label');
        label.className = 'vote-influence-option';
        const labelText = player.color === state.myColor ? `${player.name} (You)` : player.name;
        label.innerHTML = `<input type="checkbox" value="${player.color}"><img src="/assets/player_sprites/alive/player_${player.color}.png" width="30" height="30" alt="">${labelText}`;
        options.appendChild(label);
    });
    const noOne = document.createElement('label');
    noOne.className = 'vote-influence-option';
    noOne.innerHTML = '<input type="checkbox" value="No one">No one';
    options.appendChild(noOne);
    noOne.querySelector('input').addEventListener('change', (event) => {
        if (event.target.checked) options.querySelectorAll('input:not([value="No one"])').forEach((input) => { input.checked = false; });
    });
    options.querySelectorAll('input:not([value="No one"])').forEach((input) => input.addEventListener('change', () => { noOne.querySelector('input').checked = false; }));
    submit.onclick = async () => {
        submit.disabled = true;
        const influences = [...options.querySelectorAll('input:checked')].map((input) => input.value);
        const response = await apiFetch('/api/vote-influence', {
            method: 'POST', body: JSON.stringify({ influences }),
        });
        if (response.ok) hideModal('vote-influence-modal');
        else submit.disabled = false;
    };
}

function renderFinalVote(data) {
    const timer = document.getElementById('final-vote-timer');
    if (timer) timer.textContent = `${data.turn_seconds_left ?? 0}s`;
    if (!data.can_vote || !data.is_alive) {
        hideModal('final-vote-modal');
        if (!data.is_alive) hideModal('vote-influence-modal');
        return;
    }
    if (data.vote_influence_submitted) {
        hideModal('final-vote-modal');
        hideModal('vote-influence-modal');
        influenceAnchor = null;
        influenceRendered = false;
        resetInfluenceModalPosition();
        return;
    }
    if (data.final_vote_selected) {
        if (!influenceRendered) {
            renderInfluence(data);
            influenceRendered = true;
        }
        showInfluenceModal();
        return;
    }
    showModal('final-vote-modal');
    const options = document.getElementById('final-vote-options');
    const skip = document.getElementById('final-skip-vote');
    if (!options || !skip) return;
    options.innerHTML = '';
    (data.players || []).filter((player) => player.is_alive && player.color !== state.myColor).forEach((player) => {
        const button = playerButton(player, player.name);
        button.addEventListener('click', async (event) => {
            influenceAnchor = { x: event.clientX, y: event.clientY };
            setOptionsDisabled(options);
            skip.disabled = true;
            button.classList.add('vote-modal-selected');
            await apiFetch('/api/vote', { method: 'POST', body: JSON.stringify({ target: player.color }) });
        });
        options.appendChild(button);
    });
    skip.onclick = async (event) => {
        influenceAnchor = { x: event.clientX, y: event.clientY };
        setOptionsDisabled(options);
        skip.disabled = true;
        skip.classList.remove('btn-outline-warning');
        skip.classList.add('btn-warning');
        await apiFetch('/api/vote', { method: 'POST', body: JSON.stringify({ target: 'none' }) });
    };
}

function hideMeetingVoteModals() {
    hideModal('pre-vote-modal');
    hideModal('final-vote-modal');
    hideModal('vote-influence-modal');
    influenceAnchor = null;
    influenceRendered = false;
    resetInfluenceModalPosition();
}

function updateMeetingUI(data) {
    const chatInputGroup = document.getElementById('chat-input-group');
    const sendBtn = document.getElementById('send-chat-btn');
    const chatInput = document.getElementById('chat-input');
    const turnPrompt = document.getElementById('turn-prompt');
    const meetingOverlayEl = document.getElementById('meeting-overlay');
    if (meetingOverlayEl) meetingOverlayEl.classList.remove('d-none');
    renderThinkingIndicator(data);
    renderPreVote(data);
    renderFinalVote(data);

    if (data.discussion_open && data.is_alive) {
        if (turnPrompt) {
            turnPrompt.style.display = 'block';
            turnPrompt.innerText = 'Discussion is open. Speak whenever you are ready.';
            turnPrompt.className = 'text-success fw-bold small text-center mb-1';
        }
        if (chatInputGroup) chatInputGroup.style.display = 'flex';
        if (sendBtn) sendBtn.disabled = state.chatInputLocked;
        if (chatInput) chatInput.disabled = false;
    } else {
        if (chatInputGroup) chatInputGroup.style.display = 'none';
        if (turnPrompt) {
            turnPrompt.style.display = 'block';
            turnPrompt.innerText = data.pre_vote_open
                ? (data.is_alive ? 'Enter your private pre-vote.' : 'You are a ghost and cannot vote.')
                : (data.final_vote_preparing ? 'Final votes are being prepared...' : 'Waiting for the vote.');
            turnPrompt.className = 'text-secondary fw-bold small text-center mb-1';
        }
    }
    state.lastDiscussionTurnSeq = data.discussion_turn_seq;
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

export { hideMeetingVoteModals, showEjectionBanner, renderMeetingChat, updateMeetingUI, handleSendChat, handleChatTyping };
