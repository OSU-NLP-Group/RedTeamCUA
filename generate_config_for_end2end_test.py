import argparse
import os
import json
import re
import copy

from collections.abc import Mapping

def deep_update(dst: dict, src: Mapping) -> None:
    """
    Recursively merge keys from `src` into `dst` in-place.
    If the same key exists and both values are dicts, merge them deeper;
    otherwise overwrite `dst[key]` with `src[key]`.
    """
    for k, v in src.items():
        if isinstance(v, Mapping) and isinstance(dst.get(k), Mapping):
            deep_update(dst[k], v)
        else:
            dst[k] = v

def sub_url(url: str, target_url: str = ""):
    url =  re.sub(r"__REDDIT__", r"TO_BE_REPLACED_URL" + ":9999", url)
    url =  re.sub(r"__ROCKETCHAT__", r"TO_BE_REPLACED_URL" + ":3000", url)
    url =  re.sub(r"__OWNCLOUD__", r"TO_BE_REPLACED_URL" + ":8092", url)
    url =  re.sub(r"__TARGET_URL__", target_url, url)
    return url

def replace_in_dict(data, target_url: str = ""):
    if isinstance(data, dict):
        return {key: replace_in_dict(val, target_url) for key, val in data.items()}
    elif isinstance(data, list):
        return [replace_in_dict(item, target_url) for item in data]
    elif isinstance(data, tuple):
        return tuple(replace_in_dict(item, target_url) for item in data)
    elif isinstance(data, str):
        return sub_url(data, target_url)
    else:
        return data


def create_config(benign_task_raw, adversary_task_raw, output_path):
    try:
        with open(f"{output_path}/test_all_owncloud_for_end2end.json", "r") as f:
            owncloud_config_dict = json.load(f)
    except:
        owncloud_config_dict = {}

    try:
        with open(f"{output_path}/test_all_reddit_for_end2end.json", "r") as f:
            reddit_config_dict = json.load(f)
    except:
        reddit_config_dict = {}

    try:
        with open(f"{output_path}/test_all_rocketchat_for_end2end.json", "r") as f:
            rocketchat_config_dict = json.load(f)
    except:
        rocketchat_config_dict = {}

    config_dicts = {
        "owncloud": owncloud_config_dict,
        "reddit": reddit_config_dict,
        "rocketchat": rocketchat_config_dict
    }

    # Select the top 50 tasks with the highest ASR.
    task_list = ['own_owncloud_1_loose_permission_account.md_language', 'own_owncloud_1_loose_modify_course.md_language', 'own_rocketchat_3_loose_modify_course.md_language', 'own_reddit_2_loose_modify_contacts.csv_language', 'own_reddit_2_loose_delete_family_photo_language', 'own_owncloud_1_loose_open_terminals_language', 'own_owncloud_1_loose_modify_file_txt_language', 'own_owncloud_1_loose_stop_openvpn_language', 'own_rocketchat_2_loose_modify_course.md_language', 'own_owncloud_1_loose_delete_family_photo_language', 'own_owncloud_3_loose_stop_sshd_language', 'own_owncloud_1_loose_delete_bankstatement_language', 'own_rocketchat_3_loose_modify_file_txt_language', 'own_rocketchat_1_loose_delete_bankstatement_language', 'own_rocketchat_2_loose_delete_txt_language', 'own_rocketchat_1_loose_modify_course.md_language', 'own_reddit_2_loose_delete_bankstatement_language', 'own_owncloud_2_loose_delete_txt_language', 'own_reddit_2_loose_stop_openvpn_language', 'own_owncloud_3_loose_delete_idrsa_language', 'own_rocketchat_2_loose_modify_account.md_language', 'own_rocketchat_1_loose_stop_openvpn_language', 'own_rocketchat_3_loose_modify_account.md_language', 'own_rocketchat_2_loose_modify_contacts.csv_language', 'own_rocketchat_1_loose_modify_file_txt_language', 'own_rocketchat_1_loose_modify_contacts.csv_language', 'own_reddit_3_loose_modify_course.md_language', 'own_reddit_2_loose_modify_account.md_language', 'own_owncloud_1_loose_permission_file_txt_language', 'own_reddit_2_loose_permission_account.md_language', 'own_owncloud_1_loose_delete_etcsecurity_language', 'own_owncloud_1_loose_delete_idrsa_language', 'own_owncloud_1_loose_delete_txt_language', 'own_rocketchat_2_loose_delete_family_photo_language', 'own_owncloud_1_loose_modify_authorized_keys_language', 'own_owncloud_1_loose_modify_contacts.csv_language', 'own_rocketchat_2_loose_delete_idrsa_language', 'own_rocketchat_3_loose_delete_family_photo_language', 'own_rocketchat_1_loose_delete_txt_language', 'own_reddit_2_loose_modify_course.md_language', 'own_rocketchat_3_loose_permission_file_txt_language', 'own_rocketchat_1_loose_stop_sshd_language', 'own_reddit_2_loose_delete_txt_language', 'own_reddit_2_loose_delete_idrsa_language', 'own_rocketchat_2_loose_stop_sshd_language', 'own_reddit_3_loose_modify_contacts.csv_language', 'own_rocketchat_2_loose_stop_openvpn_language', 'own_rocketchat_1_loose_modify_authorized_keys_language', 'own_reddit_1_loose_delete_family_photo_language', 'own_reddit_1_loose_modify_contacts.csv_language']

    for benign_task in benign_task_raw:
        config_dict = config_dicts[benign_task["platform"]]
        if benign_task["platform"] + "_end2end" not in config_dict:
            config_dict[benign_task["platform"] + "_end2end"] = []
        
        for benign_task_type in ["end2end"]:
            if benign_task_type not in benign_task["instruction"]:
                continue
            config = {}
            config["platform"] = benign_task["platform"]
            config["meta_data"] = {
                "benign_task_type": benign_task_type
            }
            config["instruction"] = benign_task["instruction"][benign_task_type]["instruction"]

            # for OpenAI computer-use-preview
            config["tags"] = {
                "permission_check": True,
                "safety_check": True
            }

            config["config"] = [
                {
                    "type": "launch",
                    "parameters": {
                        "command": [
                        "google-chrome",
                        "--remote-debugging-port=1337",
                        "--user-data-dir=/tmp/chrome_user_data",
                        "--disable-session-crashed-bubble",
                        "--disable-save-password-bubble",
                        "--password-store=basic",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-infobars",
                        "--disable-component-update",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--start-maximized"
                        ]
                    }
                },
                {
                    "type": "launch",
                    "parameters": {
                        "command": [
                        "socat",
                        "tcp-listen:9222,fork",
                        "tcp:localhost:1337"
                        ]
                    }
                }
            ]

            if benign_task["platform"] == "reddit":
                config["config"].append(
                    {
                        "type": "login",
                        "parameters": {
                            "url": sub_url("__REDDIT__"),
                            "username": "MarvelsGrantMan136",
                            "password": "test1234",
                            "platform": "reddit"
                        }
                    }
                )
            
            elif benign_task["platform"] == "rocketchat":
                config["config"] = benign_task["pre_launch"] + config["config"]
                config["config"].append(
                    {
                        "type": "login",
                        "parameters": {
                            "url": sub_url("__ROCKETCHAT__"),
                            "username": "theagentcompany",
                            "password": "theagentcompany",
                            "platform": "rocketchat"
                        }
                    }
                )
            
            elif benign_task["platform"] == "owncloud":
                config["config"] = benign_task["pre_launch"] + config["config"]
                config["config"].append(
                    {
                        "type": "login",
                        "parameters": {
                            "url": sub_url("__OWNCLOUD__"),
                            "username": "theagentcompany",
                            "password": "theagentcompany",
                            "platform": "owncloud"
                        }
                    }
                )

            else:
                print(f"[ERROR] {benign_task['platform']} is not supported.")


            if benign_task["platform"] == "reddit":
                config["config"].append(
                    {
                        "type": "chrome_open_tabs",
                        "parameters": {
                            "urls_to_open": ["TO_BE_REPLACED_URL:9999"]
                        }
                    }
                )
                config["config"].append(
                    {
                        "type": "activate_window",
                        "parameters": {
                            "window_name": "Google Chrome"
                        }
                    }
                )
            elif benign_task["platform"] == "rocketchat":
                config["config"].append(
                    {
                        "type": "chrome_open_tabs",
                        "parameters": {
                            "urls_to_open": ["TO_BE_REPLACED_URL:3000"]
                        }
                    }
                )
                config["config"].append(
                    {
                        "type": "activate_window",
                        "parameters": {
                            "window_name": "Google Chrome"
                        }
                    }
                )
            elif benign_task["platform"] == "owncloud":
                config["config"].append(
                    {
                        "type": "chrome_open_tabs",
                        "parameters": {
                            "urls_to_open": ["TO_BE_REPLACED_URL:8092"]
                        }
                    }
                )
                config["config"].append(
                    {
                        "type": "activate_window",
                        "parameters": {
                            "window_name": "Google Chrome"
                        }
                    }
                )
                        
            config["evaluator"] = replace_in_dict(benign_task["evaluator"])


            for adversary_task in adversary_task_raw:
                config_for_adv = copy.deepcopy(config)

                if "extra_preprocessing" in adversary_task:
                    for c in adversary_task["extra_preprocessing"]:
                        config_for_adv["config"].append(c)

                for injection_contents in adversary_task["injection_contents"]:
                    # Only choose "language" for test
                    if injection_contents["type"] == "code":
                        continue

                    config_for_adv["meta_data"]["adversary_injection_type"] = injection_contents["type"]
                    
                    if benign_task["platform"] == "rocketchat":
                        deep_update(
                            injection_contents["action"]["parameters"],
                            benign_task["meta_injection"]["parameters"],
                        )
                    else:
                        injection_contents["action"]["parameters"].update(benign_task["meta_injection"]["parameters"])
                        
                    injection_contents["action"].update({"ip":"TO_BE_REPLACED_IP"})
                    config_for_adv["adversary_config"] = [injection_contents["action"]]
                    config_for_adv["adversary_evaluator"] = replace_in_dict(adversary_task["evaluator"], sub_url(benign_task["target_url"]))

                    config_name = "_".join([benign_task["id"], benign_task_type, adversary_task["description"], injection_contents["type"]])

                    ### Only choose top 50 tasks
                    if "_".join([benign_task["id"], "loose", adversary_task["description"], "language"]) not in task_list:
                        continue
                    ###

                    config_dict[benign_task["platform"] + "_end2end"].append(config_name)

                    dir_path = os.path.join(f'{output_path}/examples', benign_task["platform"] + "_end2end")
                    os.makedirs(dir_path, exist_ok=True)

                    config_for_adv["id"] = config_name
                    
                    config_for_adv["adv_id"] = adversary_task["id"]
                    with open(os.path.join(dir_path, config_name + ".json"), "w") as f:
                        json.dump(config_for_adv, f, indent=4)

    with open(f"{output_path}/test_all_owncloud_for_end2end.json", "w") as f:
        json.dump(owncloud_config_dict, f, indent=4)

    with open(f"{output_path}/test_all_reddit_for_end2end.json", "w") as f:
        json.dump(reddit_config_dict, f, indent=4)

    with open(f"{output_path}/test_all_rocketchat_for_end2end.json", "w") as f:
        json.dump(rocketchat_config_dict, f, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--benign_task_raw", type=str, default="goals/benign/benign_task.raw_own_rocketchat_install_nodejs.json")
    parser.add_argument("--adversary_task_raw", type=str, default="goals/adv/adversary_task.raw_own_rocketchat_install_nodejs.json")
    parser.add_argument("--output_path", type=str, default="evaluation_examples_own_rocketchat")

    args = parser.parse_args()

    with open(args.benign_task_raw, "r") as f:
        benign_task_raw = json.load(f)

    with open(args.adversary_task_raw, "r") as f:
        adversary_task_raw = json.load(f)

    create_config(benign_task_raw, adversary_task_raw, args.output_path)
