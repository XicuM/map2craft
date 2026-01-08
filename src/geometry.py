"""
Geospatial geometry utilities for map2craft.

Provides coordinate transforms, distance calculations, slope computation,
and other spatial operations.
"""

import math
import numpy as np
from typing import Tuple, Union
from affine import Affine


def compute_slope_degrees(
    elevation: np.ndarray,
    meters_per_pixel: Union[float, Tuple[float, float]]
) -> np.ndarray:
    ''' Compute slope in degrees from elevation raster.
    
        :param np.ndarray elevation: 2D elevation array in meters
        :param meters_per_pixel: Horizontal resolution (float) or (spacing_y, spacing_x) tuple
        
        :return: 2D array of slopes in degrees
    '''
    # Support anisotropic pixel sizes
    if isinstance(meters_per_pixel, (tuple, list)) and len(meters_per_pixel) == 2:
        spacing_y, spacing_x = float(meters_per_pixel[0]), float(meters_per_pixel[1])
    else:
        spacing_y = spacing_x = float(meters_per_pixel)
    
    # Compute gradients
    dy, dx = np.gradient(elevation, spacing_y, spacing_x)
    
    # Slope in degrees
    return np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))


def compute_pixel_size_meters(transform: Affine, crs, shape: Tuple[int, int]) -> Tuple[float, float]:
    ''' Compute pixel size in meters for X and Y from raster transform and CRS.
    
        If CRS is projected in meters, uses transform scales directly.
        If CRS is geographic (degrees), approximates meters per pixel at raster center.
    
        :param transform: Affine transform from rasterio
        :param crs: CRS object from rasterio
        :param tuple shape: (height, width) of raster
        
        :return: (px_meters, py_meters) - pixel size in meters for X and Y directions
    '''
    # Pixel size in CRS units
    px = abs(transform.a)
    py = abs(transform.e)

    # If projected and units are meters, return directly
    if crs is not None and crs.is_projected: return px, py

    # Geographic CRS (degrees): approximate meters per degree at center
    from pyproj import Geod
    height, width = shape
    
    # Center pixel indices
    c = width/2.0
    r = height/2.0
    
    # Transform pixel center to geographic coords
    x_center = transform.c + c * transform.a + r * transform.b
    y_center = transform.f + c * transform.d + r * transform.e
    
    geod = Geod(ellps='WGS84')
    
    # X step (longitude)
    x2 = x_center + px
    _, _, dist_x = geod.inv(x_center, y_center, x2, y_center)
    
    # Y step (latitude)
    y2 = y_center + (py if transform.e > 0 else -py)
    _, _, dist_y = geod.inv(x_center, y_center, x_center, y2)
    
    dist_x = abs(dist_x) if dist_x else 30.0
    dist_y = abs(dist_y) if dist_y else 30.0
    
    return dist_x, dist_y


def latlon_to_pixel(lon: float, lat: float, transform: Affine) -> Tuple[int, int]:
    ''' Convert lat/lon to pixel coordinates using affine transform.
    
        :param float lon: Longitude
        :param float lat: Latitude
        :param transform: Affine transform from rasterio
        
        :return: (col, row) pixel coordinates
    '''
    # Affine inverse to go from world coords to pixel coords
    col, row = ~transform * (lon, lat)
    return int(col), int(row)


def pixel_to_latlon(col: int, row: int, transform: Affine) -> Tuple[float, float]:
    ''' Convert pixel coordinates to lat/lon using affine transform.
    
        :param int col: Column (x) in pixels
        :param int row: Row (y) in pixels
        :param transform: Affine transform from rasterio
        
        :return: (lon, lat) coordinates
    '''
    lon, lat = transform * (col + 0.5, row + 0.5)  # Center of pixel
    return lon, lat
