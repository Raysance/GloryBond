import cv2
import threading
import time
from .. import zdynamic as dmc
from ..ztime import time_r
from ..ztime import calc_gap

class RTMPListener:
    def __init__(self, url, save_path, roleid):
        self.url = url
        self.out_file = save_path
        self.roleid=roleid
        self.running = False       # 控制是否继续监听
        self.take_screenshot = False  # 截图指令
        self.thread = None

        dmc.RTMPPlayer=roleid
        dmc.RTMPStatus=True

    def start(self):
        """启动监听线程"""
        self.running = True
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def stop(self):
        """停止监听"""
        self.running = False
        if self.thread:
            self.thread.join()

    def screenshot(self):
        """外部触发截图"""
        time_now=time_r()
        if (dmc.RTMPShotLastTime and calc_gap(time_now,dmc.RTMPShotLastTime)<10): return False
        self.take_screenshot = True
        dmc.RTMPShotLastTime=time_now
        return True

    def _listen(self):
        print(self.url)
        fail_count = 0
        max_fail = 30  # 允许最多连续 30 次失败，大约 1 秒左右
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            print("无法打开 RTMP 流")
            dmc.RTMPStatus=False
            return

        while self.running:
            ret, frame = cap.read()
            if not ret:
                fail_count += 1
                if fail_count >= max_fail:
                    print("流已结束")
                    break
                continue
            else:
                fail_count = 0

            # 如果收到截图命令
            if self.take_screenshot:
                cv2.imwrite(self.out_file, frame)
                print(f"截图已保存到 {self.out_file}")
                self.take_screenshot = False

            # （可选：实时展示）
            # cv2.imshow("RTMP Stream", frame)
            # if cv2.waitKey(1) & 0xFF == ord('q'):
            #     break
        dmc.RTMPStatus=False
        cap.release()
        cv2.destroyAllWindows()
