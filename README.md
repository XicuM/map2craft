# Map2Craft (New)

A Python-based toolset for generating realistic Minecraft worlds from real-world geospatial data. This project uses SCons to orchestrate the processing of elevation data, bathymetry, proper land cover mapping, and OpenStreetMap (OSM) features into a WorldPainter-compatible format.

## Features

*   **Real-world Terrain**: Downloads and processes SRTM/Copernicus elevation data.
*   **Bathymetry**: Merges underwater elevation data for realistic oceans.
*   **Biomes & Land Cover**: Uses ESA WorldCover data to map real-world land types to Minecraft biomes.
*   **OSM Integration**:
    *   **Roads**: Fetches and processes road networks, carving them into the terrain.
    *   **Buildings**: Places logic for buildings (optional support for schematics).
    *   **Waterways**: Carves rivers and streams based on OSM data.
*   **WorldPainter Scripting**: Generates a JavaScript file to automate WorldPainter world creation.
*   **Visualization**: Generates preview images for biomes, terrain, and land cover.

## Prerequisites

*   **Python 3.10+**
*   **WorldPainter**: Installed and accessible (path configured in `config.yaml`).
*   **SCons**: For build automation.

## Installation

1.  Clone the repository.
2.  Install Python dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *Note: You may need `gdal` installed on your system for `rasterio` and `osgeo` dependencies depending on your OS.*
3.  Ensure `scons` is installed (`pip install scons` or via system package manager).

## Configuration

Edit `config.yaml` to customize your project:

*   **Project**: Set name and directory paths.
*   **Geospatial**: Define `bounds` (min_lon, min_lat, max_lon, max_lat) and `resolution`.
*   **Minecraft**: Configure build limits, sea level, and scale.
*   **Features**: Enable/disable biomes, roads, buildings, waterways, etc.
*   **WorldPainter**: Set the absolute path to your WorldPainter installation.

## Usage

This project uses **SCons** to manage the build pipeline. All commands are run from the project root.

### Standard Build
To run the full pipeline, generate the world, and install it to your Minecraft saves folder:

```bash
scons
```
*(This runs the default `install` target)*

### specific Targets

You can run specific parts of the pipeline:

*   **Generate Previews**:
    ```bash
    scons preview
    ```
    Creates preview images in `build/[project_name]/preview/` (`terrain.png`, `biome.png`, etc.).

*   **Process Elevation Only**:
    ```bash
    scons process
    ```

*   **Download & Process OSM Data**:
    ```bash
    scons roads buildings waterways
    ```

*   **Generate WorldPainter World**:
    ```bash
    scons world
    ```
    Creates the `.world` file in `output/` using the generated script.

*   **Export Level**:
    ```bash
    scons export
    ```
    Converts the `.world` file to a Minecraft save directory structure in `output/worlds/`.

### Clean Build
To clean generated files (be careful, this might delete downloaded data if not configured otherwise):

```bash
scons -c
```

## Project Structure

*   `config.yaml`: Main configuration file.
*   `SConstruct`: SCons build definition file.
*   `src/`: Source code modules.
    *   `data.py`: Elevation downloading.
    *   `geospatial.py`: Terrain processing and reprojection.
    *   `biomes.py`: Biome mapping logic.
    *   `osm.py`: OpenStreetMap data fetching.
    *   `worldpainter.py`: Interface for generating WorldPainter scripts.
    *   ...
*   `data/`: Directory for raw and processed inputs (elevation tiff, etc.).
*   `output/`: Directory for generated results (heightmaps, masks, world files).
