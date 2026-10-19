import json
import numpy as np
from pathlib import Path
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from PIL import Image, ImageFilter
from datetime import datetime, timezone

from app.services.surfaces.aqi_surface import get_study_region_mask
from app.services.surfaces.aqi_surface import apply_study_region_mask
from app.services.surfaces.aqi_surface import _blur_rgba

DATA_ROOT = Path("data/surfaces")
MANIFEST_PATH = DATA_ROOT / "manifest.json"

def _load_manifest():
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)

def _get_latest_geotiff(surface_key):
    manifest = _load_manifest()
    surf = manifest.get("surfaces", {}).get(surface_key)
    if not surf:
        raise ValueError(f"No {surface_key} found in manifest.")
    filename = surf.get("geotiff_filename")
    if not filename and "files" in surf and "geotiff" in surf["files"]:
        filename = f"{surface_key}/{surf['files']['geotiff']}"
    if not filename:
        raise ValueError(f"No geotiff filename for {surface_key} in manifest.")
    return DATA_ROOT / filename

def composite_to_rgba(values: np.ndarray) -> np.ndarray:
    # Colors: Sea Green, Lime, Yellow, Orange, Red, Purple, Crimson
    # Target: 0 (Good) to 1 (Bad) mapped to standard color scale
    STOP_V = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0], dtype=np.float32)
    STOP_R = np.array([  0, 140, 255, 247, 237, 158, 158], dtype=np.float32)
    STOP_G = np.array([168, 198, 242, 147,  28,  11,  11], dtype=np.float32)
    STOP_B = np.array([ 89,  63,   0,  30,  36,  15,  15], dtype=np.float32)

    valid = np.isfinite(values)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]), STOP_V[0]).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)
    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t_seg = np.where(seg, (clamped - lo) / max(hi - lo, 1e-6), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t_seg)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t_seg)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t_seg)

    # Alpha ramp: Low impact is transparent, high impact is opaque
    # to create a blooming effect around critical areas.
    t_alpha = np.clip(clamped, 0.0, 1.0)
    alpha_f = 20.0 + (t_alpha ** 1.5) * (255.0 - 20.0)
    alpha_f = np.where(valid.ravel(), alpha_f, 0.0)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(r_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha_f, 0, 255).reshape(h, w).astype(np.uint8)
    return rgba

def generate_composite_surface():
    lst_path = _get_latest_geotiff("lst")
    aqi_path = _get_latest_geotiff("aqi")
    ndvi_path = _get_latest_geotiff("ndvi")
    # NDWI path is handled below since its key might be water_health

    # Actually let's manually find them to be safe
    manifest = _load_manifest()
    
    with rasterio.open(lst_path) as src_lst:
        lst_meta = src_lst.meta.copy()
        lst_data = src_lst.read(1)
        transform = src_lst.transform
        width = src_lst.width
        height = src_lst.height
        crs = src_lst.crs

        # Function to resample other rasters to LST's grid
        def _read_and_resample(path):
            with rasterio.open(path) as src:
                with WarpedVRT(src, crs=crs, transform=transform, width=width, height=height, resampling=Resampling.bilinear) as vrt:
                    data = vrt.read(1)
                    # Mask out nodata
                    if vrt.nodata is not None:
                        data = np.where(data == vrt.nodata, np.nan, data)
                    return data

        aqi_data = _read_and_resample(aqi_path)
        ndvi_data = _read_and_resample(ndvi_path)
        
        # Determine NDWI path (might be water-health or ndwi)
        ndwi_surf = manifest.get("surfaces", {}).get("water_health") or manifest.get("surfaces", {}).get("water-health")
        if ndwi_surf and "geotiff_filename" in ndwi_surf:
            ndwi_path = DATA_ROOT / ndwi_surf["geotiff_filename"]
            ndwi_data = _read_and_resample(ndwi_path)
        else:
            print("Warning: NDWI layer not found in manifest, using 0 impact for NDWI.")
            ndwi_data = np.zeros_like(lst_data)

    # Normalize LST (30C to 45C) -> 0 to 1
    lst_norm = np.clip((lst_data - 28.0) / (45.0 - 28.0), 0.0, 1.0)
    
    # Normalize AQI (0 to 200) -> 0 to 1
    aqi_norm = np.clip(aqi_data / 200.0, 0.0, 1.0)
    
    # Normalize NDVI (0 to 0.8) -> 1 to 0 (inverted: high veg = low impact)
    ndvi_norm = 1.0 - np.clip(ndvi_data / 0.8, 0.0, 1.0)
    
    # Normalize NDWI (0 to 0.5) -> 1 to 0 (inverted: water = low impact)
    ndwi_norm = 1.0 - np.clip(ndwi_data / 0.5, 0.0, 1.0)

    # Clean up NaNs
    lst_norm = np.nan_to_num(lst_norm, nan=0.0)
    aqi_norm = np.nan_to_num(aqi_norm, nan=0.0)
    ndvi_norm = np.nan_to_num(ndvi_norm, nan=1.0)
    ndwi_norm = np.nan_to_num(ndwi_norm, nan=1.0)

    # Composite Impact Score (0 to 1)
    # Weights: AQI and LST are primary stressors. Lack of vegetation/water exacerbates them.
    impact = (lst_norm * 0.35) + (aqi_norm * 0.35) + (ndvi_norm * 0.15) + (ndwi_norm * 0.15)
    impact = np.clip(impact, 0.0, 1.0)

    raw_rgba = composite_to_rgba(impact)
    img = Image.fromarray(raw_rgba, mode="RGBA")
    
    # Calculate bounds from LST raster
    west = transform[2]
    north = transform[5]
    east = west + width * transform[0]
    south = north + height * transform[4]
    bounds = (west, south, east, north)
    study_mask = get_study_region_mask(width, height, transform, bounds)

    base_rgba = np.array(img)
    
    # Noise texture
    noise_raw = np.random.uniform(0.3, 1.0, (base_rgba.shape[0] // 2, base_rgba.shape[1] // 2)).astype(np.float32)
    noise_img = Image.fromarray(noise_raw).resize((base_rgba.shape[1], base_rgba.shape[0]), Image.Resampling.BILINEAR)
    noise = np.array(noise_img)
    noise = np.clip(noise ** 1.3, 0.3, 1.0)
    base_rgba[:, :, 3] = (base_rgba[:, :, 3].astype(np.float32) * noise).astype(np.uint8)

    # Generate layers
    sharp_rgba = _blur_rgba(base_rgba, radius=0.5)
    glow_rgba = _blur_rgba(base_rgba, radius=8.0)
    halo_rgba = _blur_rgba(base_rgba, radius=24.0)

    # Boost halo
    halo_rgba = halo_rgba.copy()
    halo_rgba[:, :, 3] = np.clip(halo_rgba[:, :, 3].astype(np.uint16) * 250 // 255, 0, 255).astype(np.uint8)

    # Apply mask
    sharp_rgba = apply_study_region_mask(sharp_rgba, study_mask)
    glow_rgba  = apply_study_region_mask(glow_rgba,  study_mask)
    halo_rgba  = apply_study_region_mask(halo_rgba,  study_mask)

    # Save PNGs
    out_dir = DATA_ROOT / "composite"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    sharp_path = out_dir / f"composite_{stamp}.png"
    glow_path = out_dir / f"composite_{stamp}_glow.png"
    halo_path = out_dir / f"composite_{stamp}_halo.png"

    Image.fromarray(sharp_rgba, mode="RGBA").save(sharp_path, "PNG", compress_level=6)
    Image.fromarray(glow_rgba,  mode="RGBA").save(glow_path,  "PNG", compress_level=6)
    Image.fromarray(halo_rgba,  mode="RGBA").save(halo_path,  "PNG", compress_level=6)

    # Update manifest
    import hashlib
    def _sha256(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()

    manifest["surfaces"]["composite"] = {
        "metric": "composite",
        "generation_status": "generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "png_filename": f"composite/{sharp_path.name}",
        "sharp_png_filename": f"composite/{sharp_path.name}",
        "glow_png_filename": f"composite/{glow_path.name}",
        "halo_png_filename": f"composite/{halo_path.name}",
        "checksums": {
            "sharp_png_sha256": _sha256(sharp_path),
            "glow_png_sha256": _sha256(glow_path),
            "halo_png_sha256": _sha256(halo_path),
        }
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print("Composite surface generated successfully.")

if __name__ == "__main__":
    generate_composite_surface()
