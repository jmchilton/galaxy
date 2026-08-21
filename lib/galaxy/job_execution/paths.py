"""Path helpers shared by job setup and lightweight metadata workers."""


def dataset_path_to_extra_path(path: str) -> str:
    base_path = path[: -len(".dat")]
    return f"{base_path}_files"


__all__ = ("dataset_path_to_extra_path",)
