import importlib
import inspect
import logging
from typing import Union, TypeVar, Any

import utils
from abstract_base import BaseService

T = TypeVar('T', bound=BaseService)

def create_service() -> BaseService:
    """Create the appropriate service based on configuration"""
    driver_selection = utils.get_driver_selection()

    if driver_selection == "nodriver":
        from async_implementation import AsyncService
        logging.debug("Creating AsyncService (nodriver)")
        return AsyncService()
    else:
        from sync_implementation import SyncService
        logging.debug("Creating SyncService (standard)")
        return SyncService()

def is_async_method(obj: Any, method_name: str) -> bool:
    """Check if a method is async"""
    if not hasattr(obj, method_name):
        return False
    return inspect.iscoroutinefunction(getattr(obj, method_name))