import logging
import json
import yaml
import numpy as np
import rasterio
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from typing import Dict, Tuple, Optional
from src.constants import (
    BIOME_COLORS, BIOME_NAMES, LAND_COVER_COLORS, LAND_COVER_NAMES,
    TERRAIN_COLORS, TERRAIN_NAMES_LIST, BUILDING_TYPE_STYLES,
    SEABED_COLORS, BIOME_IDS
)

log = logging.getLogger(__name__)


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
        '''Convert 0-255 RGB tuple to 0-1 RGB tuple.'''
        return (color[0]/255, color[1]/255, color[2]/255)

    def _add_legend(self, handles, title):
        '''Helper to add a legend to the current matplotlib figure.'''
        if handles: plt.legend(
            handles=handles, loc='lower left', #bbox_to_anchor=(1, 0.5), 
            title=title, framealpha=0.9
        )

    def _save_plot(self, output_file: str):
        '''Helper to save the current matplotlib figure.'''
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(output_file, bbox_inches='tight', dpi=150)
        plt.close()

    def _resize_if_needed(self, data: np.ndarray, max_dim: int = 4096, method=Image.NEAREST) -> Tuple[np.ndarray, float]:
        """Resizes array if dimensions exceed max_dim. Returns (resized_data, scale_factor)."""
        h, w = data.shape[:2]
        if max(h, w) <= max_dim:
            return data, 1.0
            
        scale = max_dim / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        log.info(f"  Downsampling preview from {w}x{h} to {new_w}x{new_h} (scale={scale:.4f})")
        
        # Use PIL for resizing
        img = Image.fromarray(data)
        resized_img = img.resize((new_w, new_h), method)
        return np.array(resized_img), scale

    def visualize_biomes(self, biome_map_file: str, output_file: str) -> None:
        ''' Create a visualization of the biome map using matplotlib.
        
            :param str biome_map_file: Path to biome map GeoTIFF
            :param str output_file: Path to save visualization PNG
        '''
        log.info("Generating biome visualization...")
        
        
        with rasterio.open(biome_map_file) as src: biome_data = src.read(1)
        
        # Downsample
        biome_data, _ = self._resize_if_needed(biome_data)
        
        # Colorize biome map
        rgb = self.colorize_array(biome_data, BIOME_COLORS)
        
        # Plot
        plt.figure(figsize=(16, 12), dpi=150)
        plt.imshow(rgb, interpolation='nearest')
        
        handles = []
        for bid in sorted(np.unique(biome_data)):
            if bid in BIOME_COLORS: handles.append(Patch(
                color=self._normalize_color(BIOME_COLORS[bid]), 
                label=BIOME_NAMES.get(bid, f"Biome {bid}")
            ))

        self._add_legend(handles, 'Biome Types')
        self._save_plot(output_file)
        
        log.info(f"[✓] Biome visualization saved: {output_file}")

    def visualize_land_cover(self, land_cover_file: str, output_file: str) -> None:
        ''' Create a visualization of the land cover map using matplotlib.
        
            :param str land_cover_file: Path to land cover GeoTIFF
            :param str output_file: Path to save visualization PNG
        '''
        log.info("Generating land cover visualization...")
        
        with rasterio.open(land_cover_file) as src:
            land_cover_data = src.read(1)
            
        # Downsample
        land_cover_data, _ = self._resize_if_needed(land_cover_data)
        
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

        self._add_legend(handles, 'Land Cover Classes') 
        self._save_plot(output_file)
        
        log.info(f"[✓] Land cover visualization saved: {output_file}")


    def visualize_terrain(self, elevation_file: str, output_file: str, 
                        water_mask_file: Optional[str] = None,
                        river_mask_file: Optional[str] = None,
                        biome_map_file: Optional[str] = None,
                        seabed_cover_file: Optional[str] = None) -> None:
        ''' Create a terrain visualization with optional overlays using matplotlib.
        
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save visualization PNG
            :param str water_mask_file: Optional path to water mask
            :param str river_mask_file: Optional path to river mask
            :param str biome_map_file: Optional path to biome map for overlay
            :param str seabed_cover_file: Optional path to seabed cover RGB mask
        '''
        log.info("Generating terrain visualization...")
        
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1)
            
        # Downsample elevation
        elevation, scale = self._resize_if_needed(elevation, method=Image.BILINEAR if elevation.dtype == np.float32 else Image.NEAREST)
        
        # Normalize elevation for display
        elev_min, elev_max = elevation.min(), elevation.max()
        if elev_max > elev_min:
            elev_normalized = (elevation - elev_min) / (elev_max - elev_min)
        else:
            elev_normalized = np.zeros_like(elevation, dtype=np.float32)
        
        # Convert to RGB (grayscale)
        rgb = np.stack([elev_normalized] * 3, axis=-1)
        
        # Apply water mask if available
        water_pixels = None
        if water_mask_file and Path(water_mask_file).exists():
            water_mask = np.array(Image.open(water_mask_file))
            
            # Resize mask to match elevation if needed
            if water_mask.shape != elevation.shape:
                 water_mask = np.array(Image.fromarray(water_mask).resize((elevation.shape[1], elevation.shape[0]), Image.NEAREST))
                 
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

        # Apply river mask if available: REMOVED per user request for pure heightmap data
        # If rivers are carved in elevation, they will show naturally. 
        # If not, they are just terrain features not to be confused with height data.
        
        # Apply seabed cover visualization if available: REMOVED per user request
        # Heightmap should only show elevation/bathymetry depth, not terrain types.
        seabed_labels = []
        
        # Plot
        plt.figure(figsize=(16, 12), dpi=150)
        plt.imshow(rgb, interpolation='nearest') # RGB is floats 0-1

        # Legend
        handles = [Patch(color=[0.5, 0.5, 0.5], label='Land (Elevation)')]
        
        if water_mask_file and Path(water_mask_file).exists():
            if not seabed_labels:  # No seabed overlay
                handles.append(Patch(color=[0.0, 0.39, 0.78], label='Water (Bathymetry)'))
            else:
                # Add seabed types
                for label, color in seabed_labels:
                    handles.append(Patch(color=color, label=label))
        
        # if river_mask_file: REMOVED legend entry for rivers as they are not overlaid

        self._add_legend(handles, 'Terrain Features')
        self._save_plot(output_file)
        
        log.info(f"[✓] Terrain visualization saved: {output_file}")

    def visualize_building_placements(self, 
        placements_file: str,
        output_file: str,
        heightmap_file: str = None,
        water_mask_file: str = None,
        road_mask_file: str = None
    ) -> None:
        ''' Create a visualization of building placements and roads overlaid on terrain.
        
            :param str placements_file: Path to building_placements.json
            :param str output_file: Path to save visualization PNG
            :param str heightmap_file: Optional heightmap for terrain background
            :param str water_mask_file: Optional water mask for context
            :param str road_mask_file: Optional road mask
        '''
        log.info("Generating building placement visualization...")
        
        # Load building placements
        try:
            with open(placements_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            placements = data.get('placements', [])
            building_cnt = data.get('count', len(placements))
        except Exception as e:
            log.error(f"Failed to load building placements: {e}")
            return
        
        if not placements:
            log.warning("No building placements found")
            return
        
        # Create base visualization
        if heightmap_file and Path(heightmap_file).exists():
            # Use heightmap as background
            heightmap = np.array(Image.open(heightmap_file), dtype=np.uint16)
            
            # Downsample if needed
            heightmap, scale = self._resize_if_needed(heightmap, method=Image.BILINEAR)
            
            height, width = heightmap.shape
            
            # Create flat grey background for land
            rgb = np.ones((height, width, 3), dtype=np.float32) * 0.6 # Grey for land
            
            # Apply water mask if available
            if water_mask_file and Path(water_mask_file).exists():
                try:
                    water_mask = np.array(Image.open(water_mask_file))
                    # Resize to match heightmap
                    if water_mask.shape != heightmap.shape:
                         water_mask = np.array(Image.fromarray(water_mask).resize((width, height), Image.NEAREST))
                    
                    if water_mask.shape == heightmap.shape:
                        water_pixels = water_mask > 128
                        # Light blue for water
                        rgb[water_pixels] = [0.7, 0.85, 1.0]
                except Exception as e:
                    log.warning(f"Could not apply water mask: {e}")
            
            # Apply road mask if available
            if road_mask_file and Path(road_mask_file).exists():
                try:
                    if road_mask_file.lower().endswith('.tif'):
                        with rasterio.open(road_mask_file) as rsrc:
                            road_mask = rsrc.read(1)
                    else:
                        road_mask = np.array(Image.open(road_mask_file))
                    
                    # Resize
                    if road_mask.shape != heightmap.shape:
                         road_mask = np.array(Image.fromarray(road_mask).resize((width, height), Image.NEAREST))
                    
                    if road_mask.shape == heightmap.shape:
                        road_pixels = road_mask > 0
                        rgb[road_pixels] = [1.0, 0.55, 0.0] # Orange
                except Exception as e:
                    log.warning(f"Could not apply road mask: {e}")
        else:
            # Create blank canvas based on first placement
            # This path is rare in scons pipeline but handled anyway
            height = width = 1000  
            rgb = np.ones((height, width, 3), dtype=np.float32) * 0.9
            scale = 1.0 # No scaling applied
        
        # Plot
        fig, ax = plt.subplots(figsize=(16, 12), dpi=150)
        ax.imshow(rgb, interpolation='nearest')
        
        # Define mapping for building types (color, marker)
        # Define mapping for building types (color, marker)
        TYPE_STYLES = BUILDING_TYPE_STYLES
        DEFAULT_STYLE = ((255, 0, 0), 'o')

        # Group coordinates by type
        typed_coords = {} # type -> (x_list, y_list)
        
        for placement in placements:
            x_raw = placement.get('x')
            y_raw = placement.get('y')
            if x_raw is None or y_raw is None: continue
            
            # Apply scale
            x = int(x_raw * scale)
            y = int(y_raw * scale)
            
            # Check bounds
            if not (0 <= x < width and 0 <= y < height): continue
                
            # Determine type (simplified)
            b_type = placement.get('type', 'building')
            
            if b_type not in typed_coords: typed_coords[b_type] = ([], [])
            typed_coords[b_type][0].append(x)
            typed_coords[b_type][1].append(y)
        
        # Plot each group
        legend_handles = []
        if typed_coords:
            for b_type, (xs, ys) in typed_coords.items():
                color_raw, marker = TYPE_STYLES.get(b_type, DEFAULT_STYLE)
                color = self._normalize_color(color_raw)
                handle = ax.scatter(xs, ys, c=[color], marker=marker, s=40, alpha=0.9, 
                          label=f'{b_type.capitalize()} ({len(xs)})', 
                          edgecolors='black', linewidths=0.5)
                legend_handles.append(handle)
        
        # Add road handle if present
        if road_mask_file and Path(road_mask_file).exists():
             legend_handles.append(Patch(color=[1.0, 0.55, 0.0], label='Roads'))

        if legend_handles:
            ax.legend(handles=legend_handles, loc='lower left', fontsize=10, framealpha=0.9, title="Map Artifacts")
            log.info(f"Plotted {len(legend_handles)} legend items")
        else:
            log.warning("No valid building or road coordinates to plot")
        
        self._save_plot(output_file)
        
        log.info(f"[✓] Artifact visualization saved: {output_file}")

    def visualize_terrain_types(
        self,
        heightmap_file: str,
        output_file: str,
        metadata_file: str,
        water_mask_file: Optional[str] = None,
        river_mask_file: Optional[str] = None,
        biome_map_file: Optional[str] = None,
        road_mask_file: Optional[str] = None,
        steep_slopes_mask_file: Optional[str] = None,
        seabed_cover_file: Optional[str] = None
    ) -> None:
        ''' Create terrain type classification visualization.
        
            :param str heightmap_file: Path to heightmap PNG
            :param str output_file: Path to save visualization PNG
            :param str metadata_file: Path to metadata JSON
            :param str water_mask_file: Optional path to water mask
            :param str river_mask_file: Optional path to river mask
            :param str biome_map_file: Optional path to biome map
            :param str road_mask_file: Optional path to road mask
            :param str steep_slopes_mask_file: Optional path to steep slopes mask
            :param str seabed_cover_file: Optional path to seabed cover RGB mask
        '''
        log.info("Generating terrain type visualization...")

        # Terrain definitions
        TERRAIN_COLORS_RGB = TERRAIN_COLORS
        TERRAIN_NAMES = TERRAIN_NAMES_LIST

        # Helper to load mask
        def _load_mask(path: str) -> np.ndarray:
            if not path or path == 'None' or not Path(path).exists():
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
            # Downsample
            heightmap, scale = self._resize_if_needed(heightmap, method=Image.BILINEAR)
        except Exception as e:
            log.error(f"Failed to load heightmap {heightmap_file}: {e}")
            return

        water_mask = _load_mask(water_mask_file)
        river_mask = _load_mask(river_mask_file)
        road_mask = _load_mask(road_mask_file)
        biome_map = _load_mask(biome_map_file)
        steep_slopes_mask = _load_mask(steep_slopes_mask_file)
        seabed_mask = None
        if seabed_cover_file and Path(seabed_cover_file).exists():
            try:
                seabed_mask = np.array(Image.open(seabed_cover_file))
            except Exception as e:
                log.warning(f"Could not load seabed mask: {e}")
        
        # Resize all masks to match heightmap if needed
        # Since heightmap might have been downsampled
        target_shape = heightmap.shape # (H, W)
        target_size = (target_shape[1], target_shape[0]) # (W, H) for PIL

        def _resize_to_match(arr):
            if arr is None: return None
            if arr.shape[:2] == target_shape: return arr
            try:
                # Use NEAREST for masks to preserve class IDs/booleans
                return np.array(Image.fromarray(arr).resize(target_size, Image.NEAREST))
            except Exception as e:
                log.warning(f"Failed to resize mask: {e}")
                return arr

        water_mask = _resize_to_match(water_mask)
        river_mask = _resize_to_match(river_mask)
        road_mask = _resize_to_match(road_mask)
        biome_map = _resize_to_match(biome_map)
        steep_slopes_mask = _resize_to_match(steep_slopes_mask)
        seabed_mask = _resize_to_match(seabed_mask)
        
        # Get sea level and slope thresholds
        sea_level_value = 0
        cliff_threshold = self.config.get('terrain', {}).get('cliff_threshold_degrees', 25.0)
        max_slope_deg = self.config.get('masks', {}).get('slope_max_degrees', 80.0)
        # Normalize cliff threshold to 0-255 scale used in slope_mask
        slope_viz_threshold = int((cliff_threshold / max_slope_deg) * 255)
        log.info(f" Using slope threshold for visualization: {cliff_threshold}° -> {slope_viz_threshold}/255")
        
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
            
            # Default classification
            terrain[is_water] = 1 # Default to Sandy Ocean Floor
            terrain[~is_water] = 2 # Grass
            
            # Use biome map to distinguish inland water (Swamp/River biomes)
            if biome_map is not None:
                # 6 = Swamp, 247 = Mangrove Swamp, 7 = River
                is_swamp = (biome_map == BIOME_IDS['swamp']) | (biome_map == BIOME_IDS['mangrove_swamp'])
                is_river_biome = (biome_map == 7)
                
                # We color Biome-based "Inland Water" as ID 7 (Dirt/River Bed)
                # But if it's strictly a Swamp biome, we might want a different look
                terrain[is_water & is_swamp] = 7 # Dirt (River Bed)
                terrain[is_water & is_river_biome] = 7
                
            # Apply seabed classification if available
            if seabed_mask is not None and seabed_mask.shape[:2] == terrain.shape:
                # Seabed mask channels: R=sand, G=gravel, B=rock
                gravel_pixels = (seabed_mask[:, :, 1] > 127) & is_water
                rock_pixels = (seabed_mask[:, :, 2] > 127) & is_water
                
                # Apply: default is sand (1), so just apply gravel (0) and rock (3)
                # Rock overrides gravel if both present (though they shouldn't overlap much)
                terrain[gravel_pixels] = 0 # Gravel Ocean Floor
                terrain[rock_pixels] = 3   # Stone (Steep Slopes) / Rock
            else:
                # Fallback depth-based classification
                depth_delta = 5000
                deep_thresh = max(0, sea_level_value - depth_delta)
                terrain[is_water & (heightmap < deep_thresh)] = 0  # Gravel
        else:
            terrain[:] = 2

        # Extract masks from biome map if available
        # Biome IDs: Beach=16, Stone Shore=25, Badlands=37
        beach_mask = (biome_map == 16) if biome_map is not None else None
        badlands_mask = (biome_map == 37) if biome_map is not None else None
        
        # Stone shore from biome map is valid too, combine it with explicit steep slopes
        stone_shore_mask = (biome_map == 25) if biome_map is not None else None

        # Overlays: Beaches first, then cliffs/stone (to ensure steep coastal areas win), then features
        for mask, tid, thresh in [
            (beach_mask, 4, 0),          # Beach Sand (Low priority)
            (stone_shore_mask, 3, 0),    # Stone shore from biomes
            (steep_slopes_mask, 3, slope_viz_threshold), # Explicit slope gradient (Stone)
            (badlands_mask, 5, 0),       # Badlands
            (river_mask, 7, 127),        # OSM Waterways -> Dirt (River Bed) (ID 7)
            (road_mask, 6, 0)            # Roads (High priority, overwrites rivers)
        ]:
            if mask is not None:
                # Resize if necessary
                if mask.shape != terrain.shape: 
                    try:
                        mask = np.array(Image.fromarray(mask).resize((terrain.shape[1], terrain.shape[0]), Image.NEAREST))
                    except:
                        continue
                
                # Double check shape
                if mask.shape != terrain.shape: continue
                
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
        colors_norm = [self._normalize_color(c) for c in TERRAIN_COLORS_RGB]
        im = ax.imshow(terrain, cmap=ListedColormap(colors_norm), vmin=0, vmax=len(colors_norm)-1, interpolation='nearest')
        
        # Legend
        handles = [Patch(color=colors_norm[i], label=TERRAIN_NAMES[i]) for i in range(len(colors_norm))]
        self._add_legend(handles, 'Terrain Types')
        self._save_plot(output_file)
        log.info(f"[✓] Terrain type visualization saved: {output_file}")
