'''
Road processing for map2craft.
Generates road masks and flattens roads in elevation data.
'''

import logging, json
import numpy as np
import rasterio
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
        from shapely.geometry import shape, mapping

        for feature in roads_data['features']:
            highway_type = feature['properties'].get('highway', 'unclassified')
            width_blocks = road_widths.get(highway_type, 2)
            
            # Convert blocks to meters
            # Width in meters = blocks * meters_per_block
            width_meters = width_blocks * scale_down
            
            # Reproject geometry from EPSG:4326 to target CRS
            try:
                geom_dict = transform_geom('EPSG:4326', crs, feature['geometry'])
                geom_shapely = shape(geom_dict)
                
                # Buffer to create polygon (width is diameter, so buffer by radius)
                # Ensure we have at least some width
                buffer_dist = max(0.5, width_meters / 2)
                road_poly = geom_shapely.buffer(buffer_dist)
                
                shapes.append((mapping(road_poly), 255)) # Burn 255 for road
                
                # Handle Meridian for Motorway and Trunk
                if highway_type in ['motorway', 'trunk', 'motorway_link', 'trunk_link']:
                    # 1 block meridian
                    meridian_width_meters = 1 * scale_down
                    meridian_buffer = meridian_width_meters / 2
                    meridian_poly = geom_shapely.buffer(meridian_buffer)
                    
                    # Burn 0 to cut the hole
                    shapes.append((mapping(meridian_poly), 0))
                    
            except Exception as e:
                log.warning(f"Failed to process road feature: {e}")
                pass
            
        if shapes: # Rasterize
            try: road_mask = rasterize(
                shapes,
                out_shape=(height, width),
                transform=transform,
                fill=0,
                dtype=np.uint8,
                all_touched=True,
                merge_alg=rasterio.enums.MergeAlg.replace 
            )
            except Exception as e:
                log.warning(f"Failed to rasterize roads: {e}")
        
        # Save road mask
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
        ) as dst: dst.write(road_mask, 1)
        
        log.info(f"[✓] Road mask saved: {output_file}")
        log.info(f"  Roads rasterized: {len(shapes)}")

    def road_mask_action(self, target, source, env):
        self.generate_road_mask(
            str(source[0]), str(source[1]), str(target[0]),
            self.config['roads']['road_widths'], 
            self.config['minecraft']['scale']['horizontal']
        )
        return 0
