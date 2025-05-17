from __future__ import annotations

import logging
import os
import time
from typing import Callable, Any, Optional, Tuple
from typing import List, Dict, Union

import gymnasium as gym

from desktop_env.controllers.python import PythonController
from desktop_env.controllers.setup import SetupController
from desktop_env.evaluators import metrics, getters
from desktop_env.providers import create_vm_manager_and_provider

# adv
from adv.WebArena_Reddit.injection import reddit_adv_setup
from adv.TheAgentCompany_RocketChat.run_multi_npc import rocketchat_adv_setup
from adv.TheAgentCompany_OwnCloud.injection import owncloud_adv_setup, owncloud_add_user

from adv.WebArena_Reddit.if_ready import check_server_ready_reddit
from adv.TheAgentCompany_RocketChat.if_ready import check_server_ready_rocketchat
from adv.TheAgentCompany_OwnCloud.if_ready import check_server_ready_owncloud
import re

import subprocess

logger = logging.getLogger("desktopenv.env")

Metric = Callable[[Any, Any], float]
Getter = Callable[[gym.Env, Dict[str, Any]], Any]


def contains_to_be_replaced(config_list):

    def check_value(value):
        if isinstance(value, str):
            return 'TO_BE_REPLACED' in value
        elif isinstance(value, dict):
            return any(check_value(v) for v in value.values())
        elif isinstance(value, list):
            return any(check_value(item) for item in value)
        return False

    return check_value(config_list)


def sub_url(url: str, to_be_replaced, replacement):
    url =  re.sub(to_be_replaced, replacement, url)
    return url


def replace_in_dict(data,to_be_replaced,replacement):
    if isinstance(data, dict):
        return {key: replace_in_dict(val,to_be_replaced,replacement) for key, val in data.items()}
    elif isinstance(data, list):
        return [replace_in_dict(item,to_be_replaced,replacement) for item in data]
    elif isinstance(data, tuple):
        return tuple(replace_in_dict(item,to_be_replaced,replacement) for item in data)
    elif isinstance(data, str):
        return sub_url(data,to_be_replaced,replacement)
    else:
        return data

def extract_http_hosts(config_list):

    extracted_hosts = set()

    def extract_from_value(value):
        if isinstance(value, str):
            matches = re.findall(r'http://[^/:]+', value)
            extracted_hosts.update(matches)
        elif isinstance(value, dict):
            for v in value.values():
                extract_from_value(v)
        elif isinstance(value, list):
            for item in value:
                extract_from_value(item)

    for item in config_list:
        extract_from_value(item)

    return list(extracted_hosts)


class DesktopEnv(gym.Env):
    """
    DesktopEnv with OpenAI Gym interface. It provides a desktop environment for setting and evaluating desktop automation tasks.
    """

    def __init__(
            self,
            provider_name: str = "vmware",
            region: str = None,
            path_to_vm: str = None,
            snapshot_name: str = "init_state",
            action_space: str = "computer_13",
            cache_dir: str = "cache",
            screen_size: Tuple[int] = (1920, 1080),
            headless: bool = False,
            require_a11y_tree: bool = True,
            require_terminal: bool = False,
            os_type: str = "Ubuntu",
            aws_ami: str = None,
    ):
        """
        Args:
            provider_name (str): virtualization provider name, default to "vmware"
            region (str): the region for allocate machines, work for cloud services, default to  "us-east-1"
            path_to_vm (str): path to .vmx file
            snapshot_name (str): snapshot name to revert to, default to "init_state"
            action_space (str): "computer_13" | "pyautogui"
            cache_dir (str): cache directory to cache task-related stuffs like
              reference file for evaluation
            screen_size (Tuple[int]): screen size of the VM
            headless (bool): whether to run the VM in headless mode
            require_a11y_tree (bool): whether to require accessibility tree
            require_terminal (bool): whether to require terminal output
        """
        # Initialize VM manager and vitualization provider
        self.region = region

        # Default
        self.server_port = 5000
        self.chromium_port = 9222
        self.vnc_port = 8006
        self.vlc_port = 8080
        self.aws_ami = aws_ami
        self.manager, self.provider = create_vm_manager_and_provider(provider_name, region, self.aws_ami)
        self.provider_name = provider_name
        self.os_type = os_type
        

        # Initialize environment variables
        if path_to_vm:
            self.path_to_vm = os.path.abspath(os.path.expandvars(os.path.expanduser(path_to_vm))) \
                if provider_name in {"vmware", "virtualbox"} else path_to_vm
        else:
            if provider_name in {"aws"}:
                # self.path_to_vm = self.manager.get_vm_path()
                self.path_to_vm = None
            else:
                self.path_to_vm = self.manager.get_vm_path(self.os_type, region)

        self.snapshot_name = snapshot_name
        self.cache_dir_base: str = cache_dir
        self.headless = headless
        self.require_a11y_tree = require_a11y_tree
        self.require_terminal = require_terminal

        # Initialize emulator and controller   
        if provider_name != "docker" and provider_name != 'aws': # Check if this is applicable to other VM providers
            logger.info("Initializing...")
            self._start_emulator()

        # mode: human or machine
        self.instruction = None
        assert action_space in ["computer_13", "pyautogui"]
        self.action_space = action_space  # todo: refactor it to the ActType

        # episodic stuffs, like counters, will be updated or reset
        # when calling self.reset()
        self._traj_no: int = -1
        self._step_no: int = 0
        self.action_history: List[Dict[str, any]] = []
        

    def _start_emulator(self):
        # Power on the virtual machine
        if self.provider_name in {"aws"}:
            self.provider.start_emulator(self.path_to_vm, None)
        else:
            self.provider.start_emulator(self.path_to_vm, self.headless, self.os_type)

        # Get the ip from the virtual machine, and setup the controller
        vm_ip_ports = self.provider.get_ip_address(self.path_to_vm).split(':')
        self.vm_ip = vm_ip_ports[0]
        if len(vm_ip_ports) > 1:
            self.server_port = int(vm_ip_ports[1])
            self.chromium_port = int(vm_ip_ports[2])
            self.vnc_port = int(vm_ip_ports[3])
            self.vlc_port = int(vm_ip_ports[4])
        self.controller = PythonController(vm_ip=self.vm_ip, server_port=self.server_port)
        self.setup_controller = SetupController(vm_ip=self.vm_ip, server_port=self.server_port, chromium_port=self.chromium_port, vlc_port=self.vlc_port, cache_dir=self.cache_dir_base)

    def _revert_to_snapshot(self):
        # Revert to certain snapshot of the virtual machine, and refresh the path to vm and ip of vm
        # due to the fact it could be changed when implemented by cloud services
        path_to_vm = self.provider.revert_to_snapshot(self.path_to_vm, self.snapshot_name)
        if self.provider_name in {"aws"}:
            # self.manager.add_vm(path_to_vm, self.region)
            # self.manager.occupy_vm(path_to_vm, os.getpid(), self.region)
            self.path_to_vm = path_to_vm
        else:
            if path_to_vm and not path_to_vm == self.path_to_vm:
                # path_to_vm has to be a new path
                self.manager.delete_vm(self.path_to_vm, self.region)
                self.manager.add_vm(path_to_vm, self.region)
                self.manager.occupy_vm(path_to_vm, os.getpid(), self.region)
                self.path_to_vm = path_to_vm

            

    def _save_state(self, snapshot_name=None):
        # Save the current virtual machine state to a certain snapshot name
        self.provider.save_state(self.path_to_vm, snapshot_name)


    def terminate(self):
        # terminate) the virtual machine
        self.provider.terminate_emulator(self.path_to_vm)
               
    def close(self):
        # Close (release) the virtual machine
        self.provider.stop_emulator(self.path_to_vm)

    def prepare_injection(self, task_config: Optional[Dict[str, Any]] = None, seed=None, options=None) -> Dict[str, Any]:
        # Reset to certain task in OSWorld
        logger.info("Resetting environment...")
        logger.info("Switching task...")
        logger.info("Setting counters...")
        self._traj_no += 1
        self._step_no = 0
        self.action_history.clear()

        logger.info("Reverting to snapshot to {}...".format(self.snapshot_name))
        self._revert_to_snapshot()
        logger.info("Starting emulator...")
        self._start_emulator()
        logger.info("Emulator started.")

        if task_config is not None:
            if self.provider_name == "aws":
                if task_config["platform"] == "reddit":
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_URL", f"http://{self.vm_ip}")
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_IP", f"{self.vm_ip}")

                elif task_config["platform"] == "owncloud":
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_URL", "http://the-agent-company.com")
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_IP", f"{self.vm_ip}")

                elif task_config["platform"] == "rocketchat":
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_URL", "http://the-agent-company.com")
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_IP", f"{self.vm_ip}")

            
            else:
                if task_config["platform"] == "reddit":
                    self.reddit_ip = os.getenv("REDDIT")
                    assert self.reddit_ip, "Run export REDDIT='<your_reddit_domain>'"

                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_URL", f"http://{self.reddit_ip}")
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_IP", f"{self.reddit_ip}")

                elif task_config["platform"] == "owncloud":
                    self.owncloud_ip = os.getenv("OWNCLOUD")
                    assert self.owncloud_ip, "Run export OWNCLOUD='<your_owncloud_domain>'"

                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_URL", "http://the-agent-company.com")
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_IP", f"{self.owncloud_ip}")

                elif task_config["platform"] == "rocketchat":
                    self.rocketchat_ip = os.getenv("ROCKETCHAT")
                    assert self.rocketchat_ip, "Run export ROCKETCHAT='<your_rocketchat_domain>'"

                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_URL", "http://the-agent-company.com")
                    task_config = replace_in_dict(task_config, "TO_BE_REPLACED_IP", f"{self.rocketchat_ip}")
            

            self._set_task_info(task_config)

            logger.info("Setting up adversary config...")
            for adversary_c in self.adversary_config:
                hostname = adversary_c["ip"]
                    
                if self.provider_name == "aws":
                    ssh_login_info = {
                        'hostname': hostname,
                        'username': 'user',
                        'password': 'password',
                    }
                    jump_wait = False

                else:
                    ssh_login_info = {
                        'hostname': hostname,
                        'username': 'ubuntu',
                        'key_filename': os.getenv("KEY_FILENAME")
                    }
                    jump_wait = True
                    
                if adversary_c["type"] == "reddit_adv_setup":
                    logger.info("Checking if the reddit is ready...")
                    if check_server_ready_reddit(ssh_login_info["hostname"], jump_wait = jump_wait):
                        logger.info("Reddit is ready")
                    else:
                        raise RuntimeError("Reddit is not ready.")
                    logger.info("Performing injection on the fly...")
                    if reddit_adv_setup(adversary_c,login_info=ssh_login_info):
                        logger.info("Injection is done.")
                    else:
                        raise RuntimeError("Injection failed.")
                    
                elif adversary_c["type"] == "rocketchat_adv_setup":
                    logger.info("Checking if the rocketchat is ready...")
                    if check_server_ready_rocketchat(ssh_login_info["hostname"], jump_wait = jump_wait):
                        logger.info("Rocketchat is ready")
                    else:  
                        raise RuntimeError("Rocketchat is not ready.")
                    original_dir = os.getcwd()
                    os.chdir('./adv/TheAgentCompany_RocketChat')

                    # reset RocketChat for VMware runs
                    if self.provider_name == "vmware":
                        subprocess.run(['bash', 'reset.sh'], check=True)
                    
                    rocketchat_adv_setup(adversary_c)
                    os.chdir(original_dir)

                elif adversary_c["type"] == "owncloud_adv_setup":
                    logger.info("Checking if the owncloud is ready...")
                    if check_server_ready_owncloud(ssh_login_info["hostname"], jump_wait = jump_wait):
                        logger.info("Owncloud is ready")
                    else:
                        raise RuntimeError("Owncloud is not ready.")
                    
                    # reset OwnCloud for VMware runs
                    original_dir = os.getcwd()
                    os.chdir('./adv/TheAgentCompany_OwnCloud')
                    if self.provider_name == "vmware":
                        subprocess.run(['bash', 'reset.sh'], check=True)
                    os.chdir(original_dir)

                    logger.info("Performing injection on the fly...")
                    if owncloud_adv_setup(adversary_c,login_info=ssh_login_info):
                        logger.info("Injection is done.")
                    else:
                        raise RuntimeError("Injection failed.")
                    owncloud_add_user(ssh_login_info)
                    
                else:
                    raise ValueError("adversary config is wrong")


            logger.info("Adversary setup complete.")

            self.setup_controller.reset_cache_dir(self.cache_dir)
            logger.info("Setting up environment...")

            self.setup_controller.setup(self.config)
            logger.info("Environment setup complete.")
            time.sleep(20)

        observation = self._get_obs()
        return observation

    def _get_obs(self):
        # We provide screenshot, accessibility_tree (optional), terminal (optional), and instruction.
        # can be customized and scaled
        return {
            "screenshot": self.controller.get_screenshot(),
            "accessibility_tree": self.controller.get_accessibility_tree() if self.require_a11y_tree else None,
            "terminal": self.controller.get_terminal_output() if self.require_terminal else None,
            "instruction": self.instruction
        }

    @property
    def vm_platform(self):
        return self.controller.get_vm_platform()

    @property
    def vm_screen_size(self):
        return self.controller.get_vm_screen_size()

    def _set_task_info(self, task_config: Dict[str, Any]):
        self.task_id: str = task_config["id"]
        self.cache_dir: str = os.path.join(self.cache_dir_base, self.task_id)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.instruction = task_config["instruction"]
        self.config = task_config["config"] if "config" in task_config else []
        self.adversary_config = task_config["adversary_config"] if "adversary_config" in task_config else []

        # evaluator dict
        # func -> metric function string, or list of metric function strings
        # conj -> conjunction of multiple metrics if func is a list with length > 1, "and"/"or"
        # result -> result getter config, or list of result getter configs
        # expected (optional) -> expected getter config, or list of expected getter configs
        # options (optional) -> metric options, or list of metric options
        # if func is a str list, then result, expected (if exists), options (if exists) should also be lists of the same length
        # even if one of the metrics does not need expected or options field, it should be included in the list with None
        self.evaluator = task_config["evaluator"]
        self.metric: Metric = [getattr(metrics, func) for func in self.evaluator["func"]] \
            if isinstance(self.evaluator["func"], list) \
            else getattr(metrics, self.evaluator["func"])
        self.metric_conj: str = self.evaluator.get("conj", "and")  # take conjunction of multiple metrics
        if "result" in self.evaluator and len(self.evaluator["result"]) > 0:
            self.result_getter: Getter = [getattr(getters, "get_{:}".format(res["type"])) for res in
                                          self.evaluator["result"]] \
                if isinstance(self.evaluator["result"], list) \
                else getattr(getters, "get_{:}".format(self.evaluator["result"]["type"]))
        else:
            self.result_getter = [None] * len(self.metric) \
                if isinstance(self.metric, list) \
                else None

        if "expected" in self.evaluator and len(self.evaluator["expected"]) > 0:
            self.expected_getter: Getter = [getattr(getters, "get_{:}".format(exp["type"])) if exp else None for exp in
                                            self.evaluator["expected"]] \
                if isinstance(self.evaluator["expected"], list) \
                else getattr(getters, "get_{:}".format(self.evaluator["expected"]["type"]))
        else:
            self.expected_getter = [None] * len(self.metric) \
                if isinstance(self.metric, list) \
                else None
        self.metric_options: Union[List[Dict[str, Any]], Dict[str, Any]] = [opt if opt else {} for opt in
                                                                            self.evaluator["options"]] \
            if isinstance(self.evaluator.get("options", {}), list) \
            else self.evaluator["options"] \
            if "options" in self.evaluator \
            else [{}] * len(self.metric) \
            if isinstance(self.metric, list) \
            else {}

        assert (not isinstance(self.evaluator["func"], list)
                or (len(self.metric) == len(self.result_getter) == len(self.expected_getter) == len(
                    self.metric_options)))
        
        # adversary evaluation dict
        # same as the evaluation dict
        self.adversary_evaluator = task_config["adversary_evaluator"]
        self.adversary_metric: Metric = [getattr(metrics, func) for func in self.adversary_evaluator["func"]] \
            if isinstance(self.adversary_evaluator["func"], list) \
            else getattr(metrics, self.adversary_evaluator["func"])
        self.adversary_metric_conj: str = self.adversary_evaluator.get("conj", "and")  # take conjunction of multiple metrics
        if "result" in self.adversary_evaluator and len(self.adversary_evaluator["result"]) > 0:
            self.adversary_result_getter: Getter = [getattr(getters, "get_{:}".format(res["type"])) for res in
                                          self.adversary_evaluator["result"]] \
                if isinstance(self.adversary_evaluator["result"], list) \
                else getattr(getters, "get_{:}".format(self.adversary_evaluator["result"]["type"]))
        else:
            self.adversary_result_getter = [None] * len(self.adversary_metric) \
                if isinstance(self.adversary_metric, list) \
                else None

        if "expected" in self.adversary_evaluator and len(self.adversary_evaluator["expected"]) > 0:
            self.adversary_expected_getter: Getter = [getattr(getters, "get_{:}".format(exp["type"])) if exp else None for exp in
                                            self.adversary_evaluator["expected"]] \
                if isinstance(self.adversary_evaluator["expected"], list) \
                else getattr(getters, "get_{:}".format(self.adversary_evaluator["expected"]["type"]))
        else:
            self.adversary_expected_getter = [None] * len(self.adversary_metric) \
                if isinstance(self.adversary_metric, list) \
                else None
        self.adversary_metric_options: Union[List[Dict[str, Any]], Dict[str, Any]] = [opt if opt else {} for opt in
                                                                            self.adversary_evaluator["options"]] \
            if isinstance(self.adversary_evaluator.get("options", {}), list) \
            else self.adversary_evaluator["options"] \
            if "options" in self.adversary_evaluator \
            else [{}] * len(self.adversary_metric) \
            if isinstance(self.adversary_metric, list) \
            else {}

        assert (not isinstance(self.adversary_evaluator["func"], list)
                or (len(self.adversary_metric) == len(self.adversary_result_getter) == len(self.adversary_expected_getter) == len(
                    self.adversary_metric_options)))

    def step(self, action, pause=2):
        self._step_no += 1
        self.action_history.append(action)

        reward = 0  # todo: Define reward calculation for each example
        done = False  # todo: Define episode termination condition for each example
        info = {}

        # handle the special actions
        if action in ['WAIT', 'FAIL', 'DONE'] or (type(action) == dict and action['action_type'] in ['WAIT', 'FAIL', 'DONE']):
            if action == 'WAIT':
                time.sleep(pause)
            elif action == 'FAIL':
                done = True
                info = {"fail": True}
            elif action == 'DONE':
                done = True
                info = {"done": True}

        if self.action_space == "computer_13":
            # the set of all possible actions defined in the action representation
            self.controller.execute_action(action)
        elif self.action_space == "pyautogui":
            if action in ['WAIT', 'FAIL', 'DONE']:
                self.controller.execute_action(action)
            else:
                # the set of all possible python commands insides `pyautogui`
                self.controller.execute_python_command(action)

        time.sleep(pause)
        observation = self._get_obs()

        return observation, reward, done, info

    def evaluate(self, response):
        """
        Evaluate whether the task is successfully completed.
        """

        self.setup_controller.setup(self.evaluator.get("postconfig", []))

        # if self.evaluator['func'] == "infeasible":
        #     if len(self.action_history) > 0 and self.action_history[-1] == "FAIL":
        #         return 1
        #     else:
        #         return 0
        # else:
        #     if len(self.action_history) > 0 and self.action_history[-1] == "FAIL":
        #         return 0

        if type(self.metric) == list:
            results = []
            for idx, metric in enumerate(self.metric):
                try:
                    if self.result_getter[idx] is getters.get_from_response:
                        result_state = response
                    else:
                        config = self.evaluator["result"][idx]
                        result_state = self.result_getter[idx](self, config)
                except FileNotFoundError:
                    logger.error("File not found!")
                    if self.metric_conj == 'and':
                        return 0

                expected = self.evaluator["expected"][idx]
                expected_state = self.expected_getter[idx](self, expected) if expected else None

                metric: int = metric(result_state, expected_state,
                                     **self.metric_options[idx]) if expected_state is not None \
                    else metric(result_state, **self.metric_options[idx])

                if self.metric_conj == 'and' and float(metric) == 0.0:
                    return 0
                elif self.metric_conj == 'or' and float(metric) == 1.0:
                    return 1
                else:
                    results.append(metric)
            return sum(results) / len(results) if self.metric_conj == 'and' else max(results)
        else:
            try:
                if self.result_getter is getters.get_from_response:
                    result_state = response
                else:
                    result_state = self.result_getter(self, self.evaluator["result"])
            except FileNotFoundError:
                logger.error("File not found!")
                return 0

            expected_state = self.expected_getter(self, self.evaluator["expected"]) if "expected" in self.evaluator \
                else None

            metric: float = self.metric(result_state, expected_state,
                                        **self.metric_options) if expected_state is not None \
                else self.metric(result_state, **self.metric_options)

        return metric

    def adversary_evaluate(self):
        """
        Evaluate whether the task is successfully completed.
        """

        if type(self.adversary_metric) == list:
            results = []
            for idx, metric in enumerate(self.adversary_metric):
                try:
                    config = self.adversary_evaluator["result"][idx]
                    result_state = self.adversary_result_getter[idx](self, config)
                except FileNotFoundError:
                    logger.error("File not found!")
                    if self.adversary_metric_conj == 'and':
                        return 0

                expected = self.adversary_evaluator["expected"][idx]
                expected_state = self.adversary_expected_getter[idx](self, expected) if expected else None

                metric: int = metric(result_state, expected_state,
                                     **self.adversary_metric_options[idx]) if expected_state is not None \
                    else metric(result_state, **self.adversary_metric_options[idx])

                if self.adversary_metric_conj == 'and' and float(metric) == 0.0:
                    return 0
                elif self.adversary_metric_conj == 'or' and float(metric) == 1.0:
                    return 1
                else:
                    results.append(metric)
            return sum(results) / len(results) if self.adversary_metric_conj == 'and' else max(results)
        else:
            try:
                result_state = self.adversary_result_getter(self, self.adversary_evaluator["result"])
            except FileNotFoundError:
                logger.error("File not found!")
                return 0

            expected_state = self.adversary_expected_getter(self, self.adversary_evaluator["expected"]) if "expected" in self.adversary_evaluator \
                else None

            metric: float = self.adversary_metric(result_state, expected_state,
                                        **self.adversary_metric_options) if expected_state is not None \
                else self.adversary_metric(result_state, **self.adversary_metric_options)

        return metric


    def render(self, mode='rgb_array'):
        if mode == 'rgb_array':
            return self.controller.get_screenshot()
        else:
            raise ValueError('Unsupported render mode: {}'.format(mode))
