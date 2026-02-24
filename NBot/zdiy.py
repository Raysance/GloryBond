
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc
from .zapi import ai_api
import ast
import traceback
import hashlib

def get_api_manual():
    try:
        with open(os.path.join(os.path.dirname(__file__), 'api_manual.md'), 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return "API Manual not found."

def check_code_safety(code):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    forbidden_imports = [
        'os', 'subprocess', 'sys', 'shutil', 'pathlib', 'glob', 
        'pickle', 'marshal', 'tempfile', 'builtins', 'io', 
        'socket', 'requests', 'urllib', 'ftplib', 'poplib', 
        'imaplib', 'smtplib', 'telnetlib'
    ]
    
    forbidden_functions = [
        'open', 'eval', 'exec', 'compile', '__import__', 
        'input', 'exit', 'quit', 'help', 'globals', 'locals', 'vars',
        'print' # 禁止print，强制使用add_msg
    ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base_module = alias.name.split('.')[0]
                if base_module in forbidden_imports:
                    return False, f"Forbidden import: {alias.name}"
        if isinstance(node, ast.ImportFrom):
            if node.module:
                base_module = node.module.split('.')[0]
                if base_module in forbidden_imports:
                    return False, f"Forbidden import: {node.module}"
                
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in forbidden_functions:
                    return False, f"Forbidden function call: {node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in ['system', 'popen', 'spawn', 'write', 'read', 'open']:
                    return False, f"Forbidden attribute access: {node.func.attr}"
    return True, ""

def generate_code_from_text(user_input):
    manual = get_api_manual()
    prompt = diy_code_pmpt + "\n\nAPI Manual:\n" + manual + "\n\nUser Request: " + user_input
    
    retry_count = 2
    last_error = ""
    
    for i in range(retry_count):
        try:
            if last_error:
                current_prompt = prompt + f"\n\nPrevious attempt failed with error: {last_error}. Please fix it."
            else:
                current_prompt = prompt
                
            code = ai_api(current_prompt, 0.2)
            # 清理 markdown 标记
            code = code.replace("```python", "").replace("```", "").strip()
            
            is_safe, error = check_code_safety(code)
            if is_safe:
                return code
            else:
                last_error = error
        except Exception as e:
            last_error = str(e)
            
    raise Exception(f"Failed to generate safe code after {retry_count} attempts. Last error: {last_error}")

def save_code_to_redis(summary, code):
    code_id = hashlib.md5(summary.encode('utf-8')).hexdigest()
    
    # 存储代码
    dmc.redis_deamon_diy_code.hset("diy_codes", code_id, code)
    # 存储概要映射
    dmc.redis_deamon_diy_code.hset("diy_summaries", code_id, summary)
    
    return code_id

def execute_generated_code(code, event):
    local_scope = {'event': event}
    try:
        # 动态执行代码
        exec(code, globals(), local_scope)
        if 'generated_function' in local_scope:
            # 执行生成的函数
            result = local_scope['generated_function'](event)
            return result
        else:
            return "Error: generated_function not found in code."
    except Exception as e:
        return f"Execution Error: {traceback.format_exc()}"

def handle_diy_request(event, user_input):
    try:
        # 1. 生成代码
        code = generate_code_from_text(user_input)
        
        # 2. 存储代码
        code_id = save_code_to_redis(user_input, code)
        
        # 3. 执行代码
        result = execute_generated_code(code, event)
        
        return f"Code generated and executed.\nID: {code_id}\nResult: {result}"
    except Exception as e:
        return f"DIY Error: {str(e)}"
