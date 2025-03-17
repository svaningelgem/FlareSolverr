import asyncio
import inspect
from typing import Any, TypeVar

from loguru import logger

T = TypeVar("T")


def call_method(obj: Any, method_name: str, *args, **kwargs) -> Any:
    """
    Call a method that might be synchronous or asynchronous.

    Args:
        obj: Object containing the method
        method_name: Name of the method to call
        *args: Positional arguments to pass to the method
        **kwargs: Keyword arguments to pass to the method

    Returns:
        The return value of the method
    """
    if not hasattr(obj, method_name):
        raise AttributeError(f"Object has no method named '{method_name}'")

    method = getattr(obj, method_name)

    if inspect.iscoroutinefunction(method):
        logger.debug(f"Calling async method: {method_name}")
        return asyncio.run(method(*args, **kwargs))
    else:
        logger.debug(f"Calling sync method: {method_name}")
        return method(*args, **kwargs)
