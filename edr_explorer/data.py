import numpy as np

from geoviews import Dataset as GVDataset
from holoviews import Dataset as HVDataset

from .lookup import CRS_LOOKUP, TRS_LOOKUP
from .util import dict_list_search, get_request


class DataHandler(object):
    """
    Handle the response of an EDR data request from making a data-requesting query to
    the EDR Server against a specific collection, such as a locations query. This includes
    retrieving specific 2D data arrays, building the common coordinate arrays for the
    data, and caching data arrays as GeoViews Datasets to avoid repeat requests to the
    EDR Server.

    """
    horizontal_axes_names = ["x", "y", "latitude", "longitude"]  # May need to be extended.

    def __init__(self, data_json):
        """
        Set up a data handler interface to the data response `data_json` from the EDR Server.

        """
        self.data_json = data_json
        self.cache = {}
        self.colours = {}

        self._errors = None
        self._coords = None
        self._crs = None
        self._trs = None

    @property
    def errors(self):
        return self._errors

    @errors.setter
    def errors(self, value):
        self._errors = value

    @property
    def coords(self):
        if self._coords is None:
            self._build_coords()
        return self._coords

    @coords.setter
    def coords(self, value):
        self._coords = value

    @property
    def crs(self):
        if self._crs is None:
            self._get_data_crs()
        return self._crs

    @crs.setter
    def crs(self, value):
        self._crs = value

    def __getitem__(self, key):
        if not isinstance(key, str):
            emsg = "Key must be a string defining data parameter name and coord values."
            ehelp = f"`Generate a key using {self.__class__.__name__}.make_key()`."
            raise KeyError(f"{emsg}\n{ehelp}")
        param, coords_dict = self.from_key(key)
        return self.get_item(param, coords_dict)

    def _build_coord_points(self, d):
        """
        Build a linearly spaced list of coordinate point values
        from a dictionary `d` containing `start`, `stop` and `num`
        (number of points) values.

        """
        return np.linspace(d["start"], d["stop"], d["num"])

    def _build_coords(self):
        """
        Build coordinate arrays from data-describing JSON `data_json`.

        Coordinate arrays with few values are returned as a list of values. 
        Longer or easily constructed coordinate arrays are specified as a list
        of [`start`, `stop`, `number`], and these are converted to an array of values.

        Returns a dictionary of `{"axis name": array_of_coordinate_points}`.

        """
        coords_data = self.data_json["domain"]["axes"]
        axes_names = list(coords_data.keys())
        coords = {}
        for axis_name in axes_names:
            coord_data = coords_data[axis_name]
            axis_keys = list(coord_data.keys())
            if "start" in axis_keys:
                coord_points = self._build_coord_points(coord_data)
            elif "values" in axis_keys:
                coord_points = list(coord_data["values"])
            else:
                bad_keys = ", ".join(axis_keys)
                raise KeyError(f"Could not build coordinate from keys: {bad_keys!r}.")
            coords[axis_name] = coord_points
        self.coords = coords

    def _get_data_crs(self):
        """Retrieve the horizontal coordinate reference system from `data_json`."""
        ref_systems = self.data_json["domain"]["referencing"]
        axes_names = list(self.data_json["domain"]["axes"].keys())
        crs_axes = sorted(list(set(axes_names) & set(self.horizontal_axes_names)))
        ref = dict_list_search(ref_systems, "coordinates", crs_axes)
        crs_type = ref["system"]["type"]
        self.crs = CRS_LOOKUP[crs_type]

    def _build_geoviews(self, array, param_name):
        """Construct a GeoViews Dataset object from an nD array data response."""
        colours = self.get_colours(param_name)
        if colours is not None:
            data = np.ma.masked_less(array[0], colours["vmin"])
        else:
            data = np.ma.masked_invalid(array[0])
        ds = HVDataset(
            data=(self.coords["y"], self.coords["x"], data),
            kdims=["latitude", "longitude"],
            vdims=param_name,
        )
        return ds.to(GVDataset, crs=self.crs)

    def _request_data(self, param, coords_dict):
        """
        Request data from the EDR Server and handle converting the response
        into an appropriate type for caching and disseminating.

        """
        self.errors = None
        param_info = self.data_json["ranges"][param]
        param_type = param_info["type"]

        template_dict = {k: self.coords[k].index(v) for k, v in coords_dict.items()}
        url_template = param_info["tileSets"][0]["urlTemplate"]
        url = url_template.format(**template_dict)
        r, status_code, errors = get_request(url)

        data = None
        if r is not None:
            if param_type == "TiledNdArray":
                array = np.array(r["values"], dtype=r['dataType']).reshape(r["shape"])
                data = self._build_geoviews(array, param)
            else:
                raise NotImplementedError(f"Cannot process parameter type {param_type!r}")
        if errors is not None:
            emsg = errors
            if status_code is not None:
                emsg += f" ({status_code})"
            self.errors = emsg
        return data

    def get_item(self, param, coords_dict):
        """Get a single dataset from the data cache, or populate it into the cache if not present."""
        key = self.make_key(param, coords_dict)
        if self.cache.get(key) is not None:
            result = self.cache[key]
        else:
            result = self._request_data(param, coords_dict)
            self.cache[key] = result
        return result

    def get_colours(self, param_name):
        """Get a single colours reference from `self.colours`, or populate it if not present."""
        if self.colours.get(param_name) is not None:
            result = self.colours[param_name]
        else:
            result = self._build_custom_cmap(param_name)
            self.colours[param_name] = result
        return result

    def make_key(self, param, coords_dict):
        """Define the standard form for keys in the data cache."""
        coord_str = ','.join([f"{k}={coords_dict[k]}" for k in sorted(coords_dict)])
        return f"name={param},{coord_str}"

    def from_key(self, key):
        """
        Convert a string key matching the standard defined by `self.make_key` back
        into a parameter name and coords dictionary.

        """
        param, *coords = key.split(",")
        param_name = param.split("=")[1]
        coords_dict = {c.split("=")[0]: c.split("=")[1] for c in coords}
        return param_name, coords_dict

    def _build_custom_cmap(self, param_name):
        """
        Retrieve categorised colour and level information from the data JSON, if present.

        If no such information is present, the result will be `None`.
        
        """
        try:
            categories = self.data_json["parameters"][param_name]["categoryEncoding"]
        except KeyError:
            result = None
        else:
            colours = list(categories.keys())
            values = list(categories.values())
            vmin, vmax = min(values), max(values)
            high_value, = np.diff(values[-2:])
            result = {
                "colours": colours,
                "values": values + [high_value],
                "vmin": vmin,
                "vmax": vmax
            }
        return result

    # def _prepare_json(self):
    #     param_names = list(self.data_json["parameters"].keys())
    #     all_coords = list(self.data_json["domain"]["axes"].keys())
    #     template_coords = set(all_coords) - set(self.horizontal_coords)
    #     coords = {}
    #     for coord in template_coords:
    #         coord_data = self.data_json["domain"]["axes"][coord]
    #         keys = list(coord_data.keys())
    #         if "start" in keys:
    #             coord_points = list(
    #                 np.linspace(coord_data["start"],
    #                             coord_data["stop"],
    #                             coord_data["num"]
    #                 )
    #             )
    #         elif "values" in keys:
    #             coord_points = list(coord_data["values"])
    #         else:
    #             bad_keys = ", ".join(keys)
    #             raise KeyError(f"Could not build coordinate from keys: {bad_keys!r}.")
    #         coords[coord] = coord_points
