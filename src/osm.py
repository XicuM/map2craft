"""
OpenStreetMap data acquisition client for map2craft.
Downloads roads, buildings, and waterways via Overpass API.
"""

import json
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional
import requests
from pyproj import Transformer

log = logging.getLogger(__name__)


class OSMClient:
    """
    Client for downloading OpenStreetMap data via Overpass API.
    """
    
    def __init__(self, bounds: Tuple[float, float, float, float], 
                 timeout: int = 180, retries: int = 5):
        """
        Initialize OSM client.
        
        Args:
            bounds: Bounding box (lon_min, lat_min, lon_max, lat_max)
            timeout: Query timeout in seconds
            retries: Number of retry attempts on failure
        """
        self.bounds = bounds
        self.timeout = timeout
        self.retries = retries
        self.overpass_urls = [
            'https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.osm.ch/api/interpreter',
        ]
        self.url_index = 0
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'map2craft/1.0.0 (+https://github.com/lucas-mancini/map2craft)'})
    
    def _to_bbox_str(self) -> str:
        """Convert bounds to Overpass bbox format (lat_min, lon_min, lat_max, lon_max)."""
        lon_min, lat_min, lon_max, lat_max = self.bounds
        return f"{lat_min},{lon_min},{lat_max},{lon_max}"
    
    def _build_query(self, elements: List[str]) -> str:
        ''' Build Overpass QL query from element specifications.
        
            :param list elements: List of Overpass QL element queries
            
            :return: Complete Overpass QL query string
        '''
        bbox = self._to_bbox_str()
        element_queries = '\n  '.join(f'{elem}({bbox});' for elem in elements)
        
        return f"""[out:json][timeout:{self.timeout}];
(
  {element_queries}
);
out geom;"""
    
    def _execute_query(self, query: str) -> dict:
        """
        Execute Overpass API query with retry logic and mirror rotation.
        
        Args:
            query: Overpass QL query string
            
        Returns:
            Parsed JSON response
        """
        last_error = None
        
        for attempt in range(self.retries):
            url = self.overpass_urls[self.url_index % len(self.overpass_urls)]
            try:
                log.info(f"Querying Overpass API (attempt {attempt + 1}/{self.retries}) via {url}...")
                response = self.session.post(
                    url,
                    data=query,
                    timeout=self.timeout + 10
                )
                
                if response.status_code == 429:
                    log.warning("Rate limited by Overpass API. Rotating mirror...")
                    self.url_index += 1
                    time.sleep(10.0)
                    continue
                    
                response.raise_for_status()
                return response.json()
                
            except (requests.RequestException, json.JSONDecodeError) as e:
                last_error = e
                log.warning(f"Query failed at {url}: {e}")
                
                # Rotate mirror on failure
                self.url_index += 1
                
                if attempt < self.retries - 1:
                    delay = 5.0 * (attempt + 1)  # Exponential backoff
                    log.info(f"Retrying with mirror {self.overpass_urls[self.url_index % len(self.overpass_urls)]} in {delay}s...")
                    time.sleep(delay)
                    continue
        
        raise last_error or requests.RequestException("Query failed after all retries")
    
    def _osm_to_geojson(self, osm_data: dict, feature_type: str = 'LineString') -> dict:
        """
        Convert Overpass API response to GeoJSON.
        
        Args:
            osm_data: Parsed Overpass API JSON response
            feature_type: GeoJSON geometry type ('LineString', 'Point', 'Polygon')
            
        Returns:
            GeoJSON FeatureCollection
        """
        features = []
        
        for element in osm_data.get('elements', []):
            if 'geometry' not in element or not element['geometry']:
                continue
            
            # Extract coordinates
            coords = [(node['lon'], node['lat']) for node in element['geometry']]
            
            # Build geometry based on type
            if feature_type == 'LineString':
                geometry = {'type': 'LineString', 'coordinates': coords}
            elif feature_type == 'Point':
                geometry = {'type': 'Point', 'coordinates': coords[0] if coords else [0, 0]}
            elif feature_type == 'Polygon':
                geometry = {'type': 'Polygon', 'coordinates': [coords]}
            else:
                geometry = {'type': 'LineString', 'coordinates': coords}
            
            features.append({
                'type': 'Feature',
                'id': element.get('id'),
                'geometry': geometry,
                'properties': element.get('tags', {})
            })
        
        return {
            'type': 'FeatureCollection',
            'features': features
        }
    
    def _save_geojson(self, geojson: dict, target: Path) -> None:
        """Save GeoJSON to file."""
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=2)
        log.info(f"[✓] Saved {len(geojson['features'])} features to {target}")



class OsmLoader:
    def __init__(self, config=None):
        self.config = config or {}

    def download_roads(self, bounds: Tuple[float, float, float, float], output_file: str,
                    road_types: Optional[List[str]] = None) -> None:
        ''' Download road data from OpenStreetMap.
        
            :param tuple bounds: Bounding box (lon_min, lat_min, lon_max, lat_max)
            :param str output_file: Path to save GeoJSON
            :param list road_types: List of highway types to download
        '''
        if road_types is None:
            road_types = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 
                        'residential', 'service', 'unclassified']
        
        log.info(f"Downloading roads from OpenStreetMap...")
        log.info(f"  Road types: {', '.join(road_types)}")
        
        client = OSMClient(bounds)
        elements = [f'way["highway"="{road_type}"]' for road_type in road_types]
        osm_data = client._execute_query(client._build_query(elements))
        geojson = client._osm_to_geojson(osm_data, feature_type='LineString')
        client._save_geojson(geojson, Path(output_file))


    def download_buildings(self, bounds: Tuple[float, float, float, float], output_file: str,
                          building_types: List[str] = None) -> None:
        ''' Download building data from OpenStreetMap.
        
            :param tuple bounds: Bounding box (lon_min, lat_min, lon_max, lat_max)
            :param str output_file: Path to save GeoJSON
        '''
        log.info(f"Downloading buildings from OpenStreetMap...")
        
        client = OSMClient(bounds)
        
        # Join types for regex OR match
        # Map 'well' to 'water_well' for man_made tags
        mm_types = [t if t != 'well' else 'water_well' for t in building_types]
        
        types_regex = f"^({'|'.join(building_types)})$"
        mm_regex = f"^({'|'.join(mm_types)})$"
        
        elements = [
            f'way["building"~"{types_regex}"]',
            f'node["building"~"{types_regex}"]',
            f'way["man_made"~"{mm_regex}"]',
            f'node["man_made"~"{mm_regex}"]',
        ]
        
        osm_data = client._execute_query(client._build_query(elements))
        
        # Convert to point features (centroids for ways)
        features = []
        for element in osm_data.get('elements', []):
            tags = element.get('tags', {})
            
            # Filter by name: name check removed to allow unnamed buildings
            # (Filtering will be handled in buildings.py based on config)
            name = tags.get('name')

            
            # Normalize tags: Prioritize specific types over generic 'building=yes'
            # Landmark objects often have both building=yes and man_made=lighthouse
            b_val = tags.get('building')
            mm_val = tags.get('man_made')
            
            if mm_val:
                # Map back water_well to well for consistency
                norm_mm = 'well' if mm_val == 'water_well' else mm_val
                
                # If building tag is generic or missing, use the more specific man_made tag
                if not b_val or b_val == 'yes' or b_val == 'building':
                    tags['building'] = norm_mm
            
            if element['type'] == 'node':
                geometry = {
                    'type': 'Point',
                    'coordinates': [element['lon'], element['lat']]
                }
            elif element['type'] == 'way' and 'geometry' in element:
                coords = [(node['lon'], node['lat']) for node in element['geometry']]
                if coords:
                    # Calculate centroid
                    lon_avg = sum(c[0] for c in coords) / len(coords)
                    lat_avg = sum(c[1] for c in coords) / len(coords)
                    geometry = {'type': 'Point', 'coordinates': [lon_avg, lat_avg]}
                    
                    # Calculate approximate area in sq meters (using EPSG:3857 for simplicity)
                    try:
                        transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
                        proj_coords = [transformer.transform(lon, lat) for lon, lat in coords]
                        # Shoelace formula for area
                        area = 0.5 * abs(sum(proj_coords[i][0] * proj_coords[i+1][1] - proj_coords[i+1][0] * proj_coords[i][1]
                                            for i in range(len(proj_coords)-1)))
                        element['tags']['area_sq_m'] = area
                    except Exception:
                        element['tags']['area_sq_m'] = 0
                else:
                    continue
            else:
                continue
            
            features.append({
                'type': 'Feature',
                'id': element.get('id'),
                'geometry': geometry,
                'properties': element.get('tags', {})
            })
        
        geojson = {'type': 'FeatureCollection', 'features': features}
        client._save_geojson(geojson, Path(output_file))


    def download_waterways(self, bounds: Tuple[float, float, float, float], output_file: str) -> None:
        ''' Download waterway data from OpenStreetMap.
        
            :param tuple bounds: Bounding box (lon_min, lat_min, lon_max, lat_max)
            :param str output_file: Path to save GeoJSON
        '''
        log.info(f"Downloading waterways from OpenStreetMap...")
        
        client = OSMClient(bounds)
        elements = [
            'way["waterway"="river"]',
            'way["waterway"="stream"]',
        ]
        
        osm_data = client._execute_query(client._build_query(elements))
        geojson = client._osm_to_geojson(osm_data, feature_type='LineString')
        client._save_geojson(geojson, Path(output_file))



