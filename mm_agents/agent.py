import base64
import json
import logging
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from http import HTTPStatus
from io import BytesIO
from typing import Dict, List

import backoff
import dashscope
import google.generativeai as genai
import openai
import requests
import tiktoken
from PIL import Image
from google.api_core.exceptions import InvalidArgument, ResourceExhausted, InternalServerError, BadRequest
from groq import Groq
from requests.exceptions import SSLError

from mm_agents.accessibility_tree_wrap.heuristic_retrieve import filter_nodes, draw_bounding_boxes
from mm_agents.prompts import SYS_PROMPT_IN_SCREENSHOT_OUT_CODE, SYS_PROMPT_IN_SCREENSHOT_OUT_ACTION, \
    SYS_PROMPT_IN_A11Y_OUT_CODE, SYS_PROMPT_IN_A11Y_OUT_ACTION, \
    SYS_PROMPT_IN_BOTH_OUT_CODE, SYS_PROMPT_IN_BOTH_OUT_ACTION, \
    SYS_PROMPT_IN_SOM_OUT_TAG, \
    SYS_PROMPT_FOR_COMPUTER_USE_AGENT , \
    SYS_PROMPT_FOR_OPENAI_SECOND_CALL, \
    SYS_PROMPT_FOR_CLAUDE_SECOND_CALL, \
    SYS_PROMPT_ADDTIONAL, \
    SYS_DEFENSE_PROMPT

from mm_agents.utils import convert_for_openai_cua, convert_for_claude_cua, adjust_coordinates_from_response

from openai import AzureOpenAI
from anthropic import AnthropicBedrock
import httpx

logger = logging.getLogger("desktopenv.agent")

pure_text_settings = ['a11y_tree']

attributes_ns_ubuntu = "https://accessibility.windows.example.org/ns/attributes"
attributes_ns_windows = "https://accessibility.windows.example.org/ns/attributes"
state_ns_ubuntu = "https://accessibility.ubuntu.example.org/ns/state"
state_ns_windows = "https://accessibility.windows.example.org/ns/state"
component_ns_ubuntu = "https://accessibility.ubuntu.example.org/ns/component"
component_ns_windows = "https://accessibility.windows.example.org/ns/component"
value_ns_ubuntu = "https://accessibility.ubuntu.example.org/ns/value"
value_ns_windows = "https://accessibility.windows.example.org/ns/value"
class_ns_windows = "https://accessibility.windows.example.org/ns/class"
# More namespaces defined in OSWorld, please check desktop_env/server/main.py


# Function to encode the image
def encode_image(image_content):
    return base64.b64encode(image_content).decode('utf-8')


def encoded_img_to_pil_img(data_str):
    base64_str = data_str.replace("data:image/png;base64,", "")
    image_data = base64.b64decode(base64_str)
    image = Image.open(BytesIO(image_data))

    return image


def save_to_tmp_img_file(data_str):
    base64_str = data_str.replace("data:image/png;base64,", "")
    image_data = base64.b64decode(base64_str)
    image = Image.open(BytesIO(image_data))

    tmp_img_path = os.path.join(tempfile.mkdtemp(), "tmp_img.png")
    image.save(tmp_img_path)

    return tmp_img_path


def linearize_accessibility_tree(accessibility_tree, platform="ubuntu"):

    if platform == "ubuntu":
        _attributes_ns = attributes_ns_ubuntu
        _state_ns = state_ns_ubuntu
        _component_ns = component_ns_ubuntu
        _value_ns = value_ns_ubuntu
    elif platform == "windows":
        _attributes_ns = attributes_ns_windows
        _state_ns = state_ns_windows
        _component_ns = component_ns_windows
        _value_ns = value_ns_windows
    else:
        raise ValueError("Invalid platform, must be 'ubuntu' or 'windows'")

    filtered_nodes = filter_nodes(ET.fromstring(accessibility_tree), platform)
    linearized_accessibility_tree = ["tag\tname\ttext\tclass\tdescription\tposition (top-left x&y)\tsize (w&h)"]

    # Linearize the accessibility tree nodes into a table format
    for node in filtered_nodes:
        if node.text:
            text = (
                node.text if '"' not in node.text \
                    else '"{:}"'.format(node.text.replace('"', '""'))
            )

        elif node.get("{{{:}}}class".format(class_ns_windows), "").endswith("EditWrapper") \
                and node.get("{{{:}}}value".format(_value_ns)):
            node_text = node.get("{{{:}}}value".format(_value_ns), "")
            text = (node_text if '"' not in node_text \
                        else '"{:}"'.format(node_text.replace('"', '""'))
                    )
        else:
            text = '""'

        linearized_accessibility_tree.append(
            "{:}\t{:}\t{:}\t{:}\t{:}\t{:}\t{:}".format(
                node.tag, node.get("name", ""),
                text,
                node.get("{{{:}}}class".format(_attributes_ns), "") if platform == "ubuntu" else node.get("{{{:}}}class".format(class_ns_windows), ""),
                node.get("{{{:}}}description".format(_attributes_ns), ""),
                node.get('{{{:}}}screencoord'.format(_component_ns), ""),
                node.get('{{{:}}}size'.format(_component_ns), "")
            )
        )

    return "\n".join(linearized_accessibility_tree)


def tag_screenshot(screenshot, accessibility_tree, platform="ubuntu"):
    nodes = filter_nodes(ET.fromstring(accessibility_tree), platform=platform, check_image=True)
    # Make tag screenshot
    marks, drew_nodes, element_list, tagged_screenshot = draw_bounding_boxes(nodes, screenshot)

    return marks, drew_nodes, tagged_screenshot, element_list


def parse_actions_from_string(input_string):
    if input_string.strip() in ['WAIT', 'DONE', 'FAIL']:
        return [input_string.strip()]
    # Search for a JSON string within the input string
    actions = []
    matches = re.findall(r'```json\s+(.*?)\s+```', input_string, re.DOTALL)
    if matches:
        # Assuming there's only one match, parse the JSON string into a dictionary
        try:
            for match in matches:
                action_dict = json.loads(match)
                actions.append(action_dict)
            return actions
        except json.JSONDecodeError as e:
            return f"Failed to parse JSON: {e}"
    else:
        matches = re.findall(r'```\s+(.*?)\s+```', input_string, re.DOTALL)
        if matches:
            # Assuming there's only one match, parse the JSON string into a dictionary
            try:
                for match in matches:
                    action_dict = json.loads(match)
                    actions.append(action_dict)
                return actions
            except json.JSONDecodeError as e:
                return f"Failed to parse JSON: {e}"
        else:
            try:
                action_dict = json.loads(input_string)
                return [action_dict]
            except json.JSONDecodeError:
                raise ValueError("Invalid response format: " + input_string)


def parse_code_from_string(input_string):
    input_string = "\n".join([line.strip() for line in input_string.split(';') if line.strip()])
    if input_string.strip() in ['WAIT', 'DONE', 'FAIL']:
        return [input_string.strip()]

    # This regular expression will match both ```code``` and ```python code```
    # and capture the `code` part. It uses a non-greedy match for the content inside.
    pattern = r"```(?:\w+\s+)?(.*?)```"
    # Find all non-overlapping matches in the string
    matches = re.findall(pattern, input_string, re.DOTALL)

    # The regex above captures the content inside the triple backticks.
    # The `re.DOTALL` flag allows the dot `.` to match newline characters as well,
    # so the code inside backticks can span multiple lines.

    # matches now contains all the captured code snippets

    codes = []

    for match in matches:
        match = match.strip()
        commands = ['WAIT', 'DONE', 'FAIL']  # fixme: updates this part when we have more commands

        if match in commands:
            codes.append(match.strip())
        elif match.split('\n')[-1] in commands:
            if len(match.split('\n')) > 1:
                codes.append("\n".join(match.split('\n')[:-1]))
            codes.append(match.split('\n')[-1])
        else:
            codes.append(match)

    return codes


def parse_code_from_som_string(input_string, masks):
    # parse the output string by masks
    tag_vars = ""
    for i, mask in enumerate(masks):
        x, y, w, h = mask
        tag_vars += "tag_" + str(i + 1) + "=" + "({}, {})".format(int(x + w // 2), int(y + h // 2))
        tag_vars += "\n"

    actions = parse_code_from_string(input_string)

    for i, action in enumerate(actions):
        if action.strip() in ['WAIT', 'DONE', 'FAIL']:
            pass
        else:
            action = tag_vars + action
            actions[i] = action

    return actions


def trim_accessibility_tree(linearized_accessibility_tree, max_tokens):
    enc = tiktoken.encoding_for_model("gpt-4")
    tokens = enc.encode(linearized_accessibility_tree)
    if len(tokens) > max_tokens:
        linearized_accessibility_tree = enc.decode(tokens[:max_tokens])
        linearized_accessibility_tree += "[...]\n"
    return linearized_accessibility_tree


class PromptAgent:
    def __init__(
        self,
        platform="ubuntu",
        model="gpt-4-vision-preview",
        max_tokens=1500,
        top_p=0.9,
        temperature=0.5,
        action_space="computer_13",
        observation_type="screenshot_a11y_tree",
        # observation_type can be in ["screenshot", "a11y_tree", "screenshot_a11y_tree", "som"]
        max_trajectory_length=3,
        a11y_tree_max_tokens=10000
    ):
        self.platform = platform
        
        if "|" in model:
            self.model = model.split("|")[1].strip()
            self.provider = model.split("|")[0].strip()
        else:
            self.model = model
            self.provider = None

        assert self.provider is not None, "Provider can not be None. Currently, we only support the provider's API. If need to use the native API, you may need to modify the following parts: `set client`; `set system message`; `llm second call`"

        if self.provider == "azure":
            if self.model == "computer-use-preview":
                self.client = AzureOpenAI(
                    api_key=os.getenv("AZURE_API_KEY"),
                    api_version=os.getenv("AZURE_API_VERSION"),
                    azure_endpoint=os.getenv("AZURE_ENDPOINT"),
                    timeout=httpx.Timeout(60, read=60, write=60, connect=60)
                )
                self.cua = True
            elif self.model == "gpt-4o":
                self.client = AzureOpenAI(
                    api_key=os.getenv("AZURE_API_KEY"),
                    api_version=os.getenv("AZURE_API_VERSION"),
                    azure_endpoint=os.getenv("AZURE_ENDPOINT"),
                    timeout=httpx.Timeout(60, read=60, write=60, connect=60)
                )
                self.cua = False
            else:
                raise ValueError("Invalid model: " + self.provider + ": " + self.model)

        elif self.provider == "aws" and "anthropic" in self.model:
            if len(model.split("|")) == 3:
                self.cua = (model.split("|")[2].strip() == "cua")
            else:
                self.cua = False
                
            self.client = AnthropicBedrock(
                aws_region=os.getenv("AWS_REGION"),
                aws_access_key=os.getenv("AWS_ACCESS_KEY"),
                aws_secret_key=os.getenv("AWS_SECRET_KEY"),
            )
        
        else:
            self.client = None
            
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.action_space = action_space
        self.observation_type = observation_type
        self.max_trajectory_length = max_trajectory_length
        self.a11y_tree_max_tokens = a11y_tree_max_tokens

        self.thoughts = []
        self.actions = []
        self.observations = []

        # For OpenAI computer use
        self.response_ids = []
        self.call_ids = []

        # For claude computer use
        self.tool_use_ids = []
        self.claude_responses = []

        self.permission_check_config = False
        self.permission_check_in_last_step = False
        self.permission_check_cnt = 0

        self.safety_check_config = False
        self.safety_check_in_last_step = []
        self.safety_check_cnt = 0
        
        self.tool_call_in_last_step = False

        if observation_type == "screenshot":
            if action_space == "computer_13":
                self.system_message = SYS_PROMPT_IN_SCREENSHOT_OUT_ACTION
            elif action_space == "pyautogui":
                self.system_message = SYS_PROMPT_IN_SCREENSHOT_OUT_CODE
            else:
                raise ValueError("Invalid action space: " + action_space)
        elif observation_type == "a11y_tree":
            if action_space == "computer_13":
                self.system_message = SYS_PROMPT_IN_A11Y_OUT_ACTION
            elif action_space == "pyautogui":
                self.system_message = SYS_PROMPT_IN_A11Y_OUT_CODE
            else:
                raise ValueError("Invalid action space: " + action_space)
        elif observation_type == "screenshot_a11y_tree":
            if action_space == "computer_13":
                self.system_message = SYS_PROMPT_IN_BOTH_OUT_ACTION
            elif action_space == "pyautogui":
                self.system_message = SYS_PROMPT_IN_BOTH_OUT_CODE
            else:
                raise ValueError("Invalid action space: " + action_space)
        elif observation_type == "som":
            if action_space == "computer_13":
                raise ValueError("Invalid action space: " + action_space)
            elif action_space == "pyautogui":
                self.system_message = SYS_PROMPT_IN_SOM_OUT_TAG
            else:
                raise ValueError("Invalid action space: " + action_space)
        else:
            raise ValueError("Invalid experiment type: " + observation_type)

    def predict(self, instruction: str, obs: Dict) -> List:
        """
        Predict the next action(s) based on the current observation.
        """
        
        # set system message
        if self.provider == "azure":
            if self.model == "computer-use-preview":
                system_message = SYS_PROMPT_FOR_COMPUTER_USE_AGENT  + "\nYou are asked to complete the following task: {}".format(instruction)

            elif self.model == "gpt-4o":
                system_message = self.system_message + SYS_PROMPT_ADDTIONAL + "\nYou are asked to complete the following task: {}".format(instruction)

        elif self.provider == "aws" and "anthropic" in self.model:
            if self.cua:
                system_message = SYS_PROMPT_FOR_COMPUTER_USE_AGENT  + "\nYou are asked to complete the following task: {}".format(instruction)

            else:
                system_message = self.system_message + SYS_PROMPT_ADDTIONAL + "\nYou are asked to complete the following task: {}".format(instruction)

        ### Defense System Message
        # system_message += SYS_DEFENSE_PROMPT
        # logger.info(system_message)
        
        # Prepare the payload for the API call
        messages = []
        masks = None

        messages.append({
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_message
                },
            ]
        })

        # Append trajectory
        assert len(self.observations) == len(self.actions) and len(self.actions) == len(self.thoughts) \
            , "The number of observations and actions should be the same."

        if len(self.observations) > self.max_trajectory_length:
            if self.max_trajectory_length == 0:
                _observations = []
                _actions = []
                _thoughts = []
            else:
                _observations = self.observations[-self.max_trajectory_length:]
                _actions = self.actions[-self.max_trajectory_length:]
                _thoughts = self.thoughts[-self.max_trajectory_length:]
        else:
            _observations = self.observations
            _actions = self.actions
            _thoughts = self.thoughts

        for previous_obs, previous_action, previous_thought in zip(_observations, _actions, _thoughts):

            # {{{1
            if self.observation_type == "screenshot_a11y_tree":
                _screenshot = previous_obs["screenshot"]
                _linearized_accessibility_tree = previous_obs["accessibility_tree"]

                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Given the screenshot and info from accessibility tree as below:\n{}\nWhat's the next step that you will do to help with the task?".format(
                                _linearized_accessibility_tree)
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_screenshot}",
                                "detail": "high"
                            }
                        }
                    ]
                })
            elif self.observation_type in ["som"]:
                _screenshot = previous_obs["screenshot"]

                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Given the tagged screenshot as below. What's the next step that you will do to help with the task?"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_screenshot}",
                                "detail": "high"
                            }
                        }
                    ]
                })
            elif self.observation_type == "screenshot":
                _screenshot = previous_obs["screenshot"]

                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Given the screenshot as below. What's the next step that you will do to help with the task?"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_screenshot}",
                                "detail": "high"
                            }
                        }
                    ]
                })
            elif self.observation_type == "a11y_tree":
                _linearized_accessibility_tree = previous_obs["accessibility_tree"]

                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Given the info from accessibility tree as below:\n{}\nWhat's the next step that you will do to help with the task?".format(
                                _linearized_accessibility_tree)
                        }
                    ]
                })
            else:
                raise ValueError("Invalid observation_type type: " + self.observation_type)  # 1}}}

            messages.append({
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": previous_thought.strip() if len(previous_thought) > 0 else "No valid action"
                    },
                ]
            })

        # {{{1
        if self.observation_type in ["screenshot", "screenshot_a11y_tree"]:
            base64_image = encode_image(obs["screenshot"])
            linearized_accessibility_tree = linearize_accessibility_tree(accessibility_tree=obs["accessibility_tree"],
                                                                         platform=self.platform) if self.observation_type == "screenshot_a11y_tree" else None
            # logger.debug("LINEAR AT: %s", linearized_accessibility_tree)

            if linearized_accessibility_tree:
                linearized_accessibility_tree = trim_accessibility_tree(linearized_accessibility_tree,
                                                                        self.a11y_tree_max_tokens)

            if self.observation_type == "screenshot_a11y_tree":
                self.observations.append({
                    "screenshot": base64_image,
                    "accessibility_tree": linearized_accessibility_tree
                })
            else:
                self.observations.append({
                    "screenshot": base64_image,
                    "accessibility_tree": None
                })

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Given the screenshot as below. What's the next step that you will do to help with the task?"
                        if self.observation_type == "screenshot"
                        else "Given the screenshot and info from accessibility tree as below:\n{}\nWhat's the next step that you will do to help with the task?".format(
                            linearized_accessibility_tree)
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high"
                        }
                    }
                ]
            })
        elif self.observation_type == "a11y_tree":
            linearized_accessibility_tree = linearize_accessibility_tree(accessibility_tree=obs["accessibility_tree"],
                                                                         platform=self.platform)
            logger.debug("LINEAR AT: %s", linearized_accessibility_tree)

            if linearized_accessibility_tree:
                linearized_accessibility_tree = trim_accessibility_tree(linearized_accessibility_tree,
                                                                        self.a11y_tree_max_tokens)

            self.observations.append({
                "screenshot": None,
                "accessibility_tree": linearized_accessibility_tree
            })

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Given the info from accessibility tree as below:\n{}\nWhat's the next step that you will do to help with the task?".format(
                            linearized_accessibility_tree)
                    }
                ]
            })
        elif self.observation_type == "som":
            # Add som to the screenshot
            masks, drew_nodes, tagged_screenshot, linearized_accessibility_tree = tag_screenshot(obs["screenshot"], obs[
                "accessibility_tree"], self.platform)
            base64_image = encode_image(tagged_screenshot)
            logger.debug("LINEAR AT: %s", linearized_accessibility_tree)

            if linearized_accessibility_tree:
                linearized_accessibility_tree = trim_accessibility_tree(linearized_accessibility_tree,
                                                                        self.a11y_tree_max_tokens)

            self.observations.append({
                "screenshot": base64_image,
                "accessibility_tree": linearized_accessibility_tree
            })

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Given the tagged screenshot and info from accessibility tree as below:\n{}\nWhat's the next step that you will do to help with the task?".format(
                            linearized_accessibility_tree)
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high"
                        }
                    }
                ]
            })
        else:
            raise ValueError("Invalid observation_type type: " + self.observation_type)  # 1}}}

        # with open("messages.json", "w") as f:
        #     f.write(json.dumps(messages, indent=4))

        # logger.info("PROMPT: %s", messages)
        response_second = None
        
        try:
            response_first = self.call_llm({
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "top_p": self.top_p,
                "temperature": self.temperature,
                "observation_type": self.observation_type,
            })
            
            # second call to convert the CUA's response into the pyautogui actions.
            if self.provider == "azure":
                if self.model == "computer-use-preview":
                    response_second = self.convert_to_pyautogui(response_first)
                
            elif self.provider == "aws":
                # TODO coordinate out of bound
                if self.cua:
                    for block in response_first:
                        if block.type == "tool_use" and "coordinate" in block.input:
                            block = adjust_coordinates_from_response(response = block)
                            logger.info(f"Step {len(self.observations)} adjust coordinates ")
                    response_second = self.convert_to_pyautogui(response_first)

        except Exception as e:
            logger.error("Failed to call " + self.model + ", Error: " + str(e))
            response = ""
            
        saved_response_path = os.path.join(self.example_result_dir,"response.json")

        if os.path.exists(saved_response_path):
            with open(saved_response_path, "r") as f:
                try:
                    all_data = json.load(f)
                except json.JSONDecodeError:
                    all_data = []
        else:
            all_data = []

        current_entry = next((item for item in all_data if item["step_idx"] == self.step_idx), None)

        if not current_entry:
            current_entry = {
                "step_idx": self.step_idx,
                "rounds_to_call": {}
            }
            all_data.append(current_entry)

        response = response_first
        logger.info("[RESPONSE_FIRST]: %s", response)
        logger.info("\n\n")
        current_entry["rounds_to_call"]["first"] = str(response)

        if response_second:
            response = response_second
            logger.info("[RESPONSE_SECOND]: %s", response)
            logger.info("\n\n")
            current_entry["rounds_to_call"]["second"] = str(response)

        with open(saved_response_path, "w") as f:
            json.dump(all_data, f, indent=4)
                
        try:
            actions = self.parse_actions(response, masks)
            self.thoughts.append(response)
        except ValueError as e:
            print("Failed to parse action from response", e)
            actions = None
            self.thoughts.append("")

        return response, actions, self.tool_call_in_last_step



    @backoff.on_exception(
        backoff.constant,
        # here you should add more model exceptions as you want,
        # but you are forbidden to add "Exception", that is, a common type of exception
        # because we want to catch this kind of Exception in the outside to ensure each example won't exceed the time limit
        (
                # General exceptions
                SSLError,

                # OpenAI exceptions
                openai.RateLimitError,
                openai.BadRequestError,
                openai.InternalServerError,

                # Google exceptions
                InvalidArgument,
                ResourceExhausted,
                InternalServerError,
                BadRequest,

                # Groq exceptions
                # todo: check
        ),
        interval=30,
        max_tries=10
    )
    def call_llm(self, payload):
        self.tool_call_in_last_step = False

        if self.provider is not None:
            if self.provider == "azure":  
                if self.model == "computer-use-preview":
                    # openai
                    previous_response_id = self.response_ids[-1] if len(self.response_ids) > 0 else ""
                    last_call_id = self.call_ids[-1] if len(self.call_ids) > 0 else ""
                    
                    logger.info(f"all inputs:")
                    # logger.info(f"payload: {payload}")
                    logger.info(f"last_call_id: {last_call_id}")
                    logger.info(f"previous_response_id: {previous_response_id}")
                    logger.info(f"permission_check_in_last_step: {self.permission_check_in_last_step}")
                    logger.info(f"safety_check_in_last_step: {self.safety_check_in_last_step}")

                    if not previous_response_id:
                        # so this is ensured that it's the first call.
                        response = self.client.responses.create(
                            model="computer-use-preview",
                            tools=[{
                                "type": "computer_use_preview",
                                "display_width": 1920,
                                "display_height": 1080,
                                "environment": "linux" # other possible values: "mac", "windows", "ubuntu"
                            }],
                            reasoning={
                                "generate_summary": "concise",
                            },
                            truncation="auto",
                            input = convert_for_openai_cua(payload, last_call_id, self.permission_check_in_last_step, self.safety_check_in_last_step, first_time_call=True)
                        )

                    else:
                        response = self.client.responses.create(
                            model="computer-use-preview",
                            previous_response_id=previous_response_id,
                            tools=[{
                                "type": "computer_use_preview",
                                "display_width": 1920,
                                "display_height": 1080,
                                "environment": "linux" # other possible values: "mac", "windows", "ubuntu"
                            }],
                            reasoning={
                                "generate_summary": "concise",
                            },
                            truncation="auto",
                            input = convert_for_openai_cua(payload, last_call_id, self.permission_check_in_last_step, self.safety_check_in_last_step, first_time_call=False)
                        )
                    
                    # logger.info('convert_for_openai_cua output:')
                    # logger.info(convert_for_openai_cua(payload, last_call_id, self.permission_check_in_last_step, self.safety_check_in_last_step, first_time_call=False))
                        
                    self.response_ids.append(response.id)
                    self.permission_check_in_last_step = False
                    self.safety_check_in_last_step = []
                    
                    logger.info(f"Step {len(self.observations)}\n[FIRST CALL]: {response.output}")

                    computer_calls = [item for item in response.output if item.type == "computer_call"]
                    if computer_calls:
                        self.call_ids.append(computer_calls[0].call_id)

                    return response.output
                
                elif self.model == "gpt-4o":
                    logger.info("Generating content with GPT model: %s", self.model)

                    payload.pop("observation_type", None)

                    response = self.client.chat.completions.create(**payload)
                    return response.choices[0].message.content
                
                else:
                    raise ValueError("Invalid model: " + self.provider + ": " + self.model)


            elif self.provider == "aws":
                if self.cua:
                    # with tool_use
                    tools = {
                        "us.anthropic.claude-3-5-sonnet-20241022-v2:0": [
                            {
                                "type": "computer_20241022",
                                "name": "computer",
                                "display_width_px": 1366,
                                "display_height_px": 768
                            },
                            {
                                "type": "text_editor_20241022",
                                "name": "str_replace_editor"
                            },
                            {
                                "type": "bash_20241022",
                                "name": "bash"
                            }
                        ],
                        "us.anthropic.claude-3-7-sonnet-20250219-v1:0": [
                            {
                                "type": "computer_20250124",
                                "name": "computer",
                                "display_width_px": 1366,
                                "display_height_px": 768
                            },
                            {
                                "type": "text_editor_20250124",
                                "name": "str_replace_editor"
                            },
                            {
                                "type": "bash_20250124",
                                "name": "bash"
                            }
                        ],
                        "us.anthropic.claude-opus-4-20250514-v1:0": [
                            {
                                "type": "computer_20250124",
                                "name": "computer",
                                "display_width_px": 1366,
                                "display_height_px": 768
                            },
                            {
                                "type": "text_editor_20250429",
                                "name": "str_replace_based_edit_tool"
                            },
                            {
                                "type": "bash_20250124",
                                "name": "bash"
                            }
                        ]
                    }
                        
                    if len(self.claude_responses) > self.max_trajectory_length:
                        if self.claude_responses == 0:
                            claude_responses = []
                            tool_use_ids = []
                        else:
                            claude_responses = self.claude_responses[-self.max_trajectory_length:]
                            tool_use_ids = self.tool_use_ids[-self.max_trajectory_length:]

                    else:
                        claude_responses = self.claude_responses
                        tool_use_ids = self.tool_use_ids

                    assert len([msg for msg in payload["messages"] if msg["role"] == "assistant"]) == len(claude_responses), "assistant messages and claude responses don't match!"

                    claude_messages = convert_for_claude_cua(payload, claude_responses, tool_use_ids)

                    create_args = {
                        "model": self.model,
                        "max_tokens": self.max_tokens,
                        "messages": claude_messages,
                        "tools": tools[self.model],
                    }

                    if self.model == "us.anthropic.claude-3-5-sonnet-20241022-v2:0":
                        create_args["betas"] = ["computer-use-2024-10-22"]
                    else:
                        create_args["betas"] = ["computer-use-2025-01-24"]
                        create_args["thinking"] = {"type": "enabled", "budget_tokens": 1024} 

                    response = self.client.beta.messages.create(**create_args)

                    logger.info(f"Step {len(self.observations)}\n[FIRST CALL]: {response.content}")

                    self.claude_responses.append(response.content)

                    tool_results = [block for block in response.content if block.type == "tool_use"]

                    tool_result_list = []
                    for tool_result in tool_results:
                        tool_result_list.append(tool_result.id)
                        self.tool_call_in_last_step = True

                    self.tool_use_ids.append(tool_result_list)

                    return response.content
                
                else:
                    # without tool_use
                    messages = payload["messages"]
                    max_tokens = payload["max_tokens"]
                    top_p = payload["top_p"]
                    temperature = payload["temperature"]

                    claude_messages = []

                    for i, message in enumerate(messages):
                        claude_message = {
                            "role": message["role"],
                            "content": []
                        }
                        assert len(message["content"]) in [1, 2], "One text, or one text with one image"
                        for part in message["content"]:

                            if part['type'] == "image_url":
                                image_source = {}
                                image_source["type"] = "base64"
                                image_source["media_type"] = "image/png"
                                image_source["data"] = part['image_url']['url'].replace("data:image/png;base64,", "")
                                claude_message['content'].append({"type": "image", "source": image_source})

                            if part['type'] == "text":
                                claude_message['content'].append({"type": "text", "text": part['text']})

                        claude_messages.append(claude_message)

                    # the claude not support system message in our endpoint, so we concatenate it at the first user message
                    if claude_messages[0]['role'] == "system":
                        claude_system_message_item = claude_messages[0]['content'][0]
                        claude_messages[1]['content'].insert(0, claude_system_message_item)
                        claude_messages.pop(0)

                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=max_tokens,
                        messages=claude_messages,
                        # thinking={"type": "enabled", "budget_tokens": 1024}
                    )

                    return response.content[0].text
                
            else:
                raise ValueError("Invalid provider: " + self.provider)

        else:
            logger.error("")
            raise ValueError("Invalid provider: " + self.provider)



    # second call
    def convert_to_pyautogui(self, first_call_response):
        if self.provider == "azure":
            if self.model == "computer-use-preview":
                client = AzureOpenAI(
                    api_key=os.getenv("AZURE_API_KEY"),
                    api_version=os.getenv("AZURE_API_VERSION_FOR_SECOND_CALL"),
                    azure_endpoint=os.getenv("AZURE_ENDPOINT_FOR_SECOND_CALL"),
                    timeout=httpx.Timeout(60, read=60, write=60, connect=60)
                )

                #TODO,
                # should change accordingly given the choice of the model used in the first time. e.g. if the model is claude, then the prompt should be `SYS_PROMPT_FOR_Claude_SECOND_CALL`. Besides, the script need to be changed accordingly as well, for exmaple, how to call the tool.
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": SYS_PROMPT_FOR_OPENAI_SECOND_CALL},
                        {"role": "user", "content": str(first_call_response)}
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "reponse",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "is_permission_request": { "type": "boolean" },
                                    "python_code": { "type": "string" }
                                },
                                "required": ["is_permission_request", "python_code"],
                                "additionalProperties": False
                            },
                            "strict": True
                        }
                    }
                )

                second_call_response = json.loads(response.choices[0].message.content)
                logger.info(f"Step {len(self.observations)}\n[SECOND CALL]: {second_call_response}")

                if second_call_response["is_permission_request"]:
                    self.permission_check_cnt += 1
                    
                    computer_calls = [item for item in first_call_response if item.type == "computer_call"]
                    
                    if computer_calls:
                        self.tool_call_in_last_step = True
                        if len(computer_calls[0].pending_safety_checks) > 0:
                            self.safety_check_cnt += 1
                            if self.safety_check_config:
                                for it in computer_calls[0].pending_safety_checks:
                                    self.safety_check_in_last_step.append({
                                        "id": it.id,
                                        "code": it.code,
                                        "message": it.message
                                    })
                            else:
                                return "Without user safety check\n\n```FAIL```"
                        
                    if self.permission_check_config:
                        self.permission_check_in_last_step = True
                        return "```python\nimport time\n\ntime.sleep(1)```"
                    else:
                        self.permission_check_in_last_step = False
                        return "Without user permission\n\n```FAIL```"

                else: 
                    computer_calls = [item for item in first_call_response if item.type == "computer_call"]
                    
                    
                    if not computer_calls:
                        # Return the message content as response
                        message = [item for item in first_call_response if item.type == "message"]
                        if len(message) > 0:
                            return message[0].content[0].text + "\n\n```DONE```"
                        else:
                            return "```FAIL```"
                    
                    self.tool_call_in_last_step = True
                    
                    if len(computer_calls[0].pending_safety_checks) > 0:
                        self.safety_check_cnt += 1
                        if self.safety_check_config:
                            for it in computer_calls[0].pending_safety_checks:
                                self.safety_check_in_last_step.append({
                                    "id": it.id,
                                    "code": it.code,
                                    "message": it.message
                                })
                        else:
                            return "Without user safety check\n\n```FAIL```"
                    
                    if not second_call_response["python_code"].startswith("```python"):
                        second_call_response["python_code"] = "```python\n" + second_call_response["python_code"] + "\n```"

                    idx = second_call_response["python_code"].rfind("```")
                    if idx != -1:
                        added_code = second_call_response["python_code"][:idx] + "\ntime.sleep(5)\n" + second_call_response["python_code"][idx:]
                        second_call_response["python_code"] = added_code
                    return second_call_response["python_code"]
                
        elif self.provider == "aws":
            if self.cua:
                tool_results = [block for block in first_call_response if block.type == "tool_use"]
                if not tool_results:
                    text_results = [block for block in first_call_response if block.type == "text"]

                    if not text_results:
                        logger.error("No message response when task is done!")
                        return "No message response when task is done!\n\n```FAIL```"

                    return text_results[0].text + "```DONE```"

                client = AnthropicBedrock(
                    aws_region=os.getenv("AWS_REGION"),
                    aws_access_key=os.getenv("AWS_ACCESS_KEY"),
                    aws_secret_key=os.getenv("AWS_SECRET_KEY"),
                )

                response = self.client.beta.messages.create(
                    model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": SYS_PROMPT_FOR_CLAUDE_SECOND_CALL + '\n' + str(tool_results[0])}],
                    thinking={"type": "enabled", "budget_tokens": 1024}
                )

                logger.info(f"Step {len(self.observations)}\n[SECOND CALL]: {response.content}")

                text_results = [block for block in response.content if block.type == "text"]

                if not text_results:
                    logger.error("No message response in claude second call!")
                    return "No message response in claude second call!\n\n```FAIL```"

                idx = text_results[0].text.rfind("```")
                if idx != -1:
                    added_code = text_results[0].text[:idx] + "\ntime.sleep(5)\n" + text_results[0].text[idx:]
                    text_results[0].text = added_code

                return text_results[0].text

        else:
            logger.error("Invalid model in second call!")
            return "Invalid model in second call!\n\n```FAIL```"       


    def parse_actions(self, response: str, masks=None):

        if self.observation_type in ["screenshot", "a11y_tree", "screenshot_a11y_tree"]:
            # parse from the response
            if self.action_space == "computer_13":
                actions = parse_actions_from_string(response)
            elif self.action_space == "pyautogui":
                actions = parse_code_from_string(response)
            else:
                raise ValueError("Invalid action space: " + self.action_space)

            self.actions.append(actions)

            return actions
        elif self.observation_type in ["som"]:
            # parse from the response
            if self.action_space == "computer_13":
                raise ValueError("Invalid action space: " + self.action_space)
            elif self.action_space == "pyautogui":
                actions = parse_code_from_som_string(response, masks)
            else:
                raise ValueError("Invalid action space: " + self.action_space)

            self.actions.append(actions)

            return actions

    def reset(self, tags, _logger=None):
        global logger
        logger = _logger if _logger is not None else logging.getLogger("desktopenv.agent")

        self.thoughts = []
        self.actions = []
        self.observations = []

        self.response_ids = []
        self.call_ids = []

        self.tool_use_ids = []
        self.claude_responses = []

        self.permission_check_config = tags["permission_check"]
        self.permission_check_in_last_step = False
        self.permission_check_cnt = 0

        self.safety_check_config = tags["safety_check"] 
        self.safety_check_in_last_step = []
        self.safety_check_cnt = 0


        if self.provider == "azure":
            if self.model == "computer-use-preview":
                self.client = AzureOpenAI(
                    api_key=os.getenv("AZURE_API_KEY"),
                    api_version=os.getenv("AZURE_API_VERSION"),
                    azure_endpoint=os.getenv("AZURE_ENDPOINT"),
                    timeout=httpx.Timeout(60, read=60, write=60, connect=60)
                )
            elif self.model == "gpt-4o":
                self.client = AzureOpenAI(
                    api_key=os.getenv("AZURE_API_KEY"),
                    api_version=os.getenv("AZURE_API_VERSION"),
                    azure_endpoint=os.getenv("AZURE_ENDPOINT"),
                    timeout=httpx.Timeout(60, read=60, write=60, connect=60)
                )
            else:
                raise ValueError("Invalid model: " + self.provider + ": " + self.model)

        elif self.provider == "aws" and "anthropic" in self.model:
            self.client = AnthropicBedrock(
                aws_region=os.getenv("AWS_REGION"),
                aws_access_key=os.getenv("AWS_ACCESS_KEY"),
                aws_secret_key=os.getenv("AWS_SECRET_KEY"),
            )
        
        else:
            self.client = None