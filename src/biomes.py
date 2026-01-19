import logging
import numpy as np
import rasterio
from pathlib import Path
from typing import Tuple, Optional, Dict
from rasterio.warp import reproject, Resampling
from scipy import ndimage

log = logging.getLogger(__name__)
from src.constants import BIOME_IDS
from src.geometry import compute_pixel_size_meters, compute_slope_degrees
from src.masks import MaskGenerator

class BiomeMapper:
    def __init__(self, config=None):
        self.config = config or {}
        self.mask_generator = MaskGenerator(self.config)



    def load_and_resample_land_cover(self, path: str, shape: Tuple[int, int], transform, crs) -> Optional[np.ndarray]:
        ''' Loads and resamples land cover data to the target grid.
        
            :param str path: Path to land cover file
            :param Tuple[int, int] shape: Target shape (height, width)
            :param transform: Target transform
            :param crs: Target CRS
            
            :return: Resampled land cover array or None
        '''
        if not Path(path).exists():
            log.warning(f"Land cover file not found: {path}")
            return None
        with rasterio.open(path) as src:
            out = np.zeros(shape, dtype=np.uint8)
            reproject(
                source=rasterio.band(src, 1), destination=out,
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest
            )
        return out

    def generate_biome_map_array(self, 
        elevation: np.ndarray, 
        slope: np.ndarray, 
        land_cover: Optional[np.ndarray], 
        sea_level: float = 0.0, 
        cliff_threshold: float = 25.0,
        lukewarm_depth: float = -35.0, 
        deep_depth: float = -90.0,
        beach_mask: Optional[np.ndarray] = None,
        inland_water_kernel_size: int = 3
    ) -> np.ndarray:
        ''' Classifies terrain into biomes based on height, slope, and land cover.
        
            :param np.ndarray elevation: Elevation data
            :param np.ndarray slope: Slope data
            :param np.ndarray land_cover: Land cover data (optional)
            :param float sea_level: Sea level in meters
            :param float cliff_threshold: Slope threshold for cliffs
            :param float lukewarm_depth: Depth for lukewarm ocean
            :param float deep_depth: Depth for deep ocean
            :param np.ndarray beach_mask: Mask of areas suitable for beaches
            :param int inland_water_kernel_size: Kernel size for inland water detection
            
            :return: Biome ID array
        '''
        is_water = elevation <= sea_level
        is_inland_water = self.mask_generator.detect_inland_water(elevation, sea_level, kernel_size=inland_water_kernel_size)
        
        # 1. Main Ocean Conditions (Water AND NOT Inland/Swamp)
        # "Ocean" = generic water that isn't swamp
        conds = [
            is_water & ~is_inland_water & (elevation < deep_depth),      # Deep Ocean
            is_water & ~is_inland_water & (elevation > lukewarm_depth),  # Lukewarm Ocean
            is_water & ~is_inland_water,                                 # Ocean
            ~is_water & (slope >= cliff_threshold),                      # Stone Shore (Cliffs)
        ]
        choices = [
            BIOME_IDS['deep_ocean'], 
            BIOME_IDS['lukewarm_ocean'], 
            BIOME_IDS['ocean'],
            BIOME_IDS['stone_shore'],
        ]

        # 2. Beach generation (if enabled via mask)
        if beach_mask is not None:
            conds.append(~is_water & beach_mask)
            choices.append(BIOME_IDS['beach'])

        # 3. Land Cover Conditions (Applied if not coastal/cliff)
        if land_cover is not None:
            conds += [
                ~is_water & (land_cover == 90), # Wetland -> Swamp
                ~is_water & (land_cover == 10), # Trees -> Forest
                ~is_water & (land_cover == 60), # Bare -> Badlands
                ~is_water & ((land_cover == 20) | (land_cover == 30)) # Shrub/Grass -> Savanna
            ]
            choices += [BIOME_IDS['swamp'], BIOME_IDS['forest'], BIOME_IDS['badlands'], BIOME_IDS['savanna']]

        # 4. Swamp (Inland Water) - Last fallback for water
        # If it was water, but failed Ocean checks (because it's inland), catch it here.
        conds.append(is_inland_water)
        choices.append(BIOME_IDS['swamp'])

        return np.select(conds, choices, default=BIOME_IDS['plains']).astype(np.uint8)

    def create_biome_map(self, elevation_file: str, land_cover_file: Optional[str], 
                        output_file: str, is_pre_scaled: bool = False) -> None:
        ''' Orchestrates the loading, classification, and saving of the biome map.
        
            :param str elevation_file: Path to elevation GeoTIFF
            :param str land_cover_file: Path to land cover GeoTIFF
            :param str output_file: Path to save biome map
        '''
        log.info("Generating biome map...")
        
        with rasterio.open(elevation_file) as src:
            elev, trans, crs, profile = src.read(1).astype(np.float32), src.transform, src.crs, src.profile
            
            # If elevation is in blocks (pre-scaled), convert back to meters 
            # for slope calculation and biome thresholds which are configured in meters
            if is_pre_scaled:
                v_scale = float(self.config['minecraft']['scale']['vertical'])
                log.info(f" Converting pre-scaled elevation (blocks) to meters for biome logic (scale: {v_scale})")
                elev_m = elev * v_scale
            else:
                elev_m = elev

            pixel_size = compute_pixel_size_meters(trans, crs, elev_m.shape)
            slope = compute_slope_degrees(elev_m, pixel_size)
            
            lc = self.load_and_resample_land_cover(land_cover_file, elev.shape, trans, crs) if land_cover_file else None
             
            
            # Get terrain configuration
            thresholds = self.config.get('terrain', {})
            sea_level = thresholds.get('sea_level_m', 0.0)
            cliff_threshold = thresholds.get('cliff_threshold_degrees', 25.0)
            lukewarm_depth = thresholds.get('lukewarm_ocean_depth_m', -35.0)
            deep_depth = thresholds.get('deep_ocean_depth_m', -90.0)
            
            # Clamp shallow areas near sea level to ensure proper water biome classification
            # Target: 0-1 block elevation areas that should be water (artifacts from bathymetry merge)
            # CRITICAL: Only clamp if NOT steep, to preserve coastal cliff biomes
            shallow_land = (elev_m > 0) & (elev_m < 1.0) & (slope < cliff_threshold)
            if np.any(shallow_land):
                elev_m[shallow_land] = -1.0  # Force to water
                log.info(f" Clamped {np.sum(shallow_land)} flat shallow coastal pixels to -1 block for biome classification")
            
            # Also clamp any negative shallow water
            shallow_water = (elev_m < 0) & (elev_m > -1.0)
            if np.any(shallow_water):
                elev_m[shallow_water] = -1.0
                log.info(f" Clamped {np.sum(shallow_water)} shallow water pixels to -1 block for biome classification")
            
            # Get inland water configuration
            inland_water_config = self.config.get('biomes', {}).get('inland_water', {})
            inland_water_kernel = inland_water_config.get('erosion_kernel_size', 4)

            # Generate optional beach mask
            beach_mask = None
            beaches_config = self.config.get('biomes', {}).get('beaches', {})
            if beaches_config.get('enabled', True):
                log.info(" Calculating beach mask using distance transform...")
                
                # 1. Identify "Main Ocean" vs "Inland Water"
                # We need to detect inland water again here (it's also done inside generate_biome_map_array, could optimize but this is clearer)
                is_water_mask = elev_m <= sea_level
                is_inland_water = self.mask_generator.detect_inland_water(elev_m, sea_level, kernel_size=inland_water_kernel)
                is_main_ocean = is_water_mask & ~is_inland_water
                
                # 2. Distance from MAIN OCEAN only
                # If we use just ~is_water_mask, beaches format around lakes.
                # We want distance from "Main Ocean".
                # distance_transform_edt computes distance to the nearest non-zero pixel.
                # So we want to feed it the "Not Ocean" mask.
                # "Not Ocean" includes Land AND Inland Water.
                not_ocean_mask = ~is_main_ocean
                
                # distance_transform_edt returns Euclidean distance in pixels
                pixel_dist = ndimage.distance_transform_edt(not_ocean_mask)
                
                # Convert max_penetration_m to pixels
                h_scale = self.config['minecraft']['scale']['horizontal']
                dist_m = pixel_dist * h_scale
                
                max_dist_m = beaches_config.get('max_penetration_m', 50.0)
                max_slope = beaches_config.get('max_slope_degrees', 15.0)
                
                # Beach is near main ocean AND flat enough AND not already water
                # (Though usually beach is land, sometimes shallow water is beach too? 
                #  Here we assume beach is land part. The classification logic handles underwater beach if we want,
                #  but biome_map generation treats beach primarily as land feature usually? 
                #  Actually generate_biome_map_array has `conds.append(~is_water & beach_mask)` 
                #  so it only applies to land pixels anyway.)
                beach_mask = (dist_m <= max_dist_m) & (slope <= max_slope) & ~is_water_mask
                log.info(f" Beach generation: max_penetration={max_dist_m}m, max_slope={max_slope}° (Inland water excluded)")

            # Generate biome map
            biome_map = self.generate_biome_map_array(
                elev_m, slope, lc, sea_level, cliff_threshold, lukewarm_depth, deep_depth, 
                beach_mask=beach_mask, 
                inland_water_kernel_size=inland_water_kernel
            )
            
            # Save biome map
            profile.update(dtype=rasterio.uint8, count=1, compress='lzw')
            with rasterio.open(output_file, 'w', **profile) as dst:
                dst.write(biome_map, 1)
        
        log.info(f"[✓] Biome map saved: {output_file}")


