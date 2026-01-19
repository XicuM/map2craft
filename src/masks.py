""" Generate terrain masks (water, slope) for WorldPainter. """

from pathlib import Path
import numpy as np
import rasterio
from PIL import Image
from typing import Tuple
import logging
from scipy import ndimage

from . import geometry

log = logging.getLogger(__name__)

from . import geometry

class MaskGenerator:
    def __init__(self, config=None):
        self.config = config or {}

    def generate_water_mask(self, elevation: np.ndarray, sea_level: float = 0.0) -> np.ndarray:
        ''' Generate a water mask based on elevation.
            
            :param np.ndarray elevation: 2D numpy array of elevation values
            :param float sea_level: Sea level in meters (default 0)
            
            :return: 2D numpy array: 255 for water, 0 for land
        '''
        water_mask = (elevation <= sea_level).astype(np.uint8) * 255
        return water_mask


    def detect_inland_water(self, elevation: np.ndarray, sea_level: float, kernel_size: int = 4) -> np.ndarray:
        ''' Detects inland water bodies (swamps) vs main ocean using Erode-Expand.
            
            Algorithm:
            1. Erode water mask to sever narrow connections (channels).
            2. Identify the largest body touching the border as "Main Ocean Core".
            3. Dilate the "Main Ocean Core" back to restore its coastline.
            4. Inland Water = Original Water AND NOT Restored Ocean.
            
            :param np.ndarray elevation: Elevation data
            :param float sea_level: Sea level threshold
            :param int kernel_size: Size of the erosion/dilation kernel.
            :return: Boolean mask where True = Inland Water (Swamp)
        '''
        is_water = elevation <= sea_level
        if not np.any(is_water): return np.zeros_like(is_water, dtype=bool)

        # 1. Erode to sever connections
        # Larger kernel = wider channels are severed
        # border_value=1 ensures we don't erode away from the map edge (treat outside as water)
        structure = np.ones((kernel_size, kernel_size), dtype=int)
        eroded_water = ndimage.binary_erosion(is_water, structure=structure, border_value=1)
        
        # 2. Label eroded components
        # Use 4-connectivity for labeling to stop diagonal leaks
        label_structure = np.array([[0,1,0], [1,1,1], [0,1,0]], dtype=int)
        labeled_array, num_features = ndimage.label(eroded_water, structure=label_structure)
        
        # 3. Identify Main Ocean Core (touching borders)
        border_mask = np.zeros_like(labeled_array, dtype=bool)
        border_mask[0, :] = True
        border_mask[-1, :] = True
        border_mask[:, 0] = True
        border_mask[:, -1] = True
        
        ocean_labels = np.unique(labeled_array[border_mask & (labeled_array > 0)])
        is_main_ocean_core = np.isin(labeled_array, ocean_labels)
        
        # 4. Restore Main Ocean (Dilate back)
        # We dilate the CORE, not the whole mask. This restores the ocean coast
        # but does NOT reconnect to the inland bodies (because they were severed).
        # border_value=1 matches erosion behavior
        restored_ocean = ndimage.binary_dilation(is_main_ocean_core, structure=structure, border_value=1)
        
        # 5. Inland Water is any water that isn't part of the restored ocean
        return is_water & ~restored_ocean


    def generate_slope_mask(self, elevation: np.ndarray, pixel_size: Tuple[float, float], 
                           max_slope: float = 60.0) -> np.ndarray:
        ''' Generate a slope mask from elevation data.
            
            :param np.ndarray elevation: 2D numpy array of elevation values
            :param Tuple[float, float] pixel_size: (px_meters, py_meters) pixel size in meters
            :param float max_slope: Maximum slope in degrees for normalization
            
            :return: 2D numpy array: 0-255 slope intensity
        '''
        slope = geometry.compute_slope_degrees(elevation, pixel_size)
        normalized = np.clip(slope / max_slope * 255, 0, 255).astype(np.uint8)
        return normalized


    def create_water_mask(self, elevation_file: str, output_file: str, sea_level: float = 0.0, 
                        is_pre_scaled: bool = False) -> None:
        ''' Create and save water mask from elevation data.
            
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save water mask PNG
            :param float sea_level: Sea level in meters
            :param bool is_pre_scaled: If True, input is in blocks
        ''' 
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1).astype(np.float32)
            
            if is_pre_scaled:
                v_scale = float(self.config['minecraft']['scale']['vertical'])
                elevation *= v_scale
                
            water_mask = self.generate_water_mask(elevation, sea_level)
            
            img = Image.fromarray(water_mask, mode='L')
            img.save(output_file)
        
        log.info(f"[✓] Water mask saved: {output_file}")


    def create_slope_mask(self, elevation_file: str, output_file: str, max_slope: float = 60.0,
                        is_pre_scaled: bool = False) -> None:
        ''' Create and save slope mask from elevation data.
 
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save slope mask PNG
            :param float max_slope: Maximum slope in degrees
            :param bool is_pre_scaled: If True, input is in blocks
        '''
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1).astype(np.float32)
            
            if is_pre_scaled:
                v_scale = float(self.config['minecraft']['scale']['vertical'])
                elevation *= v_scale
            
            pixel_size = geometry.compute_pixel_size_meters(src.transform, src.crs, elevation.shape)
            slope_mask = self.generate_slope_mask(elevation, pixel_size, max_slope)
            
            Image.fromarray(slope_mask, mode='L').save(output_file)
        
        log.info(f"[✓] Slope mask saved: {output_file}")

    def generate_seabed_cover_mask(self, elevation: np.ndarray, pixel_size: Tuple[float, float],
                                   gravel_min_degrees: float = 2.0, 
                                   rock_min_degrees: float = 10.0,
                                   sea_level: float = 0.0,
                                   erosion_kernel_size: int = 4) -> np.ndarray:
        ''' Generate seabed cover classification mask from elevation and slope.
        
            Sand is the default for all underwater areas.
            Gravel and rock are applied based on minimum slope thresholds.
            Inland water is excluded from seabed cover (masked as 0).
            
            :param np.ndarray elevation: 2D elevation array in meters
            :param Tuple[float, float] pixel_size: (px_meters, py_meters) pixel size in meters
            :param float gravel_min_degrees: Minimum slope for gravel classification
            :param float rock_min_degrees: Minimum slope for rock classification
            
            :return: 3D array (H, W, 3) with RGB channels for sand, gravel, rock
        '''
        # Compute slope in degrees (using meters)
        slope = geometry.compute_slope_degrees(elevation, pixel_size)
        
        # Water mask (only classify underwater areas)
        water_mask = elevation < 0.0
        
        # Inland Water Exclusion
        # Detect inland water and mask it out (seabed type 0 / None)
        inland_water_mask = self.detect_inland_water(elevation, sea_level, kernel_size=erosion_kernel_size)
    
        # Initialize 3-channel mask (RGB)
        height, width = elevation.shape
        seabed_mask = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Apply mask only where it is NOT inland water
        valid_water_mask = water_mask & ~inland_water_mask

        # Sand (channel 0 - Red): Default for all valid underwater areas
        seabed_mask[:, :, 0][valid_water_mask] = 255
        
        # Gravel (channel 1 - Green): Areas with slope >= gravel_min_degrees
        gravel_mask = valid_water_mask & (slope >= gravel_min_degrees)
        seabed_mask[:, :, 1][gravel_mask] = 255
        
        # Rock (channel 2 - Blue): Areas with slope >= rock_min_degrees
        rock_mask = valid_water_mask & (slope >= rock_min_degrees)
        seabed_mask[:, :, 2][rock_mask] = 255
        
        return seabed_mask

    def create_seabed_cover_mask(self, elevation_file: str, output_file: str,
                                gravel_min_degrees: float = 2.0,
                                rock_min_degrees: float = 10.0,
                                is_pre_scaled: bool = False,
                                erosion_kernel_size: int = 4) -> None:
        ''' Create and save seabed cover mask from elevation data.
        
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save seabed cover mask PNG
            :param float gravel_min_degrees: Minimum slope for gravel (default 2.0)
            :param float rock_min_degrees: Minimum slope for rock (default 10.0)
            :param bool is_pre_scaled: If True, input is in blocks (convert to meters)
        '''
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1).astype(np.float32)
            
            # Convert from blocks to meters if needed
            if is_pre_scaled:
                v_scale = float(self.config['minecraft']['scale']['vertical'])
                elevation *= v_scale
            
            # Calculate pixel size in meters
            pixel_size = geometry.compute_pixel_size_meters(src.transform, src.crs, elevation.shape)
            
            # Generate seabed cover mask
            # Need sea_level (default 0.0 or from config if passed... assumes 0.0 for now as standard mapping)
            # Actually we should grab sea level from terrain config if possible, but here we'll default to 0.0
            # since `generate_seabed_cover_mask` uses it for thresholding.
            # Wait, `generate_seabed_cover_mask` uses `sea_level` passed to `detect_inland_water`.
            # We should probably fetch it.
            sea_level = self.config.get('terrain', {}).get('sea_level_m', 0.0)

            seabed_mask = self.generate_seabed_cover_mask(
                elevation, pixel_size, gravel_min_degrees, rock_min_degrees,
                sea_level=sea_level, erosion_kernel_size=erosion_kernel_size
            )
            
            # Save as RGB PNG
            img = Image.fromarray(seabed_mask, mode='RGB')
            img.save(output_file)
        
        log.info(f"[✓] Seabed cover mask saved: {output_file}")

    def water_mask_action(self, target, source, env):

        ''' SCons action for water mask '''
        sea_level = self.config.get('terrain', {}).get('water_mask_threshold_m', 1.0)
        is_pre_scaled = env.get('PRE_SCALED', False)
        self.create_water_mask(str(source[0]), str(target[0]), sea_level, is_pre_scaled=is_pre_scaled)
        return None

    def slope_mask_action(self, target, source, env):
        ''' SCons action for slope mask '''
        max_slope = self.config['masks']['slope_max_degrees']
        is_pre_scaled = env.get('PRE_SCALED', False)
        self.create_slope_mask(str(source[0]), str(target[0]), max_slope, is_pre_scaled=is_pre_scaled)
        return None

    def seabed_cover_mask_action(self, target, source, env):
        ''' SCons action for seabed cover mask '''
        seabed_config = self.config.get('seabed', {})
        thresholds = seabed_config.get('thresholds', {})
        gravel_min = thresholds.get('gravel_min_degrees', 2.0)
        rock_min = thresholds.get('rock_min_degrees', 10.0)
        is_pre_scaled = env.get('PRE_SCALED', False)
        
        inland_water_kernel = self.config.get('biomes', {}).get('inland_water', {}).get('erosion_kernel_size', 4)
        
        self.create_seabed_cover_mask(str(source[0]), str(target[0]), 
                                     gravel_min, rock_min, is_pre_scaled=is_pre_scaled,
                                     erosion_kernel_size=inland_water_kernel)
        return None
