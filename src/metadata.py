"""
Generate metadata JSON file for WorldPainter script.
Contains all necessary information for world generation.
"""

import os
import json
import logging
import numpy as np
import rasterio
from typing import Dict, Any, Tuple, Optional

log = logging.getLogger(__name__)



class MetadataGenerator:
    def __init__(self, config=None):
        self.config = config or {}

    def generate_metadata(self, elevation_file: str, output_file: str, bounds: Dict[str, float], 
                        scale_down: int) -> None:
        ''' Generate metadata JSON from elevation data.
        
            :param str elevation_file: Path to elevation GeoTIFF
            :param str output_file: Path to save metadata JSON
            :param dict bounds: Dictionary with lon_min, lat_min, lon_max, lat_max
            :param int scale_down: Horizontal scale factor (1:N)
        '''
        log.info(f"Generating metadata...")
        log.info(f"  Input: {elevation_file}")
        
        with rasterio.open(elevation_file) as src:
            elevation = src.read(1).astype(np.float32)
            elevation = np.nan_to_num(elevation, nan=0.0)
            height, width = elevation.shape
            
            # Extract config values
            meta_cfg = self.config.get('metadata', {})
            mc_cfg = self.config.get('minecraft', {})
            
            lon_km_factor = meta_cfg.get('longitude_km_factor', 85)
            lat_km_factor = meta_cfg.get('latitude_km_factor', 111)
            min_y = mc_cfg.get('build_limit', {}).get('min', -64)
            max_y = mc_cfg.get('build_limit', {}).get('max', 320)
            sea_level_y = meta_cfg.get('minecraft_sea_level_y', 62)
            water_level_y = meta_cfg.get('worldpainter_default_water_level_y', 62)
            scale_percent = meta_cfg.get('worldpainter_scale_percent', 100)
            
            lon_min = bounds['lon_min']
            lat_min = bounds['lat_min']
            lon_max = bounds['lon_max']
            lat_max = bounds['lat_max']
            
            width_km = (lon_max - lon_min) * lon_km_factor
            height_km = (lat_max - lat_min) * lat_km_factor
            min_elev = float(elevation.min())
            max_elev = float(elevation.max())
            mc_width = width * scale_down
            mc_height = height * scale_down
            
            metadata = {
                "name": self.config['project']['name'],
                "description": f"Realistic terrain generated from real elevation data",
                "version": "1.0.0",
                "generated": None,  # Will be set by JS script
                "geographic": {
                    "bounds": {
                        "lon_min": lon_min,
                        "lat_min": lat_min,
                        "lon_max": lon_max,
                        "lat_max": lat_max
                    },
                    "center": {
                        "lon": (lon_min + lon_max) / 2,
                        "lat": (lat_min + lat_max) / 2
                    },
                    "dimensions_km": {
                        "width": width_km,
                        "height": height_km
                    }
                },
                "terrain": {
                    "elevation": {
                        "min_meters": min_elev,
                        "max_meters": max_elev,
                        "mean_meters": float(elevation.mean()),
                        "range_meters": max_elev - min_elev
                    },
                    "heightmap": {
                        "width_pixels": width,
                        "height_pixels": height,
                        "bit_depth": 16
                    },
                    "sea_level_meters": 0
                },
                "minecraft": {
                    "scale": {
                        "factor": scale_down,
                        "description": f"1:{scale_down} (1 block = {scale_down} meter(s))"
                    },
                    "dimensions_blocks": {
                        "width": mc_width,
                        "height": mc_height
                    },
                    "height_mapping": {
                        "min_minecraft_y": min_y,
                        "max_minecraft_y": max_y,
                        "sea_level_y": sea_level_y,
                        "description": "Maps real elevation to Minecraft Y coordinates"
                    }
                },
                "worldpainter": {
                    "suggested_settings": {
                        "default_water_level": water_level_y,
                        "map_format": f"org.pepsoft.anvil.{mc_cfg.get('version', '1.20.5')}",
                        "lower_build_limit": min_y,
                        "upper_build_limit": max_y,
                        "scale_percent": scale_percent
                    },
                    "height_mapping": {
                        "from_levels": [0, 65535],
                        "to_levels": [int(min_elev), int(max_elev)]
                    }
                },
                "files": {
                    "heightmap": os.path.basename(output_file.replace('_metadata.json', '_heightmap.png')),
                    "water_mask": "masks/" + self.config['project']['name'] + "_water_mask.png",
                    "slope_mask": "masks/" + self.config['project']['name'] + "_slope_mask.png"
                }
            }
            
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            log.info(f"  Metadata saved: {output_file}")
            log.info(f"Metadata Summary:")
            log.info(f"  Geographic extent: {width_km:.1f} x {height_km:.1f} km")
            log.info(f"  Heightmap size: {width} x {height} pixels")
            log.info(f"  Minecraft size: {mc_width} x {mc_height} blocks")
            log.info(f"  Elevation range: {min_elev:.1f}m to {max_elev:.1f}m")
            log.info(f"  Scale: 1:{scale_down}")

    def metadata_action(self, target, source, env):
        ''' SCons action for metadata generation.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        bounds = {
            'lon_min': self.config['geospatial']['bounds'][0],
            'lat_min': self.config['geospatial']['bounds'][1],
            'lon_max': self.config['geospatial']['bounds'][2],
            'lat_max': self.config['geospatial']['bounds'][3]
        }
        scale_down = self.config['minecraft'].get('scale', {}).get('horizontal', 20)
        
        self.generate_metadata(str(source[0]), str(target[0]), bounds, scale_down)
        return None

