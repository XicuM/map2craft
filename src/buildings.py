"""
Building processing for map2craft.
Computes building placements from OSM data.
"""

import os
import logging
import json
import numpy as np
import rasterio
from typing import Dict, List, Tuple
from pathlib import Path
from pyproj import Transformer

log = logging.getLogger(__name__)

class BuildingsProcessor:
    def __init__(self, config={}):
        self.config = config

    def compute_building_placements(self, buildings_geojson: str, elevation_file: str, 
                                    output_file: str, metadata_file: str,
                                    min_area: float = 25.0) -> None:
        ''' Compute building placements from OSM data.
        
            :param str buildings_geojson: Path to buildings GeoJSON file
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save placements JSON
            :param str metadata_file: Path to metadata JSON
            :param float min_area: Minimum building area in square meters
        '''
        log.info("Computing building placements...")
        
        # Load buildings and metadata
        with open(buildings_geojson, 'r') as f: buildings_data = json.load(f)
        with open(metadata_file, 'r') as f: metadata = json.load(f)
        
        # Load elevation for height lookup
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1)
            transform = src.transform
            raster_crs = src.crs
        
        # Setup coordinate transformation from WGS84 to Raster CRS
        transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
        
        placements = []
        
        for feature in buildings_data['features']:
            props = feature['properties']
            geom = feature['geometry']
            
            # Filter by area if available
            area = props.get('area_sq_m', 0)
            if area < min_area and 'building' in props:
                # If area is explicitly 0 but it's a building way, we might have failed calculation
                # Nodes (points) won't have area, so we keep them if they are explicitly marked as buildings
                if area > 0 or geom['type'] != 'Point': 
                     continue
            
            if geom['type'] != 'Point':
                continue
            
            lon, lat = geom['coordinates']
            
            # Project to terrain CRS
            proj_x, proj_y = transformer.transform(lon, lat)
            
            # Convert to pixel coordinates
            from src import geometry
            col, row = geometry.latlon_to_pixel(proj_x, proj_y, transform)
            
            # Check bounds
            if 0 <= row < elevation.shape[0] and 0 <= col < elevation.shape[1]:
                elev = float(elevation[row, col])
                
                placement = {
                    'id': feature.get('id'),
                    'lon': lon,
                    'lat': lat,
                    'elevation': elev,
                    'pixel_x': col,
                    'pixel_y': row,
                    'area': area,
                    'properties': props
                }
                placements.append(placement)
        
        # Save placements
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        output_data = {
            'count': len(placements),
            'placements': placements
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        log.info(f"[✓] Building placements saved: {output_file}")
        log.info(f"  Buildings placed: {len(placements)}")

    def building_placements_action(self, target, source, env):
        ''' SCons action for building placements.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        min_area = self.config['buildings'].get('min_area_sq_m', 0)
        self.compute_building_placements(
            str(source[0]), str(source[1]), str(target[0]),
            str(source[2]), min_area
        )
        return None
