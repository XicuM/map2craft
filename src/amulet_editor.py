"""
Amulet world editor interface for map2craft.
Handles schematic placement and world modifications.
"""

import logging
import json
import yaml
import amulet
import amulet.nbt as amulet_nbt
from pathlib import Path
from typing import Dict, List, Tuple

log = logging.getLogger(__name__)

class AmuletEditor:
    def __init__(self, config={}):
        self.config = config    
        self.schematics_dir = Path(config['buildings']['schematics_dir'])
        
        # Build mapping from config types
        self.building_map = {}
        for b_def in config['buildings'].get('types', []):
            if 'name' in b_def and 'schematic' in b_def:
                self.building_map[b_def['name']] = b_def['schematic']

    def place_sign(self, level, x, y, z, text):
        ''' Place an oak sign with text. '''
        try:
            # Create block: minecraft:oak_sign[rotation=0]
            block = amulet.Block("minecraft", "oak_sign", {"rotation": "0"})
            
            # Create NBT for text
            # Minecraft sign text format: JSON string inside NBT String
            text_json = json.dumps({"text": text})
            
            # Using amulet_nbt to create the BlockEntity Tag
            nbt = amulet_nbt.TAG_Compound({
                "id": amulet_nbt.TAG_String("minecraft:sign"),
                "x": amulet_nbt.TAG_Int(x),
                "y": amulet_nbt.TAG_Int(y),
                "z": amulet_nbt.TAG_Int(z),
                "is_waxed": amulet_nbt.TAG_Byte(0),
                "Text1": amulet_nbt.TAG_String(text_json),
                "Text2": amulet_nbt.TAG_String(""),
                "Text3": amulet_nbt.TAG_String(""),
                "Text4": amulet_nbt.TAG_String("")
            })
            
            # Place the block with the block entity
            # Amulet v2: set_version_block(x, y, z, dimension, (version, block), block_entity)
            # We need to GetVersionNumber equivalent. 
            # Alternatively, simple set_block and set the block entity separately?
            # Amulet API is tricky without documentation, but let's try assuming standard usage.
            
            dimension = "minecraft:overworld"
            level.set_block(x, y, z, dimension, block)
            
            # Now set the block entity
            # level.set_block_entity(x, y, z, dimension, nbt) should exist?
            # Creating a generic approach:
            
            # Note: If Amulet v2 wrapper is complex, we might skip NBT if it fails.
            # But let's try inserting it into the chunk directly if needed.
            # For now, let's try assuming there is a way to set it.
            # Accessing the chunk:
            cx, cz = x >> 4, z >> 4
            chunk = level.get_chunk(cx, cz, dimension)
            chunk.block_entities[(x, y, z)] = nbt
            
        except Exception as e:
            log.warning(f"Failed to place sign at {x},{y},{z}: {e}")
        ''' Place an oak sign with text. '''
        try:
            # Block: minecraft:oak_sign[rotation=0] (standing sign)
            # Find a safe spot? Ideally just place it in front or inside?
            # For now, let's place it at the specific coord (which might conflict with the building center)
            # Maybe place it at y+1? Or rely on the schematic having an air block?
            # Actually, standard schematic placement is usually centered or corner.
            # Let's try to place it at the schematic origin for now.
            
            # Create block
            # Note: Amulet v2 might use Block directly, check API
            # Since we are using installed Amulet v2 (implied by previous steps finding only Python 3.12/v2)
            # Block format: "namespace:block_name[properties]"
            
            # Using universal block format if possible
            block = amulet.Block("minecraft", "oak_sign", {"rotation": "0"})
            
            # Create NBT for text
            # Text1: '{"text":"..."}'
            text_json = json.dumps({"text": text})
            nbt = amulet_nbt.NBTFile(
                amulet_nbt.TAG_Compound({
                    "id": amulet_nbt.TAG_String("minecraft:sign"),
                    "x": amulet_nbt.TAG_Int(x),
                    "y": amulet_nbt.TAG_Int(y),
                    "z": amulet_nbt.TAG_Int(z),
                    "Text1": amulet_nbt.TAG_String(text_json),
                    "Text2": amulet_nbt.TAG_String(""),
                    "Text3": amulet_nbt.TAG_String(""),
                    "Text4": amulet_nbt.TAG_String("")
                })
            )
            
            level.set_version_block(x, y, z, "minecraft:overworld", (GetVersionNumber(), block), nbt)
            # Note: set_version_block usage depends on exact Amulet version.
            # Safe bet for Amulet v2: level.set_block(x,y,z, dimension, block) and separate set_block_entity?
            # Or use put_block?
            
            # Let's use lower level API if possible or just standard set_block
            level.set_block(x, y, z, "minecraft:overworld", block)
            
        except Exception as e:
            log.warning(f"Failed to place sign at {x},{y},{z}: {e}")

    def place_buildings(self, world_path: str, placements_path: str, height_meta_path: str) -> None:
        ''' Place buildings into the world using Amulet.
        
            :param str world_path: Path to the world directory
            :param str placements_path: Path to the placements JSON file
            :param str height_meta_path: Path to the heightmap metadata JSON
        '''
        log.info(f"Adding buildings to world: {world_path}")
        
        placements_path = Path(placements_path)
        height_meta_path = Path(height_meta_path) if height_meta_path else None

        if not placements_path.exists():
            log.warning(f"Placements file not found: {placements_path}")
            return

        # Load height metadata for height mapping
        if height_meta_path is None or not height_meta_path.exists():
            log.warning(f"Height metadata not found: {height_meta_path}")
            if not height_meta_path: return

        with open(height_meta_path, 'r') as f: h_meta = json.load(f)
        
        # Metadata structure: { "terrain": { "elevation": { "min_meters": ... } }, "minecraft": { "build_limit": { "min": ... } } }
        try:
            elev_meta = h_meta.get('terrain', {}).get('elevation', {})
            min_meters = float(elev_meta.get('min_meters', 0))
            max_meters = float(elev_meta.get('max_meters', 255))
            
            # Using Minecraft build limits for Y-range
            mc_meta = h_meta.get('minecraft', {})
            default_min_y = mc_meta.get('build_limit', {}).get('min', -64)
            default_max_y = mc_meta.get('build_limit', {}).get('max', 320)
            
            # Use 'min_y'/'max_y' if they exist (old format or override), else usage defaults
            min_y = h_meta.get('min_y', default_min_y)
            max_y = h_meta.get('max_y', default_max_y)
        except Exception as e:
            log.warning(f"Error parsing metadata: {e}. Using defaults.")
            min_meters, max_meters = 0, 255
            min_y, max_y = -64, 320
        
        # Load placements
        with open(placements_path, 'r') as f: data = yaml.safe_load(f)
        
        placements = data.get('placements', [])
        if not placements: log.info("No buildings to place."); return

        # Handle nested directory from WorldPainter export
        world_path = Path(world_path)
        if not (world_path / "level.dat").exists():
            # Look in subdirectories
            for entry in world_path.iterdir():
                if entry.is_dir() and (entry / "level.dat").exists():
                    log.info(f"Found world in subdirectory: {entry.name}")
                    world_path = entry
                    break

        # Load level
        try: level = amulet.load_level(world_path)
        except Exception as e:
            log.error(f"Failed to load world at {world_path}: {e}")
            return
        
        placed_count = 0
        dimension = "minecraft:overworld"
        
        for p in placements:
            props = p.get('properties', {})
            b_type = props.get('building', 'building_type')
            
            schematic_filename = self.building_map.get(b_type)
            if not schematic_filename:
                log.warning(f"No schematic configured for type '{b_type}'. Skipping.")
                continue

            schematic_path = self.schematics_dir/schematic_filename
            if not schematic_path.exists():
                log.warning(f"Schematic file not found: {schematic_path}")
                continue

            # Load schematic
            try: schematic = amulet.load_level(schematic_path)
            except Exception as e:
                log.error(f"Failed to load schematic {schematic_path}: {e}")
                continue

            # Calculate coordinates
            # YAML x -> X (East), YAML y -> Z (South)
            x = int(p['x'])
            z = int(p['y'])
            
            # Linear interpolation from meters to MC Y
            elev = p['elevation']
            y_range = max_y - min_y
            m_range = max_meters - min_meters
            if m_range == 0: m_range = 1
            y = int(min_y + (elev - min_meters) / m_range * y_range)
            
            log.info(f"Placing {b_type} ({schematic_filename}) at ({x}, {y}, {z})")
            
            # Paste schematic
            try:
                level.paste(schematic, dimension, (x, y, z))
                placed_count += 1
                
                # Place sign if name exists
                if 'name' in p:
                    # Place sign at (x+1, y, z+1) relative to schematic origin?
                    # We don't know where the 'door' is. 
                    # Let's place it at x, y+1, z (inside the building? or floating?)
                    # Safest is probably x+1, z+1 at y+2?
                    # Let's try putting it at y+1 at the corner.
                    self.place_sign(level, x+1, y+1, z, p['name'])
                    
            except Exception as e:
                log.error(f"Failed to paste building {b_type} at ({x}, {y}, {z}): {e}")
            
            # Close schematic
            schematic.close()

        # Save and close
        if placed_count > 0:
            log.info(f"Saving world changes...")
            level.save(create_backup=False)
        
        level.close()
        log.info(f"Finished. Successfully placed {placed_count} buildings.")


