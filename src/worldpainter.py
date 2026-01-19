import subprocess
from pathlib import Path
import yaml
import json
import logging
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)
from src.constants import BIOME_TO_TERRAIN_MAP

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

    def split_seabed_mask(self, seabed_mask_path, output_dir):
        """Splits an RGB seabed mask into separate binary masks for Gravel and Rock.
           Red: Sand (Default, ignored), Green: Gravel, Blue: Rock.
        """
        if not seabed_mask_path or not Path(seabed_mask_path).exists():
            return {}
        
        try:
            img = Image.open(seabed_mask_path)
            data = np.array(img)
            
            # RGB check
            if len(data.shape) < 3 or data.shape[2] < 3:
                log.warning("Seabed mask is not RGB")
                return {}
                
            masks_found = {}
            output_dir_path = Path(output_dir)
            if not output_dir_path.exists():
                output_dir_path.mkdir(parents=True, exist_ok=True)
            
            # Red Channel = Sand
            # Green Channel = Gravel
            # Blue Channel = Rock
            
            # Create Sand Mask
            sand_pixels = data[:, :, 0]
            if np.any(sand_pixels > 127):
                mask_img = Image.fromarray(sand_pixels, mode='L')
                out_path = output_dir_path / "seabed_sand.png"
                mask_img.save(out_path)
                masks_found['sand'] = str(out_path)

            # Create Gravel Mask
            gravel_pixels = data[:, :, 1]
            if np.any(gravel_pixels > 127):
                mask_img = Image.fromarray(gravel_pixels, mode='L')
                out_path = output_dir_path / "seabed_gravel.png"
                mask_img.save(out_path)
                masks_found['gravel'] = str(out_path)

            # Create Rock Mask
            rock_pixels = data[:, :, 2]
            if np.any(rock_pixels > 127):
                mask_img = Image.fromarray(rock_pixels, mode='L')
                out_path = output_dir_path / "seabed_rock.png"
                mask_img.save(out_path)
                masks_found['rock'] = str(out_path)
                
            return masks_found
        except Exception as e:
            log.error(f"Failed to split seabed mask: {e}")
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
            "wp.applyHeightMap(heightMap).toWorld(world).applyToTerrain().fromLevels(0, 65535).toTerrain(0).go();"
        ]

        # Helper mapping for Biome -> Terrain Name conversions (approximate)
        # Note: We still rely on constants for ID -> ID, but let's try to map names if possible?
        # Actually, for Biomes we are mapping Biome ID -> Terrain ID.
        # If we want to use names, we need the map to be Biome ID -> Terrain Name.
        # Let's keep the Biome part as is (since it might be mapping to custom integer terrain IDs from a theme?)
        # NO, if the user sees Dirt instead of Stone for ID 2, then ID 2 is likely Dirt.
        # So checking BIOME_TO_TERRAIN_MAP: 25 -> 2. So Stone Shore -> Dirt.
        # We should update BIOME_TO_TERRAIN_MAP to use new IDs or names.
        # But `constants.py` is shared.
        # Ideally we update the script to look up the terrain for the biome ID dynamically if possible, 
        # but standard practice is hardcoded IDs.
        # A safer bet is to define standard terrains by name and use them for the Masks.
        # For Biomes, we might need to update the constants or mapping logic.
        
        # Let's fix the Masks first (Slope/Stone, Seabed/Sand/Gravel/Rock).
        
        lines.append("// Define Terrains using verified Wiki IDs")
        lines.append("// ID lists: https://www.worldpainter.net/trac/wiki/Scripting/TerrainTypeValues")
        lines.append("var tGrass = 0;   // Grass")
        lines.append("var tDirt = 2;    // Dirt") 
        lines.append("var tSand = 5;    // Sand")
        lines.append("var tGravel = 34; // Gravel")
        lines.append("var tStone = 28;  // Stone")
        lines.append("var tRock = 29;   // Rock (Stone + Cobble)")
        lines.append("var tWater = 37;  // Water")
        lines.append("var tDirtPath = 100; // Dirt Path")
        lines.append("var tSandstone = org.pepsoft.worldpainter.Terrain.SANDSTONE;")
        lines.append("var tMesa = org.pepsoft.worldpainter.Terrain.MESA;")
        
        # 1. Apply Biomes (Base Layer)
        biomes = kwargs.get('biomes', {})
        if biomes:
            lines.append("print('Loading Biomes layer...');")
            lines.append("var biomesLayer = wp.getLayer().withName('Biomes').go();")
            
            # Dynamic Biome ID lookup for modern biomes (1.19+)
            lines.append("// Dynamic ID lookup for modern biomes")
            lines.append("var mangroveBiome = wp.getBiome('minecraft:mangrove_swamp');")
            lines.append("var mangroveId = (mangroveBiome != null) ? mangroveBiome.getId() : 6; // Fallback to Swamp if missing")
            lines.append("print('Mangrove Swamp ID resolved to: ' + mangroveId);")
            
            biome_terrain_map = BIOME_TO_TERRAIN_MAP
            
            for bid, b_mask in biomes.items():
                bid_int = int(bid)
                mask_var = f"biomeMask_{bid_int}"
                lines.append(f"print('Applying biome {bid_int}...');")
                lines.append(f"var {mask_var} = wp.getHeightMap().fromFile('{self._to_wp_path(b_mask)}').go();")
                
                # Determine target WP Biome ID
                target_id_script = str(bid_int)
                if bid_int == 63: # Internal ID for Mangrove Swamp
                    target_id_script = "mangroveId"
                
                if bid_int != 0:
                    lines.append(f"if ({mask_var} && biomesLayer) wp.applyHeightMap({mask_var}).toWorld(world).applyToLayer(biomesLayer).fromLevels(128, 255).toLevel({target_id_script}).go();")
                
                # Apply terrain for specific biomes (Stone Shore, Beach, Swamp)
                target_terrain_script = None
                
                # Explicit overrides for standard biomes
                if bid_int == 25: target_terrain_script = "tStone" # Stone Shore
                elif bid_int == 16: target_terrain_script = "tSand" # Beach
                elif bid_int == 6: target_terrain_script = "tDirt" # Swamp
                elif bid_int == 63: target_terrain_script = "tDirt" # Mangrove Swamp
                elif bid_int == 7: target_terrain_script = "tDirt" # River
                elif bid_int in [0, 24, 45]: target_terrain_script = "tSand" # Ocean biomes (0, 24, 45)
                elif bid_int in [37, 38, 39]: target_terrain_script = "tMesa" # Badlands
                
                # Fallback to ID map if strictly defined there, but handle carefully
                elif bid_int in biome_terrain_map:
                     # Use the mapped ID directly? Most are integers.
                     # But some in map might be wrong (e.g. 2 -> Sand, but maybe map expected 2 to be Stone?)
                     # BIOME_TO_TERRAIN_MAP has: 25->2. If we use 2, we get Sand. User wants Stone. 
                     # So we MUST override 25 to tStone (which is 4).
                     pass

                if target_terrain_script:
                     lines.append(f"if ({mask_var}) wp.applyHeightMap({mask_var}).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain({target_terrain_script}).go();")

        # 2. Apply Generic Masks
        
        if kwargs.get('water_mask'):
             mask_path = self._to_wp_path(kwargs.get('water_mask'))
             lines.append(f"print('Applying water_mask (Masking only, terrain handled by biomes)...');")
             # We no longer apply a blunt terrain (like tDirt) to the whole water mask.
             # Terrain is now handled by Ocean biomes (Sand) and Inland biomes (Dirt).
             # This prevents the 'Dirt on Coast' issue.
             # lines.append(f"var mask_water = wp.getHeightMap().fromFile('{mask_path}').go();")
             # lines.append(f"if (mask_water) wp.applyHeightMap(mask_water).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain(tDirt).go();")

        if kwargs.get('slope_mask'):
             mask_path = self._to_wp_path(kwargs.get('slope_mask'))
             lines.append(f"print('Applying slope_mask (Stone)...');")
             lines.append(f"var mask_slope = wp.getHeightMap().fromFile('{mask_path}').go();")
             # Use Stone (4) or Rock (5)? Usually Stone for cliffs.
             lines.append(f"if (mask_slope) wp.applyHeightMap(mask_slope).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain(tStone).go();")

        if kwargs.get('road_mask'):
             mask_path = self._to_wp_path(kwargs.get('road_mask'))
             lines.append(f"print('Applying road_mask (Dirt Path)...');")
             lines.append(f"var mask_roads = wp.getHeightMap().fromFile('{mask_path}').go();")
             lines.append(f"if (mask_roads) wp.applyHeightMap(mask_roads).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain(tDirtPath).go();")

        # 3. Apply Seabed Classification
        seabed_masks = kwargs.get('seabed_masks', {})
        if seabed_masks:
            lines.append("print('Applying Seabed Classification...');")
            
            if 'sand' in seabed_masks:
                path = self._to_wp_path(seabed_masks['sand'])
                lines.append(f"var mask_sand = wp.getHeightMap().fromFile('{path}').go();")
                lines.append(f"if (mask_sand) wp.applyHeightMap(mask_sand).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain(tSand).go();")

            if 'gravel' in seabed_masks:
                path = self._to_wp_path(seabed_masks['gravel'])
                lines.append(f"var mask_gravel = wp.getHeightMap().fromFile('{path}').go();")
                lines.append(f"if (mask_gravel) wp.applyHeightMap(mask_gravel).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain(tGravel).go();")
            
            if 'rock' in seabed_masks:
                path = self._to_wp_path(seabed_masks['rock'])
                lines.append(f"var mask_rock = wp.getHeightMap().fromFile('{path}').go();")
                # Use Rock (5) or Stone (4)? Maybe Rock for underwater?
                # Let's use tStone to be consistent with cliffs, or tRock if preferred.
                lines.append(f"if (mask_rock) wp.applyHeightMap(mask_rock).toWorld(world).applyToTerrain().fromLevels(128, 255).toTerrain(tStone).go();")

        # 4. Custom Layers (e.g., Rivers, Custom Ground Cover)
        custom_layers = kwargs.get('custom_layers', {})
        if custom_layers:
            lines.append("// Custom Layers")
            for name, details in custom_layers.items():
                layer_path = details.get('layer_path')
                mask_path = details.get('mask_path')
                
                if layer_path and mask_path:
                    abs_layer = self._to_wp_path(layer_path)
                    abs_mask = self._to_wp_path(mask_path)
                    # Default to level 15 (max density/on) unless specified
                    lvl = details.get('level', 15) 
                    
                    # Sanitize variable name
                    safe_name = "".join(c for c in name if c.isalnum())
                    var_layer = f"cl_{safe_name}"
                    var_mask = f"cm_{safe_name}"
                    
                    lines.append(f"print('Applying Custom Layer: {name}...');")
                    lines.append(f"var {var_layer} = wp.getLayer().fromFile('{abs_layer}').go();")
                    lines.append(f"var {var_mask} = wp.getHeightMap().fromFile('{abs_mask}').go();")
                    # Apply mask: pixels > 127 set layer to 'lvl'
                    lines.append(f"if ({var_layer} && {var_mask}) wp.applyHeightMap({var_mask}).toWorld(world).applyToLayer({var_layer}).fromLevels(128, 255).toLevel({lvl}).go();")

        # 5. Global Population (Trees, Ores, etc.)
        if mp.get('populate', False):
            exclude_biomes = mp.get('populate_exclude_biomes', [])
            lines.append("print('Applying Global Population (Trees, Ores, Structures)...');")
            lines.append("var layer_populate = wp.getLayer().withName('Populate').go();")
            # Apply to the entire heightmap (which covers the whole world)
            lines.append("wp.applyHeightMap(heightMap).toWorld(world).applyToLayer(layer_populate).fromLevels(0, 65535).toLevel(1).go();")
            
            # Exclude specific biomes if configured
            if exclude_biomes:
                for bid_int in exclude_biomes:
                    mask_var = f"biomeMask_{bid_int}"
                    # We only apply the exclusion if the mask for that biome was actually generated (exists in this run)
                    if biomes and bid_int in biomes:
                        lines.append(f"print('Excluding biome {bid_int} from population...');")
                        lines.append(f"if (typeof {mask_var} !== 'undefined' && {mask_var} && layer_populate) wp.applyHeightMap({mask_var}).toWorld(world).applyToLayer(layer_populate).fromLevels(128, 255).toLevel(0).go();")


        # 6. Save
        lines.extend([
            f"print('Saving world to {abs_out}...');",
            f"wp.saveWorld(world).toFile('{abs_out}').go();",
            "print('Script completed successfully!');"
        ])
        
        return "\n".join(lines)

    def run_worldpainter(self, script_path):
        """Executes the WorldPainter JS script via wpscript executable."""
        import os
        cmd = ['wpscript', script_path]
        
        # Set JAVA Options for memory if not already set
        env = os.environ.copy()
        if '_JAVA_OPTIONS' not in env: env['_JAVA_OPTIONS'] = '-Xmx8G'
            
        log.info(f"Running WorldPainter: {cmd[0]}")
        try:
            # Stream output to console instead of capturing
            subprocess.run(cmd, check=True, env=env)
        except subprocess.CalledProcessError as e:
            log.error(f"WorldPainter execution failed: {e}")
            raise
