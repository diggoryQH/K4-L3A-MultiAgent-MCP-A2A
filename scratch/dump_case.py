import asyncio
from pathlib import Path
import os
import json
from dotenv import load_dotenv
from src.student_agent.mcp_gateway import connect_gateway
from src.student_agent.contracts import Contracts

async def main():
    load_dotenv()
    contracts_root = Path(os.getcwd()) / "contracts" / "schemas"
    async with connect_gateway(
        os.getenv('MCP_ENDPOINT'),
        os.getenv('COMPETITION_TEAM_API_KEY'),
        Contracts(contracts_root)
    ) as g:
        case_id = "L3A_CASE_097"
        
        order = await g.call("get_order", case_id=case_id, order_id="2cfc79d9582e9135c0a9b61fa60e6b21")
        print("ORDER:", json.dumps(order, indent=2))
        items = await g.call("get_order_items", case_id=case_id, order_id="2cfc79d9582e9135c0a9b61fa60e6b21")
        print("ITEMS:", json.dumps(items, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
