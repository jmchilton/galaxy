from sys import getsizeof

from galaxy.util.object_size import total_size


def test_total_size_counts_nested_values_once():
    value = "shared metadata value"
    container = {"left": value, "right": value}

    assert total_size(container) == sum(getsizeof(item) for item in (container, "left", "right", value))


def test_total_size_handles_cycles():
    container: list[object] = []
    container.append(container)

    assert total_size(container) == getsizeof(container)


def test_total_size_supports_custom_handlers():
    class Wrapper:
        def __init__(self, value):
            self.value = value

    wrapped = Wrapper("metadata value")

    assert total_size(wrapped, {Wrapper: lambda item: (item.value,)}) == getsizeof(wrapped) + getsizeof(wrapped.value)
