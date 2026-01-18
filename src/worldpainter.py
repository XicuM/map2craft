import subprocess
from pathlib import Path
import yaml
import json
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
        if not biome_map_path or not Path(biome_map_path).exists():
            return {}
        
        try:
            # Need rasterio for resizing or PIL
            # Using PIL since visualize.py uses it and we know it's there
            img = Image.open(biome_map_path)
            data = np.array(img)
            
            biomes_found = {}
            unique_biomes = np.unique(data)
            
            output_dir_path = Path(output_dir)
            if not output_dir_path.exists():
                output_dir_path.mkdir(parents=True, exist_ok=True)
            
            for bid in unique_biomes:
                mask = (data == bid).astype(np.uint8) * 255
                mask_img = Image.fromarray(mask, mode='L')
                out_path = output_dir_path/f"biome_{int(bid)}.png"
                mask_img.save(out_path)
                biomes_found[int(bid)] = str(out_path)
                
            return biomes_found
        except Exception as e:
            log.error(f"Failed to split biomes: {e}")
            return {}

    def generate_script(self, heightmap_path, output_world_path, metadata_dict, **kwargs):
        """Generates the WorldPainter Javascript to build the world."""
        mp = self.config['minecraft']
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
        abs_min_y = sea_level + (hm_min_m * v_scale)
        abs_max_y = sea_level + (hm_max_m * v_scale)
        
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
            "    .withMapFormat(mapFormat)",
            f"    .withLowerBuildLimit({int(default_min_build)})",
            f"    .withUpperBuildLimit({int(default_max_build)})",
            "    .fromLevels(0, 65535)",
            f"    .toLevels({target_min_y}, {target_max_y})",
            # withWaterLevel expects absolute Minecraft Y coordinate, not relative level
            f"    .withWaterLevel({int(sea_level)})",
            "    .go();",
            f"world.setName('{self.config['project']['name']}');",
            f"world.setGameType(org.pepsoft.worldpainter.GameType.{self.config['project'].get('game_mode', 'creative').upper()});",
            "print('World created successfully');",
            
            # Base terrain
            "print('Applying base terrain (Grass)...');",
            "wp.applyHeightMap(heightMap).toWorld(world).applyToTerrain().fromLevels(0, 65535).toTerrain(1).go();"
        ]

        # 1. Apply Terrain Types using Masks
        for mask_name, terrain_id in [('water_mask', 5), ('slope_mask', 2), ('road_mask', 100)]:
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
        import os
        cmd = ['wpscript', script_path]
        
        # Set JAVA Options for memory if not already set
        env = os.environ.copy()
        if '_JAVA_OPTIONS' not in env:
            env['_JAVA_OPTIONS'] = '-Xmx4G'
            
        log.info(f"Running WorldPainter: {cmd[0]}")
        try:
            # Stream output to console instead of capturing
            subprocess.run(cmd, check=True, env=env)
        except subprocess.CalledProcessError as e:
            log.error(f"WorldPainter execution failed: {e}")
            raise


