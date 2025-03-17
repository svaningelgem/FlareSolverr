import json
import logging
import os
import pprint
import sys

import certifi
from bottle import Bottle, ServerAdapter, request, response, run

import utils
from bottle_plugins.error_plugin import error_plugin
from bottle_plugins.logger_plugin import logger_plugin
from dtos import V1RequestBase
from method_utils import call_method
from service_factory import create_service


class JSONErrorBottle(Bottle):
    """
    Handle 404 errors with JSON responses
    """

    def default_error_handler(self, res):
        response.content_type = "application/json"
        return json.dumps({"error": res.body, "status_code": res.status_code})


app = JSONErrorBottle()

# Create the appropriate service implementation
service = create_service()


@app.route("/")
def index():
    """
    Show welcome message
    """
    logging.info("Handling request to /")
    res = call_method(service, "index_endpoint")
    result = utils.object_to_dict(res)
    logging.debug(f"Index response: {pprint.pformat(result)}")
    return result


@app.route("/health")
def health():
    """
    Healthcheck endpoint
    """
    logging.debug("Handling request to /health")
    res = call_method(service, "health_endpoint")
    return utils.object_to_dict(res)


@app.post("/v1")
def controller_v1():
    """
    Controller v1
    """
    # Deep log request details
    logging.info("Handling POST request to /v1")
    request_body = request.json if request.json else {}
    request_headers = dict(request.headers.items())

    logging.debug(f"Request headers: {pprint.pformat(request_headers)}")
    logging.debug(f"Request body: {pprint.pformat(request_body)}")

    req = V1RequestBase(request_body)

    # Call service method and handle response
    res = call_method(service, "controller_v1_endpoint", req)

    if res.__error_500__:
        response.status = 500

    result = utils.object_to_dict(res)
    logging.debug(f"Response body: {pprint.pformat(result)}")

    # Log response headers
    response_headers = dict(response.headers.items())
    logging.debug(f"Response headers: {pprint.pformat(response_headers)}")

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
    log_level = os.environ.get("LOG_LEVEL", "DEBUG").upper()
    server_host = os.environ.get("HOST", "0.0.0.0")
    server_port = int(os.environ.get("PORT", 8191))

    # Configure logger
    logger_format = "%(asctime)s %(levelname)-8s %(message)s"
    if log_level == "DEBUG":
        logger_format = "%(asctime)s %(levelname)-8s ReqId %(thread)s %(message)s"
    logging.basicConfig(
        format=logger_format,
        level=log_level,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Disable warning traces from various libraries
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("selenium.webdriver.remote.remote_connection").setLevel(logging.WARNING)
    logging.getLogger("undetected_chromedriver").setLevel(logging.WARNING)
    # Nodriver is very verbose in debug
    logging.getLogger("nd.core.element").disabled = True
    logging.getLogger("nodriver.core.browser").disabled = True
    logging.getLogger("nodriver.core.tab").disabled = True
    logging.getLogger("websockets.client").disabled = True

    # Log startup information
    logging.info(f"FlareSolverr {utils.get_flaresolverr_version()} starting up")
    logging.info(f"Server listening on http://{server_host}:{server_port}")
    if log_level == "DEBUG":
        logging.debug("Debug logging enabled")

    # Driver type information
    driver_type = utils.get_driver_selection()
    logging.info(f"Using driver: {driver_type}")

    logging.info("WARNING: YOU ARE RUNNING AN UNOFFICIAL EXPERIMENTAL BRANCH OF FLARESOLVER WHICH MAY CONTAIN BUGS.")
    logging.info("WARNING: IF YOU ENCOUNTER ANY, PLEASE REPORT THEM ON GITHUB AT THE FOLLOWING LINK:")
    logging.info("WARNING: https://github.com/FlareSolverr/FlareSolverr/pull/1163")

    # Test browser installation based on driver selection
    logging.info("Testing browser installation...")
    call_method(service, "test_browser_installation")
    logging.info("Browser installation test passed")

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

            logging.info(f"Starting waitress server on {self.host}:{self.port}")
            serve(handler, host=self.host, port=self.port, asyncore_use_poll=True)
            logging.info("Server stopped")

    logging.info("Starting server...")
    run(app, host=server_host, port=server_port, quiet=True, server=WaitressServerPoll)
