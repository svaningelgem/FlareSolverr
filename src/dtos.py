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
        # Convert old camelCase keys to snake_case for backward compatibility
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
    max_timeout: int = None
    proxy: dict = None
    session: str = None
    session_ttl_minutes: int = None

    # V1Request
    url: str = None
    post_data: str = None
    return_only_cookies: bool = None

    def __init__(self, _dict):
        # Convert old camelCase keys to snake_case for backward compatibility
        if "maxTimeout" in _dict:
            _dict["max_timeout"] = _dict.pop("maxTimeout")
        if "userAgent" in _dict:
            _dict.pop("userAgent")  # Ignore deprecated field
        if "postData" in _dict:
            _dict["post_data"] = _dict.pop("postData")
        if "returnOnlyCookies" in _dict:
            _dict["return_only_cookies"] = _dict.pop("returnOnlyCookies")
        if "returnRawHtml" in _dict:
            _dict.pop("returnRawHtml")  # Ignore deprecated field
        if "download" in _dict:
            _dict.pop("download")  # Ignore deprecated field
        if "headers" in _dict:
            _dict.pop("headers")  # Ignore deprecated field

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
        # Convert old camelCase keys to snake_case for backward compatibility
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
    user_agent: str = None

    def __init__(self, _dict):
        # Convert old camelCase keys to snake_case for backward compatibility
        if "userAgent" in _dict:
            _dict["user_agent"] = _dict.pop("userAgent")

        self.__dict__.update(_dict)


class HealthResponse:
    status: str = None

    def __init__(self, _dict):
        self.__dict__.update(_dict)
