import ipywidgets as widgets

import geoviews as gv
import holoviews as hv
import panel as pn
import param
from shapely.geometry import Polygon as sPolygon, LineString as sLineString

from .interface import EDRInterface
from .lookup import CRS_LOOKUP


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
    start_z = widgets.Dropdown(options=[], description='Z Lower', disabled=True)
    end_z = widgets.Dropdown(options=[], description='Z Upper', disabled=True)

    # Error display widgets.
    connect_error_box = widgets.HTML("", layout=widgets.Layout(display="none"))
    data_error_box = widgets.HTML("", layout=widgets.Layout(display="none"))

    # Plot control widgets.
    pc_times = widgets.SelectionSlider(options=[""], description="Timestep", disabled=True)
    pc_zs = widgets.SelectionSlider(options=[""], description="Z Level", disabled=True)
    pc_params = widgets.Dropdown(options=[], description="Parameter", disabled=True)
    use_colours = pn.widgets.Checkbox(name="Use supplied colours", disabled=True)
    use_levels = pn.widgets.Checkbox(name="Use supplied levels", disabled=True)

    # Parameters for triggering plot updates.
    _data_key = param.String("")
    _colours = param.Boolean(use_colours.value)
    _levels = param.Boolean(use_levels.value)
    cmap = param.String("viridis")
    alpha = param.Magnitude(0.85)

    # Buttons.
    connect_button = widgets.Button(description="Connect")
    submit_button = widgets.Button(description="Submit", disabled=True)
    dataset_button = widgets.Button(
        description="Get Dataset",
        disabled=True,
        layout=widgets.Layout(top="-0.5rem")
    )

    # Lists and boxes aggregating multiple widgets.
    wlist = [coll, locations, datasets, start_time, end_time, start_z, end_z]  # Metadata widgets.
    pwlist = [pc_times, pc_zs, pc_params]  # Plot widgets.
    pchecklist = [use_colours, use_levels]
    wbox = widgets.VBox(wlist)
    pwbox = pn.Row(pn.Column(*pwlist[:2]), pwlist[-1], pn.Column(*pchecklist))

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

        # Class properties.
        self._edr_interface = None
        self._dataset = None
        self._no_t = "No t values in collection"
        self._no_z = "No z values in collection"

        # Plot.
        self.plot = gv.DynamicMap(self.make_plot)

        # Button click bindings.
        self.connect_button.on_click(self._load_collections)
        self.submit_button.on_click(self._request_plot_data)
        self.dataset_button.on_click(self._get_dataset)

        # Watches on widgets.
        self.coll.observe(self._populate_contents_callback, names='value')
        self.start_time.observe(self._filter_end_time, names='value')
        self.start_z.observe(self._filter_end_z, names='value')
        self.pc_times.observe(self._plot_change, names='value')
        self.pc_zs.observe(self._plot_change, names='value')
        self.pc_params.observe(self._plot_change, names='value')
        self.use_colours.param.watch(self._checkbox_change, "value", onlychanged=True)
        self.use_levels.param.watch(self._checkbox_change, "value", onlychanged=True)

        # Items for geometry-based queries.
        self._area_poly = None
        self._corridor_path = None
        self._area_stream = None
        self._corridor_stream = None
        self._query_tools()

    @property
    def edr_interface(self):
        """The instance of `.interface.EDRInterface` used to handle requests to the EDR Server."""
        return self._edr_interface

    @edr_interface.setter
    def edr_interface(self, value):
        """Set the instance of `.interface.EDRInterface` used to handle requests to the EDR Server."""
        self._edr_interface = value

    @property
    def dataset(self):
        """
        A well-known Python data object containing all the data represented by the current state
        of select widgets on the dashboard.

        """
        return self._dataset

    @dataset.setter
    def dataset(self, value):
        self._dataset = value

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
          * the widgets column on the left contains three buttons:
              * one to connect to the server at the URI specified in the `Server` text field widget,
              * one to submit a query to the EDR Server via the `.interface.EDRInterface` instance
                based on the values set in the selector widgets, and
              * one to request and return to the user all the data referenced by the current state
                of the dashboard's select widgets as a well-known Python data object (such as an Iris cube).
          * the widgets column on the left also contains two fields for displaying error messages
            when connecting to or retrieving data from the EDR Server. These are hidden by
            default and are made visible when there is a relevant error message to display. Once
            the error has been resolved the field will become hidden again.
          * the plot area on the right contains two plot control widgets to select specific data
            from queries submitted to the EDR Server to show on the plot.
          * the plot areas on the right also contains two checkboxes to select whether or not to
            show data on the plot rendered using colours and levels supplied in the query response.

        """
        connect_row = pn.Row(
            pn.Column(self.coll_uri, self.connect_error_box),
            self.connect_button
        )
        control_widgets = pn.Column(self.wbox, self.data_error_box)
        buttons = pn.Column(self.submit_button, self.dataset_button)
        control_row = pn.Row(control_widgets, buttons, align=("end", "start"))
        control_col = pn.Column(connect_row, control_row)

        tiles = gv.tile_sources.Wikipedia.opts(width=800, height=600)
        plot = tiles * self.plot
        plot_col = pn.Column(plot, self.pwbox)
        return pn.Row(control_col, plot_col).servable()

    def _populate_error_box(self, error_box_ref, errors):
        error_box = getattr(self, error_box_ref)
        good_layout = widgets.Layout(
            display="none",
            visibility="hidden",
            border="none",
        )
        bad_layout = widgets.Layout(
            border="2px solid #dc3545",
            padding="0.05rem 0.5rem",
            margin="0 0.25rem 0 5.625rem",
            width="70%",
            overflow="auto",
            display="flex",
        )
        error_box.value = errors
        error_box.layout = good_layout if errors == "" else bad_layout

    def _load_collections(self, event):
        """
        Callback when the `connect` button is clicked.

        Set up the EDR interface instance and connect to the server's collections.

        """
        self._clear_controls()
        server_loc = self.coll_uri.value
        self.edr_interface = EDRInterface(server_loc)

        error_box = "connect_error_box"
        if self.edr_interface.errors is None:
            # Independent check to see if we can clear the error box.
            self._populate_error_box(error_box, "")
        if self.edr_interface.json is not None and self.edr_interface.errors is None:
            # The only state in which the controls can be populated and enabled.
            self.coll.options = [(ct, cid) for (cid, ct) in zip(self.edr_interface.collection_ids, self.edr_interface.collection_titles)]
            self.coll.value = self.edr_interface.collection_ids[0]
            self._enable_controls()
        elif self.edr_interface.errors is not None:
            # We have known errors to show.
            self._populate_error_box(error_box, self.edr_interface.errors)
        else:
            # Something else has gone wrong, which we need to show.
            self._populate_error_box(error_box, "UnspecifiedError")

    def _enable_controls(self):
        """Enable query control widgets in the left column."""
        for widget in self.wlist:
            widget.disabled = False
        self.submit_button.disabled = False

    def _clear_controls(self):
        """Clear state of all control and error display widgets and disable them."""
        for widget in self.wlist + self.pwlist:
            widget.disabled = True
            if isinstance(widget, widgets.SelectMultiple):
                widget.options = ("",)
                widget.value = ("",)
            elif isinstance(widget, widgets.SelectionSlider):
                widget.options = ("",)
                widget.value = ""
            else:
                widget.options = []
                widget.value = None
        for box in self.pchecklist:
            box.value = False
            box.disabled = True
        self.submit_button.disabled = True
        self.dataset_button.disabled = True
        self._populate_error_box("connect_error_box", "")
        self._populate_error_box("data_error_box", "")

    def _check_enable_checkboxes(self):
        """
        Check if we can enable the checkboxes to specify the plot should
        use colours and levels specified in the data JSON. This is only
        possible if this information is present in the data JSON.

        """
        box_disabled = self.edr_interface.data_handler.get_colours(self.pc_params.value) is None
        for box in self.pchecklist:
            box.disabled = box_disabled

    def _checkbox_change(self, event):
        """
        Bind a change in a checkbox to the relevant param object to trigger
        a plot update.

        """
        name = event.obj.name
        if "colour" in name:
            self._colours = event.new
        elif "level" in name:
            self._levels = event.new

    def _enable_plot_controls(self):
        """Enable plot control widgets for updating the specific data shown on the plot."""
        for widget in self.pwlist:
            widget.disabled = False
        self.dataset_button.disabled = False
        self._check_enable_checkboxes()

    def _populate_contents_callback(self, change):
        """
        Populate the options and values attributes of all the left column query control
        widgets when a collection provided by the EDR Server is specified.

        """
        collection_id = change["new"]
        if collection_id is not None:
            # Parameters and locations.
            self._populate_params(collection_id)
            locs = self.edr_interface.get_locations(collection_id)
            self.locations.options = locs
            # Times.
            if self.edr_interface.has_temporal_extent(collection_id):
                times = self.edr_interface.get_temporal_extent(collection_id)
            else:
                times = [self._no_t]
            self.start_time.options = times
            self.end_time.options = times
            # Vertical levels.
            if self.edr_interface.has_vertical_extent(collection_id):
                zs = self.edr_interface.get_vertical_extent(collection_id)
            else:
                zs = [self._no_z]
            self.start_z.options = zs
            self.end_z.options = zs

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
        if start_time_selected is not None:
            # Avoid errors when clearing widget state.
            times = self.start_time.options
            sel_idx = times.index(start_time_selected)
            self.end_time.options = times[sel_idx:]

    def _filter_end_z(self, change):
        """
        Only show end vertical values in the `End Z` widget that are greater than
        the value selected in the `Start Z` widget.

        """
        start_z_selected = change["new"]
        if start_z_selected is not None:
            # Avoid errors when clearing widget state.
            zs = self.start_z.options
            sel_idx = zs.index(start_z_selected)
            self.end_z.options = zs[sel_idx:]

    def _get_dataset(self, _):
        """
        Callback when the `get dataset` button is clicked.

        Request from the EDR Server all data represented by the current states of
        the select widgets and provide this data as a well-known Python data
        object (such as an Iris Cube).

        """
        # XXX somewhere we should check if the server supports `Cube` queries,
        #     and preferentially use that if available.
        from .dataset import make_dataset

        collection_id = self.coll.value
        params = self.edr_interface.get_collection_parameters(collection_id)
        keys = self.datasets.value
        names_dict = {k: v["label"] for k, v in params.items() if k in keys}
        dataset = make_dataset(self.edr_interface.data_handler, names_dict)
        self.dataset = dataset

    def _geometry_stream_data(self, query_name):
        """
        Return the data attribute of the holoviews stream referenced by `query_name`.
        
        """
        ref = f"_{query_name}_stream"
        geom_stream = getattr(self, ref)
        return geom_stream.data

    def _geometry_query_is_defined(self, query_name):
        """
        Determine whether a geometry specified by `query_name` has been defined.
        We determine this by checking if all the values in its x and y coords
        are 0 - if they are, we assume it's in its default state and thus
        undefined.

        """
        data = self._geometry_stream_data(query_name)
        return all(data["xs"][0]) and all(data["ys"][0])

    def _hv_stream_to_wkt(self, query_name):
        """
        Convert the data points in the geometry specified by `query_name` to
        the appropriate Shapely geometry, and return the WKT string representation
        of the geometry.
        
        """
        constructor = sPolygon if query_name == "area" else sLineString
        data = self._geometry_stream_data(query_name)
        geom = constructor(zip(data["xs"][0], data["ys"][0]))
        return geom.wkt

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
        start_z = self.start_z.value
        end_z = self.end_z.value

        # Define common query parameters.
        dates = [start_date, end_date] if start_date != self._no_t else None
        zs = [start_z, end_z] if start_z != self._no_z else None
        query_params = dict(datetime=dates, z=zs)

        # Set query type.
        if self._geometry_query_is_defined("area"):
            query_type = "area"
            query_params["coords"] = self._hv_stream_to_wkt(query_type)
        elif self._geometry_query_is_defined("corridor"):
            query_type = "corridor"
            query_params["coords"] = self._hv_stream_to_wkt(query_type)
        else:
            query_type = "locations"
            query_params["loc_id"] = locations

        # Request dataset.
        self.edr_interface.query(coll_id, query_type, param_names, **query_params)

        error_box = "data_error_box"
        if self.edr_interface.errors is None:
            # Independent check to see if we can clear the error box.
            self._populate_error_box(error_box, "")
        if self.edr_interface.data_handler is not None and self.edr_interface.errors is None:
            # Generate and enable the plot controls.
            if self.edr_interface.has_temporal_extent(coll_id):
                plot_control_times = list(self.edr_interface.data_handler.coords["t"])
            else:
                plot_control_times = [self._no_t]
            self.pc_times.options = plot_control_times
            self.pc_times.value = plot_control_times[0]

            if self.edr_interface.has_vertical_extent(coll_id):
                plot_control_zs = list(self.edr_interface.data_handler.coords["z"])
            else:
                plot_control_zs = [self._no_z]
            self.pc_zs.options = plot_control_zs
            self.pc_zs.value = plot_control_zs[0]

            plot_control_params = list(param_names)
            self.pc_params.options = list(filter(lambda o: o[1] in plot_control_params, self.datasets.options))
            self.pc_params.value = plot_control_params[0]

            self._enable_plot_controls()
        elif self.edr_interface.errors is not None:
            self._populate_error_box(error_box, self.edr_interface.errors)
        else:
            self._populate_error_box(error_box, "UnspecifiedError (data retrieval)")

    def _plot_change(self, _):
        """
        Helper function to capture changes from either plot control widget
        and trigger an update of the plot.

        """
        param = self.pc_params.value
        t = self.pc_times.value
        z = self.pc_zs.value
        can_request_data = False
        self._check_enable_checkboxes()

        value_dict = {}
        if t not in (None, "", self._no_t):
            value_dict.update({"t": t})
            can_request_data = True
        if z not in (None, "", self._no_z):
            value_dict.update({"z": z})
            can_request_data = True

        if param is not None and can_request_data:
            self._data_key = self.edr_interface.data_handler.make_key(param, value_dict)

    def _query_tools(self):
        self._area_poly = hv.Polygons(
            [[(0, 0), (0, 0)]]
        ).opts(
            line_color="gray", line_width=1.5, line_alpha=0.75,
            fill_color="gray", fill_alpha=0.3,
        )
        self._corridor_path = hv.Path(
            [[(0, 0), (0, 0)]]
        ).opts(
            color="gray", line_width=2, line_alpha=0.75,
        )
        self._area_stream = hv.streams.PolyDraw(
            source=self._area_poly,
            num_objects=1,
            tooltip="Area Query Tool"
        )
        self._corridor_stream = hv.streams.PolyDraw(
            source=self._corridor_path,
            num_objects=1,
            tooltip="Corridor Query Tool"
        )

    @param.depends('_data_key', '_colours', '_levels', 'cmap', 'alpha')
    def make_plot(self):
        """Show data from a data request to the EDR Server on the plot."""
        showable = gv.Image(
            ([-8, -1], [53, 58], [[0, 0], [0, 0]]),  # Approximate UK extent.
            crs=CRS_LOOKUP["WGS_1984"],
        ).opts(alpha=0.0)
        if self._data_key != "":
            dataset = self.edr_interface.data_handler[self._data_key]
            opts = {"cmap": self.cmap, "alpha": self.alpha, "colorbar": True}

            colours = self.edr_interface.data_handler.get_colours(self.pc_params.value)
            if colours is not None:
                opts.update({"clim": (colours["vmin"], colours["vmax"])})
                if self.use_colours.value:
                    opts["cmap"] = colours["colours"]
                if self.use_levels.value:
                    opts["color_levels"] = colours["values"]

            error_box = "data_error_box"
            if self.edr_interface.data_handler.errors is None:
                # Independent check to see if we can clear the data error box.
                self._populate_error_box(error_box, "")
            if dataset is not None and self.edr_interface.data_handler.errors is None:
                showable = dataset.to(gv.Image, ['longitude', 'latitude']).opts(**opts)
            elif self.edr_interface.data_handler.errors is not None:
                self._populate_error_box(
                    error_box,
                    self.edr_interface.data_handler.errors
                )
            else:
                self._populate_error_box(
                    error_box,
                    "Unspecified error (plotting)"
                )
        return showable * self._area_poly * self._corridor_path