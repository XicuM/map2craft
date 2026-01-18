from pathlib import Path
import rasterio
import numpy as np
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from rasterio.transform import from_bounds
import logging

log = logging.getLogger(__name__)

class TerrainProcessor:
    def __init__(self, config={}):
        self.config = config
        
    def process_terrain(self, input_path, output_path, target_crs="EPSG:3857", resolution=5, bounds=None, preserve_coastline=True):
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
                
                dst.write(elev_dst, 1)

                # 2. Coastline Preservation: 
                # If enabled, enforces a sharp transition between land and water based on the original land mask.
                # This prevents "muddy" coasts when upscaling but creates artifacts if we have real bathymetry.
                if preserve_coastline:
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
                else:
                    # Bathymetry mode: Don't force hard coastlines, but DO fix cubic interpolation artifacts
                    # Cubic creates "ringing" near cliffs: positive bumps at base, then undershoots
                    # This appears as a 1-block land line separated from coast by 2 blocks
                    
                    # Read source to identify water areas (use 0 threshold to catch all water)
                    src_data = src.read(1)
                    water_src = (src_data < 0).astype(np.float32)  # Any water in source
                    
                    water_dst = np.zeros_like(elev_dst, dtype=np.float32)
                    reproject(
                        source=water_src,
                        destination=water_dst,
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=target_crs,
                        resampling=Resampling.nearest
                    )
                    
                    # Fix cubic ringing: areas that should be water but became positive
                    # Use a low threshold to catch pixels that are even partially water
                    ringing_artifacts = (water_dst > 0.1) & (elev_dst > 0) & (elev_dst < 2.0)  # Only fix small positive bumps
                    if np.any(ringing_artifacts):
                        # Force these to slightly negative to mark as water
                        elev_dst[ringing_artifacts] = -0.1
                        log.info(f"Fixed {np.sum(ringing_artifacts)} cubic ringing artifacts at cliffs")
                
                # Write final result
                dst.write(elev_dst, 1)
        log.info(f"Terrain processed.")

    def scale_raster_values(self, input_path, output_path, scale_factor):
        ''' Scales the values of a raster file by the given factor.
            Used to convert meters to blocks before merging.
            
            :param str input_path: Input raster path
            :param str output_path: Output raster path
            :param float scale_factor: Factor to multiply values by
        '''
        log.info(f"Scaling raster: {input_path} by {scale_factor:.4f}")
        with rasterio.open(input_path) as src:
            data = src.read(1)
            
            # Scale values
            scaled_data = data * scale_factor
            
            # Preserve nodata
            if src.nodata is not None:
                mask = (data == src.nodata)
                scaled_data[mask] = src.nodata
            
            meta = src.meta.copy()
            meta.update(dtype=rasterio.float32)
            
            with rasterio.open(output_path, 'w', **meta) as dst:
                dst.write(scaled_data.astype(np.float32), 1)

    def generate_heightmap_image(self, input_path, output_path, land_reference_path=None, is_pre_scaled=False, water_threshold_m=0.0):
        ''' Converts processed elevation (meters) to 16-bit PNG for WorldPainter.
            Uses "Smart Scaling" to fit Land Peak to Build Limit and Sea Level to 62.
            
            :param str input_path: Pass processed/merged elevation GeoTIFF
            :param str output_file: Path to output PNG
            :param str land_reference_path: Path to Land-Only elevation GeoTIFF (for defining scale)
            :param bool is_pre_scaled: If True, input data is already in BLOCKS (vertical scale 1.0)
            :param float water_threshold_m: Elevation threshold (meters) below which terrain is forced to Y=61
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
        if land_reference_path and Path(land_reference_path).exists():
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
                    else:
                        raise ValueError("Land reference file is empty")
            except Exception as e:
                log.error(f"Failed to read land reference {land_reference_path}: {e}")
                raise
        else:
             # User stated heightmap is always present, so if we are here for auto-fit, we should probably fail if we needed it?
             # However, the original code used 255.0 as default.
             # If we are in auto_fit mode, we NEED land_max.
             if mp['scale']['auto_fit']:
                 raise FileNotFoundError(f"Land reference file required for auto-fit but not found: {land_reference_path}")
             else:
                 # If not auto-fit, land_max might not be strictly used for scaling calculation if we use natural scale, 
                 # but let's stick to the user's request: "If something is not working, then, I must know."
                 # So if land_reference_path WAS expected but missing, we error.
                 # But wait, land_reference_path is optional in the signature? 
                 # run_scons passes it. 
                 # Let's set land_max to None and ensure we blow up if it's used.
                 land_max = 255.0 # We have to have a value to avoid UnboundLocalError later?
                 # No, let's look at usage.
                 pass

        # Simplified Approach based on user request:
        # "The heightmap is the most important file in the project, so it is always present."
        # This implies we should trust it exists and read it.
        
        if not land_reference_path or not Path(land_reference_path).exists():
             raise FileNotFoundError(f"Land reference file not found: {land_reference_path}")

        try:
            with rasterio.open(land_reference_path) as ref:
                ref_data = ref.read(1)
                if ref.nodata is not None:
                        ref_data = ref_data[ref_data != ref.nodata]
                
                if ref_data.size > 0:
                    land_max = float(np.max(ref_data))
                    if land_max < 10: land_max = 64
                else:
                    raise ValueError("Land reference file contains no valid data")
        except Exception as e:
             raise RuntimeError(f"Critical failure reading land reference: {e}")
        
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
            log.info(f"Auto-fit scaling: Land Peak {land_max}m -> Y={max_build}. Sea Level 0m -> Y={sea_level_y}.")
        else:
            # NATURAL SCALE MODE: Use configured vertical scale
            if is_pre_scaled:
                # Data is already scaled to blocks (meters * scale_factor was done earlier)
                # So here we treat 1 unit of elevation as 1 block
                scale_factor = 1.0 
                log.info(f"Pre-scaled mode: Data is already in blocks. Sea Level 0 -> Y={sea_level_y}.")
            else:
                # Scale factor is 1 block per N meters
                scale_factor = 1.0 / vertical_scale  # blocks per meter
                log.info(f"Natural scaling: {vertical_scale}m per block. Sea Level 0m -> Y={sea_level_y}.")
            
            # Calculate elevation range based on natural scale
            # We still want 0m at sea_level_y, but heights are determined by natural scale
            calc_max_elev = (max_build - sea_level_y) / scale_factor
            calc_min_elev = (min_build - sea_level_y) / scale_factor
             
        
        log.info(f"Clipping Range: {calc_min_elev:.2f}m to {calc_max_elev:.2f}m")
        
        with rasterio.open(input_path) as src:
            data = src.read(1)
            
            # Ensure water areas (below threshold) are capped at -1 block maximum (Y=61)
            # This prevents shallow water from appearing as land at sea level (Y=62)
            # Threshold is in meters, but data might be in blocks (if is_pre_scaled)
            water_threshold = water_threshold_m
            if is_pre_scaled:
                # If pre-scaled, elevation data is in blocks, so we multiply threshold by 1/vertical_scale
                # Actually, 1.0m threshold should become (1.0 / vertical_scale) blocks.
                water_threshold = water_threshold_m / vertical_scale
            
            water_mask = data < water_threshold
            if np.any(water_mask):
                # We force it to be at least -1.0 blocks below the sea_level_y anchor
                # This ensures the heightmap value for these pixels is < the value for 0m
                data[water_mask] = np.minimum(data[water_mask], -1.0 / (1.0 if not is_pre_scaled else 1.0)) # Force at least 1 block deep
                # Wait, if data is meters, force to -1.0 * vertical_scale meters? No.
                # data is in current units. 
                # If is_pre_scaled=False (meters): we want it to be -1.0 * vertical_scale meters to result in -1 block.
                # If is_pre_scaled=True (blocks): we want it to be -1.0 blocks.
                
                target_min_depth_in_units = -1.0 if is_pre_scaled else -1.0 * vertical_scale
                data[water_mask] = np.minimum(data[water_mask], target_min_depth_in_units)
                
                log.info(f"Clamped {np.sum(water_mask)} water pixels (below {water_threshold:.3f}) to at least 1 block deep (Y=61)")
            
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



