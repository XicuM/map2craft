"""
Building processing for map2craft.
Computes building placements from OSM data.
"""

import logging, json, yaml
import numpy as np
import rasterio
from typing import Dict, List, Tuple
from pathlib import Path
from pyproj import Transformer
from src import geometry

log = logging.getLogger(__name__)

class BuildingsProcessor:
    def __init__(self, config={}):
        self.config = config

    def determine_building_type(self, props: Dict) -> str:
        ''' Determine simplified building type from OSM properties. '''
        b_type = props.get('building', 'building')
        
        # known types that map to schematics
        KNOWN_TYPES = ['cathedral', 'church', 'lighthouse', 'windmill', 'tower', 'well']

        # If generic, look for more specific tags
        if b_type in ['yes', 'building', 'true']:
            for tag_key in ['man_made', 'historic', 'amenity', 'tourism']:
                val = props.get(tag_key)
                if val and val != 'yes':
                    b_type = val
                    break
        
        # Check against known types (exact or substring)
        if b_type not in KNOWN_TYPES:
            for kt in KNOWN_TYPES:
                if kt in b_type.lower():
                    return kt
            return 'building'
            
        return b_type

    def compute_building_placements(self, buildings_geojson: str, elevation_file: str, 
                                    output_file: str, metadata_file: str,
                                    min_area: float = 1.0, is_pre_scaled: bool = False) -> None:
        ''' Compute building placements from OSM data.
        
            :param str buildings_geojson: Path to buildings GeoJSON file
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save placements JSON
            :param str metadata_file: Path to metadata JSON
            :param float min_area: Minimum building area in square meters
            :param bool is_pre_scaled: If True, elevation is in blocks
        '''
        log.info("Computing building placements...")
        
        # Load buildings and metadata
        with open(buildings_geojson, 'r') as f: buildings_data = json.load(f)
        with open(metadata_file, 'r') as f: metadata = json.load(f)
        
        # Load elevation for height lookup
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1).astype(np.float32)
            
            if is_pre_scaled:
                v_scale = float(self.config['minecraft']['scale']['vertical'])
                log.info(f" Converting pre-scaled elevation (blocks) to meters for building heights (scale: {v_scale})")
                elevation *= v_scale

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
                if area > 0 or geom['type'] != 'Point': continue
            
            if geom['type'] != 'Point': continue
            lon, lat = geom['coordinates']
            
            # Project to terrain CRS
            proj_x, proj_y = transformer.transform(lon, lat)
            
            # Convert to pixel coordinates
            col, row = geometry.latlon_to_pixel(proj_x, proj_y, transform)
            
            # Check bounds
            if 0 <= row < elevation.shape[0] and 0 <= col < elevation.shape[1]:
                elev = float(elevation[row, col])
                
                b_type = self.determine_building_type(props)
                name = props.get('name')
                
                placement = {
                    'x': col,
                    'y': row,
                    'elevation': elev,
                    'type': b_type
                }
                if name:
                    placement['name'] = name
                    
                placements.append(placement)
        
        with open(output_file, 'w') as f: 
            yaml.dump({
                'count': len(placements),
                'placements': placements
            }, f, sort_keys=False)
        
        log.info(f"[✓] Building placements saved: {output_file}")
        log.info(f"  Buildings placed: {len(placements)}")

    def building_placements_action(self, target, source, env):
        ''' SCons action for building placements.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        is_pre_scaled = env.get('PRE_SCALED', False)
        
        # Find metadata.json in sources (it was moved in dependency list)
        metadata_file = next((str(s) for s in source if str(s).endswith('metadata.json')), None)
        if not metadata_file:
            # Fallback for old behavior or if something else is passed
            # Original was source[2], but now source[2] is likely the script
            # If we can't find it by name, maybe log a warning or try hardcoded path
            # But in the new pipeline it SHOULD be there.
            log.warning("Could not find metadata.json in sources, checking index 6...")
            if len(source) > 6:
                metadata_file = str(source[6])
                
        self.compute_building_placements(
            str(source[0]), str(source[1]), str(target[0]),
            metadata_file, is_pre_scaled=is_pre_scaled
        )
        return 0
