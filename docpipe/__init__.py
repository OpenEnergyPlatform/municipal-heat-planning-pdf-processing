"""docpipe – generic PDF extraction pipeline. Projects plug in via profiles/."""
from .dotenv import load_dotenv as _load_dotenv

# Before any submodule's config captures os.environ. See dotenv.py.
_load_dotenv()
