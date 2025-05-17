import requests
import time
import logging

logger = logging.getLogger("adv.TheAgentCompany_RocketChat.if_ready")

def check_server_ready_rocketchat(host, interval=10, max_retries=40, port=2999, jump_wait = False):
    """
    Ping the RocketChat healthcheck endpoint until HTTP 200 is received, with retries.
    
    Args:
        host (str): IP or hostname (without scheme or port)
        interval (int): Time (in seconds) between each retry
        max_retries (int): Max retry count
        port (int): Port to connect to (default 2999)
    
    Returns:
        bool: True if ready, False if failed
    """
    url = f"http://{host}:{port}/api/healthcheck/rocketchat"
    logger.info(f"Checking Rocketchat healthcheck on {url}")

    for retry_count in range(1, max_retries + 1):
        try:
            logger.info(f"Try #{retry_count}: GET {url}")
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                logger.info("owncloud is ready.")
                if not jump_wait:
                    time.sleep(60)
                return True
            else:
                logger.info(f"Status code: {response.status_code}, retrying...")
        
        except requests.RequestException as e:
            logger.info(f"Exception occurred: {e}, retrying...")

        if retry_count < max_retries:
            time.sleep(interval)

    logger.error(f"Reached max retries ({max_retries}). Rocketchat is not ready.")
    return False
