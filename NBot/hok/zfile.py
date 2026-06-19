
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc
import shutil
import os
import requests

def readera(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            data = file.read()
        return str(data)
    except FileNotFoundError:
        return ""
def writera(filepath,data):
    try:
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(data)
        return None
    except Exception as e:
        return None

def readerl(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
def writerl(filepath,data):
    try:
        with open(filepath, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        return None
    except Exception as e:
        return None
def update_dynamic_variable(key, value):
    filepath = "variables_dynamic.json"
    data = readerl(filepath)
    if not isinstance(data, dict):
        raise Exception(f"update_dynamic_variable_error: invalid variables_dynamic.json key={key}")
    data[key] = value
    tmp_filepath = filepath + ".tmp"
    with open(tmp_filepath, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
    os.replace(tmp_filepath, filepath)
    return None
def chats_dumper(qid, question, answer): # 输出各自的chat
    from .ztime import time_r
    current_time = time_r().strftime("%Y-%m-%d %H:%M:%S")
    json_file_path=os.path.join("chats",qid+".json")
    new_item = {
        "time": current_time,
        "Q": question,
        "A": answer
    }
    data=readerl(json_file_path)
    data.append(new_item)
    writerl(json_file_path,data)
def mem_dumper(qid, mem): # 不同人的mem分开保存
    from .ztime import time_r
    current_time = time_r().strftime("%Y-%m-%d %H:%M:%S")
    json_file_path=os.path.join("memory",qid+".json")
    new_item = {
        "time": current_time,
        "mem": mem,
    }
    data=readerl(json_file_path)
    data.append(new_item)
    writerl(json_file_path,data)
def mem_loader(qid,num_records=None): # 加载所有人的memory 每人最多99条记忆
    if (num_records==None): num_records=99
    memory_dir = "memory"
    result_str = ""
    if dmc.amnesia:
        json_files = [f for f in os.listdir(memory_dir) if (f.endswith('.json') and (str(super_id) in f))]
    else:
        json_files = [f for f in os.listdir(memory_dir) if f.endswith('.json')]
    if not json_files:
        log_message("ERROR: No JSON files found in memory directory")
        return ""
    for json_file in json_files:
        json_file_path = os.path.join(memory_dir, json_file)
        data=readerl(json_file_path)
        recent_records = data[-num_records:] if len(data) >= num_records else data
        for i, qa in enumerate(recent_records, 1):
            result_str += f" {i}:\n"
            result_str += f"时间: {qa['time']}\n"
            result_str += f"内容: {qa['mem']}\n"

    if result_str == "":
        log_message("ERROR: No valid memory data found.")
        return ""

    return result_str

def chats_loader(qid,num_records=None): # 只加载自己的chat
    if(num_records==None): num_records=3
    json_file_path=os.path.join("chats",qid+".json")
    data=readerl(json_file_path)
    recent_records = data[-num_records:] if len(data) >= num_records else data
    result_str = ""
    for i, qa in enumerate(recent_records, 1):
        result_str += f"记录 {i}:\n"
        result_str += f"时间: {qa['time']}\n"
        result_str += f"问题: {qa['Q']}\n"
        result_str += f"回答: {qa['A']}\n\n"
    return result_str
    
def copyfile(src_file,dst_file):
    shutil.copy(src_file,dst_file)
def file_exist(file_path):
    return os.path.exists(file_path)
def get_file_list(root_path,end_with):
    file_list=[]
    if os.path.exists(root_path) and os.path.isdir(root_path):
        for filename in os.listdir(root_path):
            if filename.endswith(end_with):
                file_path = os.path.join(root_path, filename)
                file_list.append(file_path)
    return file_list

def ensure_dir(dir_path):
    """Ensure directory exists, otherwise raise."""
    if not dir_path:
        raise Exception("ensure_dir_error: empty dir_path")
    os.makedirs(dir_path, exist_ok=True)
    return dir_path

def copyfile_to_dir(src_file, dst_dir):
    """Copy file to dst_dir, keep basename."""
    ensure_dir(dst_dir)
    dst_file = os.path.join(dst_dir, os.path.basename(src_file))
    shutil.copy(src_file, dst_file)
    return dst_file

def download_url_to_file(url: str, dst_file: str):
    """Download url to dst_file, raise on failure."""
    ensure_dir(os.path.dirname(dst_file))
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dst_file, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)
    return dst_file

def append_jsonl(filepath: str, item):
    """Append one json line, raise on failure."""
    ensure_dir(os.path.dirname(filepath))
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False))
        f.write("\n")
    return filepath
