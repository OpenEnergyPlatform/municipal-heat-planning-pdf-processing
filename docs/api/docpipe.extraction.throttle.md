# docpipe.extraction.throttle

`docpipe/extraction/throttle.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

throttle.py: How many model requests the harvest keeps open, steered by the
server's own queue.

A fixed number of client threads left the server idle: at 140 requests in
flight vLLM reported nothing waiting and 58 percent of its KV cache in use,
so the harvest, not the four GPUs, set the pace. The right number is not a
constant either. It moves with what is being asked (a field request over two
passages is a fraction of a rows request over a table) and with how much of
each prompt the server already holds in its prefix cache.

So the limit is steered while the run goes (additive increase, multiplicative
decrease). Every few seconds the controller reads the server's /metrics:

  up    nothing waiting, the KV cache below KV_GROW, and the client actually
        using the limit it has
  down  requests waiting (twice in a row), the KV cache at KV_HIGH, or a
        preemption

The time per output token is not a reason to step down: it grows with every
sequence in the batch while the tokens per second of the whole batch still
rise, and those are what the harvest waits for. EXTRACT_LIMIT_TPOT_MAX makes
it one for a server shared with interactive users.

After a step down it holds for a few samples, so the server can drain before
it is pushed again. A server without /metrics gets no limit at all, and one
that stops answering them leaves the limit where it is. The limit decides only
when a request is sent, never what it asks or what is accepted from its answer.

## Classes

### AdaptiveLimit

```python
class AdaptiveLimit
```

A semaphore whose size can change while requests hold it.

#### AdaptiveLimit.\_\_init\_\_

```python
def __init__(self, start: int = START, minimum: int = MINIMUM,
             maximum: int = MAXIMUM)
```

#### AdaptiveLimit.limit

```python
@property
def limit(self) -> int
```

#### AdaptiveLimit.in_flight

```python
@property
def in_flight(self) -> int
```

#### AdaptiveLimit.take_peak

```python
def take_peak(self) -> int
```

The most requests open at once since the last call.

#### AdaptiveLimit.acquire

```python
def acquire(self) -> None
```

#### AdaptiveLimit.release

```python
def release(self) -> None
```

#### AdaptiveLimit.resize

```python
def resize(self, limit: int) -> int
```

### Limited

```python
class Limited
```

A client whose chat.completions.create waits for a place in *limit*.

The client's own timeout starts once the place is taken: waiting here is
the harvest's queue, not the server's slowness.

#### Limited.\_\_init\_\_

```python
def __init__(self, client, limit: AdaptiveLimit)
```

#### Limited.create

```python
def create(self, *args, **kwargs)
```

### Sample

```python
@dataclass
class Sample
```

One reading of the server, differences taken against the last one.

Fields:

- `running: float`
- `waiting: float`
- `kv: float`: fraction of KV cache blocks in use
- `preempted: float = 0.0`: preemptions since the last sample
- `tpot: Optional[float] = None`: mean seconds per output token

### Reader

```python
class Reader
```

Samples the server's /metrics, turning counters into differences.

#### Reader.\_\_init\_\_

```python
def __init__(self, base_url: str, timeout: float = 3.0)
```

#### Reader.fetch

```python
def fetch(self) -> str
```

#### Reader.sample

```python
def sample(self) -> Optional[Sample]
```

### Controller

```python
class Controller
```

Decides the next limit from one sample; no threads, no I/O.

#### Controller.\_\_init\_\_

```python
def __init__(self, limit: AdaptiveLimit, *, step: int = STEP,
             backoff: float = BACKOFF, kv_grow: float = KV_GROW,
             kv_high: float = KV_HIGH,
             tpot_max: Optional[float] = TPOT_MAX)
```

#### Controller.decide

```python
def decide(self, sample: Sample, used: int) -> tuple
```

(new limit, reason) for *sample*, *used* the peak requests open.

## Functions

### parse_metrics

```python
def parse_metrics(text: str) -> dict
```

{metric name: value summed over its label sets} from Prometheus text.

### start

```python
def start(base_url: str, *, limit: Optional[AdaptiveLimit] = None,
          reader: Optional[Reader] = None,
          poll: float = POLL) -> Optional[AdaptiveLimit]
```

An adaptive limit and the daemon thread that steers it.

None when the server does not serve vLLM's /metrics: without a queue to
read there is nothing to steer by, and the thread pools bound the
requests as they did before.

[Back to the index](../README.md)
