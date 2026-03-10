# NZMS3-grid-converter

This Python script splits each NZMS1 polygon in an input shapefile into **9 sub-polygons** arranged in a **3 × 3 grid** and writes the results to a new shapefile

The output numbering follows this layout:

1 2 3  
4 5 6  
7 8 9

For each output feature, the script also creates:

- `grid_id` → the cell number from 1 to 9
- `sheet_name` → combined field in the format `NAME-grid_id`  
  Example: `N43-9`

---

## Purpose

This script was designed for **map sheet / index grid polygons**, especially where:

- polygons are rotated
- polygons are not perfectly axis-aligned
- the output needs to preserve the original projection
- the sub-sheet naming needs to follow a pattern such as `N43-7`

Instead of splitting by a simple north-up bounding box, the script:

1. calculates the polygon's **minimum rotated rectangle**
2. determines the dominant rotation angle
3. rotates the polygon into local axis-aligned space
4. splits it into a 3 × 3 grid
5. rotates the parts back to the original orientation

This gives much better results for rotated sheet polygons.

---

## Requirements

Install the required Python packages:

```bash
pip install geopandas shapely
