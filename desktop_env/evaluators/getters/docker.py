import logging
from typing import Dict

logger = logging.getLogger("desktopenv.getters.docker")


def get_docker_images(env, config: Dict[str, str]):
    cmd = "docker images -a"
    # cmd = "echo 'password' | sudo -S docker images -a"
    response = env.controller.execute_command(cmd)

    return response["output"].strip()