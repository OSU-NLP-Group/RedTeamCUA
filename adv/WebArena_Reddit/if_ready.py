import requests
import time
import logging
logger = logging.getLogger("adv.WebArena_Reddit.if_ready")


def check_server_ready_reddit(url, interval=20, max_retries=40, port = 9999, jump_wait = None):

    logger.info(f"Checking the status of Reddit on the url: {url}")
    url = f"http://{url}:{port}"
    retry_count = 0
    while retry_count < max_retries:
        try:
            logger.info(f"Try #{retry_count + 1} times: connecting to {url}")
            response = requests.get(url, timeout=10)
            
            if "Internal Server Error" not in response.text:
                logger.info(f"Reddit on the url {url} is ready.")
                if jump_wait:
                    return True
                time.sleep(60) # Wait for 60 seconds to make sure the server is ready
                return True
            
            logger.info("Internal Server Error")
        except requests.exceptions.RequestException as e:
            logger.info(f"Retry...")
        
        retry_count += 1
        if retry_count < max_retries:
            logger.info(f"Wait for {interval} and retry...")
            time.sleep(interval)
    
    logger.error(f"Max tries: ({max_retries}) is reached. Reddit on the url {url} is not ready.")
    return False