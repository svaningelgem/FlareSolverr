from bottle import request, response
from loguru import logger
import time
import uuid


def logger_plugin(callback):
    """
    Bottle plugin for enhanced request logging

    Args:
        callback: The route callback to wrap

    Returns:
        Wrapped callback function with logging
    """
    def wrapper(*args, **kwargs):
        # Generate a request ID for traceability
        request_id = str(uuid.uuid4())[:8]

        # Start timing
        start_time = time.time()

        # Log request start
        if not request.url.endswith("/health"):
            logger.info(f"[{request_id}] {request.method} {request.url} - START")
            logger.debug(f"[{request_id}] Headers: {dict(request.headers.items())}")

            if request.json:
                logger.debug(f"[{request_id}] Request body: {request.json}")

        # Process the request
        actual_response = callback(*args, **kwargs)

        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000  # in milliseconds

        # Log completion
        if not request.url.endswith("/health"):
            logger.info(f"[{request_id}] {request.method} {request.url} - {response.status} - {processing_time:.2f}ms")

        return actual_response

    return wrapper