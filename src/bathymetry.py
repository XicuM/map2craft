import logging
from pathlib import Path
from typing import Tuple

import numpy as np
import rasterio
import requests
from rasterio.warp import reproject, Resampling

log = logging.getLogger(__name__)

def download_emodnet_bathymetry(bounds: Tuple[float, float, float, float], 
                                output_file: str, margin_km: float = 40.0) -> bool:
    ''' Download EMODnet bathymetry data for the specified bounds.
    
        :param tuple bounds: (lon_min, lat_min, lon_max, lat_max)
        :param str output_file: Output GeoTIFF path
        :param float margin_km: Margin to add around bounds in km
        
        :return: True if successful, False otherwise
    '''
    lon_min, lat_min, lon_max, lat_max = bounds
    log.info(f"Downloading EMODnet bathymetry for bounds: {bounds}")
    
    # Calculate expanded bounds
    deg_per_km = 1.0 / 111.32
    dlat = margin_km * deg_per_km
    dlon = margin_km * (deg_per_km / max(0.1, np.cos(np.radians((lat_min + lat_max) / 2.0))))
    
    req_bounds = (
        max(-180.0, lon_min - dlon), max(-90.0, lat_min - dlat),
        min(180.0, lon_max + dlon), min(90.0, lat_max + dlat)
    )
    
    base_url = "https://ows.emodnet-bathymetry.eu/wcs"
    coverages = ['emodnet:mean_multicolour', 'emodnet:mean_atlas_land', 'emodnet:mean']
    
    for coverage in coverages:
        params = {
            'service': 'WCS', 'version': '1.0.0', 'request': 'GetCoverage',
            'coverage': coverage, 'crs': 'EPSG:4326', 'format': 'GeoTIFF',
            'bbox': ",".join(map(str, req_bounds)), 'resx': 0.00208333, 'resy': 0.00208333,
        }
        try:
            resp = requests.get(base_url, params=params, timeout=180, stream=True)
            resp.raise_for_status()
            
            if 'tiff' not in resp.headers.get('Content-Type', '').lower():
                continue

            out_path = Path(output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            with rasterio.open(out_path) as src:
                data = src.read(1)
                log.info(f" [v] Downloaded {coverage}: {data.shape[1]}x{data.shape[0]}, depth {data.min():.1f}m to {data.max():.1f}m")
                return True
        except Exception as e:
            log.warning(f" Failed with {coverage}: {e}")
            
    return False

def merge_land_and_bathymetry(land_file: str, bathymetry_file: str, 
                              output_file: str, sea_level: float = 0.0) -> None:
    ''' Merge land elevation with underwater bathymetry using raster reproject.
    
        :param str land_file: Path to land elevation GeoTIFF
        :param str bathymetry_file: Path to bathymetry GeoTIFF
        :param str output_file: Path to save merged output
        :param float sea_level: Sea level in meters
    '''
    log.info("Merging land and bathymetry data...")
    
    with rasterio.open(land_file) as l_src:
        land_data = l_src.read(1).astype(np.float32)
        meta = l_src.meta.copy()
        l_trans, l_crs = l_src.transform, l_src.crs

    with rasterio.open(bathymetry_file) as b_src:
        bathy_raw = b_src.read(1).astype(np.float32)
        bathy_resampled = np.full(land_data.shape, np.nan, dtype=np.float32)
        
        reproject(
            source=bathy_raw, destination=bathy_resampled,
            src_transform=b_src.transform, src_crs=b_src.crs,
            dst_transform=l_trans, dst_crs=l_crs,
            resampling=Resampling.bilinear, src_nodata=b_src.nodata, dst_nodata=np.nan
        )

    # Standardize bathymetry to negative values if median suggests they are depths
    if np.any(finite := np.isfinite(bathy_resampled)) and np.nanmedian(bathy_resampled) > 0:
        bathy_resampled[finite] = -np.abs(bathy_resampled[finite])
    
    # Merge: use bathy where land is <= sea_level AND bathy is valid/below sea_level
    use_bathy = (land_data <= sea_level) & np.isfinite(bathy_resampled) & (bathy_resampled < sea_level)
    merged = np.where(use_bathy, bathy_resampled, land_data)
    
    log.info(f" Bathymetry used: {int(np.sum(use_bathy)):,} pixels ({np.mean(use_bathy)*100:.1f}%)")
    
    meta.update(dtype=rasterio.float32, nodata=None)
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_file, 'w', **meta) as dst:
        dst.write(merged, 1)
    log.info(f" [v] Saved: {output_file}")
