import logging
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.features import rasterize
from PIL import Image
from shapely.geometry import shape, MultiLineString, LineString
from shapely.ops import unary_union

log = logging.getLogger(__name__)

class WaterwaysProcessor:
    def __init__(self, config=None):
        self.config = config or {}

    def generate_river_mask(self, waterways_geojson: str, elevation_file: str, 
                           output_file: str, river_width: int = 4,
                           stream_width: int = 2) -> None:
        """Generate a river/stream water mask from OSM waterway data."""
        log.info(f"Generating river mask (widths: river={river_width}b, stream={stream_width}b)...")
        
        if not Path(waterways_geojson).exists():
            log.warning(f"Waterways GeoJSON not found: {waterways_geojson}")
            return

        with open(waterways_geojson, 'r') as f: data = json.load(f)
        
        shapes = []
        with rasterio.open(elevation_file) as src: 
            shape_out, transform = src.shape, src.transform
            crs = src.crs
            # Blocks per degree cannot be trusted if CRS is projected (meters).
            # We use pixel size from transform.
            res_x, res_y = abs(transform[0]), abs(transform[4])
            
            # Setup transformer: EPSG:4326 (OSM) -> Target CRS
            from pyproj import Transformer
            transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True) # lon,lat -> x,y

            for feature in data.get('features', []):
                geom_4326 = shape(feature['geometry'])
                
                # Transform geometry
                # shapely.ops.transform expects a function that takes x, y, z=None
                from shapely.ops import transform as shapely_transform
                geom_proj = shapely_transform(transformer.transform, geom_4326)
                
                tags = feature.get('properties', {})
                w_type = tags.get('waterway', 'stream')
                
                width_blocks = river_width if w_type == 'river' else stream_width
                
                # Buffer dist = (blocks / 2) * (meters/block)
                # res_x is meters/pixel (block)
                buffer_dist = (width_blocks / 2.0) * res_x
                
                buffered_geom = geom_proj.buffer(buffer_dist)
                shapes.append((buffered_geom, 255))
        
        mask = np.zeros(shape_out, dtype=np.uint8)
        if shapes:
            try: 
                mask = rasterize(shapes, out_shape=shape_out, transform=transform, dtype=np.uint8)
            except Exception as e: 
                log.warning(f"Rasterization failed: {e}")
        
        # Save mask as PNG
        out_path = Path(output_file)
        if not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            
        Image.fromarray(mask, mode='L').save(out_path)
        
        log.info(f"[✓] River mask saved: {out_path} ({len(shapes)} features)")

    def river_mask_action(self, target, source, env):
        """SCons action for river mask generation."""
        wc = self.config['waterways']
        self.generate_river_mask(
            str(source[0]), str(source[1]), str(target[0]),
            wc.get('river_width_blocks', 4), 
            wc.get('stream_width_blocks', 2)
        )
