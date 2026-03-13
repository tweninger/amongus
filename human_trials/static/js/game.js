// game.js

// Map string name of room to the X/Y coordinates of skeld.png
// Used to overlay character imgs
const roomCoordinates = {
    "cafeteria": { top: 30, left: 50 },
    "weapons": { top: 25, left: 75 },
    "navigation": { top: 45, left: 88 },
    "o2": { top: 42, left: 68 },
    "shields": { top: 75, left: 75 },
    "communication": { top: 85, left: 65 },
    "communications": { top: 85, left: 65 },
    "admin": { top: 60, left: 65 },
    "storage": { top: 75, left: 50 },
    "electrical": { top: 60, left: 35 },
    "lower engine": { top: 75, left: 20 },
    "reactor": { top: 50, left: 10 },
    "security": { top: 50, left: 28 },
    "upper engine": { top: 25, left: 20 },
    "medbay": { top: 35, left: 35 }
};

document.addEventListener('DOMContentLoaded', () => {
    const startBtn = document.getElementById('start-btn');
    const playerCountDisplay = document.getElementById('player-count-display');

    const stagingPanel = document.getElementById('staging-panel');
    const actionPanel = document.getElementById('action-panel');
    const readyChecklist = document.getElementById('ready-checklist');
    const readyUpBtn = document.getElementById('ready-up-btn');
    let isHumanReady = false;
    let readyPlayers = 0;
    let totalPlayers = 0;

    const lobbyScreen = document.getElementById('lobby-screen');
    const gameScreen = document.getElementById('game-screen');
    const gameLog = document.getElementById('game-log');
    const userDisplay = document.getElementById('user-display');
    const phaseDisplay = document.getElementById('current-phase');
    const pingBtn = document.getElementById('ping-btn')

    // Grab 3, 5, and 7 player buttons
    const sizeButtons = document.querySelectorAll('#count-selector .btn');
    
    // Update the text on webpage when a new size is clicked
    const updatePlayerCountDisplay = () => {
        const activeBtn = document.querySelector('#count-selector .btn.active');
        const totalPlayerCount = parseInt(activeBtn.innerText);
        playerCountDisplay.innerText = `Current Setup ${totalPlayerCount} Players`;
        
    };

    // Update highlighted size (player count) button when clicked
    sizeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            sizeButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updatePlayerCountDisplay();
        });
    });

    // Start Button Logic
    startBtn.addEventListener('click', async () => {
        // Get config setup (ex: THREE_MEMBER_GAME) from the active button
        const activeSize = document.querySelector('#count-selector .btn.active').dataset.value;
        
        try {

            // Send chosen game size to server.py
            const response = await fetch('/api/join', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ size: activeSize})
            });

            if (response.ok) {
                const data = await response.json();
                
                // Update HUD
                if (userDisplay) userDisplay.innerText = data.color.charAt(0).toUpperCase() + data.color.slice(1);
                if (phaseDisplay) phaseDisplay.innerText = "Staging";

                // Set up role reveal
                const roleDisplay = document.getElementById('role-display');
                roleDisplay.innerText = data.role;

                if (data.role.toLowerCase() === 'impostor'){
                    roleDisplay.className = "display-3 fw-bold text-uppercase mb-5 text-danger"; // red
                }
                else{
                    roleDisplay.className = "display-3 fw-bold text-uppercase mb-5 text-info"; // blue
                }

                // Inject colors and PNG sprite to webpage
                document.getElementById('color-name-display').innerText = data.color;
                document.getElementById('color-name-display').style.color = data.color; 
                document.getElementById('color-img-display').src = `/static/assets/player_${data.color}.png`;

                // Display role modal
                const roleModal = new bootstrap.Modal(document.getElementById('role-reveal-modal'))
                roleModal.show();

                totalPlayers = data.roster.length;
                readyChecklist.innerHTML = ''; // Clear old lists

                // Build checklist UI
                data.roster.forEach(player => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item bg-dark text-light d-flex justify-content-between align-items-center';
                    li.id = `player-status-${player.id}`;

                    // Create name label and set its color
                    const nameSpan = document.createElement('span');
                    
                    if (player.is_human){
                        nameSpan.innerHTML = `<span style="color: ${player.color}; font-weight: bold;">${player.name} (me) </span>`;
                    }
                    else{
                        nameSpan.innerHTML = `<span style="color: ${player.color}; font-weight: bold;">${player.name}</span>`;
                    }

                    // Set status badge (waiting -> ready)
                    const statusBadge = document.createElement('span');
                    statusBadge.className = 'badge bg-secondary'; // greyed-out look
                    statusBadge.innerText = 'Waiting...'; // starts out waiting
                    statusBadge.id = `badge-${player.id}`;

                    // Render li
                    li.appendChild(nameSpan);
                    li.appendChild(statusBadge);
                    readyChecklist.appendChild(li);

                    // Create artificial delay for AI players
                    if (!player.is_human) {
                        // Random delay between 3s and 10s
                        const randomDelay = Math.floor(Math.random() * 7000) + 3000;

                        setTimeout(() => {
                            const badge = document.getElementById(`badge-${player.id}`);
                            if (badge) {
                                badge.className = 'badge bg-success';
                                badge.innerText = 'Ready';
                                readyPlayers++;
                                checkAllReady(); // Check if this was the last person needed
                            }
                        }, randomDelay);
                    }
                });

                // Human ready up logic
                readyUpBtn.onclick = () => {

                    // prevent accidental double clicking
                    if (isHumanReady){
                        return;
                    }

                    isHumanReady = true;

                    // Find human (agent id 0) and mark as ready
                    const humanBadge = document.getElementById('badge-0');
                    humanBadge.className = 'badge bg-success';
                    humanBadge.innerText = 'Ready';

                    readyUpBtn.className = 'btn btn-success btn-lg w-100 disabled';
                    readyUpBtn.innerText = 'Waiting...';

                    readyPlayers++;
                    checkAllReady();
                };


                // Handles start button and switch screens
                document.getElementById('enter-map-btn').onclick = () => {
                    if (lobbyScreen) lobbyScreen.classList.add('d-none');
                    if (gameScreen) gameScreen.classList.remove('d-none');
                    refreshRoomContext();
                    updateMapUI();
                }
                if (gameLog) gameLog.innerHTML += `<p class="text-success">> Player ${data.color} authenticated.</p>`;
            }
        } catch (error) {
            console.error("Failed to start:", error);
        }
    });

    // Handles the "Check Simulation Status Button"
     pingBtn.addEventListener('click', async () => {
        pingBtn.innerText = "AIs are thinking..."; // Visual feedback, TO CHANGE LATER
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            
            // add to log some event
            gameLog.innerHTML += `<p class="text-warning">> ${data.event}</p>`;
            gameLog.scrollTop = gameLog.scrollHeight;

            refreshRoomContext();
            updateMapUI();
        } 
        catch (error) {
            console.error("Status check failed", error);
        }
        finally {
            pingBtn.innerText = "Check Simulation Status";
        }
    });

   // Fetch and update room context (movement options and tasks available)
   async function refreshRoomContext() {
        const response = await fetch('/api/room-context');
        const data = await response.json();

        // Update Location
        document.getElementById('location-display').innerText = data.current_room;

        // Update the Clock
        document.getElementById('step-counter').innerText = data.timestep;

        // Update and render tasks - "What can I do here now?"
        const taskContainer = document.getElementById('task-list');    
        taskContainer.innerHTML = '';
        data.tasks.forEach(taskName => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-outline-success btn-sm text-start m-1';
            btn.innerText = taskName;
            btn.onclick = () => completeTask(taskName);
            taskContainer.appendChild(btn);
        });

        // Update movement options - "Where can I go to now?"
        const moveContainer = document.getElementById('movement-options');
        moveContainer.innerHTML = '';
        data.adjacent.forEach(room => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-outline-info btn-sm m-1';
            btn.innerText = room;
            btn.onclick = () => performMove(room);
            moveContainer.appendChild(btn);
        });


        // Render Current Players in your Room
        const playersInRoomList = document.getElementById('players-in-room-list');
        if (playersInRoomList){
            playersInRoomList.innerHTML= ''; // clear old list
            if (data.players_in_room.length === 0){
                playersInRoomList.innerHTML = '<li class="list-group-item bg-dark text-muted small"> You are alone here. </li>';
            }
            else{
                data.players_in_room.forEach(player => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item bg-dark border-secondary d-flex align-items-center';
                    if (player.is_alive){
                        li.innerHTML = `<img src="/static/assets/player_${player.color}.png" title="${player.name}" style="width: 35px; height: 35px;">`;
                    }
                    else{
                    // dead
                    li.classList.add('text-muted');
                        li.innerHTML = `<img src="/static/assets/player_${player.color}.png" title="${player.name} (Dead)" style="width: 35px; height: 35px; opacity: 0.5; transform: rotate(90deg);"> <span class="ms-2 small">(Dead)</span>`;
                    }
                    playersInRoomList.appendChild(li);
                });
            }
        }
    }

    // Handles movement
    async function performMove(destination) {
        const response = await fetch('/api/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination: destination })
        });

        if (response.ok) {
            // Refresh the buttons for the new room
            refreshRoomContext();

            const data = await response.json();
            
            // Update the log
            const log = document.getElementById('game-log');
            log.innerHTML += `<p class="text-info">> [Step ${data.timestep}] Moved to ${destination}</p>`;
            log.scrollTop = log.scrollHeight;

            await refreshRoomContext();
        }
    }

    // Handles completing the task
    async function completeTask(taskName) {
        const response = await fetch('/api/do-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: taskName })
        });

        if (response.ok) {
            const data = await response.json();
            
            // Update the log
            const log = document.getElementById('game-log');
            log.innerHTML += `<p class="text-success">> [Step ${data.timestep}] ${data.message}</p>`;
            
            // Update the counter on screen
            document.getElementById('step-counter').innerText = data.timestep;
            
            log.scrollTop = log.scrollHeight;

            await refreshRoomContext();
        }
    }

    // Fetch map state and overlay charcter png onto skeld map
    async function updateMapUI() {
        try {
            const response = await fetch('/api/map-state');
            const data = await response.json();
            
            if (data.error) return; 

            const playerLayer = document.getElementById('player-layer');

            // Reset the board
            playerLayer.innerHTML = '';

            data.players.forEach(player => {
                // Adjusted for casing
                const safeLocation = player.location.toLowerCase().trim();
                const coords = roomCoordinates[safeLocation];
                
                // Slightly displace pngs randomly everytime so we can see overlap
                if (coords) {
                    const jitterX = (Math.random() * 10) - 5;
                    const jitterY = (Math.random() * 10) - 5;

                    const img = document.createElement('img');
                    img.src = `/static/assets/player_${player.color}.png`;
                    
                    img.style.position = 'absolute';
                    img.style.top = `${coords.top + jitterY}%`;
                    img.style.left = `${coords.left + jitterX}%`;
                    img.style.transform = 'translate(-50%, -50%)';
                    img.style.width = '35px';
                    img.style.zIndex = '10';
                    
                    // Text hover
                    img.title = `${player.name} (${player.location})`;

                    playerLayer.appendChild(img);
                }
                else {
                    console.warn(`Failed to get map coordinates: ${player.location}`);
                }
            });
        }
        catch (error) {
            console.error("Failed to update map:", error);
        }
    }

    // Checks if everyone is ready, and if so, starts the actual game
    async function checkAllReady() {
        if (readyPlayers === totalPlayers && isHumanReady) {

            // Tell backend to switch to "active"
            const response = await fetch('/api/ready', { method: 'POST' });

            if (response.ok) {
                // UI Transition
                stagingPanel.classList.add('d-none'); // Hide checklist
                actionPanel.classList.remove('d-none'); // Reveal Tasks and Movement
                document.getElementById('current-phase').innerText = "Active";
                document.getElementById('current-phase').className = "text-success fw-bold";

                const log = document.getElementById('game-log');
                log.innerHTML += `<p class="text-warning">> All players ready. Game has started.</p>`;
                log.scrollTop = log.scrollHeight;

                refreshRoomContext(); // Load initial tasks and moves
            }
        }
    }
});