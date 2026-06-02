// config.js

export const roomCoordinates = {
    "cafeteria": { top: 22.8, left: 57.4 },
    "weapons": { top: 20.4, left: 76.9 },
    "navigation": { top: 43.3, left: 94.4 },
    "o2": { top: 39.1, left: 70.7 },
    "shields": { top: 72.1, left: 77.2 },
    "communication": { top: 84.9, left: 66.5 },
    "communications": { top: 84.9, left: 66.5 },
    "admin": { top: 56.2, left: 67.6 },
    "storage": { top: 74.8, left: 53.8 },
    "electrical": { top: 64.7, left: 41.8 },
    "lower engine": { top: 68.7, left: 22.3 },
    "reactor": { top: 44.9, left: 13.0 },
    "security": { top: 43.7, left: 30.2 },
    "upper engine": { top: 22.4, left: 22.1 },
    "medbay": { top: 37.4, left: 41.0 },
    "hallway 1": { top: 22.9, left: 35.8 },
    "hallway 2": { top: 45.8, left: 22.7 },
    "hallway 3": { top: 74.5, left: 37.2 },
    "hallway 4": { top: 51.4, left: 58.8 },
    "hallway 5": { top: 72.2, left: 66.4 },
    "hallway 6": { top: 47.5, left: 82.0 }
};

export const roomViewBounds = {
    "cafeteria": { x: 432, y: 1, width: 284, height: 252 },
    "weapons": { x: 703, y: 48, width: 132, height: 132 },
    "navigation": { x: 892, y: 188, width: 103, height: 109 },
    "o2": { x: 660, y: 177, width: 94, height: 84 },
    "shields": { x: 711, y: 345, width: 121, height: 118 },
    "communication": { x: 605, y: 424, width: 119, height: 93 },
    "communications": { x: 605, y: 424, width: 119, height: 93 },
    "storage": { x: 462, y: 319, width: 152, height: 200 },
    "admin": { x: 615, y: 260, width: 121, height: 109 },
    "electrical": { x: 357, y: 283, width: 122, height: 159 },
    "lower engine": { x: 165, y: 323, width: 116, height: 123 },
    "security": { x: 267, y: 182, width: 70, height: 125 },
    "reactor": { x: 70, y: 163, width: 119, height: 177 },
    "upper engine": { x: 163, y: 59, width: 115, height: 133 },
    "medbay": { x: 340, y: 145, width: 140, height: 129 },
    "hallway 1": { x: 260, y: 87, width: 195, height: 82 },
    "hallway 2": { x: 173, y: 171, width: 108, height: 171 },
    "hallway 3": { x: 264, y: 361, width: 216, height: 112 },
    "hallway 4": { x: 545, y: 235, width: 86, height: 106 },
    "hallway 5": { x: 594, y: 368, width: 139, height: 73 },
    "hallway 6": { x: 733, y: 160, width: 174, height: 212 }
};

export const movementEdgeCoordinates = {
    "Admin <-> Hallway 4": { x: 622, y: 295 },
    "Cafeteria <-> Hallway 1": { x: 441, y: 125 },
    "Cafeteria <-> Hallway 4": { x: 566, y: 246 },
    "Cafeteria <-> Weapons": { x: 709, y: 124 },
    "Communications <-> Hallway 5": { x: 689, y: 434 },
    "Electrical <-> Hallway 3": { x: 381, y: 435 },
    "Hallway 1 <-> Medbay": { x: 398, y: 163 },
    "Hallway 1 <-> Upper Engine": { x: 272, y: 128 },
    "Hallway 2 <-> Lower Engine": { x: 226, y: 332 },
    "Hallway 2 <-> Reactor": { x: 181, y: 259 },
    "Hallway 2 <-> Security": { x: 273, y: 260 },
    "Hallway 2 <-> Upper Engine": { x: 224, y: 184 },
    "Hallway 3 <-> Lower Engine": { x: 272, y: 392 },
    "Hallway 3 <-> Storage": { x: 468, y: 453 },
    "Hallway 4 <-> Storage": { x: 566, y: 334 },
    "Hallway 5 <-> Shields": { x: 721, y: 404 },
    "Hallway 5 <-> Storage": { x: 605, y: 404 },
    "Hallway 6 <-> Navigation": { x: 898, y: 247 },
    "Hallway 6 <-> O2": { x: 746, y: 219 },
    "Hallway 6 <-> Shields": { x: 780, y: 361 },
    "Hallway 6 <-> Weapons": { x: 780, y: 174 }
};

export const ventCoordinates = {
    "cafeteria": [{ x: 671, y: 153 }, { x: 780, y: 283 }],
    "weapons": [{ x: 766, y: 77 }],
    "navigation": [{ x: 916, y: 213 }, { x: 917, y: 280 }],
    "shields": [{ x: 780, y: 446 }],
    "admin": [{ x: 635, y: 357 }],
    "electrical": [{ x: 376, y: 314 }],
    "lower engine": [{ x: 259, y: 433 }],
    "medbay": [{ x: 357, y: 233 }],
    "security": [{ x: 318, y: 292 }],
    "reactor": [{ x: 123, y: 211 }, { x: 146, y: 292 }],
    "upper engine": [{ x: 259, y: 93 }]
};

export const PLAYER_COLORS = ["red", "blue", "green", "pink", "orange", "yellow", "black", "white", "purple", "brown", "cyan", "lime"];
