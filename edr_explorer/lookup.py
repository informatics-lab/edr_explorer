import cartopy.crs as ccrs


CRS_LOOKUP = {
    "WGS_1984": ccrs.PlateCarree(),
    "GeographicCRS": ccrs.PlateCarree(),
}


TRS_LOOKUP = {
    "Gregorian Calendar": "gregorian",
}