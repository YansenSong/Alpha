"""Isolated real MissionManager + real Flask API; navigation feedback is deliberately synthetic.
Never starts a simulator or talks to the user's ROS domain. All goal publications are captured.
"""
import json
import os
import tempfile
import time
import subprocess
from pathlib import Path
import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy
from flask import Flask, jsonify
from nav_msgs.msg import Odometry
from nav_status.msg import NavigationExecution, ControllerFeedback
from std_msgs.msg import String
from werkzeug.serving import make_server
from mission_manager.node import MissionManager
from robotpilot_ui_package.auth import install_auth
from robotpilot_ui_package.platform_api import PlatformStore, register_platform_api
from test_platform_api import FakeBridge

class Spy:
    def __init__(self, forward=None): self.messages=[]; self.forward=forward
    def publish(self, msg):
        self.messages.append(msg)
        if self.forward: self.forward.publish(msg)

def main():
    with tempfile.TemporaryDirectory(prefix="alpha-ros-fixture-") as directory:
        os.environ["ROS_LOG_DIR"]=directory
        os.environ["ROBOT_MODE"]="simulation"
        rclpy.init(args=["--ros-args","-p",f"database_path:={directory}/missions.sqlite3"])
        node=MissionManager()
        node.goal_pub=Spy(node.goal_pub);node.state_pub=Spy();node.ack_pub=Spy();node.hold_pub=Spy();node.stop_pub=Spy()
        authority = subprocess.Popen([str(Path(__file__).resolve().parents[4]/"install/nav_status/lib/nav_status/nav_status_node"), "--ros-args", "-p", "arrival_hold_time:=0.12"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        execution_states=[]
        node.create_subscription(NavigationExecution,"/navigation/execution_state",execution_states.append,10)
        planner_pub = node.create_publisher(NavigationExecution, "/navigation/planner_state", QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        feedback_pub = node.create_publisher(ControllerFeedback, "/neupan/controller_feedback", 10)
        odom_pub = node.create_publisher(Odometry, "/odom_wheel", 10)
        class Bridge(FakeBridge):
            x=0.;y=0.
            def refresh(self):
                base=super().snapshot()
                node.on_software_stop_state(String(data=json.dumps(base["software_stop_state"])))
                node.on_battery_state(String(data=json.dumps(base["battery_state"])))
                node.on_route_catalog(String(data=json.dumps({"active_files":base["map_identity"]})))
                node.on_map_bundle(String(data=json.dumps(base["map_bundle"])))
                odom=Odometry();odom.header.frame_id="odom";odom.pose.pose.orientation.w=1.
                node.on_ekf_odom(odom)
                odom.header.frame_id="map";odom.header.stamp=node.get_clock().now().to_msg()
                odom.pose.pose.position.x=self.x;odom.pose.pose.position.y=self.y;node.on_odom(odom)
                rclpy.spin_once(node, timeout_sec=0.001)
                return base
            def snapshot(self):
                base=self.refresh();node.publish_state()
                base["mission"]=json.loads(node.state_pub.messages[-1].data)
                return base
            def command(self, command, request_id):
                self.refresh()
                node.on_command(String(data=json.dumps({**command,"request_id":request_id})))
                return json.loads(node.ack_pub.messages[-1].data)
        bridge=Bridge()
        app=Flask(__name__)
        store=PlatformStore(directory+"/platform.sqlite3")
        register_platform_api(app,lambda:bridge,store,"robot-001")
        install_auth(app,"open",directory+"/auth.sqlite3","robot-001")
        @app.get("/api/auth/status")
        def auth_status():
            return jsonify({"robot_id":"robot-001","mode":"open","isLocalNetwork":True,"robot_mode":"simulation"})
        store.create_waypoint("robot-001",{"map_id":"simulation/map-a","map_version_id":"simulation/map-a","name":"Home","x":1.,"y":2.,"yaw":0.,"action":"none","point_type":"inspection","source":"fixture","wait_time":0.,"enabled":True})
        @app.post("/fixture/arrival/<kind>")
        def arrival(kind):
            deadline=time.monotonic()+3
            while not node.nav_seen_active and time.monotonic()<deadline:
                rclpy.spin_once(node,timeout_sec=.02)
            execution=NavigationExecution()
            execution.stamp=node.get_clock().now().to_msg()
            execution.goal=node.goal_pub.messages[-1]
            execution.path_stamp=node.get_clock().now().to_msg()
            execution.state=execution.MOVING
            planner_pub.publish(execution)
            bridge.x,bridge.y=(1.,2.) if kind=="correct" else (9.,9.)
            deadline=time.monotonic()+.4
            while time.monotonic()<deadline:
                stamp=node.get_clock().now().to_msg()
                feedback=ControllerFeedback(stamp=stamp,path_stamp=execution.path_stamp,arrived=kind=="correct",position_tolerance=.5)
                feedback.observed_pose=type(execution.goal)()
                feedback.observed_pose.header.frame_id="map"
                feedback.observed_pose.header.stamp=stamp
                feedback.observed_pose.pose.position.x=bridge.x;feedback.observed_pose.pose.position.y=bridge.y
                feedback.observed_pose.pose.orientation.w=1.
                feedback_pub.publish(feedback)
                odom=Odometry();odom.header.stamp=stamp;odom_pub.publish(odom)
                bridge.refresh();rclpy.spin_once(node,timeout_sec=.01);node.tick()
            return jsonify({"status":node.run["status"],"goals_sent":len(node.goal_pub.messages),"navigation_states":[{"state":e.state,"detail":e.detail,"result":e.result_json,"id":e.execution_id} for e in execution_states[-8:]],"active":node.nav_seen_active,"evidence":node.navigation_result})
        deadline=time.monotonic()+5
        while feedback_pub.get_subscription_count()<1 and time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.02)
        if feedback_pub.get_subscription_count()<1:
            authority.terminate();authority.wait(timeout=5)
            raise RuntimeError("Navigation authority did not start")
        server=make_server("127.0.0.1",0,app)
        print("ALPHA_FIXTURE_PORT="+str(server.server_port),flush=True)
        import signal
        def stop_fixture(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop_fixture)
        try: server.serve_forever()
        finally:
            authority.terminate();authority.wait(timeout=5)
            server.server_close();node.destroy_node();rclpy.shutdown()

if __name__=="__main__": main()
