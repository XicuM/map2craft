import rasterio
import numpy as np
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from rasterio.transform import from_bounds
import os

import rasterio
import numpy as np
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from rasterio.transform import from_bounds
import os

class TerrainProcessor:
    def __init__(self, config=None):
        self.config = config or {}
        
    def process_terrain(self, input_path, output_path, target_crs="EPSG:3857", resolution=5, bounds=None):
        ''' Reprojects, crops to bounds, and normalizes elevation data.
        
            :param str input_path: Input elevation file
            :param str output_path: Output processed file
            :param str target_crs: Target CRS (default: EPSG:3857 Web Mercator)
            :param int resolution: Resolution in meters
            :param tuple bounds: Optional (lon_min, lat_min, lon_max, lat_max) to crop to
        '''
        with rasterio.open(input_path) as src:
            # If bounds provided, calculate transform for those bounds
            if bounds:
                # Transform bounds from WGS84 to target CRS
                target_bounds = transform_bounds('EPSG:4326', target_crs, *bounds)
                
                # Calculate transform for the cropped area
                width = int((target_bounds[2] - target_bounds[0]) / resolution)
                height = int((target_bounds[3] - target_bounds[1]) / resolution)
                transform = from_bounds(*target_bounds, width, height)
            else:
                # Use full extent
                transform, width, height = calculate_default_transform(
                    src.crs, target_crs, src.width, src.height, *src.bounds, resolution=resolution
                )
            
            kwargs = src.meta.copy()
            kwargs.update({
                'crs': target_crs,
                'transform': transform,
                'width': width,
                'height': height,
                'dtype': rasterio.float32,
                'nodata': None
            })

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with rasterio.open(output_path, 'w', **kwargs) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=Resampling.bilinear
                )

    def generate_heightmap_image(self, input_path, output_path, min_elev=-64, max_elev=320):
        ''' Converts processed elevation (meters) to 16-bit PNG for WorldPainter.
            Maps [min_elev, max_elev] to [0, 65535].

            :param str input_path: Path to processed elevation GeoTIFF
            :param str output_path: Path to output PNG
            :param float min_elev: Minimum elevation in meters (maps to 0)
            :param float max_elev: Maximum elevation in meters (maps to 65535)
        '''
        with rasterio.open(input_path) as src:
            data = src.read(1)
            
            # Clip to bounds
            data = np.clip(data, min_elev, max_elev)
            
            # Normalize to 0-65535
            span = max_elev - min_elev
            if span == 0: span = 1
            
            normalized = ((data - min_elev) / span * 65535).astype(np.uint16)
            
            meta = src.meta.copy()
            meta.update(dtype=rasterio.uint16, nodata=None, driver='PNG')
            
            with rasterio.open(output_path, 'w', **meta) as dst:
                dst.write(normalized, 1)

    def process_action(self, target, source, env):
        ''' SCons action to process terrain.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        res = self.config['geospatial']['resolution']
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        
        self.process_terrain(str(source[0]), str(target[0]), resolution=res, bounds=bounds_tuple)
        return None

    def heightmap_action(self, target, source, env):
        ''' SCons action to generate heightmap.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        min_h = self.config['minecraft']['build_limit']['min']
        max_h = self.config['minecraft']['build_limit']['max']
        self.generate_heightmap_image(str(source[0]), str(target[0]), min_elev=min_h, max_elev=max_h)
        return None

