
import rasterio
import numpy as np
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from rasterio.transform import from_bounds
import os

import logging

log = logging.getLogger(__name__)

class TerrainProcessor:
    def __init__(self, config={}):
        self.config = config
        
    def process_terrain(self, input_path, output_path, target_crs="EPSG:3857", resolution=5, bounds=None):
        ''' Reprojects, crops to bounds, and normalizes elevation data.
        
            :param str input_path: Input elevation file
            :param str output_path: Output processed file
            :param str target_crs: Target CRS (default: EPSG:3857 Web Mercator)
            :param int resolution: Resolution in meters
            :param tuple bounds: Optional (lon_min, lat_min, lon_max, lat_max) to crop to
        '''
        log.info(f"Processing terrain: {input_path} -> {output_path}")
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
                # 1. Resample Elevation using Cubic for smooth terrain
                # We do this into a memory array first so we can read and modify it
                elev_dst = np.zeros((height, width), dtype=np.float32)
                
                reproject(
                    source=rasterio.band(src, 1),
                    destination=elev_dst,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=Resampling.cubic
                )
                
                # 2. Coastline Preservation: 
                # Resample a binary "Land Mask" using Nearest neighbor to keep it sharp
                # Create a binary mask of the source land (elev >= 0)
                src_data = src.read(1)
                land_mask_src = (src_data >= 0).astype(np.float32)
                
                land_mask_dst = np.zeros_like(elev_dst, dtype=np.float32)
                reproject(
                    source=land_mask_src,
                    destination=land_mask_dst,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=Resampling.nearest  # Sharp!
                )
                
                # Fix Coastline: Ensure land pixels have elevation >= 0 and water pixels < 0
                # Using 0.01/-0.01 as small buffers to avoid ambiguity
                land_indices = land_mask_dst >= 0.5
                water_indices = land_mask_dst < 0.5
                
                # Force Land to be >= 0.01m if Cubic made it < 0
                land_correction = (land_indices) & (elev_dst < 0)
                elev_dst[land_correction] = 0.01
                
                # Force Water to be < 0m if Cubic made it >= 0
                water_correction = (water_indices) & (elev_dst >= 0)
                elev_dst[water_correction] = -0.01
                
                dst.write(elev_dst, 1)
        log.info(f"Terrain processed.")

    def generate_heightmap_image(self, input_path, output_path, land_reference_path=None):
        ''' Converts processed elevation (meters) to 16-bit PNG for WorldPainter.
            Uses "Smart Scaling" to fit Land Peak to Build Limit and Sea Level to 62.
            
            :param str input_path: Pass processed/merged elevation GeoTIFF
            :param str output_path: Path to output PNG
            :param str land_reference_path: Path to Land-Only elevation GeoTIFF (for defining scale)
        '''
        log.info(f"Generating heightmap image: {output_path}")
        
        # Config
        mp = self.config['minecraft']
        min_build = mp['build_limit']['min']
        max_build = mp['build_limit']['max'] 
        vertical_scale = mp['scale']['vertical']
        
        # Target Y level for 0m elevation (terrain at sea level)
        # Using configured sea level (usually 63). 
        # If sea_level is 63, then 0m elevation maps to Y=63.
        sea_level_y = mp.get('sea_level', 63)
        
        min_elev_limit = -10000 # Safety floor
        
        # Determine Scaling Parameters
        land_max = 255.0 # Default fallback
        if land_reference_path and os.path.exists(land_reference_path):
            try:
                with rasterio.open(land_reference_path) as ref:
                    # Read finding max value, handling nodata
                    ref_data = ref.read(1)
                    # Filter nodata if set
                    if ref.nodata is not None:
                         ref_data = ref_data[ref_data != ref.nodata]
                    
                    if ref_data.size > 0:
                        land_max = float(np.max(ref_data))
                        # Avoid strictly 0 max if flat
                        if land_max < 10: land_max = 64
            except Exception as e:
                log.warning(f"Failed to read land reference {land_reference_path}: {e}")
        
        if mp['scale']['auto_fit']:
            # AUTO-FIT MODE: Scale to fill build limits
            # Goal: Map 0m to sea_level_y, and land_max to max_build
            # Scale (blocks per meter)
            elevation_range_land = max(land_max, 1.0)
            blocks_above_sea = max_build - sea_level_y
            
            if blocks_above_sea <= 0: blocks_above_sea = 100 # Sanity check
            
            scale_factor = blocks_above_sea / elevation_range_land
            
            # Calculate the theoretical meter values that correspond to min_build and max_build
            # Y = Y_sea + (Elev - 0) * Scale
            # Elev = (Y - Y_sea) / Scale
            
            calc_max_elev = (max_build - sea_level_y) / scale_factor # Should be land_max
            calc_min_elev = (min_build - sea_level_y) / scale_factor
            
            log.info(f"Auto-fit scaling: Land Peak {land_max}m -> Y={max_build}. Sea Level 0m -> Y={sea_level_y}.")
        else:
            # NATURAL SCALE MODE: Use configured vertical scale
            # Scale factor is 1 block per N meters
            scale_factor = 1.0 / vertical_scale  # blocks per meter
            
            # Calculate elevation range based on natural scale
            # We still want 0m at sea_level_y, but heights are determined by natural scale
            calc_max_elev = (max_build - sea_level_y) / scale_factor
            calc_min_elev = (min_build - sea_level_y) / scale_factor
            
            log.info(f"Natural scaling: {vertical_scale}m per block. Sea Level 0m -> Y={sea_level_y}.")
        
        log.info(f"Clipping Range: {calc_min_elev:.2f}m to {calc_max_elev:.2f}m")
        
        with rasterio.open(input_path) as src:
            data = src.read(1)
            
            # Clip to bounds
            data = np.clip(data, calc_min_elev, calc_max_elev)
            
            # Normalize to 0-65535 map
            # 0 = calc_min_elev, 65535 = calc_max_elev
            span = calc_max_elev - calc_min_elev
            if span == 0: span = 1
            
            normalized = ((data - calc_min_elev) / span * 65535).astype(np.uint16)
            
            meta = src.meta.copy()
            meta.update(dtype=rasterio.uint16, nodata=None, driver='PNG')
            
            with rasterio.open(output_path, 'w', **meta) as dst:
                dst.write(normalized, 1)
                
        # Write sidecar JSON for validation/reference (optional)
        import json
        sidecar = output_path + ".json"
        with open(sidecar, 'w') as f:
            json.dump({
                "min_meters": calc_min_elev,
                "max_meters": calc_max_elev,
                "scale_factor_vertical": scale_factor,
                "sea_level_block": sea_level_y,
                "min_y": min_build,
                "max_y": max_build
            }, f, indent=2)
            
        log.info("Heightmap generated.")

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
            Source[0]: Merged/Processed Elevation
            Source[1]: (Optional) Land Raw Elevation for Reference
        '''
        ref_path = str(source[1]) if len(source) > 1 else None
        self.generate_heightmap_image(str(source[0]), str(target[0]), land_reference_path=ref_path)
        return None

