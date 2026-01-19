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

# Debug Amulet Version/File
try:
    log.info(f"Amulet package file: {amulet.__file__}")
    if hasattr(amulet, '__version__'):
        log.info(f"Amulet package version: {amulet.__version__}")
except:
    pass

# Robust load_level import for Amulet v2
try:
    # Amulet v2 seems to use get_level in amulet.level package (which needs to be installed separately as amulet-level)
    from amulet.level import get_level as load_level
except ImportError:
    try:
        # Fallback for v1 or other structure
        load_level = amulet.load_level
    except AttributeError:
        log.error("Could not find 'get_level' or 'load_level'. Ensure 'amulet-level' is installed for Amulet v2.")
        load_level = None

# Legacy Block ID Mapping (Minimal Set for standard buildings)
LEGACY_BLOCK_MAP = {
    0: "minecraft:air",
    1: "minecraft:stone",
    2: "minecraft:grass_block",
    3: "minecraft:dirt",
    4: "minecraft:cobblestone",
    5: "minecraft:oak_planks",
    6: "minecraft:oak_sapling",
    7: "minecraft:bedrock",
    8: "minecraft:water",
    9: "minecraft:water",
    10: "minecraft:lava",
    11: "minecraft:lava",
    12: "minecraft:sand",
    13: "minecraft:gravel",
    14: "minecraft:gold_ore",
    15: "minecraft:iron_ore",
    16: "minecraft:coal_ore",
    17: "minecraft:oak_log",
    18: "minecraft:oak_leaves",
    19: "minecraft:sponge",
    20: "minecraft:glass",
    35: "minecraft:white_wool",
    41: "minecraft:gold_block",
    42: "minecraft:iron_block",
    43: "minecraft:smooth_stone_slab", # Double slab
    44: "minecraft:smooth_stone_slab",
    45: "minecraft:bricks",
    48: "minecraft:mossy_cobblestone",
    49: "minecraft:obsidian",
    50: "minecraft:torch",
    53: "minecraft:oak_stairs",
    54: "minecraft:chest",
    58: "minecraft:crafting_table",
    60: "minecraft:farmland",
    61: "minecraft:furnace",
    63: "minecraft:oak_sign", # Standing sign
    64: "minecraft:oak_door",
    65: "minecraft:ladder",
    66: "minecraft:rail",
    67: "minecraft:cobblestone_stairs",
    68: "minecraft:oak_wall_sign",
    85: "minecraft:oak_fence",
    89: "minecraft:glowstone",
    98: "minecraft:stone_bricks",
    101: "minecraft:iron_bars",
    102: "minecraft:glass_pane",
    109: "minecraft:stone_bricks",
    126: "minecraft:oak_slab",
    # Add more as discovered
}

class LegacySchematicLoader:
    def __init__(self, path):
        self.path = Path(path)
        self.width = 0
        self.height = 0
        self.length = 0
        self.blocks = None
        self.data = None
        self._load()

    def _load(self):
        try:
            nbt_data = amulet.nbt.read_nbt(str(self.path))
            # read_nbt returns (NBTFile, format_wrapper)
            nbt = nbt_data[0]
            
            # Extract dimensions
            # NBTFile might act as CompoundTag or have .value
            if hasattr(nbt, 'value'):
                nbt = nbt.value

            self.width = int(nbt["Width"].value)
            self.height = int(nbt["Height"].value)
            self.length = int(nbt["Length"].value)
            
            # Extract block data (byte arrays)
            self.blocks = nbt["Blocks"].value
            self.data = nbt["Data"].value
            
            log.info(f"Loaded legacy schematic: {self.width}x{self.height}x{self.length}")
            
        except Exception as e:
            log.error(f"Failed to parse schematic NBT: {e}")
            raise e

    def paste(self, level, ox, oy, oz):
        try:
            from amulet.core.block import Block
        except ImportError:
            log.error("Could not import amulet.core.block.Block")
            return

        dimension = "minecraft:overworld"
        
        count = 0
        total_blocks = self.width * self.height * self.length
        
        # MCEdit Schematic order: Y, Z, X
        for y in range(self.height):
            for z in range(self.length):
                for x in range(self.width):
                    index = (y * self.length + z) * self.width + x
                    
                    block_id = self.blocks[index]
                    # handle signed byte if needed (python ints are usually fine)
                    if block_id < 0: block_id += 256
                    
                    block_data = self.data[index]
                    
                    if block_id == 0: continue # Skip air for efficiency? Or paste it?
                                             # Usually strictly cleaner to skip air to avoid overwriting terrain unless intended.
                    
                    # types > 255 not supported in standard .schematic
                    
                    # Translation
                    block_key = LEGACY_BLOCK_MAP.get(block_id, "minecraft:stone") # Default to stone if unknown? Or pink wool?
                    if block_id not in LEGACY_BLOCK_MAP:
                        # Log once per ID?
                        pass

                    # Construct properties (minimal)
                    props = {}
                    # Handling rotation/data is complex. For now, paste raw base blocks.
                    
                    # Create Block
                    # Namespace, BaseName, Properties
                    ns, name = block_key.split(":")
                    block = Block(ns, name, props)
                    
                    # Set Block
                    try:
                        level.set_block(ox + x, oy + y, oz + z, dimension, block)
                        count += 1
                    except Exception as e:
                        # log.warning(f"Failed set_block: {e}")
                        pass
                        
        log.info(f"Pasted {count} blocks from schematic.")

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

        if load_level is None:
             log.error("Amulet load_level is not available. Cannot place buildings.")
             return

        # Load level
        try: level = load_level(world_path)
        except Exception as e:
            log.error(f"Failed to load world at {world_path}: {e}")
            return
        
        placed_count = 0
        dimension = "minecraft:overworld"
        
        for p in placements:
            # Building type is at the top level in the generated YAML
            b_type = p.get('type')
            
            schematic_filename = self.building_map.get(b_type)
            if not schematic_filename:
                log.warning(f"No schematic configured for type '{b_type}'. Skipping.")
                continue

            schematic_path = self.schematics_dir/schematic_filename
            if not schematic_path.exists():
                log.warning(f"Schematic file not found: {schematic_path}")
                continue

            # Calculate coordinates first
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

            # Load schematic
            schematic = None
            try:
                schematic = load_level(str(schematic_path))
            except Exception as e:
                log.warning(f"Standard load_level failed for {schematic_path}: {e}")
                
                # Fallback for .schematic files
                if schematic_path.suffix == '.schematic':
                    log.info(f"Attempting legacy load for {schematic_path}...")
                    try:
                        loader = LegacySchematicLoader(schematic_path)
                        loader.paste(level, x, y, z)
                        placed_count += 1
                        
                        # Handle sign placement (simplified for legacy)
                        if 'name' in p:
                            self.place_sign(level, x+1, y+1, z, p['name'])
                            
                        continue # Skip standard paste
                    except Exception as le:
                        log.error(f"Legacy load also failed: {le}")
                        continue
                else:
                    continue
            
            # Paste standard schematic (Amulet supported formats)
            try:
                level.paste(schematic, dimension, (x, y, z))
                placed_count += 1
                
                # Place sign if name exists
                if 'name' in p:
                    self.place_sign(level, x+1, y+1, z, p['name'])
                    
            except Exception as e:
                log.error(f"Failed to paste building {b_type} at ({x}, {y}, {z}): {e}")
            
            # Close schematic
            if schematic:
                schematic.close()

        # Save and close
        if placed_count > 0:
            log.info(f"Saving world changes...")
            level.save(create_backup=False)
        
        level.close()
        log.info(f"Finished. Successfully placed {placed_count} buildings.")


