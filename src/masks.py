""" Generate terrain masks (water, slope) for WorldPainter. """

import os
import numpy as np
import rasterio
from PIL import Image
from typing import Tuple
import logging

from . import geometry

log = logging.getLogger(__name__)

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


    def create_water_mask(self, elevation_file: str, output_file: str, sea_level: float = 0.0) -> None:
        ''' Create and save water mask from elevation data.
            
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save water mask PNG
            :param float sea_level: Sea level in meters
        ''' 
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1)
            water_mask = self.generate_water_mask(elevation, sea_level)
            
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            img = Image.fromarray(water_mask, mode='L')
            img.save(output_file)
        
        log.info(f"[v] Water mask saved: {output_file}")


    def create_slope_mask(self, elevation_file: str, output_file: str, max_slope: float = 60.0) -> None:
        ''' Create and save slope mask from elevation data.

            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save slope mask PNG
            :param float max_slope: Maximum slope in degrees
        '''
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1)
            pixel_size = geometry.compute_pixel_size_meters(src.transform, src.crs, elevation.shape)
            slope_mask = self.generate_slope_mask(elevation, pixel_size, max_slope)
            
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            Image.fromarray(slope_mask, mode='L').save(output_file)
        
        log.info(f"[v] Slope mask saved: {output_file}")

    def water_mask_action(self, target, source, env):
        ''' SCons action for water mask '''
        sea_level = self.config.get('masks', {}).get('water_sea_level_m', 0.0)
        self.create_water_mask(str(source[0]), str(target[0]), sea_level)
        return None

    def slope_mask_action(self, target, source, env):
        ''' SCons action for slope mask '''
        max_slope = self.config.get('masks', {}).get('slope_max_degrees', 60.0)
        self.create_slope_mask(str(source[0]), str(target[0]), max_slope)
        return None
