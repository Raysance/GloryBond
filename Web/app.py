from fastapi import FastAPI, Request, HTTPException, Query, Body, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.templating import Jinja2Templates

import redis
import os
import json
import sys
import logging
import datetime
import secrets
import yaml
import time

from utils import *

# 引入变量
variables_to_import = ["userlist", "roleidlist", "qid", "namenick", "nameref", "extra_useridlist", "extra_roleidlist", "extra_namenick"]
variables_file_path = "../NBot/variables_static.json"

def reload_variables():
    with open(variables_file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
    for var_name in variables_to_import:
        if var_name in data:
            globals()[var_name] = data[var_name]
        else:
            globals()[var_name] = {}

reload_variables()

templates = Jinja2Templates(directory="templates")
# 引入Redis变量
nginx_path=str(os.environ.get('NGINX_HTML'))
redis_path=str(os.environ.get('REDIS_CONF'))
with open(redis_path, 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)

# 初始化fastapi与redis
app = FastAPI()
r_com = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
r_liked_set = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_LIKED_SET)
r_share_queue=redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_SHARE_QUEUE)
r_analyze_queue=redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_ANALYZE_QUEUE)
r_chat = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_CHAT_MEMORY)

SECRET_KEY = "HOKCAMP123"

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "ErrorPages/illegal.html",
        {"request": request},
        status_code=404
    )

@app.get("/btlist", response_class=HTMLResponse)
async def show_btlist(request:Request,key: str):
    # raise HTTPException(
    #     status_code=404,
    #     detail={"template": "404_a.html", "context": {"message": ""}}
    # )
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r_com.get(key).decode('utf-8'))
        local_path=os.path.join(nginx_path,"wzry_history",text_content["filename"]+".json")
        if (not file_exist(local_path)): raise Exception("File not exists.")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/AllBattleList.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",text_content["filename"]+".json"),
            "time": text_content["time"],
            "caller": text_content["caller"],
        }
    )
@app.get("/btlperson", response_class=HTMLResponse)
async def show_btlperson(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r_com.get(key).decode('utf-8'))
        local_path=os.path.join(nginx_path,"wzry_history",text_content["filename"]+".json")
        if (not file_exist(local_path)): raise Exception("File not exists.")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/SingleBattleList.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",text_content["filename"]+".json"),
            "key": key,
        }
    )
@app.get("/btlperiod", response_class=HTMLResponse)
async def show_btlperiod(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r_com.get(key).decode('utf-8'))
        local_path=os.path.join(nginx_path,"wzry_history",text_content["filename"]+".json")
        if (not file_exist(local_path)): raise Exception("File not exists.")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/SinglePeriodBattleList.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",text_content["filename"]+".json"),
            "key": key,
            "DateFrom":text_content["DateFrom"],
            "DateTo":text_content["DateTo"],
        }
    )
@app.get("/btldetail", response_class=HTMLResponse)
async def show_btldetail(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r_com.get(key).decode('utf-8'))
        local_path=os.path.join(nginx_path,"wzry_history",text_content["filename"]+".json")
        if (not file_exist(local_path)): raise Exception("File not exists.")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/BattleDetail.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",text_content["filename"]+".json"),
            "key": key,
        }
    )
@app.get("/btlquery", response_class=HTMLResponse)
async def show_btldetail(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r_com.get(key).decode('utf-8'))
        local_path=os.path.join(nginx_path,"wzry_history",text_content["filename"]+".json")
        if (not file_exist(local_path)): raise Exception("File not exists.")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/BattleQuery.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",text_content["filename"]+".json"),
            "query_target":text_content["caller"],
            "key": key,
        }
    )
def check_key_valid(key):
    if key is None:
        return False
    return r_com.exists(key) or key==SECRET_KEY
@app.get("/jump-btlperson", response_class=HTMLResponse)
async def jump_btlperson(request:Request,userid: str,roleid: str,key:str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(final_key)):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key失效"}
        )
    try:
        profile_res=wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
        btlist_res=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":f"网络参数错误 {str(e)}"}
        )
    res={"btlist":btlist_res,"profile":profile_res}
    file_name=secrets.token_hex(8)+".json"
    save_path=os.path.join(nginx_path,"wzry_history", file_name)
    writerl(save_path,res)
    return templates.TemplateResponse(
        "CommonPages/SingleBattleList.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",file_name),
            "key": final_key,
        }
    )
@app.get("/jump-btldetail", response_class=HTMLResponse)
async def jump_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,key:str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(final_key)):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key失效"}
        )
    if (check_battle_local_exist(gameSeq,targetRoleId)):
        web_path=os.path.join("wzry_history","battles",gameSeq+".json")
    else:
        try:
            res=wzry_get_official(reqtype="btldetail",gameseq=gameSeq,gameSvrId=gameSvr,relaySvrId=relaySvr,roleid=int(targetRoleId),pvptype=battleType)
        except Exception as e:
            return templates.TemplateResponse(
                "ErrorPages/expired.html",{"request": request,"message":f"对局已过期或id无效 {str(e)}"}
            )
        file_name=secrets.token_hex(8)+".json"
        save_path=os.path.join(nginx_path,"wzry_history", file_name)
        web_path=os.path.join("wzry_history",file_name)
        writerl(save_path,res)
    return templates.TemplateResponse(
        "CommonPages/BattleDetail.html",
        {
            "request": request,
            "filename": web_path,
            "key": final_key,
            "gameSeq":gameSeq,
            "gameSvr":gameSvr,
            "relaySvr":relaySvr,
            "targetRoleId":targetRoleId,
            "battleType":battleType,
        }
    )
@app.get("/like-btldetail", response_class=HTMLResponse)
async def like_btldetail(request:Request,gameSeq: str,key:str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(final_key)):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"key失效",
                "error_code": "LIKE_FAILED"
            }
        )
    happen_time=int(time.time())
    if (r_liked_set.exists(gameSeq)):
        result=r_liked_set.delete(gameSeq) 
        success_data={
            "success": True,
            "message": "取消收藏成功",
            "data": {
                "battle_id": gameSeq,
                "timestamp": happen_time
            }
        }
    else:
        r_liked_set.set(gameSeq,happen_time)
        success_data={
            "success": True,
            "message": "收藏成功",
            "data": {
                "battle_id": gameSeq,
                "timestamp": happen_time
            }
        }
    return JSONResponse(success_data)
@app.get("/share-btldetail", response_class=HTMLResponse)
async def share_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,key:str = Query(None), AdminKey: str = Cookie(None),Special: bool = False):
    final_key = key or AdminKey
    if (not check_key_valid(final_key)):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"key失效",
                "error_code": "LIKE_FAILED"
            }
        )
    params={
        "gameSvrId":gameSvr,
        "gameseq":gameSeq,
        "roleid":targetRoleId,
        "relaySvrId":relaySvr,
        "pvptype":battleType
    }
    try:
        json_params = json.dumps(params)
        result = r_share_queue.lpush("Shared_queue", json_params)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "数据库操作失败",
                "error_code": "DB_OPERATION_ERROR"
            }
        )
    
    happen_time=int(time.time())
    success_data={
        "success": True,
        "message": "分享成功",
        "data": {
            "battle_id": gameSeq,
            "timestamp": happen_time
        }
    }
    return JSONResponse(success_data)
@app.get("/analyze-btldetail", response_class=HTMLResponse)
async def analyze_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,Special: bool,key: str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(final_key)):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"key失效",
                "error_code": "LIKE_FAILED"
            }
        )
    game_params={
        "gameSvrId":gameSvr,
        "gameseq":gameSeq,
        "roleid":targetRoleId,
        "relaySvrId":relaySvr,
        "pvptype":battleType,
        "Special":Special
    }
    params={
        "game_params":game_params,
        "Special":Special
    }
    try:
        json_params = json.dumps(params)
        result = r_analyze_queue.lpush("Analyze_queue", json_params)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "数据库操作失败",
                "error_code": "DB_OPERATION_ERROR"
            }
        )
    
    happen_time=int(time.time())
    success_data={
        "success": True,
        "message": "分析底蕴中",
        "data": {
            "battle_id": gameSeq,
            "timestamp": happen_time
        }
    }
    return JSONResponse(success_data)


@app.get("/admin", response_class=JSONResponse)
async def admin_verify(request: Request):
    raise HTTPException(status_code=403)

@app.get("/admin/verify", response_class=JSONResponse)
async def admin_verify(request: Request, pattern: str):
    def parse_pattern(raw: str) -> list[int]:
        try:
            return [int(item) for item in raw.split(',') if item.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pattern 参数不合法") from exc

    VALID_PATTERN = [0, 1, 2, 5, 8]
    if parse_pattern(pattern) != VALID_PATTERN:
        return JSONResponse({"state": "failed","message": "认证失败","key":""})

    else:
        return {"state": "success","message":"认证成功","key": SECRET_KEY}
        
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("AdminPages/AdminLogin.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request, password: str = Body(..., embed=True)):
    if password == SECRET_KEY:
        response = JSONResponse({"status": "success", "message": "登录成功"})
        # 设置 cookie，有效期 7 天
        response.set_cookie(key="AdminKey", value=password, max_age=604800, httponly=True)
        return response
    else:
        return JSONResponse({"status": "error", "message": "密码错误"}, status_code=401)

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    return templates.TemplateResponse(
        "AdminPages/DashBoard.html",
        {
            "request": request,
            "AdminKey": AdminKey
        }
    )

@app.get("/admin/funcs/direct-navigate", response_class=HTMLResponse)
async def jump_admin_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    reload_variables()
    return templates.TemplateResponse(
        "AdminPages/DirectNavigate.html",
        {
            "request": request,
            "AdminKey": AdminKey,
            "useridlist": {**userlist, **extra_useridlist},
            "roleidlist": {**roleidlist, **extra_roleidlist}
        }
    )

@app.get("/admin/funcs/user-edit", response_class=HTMLResponse)
async def admin_user_edit_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    return templates.TemplateResponse(
        "AdminPages/UserEdit.html",
        {
            "request": request,
            "AdminKey": AdminKey
        }
    )

@app.get("/admin/funcs/chat-viewer", response_class=HTMLResponse)
async def admin_chat_viewer_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    reload_variables()
    return templates.TemplateResponse(
        "AdminPages/ChatViewer.html",
        {
            "request": request,
            "AdminKey": AdminKey,
            "qid_map": qid # realname -> qid
        }
    )

@app.get("/admin/funcs/chat-viewer/fetch")
async def fetch_chat_records(target_qid: str, mode: str = "active", AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return {"status": "error", "message": "认证失败"}
    
    prefix = "zmem:"
    try:
        if mode == "forced":
            # 获取长效记忆 (forced_mem)
            if target_qid == "global":
                # 全局模式下扫描所有人的记忆
                all_keys = r_chat.keys(f"{prefix}forced_mem:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    raw_records = r_chat.lrange(k, 0, -1) 
                    for idx, r in enumerate(raw_records):
                        item = json.loads(r.decode('utf-8'))
                        records.append({
                            "time": item.get("time", ""),
                            "nick": qid_part,
                            "Q": "强制记忆录入",
                            "A": item.get("mem", ""),
                            "qid": qid_part,
                            "idx": idx
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}forced_mem:{target_qid}"
                raw_records = r_chat.lrange(key, 0, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    item = json.loads(r.decode('utf-8'))
                    records.append({
                        "time": item.get("time", ""),
                        "Q": "主动强制内容",
                        "A": item.get("mem", ""),
                        "qid": target_qid,
                        "idx": idx
                    })
                records.reverse()
        elif mode == "passive":
            # 获取被动聊天记录 (passive_chat)
            if target_qid == "global":
                all_keys = r_chat.keys(f"{prefix}passive_chat:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    last_record = r_chat.lrange(k, -1, -1)
                    if last_record:
                        item = json.loads(last_record[0].decode('utf-8'))
                        records.append({
                            "time": item.get("time", ""),
                            "nick": qid_part,
                            "Q": item.get("text", ""),
                            "A": "(被动记录片段)",
                            "qid": qid_part
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}passive_chat:{target_qid}"
                raw_records = r_chat.lrange(key, -100, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    item = json.loads(r.decode('utf-8'))
                    records.append({
                        "time": item.get("time", ""),
                        "Q": item.get("text", ""),
                        "A": "(记录于群聊)",
                        "qid": target_qid,
                        "idx": idx
                    })
                records.reverse()
        elif mode == "summary":
            # 获取历史总结记忆 (summary_mem)
            if target_qid == "global":
                all_keys = r_chat.keys(f"{prefix}summary_mem:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    raw_records = r_chat.lrange(k, 0, -1)
                    for idx, r in enumerate(raw_records):
                        item = json.loads(r.decode('utf-8'))
                        records.append({
                            "time": item.get("time", ""),
                            "nick": qid_part,
                            "Q": f"用户总结 ({qid_part})",
                            "A": item.get("summary", ""),
                            "qid": qid_part,
                            "idx": idx
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}summary_mem:{target_qid}"
                raw_records = r_chat.lrange(key, 0, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    item = json.loads(r.decode('utf-8'))
                    records.append({
                        "time": item.get("time", ""),
                        "Q": "今日状态提炼",
                        "A": item.get("summary", ""),
                        "qid": target_qid,
                        "idx": idx
                    })
                records.reverse()
        else: # active_chat
            if target_qid == "global":
                all_keys = r_chat.keys(f"{prefix}active_chat:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    raw_records = r_chat.lrange(k, -5, -1)
                    for idx, r in enumerate(raw_records):
                        item = json.loads(r.decode('utf-8'))
                        records.append({
                            **item,
                            "nick": qid_part,
                            "qid": qid_part,
                            "idx": idx
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}active_chat:{target_qid}"
                raw_records = r_chat.lrange(key, -50, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    records.append({**json.loads(r.decode('utf-8')), "idx": idx, "qid": target_qid})
                records.reverse()
        
        return {"status": "success", "records": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/admin/funcs/chat-viewer/memory-op")
async def memory_operation(op: str = Body(...), qid: str = Body(...), mode: str = Body("forced"), content: str = Body(None), idx: int = Body(None), AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return {"status": "error", "message": "认证失败"}
    
    mapping = {"forced": "forced_mem", "active": "active_chat", "passive": "passive_chat", "summary": "summary_mem"}
    if mode not in mapping: return {"status": "error", "message": "未知模式"}
    
    key = f"zmem:{mapping[mode]}:{qid}"
    try:
        if op == "add":
            item = {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            if mode == "active": item.update({"Q": content, "A": "(手动录入)"})
            elif mode == "passive": item["text"] = content
            elif mode == "forced": item["mem"] = content
            elif mode == "summary": item["summary"] = content
            r_chat.rpush(key, json.dumps(item, ensure_ascii=False))
            r_chat.ltrim(key, -100, -1)
        
        elif op == "delete":
            target_val = r_chat.lindex(key, idx)
            if target_val: r_chat.lrem(key, 1, target_val)
        
        elif op == "update":
            old_val_raw = r_chat.lindex(key, idx)
            if old_val_raw:
                item = json.loads(old_val_raw.decode('utf-8'))
                if mode == "active": item["Q"] = content
                elif mode == "passive": item["text"] = content
                elif mode == "forced": item["mem"] = content
                elif mode == "summary": item["summary"] = content
                
                # 更新时间并打上修改标记
                item["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (已修改)"
                r_chat.lset(key, idx, json.dumps(item, ensure_ascii=False))

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/admin/funcs/user-edit/fetch-user-info")
async def fetch_user_info(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return JSONResponse({"status": "error", "message": "AdminKey失效"}, status_code=401)
    reload_variables()
    return {
        "userlist": userlist,
        "roleidlist": roleidlist,
        "qid": qid,
        "namenick": namenick,
        "nameref": nameref,
        "extra_useridlist": extra_useridlist,
        "extra_roleidlist": extra_roleidlist,
        "extra_namenick": extra_namenick,
    }

@app.post("/admin/funcs/user-edit/submit-user-info")
async def submit_user_info(request: Request, changes: list = Body(...), AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return JSONResponse({"status": "error", "message": "AdminKey失效"}, status_code=401)
    try:
        with open(variables_file_path, 'r', encoding='utf-8') as f:
            full_data = json.load(f)
        
        for change in changes:
            op = change.get('op')
            ctype = change.get('type')
            ckey = change.get('key')
            cdata = change.get('data')

            if ctype == 'main':
                target_fields = ['userlist', 'roleidlist', 'qid', 'namenick', 'nameref']
            else:
                target_fields = ['extra_useridlist', 'extra_roleidlist', 'extra_namenick']

            if op in ['add', 'edit']:
                for f_name in target_fields:
                    if f_name not in full_data: full_data[f_name] = {}
                    val = cdata.get(f_name)
                    # 处理数值类型
                    if f_name in ['userlist', 'roleidlist', 'qid', 'extra_useridlist', 'extra_roleidlist'] and val:
                        try: val = int(val)
                        except: pass
                    full_data[f_name][ckey] = val
            elif op == 'delete':
                for f_name in target_fields:
                    if f_name in full_data and ckey in full_data[f_name]:
                        del full_data[f_name][ckey]

        with open(variables_file_path, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
        
        # 同步更新到内存中的全局变量
        reload_variables()
                
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)