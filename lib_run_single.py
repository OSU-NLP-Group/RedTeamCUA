import inspect
import datetime
import json
import logging
import os
import time
from wrapt_timeout_decorator import *

logger = logging.getLogger("desktopenv.experiment")


def find_after_first_non_false(listA, listB):

    if len(listA) != len(listB):
        raise ValueError("Both lists must have the same length")
    
    found_index = -1
    for i in range(len(listA) - 1, -1, -1):
        if listB[i] is not False:
            found_index = i
            break
    if found_index == -1:
        return []
    return "\n".join(listA[found_index + 1:])


def index_of_false_after_last_true(lst):
    last_true_index = -1
    for i in range(len(lst) - 1, -1, -1):
        if lst[i] is True:
            last_true_index = i
            break
    if last_true_index == -1 or last_true_index + 1 >= len(lst):
        return -1
    if lst[last_true_index + 1] is False:
        return last_true_index + 1
    return -1

def if_cua(model_name):
    if "cua" in model_name:
        return True
    elif "computer-use-preview" in model_name:
        return True
    else:
        return False

def run_single_example(agent, agent_type, env, example, max_steps, instruction, args, example_result_dir, scores):
    runtime_logger = setup_logger(example, example_result_dir)
    sig = inspect.signature(agent.reset)
    if len(sig.parameters) == 0:
        agent.reset()
    else:
        agent.reset(tags = example["tags"], _logger = runtime_logger)
    agent.example_result_dir = example_result_dir
    env.prepare_injection(task_config=example)
    obs = env._get_obs() # Get the initial observation
    action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
    with open(os.path.join(example_result_dir, f"step_0_{action_timestamp}.png"), "wb") as _f:
        _f.write(obs['screenshot'])
    done = False
    step_idx = 0
    env.controller.start_recording()
    # for recording
    # time.sleep(30)


    tool_call_is_triggered_l = []
    while not done and step_idx < max_steps:
        agent.step_idx = step_idx + 1
        response, actions, tool_call_is_triggered = agent.predict(
            instruction,
            obs
        )

        tool_call_is_triggered_l.append(tool_call_is_triggered)
        
        for action in actions:
            # Capture the timestamp before executing the action
            action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
            logger.info("Step %d: %s", step_idx + 1, action)
            obs, reward, done, info = env.step(action, args.sleep_after_execution)

            logger.info("Reward: %.2f", reward)
            logger.info("Done: %s", done)
            # Save screenshot and trajectory information
            with open(os.path.join(example_result_dir, f"step_{step_idx + 1}_{action_timestamp}.png"),
                      "wb") as _f:
                _f.write(obs['screenshot'])
            with open(os.path.join(example_result_dir, "traj.jsonl"), "a") as f:
                f.write(json.dumps({
                    "step_num": step_idx + 1,
                    "action_timestamp": action_timestamp,
                    "action": action,
                    "reward": reward,
                    "done": done,
                    "info": info,
                    "screenshot_file": f"step_{step_idx + 1}_{action_timestamp}.png"
                }))
                f.write("\n")
            if done:
                logger.info("The episode is done.")
                break
        step_idx += 1
    
    
    if agent.cua:
        response = ""
        with open(os.path.join(example_result_dir, "response.json")) as f:
            saved_responses = json.load(f)
            
            _index_of_first_false_after_last_true = index_of_false_after_last_true(tool_call_is_triggered_l)
            
            for index_saved_response, saved_response in enumerate(saved_responses):
                if index_saved_response < _index_of_first_false_after_last_true:
                    continue
                response += f"Result of the Computer Use Agent call at step {index_saved_response}:" + saved_response["rounds_to_call"]["first"] + "\n\n"
        
        
    # last_several_responses = find_after_first_non_false(responses_l, tool_call_is_triggered_l)
    
    result = env.evaluate(response)
    logger.info("Result: %.2f", result)
    scores.append(result)
    with open(os.path.join(example_result_dir, "result.txt"), "w", encoding="utf-8") as f:
        f.write(f"{result}\n")

    adversary_result = env.adversary_evaluate()
    logger.info("Adversary Result: %.2f", adversary_result)
    with open(os.path.join(example_result_dir, "adversary_result.txt"), "w", encoding="utf-8") as f:
        f.write(f"{adversary_result}\n")

    with open(os.path.join(example_result_dir, "check.json"), "w", encoding="utf-8") as f:
        if agent_type == "PromptAgent":
            json.dump({
                "permission_check_cnt": agent.permission_check_cnt,
                "safety_check_cnt": agent.safety_check_cnt
            }, f, indent=4)
        else:
            json.dump({
                "safety_check_cnt": agent.safety_check_cnt
            }, f, indent=4)
                
    with open(os.path.join(example_result_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(example, f, indent=4)
    env.controller.end_recording(os.path.join(example_result_dir, "recording.mp4"))


def setup_logger(example, example_result_dir):
    runtime_logger = logging.getLogger(f"desktopenv.example.{example['id']}")
    runtime_logger.setLevel(logging.DEBUG)
    runtime_logger.addHandler(logging.FileHandler(os.path.join(example_result_dir, "runtime.log")))
    return runtime_logger
