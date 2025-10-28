#!/usr/bin/env python3
"""
Robust scene loader for ALFRED + old AI2-THOR (2017-2018)
Handles hanging Initialize, missing builds, X11, etc.
"""

import json
import sys
import os
import time
import subprocess
from pathlib import Path

from ai2thor.controller import Controller


def ensure_unity_build(controller):
    """Download Unity build if missing (only needed once)."""
    try:
        # This triggers download if not present
        if not os.path.exists(controller.executable_path()):
            print("Downloading AI2-THOR Unity build...")
            controller.download_binary()
            print("Download complete.")
    except Exception as e:
        print(f"Failed to download build: {e}")
        raise


def start_controller_headless_or_x11():
    """Start controller with proper display setup."""
    controller = Controller()

    # --- Linux: Use virtual X (Xvfb) if no display ---
    if sys.platform == "linux" and "DISPLAY" not in os.environ:
        print("No DISPLAY found. Starting Xvfb...")
        try:
            subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1024x768x24"])
            os.environ["DISPLAY"] = ":99"
            time.sleep(2)
        except FileNotFoundError:
            print("Xvfb not installed. Install with: sudo apt install xvfb")
            raise

    # --- Start controller ---
    print("Starting AI2-THOR controller...")
    try:
        # Download build if needed
        ensure_unity_build(controller)

        # Start Unity (300x300, not headless)
        controller.start(player_screen_width=300, player_screen_height=300)
        print("Unity started.")
    except Exception as e:
        print(f"Failed to start Unity: {e}")
        raise

    return controller


def safe_initialize(controller, timeout=30):
    """Send Initialize and wait with timeout."""
    print("Sending Initialize action...")
    start_time = time.time()

    # Send action
    controller.response_queue.put_nowait(dict(action="Initialize"))

    # Wait for response with timeout
    while time.time() - start_time < timeout:
        try:
            event = controller.request_queue.get(block=True, timeout=0.5)
            controller.last_event = event
            if event.metadata["lastActionSuccess"]:
                print("Initialize succeeded.")
                return event
            else:
                print(f"Initialize failed: {event.metadata['errorMessage']}")
                return None
        except:
            pass  # timeout, keep waiting

    raise TimeoutError("Initialize timed out. Unity may have crashed.")


# ----------------------------------------------------------------------
def generate_scene_info(traj_path: Path):
    with open(traj_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    scene = data["scene"]
    floor_plan = scene["floor_plan"]
    init_action = scene["init_action"]
    object_poses = scene["object_poses"]
    object_toggles = scene["object_toggles"]

    # --- 1. Start controller robustly ---
    controller = start_controller_headless_or_x11()

    try:
        # --- 2. Reset scene ---
        print(f"Resetting to {floor_plan}...")
        controller.reset(floor_plan)

        # --- 3. SAFE Initialize ---
        event = safe_initialize(controller, timeout=30)
        if not event:
            raise RuntimeError("Failed to initialize scene.")

        # --- 4. Apply object poses ---
        for pose in object_poses:
            obj = pose["object"]
            pos = pose["position"]
            rot = pose["rotation"]

            controller.step(dict(
                action="TeleportObject",
                objectId=obj,
                x=pos["x"], y=pos["y"], z=pos["z"]
            ))

            controller.step(dict(
                action="RotateObject",
                objectId=obj,
                rotation=dict(x=rot["x"], y=rot["y"], z=rot["z"])
            ))

        # --- 5. Apply toggles ---
        for t in object_toggles:
            action = "ToggleObjectOn" if t["state"] == "on" else "ToggleObjectOff"
            controller.step(dict(action=action, objectId=t["object"]))

        # --- 6. Agent init_action ---
        if isinstance(init_action, str):
            init_action = json.loads(init_action)
        controller.step(init_action)

        # --- 7. Describe scene ---
        objects = controller.last_event.metadata["objects"]
        descs = []
        for obj in objects:
            name = obj["objectType"].lower()
            loc = ""
            if obj.get("parentReceptacles"):
                parent = next((o for o in objects if o["objectId"] == obj["parentReceptacles"][0]), None)
                if parent:
                    loc = f"in the {parent['objectType'].lower()}"
            states = []
            if obj.get("isToggled"): states.append("on")
            if obj.get("temperature") == "Hot": states.append("hot")
            if states:
                state_str = " and is " + ", ".join(states)
            else:
                state_str = ""
            descs.append(f"{name} {loc}{state_str}".strip())

        print("\nScene description:")
        print(", ".join(d for d in descs if d) + ".")

    finally:
        controller.stop()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scene_info.py <traj.json>")
        sys.exit(1)
    generate_scene_info(Path(sys.argv[1]))