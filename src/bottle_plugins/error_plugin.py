from bottle import response
import logging
import json
import traceback


def error_plugin(callback):
    """
    Bottle plugin to handle exceptions and return JSON error responses

    Args:
        callback: The route callback to wrap

    Returns:
        Wrapped callback function that handles exceptions
    """
    def wrapper(*args, **kwargs):
        try:
            actual_response = callback(*args, **kwargs)
        except Exception as e:
            # Get full traceback
            trace = traceback.format_exc()

            # Log error with trace
            logging.error(f"Error in route handler: {str(e)}")
            logging.debug(f"Traceback: {trace}")

            # Return error as JSON
            response.status = 500
            response.content_type = 'application/json'
            return json.dumps({
                "error": str(e),
                "status_code": 500
            })

        return actual_response

    return wrapper