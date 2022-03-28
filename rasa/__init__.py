import logging

from rasa import version  # noqa: F401
from rasa.api import run, train, test  # noqa: F401

# define the version before the other imports since these need it
__version__ = version.__version__
__version_bf__ = version.__version__ + version.__bf_patch__


logging.getLogger(__name__).addHandler(logging.NullHandler())
