import json
import ai2thor.controller
def extract_contextual_relationships(traj_data):
    controller = ai2thor.controller.Controller()
    event = controller.reset(scene_name=traj_data['scene']['floor_plan'])
    scene_metadata = event.metadata
    descriptions = []
    scene = traj_data['scene']
    object_poses = scene['object_poses']
    
    # Group objects by position
    receptacles = []  # Large objects that can hold things
    items = []        # Small objects that get placed
    RECEPTACLE_TYPES = set([scene_metadata['objects'][i]['name'].split('_')[0] for i in range(len(scene_metadata['objects'])) if scene_metadata['objects'][i]['receptacle']])
    for obj_info in object_poses:
        obj_name = obj_info['objectName']
        obj_type = obj_name.split('_')[0]
        if obj_type in RECEPTACLE_TYPES:
            receptacles.append(obj_info)
        else:
            items.append(obj_info)

    # Find spatial relationships
    for item in items:
        item_name = item['objectName']
        item_type = item_name.split('_')[0]
        item_pos = item['position']
        
        best_relationship = None
        min_distance = float('inf')
        
        for recep in receptacles:
            recep_pos = recep['position']
            recep_type = recep['objectName'].split('_')[0]
            
            # Calculate distances
            horizontal_dist = ((item_pos['x'] - recep_pos['x'])**2 +
                             (item_pos['z'] - recep_pos['z'])**2)**0.5
            vertical_dist = abs(item_pos['y'] - recep_pos['y'])
            
            # Determine relationship type based on relative positions
            relationship = None
            priority = float('inf')  # Lower is better
            
            # On top of (item above receptacle, close horizontally)
            if item_pos['y'] > recep_pos['y'] and vertical_dist < 1.5 and horizontal_dist < 1.0:
                relationship = f"{item_type} is on {recep_type}"
                priority = horizontal_dist
            
            # Inside (item at similar height, very close horizontally)
            elif vertical_dist < 0.3 and horizontal_dist < 0.5:
                relationship = f"{item_type} is in {recep_type}"
                priority = horizontal_dist
            
            # Next to (similar height, nearby)
            elif vertical_dist < 0.5 and horizontal_dist < 1.5:
                relationship = f"{item_type} is next to {recep_type}"
                priority = horizontal_dist + 0.5  # Lower priority than "on"
            
            # Near (within reasonable distance)
            elif horizontal_dist < 2.5:
                relationship = f"{item_type} is near {recep_type}"
                priority = horizontal_dist + 1.0  # Lowest priority
            
            if relationship and priority < min_distance:
                min_distance = priority
                best_relationship = relationship
        
        if best_relationship:
            descriptions.append(best_relationship)
        else:
            descriptions.append(f"{item_type} is in the room")
    
    return descriptions

traj_path = '/home/kat049/ws/alfred/data/json_2.1.0/train/pick_heat_then_place_in_recep-Egg-None-Fridge-6/trial_T20190907_184237_946198/traj_data.json'
with open(traj_path, 'r', encoding='utf-8') as file:
    data = json.load(file)
extract_contextual_relationships(data)











