// For map rendering
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
    const playerNameInput = document.getElementById('player-name');
    const lobbyScreen = document.getElementById('lobby-screen');
    const gameScreen = document.getElementById('game-screen');
    const gameLog = document.getElementById('game-log');
    const userDisplay = document.getElementById('user-display');
    const phaseDisplay = document.getElementById('current-phase');
    const pingBtn = document.getElementById('ping-btn')
    const aiCount = document.getElementById('ai-count-display');
    const humanToggle = document.getElementById('human-toggle')

    // Constructs game size selector buttons

    // Put all #count-selectors in a list
    const sizeButtons = document.querySelectorAll('#count-selector .btn');
    

    const updatePlayerCountDisplay = () => {
        // Current num players clicked
        const activeBtn = document.querySelector('#count-selector .btn.active')

        const totalCount = parseInt(activeBtn.innerText);

        if (humanToggle.checked){
            const aiPlayerCount = totalCount - 1;
            aiCount.innerText = `Current Setup: 1 Human, ${aiPlayerCount} AI Players`;
        }
        else{
            aiCount.innerText = `Current Setup: ${totalCount} AI Players`;
        }
    };

    // Listens for toggle or player count selector
    humanToggle.addEventListener('change', updatePlayerCountDisplay);

    // Update when a size button is clicked
    sizeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            sizeButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updatePlayerCountDisplay();
        });
    });

    // Start Button Logic
    startBtn.addEventListener('click', async () => {
        const name = playerNameInput.value.trim();
        if (!name) return alert("Please enter a name.");
        
        try {
            const response = await fetch('/api/join', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });

            if (response.ok) {
                const data = await response.json();
                
                // Update text on screen
                if (userDisplay) userDisplay.innerText = data.player_name;
                if (phaseDisplay) phaseDisplay.innerText = "Lobby Ready";

                // Switch screens
                if (lobbyScreen) lobbyScreen.classList.add('d-none');
                if (gameScreen) gameScreen.classList.remove('d-none');

                refreshRoomContext();

                if (gameLog) gameLog.innerHTML += `<p class="text-success">> Player ${data.player_name} authenticated.</p>`;
            }
        } catch (error) {
            console.error("Failed to start:", error);
        }
    });

    // Handles the "Check Simulation Status Button"
     pingBtn.addEventListener('click', async () => {
        pingBtn.innerText = "AIs are thinking..."; // Visual feedback
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
        // Fetch the room context
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
            
            // Update the log so the researcher can see the move
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
                    const jitterX = (Math.random() * 4) - 3;
                    const jitterY = (Math.random() * 4) - 3;

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
});