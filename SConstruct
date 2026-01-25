import sys, logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s (%(name)s) %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

import yaml

# Add current working directory to path for internal modules
sys.path.append(str(Path.cwd()))
from src import (
    data, geospatial, worldpainter, landcover, masks, metadata, 
    biomes, osm, roads, buildings, waterways, visualize, bathymetry, install,
    scons_adapters
)

# Load Configuration
config_name = ARGUMENTS.get('CONFIG', None)
from src.config_manager import load_config
config = load_config(config_name)

# Path Setup
project_name = config['project']['name']
logging.info(f"Loaded project: {project_name}")
build_dir = Path("build") / project_name
data_dir = build_dir / "downloads"
masks_dir = build_dir / "masks"

# 4. Config Value Segments for selective dependency tracking
v_geo = Value(config['geospatial'])
v_mc = Value(config['minecraft'])
v_bathy = Value(config['bathymetry'])
v_biomes = Value(config['biomes'])
v_masks = Value(config['masks'])
v_meta = Value(config['metadata'])
v_roads = Value(config['roads'])
v_bldgs = Value(config['buildings'])
v_water = Value(config['waterways'])
v_seabed = Value(config['seabed'])
v_project = Value(config['project'])
v_terrain = Value(config['terrain'])


# Feature Flags
has_biomes = config['biomes']['enabled']
has_roads = config['roads']['enabled']
has_buildings = config['buildings']['enabled']
has_waterways = config['waterways']['enabled']
has_bathy = config['bathymetry']['enabled']
has_seabed = config.get('seabed', {}).get('enabled', False) and has_bathy

# Component Initialization
comp = {
    'elev': data.ElevationLoader(config),
    'geo': geospatial.TerrainProcessor(config),
    'mask': masks.MaskGenerator(config),
    'lc': landcover.LandCoverProcessor(config),
    'biome': biomes.BiomeMapper(config),
    'osm': osm.OsmLoader(config),
    'road': roads.RoadsProcessor(config),
    'bldg': buildings.BuildingsProcessor(config),
    'water': waterways.WaterwaysProcessor(config),
    'meta': metadata.MetadataGenerator(config),
    'wp': worldpainter.WorldPainterInterface(config),
    'viz': visualize.MapVisualizer(config),
    'inst': install.WorldInstaller(config)
}
adapter = scons_adapters.Map2CraftSConsAdapter(config)

import os
env = Environment(ENV=os.environ)

# 1. Elevation & Bathymetry
elev_raw = str(data_dir / "elevation_raw.tif")
env.Command(elev_raw, [v_geo, "src/data.py"], comp['elev'].download_action)

elev_source = elev_raw
if has_bathy:
    bathy_file = str(data_dir / "bathymetry.tif")
    
    # NEW PIPELINE: Scale -> Merge -> Process
    # 1. Calculate Scale Factor (blocks per meter)
    vertical_scale_m = config['minecraft']['scale']['vertical']
    scale_factor = 1.0 / vertical_scale_m
    
    tgt_elev_scaled = str(data_dir / "elevation_scaled.tif")
    tgt_bathy_scaled = str(data_dir / "bathymetry_scaled.tif")
    elev_with_bathy = str(data_dir / "elevation_merged_scaled.tif")
    
    def dl_bathy(target, source, env):
        if not bathymetry.download_emodnet_bathymetry(tuple(config['geospatial']['bounds']), str(target[0])):
            print("Warning: Bathymetry failed, using land-only.")
        return None

    # Download Bathymetry
    env.Command(bathy_file, [v_bathy, v_geo, "src/bathymetry.py"], dl_bathy)
    
    # Scale Elevation
    env.Command(tgt_elev_scaled, [elev_raw, "src/geospatial.py"], 
                adapter.scale_raster_action, SCALE_FACTOR=scale_factor)
                
    # Scale Bathymetry
    env.Command(tgt_bathy_scaled, [bathy_file, "src/geospatial.py"],
                adapter.scale_raster_action, SCALE_FACTOR=scale_factor)

    # Merge Scaled Data
    # Threshold is now in BLOCKS. 1.0m threshold becomes (1.0 * scale_factor) blocks.
    # We reduce threshold to 0.1m to targeting only strict 0-value placeholders, preserving beaches.
    merge_threshold = 0.01 * scale_factor
    
    env.Command(elev_with_bathy, [tgt_elev_scaled, tgt_bathy_scaled, v_bathy, "src/bathymetry.py"], 
                lambda target, source, env: bathymetry.merge_land_and_bathymetry(
                    str(source[0]), str(source[1]), str(target[0]), 
                    sea_level=0.0, threshold_m=merge_threshold,
                    x_offset_m=float(config.get('bathymetry', {}).get('offset_lon_m', 0.0)),
                    y_offset_m=float(config.get('bathymetry', {}).get('offset_lat_m', 0.0)),
                    smoothness_sigma=float(config.get('bathymetry', {}).get('smoothness_sigma', 2.0))))

                    
    elev_source = elev_with_bathy
    
    # Flag to tell downstream generation that we are pre-scaled
    env['PRE_SCALED'] = True


# 2. Processing & Land Cover
# 2. Processing & Land Cover
elev_proc = str(data_dir / "elevation_epsg3857.tif")
# Disable coastline preservation if bathymetry is enabled to avoid artifacts (steps/ridges)
preserve_coastline = not has_bathy
env.Command(elev_proc, [elev_source, v_geo, v_mc, "src/geospatial.py"], 
            adapter.process_terrain_action, PRESERVE_COASTLINE=preserve_coastline)

lc_file = str(data_dir / "land_cover.tif") if has_biomes else None
if lc_file:
    env.Command(lc_file, [v_geo, "src/landcover.py"], comp['lc'].download_land_cover_action)

# 3. Maps & Masks
heightmap = str(build_dir / "heightmap.png")
water_mask = str(masks_dir / "water_mask.png")
slope_mask = str(masks_dir / "slope_mask.png")
seabed_cover_mask = str(masks_dir / "seabed_cover.png") if has_seabed else None
biome_map = str(build_dir / "biome_map.tif")
meta_json = str(build_dir / "metadata.json")

env.Command(heightmap, [elev_proc, elev_raw, v_geo, v_mc, v_terrain, "src/geospatial.py"], adapter.heightmap_action, PRE_SCALED=env.get('PRE_SCALED', False))
env.Command(water_mask, [elev_proc, v_masks, v_terrain, "src/masks.py"], comp['mask'].water_mask_action, PRE_SCALED=env.get('PRE_SCALED', False))
env.Command(slope_mask, [elev_proc, v_masks, v_terrain, "src/masks.py"], comp['mask'].slope_mask_action, PRE_SCALED=env.get('PRE_SCALED', False))
if has_seabed:
    env.Command(seabed_cover_mask, [elev_proc, v_seabed, v_masks, v_terrain, "src/masks.py"], comp['mask'].seabed_cover_mask_action, PRE_SCALED=env.get('PRE_SCALED', False))
env.Command(meta_json, [elev_proc, v_meta, v_mc, v_project, v_terrain, "src/metadata.py"], comp['meta'].metadata_action, PRE_SCALED=env.get('PRE_SCALED', False))


# 4. OSM Extensions
def setup_osm(name, flag, loader_act, proc_act, out_name, config_val):
    if not flag: return None, None
    raw = str(data_dir / f"{name}.geojson")
    proc = str(build_dir / out_name)
    # 1. Raw download depends on config_val (for types/filters) and v_geo (bounds)
    env.Command(raw, [v_geo, config_val, "src/osm.py"], loader_act)
    # 2. Process depends on raw data, elevation, config_val (widths/types), v_mc (scale), and v_geo
    deps = [raw, elev_proc, f"src/{name}.py", config_val, v_mc, v_geo]
    if name == "buildings":
        deps.append(meta_json)
    env.Command(proc, deps, proc_act, PRE_SCALED=env.get('PRE_SCALED', False))
    return raw, proc

roads_raw, road_mask = setup_osm("roads", has_roads, adapter.download_roads_action, comp['road'].road_mask_action, "road_mask.tif", v_roads)
bldgs_raw, bldgs_out = setup_osm("buildings", has_buildings, adapter.download_buildings_action, comp['bldg'].building_placements_action, "building_placements.yaml", v_bldgs)
water_raw, river_mask = setup_osm("waterways", has_waterways, adapter.download_waterways_action, comp['water'].river_mask_action, "masks/river_mask.png", v_water)

biome_srcs = [elev_proc, (lc_file if lc_file else "None"), (river_mask if has_waterways else "None"), v_biomes, v_geo, v_terrain, "src/biomes.py", "src/geometry.py"]
env.Command(biome_map, biome_srcs, adapter.biome_map_action, PRE_SCALED=env.get('PRE_SCALED', False))

# 5. WorldPainter & Export
wp_script, wp_world = str(build_dir / "build_world.js"), str(build_dir / f"{project_name}.world")

wp_srcs = [
    heightmap, 
    meta_json, 
    (water_mask or "None"), 
    (slope_mask or "None"), 
    (road_mask or "None"), 
    (biome_map if has_biomes else "None"), 
    (bldgs_out or "None"),
    (seabed_cover_mask if has_seabed else "None"),
    (river_mask if has_waterways else "None"),
    v_mc, v_project,
    "src/worldpainter.py"
]
env.Command([wp_world, wp_script], wp_srcs, adapter.world_action)


export_ldat = str(build_dir / "export" / project_name / "level.dat")
env.Command(export_ldat, [wp_world], adapter.export_action)

anvil_sentinel = str(build_dir / "anvil_placed.stamp")
anvil_srcs = [export_ldat, bldgs_out, meta_json, "src/anvil_place.py"]
env.Command(anvil_sentinel, anvil_srcs, adapter.anvil_place_action)
env.Alias('anvil-place', anvil_sentinel)

install_ldat = str(Path(comp['inst'].get_saves_dir()) / project_name / "level.dat")
env.Command(install_ldat, [export_ldat, anvil_sentinel], comp['inst'].install_action)

# 6. Visualizations
preview_dir = build_dir / "preview"
v_terrain = str(preview_dir / "heightmap.png")  # Renamed from heightmap_preview.png
v_biome = str(preview_dir / "biomes.png")
v_types = str(preview_dir / "terrain.png")      
v_lc = str(preview_dir / "land_cover.png")

# Build terrain visualization sources dynamically - NO seabed for heightmap (use bathymetry gradient)
terrain_viz_sources = [heightmap, water_mask, (seabed_cover_mask or "None"), (river_mask or "None"), "src/visualize.py"]
# Note: Seabed mask intentionally omitted before, but I'll add it as placeholder to match adapter's indexing if needed.
# Actually, the adapter expects: elev, water, seabed, river.

env.Command(v_terrain, terrain_viz_sources, adapter.terrain_viz_action)

viz_targets = [v_terrain]
if has_biomes:
    env.Command(v_biome, [biome_map, "src/visualize.py"], adapter.biome_viz_action)
    
    # Build terrain types sources dynamically
    # Adapter expects: heightmap, water, biome, road, meta, steep, seabed, river
    types_sources = [
        heightmap, 
        water_mask, 
        biome_map, 
        (road_mask or "None"), 
        meta_json, 
        slope_mask, 
        (seabed_cover_mask or "None"),
        (river_mask or "None"),
        "src/visualize.py", 
        "src/biomes.py"
    ]
    
    env.Command(v_types, types_sources, adapter.terrain_types_viz_action)
    viz_targets.extend([v_biome, v_types])
if lc_file:
    env.Command(v_lc, [lc_file, "src/visualize.py"], adapter.land_cover_viz_action)
    viz_targets.append(v_lc)
if (has_buildings and bldgs_out) or (has_roads and road_mask):
    v_artifacts = str(preview_dir / "artifacts.png")
    artifacts_srcs = [(bldgs_out or "None"), heightmap, (water_mask or "None"), (road_mask or "None"), "src/visualize.py"]
    env.Command(v_artifacts, artifacts_srcs, adapter.artifacts_viz_action)
    viz_targets.append(v_artifacts)

# Targets & Aliases
Default(anvil_sentinel)
env.Alias('elevation', elev_raw)
env.Alias('process', elev_proc)
env.Alias('heightmap', heightmap)
mask_list = [water_mask, slope_mask]
if has_seabed:
    mask_list.append(seabed_cover_mask)
env.Alias('masks', mask_list)
env.Alias('biomes', biome_map)
env.Alias('metadata', meta_json)
env.Alias('world', wp_world)
env.Alias('export', export_ldat)
env.Alias('install', install_ldat)
env.Alias('preview', viz_targets)

if roads_raw:
    env.Alias('download-roads', roads_raw)
    env.Alias('road-mask', road_mask)

if bldgs_raw:
    env.Alias('download-buildings', bldgs_raw)
    env.Alias('place-buildings', bldgs_out)

if water_raw:
    env.Alias('download-waterways', water_raw)
    env.Alias('river-mask', river_mask)
