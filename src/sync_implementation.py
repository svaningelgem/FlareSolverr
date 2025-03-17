import logging
import platform
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, cast
from urllib.parse import unquote
from uuid import uuid1

from func_timeout import FunctionTimedOut, func_timeout
from selenium.common import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import presence_of_element_located, staleness_of, title_is
from selenium.webdriver.support.wait import WebDriverWait

import utils
from abstract_base import BaseService, BaseSession, BaseSessionsStorage
from dtos import (
    STATUS_ERROR,
    STATUS_OK,
    ChallengeResolutionResultT,
    ChallengeResolutionT,
    HealthResponse,
    IndexResponse,
    V1RequestBase,
    V1ResponseBase,
)

# Constants from flaresolverr_service.py
ACCESS_DENIED_TITLES = [
    # Cloudflare
    "Access denied",
    # Cloudflare http://bitturk.net/ Firefox
    "Attention Required! | Cloudflare",
]
ACCESS_DENIED_SELECTORS = [
    # Cloudflare
    "div.cf-error-title span.cf-code-label span",
    # Cloudflare http://bitturk.net/ Firefox
    "#cf-error-details div.cf-error-overview h1",
]
CHALLENGE_TITLES = [
    # Cloudflare
    "Just a moment...",
    # DDoS-GUARD
    "DDoS-Guard",
]
CHALLENGE_SELECTORS = [
    # Cloudflare
    "#cf-challenge-running",
    ".ray_id",
    ".attack-box",
    "#cf-please-wait",
    "#challenge-spinner",
    "#trk_jschal_js",
    "#turnstile-wrapper",
    ".lds-ring",
    # Custom CloudFlare for EbookParadijs, Film-Paleis, MuziekFabriek and Puur-Hollands
    "td.info #js_info",
    # Fairlane / pararius.com
    "div.vc div.text-box h2",
]
SHORT_TIMEOUT = 1


class SyncSession(BaseSession[WebDriver]):
    """Standard WebDriver session"""

    pass


class SyncSessionsStorage(BaseSessionsStorage[WebDriver]):
    """Synchronous session storage implementation"""

    def create(
        self, session_id: Optional[str] = None, proxy: Optional[dict] = None, force_new: Optional[bool] = False
    ) -> tuple[SyncSession, bool]:
        session_id = session_id or str(uuid1())

        if force_new:
            self.destroy(session_id)

        if self.exists(session_id):
            # Need to cast the session to the correct type
            return cast(tuple[SyncSession, bool], (self.sessions[session_id], False))

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

    def get(self, session_id: str, ttl: Optional[timedelta] = None) -> tuple[SyncSession, bool]:
        session, fresh = self.create(session_id)

        if ttl is not None and not fresh and session.lifetime() > ttl:
            logging.debug(f"Session lifetime expired, recreating (session_id={session_id})")
            session, fresh = self.create(session_id, force_new=True)

        return session, fresh


class SyncService(BaseService[WebDriver]):
    """Synchronous service implementation"""

    def __init__(self):
        super().__init__()
        self.sessions_storage = SyncSessionsStorage()

    def get_shadowed_iframe(self, driver: WebDriver, css_selector: str):
        """Get Shadow DOM iframe element"""
        logging.debug("Getting ShadowRoot by selector: %s", css_selector)
        shadow_element = driver.execute_script(
            """
            return (arguments[0] && document.querySelector(arguments[0])?.shadowRoot?.firstChild) || null;
        """,
            css_selector,
        )
        if shadow_element:
            logging.debug("iframe found")
        else:
            logging.debug("iframe not found")
        return shadow_element

    def click_verify(self, driver: WebDriver):
        """Try to click on Cloudflare verification elements"""
        try:
            logging.debug("Try to find the Cloudflare verify checkbox...")
            iframe = self.get_shadowed_iframe(driver, "div.cf-turnstile-wrapper")
            if iframe:
                logging.debug(f"iframe found ({type(iframe)})")
                logging.debug("iframe source: " + iframe.page_source)
            else:
                logging.debug("iframe not found")

            driver.switch_to.frame(iframe)
            checkbox = driver.find_element(
                by=By.XPATH,
                value="//label/input",
            )
            if checkbox:
                actions = ActionChains(driver)
                actions.move_to_element_with_offset(checkbox, 5, 7)
                actions.click(checkbox)
                actions.perform()
                logging.debug("Cloudflare verify checkbox found and clicked!")
        except Exception as e:
            logging.debug(f"Cloudflare verify checkbox not found on the page. {repr(e)} - {e}")
        finally:
            driver.switch_to.default_content()

        try:
            logging.debug("Try to find the Cloudflare 'Verify you are human' button...")
            button = driver.find_element(
                by=By.XPATH,
                value="//input[@type='button' and @value='Verify you are human']",
            )
            if button:
                actions = ActionChains(driver)
                actions.move_to_element_with_offset(button, 5, 7)
                actions.click(button)
                actions.perform()
                logging.debug("The Cloudflare 'Verify you are human' button found and clicked!")
        except Exception:
            logging.debug("The Cloudflare 'Verify you are human' button not found on the page.")

        time.sleep(2)

    def get_correct_window(self, driver: WebDriver) -> WebDriver:
        """Get the correct window if multiple are open"""
        if len(driver.window_handles) > 1:
            for window_handle in driver.window_handles:
                driver.switch_to.window(window_handle)
                current_url = driver.current_url
                if not current_url.startswith("devtools://devtools"):
                    return driver
        return driver

    def switch_to_new_tab(self, driver: WebDriver, url: str) -> None:
        """Open URL in a new tab and close the original"""
        logging.debug("Opening new tab...")
        driver.execute_script(f"window.open('{url}', 'new tab')")
        time.sleep(4)
        logging.debug("Closing original tab...")
        driver.close()

    def access_page(self, driver: WebDriver, url: str) -> None:
        """Access a page with Cloudflare bypass technique"""
        driver.get(url)
        driver.start_session()
        driver.start_session()  # required to bypass Cloudflare

    def _post_request(self, req: V1RequestBase, driver: WebDriver):
        """Handle POST requests by creating a form and submitting it"""
        post_form = f'<form id="hackForm" action="{req.url}" method="POST">'
        query_string = req.post_data if req.post_data[0] != "?" else req.post_data[1:]  # Updated variable name
        pairs = query_string.split("&")
        for pair in pairs:
            parts = pair.split("=")
            try:
                name = unquote(parts[0])
            except Exception:
                name = parts[0]
            if name == "submit":
                continue
            try:
                value = unquote(parts[1])
            except Exception:
                value = parts[1]
            post_form += f'<input type="text" name="{name}" value="{value}"><br>'
        post_form += "</form>"
        html_content = f"""
            <!DOCTYPE html>
            <html>
            <body>
                {post_form}
                <script>document.getElementById('hackForm').submit();</script>
            </body>
            </html>"""
        driver.get("data:text/html;charset=utf-8," + html_content)
        driver.start_session()
        driver.start_session()  # required to bypass Cloudflare

    def request_page(self, driver: WebDriver, req: V1RequestBase, method: str) -> None:
        """Request a page using either GET or POST method"""
        if method == "POST":
            self._post_request(req, driver)
        else:
            self.access_page(driver, req.url)

        if utils.get_config_log_html():
            logging.debug(f"Request: {req.url}")
            logging.debug(f"Response HTML: {utils.format_html(driver.page_source)}")

    def test_browser_installation(self):
        logging.info("Testing web browser installation...")
        logging.info("Platform: " + platform.platform())

        chrome_exe_path = utils.get_chrome_exe_path()
        if chrome_exe_path is None:
            logging.error("Chrome / Chromium web browser not installed!")
            sys.exit(1)
        else:
            logging.info("Chrome / Chromium path: " + chrome_exe_path)

        chrome_major_version = utils.get_chrome_major_version()
        if chrome_major_version == "":
            logging.error("Chrome / Chromium version not detected!")
            sys.exit(1)
        else:
            logging.info("Chrome / Chromium major version: " + chrome_major_version)

        logging.info("Launching web browser...")
        user_agent = utils.get_user_agent_uc()
        logging.info("FlareSolverr User-Agent: " + user_agent)
        logging.info("Test successful!")

    def index_endpoint(self) -> IndexResponse:
        res = IndexResponse({})
        res.msg = "FlareSolverr is ready!"
        res.version = utils.get_flaresolverr_version()
        res.userAgent = utils.get_user_agent_uc()
        return res

    def health_endpoint(self) -> HealthResponse:
        res = HealthResponse({})
        res.status = STATUS_OK
        return res

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
        logging.debug(f"Response => POST /v1 body: {utils.object_to_dict(res)}")
        logging.info(f"Response in {(res.endTimestamp - res.startTimestamp) / 1000} s")
        return res

    def _controller_v1_handler(self, req: V1RequestBase) -> V1ResponseBase:
        # do some validations
        if req.cmd is None:
            raise Exception("Request parameter 'cmd' is mandatory.")
        if req.headers is not None:
            logging.warning("Request parameter 'headers' was removed in FlareSolverr v2.")
        if req.userAgent is not None:
            logging.warning("Request parameter 'userAgent' was removed in FlareSolverr v2.")

        # set default values
        if req.maxTimeout is None or req.maxTimeout < 1:
            req.maxTimeout = 60000

        # execute the command
        res: V1ResponseBase
        if req.cmd == "sessions.create":
            res = self._cmd_sessions_create(req)
        elif req.cmd == "sessions.list":
            res = self._cmd_sessions_list(req)
        elif req.cmd == "sessions.destroy":
            res = self._cmd_sessions_destroy(req)
        elif req.cmd == "request.get":
            res = self._cmd_request_get(req)
        elif req.cmd == "request.post":
            res = self._cmd_request_post(req)
        else:
            raise Exception(f"Request parameter 'cmd' = '{req.cmd}' is invalid.")

        return res

    def _cmd_request_get(self, req: V1RequestBase) -> V1ResponseBase:
        # do some validations
        if req.url is None:
            raise Exception("Request parameter 'url' is mandatory in 'request.get' command.")
        if req.postData is not None:
            raise Exception("Cannot use 'postBody' when sending a GET request.")
        if req.returnRawHtml is not None:
            logging.warning("Request parameter 'returnRawHtml' was removed in FlareSolverr v2.")
        if req.download is not None:
            logging.warning("Request parameter 'download' was removed in FlareSolverr v2.")

        challenge_res = self._resolve_challenge(req, "GET")
        res = V1ResponseBase({})
        res.status = challenge_res.status
        res.message = challenge_res.message
        res.solution = challenge_res.result
        return res

    def _cmd_request_post(self, req: V1RequestBase) -> V1ResponseBase:
        # do some validations
        if req.postData is None:
            raise Exception("Request parameter 'postData' is mandatory in 'request.post' command.")
        if req.returnRawHtml is not None:
            logging.warning("Request parameter 'returnRawHtml' was removed in FlareSolverr v2.")
        if req.download is not None:
            logging.warning("Request parameter 'download' was removed in FlareSolverr v2.")

        challenge_res = self._resolve_challenge(req, "POST")
        res = V1ResponseBase({})
        res.status = challenge_res.status
        res.message = challenge_res.message
        res.solution = challenge_res.result
        return res

    def _cmd_sessions_create(self, req: V1RequestBase) -> V1ResponseBase:
        logging.debug("Creating new session...")

        session, fresh = self.sessions_storage.create(session_id=req.session, proxy=req.proxy)
        session_id = session.session_id

        if not fresh:
            return V1ResponseBase({"status": STATUS_OK, "message": "Session already exists.", "session": session_id})

        return V1ResponseBase({"status": STATUS_OK, "message": "Session created successfully.", "session": session_id})

    def _cmd_sessions_list(self, req: V1RequestBase) -> V1ResponseBase:
        session_ids = self.sessions_storage.session_ids()

        return V1ResponseBase({"status": STATUS_OK, "message": "", "sessions": session_ids})

    def _cmd_sessions_destroy(self, req: V1RequestBase) -> V1ResponseBase:
        session_id = req.session
        existed = self.sessions_storage.destroy(session_id)

        if not existed:
            raise Exception("The session doesn't exist.")

        return V1ResponseBase({"status": STATUS_OK, "message": "The session has been removed."})

    def _resolve_challenge(self, req: V1RequestBase, method: str) -> ChallengeResolutionT:
        timeout = req.max_timeout / 1000 if req.max_timeout else 60
        driver = None
        try:
            if req.session:
                session_id = req.session
                ttl = timedelta(minutes=req.session_ttl_minutes) if req.session_ttl_minutes else None
                session, fresh = self.sessions_storage.get(session_id, ttl)

                if fresh:
                    logging.debug(f"new session created to perform the request (session_id={session_id})")
                else:
                    logging.debug(
                        f"existing session is used to perform the request (session_id={session_id}, "
                        f"lifetime={str(session.lifetime())}, ttl={str(ttl)})"
                    )

                driver = session.driver
            else:
                driver = utils.get_webdriver_uc(req.proxy)
                logging.debug("New instance of webdriver has been created to perform the request")

            self._init_driver(driver)

            return func_timeout(timeout, self._evil_logic, (req, driver, method))
        except FunctionTimedOut as e:
            raise Exception(f"Error solving the challenge. Timeout after {timeout} seconds.") from e
        except Exception as e:
            raise Exception("Error solving the challenge. " + str(e).replace("\n", "\\n")) from e
        finally:
            if not req.session and driver is not None:
                if utils.get_current_platform() == "nt":
                    driver.close()
                driver.quit()
                logging.debug("A used instance of webdriver has been destroyed")

    def _init_driver(self, driver):
        try:
            driver.execute_cdp_cmd("Page.enable", {})
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
            Element.prototype._as = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function (params) {
            return this._as({mode: "open"})
            };
        """
                },
            )
        except Exception as e:
            logging.debug("Driver init exception: %s", repr(e))

    def _evil_logic(self, req: V1RequestBase, driver: WebDriver, method: str) -> ChallengeResolutionT:
        """Core logic for solving Cloudflare challenges"""
        res = ChallengeResolutionT({})
        res.status = STATUS_OK
        res.message = ""

        # navigate to the page
        logging.debug(f"Navigating to... {req.url}")
        self.request_page(driver, req, method)
        driver = self.get_correct_window(driver)

        # set cookies if required
        if req.cookies is not None and len(req.cookies) > 0:
            logging.debug("Setting cookies...")
            for cookie in req.cookies:
                driver.delete_cookie(cookie["name"])
                driver.add_cookie(cookie)
            # reload the page
            self.request_page(driver, req, method)
            driver = self.get_correct_window(driver)

        # wait for the page
        html_element = driver.find_element(By.TAG_NAME, "html")
        page_title = driver.title

        # find access denied titles
        for title in ACCESS_DENIED_TITLES:
            if title == page_title:
                raise Exception(
                    "Cloudflare has blocked this request. "
                    "Probably your IP is banned for this site, check in your web browser."
                )
        # find access denied selectors
        for selector in ACCESS_DENIED_SELECTORS:
            found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(found_elements) > 0:
                raise Exception(
                    "Cloudflare has blocked this request. "
                    "Probably your IP is banned for this site, check in your web browser."
                )

        # find challenge by title
        challenge_found = False
        for title in CHALLENGE_TITLES:
            if title.lower() == page_title.lower():
                challenge_found = True
                logging.info("Challenge detected. Title found: " + page_title)
                break
        if not challenge_found:
            # find challenge by selectors
            for selector in CHALLENGE_SELECTORS:
                found_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if len(found_elements) > 0:
                    challenge_found = True
                    logging.info("Challenge detected. Selector found: " + selector)
                    break

        attempt = 0
        if challenge_found:
            while True:
                try:
                    attempt = attempt + 1

                    if attempt == 4:
                        self.switch_to_new_tab(driver, req.url)
                        driver = self.get_correct_window(driver)
                        time.sleep(4)

                    # wait until the title changes
                    for title in CHALLENGE_TITLES:
                        logging.debug("Waiting for title (attempt " + str(attempt) + "): " + title)
                        WebDriverWait(driver, SHORT_TIMEOUT).until_not(title_is(title))

                    # then wait until all the selectors disappear
                    for selector in CHALLENGE_SELECTORS:
                        logging.debug("Waiting for selector (attempt " + str(attempt) + "): " + selector)
                        WebDriverWait(driver, SHORT_TIMEOUT).until_not(
                            presence_of_element_located((By.CSS_SELECTOR, selector))
                        )

                    # all elements not found
                    break

                except TimeoutException:
                    logging.debug("Timeout waiting for selector")

                    self.click_verify(driver)

                    # update the html (cloudflare reloads the page every 5 s)
                    html_element = driver.find_element(By.TAG_NAME, "html")

            # waits until cloudflare redirection ends
            logging.debug("Waiting for redirect")
            try:
                WebDriverWait(driver, SHORT_TIMEOUT).until(staleness_of(html_element))
            except Exception:
                logging.debug("Timeout waiting for redirect")

            logging.info("Challenge solved!")
            res.message = "Challenge solved!"
        else:
            logging.info("Challenge not detected!")
            res.message = "Challenge not detected!"

        challenge_res = ChallengeResolutionResultT({})
        challenge_res.url = driver.current_url
        challenge_res.status = 200  # todo: fix, selenium not provides this info
        challenge_res.cookies = driver.get_cookies()
        challenge_res.user_agent = utils.get_user_agent_uc(driver)  # Updated variable name

        if not req.return_only_cookies:  # Updated variable name
            challenge_res.headers = {}  # todo: fix, selenium not provides this info
            challenge_res.response = driver.page_source

        res.result = challenge_res
        return res
