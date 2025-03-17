import json
import logging
import os
import re
import shutil
import time
import urllib.parse
import tempfile
import asyncio
import platform as plt
import pprint

from functools import lru_cache
from sysconfig import get_python_version

import psutil
from bs4 import BeautifulSoup

from selenium.webdriver.chrome.webdriver import WebDriver
import undetected_chromedriver as uc
import nodriver as nd

# Global variables - initialized on first use
CHROME_EXE_PATH = None
CHROME_MAJOR_VERSION = None
USER_AGENT = None
XVFB_DISPLAY = None
PATCHED_DRIVER_PATH = None
CLOUDFLARE_EXTENSION_DIR = None
IS_ARMARCH = plt.machine().startswith(('arm', 'aarch'))


@lru_cache(1)
def get_config_log_html() -> bool:
    return os.environ.get("LOG_HTML", "false").lower() == "true"


@lru_cache(1)
def get_config_headless() -> bool:
    return os.environ.get("HEADLESS", "true").lower() == "true"


@lru_cache(1)
def get_flaresolverr_version() -> str:
    package_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "package.json"
    )
    if not os.path.isfile(package_path):
        package_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "package.json"
        )
    with open(package_path) as f:
        return json.loads(f.read())["version"]


@lru_cache(1)
def get_driver_selection() -> str:
    return os.environ.get("DRIVER", "nodriver")


def create_proxy_extension(proxy: dict) -> str:
    """Create a Chrome extension for proxy authentication"""
    parsed_url = urllib.parse.urlparse(proxy["url"])
    scheme = parsed_url.scheme
    host = parsed_url.hostname
    port = parsed_url.port
    username = proxy["username"]
    password = proxy["password"]

    logging.debug(f"Creating proxy extension for {scheme}://{host}:{port}")

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
    logging.debug(f"Created proxy extension directory: {proxy_extension_dir}")

    with open(os.path.join(proxy_extension_dir, "manifest.json"), "w") as f:
        f.write(manifest_json)

    with open(os.path.join(proxy_extension_dir, "background.js"), "w") as f:
        f.write(background_js)

    return proxy_extension_dir


def create_cloudflare_extension() -> str:
    """Create a Chrome extension to handle CloudFlare challenges"""
    global CLOUDFLARE_EXTENSION_DIR
    if CLOUDFLARE_EXTENSION_DIR is not None:
        return CLOUDFLARE_EXTENSION_DIR

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

    CLOUDFLARE_EXTENSION_DIR = tempfile.mkdtemp()
    logging.debug(f"Created CloudFlare extension directory: {CLOUDFLARE_EXTENSION_DIR}")

    with open(os.path.join(CLOUDFLARE_EXTENSION_DIR, "manifest.json"), "w") as f:
        f.write(manifest_json)

    with open(os.path.join(CLOUDFLARE_EXTENSION_DIR, "script.js"), "w") as f:
        f.write(script_js)

    return CLOUDFLARE_EXTENSION_DIR


async def get_webdriver_nd(proxy: dict = None) -> nd.Browser:
    """Get a nodriver browser instance"""
    logging.info("Launching web browser with nodriver...")

    options = nd.Config()
    options.sandbox = False
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--use-gl=swiftshader")

    options.lang = os.environ.get("LANG", 'en')

    # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
    if USER_AGENT is not None:
        options.add_argument("--user-agent=%s" % USER_AGENT)
        logging.debug(f"Using custom user agent: {USER_AGENT}")

    proxy_extension_dir = None
    if proxy and all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = create_proxy_extension(proxy)
        options.add_extension(os.path.abspath(proxy_extension_dir))
        logging.info(f"Using proxy extension for {proxy['url']}")
    elif proxy and "url" in proxy:
        proxy_url = proxy["url"]
        logging.info(f"Using proxy: {proxy_url}")
        options.add_argument("--proxy-server=%s" % proxy_url)

    # Add cloudflare extension
    # https://github.com/TheFalloutOf76/CDP-bug-MouseEvent-.screenX-.screenY-patcher
    cloudflare_extension_dir = create_cloudflare_extension()
    options.add_extension(os.path.abspath(cloudflare_extension_dir))
    logging.debug("Added CloudFlare extension")

    # Handle headless mode
    if get_config_headless():
        if os.name == "nt":
            options.windows_headless = True
            logging.debug("Using Windows headless mode")
        else:
            start_xvfb_display()
            logging.debug("Using Xvfb for headless mode")

    # Add browser binary path for Windows
    if os.name == "nt":
        options.browser_executable_path = get_chrome_exe_path()
        logging.debug(f"Using Chrome executable: {options.browser_executable_path}")

    logging.debug("Browser options: " + pprint.pformat(options.__dict__))

    try:
        driver = await nd.Browser.create(config=options)
        logging.info("Browser created successfully")
    except Exception as e:
        logging.error(f"Error creating Chrome Browser: {e}")
        raise

    # Clean up proxy extension directory
    if proxy_extension_dir is not None:
        shutil.rmtree(proxy_extension_dir)
        logging.debug(f"Removed proxy extension directory: {proxy_extension_dir}")

    return driver


def get_webdriver_uc(proxy: dict = None) -> WebDriver:
    """Get an undetected-chromedriver instance"""
    global PATCHED_DRIVER_PATH, USER_AGENT

    logging.info("Launching web browser with undetected-chromedriver...")

    # undetected_chromedriver options
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument('--disable-search-engine-choice-screen')
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-zygote")

    if IS_ARMARCH:
        options.add_argument('--disable-gpu-sandbox')
        options.add_argument('--disable-software-rasterizer')
        logging.debug("Added ARM architecture options")

    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--use-gl=swiftshader")

    language = os.environ.get("LANG", 'en')
    options.add_argument("--accept-lang=%s" % language)
    logging.debug(f"Using language: {language}")

    # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
    if USER_AGENT is not None:
        options.add_argument("--user-agent=%s" % USER_AGENT)
        logging.debug(f"Using custom user agent: {USER_AGENT}")

    proxy_extension_dir = None
    if proxy and all(key in proxy for key in ["url", "username", "password"]):
        proxy_extension_dir = create_proxy_extension(proxy)
        options.add_argument(
            "--load-extension=%s" % os.path.abspath(proxy_extension_dir)
        )
        logging.info(f"Using proxy extension for {proxy['url']}")
    elif proxy and "url" in proxy:
        proxy_url = proxy["url"]
        logging.info(f"Using proxy: {proxy_url}")
        options.add_argument("--proxy-server=%s" % proxy_url)

    # Handle headless mode
    windows_headless = False
    if get_config_headless():
        if os.name == "nt":
            windows_headless = True
            logging.debug("Using Windows headless mode")
        else:
            start_xvfb_display()
            logging.debug("Using Xvfb for headless mode")

    options.add_argument("--auto-open-devtools-for-tabs")
    options.add_argument("--disable-popup-blocking")

    # If we are inside the Docker container, we avoid downloading the driver
    driver_exe_path = None
    version_main = None
    if os.path.exists("/app/chromedriver"):
        # Running inside Docker
        driver_exe_path = "/app/chromedriver"
        logging.debug("Using Docker chromedriver path")
    else:
        version_main = get_chrome_major_version()
        if PATCHED_DRIVER_PATH is not None:
            driver_exe_path = PATCHED_DRIVER_PATH
            logging.debug(f"Using existing patched driver: {driver_exe_path}")

    # Detect chrome path
    browser_executable_path = get_chrome_exe_path()
    logging.debug(f"Using Chrome executable: {browser_executable_path}")

    # Log all options
    all_options = [opt for opt in options.arguments]
    logging.debug("Chrome options: " + pprint.pformat(all_options))

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
        logging.info("Chrome browser created successfully")
    except Exception as e:
        logging.error(f"Error starting Chrome: {e}")
        raise

    # Save the patched driver to avoid re-downloads
    if driver_exe_path is None:
        PATCHED_DRIVER_PATH = os.path.join(
            driver.patcher.data_path, driver.patcher.exe_name
        )
        if PATCHED_DRIVER_PATH != driver.patcher.executable_path:
            shutil.copy(driver.patcher.executable_path, PATCHED_DRIVER_PATH)
            logging.debug(f"Saved patched driver to: {PATCHED_DRIVER_PATH}")

    # Clean up proxy extension directory
    if proxy_extension_dir is not None:
        shutil.rmtree(proxy_extension_dir)
        logging.debug(f"Removed proxy extension directory: {proxy_extension_dir}")

    return driver


def get_chrome_exe_path() -> str:
    """Get the Chrome/Chromium executable path"""
    global CHROME_EXE_PATH
    if CHROME_EXE_PATH is not None:
        return CHROME_EXE_PATH

    # Check different possible locations
    logging.debug("Searching for Chrome executable...")

    # Linux pyinstaller bundle
    chrome_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "chrome", "chrome"
    )
    if os.path.exists(chrome_path):
        logging.debug(f"Found Chrome at bundle path: {chrome_path}")
        if not os.access(chrome_path, os.X_OK):
            logging.error(f"Chrome binary '{chrome_path}' is not executable")
            raise Exception(
                f'Chrome binary "{chrome_path}" is not executable. '
                f'Please, extract the archive with "tar xzf <file.tar.gz>".'
            )
        CHROME_EXE_PATH = chrome_path
        return CHROME_EXE_PATH

    # Windows pyinstaller bundle
    chrome_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "chrome", "chrome.exe"
    )
    if os.path.exists(chrome_path):
        logging.debug(f"Found Chrome at Windows bundle path: {chrome_path}")
        CHROME_EXE_PATH = chrome_path
        return CHROME_EXE_PATH

    # System installation
    try:
        CHROME_EXE_PATH = uc.find_chrome_executable()
        logging.debug(f"Found system Chrome at: {CHROME_EXE_PATH}")
    except Exception as e:
        logging.error(f"Failed to find Chrome executable: {e}")
        raise

    return CHROME_EXE_PATH


def get_chrome_major_version() -> str:
    """Get Chrome/Chromium major version"""
    global CHROME_MAJOR_VERSION
    if CHROME_MAJOR_VERSION is not None:
        return CHROME_MAJOR_VERSION

    logging.debug("Detecting Chrome version...")

    if os.name == "nt":
        # Windows version detection
        try:
            complete_version = extract_version_nt_executable(get_chrome_exe_path())
            logging.debug(f"Detected Chrome version from executable: {complete_version}")
        except Exception as e:
            logging.debug(f"Failed to get version from executable: {e}")
            try:
                complete_version = extract_version_nt_registry()
                logging.debug(f"Detected Chrome version from registry: {complete_version}")
            except Exception as e:
                logging.debug(f"Failed to get version from registry: {e}")
                complete_version = extract_version_nt_folder()
                logging.debug(f"Detected Chrome version from folder: {complete_version}")
    else:
        # Linux/macOS version detection
        chrome_path = get_chrome_exe_path()
        logging.debug(f"Running '{chrome_path} --version' to detect version")
        process = os.popen(f'"{chrome_path}" --version')
        complete_version = process.read()
        process.close()
        logging.debug(f"Chrome version output: {complete_version}")

    try:
        CHROME_MAJOR_VERSION = complete_version.split(".")[0].split(" ")[-1]
        logging.info(f"Detected Chrome major version: {CHROME_MAJOR_VERSION}")
    except Exception as e:
        logging.error(f"Failed to parse Chrome version: {e}")
        CHROME_MAJOR_VERSION = ""

    return CHROME_MAJOR_VERSION


def extract_version_nt_executable(exe_path: str) -> str:
    """Extract Chrome version from Windows executable"""
    import pefile

    pe = pefile.PE(exe_path, fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
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
        path = (
                "C:\\Program Files"
                + (" (x86)" if i else "")
                + "\\Google\\Chrome\\Application"
        )
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


async def get_user_agent_nd(driver=None) -> str:
    """Get User-Agent string from nodriver browser"""
    global USER_AGENT
    if USER_AGENT is not None:
        return USER_AGENT

    temp_driver = None
    try:
        if driver is None:
            logging.info("Creating temporary browser to get User-Agent...")
            temp_driver = await get_webdriver_nd()
            driver = temp_driver

        USER_AGENT = driver.info["User-Agent"]
        # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
        USER_AGENT = re.sub("HEADLESS", "", USER_AGENT, flags=re.IGNORECASE)
        logging.info(f"Detected User-Agent: {USER_AGENT}")
        return USER_AGENT
    except Exception as e:
        logging.error(f"Error getting browser User-Agent: {e}")
        raise Exception(f"Error getting browser User-Agent: {e}") from e
    finally:
        if temp_driver is not None:
            await after_run_cleanup(driver=temp_driver)
            logging.debug("Cleaned up temporary browser")


def get_user_agent_uc(driver=None) -> str:
    """Get User-Agent string from undetected-chromedriver browser"""
    global USER_AGENT
    if USER_AGENT is not None:
        return USER_AGENT

    temp_driver = None
    try:
        if driver is None:
            logging.info("Creating temporary browser to get User-Agent...")
            temp_driver = get_webdriver_uc()
            driver = temp_driver

        USER_AGENT = driver.execute_script("return navigator.userAgent")
        # Fix for Chrome 117 | https://github.com/FlareSolverr/FlareSolverr/issues/910
        USER_AGENT = re.sub("HEADLESS", "", USER_AGENT, flags=re.IGNORECASE)
        logging.info(f"Detected User-Agent: {USER_AGENT}")
        return USER_AGENT
    except Exception as e:
        logging.error(f"Error getting browser User-Agent: {e}")
        raise Exception(f"Error getting browser User-Agent: {e}") from e
    finally:
        if temp_driver is not None:
            if os.name == "nt":
                temp_driver.close()
            temp_driver.quit()
            logging.debug("Cleaned up temporary browser")


async def after_run_cleanup(driver: nd.Browser):
    """
    Clean up browser resources after run.

    Args:
        driver: The nodriver Browser instance to clean up
    """
    logging.debug("Performing browser cleanup...")

    # Get Browser instance process
    process = driver.get_process
    if process is None:
        logging.debug("No process to clean up")
        return

    # Get the list of child processes before closing the Browser instance
    child_processes = psutil.Process(process.pid).children(recursive=True)
    logging.debug(f"Found {len(child_processes)} child processes")

    # Stop Browser instance
    driver.stop()
    logging.debug("Browser instance stopped")

    # Wait for the websocket to return True (Closed)
    websocket_wait_start = time.time()
    while True:
        websocket_status = driver.connection.closed
        logging.debug(f"Websocket closed status: {websocket_status}")
        if websocket_status:
            break
        # Timeout after 10 seconds
        if time.time() - websocket_wait_start > 10:
            logging.warning("Timeout waiting for websocket to close")
            break
        await asyncio.sleep(0.1)

    # Find all chromium processes and terminate them if any
    for proc in child_processes:
        try:
            if proc.pid == process.pid:
                logging.debug(f"Terminating Chromium process with PID: {proc.pid}")
                proc.terminate()
            elif any(name in proc.name().lower() for name in ("chromium", "chrome")):
                logging.debug(
                    f"Terminating Chromium child process with PID: {proc.pid}"
                )
                proc.terminate()
            elif proc.status() == "zombie":
                logging.debug(
                    f"Terminating zombie Chromium process with PID: {proc.pid}"
                )
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logging.debug(f"Error terminating process {proc.pid}: {e}")

    # Wait for all processes to terminate
    for proc in child_processes:
        try:
            if proc.pid == process.pid or any(
                    name in proc.name().lower() for name in ("chromium", "chrome")
            ):
                proc.wait(timeout=10)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, psutil.TimeoutExpired) as e:
            logging.debug(f"Error waiting for process {proc.pid}: {e}")

    # Delete Browser instance data dir
    try:
        user_dir = driver.config.user_data_dir
        shutil.rmtree(user_dir, ignore_errors=False)
        logging.debug(f"Removed Browser user data directory {user_dir}")
    except OSError as e:
        logging.debug(
            f"Failed to delete Browser user data directory: {e}"
        )

    # Remove Browser instance from created instances
    try:
        nd.util.get_registered_instances().remove(driver)
        logging.debug("Removed Browser from registered instances")
    except Exception as e:
        logging.debug(f"Error when removing the Browser instance: {e}")


def start_xvfb_display():
    """Start virtual X display for headless mode on Linux"""
    global XVFB_DISPLAY
    if XVFB_DISPLAY is None:
        from xvfbwrapper import Xvfb

        XVFB_DISPLAY = Xvfb()
        XVFB_DISPLAY.start()
        logging.debug("VIRTUAL SCREEN STARTED")


def object_to_dict(_object):
    """Convert object to dictionary, removing hidden fields"""
    json_dict = json.loads(json.dumps(_object, default=lambda o: o.__dict__))
    # Remove hidden fields
    return {k: v for k, v in json_dict.items() if not k.startswith("__")}


def format_html(input_html):
    """Format HTML for logging"""
    # Parse the input HTML string
    soup = BeautifulSoup(input_html, 'html.parser')

    # Format the HTML with pretty print
    formatted_html = soup.prettify()

    return f"\n==========================================\n{formatted_html}\n==========================================\n"