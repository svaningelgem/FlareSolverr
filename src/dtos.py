STATUS_OK = "ok"
STATUS_ERROR = "error"


class ChallengeResolutionResultT:
    url: str = None
    status: int = None
    headers: list = None
    response: str = None
    cookies: list = None
    user_agent: str = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)


class ChallengeResolutionT:
    status: str = None
    message: str = None
    result: ChallengeResolutionResultT = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)
        if self.result is not None:
            self.result = ChallengeResolutionResultT(self.result)


class V1RequestBase:
    # V1RequestBase
    cmd: str = None
    cookies: list = None
    max_timeout: int = None
    proxy: dict = None
    session: str = None
    session_ttl_minutes: int = None

    # V1Request
    url: str = None
    post_data: str = None
    return_only_cookies: bool = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)


class V1ResponseBase:
    # V1ResponseBase
    status: str = None
    message: str = None
    session: str = None
    sessions: list[str] = None
    start_timestamp: int = None
    end_timestamp: int = None
    version: str = None

    # V1ResponseSolution
    solution: ChallengeResolutionResultT = None

    # hidden vars
    __error_500__: bool = False

    def __init__(self, _dict):
        self.__dict__.update(_dict)
        if self.solution is not None:
            self.solution = ChallengeResolutionResultT(self.solution)


class IndexResponse:
    msg: str = None
    version: str = None
    user_agent: str = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)


class HealthResponse:
    status: str = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)
