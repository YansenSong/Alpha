import asyncio
import time
from fastmcp import FastMCP
from .platform import Platform

def build_server(platform=None):
    adapter = platform or Platform()
    mcp = FastMCP("Alpha robot business tools", instructions="MissionManager is authoritative. accepted is not completed. UNKNOWN must be reconciled, never automatically resubmitted. Stop and cancel do not prove stationary motion.")
    @mcp.tool(description="Read real robot readiness, localization, navigation and software stop state.")
    async def get_robot_status() -> dict:
        return await adapter.get_robot_status()
    @mcp.tool(description="List enabled named inspection points on the current map. Never invent Home or assume it is the origin.")
    async def list_navigation_locations() -> dict:
        return await adapter.list_navigation_locations()
    @mcp.tool(description="Submit one navigation mission to an existing named point. Required stable idempotency_key must be reused for retries. accepted is NOT arrival.")
    async def navigate_to_location(location: str, idempotency_key: str) -> dict:
        return await adapter.navigate_to_location(location, idempotency_key)
    @mcp.tool(description="Query authoritative task state/evidence by task_id or operation_id. completed is true only with verified navigation evidence.")
    async def get_task_status(task_id: str | None = None, operation_id: str | None = None, wait_seconds: float = 0) -> dict:
        if not task_id and not operation_id: raise ValueError("task_id or operation_id required")
        if not 0 <= wait_seconds <= 15: raise ValueError("wait_seconds must be 0–15")
        deadline = time.monotonic() + wait_seconds
        while True:
            result = await adapter.get_task_status(task_id, operation_id)
            if result.get("status") not in {"running", "accepted", "pending"} or time.monotonic() >= deadline:
                return result
            await asyncio.sleep(min(1, deadline - time.monotonic()))
    @mcp.tool(description="Request software stop and await correlated latch feedback. Does not release stop and is not a physical E-STOP.")
    async def request_software_stop(idempotency_key: str) -> dict:
        return await adapter.request_software_stop(idempotency_key)
    @mcp.tool(description="Request cancellation of an explicit task_id. Then query task status. Cancellation is not proof of stationary motion.")
    async def cancel_navigation(task_id: str, idempotency_key: str) -> dict:
        return await adapter.cancel_navigation(task_id, idempotency_key)
    return mcp

def main(): build_server().run(transport="stdio", show_banner=False)
if __name__ == "__main__": main()
