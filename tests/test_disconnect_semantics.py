from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from amongagents.envs.game import AmongUs


def test_disconnected_player_is_removed_from_active_game_counts():
    game = AmongUs(
        game_config=FIVE_MEMBER_GAME,
        agent_config={
            "Impostor": "LLM",
            "Crewmate": "LLM",
            "IMPOSTOR_LLM_CHOICES": ["gemini/test-model"],
            "CREWMATE_LLM_CHOICES": ["gemini/test-model"],
        },
    )
    game.initialize_game()

    disconnected = next(player for player in game.players if player.identity == "Crewmate")
    disconnected.is_connected = False
    disconnected.available_actions = ["stale"]
    game.update_map()
    game.check_actions()

    for room in game.map.ship_map:
        assert disconnected not in game.map.get_players_in_room(room, include_new_deaths=True)

    assert disconnected.get_available_actions() == []
    assert disconnected.available_actions == []

    assigned_to_disconnected = [
        task
        for task in game.task_assignment.assigned_tasks
        if getattr(task, "assigned_player", None) is disconnected
    ]
    for task in game.task_assignment.assigned_tasks:
        if getattr(task, "assigned_player", None) is not disconnected:
            task.duration = 0

    assert assigned_to_disconnected
    assert game.task_assignment.check_task_completion() == 1.0
