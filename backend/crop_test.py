import rasterio
from rasterio.windows import Window

src_path = r"C:\path\to\test1.1.tif"        # change to your real file
out_path = r"C:\path\to\test1.1_small.tif"  # where to save the crop
SIZE = 128

with rasterio.open(src_path) as src:
    w = Window(0, 0, min(SIZE, src.width), min(SIZE, src.height))
    profile = src.profile.copy()
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(
        width=int(w.width),
        height=int(w.height),
        transform=src.window_transform(w),
        tiled=False,
    )
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(src.read(window=w))

print("saved", out_path)