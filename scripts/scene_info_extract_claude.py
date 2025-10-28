import json
import ai2thor.controller


def get_object_state_from_traj(obj_name, scene_data):
    """
    Get object state information from trajectory data.
    """
    # Check if object is dirty
    is_dirty = False
    if 'dirty_and_empty' in scene_data and scene_data['dirty_and_empty']:
        is_dirty = obj_name in scene_data['dirty_and_empty']
    
    # Check toggle state
    is_toggled = None
    if 'object_toggles' in scene_data and scene_data['object_toggles']:
        for toggle in scene_data['object_toggles']:
            toggle_id = toggle.get('objectId', '')
            if obj_name in toggle_id or toggle_id.startswith(obj_name.split('_')[0]):
                is_toggled = toggle.get('isOn', None)
                break
    
    return {
        'isDirty': is_dirty,
        'isToggled': is_toggled
    }


def match_movable_object(pose_obj, metadata_objects, used_objects):
    """
    Match a movable object from trajectory to simulator metadata.
    Uses position-based matching since names don't match.
    """
    pose_type = pose_obj['objectName'].split('_')[0]
    pose_pos = pose_obj['position']
    
    # Find objects of the same type in metadata
    candidates = [
        obj for obj in metadata_objects 
        if obj['objectType'] == pose_type 
        and obj['name'] not in used_objects
        and obj.get('pickupable', False)  # Only match pickupable objects
    ]
    
    if not candidates:
        return None
    
    # If only one candidate, return it
    if len(candidates) == 1:
        used_objects.add(candidates[0]['name'])
        return candidates[0]
    
    # Find closest match by position
    best_match = None
    min_dist = float('inf')
    
    for candidate in candidates:
        if 'position' not in candidate:
            continue
        
        cand_pos = candidate['position']
        dist = ((pose_pos['x'] - cand_pos['x'])**2 + 
                (pose_pos['y'] - cand_pos['y'])**2 + 
                (pose_pos['z'] - cand_pos['z'])**2)**0.5
        
        if dist < min_dist:
            min_dist = dist
            best_match = candidate
    
    if best_match and min_dist < 0.5:  # Must be within 0.5 units
        used_objects.add(best_match['name'])
        return best_match
    
    return None


def extract_scene_info_combined(traj_data):
    """
    Extract scene information by combining:
    - Receptacles and fixed objects from simulator
    - Movable objects from trajectory with simulator metadata
    """
    scene = traj_data['scene']
    
    random_seed = scene['random_seed']
    if random_seed > 2147483647:  # Max int32
        random_seed = random_seed % 2147483647

    # Initialize simulator
    controller = ai2thor.controller.Controller(
        agentMode="default",
        visibilityDistance=1.5,
        scene=scene['floor_plan'],
        gridSize=0.25,
        snapToGrid=True,
        rotateStepDegrees=90,
        renderDepthImage=False,
        renderInstanceSegmentation=False,
        width=300,
        height=300,
        fieldOfView=90
    )
    
    # Reset scene
    event = controller.reset(
        scene=scene['floor_plan'],
        randomSeed=random_seed
    )
    
    # Don't set object poses - we'll use the trajectory data instead
    # Just set toggles for receptacles (open/closed states)
    if 'object_toggles' in scene and scene['object_toggles']:
        try:
            event = controller.step(
                action="SetObjectToggles",
                objectToggles=scene['object_toggles']
            )
        except:
            pass  # Some toggles might not work
    
    # Get metadata - this has all receptacles and default scene objects
    event = controller.step(action="Pass")
    scene_metadata = event.metadata

    scene_info = {
        'scene_name': scene_metadata['sceneName'],
        'random_seed': scene.get('random_seed'),
        'objects': [],
        'receptacles': [],
        'movable_items': [],
        'spatial_relationships': []
    }
    
    # Get all receptacles from metadata (these are in the scene by default)
    receptacles = []
    for obj in scene_metadata['objects']:
        if obj['receptacle']:
            obj_details = {
                'name': obj['name'],
                'objectType': obj['objectType'],
                'objectId': obj.get('objectId'),
                'position': obj.get('position'),
                'rotation': obj.get('rotation'),
                'isOpen': obj.get('isOpen') if obj.get('openable') else None,
                'openness': obj.get('openness') if obj.get('openable') else None,
                'isToggled': obj.get('isToggled') if obj.get('toggleable') else None,
                'receptacle': True
            }
            
            # Override with trajectory data if available
            traj_state = get_object_state_from_traj(obj['name'], scene)
            if traj_state['isToggled'] is not None:
                obj_details['isToggled'] = traj_state['isToggled']
            
            receptacles.append(obj_details)
            scene_info['receptacles'].append(obj_details)
            scene_info['objects'].append(obj_details)
    
    print(f"Found {len(receptacles)} receptacles in scene")
    
    # Now process movable objects from trajectory
    object_poses = scene.get('object_poses', [])
    used_objects = set()
    movable_items = []
    
    for pose_obj in object_poses:
        obj_name = pose_obj['objectName']
        obj_type = obj_name.split('_')[0]
        
        # Try to match with metadata
        obj_meta = match_movable_object(pose_obj, scene_metadata['objects'], used_objects)
        
        if obj_meta:
            # Use metadata + trajectory state
            obj_details = {
                'name': obj_meta['name'],
                'traj_name': obj_name,  # Keep trajectory name for reference
                'objectType': obj_meta['objectType'],
                'objectId': obj_meta.get('objectId'),
                'position': pose_obj['position'],  # Use trajectory position
                'rotation': pose_obj.get('rotation'),
                'visible': obj_meta.get('visible'),
                'pickupable': obj_meta.get('pickupable', False),
                
                # State from metadata
                'isDirty': obj_meta.get('isDirty', False),
                'isCooked': obj_meta.get('isCooked', False),
                'isSliced': obj_meta.get('isSliced', False),
                'isBroken': obj_meta.get('isBroken', False),
                'isUsedUp': obj_meta.get('isUsedUp', False),
                'isFilledWithLiquid': obj_meta.get('isFilledWithLiquid', False),
                'temperature': obj_meta.get('temperature', 'RoomTemp'),
                'parentReceptacles': obj_meta.get('parentReceptacles', []),
            }
            
            # Override with trajectory state where applicable
            traj_state = get_object_state_from_traj(obj_name, scene)
            if traj_state['isDirty']:
                obj_details['isDirty'] = True
            
        else:
            # Couldn't match - use trajectory data only
            print(f"Warning: Could not match {obj_name} to metadata, using trajectory data only")
            obj_details = {
                'name': obj_name,
                'traj_name': obj_name,
                'objectType': obj_type,
                'position': pose_obj['position'],
                'rotation': pose_obj.get('rotation'),
                'pickupable': True,  # Assume true since it's in object_poses
            }
            
            # Add trajectory state
            traj_state = get_object_state_from_traj(obj_name, scene)
            obj_details.update(traj_state)
        
        movable_items.append(obj_details)
        scene_info['movable_items'].append(obj_details)
        scene_info['objects'].append(obj_details)
    
    print(f"Found {len(movable_items)} movable items from trajectory")
    
    # Calculate spatial relationships
    for item in movable_items:
        if 'position' not in item or item['position'] is None:
            continue
            
        item_type = item['objectType']
        item_pos = item['position']
        
        best_relationship = None
        min_distance = float('inf')
        best_receptacle = None
        
        for recep in receptacles:
            if 'position' not in recep or recep['position'] is None:
                continue
                
            recep_type = recep['objectType']
            recep_pos = recep['position']
            
            # Calculate distances
            horizontal_dist = ((item_pos['x'] - recep_pos['x'])**2 +
                             (item_pos['z'] - recep_pos['z'])**2)**0.5
            vertical_dist = abs(item_pos['y'] - recep_pos['y'])
            
            # Determine relationship
            relationship = None
            priority = float('inf')
            
            if item_pos['y'] > recep_pos['y'] and vertical_dist < 1.5 and horizontal_dist < 1.0:
                relationship = "on"
                priority = horizontal_dist
            elif vertical_dist < 0.3 and horizontal_dist < 0.5:
                relationship = "in"
                priority = horizontal_dist
            elif vertical_dist < 0.5 and horizontal_dist < 1.5:
                relationship = "next to"
                priority = horizontal_dist + 0.5
            elif horizontal_dist < 2.5:
                relationship = "near"
                priority = horizontal_dist + 1.0
            
            if relationship and priority < min_distance:
                min_distance = priority
                best_relationship = relationship
                best_receptacle = recep_type
        
        # Build relationship
        rel_desc = {
            'item': item_type,
            'item_name': item.get('name'),
            'relationship': best_relationship if best_relationship else "in room",
            'receptacle': best_receptacle,
            'item_state': {
                'isDirty': item.get('isDirty', False),
                'isCooked': item.get('isCooked', False),
                'isSliced': item.get('isSliced', False),
                'temperature': item.get('temperature', 'RoomTemp'),
            }
        }
        
        scene_info['spatial_relationships'].append(rel_desc)
    
    controller.stop()
    return scene_info


# Example usage
if __name__ == "__main__":
    traj_path = '/home/kat049/ws/alfred/data/json_2.1.0/train/pick_heat_then_place_in_recep-Egg-None-Fridge-6/trial_T20190907_184237_946198/traj_data.json'
    
    with open(traj_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
    
    scene_info = extract_scene_info_combined(data)
    
    # Print summary
    print(f"\n=== SCENE SUMMARY ===")
    print(f"Scene: {scene_info['scene_name']}")
    print(f"Total objects: {len(scene_info['objects'])}")
    print(f"Receptacles: {len(scene_info['receptacles'])}")
    print(f"Movable items: {len(scene_info['movable_items'])}")
    
    print("\n=== Sample Receptacles ===")
    for recep in scene_info['receptacles'][:5]:
        open_str = f" (open)" if recep.get('isOpen') else f" (closed)" if recep.get('isOpen') == False else ""
        print(f"{recep['objectType']}: {recep['name']}{open_str}")
    
    print("\n=== Movable Items ===")
    for item in scene_info['movable_items'][:10]:
        state_parts = []
        if item.get('isDirty'):
            state_parts.append("dirty")
        if item.get('isCooked'):
            state_parts.append("cooked")
        if item.get('isSliced'):
            state_parts.append("sliced")
        
        state_str = f" ({', '.join(state_parts)})" if state_parts else ""
        print(f"{item['objectType']}: {item.get('traj_name', item['name'])}{state_str}")
    
    print("\n=== Spatial Relationships ===")
    for rel in scene_info['spatial_relationships']:
        state_info = []
        if rel['item_state']['isDirty']:
            state_info.append("dirty")
        if rel['item_state']['isCooked']:
            state_info.append("cooked")
        if rel['item_state']['isSliced']:
            state_info.append("sliced")
        
        state_str = f" ({', '.join(state_info)})" if state_info else ""
        
        if rel['receptacle']:
            print(f"{rel['item']}{state_str} is {rel['relationship']} {rel['receptacle']}")
        else:
            print(f"{rel['item']}{state_str} is {rel['relationship']}")
    
 