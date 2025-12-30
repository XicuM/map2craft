"""
Road processing for map2craft.
Generates road masks and flattens roads in elevation data.
"""

import os
import logging
import numpy as np
import rasterio
import json
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from typing import Tuple, Dict
from pathlib import Path

log = logging.getLogger(__name__)

class RoadsProcessor:
    def __init__(self, config=None):
        self.config = config or {}

    def generate_road_mask(self, roads_geojson: str, elevation_file: str, output_file: str,
                          road_widths: Dict[str, int], scale_down: int = 20) -> None:
        ''' Generate a road mask from OSM road data.
        
            :param str roads_geojson: Path to roads GeoJSON file
            :param str elevation_file: Path to elevation GeoTIFF (for dimensions/transform)
            :param str output_file: Path to save road mask GeoTIFF
            :param dict road_widths: Dictionary mapping highway types to widths in blocks
            :param int scale_down: Horizontal scale factor (1:N)
        '''
        log.info("Generating road mask...")
        
        # Load roads
        with open(roads_geojson, 'r') as f:
            roads_data = json.load(f)
        
        # Get elevation dimensions and transform
        with rasterio.open(elevation_file) as src:
            height, width = src.shape
            transform = src.transform
            crs = src.crs
            bounds = src.bounds
        
        # Create empty mask
        road_mask = np.zeros((height, width), dtype=np.uint8)
        
        # Rasterize roads
        shapes = []
        from rasterio.warp import transform_geom
        
        for feature in roads_data['features']:
            highway_type = feature['properties'].get('highway', 'unclassified')
            width_blocks = road_widths.get(highway_type, 2)
            
            # Convert blocks to meters, then to pixels
            width_meters = width_blocks * scale_down
            width_pixels = max(1, int(width_meters / 30))  # Assuming 30m resolution
            
            # Reproject geometry from EPSG:4326 to target CRS
            try:
                geom = transform_geom('EPSG:4326', crs, feature['geometry'])
                shapes.append((geom, width_pixels))
            except Exception as e:
                pass
            
        if shapes:
            # Rasterize with different values for different widths
            try:
                # We rasterize all shapes at once for efficiency. 
                # Later shapes overwrite earlier ones, so sort/order if needed.
                road_mask = rasterize(
                    shapes,
                    out_shape=(height, width),
                    transform=transform,
                    fill=0,
                    dtype=np.uint8,
                    all_touched=True
                )
            except Exception as e:
                log.warning(f"Failed to rasterize roads: {e}")
        
        # Save road mask
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        with rasterio.open(
            output_file,
            'w',
            driver='GTiff',
            height=height,
            width=width,
            count=1,
            dtype=rasterio.uint8,
            crs=crs,
            transform=transform,
            compress='lzw'
        ) as dst:
            dst.write(road_mask, 1)
        
        log.info(f"[v] Road mask saved: {output_file}")
        log.info(f"  Roads rasterized: {len(shapes)}")

    def road_mask_action(self, target, source, env):
        ''' SCons action for road mask.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        road_widths = self.config.get('roads', {}).get('road_widths', {})
        scale_down = self.config['minecraft'].get('scale', {}).get('horizontal', 20)
        
        self.generate_road_mask(
            str(source[0]), str(source[1]), str(target[0]),
            road_widths, scale_down
        )
        return None

