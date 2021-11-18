import cartopy.crs as ccrs
import ipywidgets as widgets
import numpy as np

import geoviews as gv
import holoviews as hv
from holoviews.plotting.util import color_intervals
import panel as pn
import param

from .interface import EDRInterface


class EDRExplorer(param.Parameterized):
    # Metadata widgets.
    coll_uri = widgets.Text(placeholder='Specify an EDR Server...', description='Server')
    coll = widgets.Dropdown(options=[], description='Collections', disabled=True)
    locations = widgets.Dropdown(options=[], description='Locations', disabled=True)
    datasets = widgets.SelectMultiple(options=[], description="Datasets", disabled=True)
    start_time = widgets.Dropdown(options=[], description='Start Date', disabled=True)
    end_time = widgets.Dropdown(options=[], description='End Date', disabled=True)

    # Plot control widgets.
    pc_times = widgets.SelectionSlider(options=[""], description="Timestep", disabled=True)
    pc_params = widgets.Dropdown(options=[], description="Parameter", disabled=True)

    # Dataset attribute.
    _data_array = param.Array(np.array([np.nan]))

    connect_button = widgets.Button(description="Connect")
    submit_button = widgets.Button(description="Submit", disabled=True)
    wlist = [coll, locations, datasets, start_time, end_time]  # Metadata widgets.
    pwlist = [pc_times, pc_params]  # Plot widgets.
    wbox = widgets.VBox(wlist)
    pwbox = widgets.HBox(pwlist)

    def __init__(self, server_address=None):
        self.server_address = server_address
        if self.server_address is not None:
            self.coll_uri.value = self.server_address

        super().__init__()

        self._edr_interface = None

        self._data_getter_fn = None
        self._coords = None
        self._dataset = None
        self._custom_colours = None

        self.connect_button.on_click(self._load_collections)
        self.submit_button.on_click(self._request_plot_data)
        self.coll.observe(self._populate_contents_callback, names='value')
        self.start_time.observe(self._filter_end_time, names='value')
        self.pc_times.observe(self._plot_change, names='value')
        self.pc_params.observe(self._plot_change, names='value')

    @property
    def edr_interface(self):
        return self._edr_interface

    @edr_interface.setter
    def edr_interface(self, value):
        self._edr_interface = value

    @property
    def layout(self):
        connect_row = pn.Row(self.coll_uri, self.connect_button)
        control_row = pn.Row(self.wbox, self.submit_button, align=("end", "start"))
        plot_col = pn.Column(self.plot, self.pwbox)
        return pn.Row(pn.Column(connect_row, control_row), plot_col).servable()

    def _load_collections(self, event):
        """
        Callback when the `connect` button is clicked.

        Set up the EDR interface instance and connect to the server's collections.

        """
        server_loc = self.coll_uri.value
        try:
            self.edr_interface = EDRInterface(server_loc)
        except:
            self.coll_uri.value = "Invalid server location specified..."
        else:
            self.coll.options = [(ct, cid) for (cid, ct) in zip(self.edr_interface.collection_ids, self.edr_interface.collection_titles)]
            self.coll.value = self.edr_interface.collection_ids[0]
            self._enable_controls()

    def _request_locations_data(self, event):
        query_params = {"query_type": "locations"}
        for widget in self.wlist:
            query_params[widget.description] = widget.value
        print(query_params)

    def _request_point_data(self, event):
        query_params = {"query_type": "position"}
        pass

    def _enable_controls(self):
        for widget in self.wlist:
            widget.disabled = False
        self.submit_button.disabled = False

    def _enable_plot_controls(self):
        for widget in self.pwlist:
            widget.disabled = False

    def _populate_contents_callback(self, change):
        collection_id = change["new"]
        if collection_id is not None:
            self._populate_params(collection_id)
            locs = self.edr_interface.get_locations(collection_id)
            self.locations.options = locs
            times, _ = self.edr_interface.get_temporal_extent(collection_id)
            self.start_time.options = times
            self.end_time.options = times

    def _populate_params(self, collection_id):
        params_dict = self.edr_interface.get_collection_parameters(collection_id)
        options = []
        for k, v in params_dict.items():
            choice = f'{v["label"]} ({v["units"]})'
            options.append((choice, k))
        self.datasets.options = options

    def _filter_end_time(self, change):
        start_time_selected = change["new"]
        times = self.start_time.options
        sel_idx = times.index(start_time_selected)
        self.end_time.options = times[sel_idx:]

    def _request_plot_data(self, _):
        """Callback when the `submit` button is clicked."""
        # Get selection widgets state for request.
        coll_id = self.coll.value
        param_names = self.datasets.value
        locations = self.locations.value
        start_date = self.start_time.value
        end_date = self.end_time.value

        # Make data and coords request.
        data_getter, coords = self.edr_interface.get_data(
            coll_id, locations, param_names, start_date, end_date)
        self._data_getter_fn = data_getter
        self._coords = coords

        # Generate and enable the plot controls.
        plot_control_times = list(coords["t"])
        self.pc_times.options = plot_control_times
        self.pc_times.value = plot_control_times[0]

        plot_control_params = list(param_names)
        self.pc_params.options = list(filter(lambda o: o[1] in plot_control_params, self.datasets.options))
        self.pc_params.value = plot_control_params[0]

        self._enable_plot_controls()

    def _plot_change(self, change):
        param = self.pc_params.value
        t = self.pc_times.value
        # Make sure both plot control widgets are populated.
        if param is not None and t is not None:
            tidx = self.start_time.options.index(t)
            self._data_array, self._custom_colours = self._data_getter_fn(param, {"t": tidx})
            self._dataset = True

    @param.depends('_data_array')
    def plot(self):
        tiles = gv.tile_sources.Wikipedia.opts(width=800, height=600)
        if self._dataset is not None:
            # Handle custom colormap if specified.
            if self._custom_colours is not None:
                colours = self._custom_colours["colours"]
                levels = self._custom_colours["values"]
                opts_dict = {"cmap": colours, "color_levels": levels, "alpha": 0.9}
                data = np.ma.masked_less(self._data_array[0], levels[0])
            else:
                opts_dict = {"cmap": "viridis", "alpha": 0.9}
                data = self._data_array[0]

            ds = hv.Dataset(
                (self._coords["y"], self._coords["x"], data),
                ["latitude", "longitude"],
                self.pc_params.value)
            gds = ds.to(gv.Dataset, crs=ccrs.PlateCarree())
            showable = tiles * gds.to(gv.Image, ['longitude', 'latitude']).opts(**opts_dict)
        else:
            showable = tiles
        return showable