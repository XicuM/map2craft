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
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=2)
        log.info(f"[v] Saved {len(geojson['features'])} features to {target}")



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


    def download_buildings(self, bounds: Tuple[float, float, float, float], output_file: str) -> None:
        ''' Download building data from OpenStreetMap.
        
            :param tuple bounds: Bounding box (lon_min, lat_min, lon_max, lat_max)
            :param str output_file: Path to save GeoJSON
        '''
        log.info(f"Downloading buildings from OpenStreetMap...")
        
        client = OSMClient(bounds)
        
        # Query for all buildings
        elements = [
            'way["building"]',
            'node["building"]',
        ]
        
        osm_data = client._execute_query(client._build_query(elements))
        
        # Convert to point features (centroids for ways)
        features = []
        for element in osm_data.get('elements', []):
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

    def download_roads_action(self, target, source, env):
        ''' SCons action for downloading roads.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        road_types = list(self.config.get('roads', {}).get('road_widths', {}).keys())
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        self.download_roads(bounds_tuple, str(target[0]), road_types)
        return None

    def download_buildings_action(self, target, source, env):
        ''' SCons action for downloading buildings.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        self.download_buildings(bounds_tuple, str(target[0]))
        return None

    def download_waterways_action(self, target, source, env):
        ''' SCons action for downloading waterways.
            
            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        self.download_waterways(bounds_tuple, str(target[0]))
        return None

