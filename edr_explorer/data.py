from itertools import product as iproduct

from geoviews import Dataset as GVDataset
from holoviews import Dataset as HVDataset
import numpy as np

from .lookup import AXES_ORDER, CRS_LOOKUP, TRS_LOOKUP, VRS_LOOKUP
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
        self._param_names = None
        self._coords = None
        self._units = None
        self.shape = None
        self._selection_axes = None
        self._all_query_keys = None
        self._array = None
        self._all_data = None
        self._crs = None
        self._vrs = None
        self._trs = None

    @property
    def errors(self):
        """Capture any errors generated when making a request to the EDR Server."""
        return self._errors

    @errors.setter
    def errors(self, value):
        self._errors = value

    @property
    def param_names(self):
        """List of all parameter names present in `self.data_json`."""
        if self._param_names is None:
            self.param_names = list(self.data_json["parameters"].keys())
        return self._param_names

    @param_names.setter
    def param_names(self, value):
        self._param_names = value

    @property
    def coords(self):
        """Dict {"axis_name": points_array} of all coords present in `self.data_json`."""
        if self._coords is None:
            self._build_coords()
        return self._coords

    @coords.setter
    def coords(self, value):
        self._coords = value

    @property
    def units(self):
        """A dictionary mapping parameter names to their unit strings."""
        if self._units is None:
            self.units = self._get_units()
        return self._units

    @units.setter
    def units(self, value):
        self._units = value

    @property
    def shape(self):
        if self._shape is None:
            self.shape = self._get_shape()
        return self._shape

    @shape.setter
    def shape(self, value):
        self._shape = value

    @property
    def selection_axes(self):
        """
        List of all axis names present in `self.data_json` for which
        a data array can be selected.

        Functionally this is equivalent to all non-horizontal axis names.

        """
        if self._selection_axes is None:
            axes_names = list(self.coords.keys())
            self.selection_axes = list(set(axes_names) - set(self.horizontal_axes_names))
        return self._selection_axes

    @selection_axes.setter
    def selection_axes(self, value):
        self._selection_axes = value

    @property
    def all_query_keys(self):
        """
        A list of all possible valid query keys that could be passed to `self.get_item`
        and thus return a valid data response from the EDR Server.

        """
        if self._all_query_keys is None:
            self.all_query_keys = self.get_combinations()
        return self._all_query_keys

    @all_query_keys.setter
    def all_query_keys(self, value):
        self._all_query_keys = value

    @property
    def array(self):
        if self._array is None:
            self._get_data_json_values_array()
        return self._array

    @array.setter
    def array(self, value):
        self._array = value

    @property
    def all_data(self):
        """
        A dict of NumPy arrays of all data values for all combinations of parameter names
        and selection coordinate points present in `self.data_json`.

        """
        if self._all_data is None:
            self.all_data = self.get_all_data()
        return self._all_data

    @all_data.setter
    def all_data(self, value):
        self._all_data = value

    @property
    def crs(self):
        """Common coordinate reference system (crs) for all data represented by `self.data_json`."""
        if self._crs is None:
            self._get_data_crs()
        return self._crs

    @crs.setter
    def crs(self, value):
        self._crs = value

    @property
    def vrs(self):
        """Common vertical reference system (vrs) for all data represented by `self.data_json`."""
        if self._vrs is None:
            self._get_data_vrs()
        return self._vrs

    @vrs.setter
    def vrs(self, value):
        self._vrs = value

    @property
    def trs(self):
        """Common time-coord reference system (trs) for all data represented by `self.data_json`."""
        if self._trs is None:
            self._get_data_trs()
        return self._trs

    @trs.setter
    def trs(self, value):
        self._trs = value

    def __getitem__(self, key):
        if not isinstance(key, str):
            emsg = "Key must be a string defining data parameter name and coord values."
            ehelp = f"Generate a key using {self.__class__.__name__}.make_key()."
            raise KeyError(f"{emsg}\n{ehelp}")
        param, coords_dict = self.from_key(key)
        try:
            result = self.get_item(param, coords_dict)
        except Exception as e:
            self.errors = " ".join(e.args)
            result = None
        else:
            # Handle and allow other methods to write to `self.errors`.
            if self.errors is not None:
                result = None
        return result

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

    def _get_units(self):
        units_dict = {}
        for name in self.param_names:
            unit_string = self.data_json["parameters"][name]["unit"]["symbol"]["value"]
            units_dict[name] = unit_string
        return units_dict

    def _get_data_crs(self):
        """Retrieve the horizontal coordinate reference system from `data_json`."""
        ref_systems = self.data_json["domain"]["referencing"]
        axes_names = list(self.data_json["domain"]["axes"].keys())
        crs_axes = sorted(list(set(axes_names) & set(self.horizontal_axes_names)))
        try:
            ref = dict_list_search(ref_systems, "coordinates", crs_axes)
        except ValueError:
            # Try reversing the CRS axes, just in case.
            ref = dict_list_search(ref_systems, "coordinates", crs_axes[::-1])
        crs_type = ref["system"]["type"]
        self.crs = CRS_LOOKUP[crs_type]

    def _get_data_vrs(self):
        """Retrieve the vertical coordinate reference system from `data_json`."""
        ref_systems = self.data_json["domain"]["referencing"]
        ref = dict_list_search(ref_systems, "coordinates", ["z"])
        vrs_type = ref["system"]["type"]
        self.vrs = VRS_LOOKUP[vrs_type]

    def _get_data_trs(self):
        """Retrieve the time coordinate reference system from `data_json`."""
        ref_systems = self.data_json["domain"]["referencing"]
        ref = dict_list_search(ref_systems, "coordinates", ["t"])
        trs_type = ref["system"]["calendar"]
        self.trs = TRS_LOOKUP[trs_type]

    def _get_data_json_values_array(self):
        """
        Data values can be provided directly in `self.data_json`.
        In such a case, `ranges.<parameter_name>.values` will be set to a
        list of values, which we can use directly without needing to make
        further requests from the server to get data values. The data is
        presented as a dictionary of `{parameter_name: NumPy array}` per
        parameter in `self.data_json`.

        """
        result = {}
        errors = []
        for param_name, data_dict in self.data_json["ranges"].items():
            values = data_dict.get("values")
            if values is not None:
                shape = [s for s in data_dict["shape"] if s != 1]  # Don't make length-1 dims.
                array = self._json_list_to_nd_array(
                    values, shape, data_dict['dataType']
                )
                result[param_name] = [] if array is None else array
        self.array = result

    def _build_geoviews(self, array, param_name):
        """Construct a GeoViews Dataset object from an nD array data response."""
        colours = self.get_colours(param_name)
        if colours is not None:
            data = np.ma.masked_less(array, colours["vmin"])
        else:
            data = np.ma.masked_invalid(array)
        ds = HVDataset(
            data=(self.coords["x"], self.coords["y"], data),
            kdims=["longitude", "latitude"],
            vdims=param_name,
        )
        return ds.to(GVDataset, crs=self.crs)

    def _json_list_to_nd_array(self, values, shape, dtype):
        """
        Translate a 1D list of data values from JSON to a NumPy array,
        handling `NoneType` values by applying a mask at those points.
        
        """
        a = np.array(values)
        # Do we need to mask?
        if any([v is None for v in values]):
            fill_value = 999999 if dtype == "int" else 1e20
            a[a == None] = fill_value
            a = np.ma.masked_equal(a, fill_value)
        return a.astype(dtype).reshape(shape)

    def _request_data(self, param, coords_dict):
        """
        Request data from the EDR Server and handle converting the response
        into an appropriate type for caching and disseminating.

        """
        self.errors = None
        param_info = self.data_json["ranges"][param]
        param_type = param_info["type"]

        template_dict = {}
        for k, v in coords_dict.items():
            # Cast the incoming value to the type of the items in the relevant coord array.
            target_v_type = type(self.coords[k][0])
            template_dict[k] = self.coords[k].index(target_v_type(v))
        url_template = param_info["tileSets"][0]["urlTemplate"]
        url = url_template.format(**template_dict)
        r, status_code, errors = get_request(url)

        array = None
        if r is not None:
            if param_type == "TiledNdArray":
                shape = [s for s in r["shape"] if s != 1]  # Don't make length-1 dims.
                result = self._json_list_to_nd_array(r["values"], shape, r['dataType'])
                if errors is None:
                    array = result
            else:
                raise NotImplementedError(f"Cannot process parameter type {param_type!r}")
        if errors is not None:
            emsg = errors
            if status_code is not None:
                emsg += f" ({status_code})"
            self.errors = emsg
        return array

    def get_item(self, param, coords_dict, dataset=True):
        """Get a single dataset from the data cache, or populate it into the cache if not present."""
        key = self.make_key(param, coords_dict)
        if self.array.get(param) is not None:
            a = self.array[param]
            indices = self._build_indexer(param, coords_dict)
            result = a[indices].squeeze()  # Drop length-1 dims.
        elif self.cache.get(key) is not None:
            result = self.cache[key]
        else:
            result = self._request_data(param, coords_dict)
            self.cache[key] = result
        if dataset:
            result = self._build_geoviews(result, param)
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
            diff, = np.diff(values[-2:])
            result = {
                "colours": colours,
                "values": values + [values[-1]+diff],
                "vmin": vmin,
                "vmax": vmax
            }
        return result

    def _get_shape(self):
        axes = sorted(
            self.coords.keys(),
            key=lambda i: AXES_ORDER.index(i)
        )
        return [len(self.coords[axis]) for axis in axes]

    def _build_indexer(self, param_name, coords_dict):
        """
        Construct an indexer (a tuple of `Slice`s) to access a specific,
        coordinate value based, subset of a larger array.

        """
        axis_names = self.data_json["ranges"][param_name]["axisNames"]
        axes = list(coords_dict.keys())
        indices = [slice(None)] * len(axis_names)
        for axis in axes:
            data_val = (coords_dict[axis])
            data_idx = self.coords[axis].index(data_val)
            axis_idx = axis_names.index(axis)
            slc = slice(data_idx, data_idx+1)
            indices[axis_idx] = slc
        return tuple(indices)

    def build_data_array(self, param_name):
        # axis_names = self.data_json["ranges"][param_name]["axisNames"]
        relevant_queries = filter(
            lambda q: q[0] == param_name,
            self.all_query_keys
        )
        template_array = np.empty(self.shape)
        for query in relevant_queries:
            param, coords_dict = query
            array = self.get_item(param, coords_dict, dataset=False)
            insertion_inds = self._build_indexer(param, coords_dict)

            # axes = list(coords_dict.keys())
            # insertion_inds = [slice(None)] * len(axis_names)
            # for axis in axes:
            #     data_val = (coords_dict[axis])
            #     data_idx = self.coords[axis].index(data_val)
            #     insert_idx = axis_names.index(axis)
            #     slc = slice(data_idx, data_idx+1)
            #     insertion_inds[insert_idx] = slc
            template_array[insertion_inds] = array
        return template_array

    def get_all_data(self):
        """
        Build the full data array across all selection coord points for
        all parameter names.

        """
        params_and_data = {}
        for param_name in self.param_names:
            data = self.build_data_array(param_name)
            params_and_data[param_name] = data
        return params_and_data

    def get_combinations(self):
        """
        Return a list of all possible combinations of keys for requesting
        data values from the EDR Server based on the list of parameter names
        and selection axes present in `self.data_json`.

        """
        # Construct a dict of all selection axes and their coord values lists.
        # e.g. - {"t": [1, 2], "z": [2, 10]}
        coords_values = {axis: self.coords[axis] for axis in self.selection_axes}

        # Split `coords_values` into lists of {axis: point} dicts.
        # e.g. - [[{"t": 1}, {"t", 2}], [{"z": 2}, {"z": 10}]]
        selection_coords_keys = []
        for axis, points in coords_values.items():
            pairwise = [{axis: i} for i in points]
            selection_coords_keys.append(pairwise)

        # Combine all combinations of {axis: point} dicts per axis to construct
        # every possible `coord_dict` combination for a __getitem__ request.
        # e.g. [{"t": 1, "z": 2}, {"t": 1, "z": 10}, {"t": 2, "z": 2}, {"t": 2, "z": 10}]
        all_coord_dicts = map(
            lambda d: {k: v for itm in d for k, v in itm.items()},
            iproduct(*selection_coords_keys)
        )

        # Finally combine all_coord_dicts with the list of parameter names.
        # e.g. [("name", {"t": 1, "z": 2}), ("name", {"t": 1, "z": 10}), ...]
        return iproduct(self.param_names, all_coord_dicts)
