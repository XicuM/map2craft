import logging
import numpy as np
import rasterio
from pathlib import Path
from typing import Tuple, Optional, Dict
from rasterio.warp import reproject, Resampling

log = logging.getLogger(__name__)

from src.constants import BIOME_IDS

class BiomeMapper:
    def __init__(self, config=None):
        self.config = config or {}

    def compute_slope_and_pixel_size(self, transform, crs, elevation: np.ndarray) -> np.ndarray:
        ''' Internal helper to calculate slope in degrees without external modules.
        
            :param transform: Rasterio transform
            :param crs: Coordinate reference system
            :param np.ndarray elevation: Elevation data
            :return: Slope in degrees (same shape as elevation)
        '''
        res_x, res_y = abs(transform.a), abs(transform.e)
        # Convert degrees to meters if CRS is geographic (WGS84)
        if crs.is_geographic:
            lat_mid = transform.f + (res_y * elevation.shape[0] / 2)
            res_y *= 111320
            res_x *= 111320 * np.cos(np.radians(lat_mid))
        
        dy, dx = np.gradient(elevation, res_y, res_x)
        return np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))

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
        deep_depth: float = -90.0
    ) -> np.ndarray:
        ''' Classifies terrain into biomes based on height, slope, and land cover.
        
            :param np.ndarray elevation: Elevation data
            :param np.ndarray slope: Slope data
            :param np.ndarray land_cover: Land cover data (optional)
            :param float sea_level: Sea level in meters
            :param float cliff_threshold: Slope threshold for cliffs
            :param float lukewarm_depth: Depth for lukewarm ocean
            :param float deep_depth: Depth for deep ocean
            
            :return: Biome ID array
        '''
        is_water = elevation <= sea_level
        
        # Water Conditions (Depth-based)
        conds = [
            is_water & (elevation < deep_depth),
            is_water & (elevation > lukewarm_depth),
            is_water
        ]
        choices = [BIOME_IDS['deep_ocean'], BIOME_IDS['lukewarm_ocean'], BIOME_IDS['ocean']]

        # Land Conditions (Land-cover based)
        if land_cover is not None:
            conds += [
                land_cover == 90, # Wetland
                land_cover == 10, # Trees
                land_cover == 60, # Bare/sparse vegetation
                (land_cover == 20) | (land_cover == 30) # Shrubland/Grassland
            ]
            choices += [BIOME_IDS['swamp'], BIOME_IDS['forest'], BIOME_IDS['badlands'], BIOME_IDS['savanna']]

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

            slope = self.compute_slope_and_pixel_size(trans, crs, elev_m)
            
            lc = self.load_and_resample_land_cover(land_cover_file, elev.shape, trans, crs) if land_cover_file else None
             
            
            # Get biome configuration
            biome_cfg = self.config['biomes']
            sea_level = biome_cfg['sea_level_meters']
            cliff_threshold = biome_cfg['cliff_threshold']
            lukewarm_depth = biome_cfg['lukewarm_ocean_depth_m']
            deep_depth = biome_cfg['deep_ocean_depth_m']
            
            # Clamp shallow areas near sea level to ensure proper water biome classification
            # Target: 0-1 block elevation areas that should be water (artifacts from bathymetry merge)
            shallow_land = (elev_m > 0) & (elev_m < 1.0)
            if np.any(shallow_land):
                elev_m[shallow_land] = -1.0  # Force to water
                log.info(f" Clamped {np.sum(shallow_land)} shallow coastal pixels to -1 block for biome classification")
            
            # Also clamp any negative shallow water
            shallow_water = (elev_m < 0) & (elev_m > -1.0)
            if np.any(shallow_water):
                elev_m[shallow_water] = -1.0
                log.info(f" Clamped {np.sum(shallow_water)} shallow water pixels to -1 block for biome classification")
            
            # Generate biome map
            biome_map = self.generate_biome_map_array(elev_m, slope, lc, sea_level, cliff_threshold, lukewarm_depth, deep_depth)
            
            # Save biome map
            profile.update(dtype=rasterio.uint8, count=1, compress='lzw')
            with rasterio.open(output_file, 'w', **profile) as dst:
                dst.write(biome_map, 1)
        
        log.info(f"[✓] Biome map saved: {output_file}")


