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

    def build_dataset(self):
        raise NotImplementedError


class IrisCubeDataset(_Dataset):
    def __init__(self, data_handler, name):
        super().__init__(data_handler, names=name)

    def _handle_time_coord(self, values):
        epoch = "days since 1970-01-01"
        calendar = self.data_handler.trs.lower()
        unit = Unit(epoch, calendar=calendar)
        dts = [datetime.datetime.strptime(s, ISO_DATE_FMT_STR) for s in values]
        points = [unit.date2num(dt) for dt in dts]
        return unit, points

    # def _get_data(self):
    #     data = self.data_handler.all_data[self.names]
    #     subset_inds = [slice(None)] * len(self.data_handler.coords.keys())
    #     for axis in self.data_handler.selection_axes:
    #         axis_ind = self.data_handler.coords.keys().index(axis)
    #     return data

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

        # data = self._get_data()

        cube = Cube(
            self.data_handler.all_data[self.names],
            long_name=self.names,
            units=self.data_handler.units[self.names].replace("/", " "),
            dim_coords_and_dims=dcad,
        )
        return cube


class IrisCubeListDataset(_Dataset):
    def __init__(self, data_handler, names):
        super().__init__(data_handler, names)

    def build_dataset(self):
        cubes = []
        for name in self.names:
            cube = IrisCubeDataset(self.data_handler, name).build_dataset()
            cubes.append(cube)
        return CubeList(cubes)


def make_dataset(data_handler, names, to="iris"):
    valid_handers = ["iris"]
    if to not in valid_handers:
        emsg = f"`to` must be one of: {','.join(valid_handers)!r}; got {to}."
        raise ValueError(emsg)
    if isinstance(names, str):
        names = [names]

    n_params = len(names)  # XXX watch out for a string iterable!
    if to == "iris":
        if n_params == 1:
            provider = IrisCubeDataset(data_handler, names[0])
        elif n_params > 1:
            provider = IrisCubeListDataset(data_handler, names)
        else:
            emsg = f"Number of parameters must be greater than or equal to 1, got {n_params}."
            raise ValueError(emsg)

    return provider.build_dataset()