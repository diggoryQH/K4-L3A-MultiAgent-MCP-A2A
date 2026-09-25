import asyncio
import json
import sys
import os

sys.path.append("src")
from student_agent.mcp_gateway import EvidenceGateway

async def main():
    g = EvidenceGateway()
    await g.connect()
    
    r1 = await g.call_tool('get_order_items', {'case_id':'L3A_CASE_098'})
    r2 = await g.call_tool('get_order_payments', {'case_id':'L3A_CASE_098'})
    
    print("Items:", r1.content[0].text)
    print("Payments:", r2.content[0].text)
    
    await g.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
