// state.js
export const state = {
    processedMessageCount: 0,
    gameStarted: false,
    playerToken: null, // The session ID for the server to identify
    myColor: null,
    ws: null, // Holds live websocket connection
    myRole: null,

    actionPanel: null,
    phaseDisplay: null,
    sendChatBtn: null,
    chatInput: null,
    chatInputLocked: false,

    isAlive: true,
    lastPhase: "active",
    actionLocked: false, // Global Lock for human actions
    waitingForStep: false, // True when this current client submitted an action but other players haven't yet
    lastTimestep: 0, // Used to detect when a new step is run
    lastDiscussionTurnSeq: -1, // Server-issued counter. Increments each time the discussion passes to a new human in meetings
    pendingActionLog: null, // Stores { message, type, observations, ventObservations } while waiting for step
    meetingCountdownTimer: null,
};
