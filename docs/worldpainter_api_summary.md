# WorldPainter Scripting API Summary

## Terrain Enum Values

Based on [WorldPainter Scripting Wiki](https://www.worldpainter.net/trac/wiki/Scripting/TerrainTypeValues). These are NOT the same as `Terrain.ordinal()`.

| ID | Terrain Type |
| :--- | :--- |
| 0 | Grass |
| 1 | Bare Grass |
| 2 | Dirt |
| 3 | Coarse Dirt |
| 4 | Podzol |
| 5 | Sand |
| 6 | Red Sand |
| 7 | Desert |
| 10 | Terracotta |
| 12 | Orange Stained Terracotta |
| 28 | Stone |
| 29 | Rock (Stone + Cobble) |
| 30 | Cobblestone |
| 34 | Gravel |
| 35 | Clay |
| 37 | Water |
| 38 | Lava |
| 40 | Deep Snow |
| 41 | Netherrack |
| 42 | Soul Sand |
| 100 | Dirt Path |

## Common Scripting Patterns

### Applying a Heightmap to a Terrain

```javascript
var Terrain = org.pepsoft.worldpainter.Terrain;
var heightMap = wp.getHeightMap().fromFile('path/to/mask.png').go();

// Apply mask to set terrain to Stone
if (heightMap) {
    wp.applyHeightMap(heightMap)
      .toWorld(world)
      .applyToTerrain()
      .fromLevels(128, 255) // Usage: 50%+ intensity in mask
      .toTerrain(Terrain.STONE.ordinal()) // Use ordinal() to get integer ID
      .go();
}
```

### Applying a Layer (Annotations, Biomes)

```javascript
var layer = wp.getLayer().withName('Biomes').go();
var mask = wp.getHeightMap().fromFile('path/to/biome_mask.png').go();

if (mask && layer) {
    wp.applyHeightMap(mask)
      .toWorld(world)
      .applyToLayer(layer)
      .fromLevels(128, 255)
      .toLevel(1) // Biome ID
      .go();
}
```

### Creating a World

```javascript
var world = wp.createWorld()
    .fromHeightMap(heightMap)
    .fromLevels(0, 65535)
    .toLevels(minY, maxY)
    .withWaterLevel(seaLevel)
    .go();
```
