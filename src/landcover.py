"""
Land cover data download and processing for map2craft.
Downloads ESA WorldCover data via Microsoft Planetary Computer.
"""

import os
import logging
import numpy as np
import rasterio
import requests
from rasterio.merge import merge
from rasterio.windows import from_bounds as window_from_bounds
from typing import Optional, Tuple, List
import datetime # Added for current_year

log = logging.getLogger(__name__)

LAND_COVER_NAMES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

class LandCoverProcessor:
    def __init__(self, config=None):
        self.config = config or {}

    def download_land_cover(self, bounds: Tuple[float, float, float, float], output_file: str) -> bool:
        ''' Download the latest available ESA WorldCover via Microsoft Planetary Computer STAC API.
        
            :param tuple bounds: (lon_min, lat_min, lon_max, lat_max)
            :param str output_file: Path to save the land cover GeoTIFF
            
            :return: True if successful, False otherwise
        '''
        current_year = datetime.datetime.now().year
        
        lon_min, lat_min, lon_max, lat_max = bounds
        print(f"Downloading latest land cover from Microsoft Planetary Computer...")
        
        try:
            import pystac_client
            import planetary_computer
            
            catalog = pystac_client.Client.open(
                "https://planetarycomputer.microsoft.com/api/stac/v1",
                modifier=planetary_computer.sign_inplace,
            )
            
            # Search for available years starting from current year down to 2020
            items = []
            final_year = None
            
            for year in range(current_year, 2019, -1): # Search from current year down to 2020 (inclusive)
                query_year = str(year)
                log.debug(f"Checking for WorldCover data in {query_year}...")
                
                search = catalog.search(
                    collections=["esa-worldcover"],
                    bbox=[lon_min, lat_min, lon_max, lat_max],
                    datetime=f"{query_year}-01-01/{query_year}-12-31",
                )
                
                results = list(search.items())
                if results:
                    items = results
                    final_year = query_year
                    break
            
            if not items:
                print(f"  [x] No WorldCover data found in range 2020-{current_year}")
                return False

            print(f"  [v] Found {len(items)} tiles for year {final_year}")
            
            sources = []
            for item in items:
                asset = item.assets.get("map")
                if asset:
                    href = asset.href
                    print(f"    - Opening: {item.id}")
                    src = rasterio.open(href)
                    sources.append(src)
                    
            if not sources:
                print("  [x] No valid map assets found")
                return False

            print(f"  Merging {len(sources)} tile(s)...")
            mosaic, mosaic_transform = merge(sources, bounds=(lon_min, lat_min, lon_max, lat_max))
            
            for src in sources:
                src.close()

            print(f"  Saving cropped land cover...")
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            with rasterio.open(
                output_file,
                'w',
                driver='GTiff',
                height=mosaic.shape[1],
                width=mosaic.shape[2],
                count=1,
                dtype=mosaic.dtype,
                crs='EPSG:4326',
                transform=mosaic_transform,
                compress='lzw',
                nodata=0,
            ) as dst:
                dst.write(mosaic[0], 1)
                
            print(f"  [v] Land cover saved: {output_file}")
            self.print_land_cover_stats(output_file)
            return True
            
        except Exception as e:
            print(f"  [x] Error downloading from Planetary Computer: {e}")
            import traceback
            traceback.print_exc()
            return False


    def print_land_cover_stats(self, land_cover_file: str) -> None:
        ''' Print land cover class distribution stats.
        
            :param str land_cover_file: Path to land cover GeoTIFF
        '''
        with rasterio.open(land_cover_file) as src:
            data = src.read(1)
            
        print(f"\nLand cover distribution:")
        print(f"  Size: {data.shape[1]} x {data.shape[0]} pixels")
        
        unique, counts = np.unique(data, return_counts=True)
        total = data.size
        
        for value, count in zip(unique, counts):
            name = LAND_COVER_NAMES.get(int(value), f"Unknown ({int(value)})")
            percentage = (count / total) * 100
            print(f"  {name}: {percentage:.1f}%")

    def download_land_cover_action(self, target, source, env):
        ''' SCons action to download land cover.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        
        success = self.download_land_cover(bounds_tuple, str(target[0]))
        if not success:
            print("Warning: Land cover download failed, biomes will use elevation-only classification")
        return None

