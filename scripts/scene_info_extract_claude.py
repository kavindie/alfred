import json
import ai2thor.controller


def match_object_name(pose_name, metadata_objects, used_objects=None):
    """
    Match object name from pose data to metadata, handling mismatches in suffix.
    Returns the matched metadata object or None.
    """
    if used_objects is None:
        used_objects = set()
    
    pose_prefix = pose_name.split('_')[0]
    
    # Try exact match first
    for obj in metadata_objects:
        if obj['name'] == pose_name and obj['name'] not in used_objects:
            used_objects.add(obj['name'])
            return obj
    
    # Try matching by objectType instead of name prefix
    # This handles cases where names are completely different
    for obj in metadata_objects:
        if obj['objectType'] == pose_prefix and obj['name'] not in used_objects:
            used_objects.add(obj['name'])
            return obj
    
    # Last resort: try prefix match on name
    for obj in metadata_objects:
        if obj['name'].startswith(pose_prefix + '_') and obj['name'] not in used_objects:
            used_objects.add(obj['name'])
            return obj
    
    return None


def get_object_details(obj_meta):
    """
    Extract all relevant details from object metadata.
    """
    details = {
        'name': obj_meta.get('name', 'Unknown'),
        'objectType': obj_meta.get('objectType', 'Unknown'),
        'objectId': obj_meta.get('objectId', 'Unknown'),
        
        # State properties
        'isDirty': obj_meta.get('isDirty', False),
        'isCooked': obj_meta.get('isCooked', False),
        'isSliced': obj_meta.get('isSliced', False),
        'isBroken': obj_meta.get('isBroken', False),
        'isUsedUp': obj_meta.get('isUsedUp', False),
        'isFilledWithLiquid': obj_meta.get('isFilledWithLiquid', False),
        'fillLiquid': obj_meta.get('fillLiquid', None),
        'temperature': obj_meta.get('temperature', 'RoomTemp'),
        
        # Toggleable state (for lamps, faucets, etc.)
        'isToggled': obj_meta.get('isToggled', None) if obj_meta.get('toggleable') else None,
        
        # Openable state (for cabinets, drawers, etc.)
        'isOpen': obj_meta.get('isOpen', None) if obj_meta.get('openable') else None,
        'openness': obj_meta.get('openness', None) if obj_meta.get('openable') else None,
        
        # Positional info
        'position': obj_meta.get('position', {}),
        'rotation': obj_meta.get('rotation', {}),
        'parentReceptacles': obj_meta.get('parentReceptacles', []),
        
        # Interaction properties
        'visible': obj_meta.get('visible', False),
        'isPickedUp': obj_meta.get('isPickedUp', False),
        'receptacle': obj_meta.get('receptacle', False),
        'pickupable': obj_meta.get('pickupable', False),
        'moveable': obj_meta.get('moveable', False),
    }
    
    return details


def extract_contextual_relationships(traj_data):    
    scene = traj_data['scene']
    
    random_seed = scene['random_seed']
    if random_seed > 2147483647:  # Max int32
        random_seed = random_seed % 2147483647

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
    
    # Reset to the specific scene with random seed
    event = controller.reset(
        scene=scene['floor_plan'],
        randomSeed=random_seed
    )
    
    # Set object poses
    if 'object_poses' in scene and scene['object_poses']:
        event = controller.step(
            action="SetObjectPoses",
            objectPoses=scene['object_poses']
        )
    
    # Set object toggles (open/closed states)
    if 'object_toggles' in scene and scene['object_toggles']:
        event = controller.step(
            action="SetObjectToggles",
            objectToggles=scene['object_toggles']
        )
    
    # Set dirty/clean states
    if 'dirty_and_empty' in scene and scene['dirty_and_empty']:
        for obj_id in scene['dirty_and_empty']:
            controller.step(action="DirtyObject", objectId=obj_id)
    
    # Set agent initial position
    if 'init_action' in scene:
        init = scene['init_action']
        event = controller.step(
            action="TeleportFull",
            x=init['x'],
            y=init['y'],
            z=init['z'],
            rotation=init['rotation'],
            horizon=init['horizon'],
            standing=init.get('standing', True)
        )
    
    # Get final metadata
    event = controller.step(action="Pass")
    scene_metadata = event.metadata

    # Build comprehensive scene information
    scene_info = {
        'scene_name': scene_metadata['sceneName'],
        'objects': [],
        'spatial_relationships': [],
        'receptacles': [],
        'items': []
    }
    
    # Create a map of object names to their full metadata
    obj_metadata_map = {obj['name']: obj for obj in scene_metadata['objects']}
    
    # Identify receptacle types from actual scene metadata
    RECEPTACLE_TYPES = set([
        obj['objectType'] for obj in scene_metadata['objects'] 
        if obj['receptacle']
    ])
    
    # Debug: print ALL object types in metadata
    print(f"\nTotal objects in metadata: {len(scene_metadata['objects'])}")
    object_types_in_metadata = {}
    for obj in scene_metadata['objects']:
        obj_type = obj['objectType']
        if obj_type not in object_types_in_metadata:
            object_types_in_metadata[obj_type] = []
        object_types_in_metadata[obj_type].append(obj['name'])
    
    print(f"\nObject types available in metadata:")
    for obj_type, names in sorted(object_types_in_metadata.items()):
        print(f"  {obj_type}: {len(names)} instances")
    
    # Print non-receptacle objects
    non_receptacles = [obj for obj in scene_metadata['objects'] if not obj['receptacle']]
    print(f"\nNon-receptacle objects in metadata: {len(non_receptacles)}")
    if non_receptacles:
        print("Sample non-receptacles:")
        for obj in non_receptacles[:20]:
            print(f"  {obj['objectType']}: {obj['name']}")

    object_poses = scene['object_poses'] if 'object_poses' in scene else []
    
    print(f"\nObject poses to match: {len(object_poses)}")
    pose_types = {}
    for pose in object_poses:
        obj_type = pose['objectName'].split('_')[0]
        pose_types[obj_type] = pose_types.get(obj_type, 0) + 1
    print("Object types in poses:")
    for obj_type, count in sorted(pose_types.items()):
        print(f"  {obj_type}: {count} instances")
    
    # Group objects by type and extract details
    receptacles = []
    items = []
    used_objects = set()  # Track which metadata objects we've already matched
    
    for obj_info in object_poses:
        obj_name = obj_info['objectName']
        
        # Match object from metadata
        obj_meta = match_object_name(obj_name, scene_metadata['objects'], used_objects)
        
        if obj_meta is None:
            print(f"Warning: Could not match object {obj_name}")
            continue
        
        obj_type = obj_meta['objectType']
        obj_details = get_object_details(obj_meta)
        
        # Add to scene info
        scene_info['objects'].append(obj_details)
        
        # Categorize as receptacle or item
        if obj_type in RECEPTACLE_TYPES:
            receptacles.append({'info': obj_info, 'meta': obj_meta, 'details': obj_details})
            scene_info['receptacles'].append(obj_details)
        else:
            items.append({'info': obj_info, 'meta': obj_meta, 'details': obj_details})
            scene_info['items'].append(obj_details)

    # Find spatial relationships
    for item_data in items:
        item = item_data['info']
        item_meta = item_data['meta']
        item_details = item_data['details']
        
        item_name = item['objectName']
        item_type = item_meta['objectType']
        item_pos = item['position']

        best_relationship = None
        min_distance = float('inf')
        best_receptacle = None
        
        for recep_data in receptacles:
            recep = recep_data['info']
            recep_meta = recep_data['meta']
            
            recep_pos = recep['position']
            recep_type = recep_meta['objectType']
            
            # Calculate distances
            horizontal_dist = ((item_pos['x'] - recep_pos['x'])**2 +
                             (item_pos['z'] - recep_pos['z'])**2)**0.5
            vertical_dist = abs(item_pos['y'] - recep_pos['y'])
            
            # Determine relationship type based on relative positions
            relationship = None
            priority = float('inf')
            
            # On top of (item above receptacle, close horizontally)
            if item_pos['y'] > recep_pos['y'] and vertical_dist < 1.5 and horizontal_dist < 1.0:
                relationship = "on"
                priority = horizontal_dist
            
            # Inside (item at similar height, very close horizontally)
            elif vertical_dist < 0.3 and horizontal_dist < 0.5:
                relationship = "in"
                priority = horizontal_dist
            
            # Next to (similar height, nearby)
            elif vertical_dist < 0.5 and horizontal_dist < 1.5:
                relationship = "next to"
                priority = horizontal_dist + 0.5
            
            # Near (within reasonable distance)
            elif horizontal_dist < 2.5:
                relationship = "near"
                priority = horizontal_dist + 1.0
            
            if relationship and priority < min_distance:
                min_distance = priority
                best_relationship = relationship
                best_receptacle = recep_type
        
        # Build relationship description
        rel_desc = {
            'item': item_type,
            'item_name': item_meta['name'],
            'relationship': best_relationship if best_relationship else "in room",
            'receptacle': best_receptacle,
            'item_state': {
                'isDirty': item_details['isDirty'],
                'isCooked': item_details['isCooked'],
                'isSliced': item_details['isSliced'],
                'temperature': item_details['temperature'],
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
    
    # Debug: Print sample names from both sources
    print("=== DEBUG INFO ===")
    if 'object_poses' in data['scene'] and data['scene']['object_poses']:
        print(f"\nSample object_poses names (first 5):")
        for obj in data['scene']['object_poses'][:5]:
            print(f"  {obj['objectName']}")
    
    scene_info = extract_contextual_relationships(data)
    
    # After scene setup, print sample metadata names
    print(f"\nSample metadata object names (first 10):")
    # This will be printed inside the function, so we need to modify it
    
    # Print summary
    print(f"\n=== RESULTS ===")
    print(f"Scene: {scene_info['scene_name']}")
    print(f"Total objects: {len(scene_info['objects'])}")
    print(f"Receptacles: {len(scene_info['receptacles'])}")
    print(f"Items: {len(scene_info['items'])}")
    
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
    
    # Optionally save to file
    # with open('scene_info.json', 'w') as f:
    #     json.dump(scene_info, f, indent=2)