from dataclasses import dataclass, field

STATUS_OK = "ok"
STATUS_ERROR = "error"


@dataclass
class ChallengeResolutionResultT:
    url: str = None
    status: int = None
    headers: list = None
    response: str = None
    cookies: list = None
    user_agent: str = None


@dataclass
class ChallengeResolutionT:
    status: str = None
    message: str = None
    result: ChallengeResolutionResultT = None

    def __post_init__(self):
        if self.result is not None:
            self.result = ChallengeResolutionResultT(**self.result)


@dataclass
class Request:
    cmd: str = None
    cookies: list = None
    max_timeout: int = None
    proxy: dict = None
    session: str = None
    session_ttl_minutes: int = None

    url: str = None
    post_data: str = None
    return_only_cookies: bool = None
    headers: dict = field(default_factory=dict)

    def __post_init__(self):
        self.headers = {k.lower(): v for k, v in self.headers.items()}


@dataclass
class Response:
    status: str = None
    message: str = None
    session: str = None
    sessions: list[str] = None
    start_timestamp: int = None
    end_timestamp: int = None
    version: str = None
    headers: dict = None

    solution: ChallengeResolutionResultT = None

    def __post_init__(self):
        if self.solution is not None:
            self.solution = ChallengeResolutionResultT(**self.solution)


@dataclass
class IndexResponse:
    msg: str = None
    version: str = None
    user_agent: str = None


@dataclass
class HealthResponse:
    status: str = None
