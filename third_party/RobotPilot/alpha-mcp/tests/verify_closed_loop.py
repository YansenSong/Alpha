"""Real MCP -> real HTTP API -> real MissionManager, in an isolated synthetic-feedback fixture."""
import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from fastmcp import Client
import httpx
from alpha_mcp.platform import Journal, Platform
from alpha_mcp.server import build_server
ROOT=Path(__file__).resolve().parents[4]

async def main():
    process=subprocess.Popen(["bash",str(ROOT/"scripts/verify_alpha_ros_fixture.sh")],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    try:
        # bounded wait: fixture readiness cannot hang a verification run indefinitely.
        import select
        if not select.select([process.stdout],[],[],15)[0]: raise RuntimeError("ROS fixture did not start")
        line=process.stdout.readline().strip()
        if not line.startswith("ALPHA_FIXTURE_PORT="): raise RuntimeError("Unexpected ROS fixture startup output")
        port=int(line.split("=",1)[1]);url=f"http://127.0.0.1:{port}"
        os.environ["ALPHA_ALLOW_MOTION"]="simulation"
        with tempfile.TemporaryDirectory() as directory:
            adapter=Platform(base_url=url,journal=Journal(directory+"/ops.sqlite3"))
            async with Client(build_server(adapter)) as client:
                locations=(await client.call_tool("list_navigation_locations",{})).data
                assert locations["locations"][0]["name"]=="Home"
                request={"location":"Home","idempotency_key":"closed-loop-navigation-1"}
                accepted=(await client.call_tool("navigate_to_location",request)).data
                assert accepted["status"]=="accepted" and not accepted["completed"],accepted
                await client.call_tool("navigate_to_location",request)
                async with httpx.AsyncClient(base_url=url,trust_env=False) as transport:
                    wrong=(await transport.post("/fixture/arrival/wrong")).json()
                    assert wrong["status"]=="RUNNING" and wrong["goals_sent"]==1,wrong
                    pending=(await client.call_tool("get_task_status",{"operation_id":request["idempotency_key"]})).data
                    assert not pending["completed"]
                    correct=(await transport.post("/fixture/arrival/correct")).json()
                    assert correct["status"]=="SUCCEEDED" and correct["goals_sent"]==1,correct
                completed=(await client.call_tool("get_task_status",{"operation_id":request["idempotency_key"]})).data
                assert completed["completed"] and completed["verified"],completed
                assert completed["task_id"]==accepted["task_id"]
                assert completed["evidence"][0]["execution_id"]
                print("PASS MCP → Platform API → MissionManager → verified arrival; wrong position and duplicate submission rejected")
            await adapter.client.aclose();adapter.journal.db.close()
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait()

if __name__=="__main__":asyncio.run(main())
