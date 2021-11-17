import re
from cartopy.crs import PROJ_VERSION
import requests

import numpy as np

from .lookup import CRS_LOOKUP, TRS_LOOKUP


class EDRInterface(object):
    """
    An interface to an EDR Server that can navigate the query structure to
    return data payloads in CoverageJSON format from the EDR Server.

    """

    _collections_query_str = "collections/?f=json"
    _locs_query_str = "collections/{coll_id}/locations/{loc_id}?parameter-name={param_names}&datetime={dt_str}"
    _generic_query_str = "/{data_query_type}?"

    def __init__(self, server_host):
        self.server_host = server_host

        self.json = self._get_covjson(self._collections_query_str)
        self.collections = self.json["collections"]
        self.collection_ids = [c["id"] for c in self.collections]
        self.collection_titles = [c["title"] for c in self.collections]

    def __repr__(self):
        n_colls = len(self.collections)
        max_id_len = max([len(c_id) for c_id in self.collection_ids])

        str_result = f"EDR Interface to {n_colls} collection{'s' if n_colls>1 else ''}:\n"
        header = f"  #  {'ID'.ljust(max_id_len, ' ')}  Title\n"
        str_result += header

        line = "  {i}  {c_id}  {c_title}\n"
        for i in range(len(self.collection_ids)):
            c_id_str = self.collection_ids[i]
            c_id_block = c_id_str.ljust(max_id_len-len(c_id_str)+2, ' ')
            str_result += line.format(i=i, c_id=c_id_block, c_title=self.collection_titles[i])
        return str_result

    def _get_covjson(self, query_str, full_uri=False):
        """Make a request to the EDR Server and return the (coverage) JSON response."""
        if full_uri:
            uri = query_str
        else:
            uri = f"{self.server_host}/{query_str}"
        r = requests.get(uri)
        return r.json()

    def _get_link(self, coll_id, key, query_ref):
        coll = self.get_collection(coll_id)
        if key == "links":
            links = [itm["href"] for itm in coll[key]]
            if isinstance(query_ref, int):
                link = links[query_ref]
            elif isinstance(query_ref, str):
                link = filter(lambda l: query_ref in l, links)
            else:
                raise KeyError(f"Invalid link reference: {query_ref!r} (type {type(query_ref)}.)")
        elif key == "data_queries":
            link = coll[key][query_ref]["link"]["href"]
        else:
            raise ValueError(f"Cannot extract links from collection key {key!r}.")
        return link

    def _build_generic_query(self, parameters):
        pass

    def _dict_list_search(self, l, keys, value):
        """
        Search a list of dictionaries of a common schema for a specific key/value pair.

        For example:
            l = [{'a': foo, 'b': 1, 'c': 2}, {'a': 'bar', 'b': 3, 'c': 4}]
        If `keys='a'` and `value='foo'` then the first dict in the list would be returned.

        """
        values_list = [d[keys] for d in l]
        try:
            idx = values_list.index(value)
        except ValueError:
            raise ValueError(f"A pair matching {{{keys}: {value}}} could not be found.")
        else:
            return l[idx]

    def _get_locations_json(self, keys):
        coll = self.get_collection(keys)
        locs_query_uri = self._get_link(keys, "data_queries", "locations")
        named_query_uri = locs_query_uri.replace("name", coll["id"])
        return self._get_covjson(named_query_uri, full_uri=True)

    def get_collection(self, keys):
        idx = None
        if isinstance(keys, int):
            idx = keys
        # XXX this could be replaced with `self._dict_list_search()`.
        else:
            for i, coll in enumerate(self.collections):
                coll_keys = [coll["id"], coll["title"]]
                if keys in coll_keys:
                    idx = i
        if idx is None:
            emsg = f"Collection {keys!r} could not be found."
            raise KeyError(emsg)
        return self.collections[idx]

    def get_locations(self, keys):
        locs_json = self._get_locations_json(keys)
        return [d["id"] for d in locs_json["features"]]

    def get_location_extents(self, keys, feature_id):
        locs_json = self._get_locations_json(keys)
        feature_json = self._dict_list_search(locs_json["features"], "id", feature_id)
        return feature_json["geometry"]

    def get_spatial_extent(self, keys):
        coll = self.get_collection(keys)
        bbox = coll["extent"]["spatial"]["bbox"]
        crs = coll["extent"]["spatial"]["crs"]
        proj_re = re.search(r"DATUM\[\"(?P<crsref>[\w_]+)", crs)
        proj_name = proj_re.group("crsref")
        proj = CRS_LOOKUP[proj_name]
        return bbox, proj

    def get_temporal_extent(self, keys):
        coll = self.get_collection(keys)
        times = coll["extent"]["temporal"]
        t_keys = times.keys()
        t_ref_sys_keyname = "trs"
        t_desc_key, = list(set(list(t_keys)) - set([t_ref_sys_keyname]))
        time_strings = times[t_desc_key]
        trs = times[t_ref_sys_keyname]
        trs_re = re.search(r"TDATUM\[\"(?P<trsref>[\w ]+)", trs)
        trs_name = trs_re.group("trsref")
        trs_ref = TRS_LOOKUP[trs_name]
        return time_strings, trs_ref

    def get_query_types(self, keys):
        coll = self.get_collection(keys)
        return list(coll['data_queries'].keys())

    def get_collection_parameters(self, keys):
        """In Iris-speak these are the phenomena available in the collection."""
        coll = self.get_collection(keys)
        params_dict = {}
        for param_id, param_desc in coll["parameter_names"].items():
            en_label = param_desc["observedProperty"]["label"]["en"]
            units = param_desc["unit"]["symbol"]["value"]
            params_dict[param_id] = {"label": en_label, "units": units}
        return params_dict

    def _build_custom_cmap(self, data_json, param_name):
        try:
            categories = data_json["parameters"][param_name]["categoryEncoding"]
        except KeyError:
            result = None
        else:
            colours = list(categories.keys())
            values = list(categories.values())
            high_value = values[-1] + (values[-1] - values[-2])
            result = {"colours": colours, "values": values+[high_value]}
        return result

    def _build_data_array(self, data_json):
        def data_getter(param_name, template_params):
            param_info = data_json["ranges"][param_name]
            param_type = param_info["type"]
            if param_type == "TiledNdArray":
                data_url = param_info["tileSets"][0]["urlTemplate"]
                r = self._get_covjson(data_url.format(**template_params), full_uri=True)
                data = np.array(r["values"], dtype=r['dataType']).reshape(r["shape"])
            else:
                raise NotImplementedError(f"Cannot process parameter type {param_type!r}")
            preferred_palette = self._build_custom_cmap(data_json, param_name)
            return data, preferred_palette
        return data_getter

    def _build_coord_points(self, d):
        return np.linspace(d["start"], d["stop"], d["num"])

    def _build_coords_arrays(self, data_json):
        coords_data = data_json["domain"]["axes"]
        axes_names = list(set(list(coords_data.keys())) - set(["referencing"]))
        coords = {}
        for axis_name in axes_names:
            coord_data = coords_data[axis_name]
            axis_keys = list(coord_data.keys())
            if "start" in axis_keys:
                coord_points = self._build_coord_points(coord_data)
            elif "values" in axis_keys:
                coord_points = np.array(coord_data["values"])
            else:
                bad_keys = ", ".join(axis_keys)
                raise KeyError(f"Could not build coordinate from keys: {bad_keys!r}.")
            coords[axis_name] = coord_points
        return coords

    def get_data(self, coll_id, locations, param_names, start_date, end_date,
                 query_type="locations"):
        coll = self.get_collection(coll_id)
        available_query_types = self.get_query_types(coll_id)
        assert query_type in available_query_types, f"Query type {query_type!r} not supported by server."

        date_query_value = f"{start_date}/{end_date}"
        if not isinstance(param_names, str):
            param_names = ",".join(param_names)

        query_str = self._locs_query_str.format(coll_id=coll["id"],
                                                loc_id=locations,
                                                param_names=param_names,
                                                dt_str=date_query_value)
        data_json = self._get_covjson(query_str)

        data_getter = self._build_data_array(data_json)
        coords = self._build_coords_arrays(data_json)
        return data_getter, coords