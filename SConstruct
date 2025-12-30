import os
import sys
from pathlib import Path
import yaml

# Add current working directory to path for internal modules
sys.path.append(os.getcwd())
from src import (
    data, geospatial, worldpainter, landcover, masks, metadata, 
    biomes, osm, roads, buildings, waterways, visualize, bathymetry, install
)

# Load Configuration
with open("config.yaml", "r") as f: config = yaml.safe_load(f)

# Path Setup
project_name = config['project']['name']
build_dir = Path("build") / project_name
data_dir = build_dir / "downloads"
masks_dir = build_dir / "masks"
for d in [data_dir, masks_dir]: d.mkdir(parents=True, exist_ok=True)

# Feature Flags
has_biomes = config.get('biomes', {}).get('enabled', True)
has_roads = config.get('roads', {}).get('enabled', False)
has_buildings = config.get('buildings', {}).get('enabled', False)
has_waterways = config.get('waterways', {}).get('enabled', False)
has_bathy = config.get('bathymetry', {}).get('enabled', False)

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

env = Environment(ENV=os.environ)

# 1. Elevation & Bathymetry
elev_raw = str(data_dir / "elevation_raw.tif")
env.Command(elev_raw, ["config.yaml", "src/data.py"], comp['elev'].download_action)

elev_source = elev_raw
if has_bathy:
    bathy_file = str(data_dir / "bathymetry.tif")
    elev_with_bathy = str(data_dir / "elevation_with_bathy.tif")
    
    def dl_bathy(target, source, env):
        margin = config.get('bathymetry', {}).get('margin_km', 40)
        if not bathymetry.download_emodnet_bathymetry(tuple(config['geospatial']['bounds']), str(target[0]), margin):
            print("Warning: Bathymetry failed, using land-only.")
        return None

    env.Command(bathy_file, ["config.yaml", "src/bathymetry.py"], dl_bathy)
    env.Command(elev_with_bathy, [elev_raw, bathy_file, "src/bathymetry.py"], 
                lambda target, source, env: bathymetry.merge_land_and_bathymetry(str(source[0]), str(source[1]), str(target[0]), 0.0))
    elev_source = elev_with_bathy

# 2. Processing & Land Cover
elev_proc = str(data_dir / "elevation_epsg3857.tif")
env.Command(elev_proc, [elev_source, "config.yaml", "src/geospatial.py"], comp['geo'].process_action)

lc_file = str(data_dir / "land_cover.tif") if has_biomes else None
if lc_file:
    env.Command(lc_file, ["config.yaml", "src/landcover.py"], comp['lc'].download_land_cover_action)

# 3. Maps & Masks
heightmap = str(build_dir / "heightmap.png")
water_mask = str(masks_dir / "water_mask.png")
slope_mask = str(masks_dir / "slope_mask.png")
biome_map = str(build_dir / "biome_map.tif")
meta_json = str(build_dir / "metadata.json")

env.Command(heightmap, [elev_proc, "config.yaml", "src/geospatial.py"], comp['geo'].heightmap_action)
env.Command(water_mask, [elev_proc, "config.yaml", "src/masks.py"], comp['mask'].water_mask_action)
env.Command(slope_mask, [elev_proc, "config.yaml", "src/masks.py"], comp['mask'].slope_mask_action)
env.Command(meta_json, [elev_proc, "config.yaml", "src/metadata.py"], comp['meta'].metadata_action)

biome_srcs = [elev_proc] + ([lc_file] if lc_file else []) + ["config.yaml", "src/biomes.py", "src/geometry.py"]
env.Command(biome_map, biome_srcs, comp['biome'].biome_map_action)

# 4. OSM Extensions
def setup_osm(name, flag, loader_act, proc_act, out_name):
    if not flag: return None, None
    raw = str(data_dir / f"{name}.geojson")
    proc = str(build_dir / out_name)
    env.Command(raw, ["config.yaml", "src/osm.py"], loader_act)
    # Special case for buildings requiring metadata
    deps = [raw, elev_proc, meta_json, f"src/{name}.py"] if name == "buildings" else [raw, elev_proc, f"src/{name}.py"]
    env.Command(proc, deps, proc_act)
    return raw, proc

roads_raw, road_mask = setup_osm("roads", has_roads, comp['osm'].download_roads_action, comp['road'].road_mask_action, "road_mask.tif")
bldgs_raw, bldgs_out = setup_osm("buildings", has_buildings, comp['osm'].download_buildings_action, comp['bldg'].building_placements_action, "building_placements.json")
water_raw, river_mask = setup_osm("waterways", has_waterways, comp['osm'].download_waterways_action, comp['water'].river_mask_action, "masks/river_mask.png")

# 5. WorldPainter & Export
wp_script, wp_world = str(build_dir / "build_world.js"), str(build_dir / "world.world")
wp_srcs = [heightmap, meta_json, water_mask] + ([biome_map] if has_biomes else []) + [slope_mask, "config.yaml", "src/worldpainter.py"]
env.Command([wp_world, wp_script], wp_srcs, comp['wp'].world_action)

export_ldat = str(build_dir / "export" / project_name / "level.dat")
env.Command(export_ldat, [wp_world], comp['wp'].export_action)

install_ldat = str(Path(comp['inst'].get_saves_dir()) / project_name / "level.dat")
env.Command(install_ldat, [export_ldat], comp['inst'].install_action)

# 6. Visualizations
preview_dir = build_dir / "preview"
preview_dir.mkdir(parents=True, exist_ok=True)

v_terrain = str(preview_dir / "terrain.png")
v_biome = str(preview_dir / "biome.png")
v_types = str(preview_dir / "terrain_types.png")
v_lc = str(preview_dir / "land_cover.png")

env.Command(v_terrain, [elev_proc, water_mask, (road_mask or "None"), "src/visualize.py"], comp['viz'].terrain_viz_action)

viz_targets = [v_terrain]
if has_biomes:
    env.Command(v_biome, [biome_map, "src/visualize.py"], comp['viz'].biome_viz_action)
    env.Command(v_types, [heightmap, water_mask, biome_map, (road_mask or "None"), meta_json, slope_mask, "src/visualize.py", "src/biomes.py"], comp['viz'].terrain_types_viz_action)
    viz_targets.extend([v_biome, v_types])
if lc_file:
    env.Command(v_lc, [lc_file, "src/visualize.py"], comp['viz'].land_cover_viz_action)
    viz_targets.append(v_lc)

# Targets & Aliases
Default(install_ldat)
alias_map = {
    'elevation': elev_raw, 'process': elev_proc, 'heightmap': heightmap, 'masks': [water_mask, slope_mask],
    'biomes': biome_map, 'metadata': meta_json, 'world': wp_world, 'export': export_ldat, 'install': install_ldat,
    'roads': roads_raw, 'road-mask': road_mask, 'buildings': bldgs_raw, 'building-placements': bldgs_out,
    'waterways': water_raw, 'river-mask': river_mask, 'visualize': viz_targets
}
for name, target in alias_map.items():
    if target: env.Alias(name, target)
