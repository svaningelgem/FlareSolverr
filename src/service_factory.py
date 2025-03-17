# service_factory.py
import utils

def create_service():
    """Create appropriate service based on configuration"""
    driver_selection = utils.get_driver_selection()
    if driver_selection == "nodriver":
        from async_implementation import AsyncService
        return AsyncService()
    else:
        from sync_implementation import SyncService
        return SyncService()