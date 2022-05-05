import re

from edr_explorer.data import DataHandler

from .data import DataHandler
from .lookup import CRS_LOOKUP, TRS_LOOKUP
from .util import dict_list_search, get_request


class EDRInterface(object):
    """
    An interface to an EDR Server that can navigate the query structure to
    return data payloads in CoverageJSON format from the EDR Server.

    """

    _collections_query_str = "collections/?f=json"
    _locs_query_str = "collections/{coll_id}/locations/{loc_id}?{query_str}"
    _query_str = "collections/{coll_id}/{query_type}?{query_str}"

    def __init__(self, server_host):
        """
        Construct an interface to an EDR Server accessible at the URI specified in `server_host`
        and request the `collections` metadata from the server.

        """
        self.server_host = server_host
        self._errors = None
        self._data_handler = None

        self.json = self._get_covjson(self._collections_query_str)
        self.collections = self._get_collections()
        self.collection_ids = self._get_collection_ids()
        self.collection_titles = self._get_collection_titles()

    @property
    def errors(self):
        return self._errors

    @errors.setter
    def errors(self, value):
        self._errors = value

    @property
    def data_handler(self):
        return self._data_handler

    @data_handler.setter
    def data_handler(self, value):
        self._data_handler = value

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
        self.errors = None
        if full_uri:
            uri = query_str
        else:
            uri = f"{self.server_host}/{query_str}"
        result, status_code, errors = get_request(uri)
        if errors is not None:
            emsg = errors
            if status_code is not None:
                emsg += f" ({status_code})"
            self.errors = emsg
        return result

    def _get_collections(self):
        return self.json["collections"] if self.json is not None else None

    def _get_collection_ids(self):
        return [c["id"] for c in self.collections] if self.json is not None else None

    def _get_collection_titles(self):
        return [c["title"] for c in self.collections] if self.json is not None else None

    def _get_link(self, coll_id, key, query_ref):
        """
        Retrieve a link url embedded in collection metadata.
        Typically these links describe how to retrieve specific data from the server.

        """
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

    def _get_locations_json(self, keys):
        """Get JSON data from the server from a `locations` query."""
        coll = self.get_collection(keys)
        locs_query_uri = self._get_link(keys, "data_queries", "locations")
        named_query_uri = locs_query_uri.replace("name", coll["id"])
        return self._get_covjson(named_query_uri, full_uri=True)

    def _handle_label(self, label_item):
        """
        Labels in EDR can either be provided directly, or in a dict with one or more
        locales; respectively:
          * "label": "my_label", or
          * "label": {"en": "my_label", ...}

        This helper handles either provision, and returns the locale-specific
        label, if provided by the server.

        """
        locale = "en"  # This could be set globally in future.
        try:
            label = label_item.get(locale)
        except AttributeError:
            label = label_item
        return label

    def get_collection(self, keys):
        """
        Get the JSON metadata of a specific collection in the list of collections
        provided by the EDR Server and listed in the response from the `collections`
        query. The specific collection is selected by the value of `keys`, which may
        be one of the following:
          * an int describing the index of the collection in the list of collections
          * a string containing the value of the `id` parameter of a collection
          * a string containing the value of the `title` parameter of a collection

        """
        idx = None
        if isinstance(keys, int):
            idx = keys
        # XXX this could be replaced with `dict_list_search`.
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
        """
        Make a `locations` request to the EDR Server and return a list of IDs of defined
        locations in the collection defined by `keys`.

        """
        result = [None]
        if "locations" in self.get_query_types(keys):
            locs_json = self._get_locations_json(keys)
            result = [d["id"] for d in locs_json["features"]]
        return result

    def get_location_extents(self, keys, feature_id):
        """
        Make a `locations` request to the EDR Server and return the bounding-box
        geometry of a specific location defined by:
          * the collection specified by `keys`
          * the location specified by `feature_id`.

        """
        locs_json = self._get_locations_json(keys)
        feature_json = dict_list_search(locs_json["features"], "id", feature_id)
        return feature_json["geometry"]

    def get_spatial_extent(self, keys):
        """
        Return the spatial (bounding-box) extent of the collection defined by `keys`.

        """
        coll = self.get_collection(keys)
        return coll["extent"]["spatial"]["bbox"]

    def has_temporal_extent(self, keys):
        """Determine whether a collection described by `keys` has a temporal extent section."""
        coll = self.get_collection(keys)
        extent = coll["extent"].get("temporal")
        return extent is not None

    def get_temporal_extent(self, keys):
        """
        Return the time coordinate points for the collection defined by `keys`.

        """
        coll = self.get_collection(keys)
        times = coll["extent"]["temporal"]
        t_desc_keys = ["interval", "values"]
        return times[t_desc_keys[1]]  # Presume we'll have explicit values.

    def has_vertical_extent(self, keys):
        """Determine whether a collection described by `keys` has a vertical extent section."""
        coll = self.get_collection(keys)
        extent = coll["extent"].get("vertical")
        return extent is not None

    def get_vertical_extent(self, keys):
        """
        Return the vertical coordinate points for the collection defined by `keys`.

        """
        coll = self.get_collection(keys)
        vertical = coll["extent"]["vertical"]
        z_desc_keys = ["interval", "values"]
        return vertical[z_desc_keys[1]]  # Presume we'll have explicit values.

    def get_query_types(self, keys):
        """Return a list of the query types supported against a collection defined by `keys`."""
        coll = self.get_collection(keys)
        return list(coll['data_queries'].keys())

    def get_collection_parameters(self, keys):
        """
        Get descriptions of the datasets (that is, environmental quantities / parameters / phenomena)
        provided by a collection defined by `keys`.

        """
        coll = self.get_collection(keys)
        params_dict = {}
        for param_id, param_desc in coll["parameter_names"].items():
            label_provider = param_desc["observedProperty"]["label"]
            label = self._handle_label(label_provider)
            units = param_desc["unit"]["symbol"]["value"]
            params_dict[param_id] = {"label": label, "units": units}
        return params_dict

    def query_position(self):
        """
        Request data values and coordinate point arrays for a specific dataset provided
        by the EDR Server. A `position` request is one of the specifically defined query
        types in EDR, along with `location` and `items`, and is used for returning data
        at a particular location.

        """
        raise NotImplemented

    def query_locations(self, coll_id, location, param_names, dates=None, zs=None):
        """
        Request data values and coordinate point arrays for a specific dataset provided
        by the EDR Server. A `location` request is one of the specifically defined query
        types in EDR, along with `position` and `items`, and is used for defining specific
        areas of interest within the data that are to be made commonly available to all users
        of the EDR Server.

        The dataset is specified by the calling args:
          * `coll_id` is an identifier for a collection
          * `location` is an identifier for the location for which the data is provided
          * `param_names` is a list of one or more datasets for which to retrieve data
          * `dates`; `(start_date`, `end_date`) describe the temporal extent over which to retrieve data
          * `zs`; `(start_z`, `end_z`) describe the vertical extent over which to retrieve data

        One principle of EDR is to serve as little data as possible per query. Thus a data request
        returns JSON describing coordinate arrays and an EDR Server location to hit for each dataset
        specified by the request. For example, a query to retrieve data for multiple datasets
        and datetime values will return EDR Server locations for each combination of dataset and]
        datetime value. 

        To avoid making all these requests consecutively, a closure function that
        can be called to request the data array for a specific combination is returned, along with
        the coordinate arrays that describe all the data being requested.

        """
        self.data_handler = None  # Reset the `data_handler` attribute.
        query_type = "locations"
        coll = self.get_collection(coll_id)
        available_query_types = self.get_query_types(coll_id)
        assert query_type in available_query_types, f"Query type {query_type!r} not supported by server."

        if not isinstance(param_names, str):
            param_names = ",".join(param_names)

        query_str = f"parameter-name={param_names}"
        if dates is not None:
            query_str += f"&datetime={'/'.join(dates)}"
        if zs is not None:
            query_str += f"&z={'/'.join([str(z) for z in zs])}"

        request_str = self._locs_query_str.format(
            coll_id=coll["id"],
            loc_id=location,
            query_str=query_str
        )
        data_json = self._get_covjson(request_str)
        self.data_handler = DataHandler(data_json)

    def query_items(self):
        """
        Request predefined data objects the EDR Server. An `items` request is one of the
        specifically defined query types in EDR, along with `position` and `location`.
        It is used for returning whole dataset objects, such as NetCDF files.
        
        """
        raise NotImplementedError

    def _query(self, coll_id, query_type, param_names=None, **query_kwargs):
        """Run a query to return data from the EDR Server."""
        coll = self.get_collection(coll_id)

        # Set up the dict to format the query string based on query type.
        format_dict = dict(coll_id=coll["id"])
        if query_type == "locations":
            # uri_str = self._locs_query_str
            loc_id = query_kwargs.pop("loc_id")
            format_dict["query_type"] = f"locations/{loc_id}"
        else:
            # uri_str = self._generic_query_str
            format_dict["query_type"] = query_type

        # Construct the query string for the request.
        parameter_str = "{key}={value}"
        query_items = [parameter_str.format(key=k, value=v) for k, v in query_kwargs.items()]
        if param_names is not None:
            if not isinstance(param_names, str):
                param_names = ",".join(param_names)
            query_items.append(parameter_str.format(key="parameter-name", value=param_names))
        query_str = "&".join(query_items)
        format_dict["query_str"] = query_str

        # Make the request and set up the data handler from the response.
        query_uri = self._query_str.format(**format_dict)
        data_json = self._get_covjson(query_uri)
        self.data_handler = DataHandler(data_json)

    def query(self, coll_id, query_type, param_names=None, **query_kwargs):
        """
        Define a generic query to submit to the EDR Server.

        Args and kwargs:
          * `coll_id` is an identifier for a collection
          * `query_type` is a valid query type to submit to the EDR Server. This can be one
            of `radius`, `area`, `cube`, `trajectory`, `corridor`, `position`, `locations`, `items`;
            note that not all query types are guaranteed to be supported by the EDR Server.
            An `AssertionError` will be raised if the query type is not supported by the EDR Server.
            If `query_type` is set to `locations`, a location ID **must** be specified in
            the query kwargs using the key `loc_id`.
          * `param_names`: names of parameters, available in the collection defined by `coll_id`,
            to return data for.
          * `query_kwargs`: parameters to construct the parameter string of the query.
            Valid parameters vary between query types; check the EDR documentation for more
            information. Common parameter **keys** include `coords`, `parameter-name`, `z`, `datetime`,
            `crs` and `f` (for return type of the result from the EDR Server). **Values** _must_ be
            appropriately formatted strings.

        Note: it is up to the calling scope to ensure that valid query kwargs are
        passed. No parameter validation is performed here; a query will be constructed
        and submitted to the EDR Server without further checks.

        """
        self.data_handler = None  # Reset the `data_handler` attribute.

        # Confirm the EDR Server can handle the sort of query requested.
        available_query_types = self.get_query_types(coll_id)
        if query_type in available_query_types:
            self._query(coll_id, query_type, param_names=param_names, **query_kwargs)
        else:
            self.errors = f"Query type {query_type!r} not supported by server."
