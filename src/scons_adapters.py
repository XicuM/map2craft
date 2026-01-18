"""
SCons Adapters for Map2Craft.
This module bridges the SCons build system interactions with the pure Python logic modules.
It extracts targets, sources, and environment variables, and calls the appropriate methods.
"""

from pathlib import Path
import json
import yaml
import logging

from src import (
    geospatial, osm, worldpainter, visualize, amulet_editor, biomes
)

log = logging.getLogger(__name__)

class Map2CraftSConsAdapter:
    def __init__(self, config):
        self.config = config
        
        # Initialize Logic Components
        self.geo = geospatial.TerrainProcessor(config)
        self.osm = osm.OsmLoader(config)
        self.wp = worldpainter.WorldPainterInterface(config)
        self.viz = visualize.MapVisualizer(config)
        self.amulet = amulet_editor.AmuletEditor(config)
        self.biome = biomes.BiomeMapper(config)

    # ==========================
    # Geospatial Actions
    # ==========================

    def process_terrain_action(self, target, source, env):
        bounds_list = self.config['geospatial']['bounds']
        bounds_tuple = tuple(bounds_list)
        resolution = self.config.get('minecraft', {}).get('scale', {})['horizontal']
        preserve_coastline = env.get('PRESERVE_COASTLINE', True)
        
        self.geo.process_terrain(str(source[0]), str(target[0]), bounds=bounds_tuple, resolution=int(resolution), preserve_coastline=preserve_coastline)
        return None

    def scale_raster_action(self, target, source, env):
        factor = float(env.get('SCALE_FACTOR', 1.0))
        self.geo.scale_raster_values(str(source[0]), str(target[0]), scale_factor=factor)
        return None

    def heightmap_action(self, target, source, env):
        ref_path = str(source[1]) if len(source) > 1 else None
        is_pre_scaled = env.get('PRE_SCALED', False)
        
        water_threshold = self.config.get('masks', {}).get('water_sea_level_m', 0.0)
        
        self.geo.generate_heightmap_image(str(source[0]), str(target[0]), 
                                        land_reference_path=ref_path, 
                                        is_pre_scaled=is_pre_scaled,
                                        water_threshold_m=water_threshold)
        return None

    # ==========================
    # OSM Actions
    # ==========================

    def download_roads_action(self, target, source, env):
        road_types = list(self.config['roads']['road_widths'].keys())
        bounds_tuple = tuple(self.config['geospatial']['bounds'])
        self.osm.download_roads(bounds_tuple, str(target[0]), road_types)
        return None

    def download_buildings_action(self, target, source, env):
        bounds_tuple = tuple(self.config['geospatial']['bounds'])
        building_types_config = self.config.get('buildings', {}).get('types', [])
        building_types = [b.get('name') for b in building_types_config if 'name' in b]
        self.osm.download_buildings(bounds_tuple, str(target[0]), building_types)
        return None

    def download_waterways_action(self, target, source, env):
        bounds_tuple = tuple(self.config['geospatial']['bounds'])
        self.osm.download_waterways(bounds_tuple, str(target[0]))
        return None

    # ==========================
    # WorldPainter Actions
    # ==========================

    def world_action(self, target, source, env):
        heightmap = str(source[0])
        meta_json_path = str(source[1])
        
        # Load Metadata
        metadata_dict = {}
        if Path(meta_json_path).exists():
            with open(meta_json_path, 'r', encoding='utf-8') as f:
                metadata_dict = json.load(f)
        
        # Merge dynamic heightmap metadata
        hm_json = Path(heightmap + ".json")
        if hm_json.exists():
            log.info(f"Loading heightmap metadata from {hm_json}")
            with open(hm_json, 'r', encoding='utf-8') as f:
                metadata_dict.update(json.load(f))
        
        def get_src(i): return str(source[i]) if len(source) > i and str(source[i]) != 'None' else None
        
        water_mask = get_src(2)
        slope_mask = get_src(3)
        road_mask = get_src(4)
        biome_map = get_src(5)
        buildings_json = get_src(6)

        # Load buildings if provided
        buildings_data = {}
        if buildings_json and Path(buildings_json).exists():
            with open(buildings_json, 'r', encoding='utf-8') as f:
                buildings_data = yaml.safe_load(f)

        # Split biomes
        biomes_dict = {}
        if biome_map:
            log.info(f"Splitting biomes from {biome_map}...")
            out_dir = Path(str(target[0])).parent / "biome_masks"
            biomes_dict = self.wp.split_biomes(biome_map, out_dir)

        script_content = self.wp.generate_script(
            heightmap, target[0],
            metadata_dict=metadata_dict,
            water_mask=water_mask,
            slope_mask=slope_mask,
            road_mask=road_mask,
            biomes=biomes_dict,
            buildings=buildings_data
        )
        
        script_file = str(target[1])
        Path(script_file).write_text(script_content)
        self.wp.run_worldpainter(script_file)

    def export_action(self, target, source, env):
        # We need the local path for the source world file
        world_path = self.wp._to_wp_path(source[0])
        
        # SCons target is .../export/default/level.dat
        # We want parent.parent (.../export/)
        out_dir = self.wp._to_wp_path(Path(str(target[0])).parent.parent)
        script_path = Path(str(target[0])).parent / "export_script.js"

        script = (
            "print('Loading world file...');\n"
            f"var world = wp.getWorld().fromFile('{world_path}').go();\n"
            "print('World loaded. Exporting to directory...');\n"
            f"wp.exportWorld(world).toDirectory('{out_dir}').go();\n"
            "print('Export complete!');"
        )
        
        if not script_path.parent.exists():
            script_path.parent.mkdir(parents=True, exist_ok=True)

        script_path.write_text(script)
        self.wp.run_worldpainter(str(script_path))

    # ==========================
    # Biome Actions
    # ==========================

    def biome_map_action(self, target, source, env):
        elev_file = str(source[0])
        lc_file = str(source[1]) if len(source) > 1 and Path(str(source[1])).exists() else None
        is_pre_scaled = env.get('PRE_SCALED', False)
        self.biome.create_biome_map(elev_file, lc_file, str(target[0]), is_pre_scaled=is_pre_scaled)
        return 0

    # ==========================
    # Visualization Actions
    # ==========================
    
    def terrain_viz_action(self, target, source, env):
        elev = str(source[0])
        water = str(source[1]) if len(source) > 1 else None
        road = str(source[2]) if len(source) > 2 else None
        
        # Filter out script files passed as dependencies if any
        if water and water.endswith('.py'): water = None
        if road and road.endswith('.py'): road = None
            
        self.viz.visualize_terrain(elev, str(target[0]), water_mask_file=water, road_mask_file=road)
        return None

    def biome_viz_action(self, target, source, env):
        self.viz.visualize_biomes(str(source[0]), str(target[0]))
        return None

    def land_cover_viz_action(self, target, source, env):
        self.viz.visualize_land_cover(str(source[0]), str(target[0]))
        return None

    def terrain_types_viz_action(self, target, source, env):
        if len(source) < 5: return None
        heightmap = str(source[0])
        water = str(source[1])
        biome = str(source[2])
        road_mask = str(source[3])
        meta = str(source[4])
        steep = str(source[5]) if len(source) > 5 else None
        
        self.viz.visualize_terrain_types(
            heightmap_file=heightmap,
            output_file=str(target[0]),
            metadata_file=meta,
            water_mask_file=water,
            biome_map_file=biome,
            road_mask_file=road_mask,
            steep_slopes_mask_file=steep
        )
        return None

    def building_viz_action(self, target, source, env):
        placements = str(source[0])
        heightmap = str(source[1]) if len(source) > 1 else None
        water = str(source[2]) if len(source) > 2 else None
        if heightmap and heightmap.endswith('.py'): heightmap = None
        if water and water.endswith('.py'): water = None
        
        self.viz.visualize_building_placements(
            placements_file=placements,
            output_file=str(target[0]),
            heightmap_file=heightmap,
            water_mask_file=water
        )
        return None

    # ==========================
    # Amulet Actions
    # ==========================

    def amulet_place_action(self, target, source, env):
        world_path = Path(str(source[0])).parent
        placements_path = str(source[1])
        height_meta_path = str(source[2])
        
        self.amulet.place_buildings(world_path, placements_path, height_meta_path)
        
        with open(str(target[0]), 'w') as f: 
            f.write("Building placement completed.")
        return None
