import rasterio
import numpy as np

with rasterio.open("server/data/surfaces/lst/lst_20260816T000000Z.tif") as src:
    data = src.read(1)
    valid = (data != src.nodata) & np.isfinite(data)
    
    rows_valid = np.sum(valid, axis=1)
    cols_valid = np.sum(valid, axis=0)
    
    valid_row_idx = np.where(rows_valid > 0)[0]
    valid_col_idx = np.where(cols_valid > 0)[0]
    
    if len(valid_row_idx) > 0:
        first_row = valid_row_idx[0]
        last_row = valid_row_idx[-1]
        first_col = valid_col_idx[0]
        last_col = valid_col_idx[-1]
        
        north, west = src.xy(first_row, first_col)
        south, east = src.xy(last_row, last_col)
        print(f"Valid Pixels Bounding Box:")
        print(f"Rows with data: {first_row} to {last_row} (out of {src.height})")
        print(f"Cols with data: {first_col} to {last_col} (out of {src.width})")
        print(f"Approx Valid Bounds: North={north:.4f}, South={south:.4f}, West={west:.4f}, East={east:.4f}")
    else:
        print("No valid pixels found.")
