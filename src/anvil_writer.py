import math
import struct
import time
import zlib
from io import BytesIO
import os
from typing import List, Dict, Tuple, Optional, Set, BinaryIO

from amulet import nbt

# Constants
SECTOR_SIZE = 4096

class BitPacker:
    """
    Handles block state bit-packing for Minecraft 1.16+ (Anvil).
    Block states are packed into a LongArray block_states.
    Indices cannot cross 64-bit boundaries.
    """
    
    @staticmethod
    def pack(indices: List[int], bits_per_block: int) -> nbt.TAG_Long_Array:
        if bits_per_block < 4:
            bits_per_block = 4
            
        blocks_per_long = 64 // bits_per_block
        long_count = math.ceil(len(indices) / blocks_per_long)
        longs = [0] * long_count
        
        current_long_idx = 0
        current_long_val = 0
        blocks_in_current_long = 0
        
        for idx in indices:
            # Shift the index value to its position
            shifted_val = idx << (blocks_in_current_long * bits_per_block)
            current_long_val |= shifted_val
            blocks_in_current_long += 1
            
            # If the long is full (or we can't fit another block), move to next
            if blocks_in_current_long >= blocks_per_long:
                # Handle signed 64-bit integer conversion for NBT
                if current_long_val >= 2**63:
                    current_long_val -= 2**64
                
                longs[current_long_idx] = current_long_val
                current_long_idx += 1
                current_long_val = 0
                blocks_in_current_long = 0
                
        # Handle the last partial long
        if blocks_in_current_long > 0:
            if current_long_val >= 2**63:
                current_long_val -= 2**64
            longs[current_long_idx] = current_long_val
        
        # amulet.nbt TAG_Long_Array usually wraps a numpy array or list
        # We pass the list
        return nbt.TAG_Long_Array(longs)
    
    @staticmethod
    def unpack(longs: List[int], bits_per_block: int, count: int = 4096) -> List[int]:
        """
        Unpacks block states from LongArray.
        """
        if bits_per_block < 4:
            bits_per_block = 4
            
        blocks_per_long = 64 // bits_per_block
        indices = []
        
        current_long_idx = 0
        current_long_val = longs[0] if longs else 0
        blocks_in_current_long = 0
        
        # Handle signed 64-bit to unsigned
        if current_long_val < 0:
            current_long_val += 2**64
            
        for _ in range(count):
            # Extract
            mask = (1 << bits_per_block) - 1
            val = (current_long_val >> (blocks_in_current_long * bits_per_block)) & mask
            indices.append(val)
            
            blocks_in_current_long += 1
            
            # Move to next long if needed
            if blocks_in_current_long >= blocks_per_long:
                current_long_idx += 1
                blocks_in_current_long = 0
                if current_long_idx < len(longs):
                    current_long_val = longs[current_long_idx]
                    if current_long_val < 0:
                        current_long_val += 2**64
                else:
                    current_long_val = 0
                    
        return indices

    @staticmethod
    def min_bits(max_value: int) -> int:
        return max(4, max_value.bit_length())

class Section:
    """
    Represents a 16x16x16 chunk section.
    """
    def __init__(self, y_index: int):
        self.y_index = y_index # Section Y index (0 to 15 for typical world, -4 to 19 for 1.18+)
        self.palette: List[nbt.TAG_Compound] = [
            nbt.TAG_Compound({
                "Name": nbt.TAG_String("minecraft:air")
            })
        ]
        self.palette_map: Dict[str, int] = {"minecraft:air": 0}
        self.blocks = [0] * 4096 # Initialize with air (index 0)
        
    @staticmethod
    def from_nbt(tag: nbt.TAG_Compound) -> 'Section':
        y_index = int(tag["Y"])
        section = Section(y_index)
        
        if "block_states" in tag:
            bs = tag["block_states"]
            if "palette" in bs:
                # Load palette
                section.palette = []
                section.palette_map = {}
                p_list = bs["palette"]
                for i, p_tag in enumerate(p_list):
                    # p_tag is compound
                    section.palette.append(p_tag)
                    
                    name = str(p_tag["Name"])
                    props = ""
                    if "Properties" in p_tag:
                        p_dict = p_tag["Properties"]
                        props = ",".join(f"{k}={p_dict[k]}" for k in sorted(p_dict.keys()))
                    
                    palette_key = f"{name}[{props}]"
                    section.palette_map[palette_key] = i
            
            if "data" in bs:
                # Load block data
                data_longs = bs["data"] # This might be nbt.TAG_Long_Array, assume list-like
                # Convert TAG_Long_Array to list of ints if needed
                if hasattr(data_longs, 'value'): # some libs
                    longs_list = list(data_longs.value)
                else:
                    longs_list = list(data_longs)
                
                bits = BitPacker.min_bits(len(section.palette) - 1)
                section.blocks = BitPacker.unpack(longs_list, bits)
            else:
                # No data means all blocks are index 0 (usually air, if palette[0] is air)
                section.blocks = [0] * 4096
                
        return section
        
    def set_block(self, x: int, y: int, z: int, block_data: nbt.TAG_Compound):
        """
        Set a block at local section coordinates (0-15).
        block_data should be a Compound Tag with "Name" and optionally "Properties".
        """
        name = str(block_data["Name"])
        props = ""
        if "Properties" in block_data:
             p_dict = block_data["Properties"]
             props = ",".join(f"{k}={p_dict[k]}" for k in sorted(p_dict.keys()))
        
        palette_key = f"{name}[{props}]"
        
        if palette_key not in self.palette_map:
            new_index = len(self.palette)
            self.palette.append(block_data)
            self.palette_map[palette_key] = new_index
            index = new_index
        else:
            index = self.palette_map[palette_key]
            
        # flat index = (y * 256) + (z * 16) + x
        flat_index = (y * 256) + (z * 16) + x
        self.blocks[flat_index] = index

    def get_block_id(self, x: int, y: int, z: int) -> int:
        """
        Get palette index of block at local coordinates.
        """
        flat_index = (y * 256) + (z * 16) + x
        return self.blocks[flat_index]


    def to_nbt(self) -> nbt.TAG_Compound:
        tag = nbt.TAG_Compound()
        tag["Y"] = nbt.TAG_Byte(self.y_index)
        
        # Palette
        tag["block_states"] = nbt.TAG_Compound()
        tag["block_states"]["palette"] = nbt.TAG_List(self.palette)
        
        # Data
        # Optimize: if all blocks are 0, we can omit data? Minecraft requires it usually if palette > 1
        if len(self.palette) > 1:
            bits = BitPacker.min_bits(len(self.palette) - 1)
            packed_data = BitPacker.pack(self.blocks, bits)
            tag["block_states"]["data"] = packed_data
        
        return tag

class Chunk:
    """
    Represents a vertical chunk column.
    """
    def __init__(self, x: int, z: int):
        self.x = x
        self.z = z
        self.sections: Dict[int, Section] = {}
        self.data_version = 3465 # 1.20.1
        self.status = "minecraft:full"
        self.other_tags = {} 
        
    def get_section(self, y_idx: int) -> Section:
        if y_idx not in self.sections:
            self.sections[y_idx] = Section(y_idx)
        return self.sections[y_idx]
        
    def set_block(self, x: int, y: int, z: int, block_data: nbt.TAG_Compound):
        """
        x, z are chunk-local (0-15). y is world height.
        """
        section_y = y >> 4
        local_y = y & 15
        
        section = self.get_section(section_y)
        section.set_block(x, local_y, z, block_data)
        
    def get_highest_block(self, x: int, z: int) -> int:
        """
        Finds the Y coordinate of the highest non-air block at chunk-local x, z.
        Returns -64 (or min height) if no blocks found.
        """
        # Iterate sections from top down
        # Standard world height 320 to -64. Sections 19 to -4.
        # We can just iterate keys in reverse order
        sorted_sections = sorted(self.sections.keys(), reverse=True)
        
        for s_idx in sorted_sections:
            section = self.sections[s_idx]
            # Iterate Y in section from 15 down to 0
            for y in range(15, -1, -1):
                block_idx = section.get_block_id(x, y, z)
                
                # Check if air
                # We need to check the palette
                if block_idx < len(section.palette):
                    # Check name
                    block_tag = section.palette[block_idx]
                    name = str(block_tag["Name"])
                    if name != "minecraft:air":
                        # Found ground!
                        return (s_idx * 16) + y
                        
        return -64 # default min

        
    def to_nbt(self) -> nbt.TAG_Compound:
        root = nbt.TAG_Compound()
        root["DataVersion"] = nbt.TAG_Int(self.data_version)
        root["Status"] = nbt.TAG_String(self.status)
        root["xPos"] = nbt.TAG_Int(self.x)
        root["zPos"] = nbt.TAG_Int(self.z)
        root["yPos"] = nbt.TAG_Int(-64) # Typical 1.18+ min height
        
        sections_list = nbt.TAG_List()
        # Sort sections by Y
        for y in sorted(self.sections.keys()):
            sections_list.append(self.sections[y].to_nbt())
        
        root["sections"] = sections_list
        
        # Merge other preserved tags
        for k, v in self.other_tags.items():
            if k not in root:
                root[k] = v
                
        return root

    @staticmethod
    def from_nbt(tag: nbt.TAG_Compound) -> 'Chunk':
        x = int(tag["xPos"])
        z = int(tag["zPos"])
        chunk = Chunk(x, z)
        
        if "DataVersion" in tag:
            chunk.data_version = int(tag["DataVersion"])
        if "Status" in tag:
            chunk.status = str(tag["Status"])
            
        # Parse sections
        if "sections" in tag:
            for section_tag in tag["sections"]:
                if "Y" in section_tag and "block_states" in section_tag:
                    try:
                        section = Section.from_nbt(section_tag)
                        chunk.sections[section.y_index] = section
                    except Exception as e:
                        print(f"Failed to parse section {section_tag.get('Y')}: {e}")
                        # Keep raw if needed? For now we might lose it if we fail to parse.
                        pass
        
        # Save other tags.
        for key in tag:
            if key not in ["DataVersion", "Status", "xPos", "zPos", "yPos", "sections"]:
                chunk.other_tags[key] = tag[key]
                
        return chunk


class Region:
    """
    Handles reading and writing of Anvil .mca files.
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.locations = [0] * 1024
        self.timestamps = [0] * 1024
        self.used_sectors: Set[int] = {0, 1} # Header takes first 2 sectors
        self.chunks: Dict[int, Chunk] = {} # Cached/Loaded chunks
        
        # Open file
        self.file_exists = os.path.exists(file_path)
        if self.file_exists:
            with open(file_path, "rb") as f:
                self._read_header(f)
        
    def _read_header(self, f: BinaryIO):
        f.seek(0)
        loc_data = f.read(4096)
        ts_data = f.read(4096)
        
        for i in range(1024):
            # Location: 3 bytes offset, 1 byte sector count
            off_bytes = loc_data[i*4 : i*4+3]
            sec_count = loc_data[i*4+3]
            offset = int.from_bytes(off_bytes, byteorder='big')
            
            self.locations[i] = (offset << 8) | sec_count
            
            # Mark sectors as used
            if offset > 0 and sec_count > 0:
                for s in range(offset, offset + sec_count):
                    self.used_sectors.add(s)
            
            # Timestamp
            self.timestamps[i] = int.from_bytes(ts_data[i*4 : i*4+4], byteorder='big')
            
    def get_chunk(self, rx: int, rz: int) -> Chunk:
        """
        rx, rz are region-local chunk coordinates (0-31).
        """
        if not (0 <= rx < 32 and 0 <= rz < 32):
            raise ValueError(f"Chunk coords out of range: {rx}, {rz}")
        
        index = (rx & 31) + (rz & 31) * 32
        
        # Check cache
        if index in self.chunks:
            return self.chunks[index]
        
        # Load from file
        offset_info = self.locations[index]
        offset = offset_info >> 8
        sector_count = offset_info & 0xFF
        
        if offset == 0 or not self.file_exists:
            # New chunk
             # We need absolute coordinates? 
             # We can't know absolute without region x/z passed to Region init?
             # For now, just use local placeholders, caller might fix?
            chunk = Chunk(rx, rz)
            self.chunks[index] = chunk
            return chunk
            
        with open(self.file_path, "rb") as f:
            f.seek(offset * SECTOR_SIZE)
            # Read length (4 bytes) and compression type (1 byte)
            length_data = f.read(5)
            length = int.from_bytes(length_data[0:4], byteorder='big')
            compression = length_data[4]
            
            compressed_data = f.read(length - 1)
            
            if compression == 2: # Zlib
                data = zlib.decompress(compressed_data)
            elif compression == 1: # Gzip (unused usually)
                import gzip
                data = gzip.decompress(compressed_data)
            else:
                raise ValueError(f"Unknown compression: {compression}")
                

            # Use amulet.nbt to parse raw bytes? 
            # library doesn't have from_buffer?
            # We can wrap in BytesIO and use load
            # Amulet's load takes a file path or file-like object?
            
            # Amulet NBT load is: amulet.nbt.load(file, compressed=True/False)
            # Here 'data' is already decompressed NBT.
            # So duplicate parsing? 
            # Actually load() expects headers if compressed=True.
            
            # Correct approach with amulet.nbt:
            # It provides read_nbt. 
            pass
            
            # Let's try to parse the buffer
            # Since we decompressed it, it's raw NBT data (Compound tag)
            # We can use our own simple parser or reuse library if exposed.
            # amulet.nbt.read_nbt works on file object.
            
            with BytesIO(data) as bio:
                tag = nbt.read_nbt(bio, compressed=False, little_endian=False)
                
                # Amulet NBT often returns a NamedTag (wrapper)
                # We need the inner CompoundTag for dictionary access
                chunk_data = tag
                if isinstance(tag, nbt.NamedTag):
                    # NamedTag usually has .compound or .tag property depending on version/payload
                    if hasattr(tag, 'compound'): # Ideally check payload type first?
                         # Accessing .compound on NamedTag usually returns the raw python dict or the Tag?
                         # Let's inspect_log said 'compound' is a property.
                         # Assuming it returns ANYNBT or specifically CompoundTag
                         chunk_data = tag.compound 
                    elif hasattr(tag, 'tag'):
                         chunk_data = tag.tag
                
                # Double check: if still NamedTag (nested?), unwrap again?
                if isinstance(chunk_data, nbt.NamedTag):
                     if hasattr(chunk_data, 'tag'):
                         chunk_data = chunk_data.tag

                # Verify it is CompoundTag
                if not isinstance(chunk_data, nbt.TAG_Compound):
                     # Last ditch: maybe it IS the dict/compound itself?
                     # amulet v1/v2 diffs.
                     pass 

                # print(f"DEBUG: Loaded chunk type: {type(chunk_data)}")
                
                if not isinstance(chunk_data, nbt.TAG_Compound):
                     # If it's still not a compound, we can't use it as one.
                     # Raise error or try to continue if it behaves like dict (which TAG_Compound does)
                     if not hasattr(chunk_data, 'keys'):
                         raise TypeError(f"Expected TAG_Compound or dict-like, got {type(chunk_data)}")

                chunk = Chunk.from_nbt(chunk_data)
                self.chunks[index] = chunk
                return chunk

    def save(self):
        """
        Writes all cached/modified chunks to disk and updates headers.
        """
        # Determine strict write mode: 
        # If we modify file, we should probably rewrite it or append carefully.
        # Safe approach: Read entire file into memory (sectors), update chunks, write back.
        # Or: Append new chunks at end, update header. 
        # Fragmentation is okay for now.
        
        # We need to keep existing data? Yes.
        # If 'file_exists', we open in r+b.
        
        mode = "r+b" if self.file_exists else "wb"
        # If wb, make sure to init file with 8KB zeros
        
        if not self.file_exists:
            with open(self.file_path, "wb") as f:
                f.write(b'\x00' * 8192)
            mode = "r+b"
            
        with open(self.file_path, mode) as f:
            # Write cached chunks
            for index, chunk in self.chunks.items():
                # Serialize
                tag = chunk.to_nbt()
                
                # Write to buffer
                bio = BytesIO()
                tag.save_to(bio, compressed=False, little_endian=False) # Write raw NBT
                raw_data = bio.getvalue()
                
                # Compress
                compressed_data = zlib.compress(raw_data)
                
                # Payload: Length (4) + Compression (1) + Data
                payload_len = len(compressed_data) + 1
                header = payload_len.to_bytes(4, byteorder='big') + b'\x02'
                payload = header + compressed_data
                
                # Calculate required sectors
                total_len = len(payload)
                sectors_needed = (total_len + SECTOR_SIZE - 1) // SECTOR_SIZE
                
                # Find space
                # Simple allocator: Just append to end of file for now?
                # Or reuse if it fits in old spot?
                # If we read the existing header, we know where it was.
                # If it fits in old sectors, use them.
                
                old_offset_info = self.locations[index]
                old_offset = old_offset_info >> 8
                old_sector_count = old_offset_info & 0xFF
                
                new_offset = 0
                
                if old_offset > 0 and old_sector_count >= sectors_needed:
                    # Fits in old spot
                    new_offset = old_offset
                    # We don't shrink sector usage in header usually, to avoid fragmentation?
                    # Or we just write fewer? 
                    # Standard behavior: Write to old spot.
                else:
                    # Append to end of file
                    f.seek(0, 2) # Seek end
                    file_end = f.tell()
                    
                    # Align to sector
                    if file_end % SECTOR_SIZE != 0:
                        pad = SECTOR_SIZE - (file_end % SECTOR_SIZE)
                        f.write(b'\x00' * pad)
                        file_end += pad
                        
                    new_offset = file_end // SECTOR_SIZE
                    
                    # Mark used (update local allocator if we were tracking it properly)
                    # For simple append, we just go.
                    
                # Write payload
                f.seek(new_offset * SECTOR_SIZE)
                f.write(payload)
                
                # Pad sector
                bytes_written = len(payload)
                padding = (SECTOR_SIZE - (bytes_written % SECTOR_SIZE)) % SECTOR_SIZE
                if padding > 0:
                    f.write(b'\x00' * padding)
                
                # Update location table in memory
                self.locations[index] = (new_offset << 8) | sectors_needed
                self.timestamps[index] = int(time.time())
                
            # Write header tables
            f.seek(0)
            
            loc_bytes = bytearray()
            for val in self.locations:
                loc_bytes.extend(val.to_bytes(4, byteorder='big'))
            f.write(loc_bytes)
            
            ts_bytes = bytearray()
            for val in self.timestamps:
                ts_bytes.extend(val.to_bytes(4, byteorder='big'))
            f.write(ts_bytes)

