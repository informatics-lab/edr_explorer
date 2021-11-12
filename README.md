# edr_explorer
Interface with an EDR Server and explore its contents from a Python session.

## Installation

No pip / conda installer (yet). Download the source code / clone this repo and add the repo root to your `$PYTHONPATH` using your preferred method...

### Dependencies

EDR Explorer is dependent on the following Python packages:

* NumPy,
* Cartopy,
* IPyWidgets (and JupyterLab if you wish to use the explorer interface in a notebook), and
* GeoViews, HoloViews, Panel and Param

## Using it

The explorer interface is produced as a Panel application, and intended for use either in a Jupyter notebook or as a standalone Panel application. In the future we hope to add a commandline-based interface as well.

To set up an explorer interface:

```python
from edr_explorer import EDRExplorer

explorer = EDRExplorer()
explorer.layout
```

This can be used either in a notebook or in a Python script that can be served by Panel. For example, assuming that the Python script is called `run.py`:

```bash
panel serve --show run.py
```

You can also pass the URI for a running EDR Server to the explorer interface when you instantiate it. For example:

```python
explorer = EDRExplorer("http://localhost:8000")
```

This will pre-populate the server location field in the explorer interface.