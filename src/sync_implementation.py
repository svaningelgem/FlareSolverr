# sync_implementation.py
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
from uuid import uuid1

from selenium.webdriver.chrome.webdriver import WebDriver

import utils
from abstract_base import BaseService, BaseSession, BaseSessionsStorage
from dtos import STATUS_ERROR, V1RequestBase, V1ResponseBase, ChallengeResolutionT

class SyncSession(BaseSession[WebDriver]):
    """Standard WebDriver session"""
    pass

class SyncSessionsStorage(BaseSessionsStorage[WebDriver]):
    """Synchronous session storage implementation"""

    def create(self, session_id: Optional[str] = None, proxy: Optional[dict] = None,
               force_new: Optional[bool] = False) -> Tuple[SyncSession, bool]:
        session_id = session_id or str(uuid1())

        if force_new:
            self.destroy(session_id)

        if self.exists(session_id):
            return self.sessions[session_id], False

        driver = utils.get_webdriver_uc(proxy)
        session = SyncSession(session_id, driver, datetime.now())
        self.sessions[session_id] = session

        return session, True

    def destroy(self, session_id: str) -> bool:
        if not self.exists(session_id):
            return False

        session = self.sessions.pop(session_id)
        if utils.get_current_platform() == "nt":
            session.driver.close()
        session.driver.quit()
        return True

    def get(self, session_id: str, ttl: Optional[timedelta] = None) -> Tuple[SyncSession, bool]:
        session, fresh = self.create(session_id)

        if ttl is not None and not fresh and session.lifetime() > ttl:
            logging.debug(f'Session lifetime expired, recreating (session_id={session_id})')
            session, fresh = self.create(session_id, force_new=True)

        return session, fresh

class SyncService(BaseService):
    """Synchronous service implementation"""

    def __init__(self):
        self.sessions_storage = SyncSessionsStorage()

    def test_browser_installation(self):
        # Implement browser testing logic
        utils.get_user_agent_uc()

    def controller_v1_endpoint(self, req: V1RequestBase) -> V1ResponseBase:
        start_ts = int(time.time() * 1000)
        logging.info(f"Incoming request => POST /v1 body: {utils.object_to_dict(req)}")
        res: V1ResponseBase
        try:
            res = self._controller_v1_handler(req)
        except Exception as e:
            res = V1ResponseBase({})
            res.__error_500__ = True
            res.status = STATUS_ERROR
            res.message = "Error: " + str(e)
            logging.error(res.message)

        res.startTimestamp = start_ts
        res.endTimestamp = int(time.time() * 1000)
        res.version = utils.get_flaresolverr_version()

        return res

    def _resolve_challenge(self, req: V1RequestBase, method: str) -> ChallengeResolutionT:
        # Implement challenge resolution logic
        pass

    def _controller_v1_handler(self, req: V1RequestBase) -> V1ResponseBase:
        # Implement controller logic
        pass