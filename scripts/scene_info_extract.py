import json
import ai2thor.controller


def horizontal_dist(p1: Dict[str, float], p2: Dict[str, float]) -> float:
    return math.sqrt((p1["x"] - p2["x"])**2 + (p1["z"] - p2["z"])**2)

def format_position(pos: Dict[str, float]) -> str:
    return f"({pos['x']:.2f}, {pos['y']:.2f}, {pos['z']:.2f})"

def capitalize_first(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def build_scene_description(traj_data: Dict[str, Any]) -> str:
    """
    Generate a detailed natural-language scene description from ALFRED traj.json.
    """
    scene = traj_data["scene"]
    floor_plan = scene["floor_plan"]
    random_seed = scene.get("random_seed", 0)
    if random_seed > 2_147_483_647:
        random_seed = random_seed % 2_147_483_647

    # --------------------------------------------------------------- #
    # 1. Initialize controller
    # --------------------------------------------------------------- #
    controller = ai2thor.controller.Controller(
        agentMode="default",
        visibilityDistance=1.5,
        scene=floor_plan,
        gridSize=0.25,
        snapToGrid=True,
        rotateStepDegrees=90,
        renderDepthImage=False,
        renderInstanceSegmentation=False,
        width=300,
        height=300,
        fieldOfView=90,
    )
    controller.reset(scene=floor_plan, randomSeed=random_seed)

    # --------------------------------------------------------------- #
    # 2. Apply deterministic modifications
    # --------------------------------------------------------------- #
    if scene.get("object_poses"):
        controller.step(action="SetObjectPoses", objectPoses=scene["object_poses"])
    if scene.get("object_toggles"):
        controller.step(action="SetObjectToggles", objectToggles=scene["object_toggles"])
    if scene.get("dirty_and_empty"):
        for obj_id in scene["dirty_and_empty"]:
            controller.step(action="DirtyObject", objectId=obj_id)

    # --------------------------------------------------------------- #
    # 3. Teleport agent to initial pose
    # --------------------------------------------------------------- #
    if "init_action" in scene:
        init = scene["init_action"]
        controller.step(
            action="TeleportFull",
            x=init["x"], y=init["y"], z=init["z"],
            rotation=init["rotation"],
            horizon=init.get("horizon", 0),
            standing=init.get("standing", True),
        )

    # --------------------------------------------------------------- #
    # 4. Get final metadata
    # --------------------------------------------------------------- #
    event = controller.step(action="Pass")
    metadata = event.metadata
    objects = metadata["objects"]
    agent_pos = metadata["agent"]["position"]
    agent_rot = metadata["agent"]["rotation"]["y"]

    # Quick lookup: name → object dict
    obj_by_name = {obj["name"]: obj for obj in objects}

    # --------------------------------------------------------------- #
    # 5. Receptacles: from metadata (fixed scene objects)
    # --------------------------------------------------------------- #
    receptacles_meta = [
        obj for obj in objects if obj.get("receptacle", False)
    ]
    print(f"[DEBUG] Found {len(receptacles_meta)} receptacles in metadata")

    # --------------------------------------------------------------- #
    # 6. Movable items: from traj.json object_poses
    # --------------------------------------------------------------- #
    items_poses = scene.get("object_poses", [])
    print(f"[DEBUG] Found {len(items_poses)} movable items in object_poses")

    # --------------------------------------------------------------- #
    # 7. Build relationship lines
    # --------------------------------------------------------------- #
    relationship_lines = []

    for pose in items_poses:
        item_name = pose["objectName"]           # e.g., "Potato_..."
        item_type = item_name.split("_")[0].lower()

        # Get current position from metadata (after SetObjectPoses)
        meta_obj = obj_by_name.get(item_name)
        if meta_obj:
            print("meta")
            item_pos = meta_obj["position"]
        else:
            # Fallback: use pose (rare)
            item_pos = pose["position"]

        # State adjectives
        state_parts = []
        if meta_obj:
            if meta_obj.get("isBroken"):     state_parts.append("broken")
            if meta_obj.get("isDirty"):      state_parts.append("dirty")
            if meta_obj.get("isFilledWithLiquid"): state_parts.append("filled with liquid")
            if meta_obj.get("isToggled"):    state_parts.append("toggled on")
        state_adj = f" ({', '.join(state_parts)})" if state_parts else ""

        # Find best receptacle
        best_rel = None
        best_score = float("inf")

        for rec in receptacles_meta:
            rec_pos = rec["position"]
            rec_type = rec["objectType"].lower()

            h_dist = horizontal_dist(item_pos, rec_pos)
            v_dist = abs(item_pos["y"] - rec_pos["y"])

            rel = None
            score = float("inf")

            # ON TOP
            if item_pos["y"] > rec_pos["y"] and v_dist < 1.5 and h_dist < 1.0:
                rel = f"on the {rec_type}"
                score = h_dist

            # INSIDE
            elif v_dist < 0.3 and h_dist < 0.5:
                rel = f"inside the {rec_type}"
                score = h_dist + 0.1

            # NEXT TO
            elif v_dist < 0.5 and h_dist < 1.5:
                rel = f"next to the {rec_type}"
                score = h_dist + 0.5

            # NEAR
            elif h_dist < 2.5:
                rel = f"near the {rec_type}"
                score = h_dist + 1.0

            if rel and score < best_score:
                best_score = score
                best_rel = rel

        line = f"A {item_type}{state_adj} is {best_rel or 'lying in the room'}."
        relationship_lines.append(capitalize_first(line))

    # --------------------------------------------------------------- #
    # 8. Receptacle status lines
    # --------------------------------------------------------------- #
    receptacle_lines = []
    for rec in receptacles_meta:
        rec_type = rec["objectType"].lower()
        parts = [f"The {rec_type}"]

        openness = rec.get("openness", 0)
        if openness > 0.01:
            parts.append(f"is {openness*100:.0f}% open")
        else:
            parts.append("is closed")

        if rec.get("isDirty"):
            parts.append("and dirty")
        elif rec.get("isClean", True):
            parts.append("and clean")

        receptacle_lines.append(" ".join(parts) + ".")

    # --------------------------------------------------------------- #
    # 9. Assemble final description
    # --------------------------------------------------------------- #
    lines = [
        f"Scene: **{floor_plan}** (random seed {random_seed}). "
        f"The agent starts at position {format_position(agent_pos)} facing {agent_rot:.0f}°.",
        "",
    ]

    if receptacle_lines:
        lines.append("**Receptacles present:**")
        lines.extend(f"  • {rl}" for rl in receptacle_lines)
        lines.append("")

    if relationship_lines:
        lines.append("**Objects and their locations:**")
        lines.extend(f"  • {rl}" for rl in relationship_lines)
        lines.append("")

    total_items = len(items_poses)
    total_recs  = len(receptacles_meta)
    summary = (
        f"In total there {'is' if total_items == 1 else 'are'} {total_items} "
        f"movable object{'s' if total_items != 1 else ''} and "
        f"{total_recs} receptacle{'s' if total_recs != 1 else ''} in the room."
    )
    lines.append(summary)

    controller.stop()
    return "\n".join(lines)


traj_path = '/home/kat049/ws/alfred/data/json_2.1.0/train/pick_heat_then_place_in_recep-Egg-None-Fridge-6/trial_T20190907_184237_946198/traj_data.json'
with open(traj_path, 'r', encoding='utf-8') as file:
    data = json.load(file)
build_scene_description(data)











