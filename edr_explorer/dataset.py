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
    """Abstract class to define construction of dataset objects."""
    def __init__(self, data_handler, names):
        self.data_handler = data_handler
        self.names = names

    def build_dataset(self):
        raise NotImplementedError


class IrisCubeDataset(_Dataset):
    """
    Convert data queried from an EDR Server to an Iris Cube object
    for further processing.

    """
    def __init__(self, data_handler, names):
        """
        Construct a Cube dataset construction instance.

        Args:
          * `data_handler`: an instance of `.data.DataHandler` containing the data
            to be converted.
          * `names`: a dict `{key_name: friendly_name}` of names that describe the data.

        """
        super().__init__(data_handler, names)
        self._key_name, = list(self.names.keys())
        self._friendly_name, = list(self.names.values())

    def _handle_time_coord(self, values):
        """
        Implement specific processing needs for handling a time coordinate
        returned by the EDR Server. There are two main needs:
          * Construct a time unit (as a `cf_units.Unit` object) given only a calendar
            from the EDR Server response.
          * Convert the ISO DateTime strings from the EDR Server response to
            time coordinate point values using the time unit.

        """
        epoch = "days since 1970-01-01"
        calendar = self.data_handler.trs.lower()
        unit = Unit(epoch, calendar=calendar)
        dts = [datetime.datetime.strptime(s, ISO_DATE_FMT_STR) for s in values]
        points = [unit.date2num(dt) for dt in dts]
        return unit, points

    def _build_coord(self, axis_name):
        """Build a coordinate for the axis specified by `axis_name`."""
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
        """
        Build an Iris Cube object from the data provided.

        Returns:
          * an `Iris.cube.Cube` instance.

        """
        axes = sorted(
            self.data_handler.coords.keys(),
            key=lambda i: AXES_ORDER.index(i)
        )
        dcad = []
        for i, axis in enumerate(axes):
            coord = self._build_coord(axis)
            dcad.append((coord, i))

        cube = Cube(
            self.data_handler.all_data[self._key_name],
            units=self.data_handler.units[self._key_name].replace("/", " "),
            dim_coords_and_dims=dcad,
        )
        cube.rename(self._friendly_name)
        return cube


class IrisCubeListDataset(_Dataset):
    """
    Convert data queried from an EDR Server to an Iris CubeList object
    for further processing.

    """
    def __init__(self, data_handler, names):
        """
        Construct a CubeList dataset construction instance.

        Args:
          * `data_handler`: an instance of `.data.DataHandler` containing the data
            to be converted.
          * `names`: a dict `{key_name: friendly_name, ...}` of names that describe the data.

        """
        super().__init__(data_handler, names)

    def build_dataset(self):
        """
        Build an Iris CubeList object from the data provided.

        Returns:
          * an `Iris.cube.CubeList` instance.

        """
        cubes = []
        for k, v in self.names.items():
            cube = IrisCubeDataset(self.data_handler, {k: v}).build_dataset()
            cubes.append(cube)
        return CubeList(cubes)


def make_dataset(data_handler, names, to="iris"):
    """
    Construct a dataset from data returned by the EDR Server by selecting the most
    appropriate dataset producer given the common query parameters.

    Note: currently on Iris datasets (`Cube` and `CubeList`) are supported.

    """
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