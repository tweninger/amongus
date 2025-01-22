from langchain.output_parsers import PydanticOutputParser
from langchain.tools import BaseTool
import networkx as nx
from typing import Optional, Type
from pydantic import BaseModel, Field, field_validator


class PathSearchInput(BaseModel):
    from_location: str = Field(description="The location to start from")
    to_location: str = Field(description="The location to go to")
    identity: str = Field(description="The identity of the player: Crewmate or Impostor")


class GetBestPath(BaseTool):
    name: str = "GetBestPath"  # Add a type annotation
    description: str = "Get the quickest path to a location"  # Add a type annotation
    args_schema: Type[BaseModel] = PathSearchInput

    def _run(self, from_location: str, to_location: str, identity: str) -> str:
        """Get the quickest path to a location."""
        print(f'OKAY THIS FUNCTION GET BEST PATH IS CALLED WOW', flush=True)
        if identity == "Impostor":
            path = nx.shortest_path(self.metadata["network"], from_location, to_location)
        else:
            path = nx.shortest_path(self.metadata["network"], from_location, to_location, weight='weight')
        path = "->".join(path)
        instruction = (
            "Now, write your response with [Condensed Memory], [Thinking Process], and [Action]. "
            "Make sure action is chosen from the available actions. Case sensitive."
        )
        return f"{path}\n{instruction}"

    async def _arun(self, from_location: str, to_location: str, identity: str) -> str:
        raise NotImplementedError("This tool does not support async execution")


class AgentResponse(BaseModel):
    condensed_memory: str = Field(description="The condensed memory of the agent: a summarization of the past observed events and taken actions.")
    thinking_process: str = Field(description="A thoughtful and thorough plan of action based on the current state of the game.")
    action: str = Field(description="The action to take from the available actions.")

    @field_validator("action")
    def action_must_be_valid(cls, value):
        valid_actions = [
            "VOTE", "MOVE", "SPEAK", "CALL MEETING", "KILL", "VENT",
            "REPORT DEAD BODY", "VIEW MONITOR", "COMPLETE TASK", "COMPLETE FAKE TASK"
        ]
        if value not in valid_actions:
            raise ValueError("Invalid action")
        return value


AgentResponseOutputParser = PydanticOutputParser(pydantic_object=AgentResponse)