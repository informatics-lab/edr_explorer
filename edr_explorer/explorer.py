import cartopy.crs as ccrs
import ipywidgets as widgets

import geoviews as gv
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

    # Error display widgets.
    connect_error_box = widgets.HTML("", layout=widgets.Layout(display="none"))
    data_error_box = widgets.HTML("", layout=widgets.Layout(display="none"))

    # Plot control widgets.
    pc_times = widgets.SelectionSlider(options=[""], description="Timestep", disabled=True)
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
    wlist = [coll, locations, datasets, start_time, end_time]  # Metadata widgets.
    pwlist = [pc_times, pc_params]  # Plot widgets.
    pchecklist = [use_colours, use_levels]
    wbox = widgets.VBox(wlist)
    pwbox = pn.Row(*pwlist, pn.Column(*pchecklist))

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

        # Button click bindings.
        self.connect_button.on_click(self._load_collections)
        self.submit_button.on_click(self._request_plot_data)
        self.dataset_button.on_click(self._get_dataset)

        # Watches on widgets.
        self.coll.observe(self._populate_contents_callback, names='value')
        self.start_time.observe(self._filter_end_time, names='value')
        self.pc_times.observe(self._plot_change, names='value')
        self.pc_params.observe(self._plot_change, names='value')
        self.use_colours.param.watch(self._checkbox_change, "value", onlychanged=True)
        self.use_levels.param.watch(self._checkbox_change, "value", onlychanged=True)

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
        plot_col = pn.Column(self.plot, self.pwbox)
        control_col = pn.Column(connect_row, control_row)
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
        if start_time_selected is not None:
            # Avoid errors when clearing widget state.
            times = self.start_time.options
            sel_idx = times.index(start_time_selected)
            self.end_time.options = times[sel_idx:]

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
        dataset = make_dataset(self.edr_interface.data_handler, self.pc_params.value)
        self.dataset = dataset

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

        # Get dataset.
        self.edr_interface.query_locations(coll_id, locations, param_names, start_date, end_date)

        error_box = "data_error_box"
        if self.edr_interface.errors is None:
            # Independent check to see if we can clear the error box.
            self._populate_error_box(error_box, "")
        if self.edr_interface.data_handler is not None and self.edr_interface.errors is None:
            # Generate and enable the plot controls.
            plot_control_times = list(self.edr_interface.data_handler.coords["t"])
            self.pc_times.options = plot_control_times
            self.pc_times.value = plot_control_times[0]

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
        self._check_enable_checkboxes()
        # Make sure both widgets are populated.
        if param is not None and t not in (None, ""):
            self._data_key = self.edr_interface.data_handler.make_key(param, {"t": t})

    @param.depends('_data_key', '_colours', '_levels', 'cmap', 'alpha')
    def plot(self):
        """Show data from a data request to the EDR Server on the plot."""
        tiles = gv.tile_sources.Wikipedia.opts(width=800, height=600)
        showable = tiles
        if self._data_key != "":
            dataset = self.edr_interface.data_handler[self._data_key]
            opts = {"cmap": self.cmap, "alpha": self.alpha}

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
                showable = tiles * dataset.to(
                    gv.Image,
                    ['longitude', 'latitude']
                ).opts(**opts)
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
        return showable