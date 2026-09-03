from amongagents.agent.neutral_prompts import (
    CREWMATE_PROMPT,
    IMPOSTOR_PROMPT,
    MEETING_PHASE_INSTRUCTION,
    TASK_PHASE_INSTRUCTION,
)


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
