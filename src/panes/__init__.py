# todo: dynamically load these for drag/drop modularity

from .deviceinfo.pane import DeviceInfoPane
from .display.pane import DisplayPane
from .splash.pane import SplashPane
from .about.pane import AboutPane
from .templates.pane import TemplatesPane
from .notebooks.pane import NotebooksPane
from .software.pane import SoftwarePane
from .printer.pane import PrinterPane
from .incompatible.pane import IncompatiblePane

paneslist = [
    DeviceInfoPane,
    DisplayPane,
    NotebooksPane,
    TemplatesPane,
    SplashPane,
    SoftwarePane,
    PrinterPane,
    AboutPane
]
