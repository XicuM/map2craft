"""
Centralized constants for Map2Craft.
Contains definitions for Biomes, Land Cover, Terrain Types, and standard configuration values.
"""

# ==========================================
# BIOMES
# ==========================================

# Minecraft Biome IDs (internal map2craft mapping)
# These align with WorldPainter/Minecraft standard IDs where possible
BIOME_IDS = {
    'ocean': 0,
    'plains': 1,
    'forest': 4,
    'taiga': 5,
    'swamp': 6,
    'mangrove_swamp': 63,
    'river': 7,
    'frozen_ocean': 10,
    'frozen_river': 11,
    'snowy_tundra': 12,
    'snowy_mountains': 13,
    'mushroom_fields': 14,
    'mushroom_field_shore': 15,
    'beach': 16,
    'desert_hills': 17,
    'wooded_hills': 18,
    'taiga_hills': 19,
    'mountain_edge': 20,
    'jungle': 21,
    'jungle_hills': 22,
    'jungle_edge': 23,
    'deep_ocean': 24,
    'stone_shore': 25,
    'snowy_beach': 26,
    'birch_forest': 27,
    'birch_forest_hills': 28,
    'dark_forest': 29,
    'snowy_taiga': 30,
    'snowy_taiga_hills': 31,
    'giant_tree_taiga': 32,
    'giant_tree_taiga_hills': 33,
    'wooded_mountains': 34,
    'savanna': 35,
    'savanna_plateau': 36,
    'badlands': 37,
    'wooded_badlands_plateau': 38,
    'badlands_plateau': 39,
    'regular_ocean': 40, # Custom/Generic
    'lukewarm_ocean': 45,
    'sunflower_plains': 129,
}

# Reverse mapping for visualization/logging
BIOME_NAMES = {v: k.replace('_', ' ').title() for k, v in BIOME_IDS.items()}

# Visualization Colors (RGB)
BIOME_COLORS = {
    0: (0, 0, 112),      # Ocean - dark blue
    1: (141, 179, 96),   # Plains - light green
    4: (5, 102, 33),     # Forest - dark green
    5: (11, 102, 89),    # Taiga - teal
    6: (7, 249, 178),    # Swamp - cyan-green
    63: (0, 207, 117),   # Mangrove Swamp - green
    7: (86, 173, 245),      # River - blue
    16: (250, 222, 85),  # Beach - sand yellow
    24: (0, 0, 80),      # Deep Ocean - very dark blue
    25: (162, 162, 132), # Stone Shore - gray
    35: (189, 178, 95),  # Savanna - tan
    37: (219, 127, 57),   # Badlands - orange-red
    45: (0, 119, 190),   # Lukewarm Ocean - lighter blue
    129: (180, 200, 50), # Sunflower Plains - yellow-green
}

# WorldPainter Layer Mapping (Biome ID -> Terrain ID or Layer ID)
# Used to apply specific terrain types/layers based on biome mask
# Format: {BiomeID: TargetID}
# Note: In WorldPainter, terrains are 0-15 roughly, layers are different. 
# This specific map was found in worldpainter.py
BIOME_TO_TERRAIN_MAP = { 
    0: 0,   # Ocean -> Water/Deep Water?
    24: 0,  # Deep Ocean -> Water
    45: 1,  # Lukewarm Ocean -> ?
    16: 5,  # Beach -> Sand
    25: 2,  # Stone Shore -> Stone
    37: 11, # Badlands -> Sandstone
    6: 12,  # Swamp -> Dirt
    63: 12, # Mangrove Swamp -> Dirt
    7: 12   # River -> Dirt
}


# ==========================================
# LAND COVER (ESA WorldCover)
# ==========================================

LAND_COVER_COLORS = {
    10: (0, 100, 0),     # Tree cover
    20: (255, 187, 34),  # Shrubland
    30: (255, 255, 76),  # Grassland
    40: (240, 150, 255), # Cropland
    50: (250, 0, 0),     # Built-up
    60: (180, 180, 180), # Bare/sparse
    70: (240, 240, 240), # Snow and ice
    80: (0, 100, 200),   # Water
    90: (0, 150, 160),   # Wetland
    95: (0, 207, 117),   # Mangroves
    100: (250, 230, 160),# Moss and lichen
    0: (0, 0, 0),        # No data
}

LAND_COVER_NAMES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
    0: "No data",
}


# ==========================================
# TERRAIN VISUALIZATION
# ==========================================

TERRAIN_COLORS = [
    (175, 175, 175), # 0: Gravel Ocean Floor
    (212, 196, 160), # 1: Sandy Ocean Floor
    (141, 179, 96),  # 2: Grass
    (122, 122, 122), # 3: Stone (Steep Slopes)
    (247, 238, 171), # 4: Beach Sand
    (210, 180, 120), # 5: Sandstone (Badlands)
    (171, 126, 72), # 6: Dirt Path (Roads)
    (125, 92, 52)    # 7: Dirt (River Bed)
]

TERRAIN_NAMES_LIST = [
    'Gravel Ocean Floor', 
    'Sandy Ocean Floor', 
    'Grass', 
    'Stone (Steep Slopes)', 
    'Beach Sand', 
    'Sandstone', 
    'Dirt Path (Roads)',
    'Dirt (River Bed)'
]


# ==========================================
# SEABED COVER
# ==========================================

SEABED_COLORS = {
    'sand': (227, 196, 123),
    'gravel': (128, 128, 128),
    'rock': (74, 74, 74),
}


# ==========================================
# BUILDING TYPES
# ==========================================

BUILDING_TYPE_STYLES = {
    'cathedral': ((128, 0, 128), 'P'),
    'church': ((0, 0, 255), 's'),
    'lighthouse': ((255, 255, 0), 'D'),
    'windmill': ((255, 165, 0), '^'),
    'tower': ((0, 128, 0), 'o'),
    'well': ((0, 255, 255), '*'),
    'building': ((255, 0, 0), 'o')
}
