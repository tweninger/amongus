// state.js
export const state = {
    processedMessageCount: 0,
    gameStarted: false,
    playerToken: null, // The session ID for the server to identify
    myColor: null,
    ws: null, // Holds live websocket connection
    myRole: null,

    actionPanel: null,
    sendChatBtn: null,
    chatInput: null,
    chatInputLocked: false,

    isAlive: true,
    deathModalShown: false,
    lastPhase: "active",
    actionLocked: false, // Global Lock for human actions
    moveCooldownUntil: 0,
    moveCooldownTimer: null,
    activeTask: null, // { name, location, deadline, completing } while a timed task is running
    taskCountdownTimer: null,
    lastTimestep: 0, // Most recent action sequence number received from the server
    lastDiscussionTurnSeq: -1, // Server-issued counter. Increments each time the discussion passes to a new human in meetings
    processedGameEventIds: new Set(), // Server-issued event ids already shown in the game log
    meetingCountdownTimer: null,
    lobbyCountdownTimer: null,
};
