"""Current X website bootstrap around Twikit's transaction implementation."""

import re

from bs4 import BeautifulSoup
from twikit.x_client_transaction import ClientTransaction


class XWebTransaction(ClientTransaction):
    async def init(self, session, headers):
        # X's logged-out root is now a different application. The logged-in
        # /home document still carries the transaction animation and chunk map.
        response = await session.get("https://x.com/home", headers=headers)
        if response.status_code != 200:
            raise RuntimeError("X 网页初始化失败，请检查登录会话")
        self.home_page_response = BeautifulSoup(response.content, "html.parser")
        self.DEFAULT_ROW_INDEX, self.DEFAULT_KEY_BYTES_INDICES = await self.get_indices(
            self.home_page_response, session, headers,
        )
        self.key = self.get_key(response=self.home_page_response)
        self.key_bytes = self.get_key_bytes(key=self.key)
        self.animation_key = self.get_animation_key(
            key_bytes=self.key_bytes, response=self.home_page_response,
        )

    async def get_indices(self, home_page_response, session, headers):
        html = str(home_page_response)
        chunk = re.search(r'''(?:^|[,{])\s*["']?(\d+)["']?\s*:\s*["']ondemand\.s["']''', html)
        if chunk:
            # The module name and content hash live in two webpack maps.
            hash_match = re.search(r'''(?:^|[,{])\s*["']?''' + re.escape(chunk[1]) + r'''["']?\s*:\s*["']([0-9a-f]+)["']''', html)
        else:
            hash_match = re.search(r'''["']ondemand\.s["']\s*:\s*["']([0-9a-f]+)["']''', html)
        if not hash_match:
            raise RuntimeError("X 网页缺少 transaction 资源映射")
        asset = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{hash_match[1]}a.js"
        response = await session.get(asset, headers=headers)
        if response.status_code != 200:
            raise RuntimeError("X 网页 transaction 资源获取失败")
        indices = [int(value) for value in re.findall(r'''\(\w{1,3}\[(\d{1,2})\],\s*16\)''', response.text)]
        if len(indices) < 2:
            raise RuntimeError("X 网页 transaction 索引结构变化")
        return indices[0], indices[1:]
