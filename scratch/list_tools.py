import asyncio
from pathlib import Path
import os
from dotenv import load_dotenv
from src.student_agent.mcp_gateway import connect_gateway
from src.student_agent.contracts import Contracts

async def main():
    load_dotenv()
    async with connect_gateway(
        os.getenv('MCP_ENDPOINT'),
        os.getenv('COMPETITION_TEAM_API_KEY'),
        Contracts(Path('contracts'))
    ) as g:
        response = await g._session.list_tools()
        for tool in response.tools:
            print(f"{tool.name}: {tool.input_schema}")

if __name__ == "__main__":
    asyncio.run(main())
