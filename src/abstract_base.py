# abstract_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple, List, TypeVar, Generic

from dtos import V1RequestBase, V1ResponseBase, ChallengeResolutionT

DriverT = TypeVar('DriverT')  # Type variable for driver implementations

@dataclass
class BaseSession(Generic[DriverT]):
    """Base class for browser sessions"""
    session_id: str
    driver: DriverT
    created_at: datetime

    def lifetime(self) -> timedelta:
        return datetime.now() - self.created_at

class BaseSessionsStorage(ABC, Generic[DriverT]):
    """Abstract base class for session management"""

    def __init__(self):
        self.sessions = {}

    def exists(self, session_id: str) -> bool:
        return session_id in self.sessions

    def session_ids(self) -> List[str]:
        return list(self.sessions.keys())

    @abstractmethod
    def create(self, session_id: Optional[str] = None, proxy: Optional[dict] = None,
               force_new: Optional[bool] = False) -> Tuple[BaseSession[DriverT], bool]:
        """Create a new session or return existing one"""
        pass

    @abstractmethod
    def destroy(self, session_id: str) -> bool:
        """Destroy a session and return whether it existed"""
        pass

    @abstractmethod
    def get(self, session_id: str, ttl: Optional[timedelta] = None) -> Tuple[BaseSession[DriverT], bool]:
        """Get a session, creating it if needed or expired"""
        pass

class BaseService(ABC):
    """Abstract base class for FlareSolver service implementations"""

    @abstractmethod
    def test_browser_installation(self):
        """Test if browser is properly installed"""
        pass

    @abstractmethod
    def controller_v1_endpoint(self, req: V1RequestBase) -> V1ResponseBase:
        """Handle controller V1 endpoint"""
        pass

    @abstractmethod
    def _resolve_challenge(self, req: V1RequestBase, method: str) -> ChallengeResolutionT:
        """Resolve CloudFlare challenge"""
        pass