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
    geospatial, osm, worldpainter, visualize, biomes
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
        # self.amulet = amulet_editor.AmuletEditor(config)
        self.biome = biomes.BiomeMapper(config)

    # ------------------------------------------------------------------
    # Geospatial Actions

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
        
        water_threshold = self.config.get('terrain', {}).get('water_mask_threshold_m', 0.0)
        
        self.geo.generate_heightmap_image(str(source[0]), str(target[0]), 
                                        land_reference_path=ref_path, 
                                        is_pre_scaled=is_pre_scaled,
                                        water_threshold_m=water_threshold)
        return None

    # ------------------------------------------------------------------
    # OSM Actions

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

    # ------------------------------------------------------------------
    # WorldPainter Actions

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
        seabed_mask = get_src(7)
        river_mask = get_src(8)

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
            
        # Split Seabed Mask
        seabed_masks_dict = {}
        if seabed_mask and Path(seabed_mask).exists():
            log.info(f"Splitting seabed mask from {seabed_mask}...")
            out_dir = Path(str(target[0])).parent / "seabed_masks"
            seabed_masks_dict = self.wp.split_seabed_mask(seabed_mask, out_dir)

        # Custom Layers binding
        custom_layers = self.config.get('custom_layers', {}).copy()
        
        # 1. Waterways / Rivers
        # If waterways are enabled and a layer_path is specified in waterways config, use it.
        waterways_conf = self.config.get('waterways', {})
        if river_mask and waterways_conf.get('layer_path'):
            log.info(f"Binding generated river mask to Custom Layer from {waterways_conf['layer_path']}")
            custom_layers['Waterways'] = {
                'layer_path': waterways_conf['layer_path'],
                'mask_path': river_mask,
                'level': 1 # Default to 1 for 1-bit layers (like Custom Ground Cover)
            }
        
        # 2. Check for generic 'Rivers' key in custom_layers if not already handled
        elif river_mask and 'Rivers' in custom_layers:
            log.info(f"Binding generated river mask to 'Rivers' custom layer: {river_mask}")
            custom_layers['Rivers']['mask_path'] = river_mask
            if 'level' not in custom_layers['Rivers']:
                custom_layers['Rivers']['level'] = 1 # Default to 1 for safety
        
        script_content = self.wp.generate_script(
            heightmap, target[0],
            metadata_dict=metadata_dict,
            water_mask=water_mask,
            slope_mask=slope_mask,
            road_mask=road_mask,
            biomes=biomes_dict,
            buildings=buildings_data,
            seabed_masks=seabed_masks_dict,
            custom_layers=custom_layers
        )
        
        script_file = str(target[1])
        Path(script_file).write_text(script_content)
        self.wp.run_worldpainter(script_file)
        
        # Cleanup backups
        backups_dir = Path(str(target[0])).parent / "backups"
        if backups_dir.exists():
            import shutil
            log.info(f"Removing WorldPainter backups: {backups_dir}")
            shutil.rmtree(backups_dir)

    def export_action(self, target, source, env):
        # We need the local path for the source world file
        world_path = self.wp._to_wp_path(source[0])
        
        # SCons target is .../export/default/level.dat
        # We want parent.parent (.../export/)
        out_dir = self.wp._to_wp_path(Path(str(target[0])).parent.parent)
        script_path = Path(str(target[0])).parent / "export_script.js"
        
        # The actual world folder that will be created is the parent of the target level.dat
        export_world_dir = Path(str(target[0])).parent

        if export_world_dir.exists():
            import shutil
            log.info(f"Removing existing export directory to prevent backups: {export_world_dir}")
            shutil.rmtree(export_world_dir)

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
        
        # Cleanup backups (WorldPainter might create backups of the source world)
        world_backups = Path(str(source[0])).parent / "backups"
        if world_backups.exists():
            import shutil
            log.info(f"Removing WorldPainter backups: {world_backups}")
            shutil.rmtree(world_backups)

    # ------------------------------------------------------------------
    # Biome Actions

    def biome_map_action(self, target, source, env):
        elev_file = str(source[0])
        lc_file = str(source[1]) if str(source[1]) != 'None' else None
        river_file = str(source[2]) if len(source) > 2 and str(source[2]) != 'None' else None
        is_pre_scaled = env.get('PRE_SCALED', False)
        self.biome.create_biome_map(elev_file, lc_file, str(target[0]), 
                                    river_mask_file=river_file,
                                    is_pre_scaled=is_pre_scaled)
        return 0

    # ------------------------------------------------------------------
    # Preview Actions
    
    def terrain_viz_action(self, target, source, env):
        elev = str(source[0])
        water = str(source[1]) if len(source) > 1 else None
        seabed = str(source[2]) if len(source) > 2 else None
        river = str(source[3]) if len(source) > 3 else None
        
        # Filter out script files passed as dependencies if any
        def clean(s): return None if s and (s.endswith('.py') or s == 'None') else s
            
        self.viz.visualize_terrain(elev, str(target[0]), water_mask_file=clean(water), 
                                   seabed_cover_file=clean(seabed),
                                   river_mask_file=clean(river))
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
        seabed = str(source[6]) if len(source) > 6 else None
        
        # Clean up script references
        if steep and steep.endswith('.py'): steep = None
        if seabed and seabed.endswith('.py'): seabed = None
        
        river = str(source[7]) if len(source) > 7 else None
        def clean(s): return None if s and (s.endswith('.py') or s == 'None') else s

        self.viz.visualize_terrain_types(
            heightmap_file=heightmap,
            output_file=str(target[0]),
            metadata_file=meta,
            water_mask_file=water,
            biome_map_file=biome,
            road_mask_file=road_mask,
            steep_slopes_mask_file=steep,
            seabed_cover_file=seabed,
            river_mask_file=clean(river)
        )
        return None

    def artifacts_viz_action(self, target, source, env):
        placements = str(source[0])
        heightmap = str(source[1]) if len(source) > 1 else None
        water = str(source[2]) if len(source) > 2 else None
        road = str(source[3]) if len(source) > 3 else None
        
        # Filter out script files
        def clean(s): return None if s and s.endswith('.py') or s == 'None' else s
        
        self.viz.visualize_building_placements(
            placements_file=placements,
            output_file=str(target[0]),
            heightmap_file=clean(heightmap),
            water_mask_file=clean(water),
            road_mask_file=clean(road)
        )
        return None

    # ------------------------------------------------------------------
    # Amulet Actions

    def anvil_place_action(self, target, source, env):
        world_path = Path(str(source[0])).parent
        placements_path = str(source[1])
        height_meta_path = str(source[2])
        
        # We need the Config object's path or dictionary
        # Since AnvilPlacer takes paths, we can pass the config FILE path if available, or just the dict
        # But my AnvilPlacer implementation expects a config YAML PATH.
        # Let's verify if scons_adapters keeps the config path.
        # It typically loads config into a dict.
        # I'll modify AnvilPlacer to accept a dict, OR write a temporary config.
        # Actually, AnvilPlacer takes yaml path in __main__, but I can modify the class to take dict.
        
        from src.anvil_place import AnvilPlacer
        
        # HACK: Re-dump config to a temp file or assume default?
        # Better: Instantiate AnvilPlacer with the config dict I already have.
        # I'll update src/anvil_place.py next to handle dict config.
        
        placer = AnvilPlacer(
            config_path=None, 
            placements_path=placements_path, 
            metadata_path=height_meta_path, 
            world_path=world_path,
            config_dict=self.config
        )
        placer.run()
        
        with open(str(target[0]), 'w') as f: f.write("Anvil placement completed.")
        return None
