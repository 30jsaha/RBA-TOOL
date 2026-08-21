import os
import threading


_local = threading.local()


def set_runtime_context(**kwargs):
    _local.values = dict(kwargs)


def clear_runtime_context():
    _local.values = {}


def get_runtime_value(name, default=None):
    values = getattr(_local, "values", {})
    return values.get(name, default)


def get_output_dir(default_dir: str) -> str:
    output_dir = get_runtime_value("output_dir", default_dir)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def get_artifact_path(key: str, default_name: str, default_dir: str) -> str:
    value = get_runtime_value(key)
    if value:
        return os.path.abspath(value)
    return os.path.join(get_output_dir(default_dir), default_name)
