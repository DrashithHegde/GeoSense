import rasterio
import numpy as np
with rasterio.open('server/data/surfaces/lst/lst_20260816T000000Z.tif') as src:
    data = src.read(1)
    valid = data[ (data != src.nodata) & np.isfinite(data) ]
    print("Min:", np.min(valid))
    print("Max:", np.max(valid))
    print("Mean:", np.mean(valid))
    print("Count:", valid.size)
    print("Zeros count:", np.sum(valid == 0.0))
    print("Below zero:", np.sum(valid < 0))
