import asyncio
import json
import os
import platform as plt
import pprint
import re
import shutil
import tempfile
import time
import urllib.parse
from functools import lru_cache
from typing import Optional

import psutil
from bs4 import BeautifulSoup
from loguru import logger
from selenium.webdriver.chrome.webdriver import WebDriver

import nodriver as nd
import undetected_chromedriver as uc
from src.dtos import Request, Response


@lru_cache(1)
def is_arm_arch() -> bool:
    """Check if we're running on ARM architecture"""
    return plt.machine().startswith(("arm", "aarch"))


@lru_cache(1)
def get_config_log_html() -> bool:
    """Get LOG_HTML environment variable as boolean"""
    return os.environ.get("LOG_HTML", "false").lower() == "true"


@lru_cache(1)
def get_config_headless() -> bool:
    """Get HEADLESS environment variable as boolean"""
    return os.environ.get("HEADLESS", "true").lower() == "true"


@lru_cache(1)
def get_flaresolverr_version() -> str:
    """Get FlareSolverr version from package.json"""
    package_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "package.json")
    if not os.path.isfile(package_path):
        package_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "package.json")
    with open(package_path) as f:
        return json.loads(f.read())["version"]


@lru_cache(1)
def get_driver_selection() -> str:
    """Get DRIVER environment variable, defaulting to nodriver"""
    return os.environ.get("DRIVER", "nodriver")


@lru_cache(1)
def get_cloudflare_extension_dir() -> str:
    """Create and return Chrome extension for CloudFlare challenge handling"""
    manifest_json = """
    {
        "manifest_version": 3,
        "name": "Turnstile Patcher",
        "version": "2.1",
        "content_scripts": [
            {
                "js": [
                    "./script.js"
                ],
                "matches": [
                    "<all_urls>"
                ],
                "run_at": "document_start",
                "all_frames": true,
                "world": "MAIN"
            }
        ]
    }
    """

    script_js = """
    Object.defineProperty(MouseEvent.prototype, 'screenX', {
        get: function () {
            return this.clientX + window.screenX;
        }
    });

    Object.defineProperty(MouseEvent.prototype, 'screenY', {
        get: function () {
            return this.clientY + window.screenY;
        }
    });
    """

    extension_dir = tempfile.mkdtemp()
    logger.debug(f"Created CloudFlare extension directory: {extension_dir}")

    with open(os.path.join(extension_dir, "manifest.json"), "w") as f:
        f.write(manifest_json)

    with open(os.path.join(extension_dir, "script.js"), "w") as f:
        f.write(script_js)

    return extension_dir


def create_proxy_extension(proxy: dict) -> str:
    """Create a Chrome extension for proxy authentication"""
    parsed_url = urllib.parse.urlparse(proxy["url"])
    scheme = parsed_url.scheme
    host = parsed_url.hostname
    port = parsed_url.port
    username = proxy["username"]
    password = proxy["password"]

    logger.debug(f"Creating proxy extension for {scheme}://{host}:{port}")

    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {"scripts": ["background.js"]},
        "minimum_chrome_version": "76.0.0"
    }
    """

    background_js = f"""
    var config = {{
        mode: "fixed_servers",
        rules: {{
            singleProxy: {{
                scheme: "{scheme}",
                host: "{host}",
                port: {port}
            }},
            bypassList: ["localhost"]
        }}
    }};

    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

    function callbackFn(details) {{
        return {{
            authCredentials: {{
                username: "{username}",
                password: "{password}"
            }}
        }};
    }}

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {{ urls: ["<all_urls>"] }},
        ['blocking']
    );
    """

    proxy_extension_dir = tempfile.mkdtemp()
    logger.debug(f"Created proxy extension directory: {proxy_extension_dir}")

    with open(os.path.join(proxy_extension_dir, "manifest.json"), "w") as f:
        f.write(manifest_json)

    with open(os.path.join(proxy_extension_dir, "background.js"), "w") as f:
        f.write(background_js)

    return proxy_extension_dir


@lru_cache(1)
def get_chrome_exe_path() -> str:
    """Get the Chrome/Chromium executable path"""
    # Check different possible locations
    logger.debug("Searching for Chrome executable...")

    # Linux pyinstaller bundle
    chrome_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome", "chrome")
    if os.path.exists(chrome_path):
        logger.debug(f"Found Chrome at bundle path: {chrome_path}")
        if not os.access(chrome_path, os.X_OK):
            logger.error(f"Chrome binary '{chrome_path}' is not executable")
            raise Exception(
                f'Chrome binary "{chrome_path}" is not executable. '
                f'Please, extract the archive with "tar xzf <file.tar.gz>".'
            )
        return chrome_path

    # Windows pyinstaller bundle
    chrome_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome", "chrome.exe")
    if os.path.exists(chrome_path):
        logger.debug(f"Found Chrome at Windows bundle path: {chrome_path}")
        return chrome_path

    # System installation
    try:
        path = uc.find_chrome_executable()
        logger.debug(f"Found system Chrome at: {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to find Chrome executable: {e}")
        raise


@lru_cache(1)
def get_chrome_major_version() -> str:
    """Get Chrome/Chromium major version"""
    logger.debug("Detecting Chrome version...")

    if os.name == "nt":
        # Windows version detection
        try:
            complete_version = extract_version_nt_executable(get_chrome_exe_path())
            logger.debug(f"Detected Chrome version from executable: {complete_version}")
        except Exception as e:
            logger.debug(f"Failed to get version from executable: {e}")
            try:
                complete_version = extract_version_nt_registry()
                logger.debug(f"Detected Chrome version from registry: {complete_version}")
            except Exception as e:
                logger.debug(f"Failed to get version from registry: {e}")
                complete_version = extract_version_nt_folder()
                logger.debug(f"Detected Chrome version from folder: {complete_version}")
    else:
        # Linux/macOS version detection
        chrome_path = get_chrome_exe_path()
        logger.debug(f"Running '{chrome_path} --version' to detect version")
        process = os.popen(f'"{chrome_path}" --version')
        complete_version = process.read()
        process.close()
        logger.debug(f"Chrome version output: {complete_version}")

    try:
        major_version = complete_version.split(".")[0].split(" ")[-1]
        logger.info(f"Detected Chrome major version: {major_version}")
        return major_version
    except Exception as e:
        logger.error(f"Failed to parse Chrome version: {e}")
        return ""


def extract_version_nt_executable(exe_path: str) -> str:
    """Extract Chrome version from Windows executable"""
    import pefile

    pe = pefile.PE(exe_path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    return pe.FileInfo[0][0].StringTable[0].entries[b"FileVersion"].decode("utf-8")


def extract_version_nt_registry() -> str:
    """Extract Chrome version from Windows registry"""
    registry_output = os.popen(
        'reg query "HKLM\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Google Chrome"'
    ).read()
    version_start = registry_output.find("DisplayVersion    REG_SZ") + 24
    version_end = registry_output.find("\n", version_start)
    return registry_output[version_start:version_end].strip()


def extract_version_nt_folder() -> str:
    """Extract Chrome version from Windows Program Files folder"""
    # Check if the Chrome folder exists in the x32 or x64 Program Files folders
    for i in range(2):
        path = "C:\\Program Files" + (" (x86)" if i else "") + "\\Google\\Chrome\\Application"
        if os.path.isdir(path):
            paths = [f.path for f in os.scandir(path) if f.is_dir()]
            for path in paths:
                filename = os.path.basename(path)
                pattern = r"\d+\.\d+\.\d+\.\d+"
                match = re.search(pattern, filename)
                if match and match.group():
                    # Found a Chrome version
                    return match.group(0)
    return ""


# User-Agent cache
_user_agent_cache = None


def _get_user_agent_cached() -> Optional[str]:
    """Get cached user agent if available"""
    global _user_agent_cache
    return _user_agent_cache


def _set_user_agent_cached(user_agent: str) -> None:
    """Cache user agent value"""
    global _user_agent_cache
    # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
    _user_agent_cache = re.sub("HEADLESS", "", user_agent, flags=re.IGNORECASE)
    logger.info(f"Stored User-Agent: {_user_agent_cache}")


async def get_user_agent_nd(driver=None) -> str | None:
    """Get User-Agent string from nodriver browser"""
    cached = _get_user_agent_cached()
    if cached:
        return cached

    temp_driver = None
    try:
        if driver is None:
            logger.info("Creating temporary browser to get User-Agent...")
            temp_driver = await get_webdriver_nd()
            driver = temp_driver

        user_agent = driver.info["User-Agent"]
        _set_user_agent_cached(user_agent)
        return _get_user_agent_cached()
    except Exception as e:
        logger.error(f"Error getting browser User-Agent: {e}")
        raise Exception(f"Error getting browser User-Agent: {e}") from e
    finally:
        if temp_driver is not None:
            await after_run_cleanup(driver=temp_driver)
            logger.debug("Cleaned up temporary browser")


def get_user_agent_uc(driver=None) -> str | None:
    """Get User-Agent string from undetected-chromedriver browser"""
    cached = _get_user_agent_cached()
    if cached:
        return cached

    temp_driver = None
    try:
        if driver is None:
            logger.info("Creating temporary browser to get User-Agent...")
            temp_driver = get_webdriver_uc()
            driver = temp_driver

        user_agent = driver.execute_script("return navigator.user_agent")
        _set_user_agent_cached(user_agent)
        return _get_user_agent_cached()
    except Exception as e:
        logger.error(f"Error getting browser User-Agent: {e}")
        raise Exception(f"Error getting browser User-Agent: {e}") from e
    finally:
        if temp_driver is not None:
            if os.name == "nt":
                temp_driver.close()
            temp_driver.quit()
            logger.debug("Cleaned up temporary browser")


# Patched driver path cache
_patched_driver_path = None


def get_patched_driver_path() -> Optional[str]:
    """Get cached patched driver path if available"""
    global _patched_driver_path
    return _patched_driver_path


def set_patched_driver_path(path: str) -> None:
    """Cache patched driver path"""
    global _patched_driver_path
    _patched_driver_path = path
    logger.debug(f"Stored patched driver path: {_patched_driver_path}")


# Xvfb display instance cache
_xvfb_display = None


def start_xvfb_display():
    """Start virtual X display for headless mode on Linux"""
    global _xvfb_display
    if _xvfb_display is None:
        from xvfbwrapper import Xvfb

        _xvfb_display = Xvfb()
        _xvfb_display.start()
        logger.debug("VIRTUAL SCREEN STARTED")


async def get_webdriver_nd(proxy: dict = None) -> nd.Browser:
    """Get a nodriver browser instance"""
    logger.info("Launching web browser with nodriver...")

    options = nd.Config()
    options.sandbox = False
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--use-gl=swiftshader")

    options.lang = os.environ.get("LANG", "en")

    # Add user agent if we have it cached
    cached_ua = _get_user_agent_cached()
    if cached_ua:
        options.add_argument(f"--user-agent={cached_ua}")
        logger.debug(f"Using cached user agent: {cached_ua}")

    proxy_extension_dir = None
    if proxy and all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = create_proxy_extension(proxy)
        options.add_extension(os.path.abspath(proxy_extension_dir))
        logger.info(f"Using proxy extension for {proxy['url']}")
    elif proxy and "url" in proxy:
        proxy_url = proxy["url"]
        logger.info(f"Using proxy: {proxy_url}")
        options.add_argument(f"--proxy-server={proxy_url}")

    # Add cloudflare extension
    # https://github.com/TheFalloutOf76/CDP-bug-MouseEvent-.screenX-.screenY-patcher
    cloudflare_extension_dir = get_cloudflare_extension_dir()
    options.add_extension(os.path.abspath(cloudflare_extension_dir))
    logger.debug("Added CloudFlare extension")

    # Handle headless mode
    if get_config_headless():
        if os.name == "nt":
            options.windows_headless = True
            logger.debug("Using Windows headless mode")
        else:
            start_xvfb_display()
            logger.debug("Using Xvfb for headless mode")

    # Add browser binary path for Windows
    if os.name == "nt":
        options.browser_executable_path = get_chrome_exe_path()
        logger.debug(f"Using Chrome executable: {options.browser_executable_path}")

    logger.debug(f"Browser options: {pprint.pformat(options.__dict__)}")

    try:
        driver = await nd.Browser.create(config=options)
        logger.info("Browser created successfully")
    except Exception as e:
        logger.error(f"Error creating Chrome Browser: {e}")
        raise

    # Clean up proxy extension directory
    if proxy_extension_dir is not None:
        shutil.rmtree(proxy_extension_dir)
        logger.debug(f"Removed proxy extension directory: {proxy_extension_dir}")

    return driver


def get_webdriver_uc(proxy: dict = None) -> WebDriver:
    """Get an undetected-chromedriver instance"""
    logger.info("Launching web browser with undetected-chromedriver...")

    # undetected_chromedriver options
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-search-engine-choice-screen")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-zygote")

    if is_arm_arch():
        options.add_argument("--disable-gpu-sandbox")
        options.add_argument("--disable-software-rasterizer")
        logger.debug("Added ARM architecture options")

    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--use-gl=swiftshader")

    language = os.environ.get("LANG", "en")
    options.add_argument(f"--accept-lang={language}")
    logger.debug(f"Using language: {language}")

    # Add user agent if we have it cached
    cached_ua = _get_user_agent_cached()
    if cached_ua:
        options.add_argument(f"--user-agent={cached_ua}")
        logger.debug(f"Using cached user agent: {cached_ua}")

    proxy_extension_dir = None
    if proxy and all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = create_proxy_extension(proxy)
        options.add_argument(f"--load-extension={os.path.abspath(proxy_extension_dir)}")
        logger.info(f"Using proxy extension for {proxy['url']}")
    elif proxy and "url" in proxy:
        proxy_url = proxy["url"]
        logger.info(f"Using proxy: {proxy_url}")
        options.add_argument(f"--proxy-server={proxy_url}")

    # Handle headless mode
    windows_headless = False
    if get_config_headless():
        if os.name == "nt":
            windows_headless = True
            logger.debug("Using Windows headless mode")
        else:
            start_xvfb_display()
            logger.debug("Using Xvfb for headless mode")

    options.add_argument("--auto-open-devtools-for-tabs")
    options.add_argument("--disable-popup-blocking")

    # If we are inside the Docker container, we avoid downloading the driver
    driver_exe_path = None
    version_main = None
    if os.path.exists("/app/chromedriver"):
        # Running inside Docker
        driver_exe_path = "/app/chromedriver"
        logger.debug("Using Docker chromedriver path")
    else:
        version_main = get_chrome_major_version()
        patched_path = get_patched_driver_path()
        if patched_path:
            driver_exe_path = patched_path
            logger.debug(f"Using existing patched driver: {driver_exe_path}")

    # Detect chrome path
    browser_executable_path = get_chrome_exe_path()
    logger.debug(f"Using Chrome executable: {browser_executable_path}")

    # Log all options
    all_options = list(options.arguments)
    logger.debug(f"Chrome options: {pprint.pformat(all_options)}")

    # Downloads and patches the chromedriver
    try:
        driver = uc.Chrome(
            options=options,
            browser_executable_path=browser_executable_path,
            driver_executable_path=driver_exe_path,
            version_main=version_main,
            windows_headless=windows_headless,
            headless=get_config_headless(),
        )
        logger.info("Chrome browser created successfully")
    except Exception as e:
        logger.error(f"Error starting Chrome: {e}")
        raise

    # Save the patched driver to avoid re-downloads
    if driver_exe_path is None and hasattr(driver, "patcher"):
        new_path = os.path.join(driver.patcher.data_path, driver.patcher.exe_name)
        if new_path != driver.patcher.executable_path:
            shutil.copy(driver.patcher.executable_path, new_path)
            logger.debug(f"Saved patched driver to: {new_path}")
            set_patched_driver_path(new_path)

    # Clean up proxy extension directory
    if proxy_extension_dir is not None:
        shutil.rmtree(proxy_extension_dir)
        logger.debug(f"Removed proxy extension directory: {proxy_extension_dir}")

    return driver


async def after_run_cleanup(driver: nd.Browser):
    """
    Clean up browser resources after run.

    Args:
        driver: The nodriver Browser instance to clean up
    """
    logger.debug("Performing browser cleanup...")

    # Get Browser instance process
    process = driver.get_process
    if process is None:
        logger.debug("No process to clean up")
        return

    # Get the list of child processes before closing the Browser instance
    child_processes = psutil.Process(process.pid).children(recursive=True)
    logger.debug(f"Found {len(child_processes)} child processes")

    # Stop Browser instance
    driver.stop()
    logger.debug("Browser instance stopped")

    # Wait for the websocket to return True (Closed)
    websocket_wait_start = time.time()
    while True:
        websocket_status = driver.connection.closed
        logger.debug(f"Websocket closed status: {websocket_status}")
        if websocket_status:
            break
        # Timeout after 10 seconds
        if time.time() - websocket_wait_start > 10:
            logger.warning("Timeout waiting for websocket to close")
            break
        await asyncio.sleep(0.1)

    # Find all chromium processes and terminate them if any
    for proc in child_processes:
        try:
            if proc.pid == process.pid:
                logger.debug(f"Terminating Chromium process with PID: {proc.pid}")
                proc.terminate()
            elif any(name in proc.name().lower() for name in ("chromium", "chrome")):
                logger.debug(f"Terminating Chromium child process with PID: {proc.pid}")
                proc.terminate()
            elif proc.status() == "zombie":
                logger.debug(f"Terminating zombie Chromium process with PID: {proc.pid}")
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            message = str(e)
            if "process no longer exists" not in message:
                logger.debug(f"Error terminating process {proc.pid}: {message}")

    # Wait for all processes to terminate
    for proc in child_processes:
        try:
            if proc.pid == process.pid or any(name in proc.name().lower() for name in ("chromium", "chrome")):
                proc.wait(timeout=10)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, psutil.TimeoutExpired) as e:
            message = str(e)
            if "process no longer exists" not in message:
                logger.debug(f"Error waiting for process {proc.pid}: {message}")

    # Delete Browser instance data dir
    try:
        user_dir = driver.config.user_data_dir
        shutil.rmtree(user_dir, ignore_errors=False)
        logger.debug(f"Removed Browser user data directory {user_dir}")
    except OSError as e:
        logger.debug(f"Failed to delete Browser user data directory: {e}")

    # Remove Browser instance from created instances
    try:
        nd.util.get_registered_instances().remove(driver)
        logger.debug("Removed Browser from registered instances")
    except Exception as e:
        logger.debug(f"Error when removing the Browser instance: {e}")


def object_to_dict(_object):
    """Convert object to dictionary, removing hidden fields"""
    json_dict = json.loads(json.dumps(_object, default=lambda o: o.__dict__))
    # Remove hidden fields
    return {k: v for k, v in json_dict.items() if not k.startswith("__")}


def format_html(input_html):
    """Format HTML for logging"""
    # Parse the input HTML string
    soup = BeautifulSoup(input_html, "html.parser")

    # Format the HTML with pretty print
    formatted_html = soup.prettify()

    return (
        f"\n==========================================\n{formatted_html}\n==========================================\n"
    )


def dump(obj: Response | Request) -> None:
    """Dump the response object in debug mode"""
    logger.debug(f"========================================== {obj.__class__.__name__.upper()}")
    for k, v in obj.headers.items():
        logger.debug(f"header: {k}: {pprint.pformat(v, width=200)}")
    logger.debug("---------------------------------------------------")
    for k, v in vars(obj).items():
        if k == "headers":
            continue
        if k == "solution":
            v = {**v, "response": v["response"][:200]}
        logger.debug(f"{k}: {pprint.pformat(v, width=200)}")
    logger.debug(f"========================================== /{obj.__class__.__name__.upper()}")
