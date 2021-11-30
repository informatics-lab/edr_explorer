import datetime

import cartopy.crs as ccrs
from cf_units import Unit
from iris.coords import DimCoord
from iris.coord_systems import GeogCS
from iris.cube import Cube, CubeList
import numpy as np

from .lookup import (
    AXES_ORDER,
    HORIZONTAL_AXES_LOOKUP,
    ISO_DATE_FMT_STR,
    UNITS_LOOKUP,
    WGS84_EARTH_RADIUS,
)


class _Dataset(object):
    def __init__(self, data_handler, names):
        self.data_handler = data_handler
        self.names = names

    def get_name(self, name):
        if isinstance(self.names, dict):
            result = self.names[name]
        else:
            result = name
        return result

    def build_dataset(self):
        raise NotImplementedError


class IrisCubeDataset(_Dataset):
    def __init__(self, data_handler, names):
        super().__init__(data_handler, names)
        self._key_name, = list(self.names.keys())
        self._friendly_name, = list(self.names.values())

    def _handle_time_coord(self, values):
        epoch = "days since 1970-01-01"
        calendar = self.data_handler.trs.lower()
        unit = Unit(epoch, calendar=calendar)
        dts = [datetime.datetime.strptime(s, ISO_DATE_FMT_STR) for s in values]
        points = [unit.date2num(dt) for dt in dts]
        return unit, points

    def build_coord(self, axis_name):
        values = self.data_handler.coords[axis_name]

        if axis_name in HORIZONTAL_AXES_LOOKUP.keys():
            crs = self.data_handler.crs
            if isinstance(crs, ccrs.PlateCarree):
                ref_sys = GeogCS(WGS84_EARTH_RADIUS)
                ref_sys_ref = "GeogCS"
            units = UNITS_LOOKUP[ref_sys_ref]
            points = np.array(values)
        elif axis_name == "t":
            ref_sys = None
            units, points = self._handle_time_coord(values)
        else:
            ref_sys = None
            units = None
            points = np.array(values)

        coord = DimCoord(
            points,
            long_name=axis_name,
            units=units,
            coord_system=ref_sys,
        )
        return coord

    def build_dataset(self):
        axes = sorted(
            self.data_handler.coords.keys(),
            key=lambda i: AXES_ORDER.index(i)
        )
        dcad = []
        for i, axis in enumerate(axes):
            coord = self.build_coord(axis)
            dcad.append((coord, i))

        cube = Cube(
            self.data_handler.all_data[self._key_name],
            units=self.data_handler.units[self._key_name].replace("/", " "),
            dim_coords_and_dims=dcad,
        )
        cube.rename(self._friendly_name)
        return cube


class IrisCubeListDataset(_Dataset):
    def __init__(self, data_handler, names):
        super().__init__(data_handler, names)

    def build_dataset(self):
        cubes = []
        for k, v in self.names.items():
            cube = IrisCubeDataset(self.data_handler, {k: v}).build_dataset()
            cubes.append(cube)
        return CubeList(cubes)


def make_dataset(data_handler, names, to="iris"):
    valid_handers = ["iris"]
    if to not in valid_handers:
        emsg = f"`to` must be one of: {','.join(valid_handers)!r}; got {to}."
        raise ValueError(emsg)

    n_params = len(names)
    if to == "iris":
        if n_params == 1:
            provider = IrisCubeDataset(data_handler, names)
        elif n_params > 1:
            provider = IrisCubeListDataset(data_handler, names)
        else:
            emsg = f"Number of parameters must be greater than or equal to 1, got {n_params}."
            raise ValueError(emsg)

    return provider.build_dataset()