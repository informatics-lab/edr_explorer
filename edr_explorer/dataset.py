import datetime

import cartopy.crs as ccrs
from cf_units import Unit
from iris.coords import DimCoord
from iris.coord_systems import GeogCS
from iris.cube import Cube, CubeList
import numpy as np

from .lookup import (
    HORIZONTAL_AXES_LOOKUP,
    ISO_DATE_FMT_STR,
    UNITS_LOOKUP,
)


class _Dataset(object):
    def __init__(self, data_handler, names):
        self.data_handler = data_handler
        self.names = names

    def build_dataset(self):
        raise NotImplementedError


class IrisCubeDataset(_Dataset):
    def __init__(self, data_handler, name):
        super().__init__(data_handler, name)

    def _handle_time_coord(self, values):
        epoch = "days since 1970-01-01"
        calendar = self.data_handler.trs.lower()
        units = Unit(epoch, calendar=calendar)

        points = [datetime.datetime.strptime(s, ISO_DATE_FMT_STR) for s in values]
        return units, points

    def build_coord(self, axis_name):
        values = self.data_handler.coords[axis_name]

        if axis_name in HORIZONTAL_AXES_LOOKUP.keys():
            crs = self.data_handler.crs
            if isinstance(crs, ccrs.PlateCarree()):
                ref_sys = GeogCS()
            units = UNITS_LOOKUP[ref_sys]
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
        axes = self.data_handler.coords.keys()
        dcad = []
        for i, axis in enumerate(axes):
            coord = self.build_coord(axis)
            dcad.append(coord, i)

        cube = Cube(
            self.data_handler.all_data[self.name],
            long_name=self.name,
            units=self.data_handler.units[self.name].replace("/", " "),
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

    n_params = len(names)  # XXX watch out for a string iterable!
    if to == "iris":
        if n_params == 1:
            provider = IrisCubeDataset(data_handler, names)
        elif n_params > 1:
            provider = IrisCubeListDataset(data_handler, names)
        else:
            emsg = f"Number of parameters must be greater than or equal to 1, got {n_params}."
            raise ValueError(emsg)

    return provider.build_dataset()