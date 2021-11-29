import cartopy.crs as ccrs


WGS84_EARTH_RADIUS = 6371229


HORIZONTAL_AXES_LOOKUP = {
    "x": [
        "x,"
        "longitude",
        "projection_x_coord",
    ],
    "y": [
        "y",
        "latitude",
        "projection_y_coord",
    ],
}


SELECTION_AXES_LOOKUP = {
    "z": [
        "z",
        "height",
        "height_level",
        "pressure_level",
    ],
    "t": [
        "t",
        "time",
        "forecast_reference_time",
        "forecast_period",
    ],
    "e": [
        "e",
        "ensemble_member",
        "realization",
    ],
}


CRS_LOOKUP = {
    "WGS_1984": ccrs.PlateCarree(),
    "GeographicCRS": ccrs.PlateCarree(),
}


TRS_LOOKUP = {
    "Gregorian Calendar": "gregorian",
    "Gregorian": "gregorian",
}


UNITS_LOOKUP = {
    "GeogCS": "degrees",
    "Mercator": "m",
}


AXES_ORDER = ["e", "t", "z", "y", "x"]


ISO_DATE_FMT_STR = "%Y-%m-%dT%H:%MZ"