"""
Waterway processing for map2craft.
Generates river masks and carves channels in elevation data.
"""

import logging
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.features import rasterize
from PIL import Image

log = logging.getLogger(__name__)

class WaterwaysProcessor:
    def __init__(self, config=None):
        self.config = config or {}

    def generate_river_mask(self, waterways_geojson: str, elevation_file: str, 
                           output_file: str, river_width: int = 4,
                           stream_width: int = 2) -> None:
        """Generate a river/stream water mask from OSM waterway data."""
        log.info("Generating river mask...")
        
        with open(waterways_geojson, 'r') as f: data = json.load(f)
        with rasterio.open(elevation_file) as src: shape, transform = src.shape, src.transform
        shapes = [(f['geometry'], 255) for f in data.get('features', [])]
        
        mask = np.zeros(shape, dtype=np.uint8)
        if shapes:
            try: mask = rasterize(shapes, out_shape=shape, transform=transform, dtype=np.uint8)
            except Exception as e: log.warning(f"Rasterization failed: {e}")
        
        # Save mask as PNG
        out_path = Path(output_file)
        Image.fromarray(mask, mode='L').save(out_path)
        
        log.info(f"[✓] River mask saved: {out_path} ({len(shapes)} features)")

    def river_mask_action(self, target, source, env):
        """SCons action for river mask generation."""
        wc = self.config['waterways']
        self.generate_river_mask(
            str(source[0]), str(source[1]), str(target[0]),
            wc['river_width_blocks'], 
            wc['stream_width_blocks']
        )
