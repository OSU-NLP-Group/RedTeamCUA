from copy import deepcopy
from mm_agents.prompts import PROMPT_FOR_COUNTERING_PERMISSION_REQUEST
from termcolor import cprint

# to_return can be "image" or "image_and_text"
def convert_for_openai_cua_utlis_1(messages, use_last=False, to_return="image"):
    to_return_l = []

    for idx, message in enumerate(messages):

        if use_last:
            if idx != len(messages) - 1:
                continue

        for content in message["content"]:
            if to_return == "image_and_text":
                if content["type"] == "text":
                    content["type"] = "input_text"
                elif content["type"] == "image_url":
                    content["type"] = "input_image"
                    content["image_url"] = content["image_url"]["url"]

        if to_return == "image_and_text":
            to_return_l.append(message)

        elif to_return == "image":
            filtered_list = [
                item for item in message if item.get("type") != "input_text"
            ]
            to_return_l.append(filtered_list)

    return to_return_l


def convert_for_openai_cua(
    _payload,
    last_call_id,
    permission_check_message,
    safety_check_message,
    first_time_call,
):

    if first_time_call:
        # if it's the first time to call llm. then we should ensure that the system message is included.
        payload = deepcopy(_payload)
        assert (
            payload["messages"][0]["role"] == "system"
        ), "The first message should be a system message"
        payload["messages"][0]["role"] = "developer"

        for message in payload["messages"]:
            for content in message["content"]:
                if content["type"] == "text":
                    content["type"] = "input_text"
                elif content["type"] == "image_url":
                    content["type"] = "input_image"
                    content["image_url"] = content["image_url"]["url"]

        return payload["messages"]

    else:
        assert _payload["observation_type"] in [
            "screenshot",
            "screenshot_a11y_tree",
        ], " We are using CUA models which mainly use screenshots as observations."
        if permission_check_message is True:

            if not last_call_id:
                return [
                    # {
                    #     "type": "output_text",
                    #     "output": "Please continue to finish the assigned task. If you feel the task is done, please don't ask for permission, clarification, confirmation, or prompt user for next instructions anymore. Just directly say that the `task is finished`."
                    # }
                    {
                        "role": "user",
                        "content": (
                            PROMPT_FOR_COUNTERING_PERMISSION_REQUEST
                            if _payload["observation_type"] == "screenshot"
                            else _payload["messages"][-1]["content"][0]["text"]
                            + "\n\n"
                            + PROMPT_FOR_COUNTERING_PERMISSION_REQUEST
                        ),
                    }
                ]
            else:
                return [
                    {
                        "role": "user",
                        "content": (
                            PROMPT_FOR_COUNTERING_PERMISSION_REQUEST
                            if _payload["observation_type"] == "screenshot"
                            else _payload["messages"][-1]["content"][0]["text"]
                            + "\n\n"
                            + PROMPT_FOR_COUNTERING_PERMISSION_REQUEST
                        ),
                    },
                    (
                        {
                            "type": "computer_call_output",
                            "call_id": last_call_id,
                            "output": {
                                "type": "input_image",
                                "image_url": _payload["messages"][-1]["content"][1][
                                    "image_url"
                                ]["url"],
                            },
                        }
                        if len(safety_check_message) == 0
                        else {
                            "type": "computer_call_output",
                            "call_id": last_call_id,
                            "acknowledged_safety_checks": safety_check_message,
                            "output": {
                                "type": "input_image",
                                "image_url": _payload["messages"][-1]["content"][1][
                                    "image_url"
                                ]["url"],
                            },
                        }
                    ),
                ]

        else:
            # permission_check_message = False, which means that the `permission` is not triggered.
            if _payload["observation_type"] == "screenshot":
                return [
                    (
                        {
                            "type": "computer_call_output",
                            "call_id": last_call_id,
                            "output": {
                                "type": "input_image",
                                "image_url": _payload["messages"][-1]["content"][1][
                                    "image_url"
                                ]["url"],
                            },
                        }
                        if len(safety_check_message) == 0
                        else {
                            "type": "computer_call_output",
                            "call_id": last_call_id,
                            "acknowledged_safety_checks": safety_check_message,
                            "output": {
                                "type": "input_image",
                                "image_url": _payload["messages"][-1]["content"][1][
                                    "image_url"
                                ]["url"],
                            },
                        }
                    )
                ]
            else:
                # a11y tree + screenshot
                return [
                    {
                        "role": "user",
                        "content": _payload["messages"][-1]["content"][0]["text"],
                    },
                    (
                        {
                            "type": "computer_call_output",
                            "call_id": last_call_id,
                            "output": {
                                "type": "input_image",
                                "image_url": _payload["messages"][-1]["content"][1][
                                    "image_url"
                                ]["url"],
                            },
                        }
                        if len(safety_check_message) == 0
                        else {
                            "type": "computer_call_output",
                            "call_id": last_call_id,
                            "acknowledged_safety_checks": safety_check_message,
                            "output": {
                                "type": "input_image",
                                "image_url": _payload["messages"][-1]["content"][1][
                                    "image_url"
                                ]["url"],
                            },
                        }
                    ),
                ]


def convert_for_claude_cua(_payload, claude_responses, tool_use_ids):
    messages = _payload["messages"]
    claude_messages = []

    it = 0
    for message in messages:
        if message["role"] == "assistant":
            assert (
                message["content"][0]["type"] == "text"
            ), "role assistant content type error!"

            claude_messages.append(
                {"role": message["role"], "content": claude_responses[it]}
            )

            
            claude_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "Tool executed successfully",
                        } for tool_use_id in tool_use_ids[it]
                    ],
                }
            )

            it += 1

        else:
            claude_message = {"role": message["role"], "content": []}

            for part in message["content"]:
                if part["type"] == "image_url":
                    image_source = {}
                    image_source["type"] = "base64"
                    image_source["media_type"] = "image/png"
                    image_source["data"] = part["image_url"]["url"].replace(
                        "data:image/png;base64,", ""
                    )

                    img = decode_image(image_source["data"])

                    screenshot_width = 1920
                    screenshot_height = 1080
                    resized_width, resized_height = scale_coordinates(
                        source="Computer",
                        x=screenshot_width,
                        y=screenshot_height,
                        width=screenshot_width,
                        height=screenshot_height,
                    )

                    # resized_screenshot is the one should be input to the Agent.
                    resized_screenshot = resize_screenshot(
                        img, resized_width, resized_height
                    )
                    image_source["data"] = encode_image(resized_screenshot)

                    claude_message["content"].append(
                        {"type": "image", "source": image_source}
                    )

                if part["type"] == "text":
                    claude_message["content"].append(
                        {"type": "text", "text": part["text"]}
                    )

            claude_messages.append(claude_message)

    # the claude not support system message in our endpoint, so we concatenate it at the first user message
    if claude_messages[0]["role"] == "system":
        claude_system_message_item = claude_messages[0]["content"][0]
        claude_messages[1]["content"].insert(0, claude_system_message_item)
        claude_messages.pop(0)

    return claude_messages


from typing import Literal, TypedDict, cast, get_args
from PIL import Image, ImageDraw, ImageFont


class Resolution(TypedDict):
    width: int
    height: int


import io

MAX_SCALING_TARGETS: dict[str, Resolution] = {
    "XGA": Resolution(width=1024, height=768),  # 4:3
    "WXGA": Resolution(width=1280, height=800),  # 16:10
    "FWXGA": Resolution(width=1366, height=768),  # ~16:9
}


def scale_coordinates(source, x: int, y: int, width: int = 1920, height: int = 1080):
    """Scale coordinates to a target maximum resolution."""
    _scaling_enabled = True
    if not _scaling_enabled:
        return x, y
    ratio = width / height
    target_dimension = None
    for dimension in MAX_SCALING_TARGETS.values():
        # allow some error in the aspect ratio - not ratios are exactly 16:9
        if abs(dimension["width"] / dimension["height"] - ratio) < 0.02:
            if dimension["width"] < width:
                target_dimension = dimension
            break
    if target_dimension is None:
        return x, y
    # should be less than 1
    x_scaling_factor = target_dimension["width"] / width
    y_scaling_factor = target_dimension["height"] / height
    if source == "API":
        if x > width or y > height:
            # raise ValueError(f"Coordinates {x}, {y} are out of bounds")
            cprint(f"Coordinates {x}, {y} are out of bounds. Here, we simply cut the coordinates to the boundary.", "red")
            x = min(x, width)
            y = min(y, height)
            cprint(f"The scaled coordinates (after scaling) are {x / x_scaling_factor}, {y / y_scaling_factor}. Note that they are obviously out of bounds because of the models' limited grounding capability.", "red")
        # scale up
        return round(x / x_scaling_factor), round(y / y_scaling_factor)
    elif source == "Computer":
        return round(x * x_scaling_factor), round(y * y_scaling_factor)
    else:
        raise ValueError(f"Invalid source {source}")


def resize_screenshot(screenshot, width, height):
    """Resize a screenshot to a target resolution."""
    image_stream = io.BytesIO(screenshot)
    image = Image.open(image_stream)
    image = image.resize((int(width), int(height)))

    # Convert back to bytes
    output_stream = io.BytesIO()
    image.save(output_stream, format=image.format or "PNG")
    return output_stream.getvalue()


# ensure the response is the one with `tool_used.`
def adjust_coordinates_from_response(response, width=1920, height=1080):
    """Adjust coordinates from a response to the target resolution."""

    if isinstance(response.input["coordinate"], list):
        x, y = response.input["coordinate"]
    elif isinstance(response.input["coordinate"], str):
        x, y = response.input["coordinate"].split(",")
        import re

        x_match = re.search(r"\d+", x)
        x = int(x_match.group())
        y_match = re.search(r"\d+", y)
        y = int(y_match.group())
    else:
        raise ValueError("Invalid coordinate format")

    adjusted_x, adjusted_y = scale_coordinates(
        source="API", x=x, y=y, width=width, height=height
    )
    response.input["coordinate"] = [adjusted_x, adjusted_y]
    return response


import base64


def decode_image(encoded_content):
    return base64.b64decode(encoded_content)


def encode_image(image_content):
    return base64.b64encode(image_content).decode("utf-8")
