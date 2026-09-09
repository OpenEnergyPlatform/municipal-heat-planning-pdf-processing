# docpipe.dotenv

`docpipe/dotenv.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

dotenv.py – Populate os.environ from a `.env` file before anything reads it.

Config modules across docpipe capture their values at import time
(`LLM_API_KEY = os.environ.get(...)`). Whoever loads the .env therefore has to
win the race against the first such import — and an app that imports
docpipe.inference before its own config module loses it silently: the key is
simply "EMPTY" and the endpoint answers 401.

So the load happens in docpipe/\_\_init\_\_.py, which by definition runs before any
module under docpipe.

Only keys not already set are added, so an explicit environment variable — a
SLURM script's export, a systemd `Environment=` — always wins over the file.

Author: Felix Vossel

## Functions

### load_dotenv

```python
def load_dotenv() -> Path | None
```

Read the first readable candidate into os.environ; return which one.

[Back to the index](../README.md)
