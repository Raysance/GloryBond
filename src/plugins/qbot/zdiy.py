
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

    for node in ast.walk(tree):
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in ['os', 'subprocess', 'sys', 'shutil']:
                    return False, f"Forbidden import: {alias.name}"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ['eval', 'exec', 'open']:
                    return False, f"Forbidden function call: {node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in ['system', 'popen', 'spawn']:
                    return False, f"Forbidden attribute access: {node.func.attr}"
    return True, ""

def generate_code_from_text(user_input):
    # 尝试获取 prompt，如果未加载则使用默认值或重新读取
    try:
        pmpt = diy_code_pmpt
    except NameError:
        with open(os.path.join(os.path.dirname(__file__), 'variables_static.json'), 'r', encoding='utf-8') as f:
            varia = json.load(f)
            pmpt = varia.get("diy_code_pmpt", "")

    manual = get_api_manual()
    prompt = pmpt + "\n\nAPI Manual:\n" + manual + "\n\nUser Request: " + user_input
    
    retry_count = 3
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
