import random
import string
from collections.abc import Iterator
from contextlib import contextmanager

from galaxy import model
from galaxy.objectstore import BaseObjectStore


def random_str() -> str:
    alphabet = string.ascii_lowercase + string.digits
    size = random.randint(5, 10)
    return "".join(random.choices(alphabet, k=size))


def random_email() -> str:
    text = random_str()
    return f"{text}@galaxy.testing"


@contextmanager
def global_object_store_for_models(object_store: BaseObjectStore) -> Iterator[None]:
    """Use ``object_store`` as the models' global object store, restoring the previous one on exit."""
    previous_object_store = model.Dataset.object_store
    model.setup_global_object_store_for_models(object_store)
    try:
        yield
    finally:
        model.Dataset.object_store = previous_object_store
