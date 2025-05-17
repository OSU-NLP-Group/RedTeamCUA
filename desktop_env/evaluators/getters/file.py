import os
from typing import Dict, List, Set
from typing import Optional, Any, Union
from datetime import datetime
import requests
import pandas as pd


def get_vm_file_path(env, config: Dict[str, Any]) -> bool:
    start_from = config["start_from"]
    path = config["path"]

    target_type = "f"
    if path.startswith("/"):
        target_path = path
    else:
        target_path = "*/" + path

    if start_from == '/home/user/':
        cmd = f"find {start_from} -type {target_type} -wholename '{target_path}'"
        response = env.controller.execute_command(cmd)

        if path in response["output"].strip():
            print(f"{path} exists")
            return 1
        else:
            print(f"{path} does not exist")
            return 0
        
    else:
        cmd = f"ls -l {config['path'].rstrip('/')}"
        response = env.controller.execute_command(cmd)

        if "No such file or directory" in response["error"].strip():
            print(f"{path} does not exist")
            return 0
        else:
            print(f"{path} exists")
            return 1




def get_vm_dir_path(env, config: Dict[str, Any]) -> bool:
    start_from = config["start_from"]
    path = config["path"].rstrip("/")

    target_type = "d"
    if path.startswith("/"):
        target_path = path
    else:
        target_path = "*/" + path

    if start_from == '/home/user/':
        cmd = f"find {start_from} -type {target_type} -wholename '{target_path}'"
        response = env.controller.execute_command(cmd)

        if path in response["output"].strip():
            print(f"{path} exists")
            return 1
        else:
            print(f"{path} does not exist")
            return 0
        
    else:
        cmd = f"ls -l {config['path'].rstrip('/')}"
        response = env.controller.execute_command(cmd)

        if "No such file or directory" in response["error"].strip():
            print(f"{path} does not exist")
            return 0
        else:
            print(f"{path} exists")
            return 1
    

def get_vm_file_content(env, config: Dict[str, Any]) -> str:
    file = env.controller.get_file(config["path"])

    if file is None:
        return ""

    if isinstance(file, bytes):
        file = file.decode("utf-8")
        print(file)
        return file
    

def get_vm_zip_password(env, config: Dict[str, Any]) -> str:
    start_from = config["start_from"]
    path = config["path"]
    password = config["password"]

    if start_from == '/home/user/':
        command = f"echo 'password' | sudo -S find {start_from} -type f -wholename '{path}'"
        response = env.controller.execute_command(command)

        if path not in response["output"].strip():
            print(f"{path} does not exist")
            return 0
        
    else:
        command = f"ls -l {config['path'].rstrip('/')}"
        response = env.controller.execute_command(command)

        if "No such file or directory" in response["error"].strip():
            print(f"{path} does not exist")
            return 0

    command = f"zipinfo -v {path}"
    response = env.controller.execute_command(command)

    if "file security status:                           encrypted" not in response["output"].strip():
        print(f"{path} is not encrypted")
        return 0

    command = f"unzip -P {password} {path}"
    response = env.controller.execute_command(command)

    if "incorrect password" in response["error"].strip():
        print(f"unzip {path}: incorrect password")
        return 0
    else:
        print(f"unzip {path} successfully")
        return 1


def get_content_from_vm_file(env, config: Dict[str, Any]) -> Any:
    """
    Config:
        path (str): absolute path on the VM to fetch
    """

    path = config["path"]
    file_path = get_vm_file(env, {"path": path, "dest": os.path.basename(path)})
    file_type, file_content = config['file_type'], config['file_content']
    if file_type == 'xlsx':
        if file_content == 'last_row':
            df = pd.read_excel(file_path)
            last_row = df.iloc[-1]
            last_row_as_list = last_row.astype(str).tolist()
            return last_row_as_list
    else:
        raise NotImplementedError(f"File type {file_type} not supported")


def get_cloud_file(env, config: Dict[str, Any]) -> Union[str, List[str]]:
    """
    Config:
        path (str|List[str]): the url to download from
        dest (str|List[str])): file name of the downloaded file
        multi (bool) : optional. if path and dest are lists providing
          information of multiple files. defaults to False
        gives (List[int]): optional. defaults to [0]. which files are directly
          returned to the metric. if len==1, str is returned; else, list is
          returned.
    """

    if not config.get("multi", False):
        paths: List[str] = [config["path"]]
        dests: List[str] = [config["dest"]]
    else:
        paths: List[str] = config["path"]
        dests: List[str] = config["dest"]
    cache_paths: List[str] = []

    gives: Set[int] = set(config.get("gives", [0]))

    for i, (p, d) in enumerate(zip(paths, dests)):
        _path = os.path.join(env.cache_dir, d)
        if i in gives:
            cache_paths.append(_path)

        if os.path.exists(_path):
            #return _path
            continue

        url = p
        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    return cache_paths[0] if len(cache_paths)==1 else cache_paths


def get_vm_file(env, config: Dict[str, Any]) -> Union[Optional[str], List[Optional[str]]]:
    """
    Config:
        path (str): absolute path on the VM to fetch
        dest (str): file name of the downloaded file
        multi (bool) : optional. if path and dest are lists providing
          information of multiple files. defaults to False
        gives (List[int]): optional. defaults to [0]. which files are directly
          returned to the metric. if len==1, str is returned; else, list is
          returned.
        only support for single file now:
        time_suffix(bool): optional. defaults to False. if True, append the current time in required format.
        time_format(str): optional. defaults to "%Y_%m_%d". format of the time suffix.
    """
    time_format = "%Y_%m_%d"
    if not config.get("multi", False):
        paths: List[str] = [config["path"]]
        dests: List[str] = [config["dest"]]
        if "time_suffix" in config.keys() and config["time_suffix"]:
            if "time_format" in config.keys():
                time_format = config["time_format"]
            # Insert time before . in file type suffix
            paths = [p.split(".")[0] + datetime.now().strftime(time_format) + "." + p.split(".")[1] if "." in p else p for p in paths]
            dests = [d.split(".")[0] + datetime.now().strftime(time_format) + "." + d.split(".")[1] if "." in d else d for d in dests]
    else:
        paths: List[str] = config["path"]
        dests: List[str] = config["dest"]


    cache_paths: List[str] = []

    gives: Set[int] = set(config.get("gives", [0]))

    for i, (p, d) in enumerate(zip(paths, dests)):
        _path = os.path.join(env.cache_dir, d)
        file = env.controller.get_file(p)
        if file is None:
            #return None
            # raise FileNotFoundError("File not found on VM: {:}".format(config["path"]))
            if i in gives:
                cache_paths.append(None)
            continue

        if i in gives:
            cache_paths.append(_path)
        with open(_path, "wb") as f:
            f.write(file)
    return cache_paths[0] if len(cache_paths)==1 else cache_paths


def get_cache_file(env, config: Dict[str, str]) -> str:
    """
    Config:
        path (str): relative path in cache dir
    """

    _path = os.path.join(env.cache_dir, config["path"])
    assert os.path.exists(_path)
    return _path
