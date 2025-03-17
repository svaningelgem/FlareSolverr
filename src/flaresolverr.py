import asyncio
import inspect
import json
import os
import pprint
import sys
import time
from typing import Any

import certifi
from bottle import Bottle, ServerAdapter, request, response, run
from loguru import logger

import utils
from bottle_plugins.error_plugin import error_plugin
from bottle_plugins.logger_plugin import logger_plugin
from dtos import V1RequestBase
import service_factory



def call_service(method_name: str, *args, **kwargs) -> Any:
    """
    Call a method that might be synchronous or asynchronous.

    Args:
        method_name: Name of the method to call
        *args: Positional arguments to pass to the method
        **kwargs: Keyword arguments to pass to the method

    Returns:
        The return value of the method
    """
    service = service_factory.get()
    if not hasattr(service, method_name):
        raise AttributeError(f"Object has no method named '{method_name}'")

    method = getattr(service, method_name)

    if inspect.iscoroutinefunction(method):
        logger.debug(f"Calling async method: {method_name}")
        return asyncio.run(method(*args, **kwargs))
    else:
        logger.debug(f"Calling sync method: {method_name}")
        return method(*args, **kwargs)


# Configure loguru
def setup_logging() -> None:
    """Configure loguru logger"""

    log_level = os.environ.get("LOG_LEVEL", "DEBUG").upper()
    if log_level != "DEBUG":  # Loguru's default is already DEBUG, with a good debugging format
        log_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"

        # Remove the default handler
        logger.remove()

        # Add console logger with the format
        logger.add(
            sys.stdout,
            format=log_format,
            level=log_level,
            colorize=True,
        )


class JSONErrorBottle(Bottle):
    """
    Handle 404 errors with JSON responses
    """

    def default_error_handler(self, res):
        response.content_type = "application/json"
        return json.dumps({"error": res.body, "status_code": res.status_code})


app = JSONErrorBottle()


@app.route("/")
def index():
    """
    Show welcome message
    """
    logger.info("Handling request to /")
    res = call_service("index_endpoint")
    result = utils.object_to_dict(res)
    logger.debug(f"Index response: {pprint.pformat(result)}")
    return result


@app.route("/health")
def health():
    """
    Healthcheck endpoint
    """
    logger.debug("Handling request to /health")
    res = call_service("health_endpoint")
    return utils.object_to_dict(res)


@app.post("/v1")
def controller_v1():
    """
    Controller v1
    """
    # Deep log request details
    start_time = time.time()
    request_id = f"req-{int(start_time * 1000) % 10000:04d}"
    logger.configure(extra={"request_id": request_id})

    logger.info("Handling POST request to /v1")
    request_body = request.json if request.json else {}
    request_headers = dict(request.headers.items())

    logger.debug(f"Request headers: {pprint.pformat(request_headers)}")
    logger.debug(f"Request body: {pprint.pformat(request_body)}")

    req = V1RequestBase(request_body)

    # Call service method and handle response
    res = call_service("controller_v1_endpoint", req)

    if res.__error_500__:
        response.status = 500

    result = utils.object_to_dict(res)
    logger.debug(f"Response body: {pprint.pformat(result)}")

    # Log response headers and timing
    response_headers = dict(response.headers.items())
    logger.debug(f"Response headers: {pprint.pformat(response_headers)}")

    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"Request completed in {duration_ms:.2f}ms")

    return result


if __name__ == "__main__":
    # Check Python version

    # Fix for HEADLESS=false in Windows binary
    # https://stackoverflow.com/a/27694505
    if os.name == "nt":
        import multiprocessing

        multiprocessing.freeze_support()

    # Fix SSL certificates for compiled binaries
    # https://github.com/pyinstaller/pyinstaller/issues/7229
    # https://stackoverflow.com/questions/55736855/how-to-change-the-cafile-argument-in-the-ssl-module-in-python3
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["SSL_CERT_FILE"] = certifi.where()

    # Validate configuration
    server_host = os.environ.get("HOST", "0.0.0.0")
    server_port = int(os.environ.get("PORT", 8191))

    # Configure logger
    setup_logging()

    # Disable warning traces from various libraries by not intercepting their logs
    # Instead, we'll just let loguru handle the logs directly

    # Log startup information
    logger.info(f"FlareSolverr {utils.get_flaresolverr_version()} starting up")
    logger.info(f"Server listening on http://{server_host}:{server_port}")
    logger.debug("Debug logging enabled")

    # Driver type information
    driver_type = utils.get_driver_selection()
    logger.info(f"Using driver: {driver_type}")

    logger.warning("YOU ARE RUNNING AN UNOFFICIAL EXPERIMENTAL BRANCH OF FLARESOLVER WHICH MAY CONTAIN BUGS.")

    # Test browser installation based on driver selection
    logger.info("Testing browser installation...")
    call_service("test_browser_installation")
    logger.info("Browser installation test passed")

    # Install bottle plugins (error handling and logging)
    app.install(logger_plugin)
    app.install(error_plugin)

    # Start webserver
    # Default server 'wsgiref' does not support concurrent requests
    # https://github.com/FlareSolverr/FlareSolverr/issues/680
    # https://github.com/Pylons/waitress/issues/31
    class WaitressServerPoll(ServerAdapter):
        def run(self, handler):
            from waitress import serve

            logger.info(f"Starting waitress server on {self.host}:{self.port}")
            serve(handler, host=self.host, port=self.port, asyncore_use_poll=True)
            logger.info("Server stopped")

    logger.info("Starting server...")
    run(app, host=server_host, port=server_port, quiet=True, server=WaitressServerPoll)
