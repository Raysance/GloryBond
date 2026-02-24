from fastapi import FastAPI, Request, HTTPException, Query, Body
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
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
    return r_com.exists(key) or key==SECRET_KEY
@app.get("/jump-btlperson", response_class=HTMLResponse)
async def jump_btlperson(request:Request,userid: str,roleid: str,key:str):
    if (not check_key_valid(key)):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key失效"}
        )
    try:
        profile_res=wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
        btlist_res=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"网络参数错误"}
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
            "key":key,
        }
    )
@app.get("/jump-btldetail", response_class=HTMLResponse)
async def jump_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,key:str):
    if (not check_key_valid(key)):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key失效"}
        )
    res=fetch_battle(gameSeq,targetRoleId)
    if not res:
        try:
            res=wzry_get_official(reqtype="btldetail",gameseq=gameSeq,gameSvrId=gameSvr,relaySvrId=relaySvr,roleid=int(targetRoleId),pvptype=battleType)
        except Exception as e:
            return templates.TemplateResponse(
                "ErrorPages/expired.html",{"request": request,"message":"对局已过期或id无效"}
            )
    file_name=secrets.token_hex(8)+".json"
    save_path=os.path.join(nginx_path,"wzry_history", file_name)
    writerl(save_path,res)
    return templates.TemplateResponse(
        "CommonPages/BattleDetail.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",file_name),
            "key":key,
            "gameSeq":gameSeq,
            "gameSvr":gameSvr,
            "relaySvr":relaySvr,
            "targetRoleId":targetRoleId,
            "battleType":battleType,
        }
    )
@app.get("/like-btldetail", response_class=HTMLResponse)
async def like_btldetail(request:Request,gameSeq: str,key:str):
    if (not check_key_valid(key)):
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
async def share_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,key:str):
    if (not check_key_valid(key)):
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
async def analyze_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,Special: bool,key: str):
    if (not check_key_valid(key)):
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
        "pvptype":battleType
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

    if parse_pattern(pattern) != VALID_PATTERN:
        return JSONResponse({"state": "failed","message": "认证失败","key":""})

    else:
        return {"state": "success","message":"认证成功","key": SECRET_KEY}
        
@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_user_edit_page(request: Request, AdminKey: str):
    if AdminKey != SECRET_KEY:
        return templates.TemplateResponse("ErrorPages/illegal.html", {"request": request, "message": "AdminKey失效"})
    return templates.TemplateResponse(
        "AdminPages/DashBoard.html",
        {
            "request": request,
            "AdminKey":AdminKey
        }
    )

@app.get("/admin/funcs/direct-navigate", response_class=HTMLResponse)
async def jump_admin_page(request: Request, AdminKey: str):
    if (AdminKey!=SECRET_KEY):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"AdminKey失效"}
        )
    reload_variables()
    return templates.TemplateResponse(
        "AdminPages/DirectNavigate.html",
        {
            "request": request,
            "AdminKey":AdminKey,
            "useridlist":{**userlist,**extra_useridlist},
            "roleidlist":{**roleidlist,**extra_roleidlist}
        }
    )

@app.get("/admin/funcs/user-edit", response_class=HTMLResponse)
async def admin_user_edit_page(request: Request, AdminKey: str):
    if AdminKey != SECRET_KEY:
        return templates.TemplateResponse("ErrorPages/illegal.html", {"request": request, "message": "AdminKey失效"})
    return templates.TemplateResponse(
        "AdminPages/UserEdit.html",
        {
            "request": request,
            "AdminKey":AdminKey
        }
    )
@app.get("/admin/funcs/user-edit/fetch-user-info")
async def fetch_user_info(request: Request, AdminKey: str = Query(...)):
    if AdminKey != SECRET_KEY:
        return templates.TemplateResponse("ErrorPages/illegal.html", {"request": request, "message": "AdminKey失效"})
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
async def submit_user_info(request: Request, AdminKey: str = Query(...), changes: list = Body(...)):
    if AdminKey != SECRET_KEY:
        return templates.TemplateResponse("ErrorPages/illegal.html", {"request": request, "message": "AdminKey失效"})
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