from amongagents.agent.neutral_prompts import (
    CREWMATE_PROMPT,
    IMPOSTOR_PROMPT,
    MEETING_PHASE_INSTRUCTION,
    TASK_PHASE_INSTRUCTION,
)
from amongagents.envs.action import MoveTo
from amongagents.envs.player import LLM_RECENT_ACTIONS, LLM_RECENT_OBSERVATIONS, Player


def test_active_prompts_describe_realtime_gameplay():
    active_prompt_text = "\n".join(
        [
            CREWMATE_PROMPT,
            IMPOSTOR_PROMPT,
            MEETING_PHASE_INSTRUCTION,
            TASK_PHASE_INSTRUCTION,
        ]
    ).lower()

    assert "real-time" in active_prompt_text
    assert "the game runs sequentially" not in active_prompt_text
    assert "3 discussion rounds" not in active_prompt_text
    assert "sabotaging critical systems" not in active_prompt_text


def test_meeting_prompt_allows_silence_in_free_chat():
    instruction = MEETING_PHASE_INSTRUCTION.lower()

    assert "free-chat" in instruction
    assert "choose silence" in instruction


def test_player_prompt_retains_extended_recent_histories():
    player = Player("Player 1", "Crewmate", "red", "", location="Cafeteria")
    player.observation_history = [
        f"observation-{index:02d}"
        for index in range(LLM_RECENT_OBSERVATIONS + 5)
    ]
    player.action_history = [
        {"timestep": index, "phase": "task", "action": MoveTo("Cafeteria", "Weapons")}
        for index in range(LLM_RECENT_ACTIONS + 2)
    ]

    observations = player.observation_history_prompt()
    actions = player.action_history_prompt()

    assert f"observation-{4:02d}" not in observations
    assert f"observation-{5:02d}" in observations
    assert "Event 1:" not in actions
    assert "Event 2:" in actions
