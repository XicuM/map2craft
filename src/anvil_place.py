import sys
import yaml
import json
import math
import logging
from pathlib import Path
import src.anvil_writer as anvil
from amulet import nbt
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s (%(name)s) %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('anvil_place')

class NBTStructureLoader:
    """
    Loader for Minecraft Structure NBT format (.nbt).
    Uses amulet-nbt to read the file, but prepares data for anvil-parser.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.width = 0
        self.height = 0
        self.length = 0
        self.blocks_list = []
        self.palette = []
        self._load()
        
    def _load(self):
        try:
            # Use amulet.nbt (v4/v5 API) as installed
            try:
                from amulet import nbt
            except ImportError:
                log.error("amulet.nbt not found. Please pip install amulet-nbt or amulet.")
                return

            log.info(f"Loading structure: {self.path}")
            
            nbt_data = None
            # Try loading as gzip compressed first
            try:
                with open(self.path, 'rb') as f:
                    nbt_data = nbt.read_nbt(f, compressed=True)
            except:
                # Try uncompressed
                try:
                    with open(self.path, 'rb') as f:
                        nbt_data = nbt.read_nbt(f, compressed=False)
                except Exception as e:
                    log.error(f"Could not load {self.path} with amulet.nbt: {e}")
                    return

            # Access the compound tag - in v4/v5 read_nbt returns NamedTag which has .compound property
            data = nbt_data.compound if hasattr(nbt_data, 'compound') else nbt_data
            
            # Extract dimensions
            # data tags are values
            size_list = data.get('size')
            if size_list:
                self.width = int(size_list[0])
                self.height = int(size_list[1])
                self.length = int(size_list[2])
                self.palette = data.get('palette', [])
                self.blocks_list = data.get('blocks', [])
            else:
                # Check for Sponge/Schematic format
                if 'Width' in data and 'BlockData' in data:
                    self._load_sponge(data)
                    return
                else:
                    raise ValueError("Unknown structure format: missing size/Width or BlockData")
            
            log.info(f"Loaded NBT structure: {self.width}x{self.height}x{self.length}")
            
        except Exception as e:
            log.error(f"Failed to parse structure {self.path}: {e}")
            raise e

    def _load_sponge(self, data):
        """Handle Sponge .schem format"""
        self.width = int(data['Width'])
        self.height = int(data['Height'])
        self.length = int(data['Length'])
        
        # Palette: name -> index
        # We need index -> name for unpacking
        raw_palette = data.get('Palette', {})
        # Create a list where list[index] = name
        # raw_palette values might be IntTags
        max_idx = 0
        if raw_palette:
            max_value_tag = max(raw_palette.values())
            max_idx = int(max_value_tag)
            
        self.palette = ["minecraft:air"] * (max_idx + 1)
        for name, idx in raw_palette.items():
            self.palette[int(idx)] = str(name)
            
        # BlockData: VarInt array
        # Amulet-nbt returns ByteArrayTag, which behaves like bytes/numpy array
        block_data = data['BlockData']
        # Depending on amulet version, could be bytes or numpy array. Ensure bytes.
        if hasattr(block_data, 'tobytes'):
            block_bytes = block_data.tobytes()
        else:
            block_bytes = bytes(block_data)
            
        # Decode VarInts
        block_indices = self._decode_varints(block_bytes)
        
        # Populate blocks_list in NBT format for generic getter
        # Sponge index = (y * Length + z) * Width + x
        self.blocks_list = []
        
        # Optimization: Don't store every air block, or do we need to?
        # NBTStructureLoader stores sparse blocks list usually.
        # But here we have full dense array.
        # We can just store non-air blocks to save memory.
        
        total_blocks = self.width * self.height * self.length
        if len(block_indices) != total_blocks:
            log.warning(f"Sponge block data length mismatch: got {len(block_indices)}, expected {total_blocks}")
            
        log.info(f"Sponge structure loaded. Palette size: {len(self.palette)}. Blocks: {len(block_indices)}. Max index: {max_idx}")
            
        for y in range(self.height):
            for z in range(self.length):
                for x in range(self.width):
                    idx = (y * self.length + z) * self.width + x
                    if idx < len(block_indices):
                        state_id = block_indices[idx]
                        if state_id < len(self.palette):
                            name = self.palette[state_id]
                            if name != "minecraft:air": pass
        
        new_palette = []
        for name_str in self.palette:
            # Parse "minecraft:name[prop=val]"
            if '[' in name_str and name_str.endswith(']'):
                base, props_str = name_str[:-1].split('[', 1)
                props = {}
                for p in props_str.split(','):
                    if '=' in p:
                        k, v = p.split('=', 1)
                        props[k] = v
                new_palette.append({'Name': base, 'Properties': props})
            else:
                new_palette.append({'Name': name_str, 'Properties': {}})
        self.palette = new_palette

        # Now populate blocks
        for y in range(self.height):
            for z in range(self.length):
                for x in range(self.width):
                    idx = (y * self.length + z) * self.width + x
                    if idx < len(block_indices):
                        state_id = block_indices[idx]
                        if state_id < len(self.palette):
                            # Skip air if implicit?
                            # Usually explicit air is 0?
                            # Let's include everything or skip air.
                            if self.palette[state_id]['Name'] == "minecraft:air":
                                continue
                            
                            self.blocks_list.append({
                                'pos': [x, y, z],
                                'state': state_id
                            })

    def _decode_varints(self, data):
        """Decode VarInt byte stream"""
        res = []
        i = 0
        l = len(data)
        while i < l:
            value = 0
            shift = 0
            while True:
                if i >= l: break
                b = data[i]
                i += 1
                value |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            res.append(value)
        return res
            
    def get_blocks(self):
        """
        Generator yielding (x, y, z, block_object)
        """
        for block_data in self.blocks_list:
            pos = block_data['pos']
            x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
            
            state_idx = int(block_data['state'])
            if state_idx >= len(self.palette):
                continue
                
            entry = self.palette[state_idx]
            
            # Get name
            if 'Name' in entry:
                full_name = str(entry['Name']) # e.g. "minecraft:stone"
                if ':' in full_name:
                    namespace, block_id = full_name.split(':', 1)
                else:
                    namespace, block_id = 'minecraft', full_name
            else:
                continue

            # Get properties
            props = {}
            if 'Properties' in entry:
                for k, v in entry['Properties'].items():
                    props[str(k)] = str(v)
            
            try:
                # Convert to NBT Compound
                block_tag = nbt.TAG_Compound()
                block_tag["Name"] = nbt.TAG_String(namespace + ":" + block_id)
                if props:
                    p_tag = nbt.TAG_Compound()
                    for k, v in props.items():
                        p_tag[k] = nbt.TAG_String(str(v))
                    block_tag["Properties"] = p_tag
                
                yield x, y, z, block_tag
            except Exception as e:
                # log.warning(f"Bad block {namespace}:{block_id}: {e}")
                pass

class AnvilPlacer:
    def __init__(self, config_path, placements_path, metadata_path, world_path, config_dict=None):
        self.world_path = Path(world_path)
        self.region_dir = self.world_path / "region"
        
        # Load config
        if config_dict:
            self.config = config_dict
        else:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            
        # Load metadata for elevation
        with open(metadata_path, 'r') as f:
            self.meta = json.load(f)
            
        # Load placements
        with open(placements_path, 'r') as f:
            self.placements_data = yaml.safe_load(f)
            
        # Prepare schema map
        self.schematics = {}
        self.offsets = {} # name -> y_offset
        
        schem_dir = Path(self.config['buildings']['schematics_dir']) # Relative to project root, not script
        # Check if absolute or relative
        if not schem_dir.is_absolute():
            # Assume relative to project root (where script runs or config is)
            # We'll assume CWD is project root
            pass
            
        for b_type in self.config['buildings'].get('types', []):
            name = b_type['name']
            filename = b_type['schematic']
            path = schem_dir / filename
            if path.exists():
                try:
                    self.schematics[name] = NBTStructureLoader(path)
                    self.offsets[name] = int(b_type.get('y_offset', 0))
                except Exception as e:
                    log.error(f"Failed to load schematic for {name}: {e}")
            else:
                log.warning(f"Schematic file not found: {path}")

    def run(self):
        log.info(f"Processing {self.placements_data.get('count', 0)} placements...")
        
        # 1. Group by Region
        region_tasks = {} # (rx, rz) -> list of placements
        
        items = self.placements_data.get('placements', [])
        for item in items:
            px, pz = int(item['x']), int(item['y']) # YAML has x, y (which is Z)
            
            # Calculate Region
            rx = px >> 9
            rz = pz >> 9
            
            key = (rx, rz)
            if key not in region_tasks:
                region_tasks[key] = []
            region_tasks[key].append(item)
            
        log.info(f"Grouped into {len(region_tasks)} regions.")
        
        # 2. Process Regions
        for (rx, rz), tasks in region_tasks.items():
            self.process_region(rx, rz, tasks)
            
    def process_region(self, rx, rz, tasks):
        region_file = self.region_dir / f"r.{rx}.{rz}.mca"
        if not region_file.exists():
            log.warning(f"Region file missing: {region_file}. Skipping {len(tasks)} buildings.")
            return

        log.info(f"Processing Region ({rx}, {rz}) - {len(tasks)} buildings")
        
        try:
            # Create Region object
            region = anvil.Region(str(region_file))
            
            modified = False
            
            for task in tasks:
                b_type = task['type']
                if b_type not in self.schematics:
                    continue
                    
                schematic = self.schematics[b_type]
                
                # Calculate coordinates
                wx = int(task['x'])
                wz = int(task['y']) # y in yaml is Z in world
                
                # Determine Elevation via Ground Sampling
                # We need to load the chunk at wx, wz to find the ground
                cx = wx >> 4
                cz = wz >> 4
                
                # Region local chunk coords
                rcx = cx & 31
                rcz = cz & 31
                
                # Chunk local block coords
                lx = wx & 15
                lz = wz & 15
                
                try:
                    target_chunk = region.get_chunk(rcx, rcz)
                    ground_y = target_chunk.get_highest_block(lx, lz)
                    
                    # Place on top of ground + offset
                    offset = self.offsets.get(b_type, 0)
                    world_y = ground_y + 1 + offset
                    
                    # Fallback if no ground found (void) -> use sea level?
                    if ground_y <= -60:
                        sea_level = self.meta['minecraft']['height_mapping']['sea_level_y']
                        world_y = sea_level + 1
                        
                except Exception as e:
                    log.warning(f"Failed to sample ground for {b_type} at {wx},{wz}: {e}")
                    continue

                # Place blocks
                vals = list(schematic.get_blocks())
                if len(vals) == 0:
                    log.warning(f"No valid blocks found in schematic {b_type}")
                else:
                    log.info(f"Placing {len(vals)} blocks for {b_type} at {wx},{wz} (Ground Y: {ground_y} -> Place Y: {world_y})")

                for sx, sy, sz, block_tag in vals:
                    abs_x = wx + sx
                    abs_y = world_y + sy
                    abs_z = wz + sz
                    
                    try:
                        # Check bounds
                        if abs_y < -64 or abs_y > 319:
                            continue
                            
                        # Get chunk (local region coords)
                        # rx, rz are passed in process_region. 
                        # abs_x >> 9 should equal rx
                        
                        cx = (abs_x >> 4) & 31
                        cz = (abs_z >> 4) & 31
                        
                        chunk = region.get_chunk(cx, cz)
                        
                        # Set block in chunk (chunk local coords)
                        lx = abs_x & 15
                        lz = abs_z & 15
                        
                        chunk.set_block(lx, abs_y, lz, block_tag)
                        modified = True
                        
                    except Exception as e:
                        log.warning(f"Failed to set block at {abs_x},{abs_y},{abs_z}: {e}")
                        pass
            
            if modified:
                # Save region
                region.save()
                log.info(f"Saved region r.{rx}.{rz}.mca")
                
        except Exception as e:
            log.error(f"Error processing region {rx},{rz}: {e}")
            import traceback
            log.error(traceback.format_exc())

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python anvil_place.py <world_dir> <placements_yaml> <metadata_json> <config_yaml>")
        sys.exit(1)
        
    world_dir = sys.argv[1]
    placements = sys.argv[2]
    metadata = sys.argv[3]
    config = sys.argv[4]
    
    placer = AnvilPlacer(config, placements, metadata, world_dir)
    placer.run()
