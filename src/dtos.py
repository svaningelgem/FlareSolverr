STATUS_OK = "ok"
STATUS_ERROR = "error"


class ChallengeResolutionResultT:
    url: str = None
    status: int = None
    headers: list = None
    response: str = None
    cookies: list = None
    user_agent: str = None  # Changed from userAgent

    def __init__(self, _dict):
        # Convert old camelCase keys to snake_case
        if "userAgent" in _dict:
            _dict["user_agent"] = _dict.pop("userAgent")

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
    max_timeout: int = None  # Changed from maxTimeout
    proxy: dict = None
    session: str = None
    session_ttl_minutes: int = None
    headers: list = None  # deprecated v2.0.0, not used
    user_agent: str = None  # Changed from userAgent, deprecated v2.0.0, not used

    # V1Request
    url: str = None
    post_data: str = None  # Changed from postData
    return_only_cookies: bool = None  # Changed from returnOnlyCookies
    download: bool = None  # deprecated v2.0.0, not used
    return_raw_html: bool = None  # Changed from returnRawHtml, deprecated v2.0.0, not used

    def __init__(self, _dict):
        # Convert old camelCase keys to snake_case
        if "maxTimeout" in _dict:
            _dict["max_timeout"] = _dict.pop("maxTimeout")
        if "userAgent" in _dict:
            _dict["user_agent"] = _dict.pop("userAgent")
        if "postData" in _dict:
            _dict["post_data"] = _dict.pop("postData")
        if "returnOnlyCookies" in _dict:
            _dict["return_only_cookies"] = _dict.pop("returnOnlyCookies")
        if "returnRawHtml" in _dict:
            _dict["return_raw_html"] = _dict.pop("returnRawHtml")

        self.__dict__.update(_dict)


class V1ResponseBase:
    # V1ResponseBase
    status: str = None
    message: str = None
    session: str = None
    sessions: list[str] = None
    start_timestamp: int = None  # Changed from startTimestamp
    end_timestamp: int = None  # Changed from endTimestamp
    version: str = None

    # V1ResponseSolution
    solution: ChallengeResolutionResultT = None

    # hidden vars
    __error_500__: bool = False

    def __init__(self, _dict):
        # Convert old camelCase keys to snake_case
        if "startTimestamp" in _dict:
            _dict["start_timestamp"] = _dict.pop("startTimestamp")
        if "endTimestamp" in _dict:
            _dict["end_timestamp"] = _dict.pop("endTimestamp")

        self.__dict__.update(_dict)
        if self.solution is not None:
            self.solution = ChallengeResolutionResultT(self.solution)


class IndexResponse:
    msg: str = None
    version: str = None
    user_agent: str = None  # Changed from userAgent

    def __init__(self, _dict):
        # Convert old camelCase keys to snake_case
        if "userAgent" in _dict:
            _dict["user_agent"] = _dict.pop("userAgent")

        self.__dict__.update(_dict)


class HealthResponse:
    status: str = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)
