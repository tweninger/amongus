// Socket.io connection
const socket = io();

// Game state
let gameState = {
    players: [],
    currentPlayer: null,
    tasks: [],
    isImpostor: false,
    isDead: false,
    meetingInProgress: false
};

// DOM Elements
const loginScreen = document.getElementById('login-screen');
const gameScreen = document.getElementById('game-screen');
const playerNameInput = document.getElementById('player-name');
const roomCodeInput = document.getElementById('room-code');
const joinButton = document.getElementById('join-game');
const gameCanvas = document.getElementById('game-canvas');
const playersList = document.getElementById('players-list');
const tasksList = document.getElementById('tasks-list');
const meetingModal = document.getElementById('meeting-screen');
const discussionText = document.getElementById('meeting-reason');
const votingOptions = document.getElementById('voting-options');
const actionForm = document.getElementById('action-form');
const actionOptions = document.getElementById('action-options');
const messageInput = document.getElementById('message-input');
const submitActionButton = document.getElementById('submit-action');
const submitVoteButton = document.getElementById('submit-vote');

// Canvas setup
const ctx = gameCanvas.getContext('2d');

// Load the Skeld map image
const mapImage = new Image();
mapImage.src = '/static/assets/skeld.png';

// Join game
joinButton.addEventListener('click', () => {
    const playerName = playerNameInput.value.trim();
    const roomCode = roomCodeInput.value.trim();
    
    if (playerName && roomCode) {
        socket.emit('join_game', { playerName, roomCode });
        loginScreen.classList.add('d-none');
        gameScreen.classList.remove('d-none');
    }
});

// Socket event handlers
socket.on('game_state', (state) => {
    gameState = state;
    updateGameUI();
});

socket.on('player_joined', (player) => {
    gameState.players.push(player);
    updatePlayersList();
});

socket.on('player_left', (playerId) => {
    gameState.players = gameState.players.filter(p => p.id !== playerId);
    updatePlayersList();
});

socket.on('task_completed', (taskId) => {
    const task = gameState.tasks.find(t => t.id === taskId);
    if (task) {
        task.completed = true;
        updateTasksList();
    }
});

socket.on('emergency_meeting', (data) => {
    gameState.meetingInProgress = true;
    showMeetingModal(data);
});

socket.on('meeting_ended', () => {
    gameState.meetingInProgress = false;
    hideMeetingModal();
});

socket.on('available_actions', (actions) => {
    displayAvailableActions(actions);
});

// UI update functions
function updateGameUI() {
    updatePlayersList();
    updateTasksList();
    drawGame();
}

function updatePlayersList() {
    playersList.innerHTML = '';
    gameState.players.forEach(player => {
        const playerCard = document.createElement('div');
        playerCard.className = `player-card ${player.isImpostor ? 'impostor' : 'crewmate'} ${player.isDead ? 'dead' : ''}`;
        
        const colorDot = document.createElement('span');
        colorDot.className = 'color-dot';
        colorDot.style.backgroundColor = player.color;
        
        const playerName = document.createElement('span');
        playerName.textContent = player.name;
        
        playerCard.appendChild(colorDot);
        playerCard.appendChild(playerName);
        playersList.appendChild(playerCard);
    });
}

function updateTasksList() {
    tasksList.innerHTML = '';
    gameState.tasks.forEach(task => {
        const taskItem = document.createElement('div');
        taskItem.className = `task-item ${task.completed ? 'completed' : ''}`;
        
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'task-checkbox';
        checkbox.checked = task.completed;
        checkbox.disabled = true;
        
        const taskName = document.createElement('span');
        taskName.textContent = task.name;
        
        taskItem.appendChild(checkbox);
        taskItem.appendChild(taskName);
        tasksList.appendChild(taskItem);
    });
}

function drawGame() {
    ctx.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
    
    // Draw the Skeld map
    ctx.drawImage(mapImage, 0, 0, gameCanvas.width, gameCanvas.height);
    
    // Draw players
    gameState.players.forEach(player => {
        if (!player.isDead) {
            ctx.beginPath();
            ctx.arc(player.x, player.y, 15, 0, Math.PI * 2);
            ctx.fillStyle = player.color;
            ctx.fill();
            ctx.strokeStyle = player.isImpostor ? 'red' : 'white';
            ctx.lineWidth = 2;
            ctx.stroke();
            
            // Draw player name
            ctx.fillStyle = 'white';
            ctx.font = '12px Arial';
            ctx.textAlign = 'center';
            ctx.fillText(player.name, player.x, player.y - 20);
        }
    });
}

// Meeting modal functions
function showMeetingModal(data) {
    discussionText.textContent = `Emergency meeting called by ${data.caller}!`;
    votingOptions.innerHTML = '';
    
    gameState.players.forEach(player => {
        if (!player.isDead) {
            const option = document.createElement('div');
            option.className = 'voting-option';
            option.textContent = player.name;
            option.onclick = () => selectVote(player.id);
            votingOptions.appendChild(option);
        }
    });
    
    // Show the modal using Bootstrap
    const modal = new bootstrap.Modal(meetingModal);
    modal.show();
}

function hideMeetingModal() {
    // Hide the modal using Bootstrap
    const modal = bootstrap.Modal.getInstance(meetingModal);
    if (modal) {
        modal.hide();
    }
}

function selectVote(playerId) {
    const options = votingOptions.getElementsByClassName('voting-option');
    for (let option of options) {
        option.classList.remove('selected');
    }
    event.target.classList.add('selected');
    gameState.selectedVote = playerId;
}

// Submit vote button
submitVoteButton.addEventListener('click', () => {
    if (gameState.selectedVote) {
        socket.emit('cast_vote', { targetId: gameState.selectedVote });
        hideMeetingModal();
    }
});

// Action selection functions
function displayAvailableActions(actions) {
    actionOptions.innerHTML = '';
    
    actions.forEach((action, index) => {
        const actionDiv = document.createElement('div');
        actionDiv.className = 'form-check';
        
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.className = 'form-check-input';
        radio.name = 'action';
        radio.id = `action-${index}`;
        radio.value = action.name;
        radio.onchange = () => toggleMessageInput(action.name === 'SPEAK');
        
        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.htmlFor = `action-${index}`;
        label.textContent = action.name;
        
        actionDiv.appendChild(radio);
        actionDiv.appendChild(label);
        actionOptions.appendChild(actionDiv);
    });
    
    // Add message input for SPEAK action (hidden by default)
    messageInput.style.display = 'none';
    
    // Show the action form
    actionForm.style.display = 'block';
}

function toggleMessageInput(show) {
    messageInput.style.display = show ? 'block' : 'none';
}

submitActionButton.addEventListener('click', () => {
    const selectedAction = document.querySelector('input[name="action"]:checked');
    
    if (selectedAction) {
        const actionName = selectedAction.value;
        const message = actionName === 'SPEAK' ? messageInput.value : '';
        
        socket.emit('submit_action', { 
            action: actionName,
            message: message
        });
        
        // Clear the form
        actionForm.reset();
        messageInput.style.display = 'none';
    }
}); 