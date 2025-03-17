import asyncio
import logging
import platform
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, cast
from urllib.parse import unquote, urlparse
from uuid import uuid1

from nodriver import Browser, Tab

import utils
from abstract_base import BaseService, BaseSession, BaseSessionsStorage
from dtos import (
    STATUS_OK,
    STATUS_ERROR,
    V1RequestBase,
    V1ResponseBase,
    ChallengeResolutionT,
    IndexResponse,
    HealthResponse, ChallengeResolutionResultT
)

# Constants from flaresolverr_service_nd.py
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
    ".loading-spinner",
    ".main-wrapper",
    # Custom CloudFlare for EbookParadijs, Film-Paleis, MuziekFabriek and Puur-Hollands
    "td.info #js_info",
    # Fairlane / pararius.com
    "div.vc div.text-box h2",
]
STATUS_CODE = 200  # Always return 200 until I can catch the proper return code
SHORT_TIMEOUT = 2

class AsyncSession(BaseSession[Browser]):
    """Nodriver Browser session"""
    pass

class AsyncSessionsStorage(BaseSessionsStorage[Browser]):
    """Asynchronous session storage implementation"""

    async def create(self, session_id: Optional[str] = None, proxy: Optional[dict] = None,
                     force_new: Optional[bool] = False) -> Tuple[AsyncSession, bool]:
        session_id = session_id or str(uuid1())

        if force_new:
            await self.destroy(session_id)

        if self.exists(session_id):
            # Need to cast the session to the correct type
            return cast(Tuple[AsyncSession, bool], (self.sessions[session_id], False))

        driver = await utils.get_webdriver_nd(proxy)
        session = AsyncSession(session_id, driver, datetime.now())
        self.sessions[session_id] = session

        return session, True

    async def destroy(self, session_id: str) -> bool:
        if not self.exists(session_id):
            return False

        session = self.sessions.pop(session_id)
        await utils.after_run_cleanup(driver=session.driver)
        return True

    async def get(self, session_id: str, ttl: Optional[timedelta] = None) -> Tuple[AsyncSession, bool]:
        session, fresh = await self.create(session_id)

        if ttl is not None and not fresh and session.lifetime() > ttl:
            logging.debug(f'Session lifetime expired, recreating (session_id={session_id})')
            session, fresh = await self.create(session_id, force_new=True)

        return session, fresh

class AsyncService(BaseService[Browser]):
    """Asynchronous service implementation"""

    def __init__(self):
        super().__init__()
        self.sessions_storage = AsyncSessionsStorage()

    async def get_status_code(self, event):
        """Monitor network request status code"""
        global STATUS_CODE
        STATUS_CODE = event

    async def click_verify_nd(self, tab: Tab):
        """Try to click on Cloudflare verification elements for nodriver"""
        try:
            logging.debug("Checking if cloudflare captcha is present on page...")
            await tab.wait(2)
            await tab
            cf_element = await tab.find(text="cf-chl-widget-", timeout=SHORT_TIMEOUT)

            if cf_element:
                logging.debug("Cloudflare captcha found!")

                # update targets before looking for the iframe
                # nodriver list it in LOG_LEVEL debug but not in info
                await tab.browser.update_targets()
                # get the iframe target
                cf_tab = next(
                    (
                        target
                        for target in tab.browser.targets
                        if "challenges.cloudflare.com" in target.url
                    ),
                    None,
                )
                if cf_tab is None:
                    raise ValueError("Captcha iframe not found!")

                # Fix iframe being denied access by websocket
                cf_tab.websocket_url = cf_tab.websocket_url.replace("iframe", "page")

                logging.debug("Found captcha iframe!")

                # get checkbox from iframe
                cf_checkbox = await cf_tab.find(text="checkbox", timeout=SHORT_TIMEOUT)

                await cf_checkbox.mouse_click()
                logging.debug("Checkbox element clicked!")
        except Exception as e:
            logging.debug(f"Cloudflare element not found on the page - {str(e)}")

        await asyncio.sleep(2)

    async def _post_request_nd(self, req: V1RequestBase) -> str:
        """Create HTML content for POST request submission"""
        post_form = f'<form id="hackForm" action="{req.url}" method="POST">'
        query_string = req.postData if req.postData[0] != "?" else req.postData[1:]
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

        return html_content

    async def test_browser_installation(self):
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
        user_agent = await utils.get_user_agent_nd()
        logging.info("FlareSolverr User-Agent: " + user_agent)
        logging.info("Test successful!")

    async def index_endpoint(self) -> IndexResponse:
        res = IndexResponse({})
        res.msg = "FlareSolverr is ready!"
        res.version = utils.get_flaresolverr_version()
        res.userAgent = await utils.get_user_agent_nd()
        return res

    async def health_endpoint(self) -> HealthResponse:
        res = HealthResponse({})
        res.status = STATUS_OK
        return res

    async def controller_v1_endpoint(self, req: V1RequestBase) -> V1ResponseBase:
        start_ts = int(time.time() * 1000)
        logging.info(f"Incoming request => POST /v1 body: {utils.object_to_dict(req)}")
        res: V1ResponseBase
        try:
            res = await self._controller_v1_handler(req)
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

    async def _controller_v1_handler(self, req: V1RequestBase) -> V1ResponseBase:
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
            res = await self._cmd_sessions_create(req)
        elif req.cmd == "sessions.list":
            res = self._cmd_sessions_list(req)
        elif req.cmd == "sessions.destroy":
            res = await self._cmd_sessions_destroy(req)
        elif req.cmd == "request.get":
            res = await self._cmd_request_get(req)
        elif req.cmd == "request.post":
            res = await self._cmd_request_post(req)
        else:
            raise Exception(f"Request parameter 'cmd' = '{req.cmd}' is invalid.")

        return res

    async def _cmd_request_get(self, req: V1RequestBase) -> V1ResponseBase:
        # do some validations
        if req.url is None:
            raise Exception(
                "Request parameter 'url' is mandatory in 'request.get' command."
            )
        if req.postData is not None:
            raise Exception("Cannot use 'postBody' when sending a GET request.")
        if req.returnRawHtml is not None:
            logging.warning(
                "Request parameter 'returnRawHtml' was removed in FlareSolverr v2."
            )
        if req.download is not None:
            logging.warning("Request parameter 'download' was removed in FlareSolverr v2.")

        challenge_res = await self._resolve_challenge(req, "GET")
        res = V1ResponseBase({})
        res.status = challenge_res.status
        res.message = challenge_res.message
        res.solution = challenge_res.result
        return res

    async def _cmd_request_post(self, req: V1RequestBase) -> V1ResponseBase:
        # do some validations
        if req.postData is None:
            raise Exception(
                "Request parameter 'postData' is mandatory in 'request.post' command."
            )
        if req.returnRawHtml is not None:
            logging.warning(
                "Request parameter 'returnRawHtml' was removed in FlareSolverr v2."
            )
        if req.download is not None:
            logging.warning("Request parameter 'download' was removed in FlareSolverr v2.")

        challenge_res = await self._resolve_challenge(req, "POST")
        res = V1ResponseBase({})
        res.status = challenge_res.status
        res.message = challenge_res.message
        res.solution = challenge_res.result
        return res

    async def _cmd_sessions_create(self, req: V1RequestBase) -> V1ResponseBase:
        logging.debug("Creating new session...")

        session, fresh = await self.sessions_storage.create(
            session_id=req.session, proxy=req.proxy
        )
        session_id = session.session_id

        if not fresh:
            return V1ResponseBase(
                {
                    "status": STATUS_OK,
                    "message": "Session already exists.",
                    "session": session_id,
                }
            )

        return V1ResponseBase(
            {
                "status": STATUS_OK,
                "message": "Session created successfully.",
                "session": session_id,
            }
        )

    def _cmd_sessions_list(self, req: V1RequestBase) -> V1ResponseBase:
        session_ids = self.sessions_storage.session_ids()

        return V1ResponseBase({"status": STATUS_OK, "message": "", "sessions": session_ids})

    async def _cmd_sessions_destroy(self, req: V1RequestBase) -> V1ResponseBase:
        session_id = req.session
        existed = await self.sessions_storage.destroy(session_id)

        if not existed:
            raise Exception("The session doesn't exist.")

        return V1ResponseBase(
            {"status": STATUS_OK, "message": "The session has been removed."}
        )

    async def _resolve_challenge(self, req: V1RequestBase, method: str) -> ChallengeResolutionT:
        timeout = req.maxTimeout / 1000
        driver = None
        try:
            if req.session:
                session_id = req.session
                ttl = (
                    timedelta(minutes=req.session_ttl_minutes)
                    if req.session_ttl_minutes
                    else None
                )
                session, fresh = await self.sessions_storage.get(session_id, ttl)

                if fresh:
                    logging.debug(
                        f"new session created to perform the request (session_id={session_id})"
                    )
                else:
                    logging.debug(
                        f"existing session is used to perform the request (session_id={session_id}, "
                        f"lifetime={str(session.lifetime())}, ttl={str(ttl)})"
                    )

                driver = session.driver
            else:
                driver = await utils.get_webdriver_nd(req.proxy)
                logging.debug(
                    "New instance of chromium has been created to perform the request"
                )
            return await asyncio.wait_for(
                self._evil_logic(req, driver, method), timeout=timeout
            )
        except asyncio.TimeoutError:
            raise Exception(
                f"Error solving the challenge. Timeout after {timeout} seconds."
            )
        except Exception as e:
            raise Exception("Error solving the challenge. " + str(e).replace("\n", "\\n"))
        finally:
            if not req.session and driver is not None:
                await utils.after_run_cleanup(driver=driver)
                logging.debug("A used instance of chromium has been destroyed")

    async def _evil_logic(self, req: V1RequestBase, driver: Browser, method: str) -> ChallengeResolutionT:
        """Core logic for solving Cloudflare challenges with nodriver"""
        res = ChallengeResolutionT({})
        res.status = STATUS_OK
        res.message = ""

        # navigate to the page
        logging.debug(f"Navigating to... {req.url}")
        if method == "POST":
            post_content = await self._post_request_nd(req)
            tab = await driver.get("data:text/html;charset=utf-8," + post_content)
        else:
            tab = await driver.get(req.url)

        # Insert cookies in Browser if set
        if req.cookies is not None and len(req.cookies) > 0:
            await tab.wait(1)
            await tab
            logging.debug(f"Setting cookies...")

            # Get cleaned domain
            domain = (urlparse(req.url).netloc).split(".")
            domain = ".".join(domain[-2:])

            # Delete all cookies
            logging.debug("Removing all Browser cookies...")
            await driver.cookies.clear()

            cookies = []
            for cookie in req.cookies:
                if domain not in cookie["domain"]:
                    logging.debug(f"Skipping cookie from domain {cookie['domain']}")
                    continue
                logging.debug(
                    f"Appending cookie '{cookie['name']}' for '{cookie['domain']}'..."
                )
                cookies.append(
                    utils.nd.cdp.network.CookieParam(
                        name=cookie["name"],
                        value=cookie["value"],
                        path=cookie["path"],
                        domain=cookie["domain"],
                    )
                )

            await driver.cookies.set_all(cookies)

            # reload the page
            if method == "POST":
                tab = await driver.get(post_content)
            else:
                logging.debug("Reloading tab...")
                await tab.reload()

        # wait for the page and make sure it catches the load event
        await tab.wait(1)
        await tab

        # get current page nodes
        doc = await tab.send(utils.nd.cdp.dom.get_document(-1, True))

        if utils.get_config_log_html():
            logging.debug(f"Response HTML:\n{utils.format_html(await tab.get_content(_node=doc))}")
        page_title = tab.target.title

        # find access denied titles
        for title in ACCESS_DENIED_TITLES:
            if title == page_title:
                raise Exception(
                    "Cloudflare has blocked this request. "
                    "Probably your IP is banned for this site, check in your web browser."
                )
        # find access denied selectors
        for selector in ACCESS_DENIED_SELECTORS:
            found_elements = await tab.query_selector(selector=selector, _node=doc)
            if found_elements is not None:
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
                found_elements = await tab.query_selector(selector=selector, _node=doc)
                if found_elements is not None:
                    challenge_found = True
                    logging.info("Challenge detected. Selector found: " + selector)
                    break

        attempt = 0
        if challenge_found:
            while True:
                try:
                    attempt = attempt + 1
                    await tab.wait(1)

                    # wait until the title changes
                    for title in CHALLENGE_TITLES:
                        logging.debug(f"Waiting for title (attempt {attempt}): {title} [Current title: {tab.target.title}]")
                        if tab.target.title != title:
                            logging.debug(" * nope")
                            continue
                        start_time = time.time()
                        while True:
                            current_title = tab.target.title
                            logging.debug(f" * current title: {current_title}")
                            if current_title not in CHALLENGE_TITLES:
                                logging.debug(" * nope2")
                                break
                            if time.time() - start_time > SHORT_TIMEOUT:
                                logging.debug(" * timeout")
                                raise TimeoutError
                            logging.debug(" * still same title")
                            await tab.wait(0.1)

                    # then wait until all the selectors disappear
                    logging.debug("Waiting for CHALLENGE_SELECTORS")
                    for selector in CHALLENGE_SELECTORS:
                        logging.debug("Waiting for tab")
                        await tab
                        logging.debug(f"Waiting for selector (attempt {attempt}): {selector}")
                        if (
                                await tab.query_selector(selector=selector, _node=doc)
                                is not None
                        ):
                            logging.debug(" * found selector")
                            start_time = time.time()
                            while True:
                                element = await tab.query_selector(
                                    selector=selector, _node=doc
                                )
                                logging.debug(" * finised querying (again)")
                                if not element:
                                    logging.debug(" * ok next")
                                    break
                                if time.time() - start_time > SHORT_TIMEOUT:
                                    logging.debug(" * timeout reached")
                                    raise TimeoutError
                                logging.debug(" * deleting element")
                                del element
                                logging.debug(" * sleeping")
                                await asyncio.sleep(0.1)

                        logging.debug("Next selector")

                    logging.debug("All elements gone")
                    # all elements not found
                    break

                except TimeoutError:
                    logging.debug("Timeout waiting for selector")

                    await self.click_verify_nd(tab)

            # waits until cloudflare redirection ends
            logging.debug("Waiting for redirect")
            try:
                await tab
            except Exception:
                logging.debug("Timeout waiting for redirect")

            logging.info("Challenge solved!")
            res.message = "Challenge solved!"
        else:
            logging.info("Challenge not detected!")
            res.message = "Challenge not detected!"

        challenge_res = ChallengeResolutionResultT({})
        challenge_res.url = tab.target.url
        challenge_res.status = STATUS_CODE
        logging.debug("requesting cookies from the driver")
        challenge_res.cookies = await driver.cookies.get_all(requests_cookie_format=True)
        logging.debug("requesting user agent from the driver")
        challenge_res.userAgent = await utils.get_user_agent_nd(driver)

        if not req.returnOnlyCookies:
            challenge_res.headers = {}  # nodriver should support this in the future
            logging.debug("requesting html content from the tab")
            challenge_res.response = await tab.get_content(_node=doc)

        # Close websocket connection to reuse the driver tab
        if req.session:
            logging.debug("tab.aclose()")
            await tab.aclose()
        else:
            logging.debug("tab.close()")
            await tab.close()
        logging.debug("Tab was closed")

        res.result = challenge_res
        return res