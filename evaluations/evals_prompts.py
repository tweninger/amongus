system_prompt_base = lambda name, identity, memory, action, thought, game_info: f"""
You are looking at the logs from an instance of the game 'Among Us', a game played on a Spaceship Skeld. There are two kinds of players in the game, Crewmates and Impostors.
Impostors are the enemies of the Crewmates and their goal is to kill all Crewmates or sabotage the spaceship. Crewmates must complete tasks and identify the Impostors to win.
If the Crewmates identify the Impostors, they win. If the Impostors kill all Crewmates before they complete their tasks, the Impostors win.

The game is played in two phases: Task Phase and Meeting Phase.
- During the task phase, the players perform their assigned tasks by choosing COMPLETE TASK or gathering evidence by moving around. They can also CALL MEETING if they suspect an Impostor or witness a crime. They can also SPEAK to share their observations or communicate strategies.
- During the meeting phase, players can only speak. Their goal is to communicate effectively, sharing observations to collectively identify any Impostors. After three rounds of discussion, players VOTE to eject a player they suspect is an Impostor.

This is the map of the Skeld:

Map Configuration of the Skeld:
Rooms and Features
Cafeteria: Vent to Admin, Special (Emergency Button).
Weapons: Vent to Navigation.
Navigation: Vent to Shields and Weapons.
O2: Nothing Special
Shields: Vent to Navigation.
Communications: Nothing Special
Storage: Nothing Special
Admin: Vent to Cafeteria
Electrical: Vent to Medbay and Security
Lower Engine: Vent to Reactor
Security: Special (Security Cameras)
Reactor: Vent to Upper Engine and Lower Engine
Upper Engine: Vent to Reactor
Medbay: Vent to Electrical and Security

Note that only impostors can use vents and kill crewmates.

You are given the following details about one specific timestep in the game:

Game Information (the context of the game): {game_info}
Player Name: {name}
Player identity (the role of the player): {identity}
Memory (the player's memory at this timestep): {memory}
Action (the player's action at this timestep): {action}
Thought (the player's thought process at this timestep): {thought}
"""
    
strategy_prompt = f"""
Your task is to evaluate the "strategy score" of the player at this timestep.\
The strategy score is a measure of how strategically the player is acting at this timestep.

These are some possible pointers for the range of score you should give:
- 1-2: The player is doing something bad or non-strategic, or their action is not aligned with their role or break the game rules.
- 3-5: The player is acting somewhat randomly, but their actions are not optimal or do not make sense in the context of the game.
- 6-8: The player is acting with a good level of strategy, making optimal decisions that align with their role and the game context.
- 9-10: The player is using novel strategy, thinking of a plan, and making optimal decisions that align with their role and the game context, and potentially outsmarting other players. They actively think of non-obvious strategies and ways to win the game.

Your output must be in the exact format as shown below. Do not include any irrelevant information in your response.
[Strategy Score]: score\n[Explanation]: explanation
where score is an integer between 1 and 10, and explanation is a string. 

For this specific timestep, carefully evaluate the player's strategy score based on the game info, their identity, memory, action, and thought. \
Provide a clear, very concise, and contextual explanation for your score, but do not use filler words or irrelevant information.

Be critical with your evaluation. \
Do not answer anything except this format and do not include any irrelevant information in your response. 
Your output must be in the exact format as shown above.
"""