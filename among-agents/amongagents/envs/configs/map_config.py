room_data = {
    "Cafeteria": {
        "tasks": ["Download Data", "Empty Garbage", "Fix Wiring", "Clean Vent"],
        "vent": ["Admin"],
        "special_actions": ["Emergency Button"],
        "players": [],
    },
    "Weapons": {
        "tasks": ["Clear Asteroids", "Download Data", "Clean Vent", "Divert Power"],
        "vent": ["Navigation"],
        "special_actions": [],
        "players": [],
    },
    "Navigation": {
        "tasks": [
            "Chart Course",
            "Download Data",
            "Fix Wiring",
            "Stabilize Steering", 
            "Clean Vent",
            "Divert Power",
        ],
        "vent": ["Shields", "Weapons"],
        "special_actions": [],
        "players": [],
    },
    "O2": {
        "tasks": ["Clean O2 Filter", "Empty Chute", "Divert Power"],
        "vent": [],
        "special_actions": ["Oxygen Depleted"],
        "players": [],
    },
    "Shields": {
        "tasks": ["Prime Shields", "Clean Vent", "Divert Power"],
        "vent": ["Navigation"],
        "special_actions": [],
        "players": [],
    },
    "Communications": {
        "tasks": ["Download Data", "Divert Power"],
        "vent": [],
        "special_actions": ["Comms Sabotaged"],
        "players": [],
    },
    "Storage": {
        "tasks": ["Empty Garbage", "Empty Chute", "Fix Wiring", "Fuel Engines"],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
    "Admin": {
        "tasks": ["Fix Wiring", "Swipe Card", "Upload Data", "Clean Vent"],
        "vent": ["Cafeteria"],
        "special_actions": ["Admin Map"],
        "players": [],
    },
    "Electrical": {
        "tasks": [
            "Calibrate Distributor",
            "Divert Power",
            "Download Data",
            "Fix Wiring",
            "Clean Vent",
        ],
        "vent": ["Medbay", "Security"],
        "special_actions": ["Fix Lights"],
        "players": [],
    },
    "Lower Engine": {
        "tasks": ["Align Engine Output", "Fuel Engines", "Clean Vent", "Divert Power"],
        "vent": ["Reactor"],
        "special_actions": [],
        "players": [],
    },
    "Security": {
        "tasks": ["Fix Wiring", "Clean Vent", "Divert Power"],
        "vent": [],
        "special_actions": ["Security Cameras"],
        "players": [],
    },
    "Reactor": {
        "tasks": ["Start Reactor", "Unlock Manifolds", "Clean Vent"],
        "vent": ["Upper Engine", "Lower Engine"],
        "special_actions": ["Reactor Meltdown"],
        "players": [],
    },
    "Upper Engine": {
        "tasks": ["Align Engine Output", "Fuel Engines", "Clean Vent", "Divert Power"],
        "vent": ["Reactor"],
        "special_actions": [],
        "players": [],
    },
    "Medbay": {
        "tasks": ["Inspect Sample", "Submit Scan", "Clean Vent"],
        "vent": ["Electrical", "Security"],
        "special_actions": ["Medbay Scan"],
        "players": [],
    },
    "Hallway 1": {
        "tasks": [],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
    "Hallway 2": {
        "tasks": [],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
    "Hallway 3": {
        "tasks": [],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
    "Hallway 4": {
        "tasks": [],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
    "Hallway 5": {
        "tasks": [],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
    "Hallway 6": {
        "tasks": [],
        "vent": [],
        "special_actions": [],
        "players": [],
    },
}

# Since we're defining a simple undirected graph, we don't need to specify directions for connections.
# Defining the connections (edges) between rooms manually as per the images.
vent_connections = [
    ("Reactor", "Lower Engine"),
    ("Upper Engine", "Reactor"),
    ("Upper Engine", "Lower Engine"),
    ("Electrical", "Security"),
    ("Electrical", "Medbay"),
    ("Navigation", "Shields"),
    ("Medbay", "Security"),
    ("Weapons", "Shields"),
    ("Navigation", "Weapons"),
    ("Admin", "Cafeteria"),
]

connections = [
    ("Cafeteria", "Weapons"),
    ("Cafeteria", "Hallway 1"),
    ("Upper Engine", "Hallway 1"),
    ("Medbay", "Hallway 1"),
    ("Upper Engine", "Hallway 2"),
    ("Reactor", "Hallway 2"),
    ("Security", "Hallway 2"),
    ("Lower Engine", "Hallway 2"),
    ("Lower Engine", "Hallway 3"),
    ("Electrical", "Hallway 3"),
    ("Storage", "Hallway 3"),
    ("Cafeteria", "Hallway 4"),
    ("Admin", "Hallway 4"),
    ("Storage", "Hallway 4"),
    ("Storage", "Hallway 5"),
    ("Communications", "Hallway 5"),
    ("Shields", "Hallway 5"),
    ("Weapons", "Hallway 6"),
    ("O2", "Hallway 6"),
    ("Navigation", "Hallway 6"),
    ("Shields", "Hallway 6"),
]

map_coords = {
    "Cafeteria": {
        "coords": (
            432,
            1,
            716,
            1,
            716,
            253,
            432,
            253,
        ),
    },
    "Weapons": {
        "coords": (703, 48, 835, 48, 835, 180, 703, 180),
    },
    "Navigation": {
        "coords": (892, 188, 995, 188, 995, 297, 892, 297),
    },
    "O2": {
        "coords": (660, 177, 754, 177, 754, 261, 660, 261),
    },
    "Shields": {
        "coords": (711, 345, 832, 345, 832, 463, 711, 463),
    },
    "Communications": {
        "coords": (605, 424, 724, 424, 724, 517, 605, 517),
    },
    "Storage": {
        "coords": (462, 319, 614, 319, 614, 519, 462, 519),
    },
    "Admin": {
        "coords": (615, 260, 736, 260, 736, 369, 615, 369),
    },
    "Electrical": {
        "coords": (357, 283, 479, 283, 479, 442, 357, 442),
    },
    "Lower Engine": {
        "coords": (165, 323, 281, 323, 281, 446, 165, 446),
    },
    "Security": {
        "coords": (267, 182, 337, 182, 337, 307, 267, 307),
    },
    "Reactor": {
        "coords": (70, 163, 189, 163, 189, 340, 70, 340),
    },
    "Upper Engine": {
        "coords": (163, 59, 278, 59, 278, 192, 163, 192),
    },
    "Medbay": {
        "coords": (340, 145, 480, 145, 480, 274, 340, 274),
    },
    "Hallway 1": {
        "coords": (260, 87, 455, 87, 455, 169, 260, 169),
    },
    "Hallway 2": {
        "coords": (173, 171, 281, 171, 281, 342, 173, 342),
    },
    "Hallway 3": {
        "coords": (264, 361, 480, 361, 480, 473, 264, 473),
    },
    "Hallway 4": {
        "coords": (545, 235, 631, 235, 631, 341, 545, 341),
    },
    "Hallway 5": {
        "coords": (594, 368, 733, 368, 733, 441, 594, 441),
    },
    "Hallway 6": {
        "coords": (733, 160, 907, 160, 907, 372, 733, 372),
    },
}
