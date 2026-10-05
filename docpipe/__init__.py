"""docpipe: generic PDF extraction pipeline. Projects plug in via profiles/."""
from .dotenv import load_dotenv as _load_dotenv

__version__ = "0.1.0"

# Before any submodule's config captures os.environ. See dotenv.py.
_load_dotenv()

# And underneath it the project file, for what the environment leaves open.
# See settings.py.
from . import settings as _settings          # noqa: E402

try:
    _settings.apply()
except _settings.ConfigError as _error:
    raise SystemExit(str(_error)) from None
