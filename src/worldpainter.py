import os
import subprocess
from pathlib import Path
import logging
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

class WorldPainterInterface:
    def __init__(self, config={}):
        self.config = config

    def _to_wp_path(self, path):
        """Converts local path to an absolute string with forward slashes for JS."""
        # Ensure it is a string before passing to Path
        path_str = str(path)
        return str(Path(path_str).resolve()).replace('\\', '/')

    def split_biomes(self, biome_map_path, output_dir):
        """Splits a multi-value biome map into separate binary masks for each biome."""
        if not biome_map_path or not os.path.exists(biome_map_path):
            return {}
        
        try:
            # Need rasterio for resizing or PIL
            # Using PIL since visualize.py uses it and we know it's there
            img = Image.open(biome_map_path)
            data = np.array(img)
            
            biomes_found = {}
            unique_biomes = np.unique(data)
            
            for bid in unique_biomes:
                # Simply use the ID as the key
                valid_bid = int(bid)
                
                mask = (data == bid).astype(np.uint8) * 255
                mask_img = Image.fromarray(mask, mode='L')
                
                filename = f"biome_{valid_bid}.png"
                out_path = Path(output_dir) / filename
                mask_img.save(out_path)
                biomes_found[valid_bid] = str(out_path)
                
            return biomes_found
        except Exception as e:
            log.error(f"Failed to split biomes: {e}")
            return {}

    def _get_wp_biome_name(self, bid):
        """Maps internal biome ID to WorldPainter Biome constant name."""
        # Deprecated / Unused now
        return str(bid)

    def generate_script(self, heightmap_path, output_world_path, metadata_dict, **kwargs):
        """Generates the WorldPainter Javascript to build the world."""
        mp = self.config['minecraft']
        scale = mp['scale']['scale_percent']
        sea_level = mp['sea_level']
        
        # Build Limits from config
        default_min_build = mp['build_limit']['min']
        default_max_build = mp['build_limit']['max']
        
        # Get actual Y-coordinate range from heightmap metadata
        # This ensures correct mapping regardless of vertical scale
        heightmap_min_y = metadata_dict.get('min_y', default_min_build)
        heightmap_max_y = metadata_dict.get('max_y', default_max_build)
        
        # Note on mapping:
        # The heightmap image (0-65535) should map to the actual Y-coordinate range
        # that the heightmap generation calculated, not necessarily the full build limits.
        # This keeps the coastline at the same position regardless of vertical scale.
        
        abs_hm = self._to_wp_path(heightmap_path)
        abs_out = self._to_wp_path(output_world_path)
        
        # Map format
        # Map format
        version = mp['version']
        format_id = f"org.pepsoft.anvil.{version}"
        
        # relative height mapping logic...
        
        # Relative Height Mapping Strategy
        # Relative Height Mapping Strategy
        # We need to map the Input Meters (min/max from metadata) to Output Blocks (WorldPainter Levels)
        # ensuring that 0m (Input) maps to Sea Level (Output).
        
        # 1. Get Metadata
        hm_min_m = metadata_dict.get('min_meters', 0.0)
        hm_max_m = metadata_dict.get('max_meters', 255.0)
        v_scale = metadata_dict.get('scale_factor_vertical', 1.0) # blocks per meter
        
        # 2. Calculate Block Heights (Absolute Y)
        # Y = SeaLevel + (Meters * Scale)
        # We use the configured sea_level as the anchor point.
        # User requested 1 block downward shift (Coastline was 64, should be 63)
        y_shift = -1
        abs_min_y = sea_level + (hm_min_m * v_scale) + y_shift
        abs_max_y = sea_level + (hm_max_m * v_scale) + y_shift
        
        # 3. Y-Offset for Scripting
        # WorldPainter's 'toLevels' usually takes absolute levels for modern formats (1.18+),
        # but to be safe and consistent with previous logic, we check if offset is needed.
        # Actually, for 1.18+ with negative build limits, toLevels takes Absolute Y if the format supports it.
        # However, purely relative shifting was used before. Let's stick to Absolute Y since we use 1.18 format.
        
        # WorldPainter scripting "toLevels(min, max)" maps the image range [0, 65535] to [min, max].
        # So we just pass the calculated Absolute Y values.
        
        target_min_y = int(abs_min_y)
        target_max_y = int(abs_max_y)

        # Build JS lines
        lines = [
            "// Auto-generated detailed script",
            "print('Starting WorldPainter script...');",
            f"var heightMap = wp.getHeightMap().fromFile('{abs_hm}').go();",
            "print('Heightmap loaded');",
            
            f"var mapFormat = wp.getMapFormat().withId('{format_id}').go();",
            "print('Map format selected: ' + mapFormat);",
            
            "print('Creating world with Precision Scaling...');",
            f"print('Mapping: {hm_min_m:.2f}m..{hm_max_m:.2f}m -> Y={target_min_y}..{target_max_y} (Scale: {v_scale:.4f} b/m)');",
            f"print('Water Level: {int(sea_level)} (Absolute Y)');",
            
            "var world = wp.createWorld()",
            "    .fromHeightMap(heightMap)",
            f"    .scale({int(scale)})",
            "    .withMapFormat(mapFormat)",
            f"    .withLowerBuildLimit({int(default_min_build)})",
            f"    .withUpperBuildLimit({int(default_max_build)})",
            f"    .fromLevels(0, 65535)",
            f"    .toLevels({target_min_y}, {target_max_y})",
            # withWaterLevel expects absolute Minecraft Y coordinate, not relative level
            f"    .withWaterLevel({int(sea_level)})",
            "    .go();",
            "print('World created successfully');",
            
            # Base terrain
            "print('Applying base terrain (Grass)...');",
            "wp.applyHeightMap(heightMap).toWorld(world).applyToTerrain().fromLevels(0, 65535).toTerrain(1).go();"
        ]

        # 1. Apply Terrain Types using Masks
        for mask_name, terrain_id in [('water_mask', 5), ('slope_mask', 2), ('road_mask', 12)]:
            mask_path = kwargs.get(mask_name)
            if mask_path:
                lines.append(f"print('Applying {mask_name}...');")
                lines.append(f"var mask_{mask_name} = wp.getHeightMap().fromFile('{self._to_wp_path(mask_path)}').go();")
                lines.append(f"if (mask_{mask_name}) wp.applyHeightMap(mask_{mask_name}).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain({terrain_id}).go();")

        # 2. Apply Biomes
        biomes = kwargs.get('biomes', {})
        if biomes:
            lines.append("print('Loading Biomes layer...');")
            lines.append("var biomesLayer = wp.getLayer().withName('Biomes').go();")
            
            biome_terrain_map = { 0: 0, 24: 0, 45: 1, 16: 5, 25: 2, 37: 6 }
            
            for bid, b_mask in biomes.items():
                bid_int = int(bid)
                mask_var = f"biomeMask_{bid_int}"
                lines.append(f"print('Applying biome {bid_int}...');")
                lines.append(f"var {mask_var} = wp.getHeightMap().fromFile('{self._to_wp_path(b_mask)}').go();")
                if bid_int != 0:
                    lines.append(f"if ({mask_var} && biomesLayer) wp.applyHeightMap({mask_var}).toWorld(world).applyToLayer(biomesLayer).fromLevels(128, 255).toLevel({bid_int}).go();")
                
                if bid_int in biome_terrain_map:
                    target_terrain = biome_terrain_map[bid_int]
                    lines.append(f"if ({mask_var}) wp.applyHeightMap({mask_var}).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain({target_terrain}).go();")

        # 3. Save
        lines.extend([
            f"print('Saving world to {abs_out}...');",
            f"wp.saveWorld(world).toFile('{abs_out}').go();",
            "print('Script completed successfully!');"
        ])
        
        return "\n".join(lines)
        
        return "\n".join(lines)

    def run_worldpainter(self, script_path):
        """Executes the WorldPainter JS script via wpscript executable."""
        wp_dir = self.config['worldpainter']['path']
        exe = Path(wp_dir)/'wpscript.exe' if os.name == 'nt' else Path('wpscript')
        
        # Fallback to system PATH if config path is invalid
        cmd = [str(exe) if exe.exists() else 'wpscript', script_path]
        
        log.info(f"Running WorldPainter: {cmd[0]}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout: log.info(f"WorldPainter output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            log.error(f"WorldPainter execution failed: {e}")
            if e.stdout: log.error(f"stdout: {e.stdout}")
            if e.stderr: log.error(f"stderr: {e.stderr}")
            raise

    def world_action(self, target, source, env):
        """SCons action for world generation."""
        import json
        
        heightmap = str(source[0])
        meta_json_path = str(source[1])
        
        # Load Metadata
        metadata_dict = {}
        if os.path.exists(meta_json_path):
            with open(meta_json_path, 'r', encoding='utf-8') as f:
                metadata_dict = json.load(f)
        
        # Merge dynamic heightmap metadata (sidecar)
        hm_json = heightmap + ".json"
        if os.path.exists(hm_json):
            log.info(f"Loading heightmap metadata from {hm_json}")
            with open(hm_json, 'r', encoding='utf-8') as f:
                hm_meta = json.load(f)
                metadata_dict.update(hm_meta) # Override defaults with actuals
        
        def get_src(i): return str(source[i]) if len(source) > i and str(source[i]) != 'None' else None
        
        water_mask = get_src(2)
        slope_mask = get_src(3)
        road_mask = get_src(4)
        biome_map = get_src(5)
        buildings_json = get_src(6)

        # Load buildings if provided
        buildings_data = {}
        if buildings_json and os.path.exists(buildings_json):
            with open(buildings_json, 'r', encoding='utf-8') as f:
                buildings_data = json.load(f)

        # Split biomes
        biomes_dict = {}
        if biome_map:
            log.info(f"Splitting biomes from {biome_map}...")
            out_dir = Path(str(target[0])).parent / "biome_masks"
            out_dir.mkdir(parents=True, exist_ok=True)
            biomes_dict = self.split_biomes(biome_map, out_dir)

        script_content = self.generate_script(
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
        self.run_worldpainter(script_file)

    def export_action(self, target, source, env):
        """SCons action to export .world file to Minecraft save directory."""
        world_path = self._to_wp_path(source[0])
        out_dir = self._to_wp_path(Path(str(target[0])).parent)
        script_path = Path(str(target[0])).parent / "export_script.js"

        script = (
            f"var world = wp.getWorld().fromFile('{world_path}').go();\n"
            f"wp.exportWorld(world).toDirectory('{out_dir}').go();\n"
            "print('Export complete!');"
        )
        
        script_path.write_text(script)
        self.run_worldpainter(str(script_path))

    