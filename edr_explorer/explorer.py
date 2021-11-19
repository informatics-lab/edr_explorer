import cartopy.crs as ccrs
import ipywidgets as widgets
import numpy as np

import geoviews as gv
import holoviews as hv
import panel as pn
import param

from .interface import EDRInterface


class EDRExplorer(param.Parameterized):
    """
    A `Panel` dashboard from which you can explore the data presented by an EDR Server.

    """
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
        """
        Set up a new `Panel` dashboard to use to explore the data presented by an
        EDR Server. This constructs an instance of `.interface.EDRInterface` to submit
        requests to the EDR Server on the dashboard's behalf and displays results from
        these requests in the dashboard.

        Optionally pass the hostname of an EDR server via `server_address`. If specified,
        this value will pre-populate the `Server` field of the interface.

        """
        self.server_address = server_address
        if self.server_address is not None:
            self.coll_uri.value = self.server_address

        super().__init__()

        self._edr_interface = None

        self._data_getter_fn = None
        self._coords = None
        self._data_crs = None
        self._dataset = None

        self.connect_button.on_click(self._load_collections)
        self.submit_button.on_click(self._request_plot_data)
        self.coll.observe(self._populate_contents_callback, names='value')
        self.start_time.observe(self._filter_end_time, names='value')
        self.pc_times.observe(self._plot_change, names='value')
        self.pc_params.observe(self._plot_change, names='value')

    @property
    def edr_interface(self):
        """The instance of `.interface.EDRInterface` used to handle requests to the EDR Server."""
        return self._edr_interface

    @edr_interface.setter
    def edr_interface(self, value):
        """Set the instance of `.interface.EDRInterface` used to handle requests to the EDR Server."""
        self._edr_interface = value

    @property
    def layout(self):
        """
        Construct a layout of `Panel` objects to produce the EDR explorer dashboard.
        To view the dashboard:
            explorer = EDRExplorer()
            explorer.layout

        The layout is composed of two main elements:
          * a set of selector widgets in a column on the left that define the values passed
            in queries to the EDR Server via the `.interface.EDRInterface` instance
          * a plot on the right that displays graphical results from queries submitted to the
            EDR Server via the `.interface.EDRInterface` instance

        There are some extra elements too:
          * the widgets column on the left contains two buttons - one to connect to the server
            at the web address specified in the `Server` text field widget; and one to submit a
            query to the EDR Server via the `.interface.EDRInterface` instance based on the values
            set in the selector widgets
          * the plot area on the right contains two plot control widgets to select specific data
            from queries submitted to the EDR Server to show on the plot

        """
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

    def _enable_controls(self):
        """Enable query control widgets in the left column."""
        for widget in self.wlist:
            widget.disabled = False
        self.submit_button.disabled = False

    def _enable_plot_controls(self):
        """Enable plot control widgets for updating the specific data shown on the plot."""
        for widget in self.pwlist:
            widget.disabled = False

    def _populate_contents_callback(self, change):
        """
        Populate the options and values attributes of all the left column query control
        widgets when a collection provided by the EDR Server is specified.

        """
        collection_id = change["new"]
        if collection_id is not None:
            self._populate_params(collection_id)
            locs = self.edr_interface.get_locations(collection_id)
            self.locations.options = locs
            times, _ = self.edr_interface.get_temporal_extent(collection_id)
            self.start_time.options = times
            self.end_time.options = times

    def _populate_params(self, collection_id):
        """
        Populate the `Datasets` widget with a descriptive list (names and units) of
        the parameters provided by the selected collection.

        """
        params_dict = self.edr_interface.get_collection_parameters(collection_id)
        options = []
        for k, v in params_dict.items():
            choice = f'{v["label"]} ({v["units"]})'
            options.append((choice, k))
        self.datasets.options = options

    def _filter_end_time(self, change):
        """
        Only show end datetimes in the `End Date` widget that are later than
        the value selected in the `Start Date` widget.

        """
        start_time_selected = change["new"]
        times = self.start_time.options
        sel_idx = times.index(start_time_selected)
        self.end_time.options = times[sel_idx:]

    def _request_plot_data(self, _):
        """
        Callback when the `submit` button is clicked.

        This makes a get data request to the EDR Server via the
        `.interface.EDRInterface` instance.

        """
        # Get selection widgets state for request.
        coll_id = self.coll.value
        param_names = self.datasets.value
        locations = self.locations.value
        start_date = self.start_time.value
        end_date = self.end_time.value

        # Make data and coords request.
        data_getter, coords, crs = self.edr_interface.get_data(
            coll_id, locations, param_names, start_date, end_date)
        self._data_getter_fn = data_getter
        self._coords = coords
        self._data_crs = crs

        # Generate and enable the plot controls.
        plot_control_times = list(coords["t"])
        self.pc_times.options = plot_control_times
        self.pc_times.value = plot_control_times[0]

        plot_control_params = list(param_names)
        self.pc_params.options = list(filter(lambda o: o[1] in plot_control_params, self.datasets.options))
        self.pc_params.value = plot_control_params[0]

        self._enable_plot_controls()

    def _plot_change(self, _):
        """
        Helper function to capture changes from either plot control widget
        and trigger an update of the plot.

        """
        param = self.pc_params.value
        t = self.pc_times.value
        # Make sure both widgets are populated.
        if param is not None and t is not None:
            tidx = self.start_time.options.index(t)
            self._data_array = self._data_getter_fn(param, {"t": tidx})
            self._dataset = True

    @param.depends('_data_array')
    def plot(self):
        """Show data from a data request to the EDR Server on the plot."""
        tiles = gv.tile_sources.Wikipedia.opts(width=800, height=600)
        if self._dataset is not None:
            ds = hv.Dataset(
                (self._coords["y"], self._coords["x"], np.ma.masked_invalid(self._data_array[0])),
                ["latitude", "longitude"],
                self.pc_params.value)
            gds = ds.to(gv.Dataset, crs=self._data_crs)
            showable = tiles * gds.to(gv.Image, ['longitude', 'latitude']).opts(cmap="viridis", alpha=0.75)
        else:
            showable = tiles
        return showable