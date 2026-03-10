import math
import geopandas as gpd
from shapely.geometry import box
from shapely import affinity

# -----------------------------------------------------------------------------
# INPUT / OUTPUT FILES
# -----------------------------------------------------------------------------
# Input NZMS1 shapefile containing the source sheet polygons.
input_file = r"nz-north-island-yard-grid.shp"

# Output shapefile containing each source polygon split into 9 sub-polygons.
output_file = r"NZMS3_NI.shp"

# Optional shapefile containing any polygons that could not be split cleanly.
failed_file = r"failed_polygons.shp"


# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def largest_polygon(geom):
    """
    Return the largest Polygon from the input geometry.

    Why:
    - Some input features may be simple Polygons.
    - Some may be MultiPolygons.
    - For map-sheet style data, the largest part is usually the correct one.

    Parameters:
        geom: A Shapely geometry

    Returns:
        Polygon or None
    """
    if geom is None or geom.is_empty:
        return None

    if geom.geom_type == "Polygon":
        return geom

    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)

    return None


def edge_angle_from_mrr(poly):
    """
    Get the dominant rotation angle of a polygon using its
    minimum rotated rectangle (MRR).

    Why:
    - Many sheet polygons are rotated relative to north-up.
    - We rotate each polygon into a local axis-aligned space,
      split it into a simple 3x3 grid, then rotate the pieces back.

    Method:
    - Build the polygon's minimum rotated rectangle.
    - Find the longest rectangle edge.
    - Use that edge angle as the polygon orientation.

    Parameters:
        poly: Shapely Polygon

    Returns:
        angle in degrees
    """
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]

    best_len = -1
    best_angle = 0.0

    # Check all 4 rectangle edges
    for i in range(4):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % 4]

        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)

        # Use the longest edge as the primary orientation
        if length > best_len:
            best_len = length
            best_angle = math.degrees(math.atan2(dy, dx))

    return best_angle


def split_polygon_3x3_rotated(poly):
    """
    Split a polygon into 9 parts using a rotated local coordinate system.

    Steps:
    1. Determine the polygon orientation.
    2. Rotate the polygon so it becomes axis-aligned.
    3. Build a 3x3 grid from the rotated polygon bounds.
    4. Intersect the rotated polygon with each of the 9 grid cells.
    5. Rotate the pieces back to the original orientation.

    Numbering layout:
        1 2 3
        4 5 6
        7 8 9

    Parameters:
        poly: Shapely Polygon

    Returns:
        List of tuples: (grid_id, geometry)
    """
    # Use the polygon centroid as the rotation origin
    cx, cy = poly.centroid.x, poly.centroid.y

    # Determine the dominant orientation angle
    angle = edge_angle_from_mrr(poly)

    # Rotate polygon into local axis-aligned space
    rot = affinity.rotate(poly, -angle, origin=(cx, cy))

    # Bounds of rotated polygon
    minx, miny, maxx, maxy = rot.bounds

    # Size of each grid cell
    dx = (maxx - minx) / 3.0
    dy = (maxy - miny) / 3.0

    # Define 9 cells in row-major order:
    # top row = 1,2,3
    # middle row = 4,5,6
    # bottom row = 7,8,9
    cells = [
        (1, minx,          minx + dx,     miny + 2 * dy, maxy),
        (2, minx + dx,     minx + 2 * dx, miny + 2 * dy, maxy),
        (3, minx + 2 * dx, maxx,          miny + 2 * dy, maxy),
        (4, minx,          minx + dx,     miny + dy,     miny + 2 * dy),
        (5, minx + dx,     minx + 2 * dx, miny + dy,     miny + 2 * dy),
        (6, minx + 2 * dx, maxx,          miny + dy,     miny + 2 * dy),
        (7, minx,          minx + dx,     miny,          miny + dy),
        (8, minx + dx,     minx + 2 * dx, miny,          miny + dy),
        (9, minx + 2 * dx, maxx,          miny,          miny + dy),
    ]

    parts = []

    for grid_id, x1, x2, y1, y2 in cells:
        # Create the grid cell as a rectangle
        cell = box(x1, y1, x2, y2)

        # Intersect the rotated polygon with the cell
        piece = rot.intersection(cell)

        # Keep valid non-empty pieces
        if not piece.is_empty and piece.area > 0:
            # Rotate the piece back to original orientation
            piece = affinity.rotate(piece, angle, origin=(cx, cy))
            parts.append((grid_id, piece))

    return parts


# -----------------------------------------------------------------------------
# MAIN PROCESS
# -----------------------------------------------------------------------------

# Read the input shapefile into a GeoDataFrame
gdf = gpd.read_file(input_file)

# Basic cleanup:
# - remove null geometries
# - repair minor invalid geometry using buffer(0)
# - remove empty geometries
gdf = gdf[gdf.geometry.notnull()].copy()
gdf["geometry"] = gdf.geometry.buffer(0)
gdf = gdf[~gdf.geometry.is_empty].copy()

# List to hold successful output rows
rows = []

# List to hold failed rows for inspection
failed_rows = []

# Loop through each input feature
for _, row in gdf.iterrows():
    # Extract the largest polygon part if needed
    geom = largest_polygon(row.geometry)

    # Skip empty or unusable geometry
    if geom is None or geom.is_empty:
        bad_row = row.copy()
        bad_row["reason"] = "empty_or_invalid"
        failed_rows.append(bad_row)
        continue

    # Split polygon into 9 sub-polygons
    parts = split_polygon_3x3_rotated(geom)

    # If we did not get exactly 9 parts, log as failed
    if len(parts) != 9:
        bad_row = row.copy()
        bad_row["reason"] = f"got_{len(parts)}_parts"
        bad_row["geometry"] = geom
        failed_rows.append(bad_row)
        continue

    # Read the source sheet name from the NAME field
    # Example: N43
    base_name = str(row.get("NAME", "")).strip()

    # Build output records
    for grid_id, piece in parts:
        new_row = row.copy()

        # Add numeric grid ID (1 to 9)
        new_row["grid_id"] = grid_id

        # Add combined sheet name, e.g. N43-9
        new_row["sheet_name"] = f"{base_name}-{grid_id}"

        # Store geometry for this sub-polygon
        new_row["geometry"] = piece

        rows.append(new_row)

# Fail fast if nothing succeeded
if not rows:
    raise ValueError("No polygons were successfully split.")

# Create output GeoDataFrame
# geometry='geometry' is explicitly specified so GeoPandas knows which column
# contains the shapes
out_gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf.crs)

# Write output shapefile
# CRS is preserved from the input
out_gdf.to_file(output_file, driver="ESRI Shapefile")

# Write failed polygons if there were any
if failed_rows:
    failed_gdf = gpd.GeoDataFrame(failed_rows, geometry="geometry", crs=gdf.crs)
    failed_gdf.to_file(failed_file, driver="ESRI Shapefile")
    print(f"Failed polygons written to: {failed_file}")

# Summary
print(f"Input features: {len(gdf)}")
print(f"Output features: {len(out_gdf)}")
print(f"Expected output if all succeed: {len(gdf) * 9}")
print("CRS:", out_gdf.crs)
