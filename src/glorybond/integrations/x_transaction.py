"""Current X website bootstrap around Twikit's transaction implementation."""

import re

from bs4 import BeautifulSoup
from twikit.x_client_transaction import ClientTransaction

from glorybond.integrations.x_web_assets import XWebAssets, XWebError


class XWebTransaction(ClientTransaction):
    async def init(self, session, headers):
        self.assets = None
        response = await session.get("https://x.com/home", headers=headers)
        if response.status_code != 200:
            raise XWebError(f"X 网页首页初始化失败（HTTP {response.status_code}），请检查登录会话；本次保留游标")
        self.home_page_response = BeautifulSoup(response.content, "html.parser")
        entry = re.search(r'''\bentryHref\s*=\s*["'](https://abs\.twimg\.com/[^"']+)["']''', str(self.home_page_response))
        if entry:
            self.assets = XWebAssets(entry[1], session, headers)
            await self.assets.bootstrap()
        self.DEFAULT_ROW_INDEX, self.DEFAULT_KEY_BYTES_INDICES = await self.get_indices(
            self.home_page_response, session, headers,
        )
        self.key = self.get_key(response=self.home_page_response)
        self.key_bytes = self.get_key_bytes(key=self.key)
        self.animation_key = self.get_animation_key(
            key_bytes=self.key_bytes, response=self.home_page_response,
        )

    async def get_indices(self, home_page_response, session, headers):
        if getattr(self, "assets", None) is not None:
            source = await self.assets.signature_source()
            # Current obfuscation wraps arithmetic calls but leaves these byte
            # accesses literal. Never evaluate downloaded JavaScript.
            indices = [int(value) for value in re.findall(r'''\(\s*[\w$]+\[(\d{1,2})\],\s*16\)''', source)]
            if len(indices) != 4:
                raise XWebError("X 网页 transaction 索引结构变化，本次保留游标")
            return indices[0], indices[1:]
        html = str(home_page_response)
        chunk = re.search(r'''(?:^|[,{])\s*["']?(\d+)["']?\s*:\s*["']ondemand\.s["']''', html)
        if chunk:
            # The module name and content hash live in two webpack maps.
            hash_match = re.search(r'''(?:^|[,{])\s*["']?''' + re.escape(chunk[1]) + r'''["']?\s*:\s*["']([0-9a-f]+)["']''', html)
        else:
            hash_match = re.search(r'''["']ondemand\.s["']\s*:\s*["']([0-9a-f]+)["']''', html)
        if not hash_match:
            raise XWebError("X 网页缺少 transaction 资源映射，本次保留游标")
        asset = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{hash_match[1]}a.js"
        response = await session.get(asset, headers=headers)
        if response.status_code != 200:
            raise XWebError("X 网页 transaction 资源获取失败，本次保留游标")
        indices = [int(value) for value in re.findall(r'''\(\w{1,3}\[(\d{1,2})\],\s*16\)''', response.text)]
        if len(indices) < 2:
            raise XWebError("X 网页 transaction 索引结构变化，本次保留游标")
        return indices[0], indices[1:]
