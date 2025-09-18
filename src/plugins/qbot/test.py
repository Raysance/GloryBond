import request
url_btlist = f"{wzry_btl_url}?key={key}&id={id}&option={option}"
url_rnk = f"{wzry_profile_url}?key={key}&id={id}"
headers = {
    "Content-Type": "application/x-www-form-urlencoded;charset:utf-8;"
}
response_rnk = requests.get(url_rnk, headers=headers)