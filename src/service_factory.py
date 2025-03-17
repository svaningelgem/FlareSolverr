from functools import lru_cache
from typing import TypeVar

from loguru import logger

import utils
from abstract_base import BaseService

T = TypeVar("T", bound=BaseService)


@lru_cache(1)
def get() -> BaseService:
    """Create the appropriate service based on configuration"""
    driver_selection = utils.get_driver_selection()

    if driver_selection == "nodriver":
        from async_implementation import AsyncService

        logger.debug("Creating AsyncService (nodriver)")
        return AsyncService()
    else:
        from sync_implementation import SyncService

        logger.debug("Creating SyncService (standard)")
        return SyncService()
