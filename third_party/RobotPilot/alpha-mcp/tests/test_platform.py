import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import httpx
from alpha_mcp.platform import Platform, Journal
from alpha_mcp.readonly_bridge import allowed

class PlatformTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.journal = Journal(self.directory.name + "/journal.sqlite3")
        self.posts = []
        self.task_status = "running"
        self.evidence = []
        self.interrupt_start = False
        self.status = {"autonomy_ready": True, "task_stale": False, "current_map": {"map_id": "map1", "map_version_id": "v1", "stale": False}}
        self.target = {"x": 1.0, "y": 2.0, "z": 0.0, "w": 1.0}
        async def transport(request):
            p = request.url.path
            if request.method == "POST":
                self.posts.append(p)
                if p.endswith("/missions"): return httpx.Response(202, json={"status":"accepted"})
                if self.interrupt_start: raise httpx.ReadTimeout("lost acknowledgement")
                return httpx.Response(202, json={"status":"accepted", "task_id":"task1", "command_id":"command1"})
            if p == "/api/auth/status": return httpx.Response(200, json={"robot_id":"robot-001", "mode":"open", "isLocalNetwork":True, "robot_mode":"simulation"})
            if p.endswith("/status"): return httpx.Response(200,json=self.status)
            if p.endswith("/waypoints"): return httpx.Response(200,json={"waypoints":[{"waypoint_id":"wp1", "name":"Home", "enabled":True,"map_version_id":"v1", "x":1.,"y":2.,"yaw":0.}]})
            if p.endswith("/tasks"): return httpx.Response(200,json={"current":None,"history":[]})
            return httpx.Response(200,json={"task_id":"task1","mission_id":"mission1","status":self.task_status,"attempt":1,"map_id":"map1", "map_version_id":"v1","steps":[{"type":"waypoint","pose":self.target}],"navigation_evidence":self.evidence})
        self.client = httpx.AsyncClient(base_url="http://127.0.0.1:5050", transport=httpx.MockTransport(transport))
        self.adapter = Platform(journal=self.journal, client=self.client)
        self.env = patch.dict(os.environ, {"ALPHA_ALLOW_MOTION":"simulation"}); self.env.start()
    async def asyncTearDown(self):
        await self.client.aclose(); self.journal.db.close(); self.env.stop(); self.directory.cleanup()
    async def test_duplicate_and_concurrent_navigation_only_start_once(self):
        first, second = await asyncio.gather(self.adapter.navigate_to_location("Home","navigate-key-1"),self.adapter.navigate_to_location("Home","navigate-key-1"))
        self.assertFalse(first["completed"])
        self.assertEqual(sum(p.endswith("/tasks") for p in self.posts),1)
        await self.adapter.navigate_to_location("Home","navigate-key-1")
        self.assertEqual(len(self.posts),2)
        with self.assertRaises(ValueError): await self.adapter.navigate_to_location("Other","navigate-key-1")
    async def test_restart_preserves_idempotency(self):
        await self.adapter.navigate_to_location("Home", "restart-key-1")
        reopened = Journal(self.directory.name + "/journal.sqlite3")
        try:
            adapter = Platform(journal=reopened, client=self.client)
            await adapter.navigate_to_location("Home", "restart-key-1")
            self.assertEqual(len(self.posts), 2)
        finally:
            reopened.db.close()
    async def test_disconnect_during_reconciliation_is_unknown(self):
        self.journal.reserve("disconnect-key-1", {"type": "navigate"})
        self.journal.save("disconnect-key-1", {"mission_id": "mission1"})
        async def disconnected(*args, **kwargs):
            raise httpx.ConnectError("unavailable")
        self.adapter.request = disconnected
        result = await self.adapter.get_task_status(operation_id="disconnect-key-1")
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["completed"])
    async def test_timeout_remains_unknown_without_repeating_motion(self):
        self.interrupt_start = True
        result = await self.adapter.navigate_to_location("Home","unknown-key-1")
        self.assertEqual(result["status"],"unknown")
        await self.adapter.navigate_to_location("Home","unknown-key-1")
        self.assertEqual(len(self.posts),2)
    async def test_transport_success_or_succeeded_without_evidence_is_not_completion(self):
        result = await self.adapter.navigate_to_location("Home","evidence-key-1")
        self.assertEqual(result["status"],"accepted");self.assertFalse(result["completed"])
        self.task_status="SUCCEEDED"
        self.assertFalse((await self.adapter.get_task_status("task1"))["completed"])
        self.evidence=[{"task_id":"old-task","step_index":0,"attempt":1,"map_id":"map1","target":self.target,"verified":True}]
        self.assertFalse((await self.adapter.get_task_status("task1"))["completed"])
        self.evidence[0].update(task_id="task1",source="nav_status",map_version_id="v1")
        self.assertTrue((await self.adapter.get_task_status("task1"))["completed"])
        self.task_status="CANCELLED"
        self.assertFalse((await self.adapter.get_task_status("task1"))["completed"])
    async def test_stale_state_and_low_battery_cannot_authorize_motion(self):
        self.status.update(autonomy_ready=False,readiness_blockers=["battery low"])
        result=await self.adapter.navigate_to_location("Home","blocked-key-1")
        self.assertEqual(result["status"],"rejected");self.assertEqual(self.posts,[])
        with patch.dict(os.environ,{"ALPHA_ALLOW_MOTION":""}):
            with self.assertRaises(PermissionError): await self.adapter.navigate_to_location("Home","blocked-key-2")
    async def test_stop_requires_matching_feedback_and_never_claims_physical_stationarity(self):
        calls=[]
        async def send(request_id): calls.append(request_id);return {"request_id":"old-request", "active":True,"result":"confirmed","durable":True}
        self.adapter.stop_sender=send
        result=await self.adapter.request_software_stop("stop-key-123")
        self.assertEqual(result["status"],"unknown");self.assertFalse(result["completed"]);self.assertFalse(result["stationary_verified"])
        await self.adapter.request_software_stop("stop-key-123")
        self.assertEqual(len(calls),1)
    def test_inspect_transport_rejects_all_write_families(self):
        for op in ["publish","advertise","send_action_goal","call_service"]:
            self.assertFalse(allowed({"op":op,"topic":"/cmd_vel","service":"/anything/set_parameters"}))
        self.assertTrue(allowed({"op":"call_service","service":"/rosapi/topics"}))
        self.assertFalse(allowed({"op":"subscribe","topic":"/points_raw"}))

if __name__ == "__main__": unittest.main()
