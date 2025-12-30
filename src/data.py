import requests
import numpy as np
import rasterio
from rasterio.merge import merge
import os
import logging

log = logging.getLogger(__name__)

class ElevationLoader:
    def __init__(self, config={}):
        self.config = config

    def download_copernicus_tile(self, lat, lon, output_dir):
        ''' Download Copernicus DEM tile (GLO-30) from AWS Open Data.
            Tiles are named by SW corner.

            :param float lat: Latitude of the tile
            :param float lon: Longitude of the tile
            :param str output_dir: Directory to save the tile
            
            :return: Path to the downloaded tile or None if failed
        '''
        tile_lat = int(np.floor(lat))
        tile_lon = int(np.floor(lon))
        
        lat_code = f"N{abs(tile_lat):02d}" if tile_lat >= 0 else f"S{abs(tile_lat):02d}"
        lon_code = f"E{abs(tile_lon):03d}" if tile_lon >= 0 else f"W{abs(tile_lon):03d}"
        
        tile_name = f"Copernicus_DSM_COG_10_{lat_code}_00_{lon_code}_00_DEM"
        output_file = os.path.join(output_dir, f"{tile_name}.tif")
        
        if os.path.exists(output_file):
            print(f"  Tile {lat_code}{lon_code} already exists")
            return output_file
            
        url = f"https://copernicus-dem-30m.s3.amazonaws.com/{tile_name}/{tile_name}.tif"
        print(f"  Downloading tile {lat_code}{lon_code} from AWS...")
        
        try:
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(output_file, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return output_file
        except Exception as e:
            print(f"  Error downloading {tile_name}: {e}")
            return None

    def download_elevation(self, bounds, output_path, resolution_meters=30):
        ''' Downloads Copernicus DEM tiles covering the bounds and merges them.
            (AWS Open Data, free, no auth)

            :param tuple bounds: (lon_min, lat_min, lon_max, lat_max)
            :param str output_path: Path to save the merged GeoTIFF
            :param int resolution_meters: Target resolution in meters (default 30)
        '''
        lon_min, lat_min, lon_max, lat_max = bounds
        
        print(f"Downloading Copernicus DEM for bounds: {bounds}...")
        
        # 1. Determine tiles needed
        margin = 0.02
        tiles_needed = []
        for lat in range(int(np.floor(lat_min - margin)), int(np.ceil(lat_max + margin))):
            for lon in range(int(np.floor(lon_min - margin)), int(np.ceil(lon_max + margin))):
                tiles_needed.append((lat, lon))
                
        print(f"Need {len(tiles_needed)} tiles.")
        
        temp_dir = os.path.join(os.path.dirname(output_path), "tiles_temp")
        os.makedirs(temp_dir, exist_ok=True)
        
        # 2. Download tiles
        tile_files = []
        for lat, lon in tiles_needed:
            tf = self.download_copernicus_tile(lat, lon, temp_dir)
            if tf:
                tile_files.append(tf)
                
        if not tile_files:
            raise RuntimeError("No tiles downloaded. Check internet connection or bounds.")
            
        # 3. Merge tiles
        print(f"Merging {len(tile_files)} tiles...")
        src_files_to_close = []
        try:
            src_files = []
            for tf in tile_files:
                src = rasterio.open(tf)
                src_files.append(src)
                src_files_to_close.append(src)
                
            mosaic, out_trans = merge(src_files)
            
            out_meta = src_files[0].meta.copy()
            out_meta.update({
                "driver": "GTiff",
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": out_trans,
                "compress": "lzw"
            })
            
            # Save merged
            with rasterio.open(output_path, "w", **out_meta) as dest:
                dest.write(mosaic)

            print(f"Saved merged elevation to {output_path}")
            
        finally:
            for src in src_files_to_close:
                src.close()

    def download_action(self, target, source, env):
        ''' SCons action to download elevation.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        self.download_elevation(bounds_tuple, str(target[0]), resolution_meters=30)
        return None
