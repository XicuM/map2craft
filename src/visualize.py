"""
Visualization tools for map2craft.
Generate preview images for terrain, biomes, and land cover.
"""

import os
import logging
import json
import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from typing import Dict, Tuple, Optional

log = logging.getLogger(__name__)

# Minecraft biome colors (approximate)
BIOME_COLORS = {
    0: (0, 0, 112),      # Ocean - dark blue
    1: (141, 179, 96),   # Plains - light green
    4: (5, 102, 33),     # Forest - dark green
    5: (11, 102, 89),    # Taiga - teal
    6: (7, 249, 178),    # Swamp - cyan-green
    7: (0, 0, 255),      # River - blue
    16: (250, 222, 85),  # Beach - sand yellow
    24: (0, 0, 80),      # Deep Ocean - very dark blue
    25: (162, 162, 132), # Stone Shore - gray
    35: (189, 178, 95),  # Savanna - tan
    37: (217, 69, 21),   # Badlands - orange-red
    45: (0, 119, 190),   # Lukewarm Ocean - lighter blue
}

# ESA WorldCover colors (official)
LAND_COVER_COLORS = {
    10: (0, 100, 0),     # Tree cover - dark green
    20: (255, 187, 34),  # Shrubland - orange
    30: (255, 255, 76),  # Grassland - yellow
    40: (240, 150, 255), # Cropland - pink
    50: (250, 0, 0),     # Built-up - red
    60: (180, 180, 180), # Bare/sparse - gray
    70: (240, 240, 240), # Snow and ice - white
    80: (0, 100, 200),   # Water - blue
    90: (0, 150, 160),   # Wetland - teal
    95: (0, 207, 117),   # Mangroves - bright green
    100: (250, 230, 160),# Moss and lichen - beige
    0: (0, 0, 0),        # No data - black
}

LAND_COVER_NAMES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
    0: "No data",
}

BIOME_NAMES = {
    0: "Ocean",
    1: "Plains",
    4: "Forest",
    5: "Taiga",
    6: "Swamp",
    7: "River",
    16: "Beach",
    24: "Deep Ocean",
    25: "Stone Shore",
    35: "Savanna",
    37: "Badlands",
    45: "Lukewarm Ocean",
}


class MapVisualizer:
    def __init__(self, config=None):
        self.config = config or {}

    def colorize_array(self, data: np.ndarray, color_map: Dict[int, Tuple[int, int, int]]) -> np.ndarray:
        ''' Convert classified data to RGB image using color map.
        
            :param np.ndarray data: 2D array of class IDs
            :param dict color_map: Dictionary mapping class ID to (R, G, B) tuple
            
            :return: RGB image array (H, W, 3)
        '''
        height, width = data.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        
        for class_id, color in color_map.items():
            mask = data == class_id
            rgb[mask] = color
        
        return rgb


    def _normalize_color(self, color):
        """Convert 0-255 RGB tuple to 0-1 RGB tuple."""
        return (color[0]/255, color[1]/255, color[2]/255)

    def _save_plot(self, output_file: str, title: str):
        """Helper to save the current matplotlib figure."""
        plt.title(title)
        plt.axis('off')
        plt.tight_layout()
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()

    def visualize_biomes(self, biome_map_file: str, output_file: str) -> None:
        ''' Create a visualization of the biome map using matplotlib.
        
            :param str biome_map_file: Path to biome map GeoTIFF
            :param str output_file: Path to save visualization PNG
        '''
        log.info("Generating biome visualization...")
        
        with rasterio.open(biome_map_file) as src:
            biome_data = src.read(1)
        
        # Colorize biome map
        rgb = self.colorize_array(biome_data, BIOME_COLORS)
        
        # Plot
        plt.figure(figsize=(16, 12), dpi=150)
        plt.imshow(rgb, interpolation='nearest')
        
        # Legend
        unique_biomes = np.unique(biome_data)
        handles = []
        for bid in sorted(unique_biomes):
            if bid in BIOME_COLORS:
                color = self._normalize_color(BIOME_COLORS[bid])
                name = BIOME_NAMES.get(bid, f"Biome {bid}")
                handles.append(Patch(color=color, label=name))
        
        if handles:
            plt.legend(handles=handles, loc='center left', bbox_to_anchor=(1, 0.5), 
                      title='Biome Types', framealpha=0.9)

        self._save_plot(output_file, f'Biome Map: {self.config["project"]["name"]}')
        
        log.info(f"[✓] Biome visualization saved: {output_file}")


    def visualize_land_cover(self, land_cover_file: str, output_file: str) -> None:
        ''' Create a visualization of the land cover map using matplotlib.
        
            :param str land_cover_file: Path to land cover GeoTIFF
            :param str output_file: Path to save visualization PNG
        '''
        log.info("Generating land cover visualization...")
        
        with rasterio.open(land_cover_file) as src:
            land_cover_data = src.read(1)
        
        # Colorize land cover map
        rgb = self.colorize_array(land_cover_data, LAND_COVER_COLORS)
        
        # Plot
        plt.figure(figsize=(16, 12), dpi=150)
        plt.imshow(rgb, interpolation='nearest')
        
        # Legend
        unique_classes = np.unique(land_cover_data)
        handles = []
        for cid in sorted(unique_classes):
            if cid in LAND_COVER_COLORS:
                color = self._normalize_color(LAND_COVER_COLORS[cid])
                name = LAND_COVER_NAMES.get(cid, f"Class {cid}")
                handles.append(Patch(color=color, label=name))
        
        if handles:
            plt.legend(handles=handles, loc='center left', bbox_to_anchor=(1, 0.5), 
                      title='Land Cover Classes', framealpha=0.9)
            
        self._save_plot(output_file, f'Land Cover: {self.config["project"]["name"]}')
        
        log.info(f"[✓] Land cover visualization saved: {output_file}")


    def visualize_terrain(self, elevation_file: str, output_file: str, 
                        water_mask_file: Optional[str] = None,
                        road_mask_file: Optional[str] = None,
                        biome_map_file: Optional[str] = None) -> None:
        ''' Create a terrain visualization with optional overlays using matplotlib.
        
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save visualization PNG
            :param str water_mask_file: Optional path to water mask
            :param str road_mask_file: Optional path to road mask
            :param str biome_map_file: Optional path to biome map for overlay
        '''
        log.info("Generating terrain visualization...")
        
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1)
        
        # Normalize elevation for display
        elev_min, elev_max = elevation.min(), elevation.max()
        if elev_max > elev_min:
            elev_normalized = (elevation - elev_min) / (elev_max - elev_min)
        else:
            elev_normalized = np.zeros_like(elevation, dtype=np.float32)
        
        # Convert to RGB (grayscale)
        rgb = np.stack([elev_normalized] * 3, axis=-1)
        
        # Apply water mask if available
        if water_mask_file and os.path.exists(water_mask_file):
            water_mask = np.array(Image.open(water_mask_file))
            if water_mask.shape == elevation.shape:
                water_pixels = water_mask > 128
                
                # Bathymetry Visualization
                water_elev = elevation[water_pixels]
                if water_elev.size > 0:
                    w_min, w_max = water_elev.min(), water_elev.max()
                    if w_max > w_min:
                        # Normalize depth: 0 = deepest, 1 = shallowest
                        w_norm = (water_elev - w_min) / (w_max - w_min)
                    else:
                        w_norm = np.ones_like(water_elev, dtype=np.float32)
                    
                    # Gradient: Dark Blue (Deep) -> Lighter Blue (Shallow)
                    # Deep: (0, 20, 60) -> (0.0, 0.08, 0.24)
                    # Shallow: (0, 100, 200) -> (0.0, 0.39, 0.78)
                    deep_color = np.array([0.0, 0.08, 0.24])
                    shallow_color = np.array([0.0, 0.39, 0.78])
                    
                    # Interpolate
                    # w_norm needs to be broadcast to (N, 3) 
                    # shape: (N, 1) * (1, 3) + (N, 1) * (1, 3)
                    w_norm_expanded = w_norm[:, np.newaxis]
                    water_colors = (1.0 - w_norm_expanded) * deep_color + w_norm_expanded * shallow_color
                    
                    rgb[water_pixels] = water_colors
                else:
                    rgb[water_pixels] = [0.0, 0.39, 0.78]
        
        # Apply road mask if available
        if road_mask_file and os.path.exists(road_mask_file):
            try:
                if road_mask_file.lower().endswith('.tif'):
                    with rasterio.open(road_mask_file) as rsrc:
                        road_mask = rsrc.read(1)
                else:
                    road_mask = np.array(Image.open(road_mask_file))
                
                if road_mask.shape == elevation.shape:
                    road_pixels = road_mask > 0
                    rgb[road_pixels] = [1.0, 0.55, 0.0] # Orange (255, 140, 0) normalized
            except Exception as e:
                log.warning(f"Could not apply road mask: {e}")

        # Plot
        plt.figure(figsize=(16, 12), dpi=150)
        plt.imshow(rgb, interpolation='nearest') # RGB is floats 0-1
        
        self._save_plot(output_file, f'Terrain: {self.config["project"]["name"]}')
        
        log.info(f"[✓] Terrain visualization saved: {output_file}")

    def visualize_building_placements(self, placements_file: str, output_file: str,
                                      heightmap_file: str = None,
                                      water_mask_file: str = None) -> None:
        ''' Create a visualization of building placements overlaid on terrain.
        
            :param str placements_file: Path to building_placements.json
            :param str output_file: Path to save visualization PNG
            :param str heightmap_file: Optional heightmap for terrain background
            :param str water_mask_file: Optional water mask for context
        '''
        log.info("Generating building placement visualization...")
        
        # Load building placements
        try:
            with open(placements_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            placements = data.get('placements', [])
            building_count = data.get('count', len(placements))
        except Exception as e:
            log.error(f"Failed to load building placements: {e}")
            return
        
        if not placements:
            log.warning("No building placements found")
            return
        
        # Create base visualization
        if heightmap_file and os.path.exists(heightmap_file):
            # Use heightmap as background
            heightmap = np.array(Image.open(heightmap_file), dtype=np.uint16)
            height, width = heightmap.shape
            
            # Normalize heightmap to 0-1
            h_min, h_max = heightmap.min(), heightmap.max()
            if h_max > h_min:
                normalized = (heightmap - h_min) / (h_max - h_min)
            else:
                normalized = np.zeros_like(heightmap, dtype=np.float32)
            
            # Convert to grayscale RGB
            rgb = np.stack([normalized] * 3, axis=-1)
            
            # Apply water mask if available
            if water_mask_file and os.path.exists(water_mask_file):
                try:
                    water_mask = np.array(Image.open(water_mask_file))
                    if water_mask.shape == heightmap.shape:
                        water_pixels = water_mask > 128
                        # Light blue for water
                        rgb[water_pixels] = [0.7, 0.85, 1.0]
                except Exception as e:
                    log.warning(f"Could not apply water mask: {e}")
        else:
            # Create blank canvas based on first placement
            height = width = 1000  # Default size
            rgb = np.ones((height, width, 3), dtype=np.float32) * 0.9
        
        # Plot
        fig, ax = plt.subplots(figsize=(16, 12), dpi=150)
        ax.imshow(rgb, interpolation='nearest')
        
        # Define mapping for building types (color, marker)
        # Markers: o (circle), s (square), ^ (triangle), D (diamond), * (star), P (plus)
        TYPE_STYLES = {
            'cathedral': ('purple', 'P'),
            'church': ('blue', 's'),
            'lighthouse': ('yellow', 'D'),
            'windmill': ('orange', '^'),
            'tower': ('green', 'o'),
            'well': ('cyan', '*'),
            'building': ('red', 'o') # Default
        }
        DEFAULT_STYLE = ('red', 'o')

        # Group coordinates by type
        typed_coords = {} # type -> (x_list, y_list)
        
        for placement in placements:
            x = placement.get('pixel_x')
            y = placement.get('pixel_y')
            if x is None or y is None: continue
            
            # Check bounds
            if not (0 <= x < width and 0 <= y < height): continue
                
            # Determine type
            props = placement.get('properties', {})
            b_type = props.get('building', 'building')
            
            # If the primary building tag is generic, look for more specific tags in properties
            if b_type in ['yes', 'building', 'true']:
                # Order of priority for landmark identification
                for tag_key in ['man_made', 'historic', 'amenity', 'tourism']:
                    val = props.get(tag_key)
                    if val and val != 'yes':
                        b_type = val
                        break

            if b_type not in TYPE_STYLES:
                # Check if it matches any known types as a fallback
                found = False
                for kt in TYPE_STYLES:
                    if kt in b_type.lower():
                        b_type = kt
                        found = True
                        break
                if not found: b_type = 'building'

            if b_type not in typed_coords: typed_coords[b_type] = ([], [])
            typed_coords[b_type][0].append(x)
            typed_coords[b_type][1].append(y)
        
        # Plot each group
        if typed_coords:
            for b_type, (xs, ys) in typed_coords.items():
                color, marker = TYPE_STYLES.get(b_type, DEFAULT_STYLE)
                ax.scatter(xs, ys, c=color, marker=marker, s=40, alpha=0.9, 
                          label=f'{b_type.capitalize()} ({len(xs)})', 
                          edgecolors='black', linewidths=0.5)
            
            # Add legend
            ax.legend(loc='upper right', fontsize=10, framealpha=0.9, title="Building Types")
            log.info(f"Plotted buildings for types: {', '.join(typed_coords.keys())}")
        
        else: log.warning("No valid building coordinates to plot")
        
        # Title and formatting
        ax.set_title(
            f'Building Placements: {self.config["project"]["name"]} ({building_count} total)', 
            fontsize=14, fontweight='bold'
        )
        ax.axis('off')
        
        # Save
        plt.tight_layout()
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()
        
        log.info(f"[✓] Building placement visualization saved: {output_file}")

    def biome_viz_action(self, target, source, env):
        self.visualize_biomes(str(source[0]), str(target[0]))
        return None

    def land_cover_viz_action(self, target, source, env):
        self.visualize_land_cover(str(source[0]), str(target[0]))
        return None

    def terrain_viz_action(self, target, source, env):
        elev = str(source[0])
        water = str(source[1]) if len(source) > 1 else None
        road = str(source[2]) if len(source) > 2 else None
        
        # Filter out script files passed as dependencies
        if water and water.endswith('.py'): water = None
        if road and road.endswith('.py'): road = None
            
        self.visualize_terrain(elev, str(target[0]), water_mask_file=water, road_mask_file=road)
        return None

    def visualize_terrain_types(
        self,
        heightmap_file: str,
        output_file: str,
        metadata_file: str,
        water_mask_file: str = None,
        biome_map_file: str = None,
        road_mask_file: str = None,
        steep_slopes_mask_file: str = None
    ) -> None:
        ''' Create terrain type classification visualization.
        
            :param str heightmap_file: Path to heightmap PNG
            :param str output_file: Path to save visualization PNG
            :param str metadata_file: Path to metadata JSON
            :param str water_mask_file: Optional path to water mask
            :param str biome_map_file: Optional path to biome map
            :param str road_mask_file: Optional path to road mask
            :param str steep_slopes_mask_file: Optional path to steep slopes mask
        '''
        log.info("Generating terrain type visualization...")

        # Terrain definitions
        TERRAIN_COLORS = [
            '#afafaf',  # 0: Gravel Ocean Floor
            '#d4c4a0',  # 1: Sandy Ocean Floor
            '#88be63',  # 2: Grass
            '#7a7a7a',  # 3: Stone (Steep Slopes)
            '#e8d4a0',  # 4: Beach Sand
            '#c86428',  # 5: Badlands
            '#8b6a47'   # 6: Dirt Path (Roads)
        ]
        TERRAIN_NAMES = ['Gravel Ocean Floor', 'Sandy Ocean Floor', 'Grass', 
                        'Stone (Steep Slopes)', 'Beach Sand', 'Badlands', 'Dirt Path (Roads)']

        # Helper to load mask
        def _load_mask(path: str) -> np.ndarray:
            if not path or path == 'None' or not os.path.exists(path):
                return None
            try:
                if path.lower().endswith('.tif'):
                    with rasterio.open(path) as src:
                        return src.read(1)
                else:
                    return np.array(Image.open(path))
            except Exception as e:
                log.warning(f"Could not load mask {path}: {e}")
                return None

        # Load inputs
        try:
            heightmap = np.array(Image.open(heightmap_file), dtype=np.uint16)
        except Exception as e:
            log.error(f"Failed to load heightmap {heightmap_file}: {e}")
            return

        water_mask = _load_mask(water_mask_file)
        road_mask = _load_mask(road_mask_file)
        biome_map = _load_mask(biome_map_file)
        steep_slopes_mask = _load_mask(steep_slopes_mask_file)
        
        # Get sea level
        sea_level_value = 0
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            min_elev = float(meta['terrain']['elevation']['min_meters'])
            max_elev = float(meta['terrain']['elevation']['max_meters'])
            sea_level_m = float(meta['terrain'].get('sea_level_meters', 0.0))
            if max_elev > min_elev:
                sea_level_value = int(round((sea_level_m - min_elev) / (max_elev - min_elev) * 65535))
        except Exception:
            pass

        # Build terrain map
        terrain = np.zeros(heightmap.shape, dtype=np.uint8)
        
        # Base classification (Land vs Ocean)
        if water_mask is not None:
            is_water = water_mask > 127
            depth_delta = 5000
            deep_thresh = max(0, sea_level_value - depth_delta)
            
            terrain[is_water & (heightmap < deep_thresh)] = 0  # Gravel
            terrain[is_water & (heightmap >= deep_thresh)] = 1  # Sand
            terrain[~is_water] = 2  # Grass
        else:
            terrain[:] = 2

        # Extract masks from biome map if available
        # Biome IDs: Beach=16, Stone Shore=25, Badlands=37
        beach_mask = (biome_map == 16) if biome_map is not None else None
        badlands_mask = (biome_map == 37) if biome_map is not None else None
        
        # Stone shore from biome map is valid too, combine it with explicit steep slopes
        stone_shore_mask = (biome_map == 25) if biome_map is not None else None

        # Overlays
        for mask, tid, thresh in [
            (stone_shore_mask, 3, 0), # Stone shore from biomes (binary)
            (steep_slopes_mask, 3, 150), # Explicit slope gradient (needs threshold ~35 deg)
            (beach_mask, 4, 0),
            (badlands_mask, 5, 0),
            (road_mask, 6, 0)
        ]:
            if mask is not None:
                # Resize if necessary
                if mask.shape != terrain.shape:
                     continue
                terrain[mask > thresh] = tid

        # Log distribution
        unique, counts = np.unique(terrain, return_counts=True)
        total_pixels = terrain.size
        log.info("Terrain Type Distribution:")
        for tid, count in zip(unique, counts):
            name = TERRAIN_NAMES[tid] if tid < len(TERRAIN_NAMES) else f"Unknown ({tid})"
            percent = (count / total_pixels) * 100
            log.info(f"  {tid}: {name} - {percent:.2f}%")

        # Plot
        fig, ax = plt.subplots(figsize=(16, 12), dpi=150)
        im = ax.imshow(terrain, cmap=ListedColormap(TERRAIN_COLORS), vmin=0, vmax=6, interpolation='nearest')
        
        # Legend
        handles = [Patch(color=TERRAIN_COLORS[i], label=TERRAIN_NAMES[i]) for i in range(len(TERRAIN_COLORS))]
        ax.legend(handles=handles, loc='lower left', fontsize=10, title='Terrain Types', framealpha=0.9)
        ax.set_title(f'Terrain Types Analysis: {self.config["project"]["name"]}')
        ax.axis('off')

        plt.tight_layout()
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()
        log.info(f"[✓] Terrain type visualization saved: {output_file}")


    def terrain_types_viz_action(self, target, source, env):
        # source: heightmap, water, biome_map, road, metadata, steep_slopes
        if len(source) < 6:
             pass
             
        heightmap = str(source[0])
        water = str(source[1])
        biome = str(source[2])
        road_mask = str(source[3])
        meta = str(source[4])
        steep = str(source[5]) if len(source) > 5 else None
        
        self.visualize_terrain_types(
            heightmap_file=heightmap,
            output_file=str(target[0]),
            metadata_file=meta,
            water_mask_file=water,
            biome_map_file=biome,
            road_mask_file=road_mask,
            steep_slopes_mask_file=steep
        )
        return None

    def building_viz_action(self, target, source, env):
        ''' SCons action for building placement visualization.
            source: building_placements.json, heightmap, water_mask
        '''
        placements = str(source[0])
        heightmap = str(source[1]) if len(source) > 1 else None
        water = str(source[2]) if len(source) > 2 else None
        
        # Filter out script files
        if heightmap and heightmap.endswith('.py'): heightmap = None
        if water and water.endswith('.py'): water = None
        
        self.visualize_building_placements(
            placements_file=placements,
            output_file=str(target[0]),
            heightmap_file=heightmap,
            water_mask_file=water
        )
        return None


