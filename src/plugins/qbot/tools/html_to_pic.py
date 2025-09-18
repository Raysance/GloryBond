#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级网页截图工具
功能：
1. 滚动截图（截取整个页面）
2. 等待页面完全加载
3. 高清截图
4. 可调整边界参数
5. 支持本地HTML文件和网页URL
"""

import time
import os
import sys
import io
from PIL import Image
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

class WebPageScreenshot:
    def __init__(self, window_width=1220, window_height=2200, device_scale_factor=2.0):
        """
        初始化截图工具
        
        Args:
            window_width (int): 浏览器窗口宽度
            window_height (int): 浏览器窗口高度
            device_scale_factor (float): 设备缩放因子，用于高清截图
        """
        self.window_width = window_width
        self.window_height = window_height
        self.device_scale_factor = device_scale_factor
        self.driver = None
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('html_to_image.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def setup_driver(self, headless=True):
        """
        设置Chrome浏览器驱动
        
        Args:
            headless (bool): 是否无头模式
        """
        try:
            chrome_options = Options()
            
            if headless:
                chrome_options.add_argument('--headless')
            
            # 基本设置
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # 高清截图设置
            chrome_options.add_argument(f'--window-size={self.window_width},{self.window_height}')
            chrome_options.add_argument(f'--force-device-scale-factor={self.device_scale_factor}')
            chrome_options.add_argument('--high-dpi-support=1')
            
            # 性能优化
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins')
            # chrome_options.add_argument('--disable-images')  # 注释掉：保留图片加载以获得完整页面
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.set_window_size(self.window_width, self.window_height)
            
            self.logger.info("Chrome驱动初始化成功")
            return True
            
        except Exception as e:
            self.logger.error(f"Chrome驱动初始化失败: {e}")
            return False
    
    def wait_for_page_load(self, timeout=30, additional_wait=3):
        """
        等待页面完全加载
        
        Args:
            timeout (int): 超时时间（秒）
            additional_wait (int): 额外等待时间（秒）
        """
        try:
            # 等待页面基本加载完成
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            # 等待所有图片加载完成
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script(
                    """
                    var images = document.getElementsByTagName('img');
                    for (var i = 0; i < images.length; i++) {
                        if (!images[i].complete || images[i].naturalWidth === 0) {
                            return false;
                        }
                    }
                    return true;
                    """
                )
            )
            
            # 等待所有Ajax请求完成（如果使用jQuery）
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda driver: driver.execute_script("return jQuery.active == 0") if 
                    driver.execute_script("return typeof jQuery != 'undefined'") else True
                )
            except:
                pass  # 如果没有jQuery，忽略这个检查
            
            # 额外等待时间，确保动态内容加载
            time.sleep(additional_wait)
            
            self.logger.info("页面加载完成")
            return True
            
        except TimeoutException:
            self.logger.warning(f"页面加载超时，但继续执行截图")
            return False
        except Exception as e:
            self.logger.error(f"等待页面加载时出错: {e}")
            return False
    
    def get_full_page_size(self):
        """
        获取页面的完整尺寸
        
        Returns:
            tuple: (width, height)
        """
        try:
            # 获取页面的完整高度和宽度
            total_width = self.driver.execute_script("return Math.max(document.body.scrollWidth, document.body.offsetWidth, document.documentElement.clientWidth, document.documentElement.scrollWidth, document.documentElement.offsetWidth);")
            total_height = self.driver.execute_script("return Math.max(document.body.scrollHeight, document.body.offsetHeight, document.documentElement.clientHeight, document.documentElement.scrollHeight, document.documentElement.offsetHeight);")
            
            self.logger.info(f"页面完整尺寸: {total_width} x {total_height}")
            return total_width, total_height
            
        except Exception as e:
            self.logger.error(f"获取页面尺寸失败: {e}")
            return self.window_width, self.window_height
    
    def scroll_screenshot(self, url, output_path, crop_box=None, scroll_step=None):
        """
        滚动截图整个页面
        
        Args:
            url (str): 网页URL或本地HTML文件路径
            output_path (str): 输出图片路径
            crop_box (tuple): 裁剪边界 (left, top, right, bottom)
            scroll_step (int): 滚动步长，None表示自动计算
        
        Returns:
            bool: 是否成功
        """
        try:
            # 如果是本地文件，转换为file://格式
            if os.path.isfile(url):
                url = f"file://{os.path.abspath(url)}"
            
            self.logger.info(f"开始访问: {url}")
            self.driver.get(url)
            
            # 等待页面加载
            self.wait_for_page_load()
            
            # 获取页面完整尺寸
            total_width, total_height = self.get_full_page_size()
            
            # 获取视窗高度
            viewport_height = self.driver.execute_script("return window.innerHeight")
            
            self.logger.info(f"页面高度: {total_height}, 视窗高度: {viewport_height}")
            
            # 如果页面高度小于等于视窗高度，直接截图
            if total_height <= viewport_height:
                self.logger.info("页面高度小于视窗高度，直接截图")
                return self.simple_screenshot(url, output_path, crop_box)
            
            # 设置浏览器窗口大小为页面实际大小（用于全页面截图）
            original_size = self.driver.get_window_size()
            try:
                # 尝试设置窗口大小为页面大小
                self.driver.set_window_size(total_width, total_height)
                time.sleep(2)  # 等待窗口调整完成
                
                # 滚动到顶部
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                
                # 截取整个页面
                screenshot = self.driver.get_screenshot_as_png()
                img = Image.open(io.BytesIO(screenshot))
                
                self.logger.info(f"全页面截图完成，尺寸: {img.width} x {img.height}")
                
            except Exception as e:
                self.logger.warning(f"全页面截图失败，使用滚动截图方法: {e}")
                # 恢复原始窗口大小
                self.driver.set_window_size(original_size['width'], original_size['height'])
                
                # 使用滚动截图方法
                return self._scroll_capture_method(url, output_path, crop_box, scroll_step, total_width, total_height, viewport_height)
            
            finally:
                # 恢复原始窗口大小
                try:
                    self.driver.set_window_size(original_size['width'], original_size['height'])
                except:
                    pass
            
            # 应用边界裁剪
            if crop_box:
                left, top, right, bottom = crop_box
                width, height = img.size
                
                # 处理负值和超出边界的情况
                left = max(0, left) if left >= 0 else max(0, width + left)
                top = max(0, top) if top >= 0 else max(0, height + top)
                right = min(width, right) if right > 0 else min(width, width + right)
                bottom = min(height, bottom) if bottom > 0 else min(height, height + bottom)
                
                img = img.crop((left, top, right, bottom))
                self.logger.info(f"应用边界裁剪: ({left}, {top}, {right}, {bottom})")
            
            # 保存图片
            img.save(output_path, quality=95, optimize=True)
            self.logger.info(f"截图保存成功: {output_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return False
    
    def _scroll_capture_method(self, url, output_path, crop_box, scroll_step, total_width, total_height, viewport_height):
        """
        滚动截图方法（备用方案）
        """
        try:
            # 计算滚动步长
            if scroll_step is None:
                scroll_step = viewport_height - 50  # 留一点重叠
            
            # 计算需要的截图数量
            num_screenshots = max(1, (total_height + scroll_step - 1) // scroll_step)
            
            self.logger.info(f"滚动步长: {scroll_step}, 需要 {num_screenshots} 张截图")
            
            screenshots = []
            
            # 滚动到顶部开始
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            # 滚动截图
            for i in range(num_screenshots):
                scroll_y = i * scroll_step
                
                # 确保不超过页面最大高度
                max_scroll = total_height - viewport_height
                if scroll_y > max_scroll:
                    scroll_y = max_scroll
                
                # 滚动到指定位置
                self.driver.execute_script(f"window.scrollTo(0, {scroll_y});")
                
                # 等待滚动完成
                time.sleep(0.8)
                
                # 截图
                screenshot = self.driver.get_screenshot_as_png()
                img = Image.open(io.BytesIO(screenshot))
                screenshots.append((img, scroll_y))
                
                self.logger.info(f"完成第 {i+1}/{num_screenshots} 张截图，滚动位置: {scroll_y}")
                
                # 如果已经到达页面底部，停止滚动
                if scroll_y >= max_scroll:
                    break
            
            # 拼接图片
            final_image = self.stitch_screenshots(screenshots, total_height, viewport_height, scroll_step)
            
            # 应用边界裁剪
            if crop_box:
                left, top, right, bottom = crop_box
                width, height = final_image.size
                
                # 处理负值和超出边界的情况
                left = max(0, left) if left >= 0 else max(0, width + left)
                top = max(0, top) if top >= 0 else max(0, height + top)
                right = min(width, right) if right > 0 else min(width, width + right)
                bottom = min(height, bottom) if bottom > 0 else min(height, height + bottom)
                
                final_image = final_image.crop((left, top, right, bottom))
                self.logger.info(f"应用边界裁剪: ({left}, {top}, {right}, {bottom})")
            
            # 保存图片
            final_image.save(output_path, quality=95, optimize=True)
            self.logger.info(f"滚动截图保存成功: {output_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"滚动截图失败: {e}")
            return False
    
    def stitch_screenshots(self, screenshots, total_height, viewport_height, scroll_step):
        """
        拼接多张截图
        
        Args:
            screenshots (list): 截图列表，每个元素为(image, scroll_y)
            total_height (int): 页面总高度
            viewport_height (int): 视窗高度
            scroll_step (int): 滚动步长
        
        Returns:
            Image: 拼接后的图片
        """
        if not screenshots:
            raise ValueError("没有截图可以拼接")
        
        # 获取第一张图的宽度
        first_img = screenshots[0][0]
        width = first_img.width
        
        # 使用实际的总高度，但确保不小于所有截图的累计高度
        actual_height = max(total_height, len(screenshots) * viewport_height)
        
        # 创建最终图片
        final_image = Image.new('RGB', (width, actual_height), 'white')
        
        self.logger.info(f"创建拼接画布: {width} x {actual_height}")
        
        for i, (img, scroll_y) in enumerate(screenshots):
            # 计算在最终图片中的位置
            if i == 0:
                # 第一张图片从顶部开始
                paste_y = 0
            elif i == len(screenshots) - 1:
                # 最后一张图片确保覆盖到底部
                paste_y = actual_height - img.height
            else:
                # 中间的图片按照滚动位置放置，但避免重叠
                paste_y = min(scroll_y, i * scroll_step)
            
            # 确保不超出边界
            paste_y = max(0, min(paste_y, actual_height - img.height))
            
            # 处理重叠部分：如果当前图片与上一张有重叠，进行融合
            if i > 0:
                prev_bottom = paste_y
                # 检查是否有重叠
                for j in range(i):
                    prev_img, prev_scroll = screenshots[j]
                    if j == 0:
                        prev_paste_y = 0
                    elif j == len(screenshots) - 1:
                        prev_paste_y = actual_height - prev_img.height
                    else:
                        prev_paste_y = min(prev_scroll, j * scroll_step)
                    
                    prev_paste_y = max(0, min(prev_paste_y, actual_height - prev_img.height))
                    prev_bottom = max(prev_bottom, prev_paste_y + prev_img.height)
                
                # 如果有重叠，调整位置
                if paste_y < prev_bottom:
                    paste_y = prev_bottom
            
            # 再次确保不超出边界
            paste_y = max(0, min(paste_y, actual_height - img.height))
            
            final_image.paste(img, (0, paste_y))
            self.logger.info(f"拼接第 {i+1} 张图片，位置: y={paste_y}, 图片高度: {img.height}")
        
        return final_image
    
    def simple_screenshot(self, url, output_path, crop_box=None):
        """
        简单截图（单张）
        
        Args:
            url (str): 网页URL或本地HTML文件路径
            output_path (str): 输出图片路径
            crop_box (tuple): 裁剪边界 (left, top, right, bottom)
        
        Returns:
            bool: 是否成功
        """
        try:
            # 如果是本地文件，转换为file://格式
            if os.path.isfile(url):
                url = f"file://{os.path.abspath(url)}"
            
            self.logger.info(f"开始访问: {url}")
            self.driver.get(url)
            
            # 等待页面加载
            self.wait_for_page_load()
            
            # 截图
            screenshot = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(screenshot))
            
            # 应用边界裁剪
            if crop_box:
                left, top, right, bottom = crop_box
                width, height = img.size
                
                # 处理负值和超出边界的情况
                left = max(0, left) if left >= 0 else max(0, width + left)
                top = max(0, top) if top >= 0 else max(0, height + top)
                right = min(width, right) if right > 0 else min(width, width + right)
                bottom = min(height, bottom) if bottom > 0 else min(height, height + bottom)
                
                img = img.crop((left, top, right, bottom))
                self.logger.info(f"应用边界裁剪: ({left}, {top}, {right}, {bottom})")
            
            # 保存图片
            img.save(output_path, quality=95, optimize=True)
            self.logger.info(f"截图保存成功: {output_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return False
    
    def close(self):
        """关闭浏览器驱动"""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("浏览器驱动已关闭")
            except Exception as e:
                self.logger.error(f"关闭浏览器驱动时出错: {e}")

def capture_webpage(url, output_path='screenshot.png', window_width=1920, window_height=1080, 
                   device_scale_factor=2.0, full_page=True, headless=True, crop_box=None, scroll_step=None):
    """
    网页截图函数
    
    Args:
        url (str): 网页URL或本地HTML文件路径
        output_path (str): 输出图片路径
        window_width (int): 浏览器窗口宽度
        window_height (int): 浏览器窗口高度
        device_scale_factor (float): 设备缩放因子（用于高清截图）
        full_page (bool): 是否滚动截图整个页面
        headless (bool): 无头模式
        crop_box (tuple): 裁剪边界 (left, top, right, bottom)
        scroll_step (int): 滚动步长
    
    Returns:
        bool: 是否成功
    """
    # 创建截图工具
    screenshot_tool = WebPageScreenshot(
        window_width=window_width,
        window_height=window_height,
        device_scale_factor=device_scale_factor
    )
    
    try:
        # 初始化浏览器驱动
        if not screenshot_tool.setup_driver(headless=headless):
            print("浏览器驱动初始化失败")
            return False
        
        # 执行截图
        if full_page:
            success = screenshot_tool.scroll_screenshot(
                url, 
                output_path, 
                crop_box=crop_box,
                scroll_step=scroll_step
            )
        else:
            success = screenshot_tool.simple_screenshot(
                url, 
                output_path, 
                crop_box=crop_box
            )
        
        if success:
            print(f"截图成功保存到: {output_path}")
            return True
        else:
            print("截图失败")
            return False
            
    except KeyboardInterrupt:
        print("\n用户中断操作")
        return False
    except Exception as e:
        print(f"程序执行出错: {e}")
        return False
    finally:
        # 关闭浏览器驱动
        screenshot_tool.close()


def main():
    """主函数 - 保留用于向后兼容"""
    import argparse
    
    parser = argparse.ArgumentParser(description='网页截图工具')
    parser.add_argument('url', help='网页URL或本地HTML文件路径')
    parser.add_argument('-o', '--output', default='screenshot.png', help='输出图片路径')
    parser.add_argument('-w', '--width', type=int, default=1920, help='浏览器窗口宽度')
    parser.add_argument('--height', type=int, default=1080, help='浏览器窗口高度')
    parser.add_argument('-s', '--scale', type=float, default=2.0, help='设备缩放因子（用于高清截图）')
    parser.add_argument('--full-page', action='store_true', help='滚动截图整个页面')
    parser.add_argument('--headless', action='store_true', default=True, help='无头模式')
    parser.add_argument('--crop', help='裁剪边界 "left,top,right,bottom"')
    parser.add_argument('--scroll-step', type=int, help='滚动步长')
    
    args = parser.parse_args()
    
    # 解析裁剪边界
    crop_box = None
    if args.crop:
        try:
            crop_box = tuple(map(int, args.crop.split(',')))
            if len(crop_box) != 4:
                raise ValueError("裁剪边界必须包含4个值")
        except ValueError as e:
            print(f"裁剪边界格式错误: {e}")
            return False
    
    # 调用新的截图函数
    success = capture_webpage(
        url=args.url,
        output_path=args.output,
        window_width=args.width,
        window_height=args.height,
        device_scale_factor=args.scale,
        full_page=args.full_page,
        headless=args.headless,
        crop_box=crop_box,
        scroll_step=args.scroll_step
    )
    
    return success

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)