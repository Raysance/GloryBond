from fastapi import FastAPI, Request, HTTPException
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

# 引入变量
variables_to_import = ["userlist","idname"]
with open("../NBot/variables_static.json", 'r', encoding='utf-8') as file:
    data = json.load(file)
for var_name in variables_to_import:
    if var_name in data:
        globals()[var_name] = data[var_name]
templates = Jinja2Templates(directory="templates")
# 引入Redis变量
nginx_path=str(os.environ.get('NGINX_HTML'))
redis_path=str(os.environ.get('REDIS_CONF'))
with open(redis_path, 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)
# 初始化fastapi与redis
app = FastAPI()
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,password=REDIS_PASSWORD)

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "404_all.html",
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
        text_content = json.loads(r.get(key).decode('utf-8'))
    except Exception as e:
        return templates.TemplateResponse(
            "err_single.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "AllBattleList.html",
        {
            "request": request,
            "filename": os.path.join("wzry_history",text_content["filename"]+".json"),
            "time": text_content["time"],
            "caller": text_content["caller"],
        }
    )
@app.get("/btlperson", response_class=HTMLResponse)
async def show_btlist(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r.get(key).decode('utf-8'))
    except Exception as e:
        return templates.TemplateResponse(
            "err_single.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "SingleBattleList.html",
        {
            "request": request,
            # "userfiles":{"a":os.path.join("wzry_history","ed5db8f34da0d8e8.json")},
            "filename": os.path.join("wzry_history",text_content["filename"]+".json")
        }
    )
@app.get("/btldetail", response_class=HTMLResponse)
async def show_btldetail(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content = json.loads(r.get(key).decode('utf-8'))
    except Exception as e:
        return templates.TemplateResponse(
            "err_single.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "BattleDetail.html",
        {
            "request": request,
            # "userfiles":{"a":os.path.join("wzry_history","ed5db8f34da0d8e8.json")},
            "filename": os.path.join("wzry_history",text_content["filename"]+".json")
        }
    )
# @app.get("/btlapi/btlperson", response_class=HTMLResponse)
# async def api_btlperson(request:Request,userid: str,roleid: str):
#     from ..NBot.src.plugins.qbot.zapi import wzry_get_official
#     from ..NBot.
#     from openai import OpenAI
#     import requests
#     from ratelimit import limits, sleep_and_retry
#     try:
#         text_content = json.loads(r.get(key).decode('utf-8'))
#     except Exception as e:
#         return templates.TemplateResponse(
#             "err_single.html",{"request": request,}
#         )
#     return templates.TemplateResponse(
#         "BattleDetail.html",
#         {
#             "request": request,
#             # "userfiles":{"a":os.path.join("wzry_history","ed5db8f34da0d8e8.json")},
#             "filename": os.path.join("wzry_history",text_content["filename"]+".json")
#         }
#     )
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)