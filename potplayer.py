# Copyright (c) 2021 by xfangfang. All Rights Reserved.
#
# Using potplayer as DLNA media renderer
#
# Macast Metadata
# <macast.title>PotPlayer Renderer</macast.title>
# <macast.renderer>PotplayerRenderer</macast.title>
# <macast.platform>win32</macast.title>
# <macast.version>0.4</macast.version>
# <macast.host_version>0.7</macast.host_version>
# <macast.author>xfangfang</macast.author>
# <macast.desc>PotPlayer support for Macast, this is a simple plugin that only supports play and stop.</macast.desc>


import os
import time
import logging
import cherrypy
import threading
import subprocess
import traceback
import win32api, win32con
from enum import Enum
from contextlib import contextmanager

from macast import gui, Setting
from macast.renderer import Renderer
from macast.utils import SETTING_DIR

POTPLAYER_PATH_64 = r'C:\Program Files\Pure Codec\x64\PotPlayerMini64.exe'
POTPLAYER_PATH_32 = r'C:\Program Files\Pure Codec\x64\PotPlayerMini.exe'

logger = logging.getLogger("PotPlayer")
subtitle = os.path.join(SETTING_DIR, r"macast.ass")
# temporary diagnostic log, used to find out what the phone really sends to the renderer
debug_log = os.path.join(SETTING_DIR, r"potplayer_debug.log")


def debug(msg):
    try:
        with open(debug_log, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')
    except Exception:
        pass


def debug_stack(tag):
    try:
        frames = traceback.extract_stack()[-4:-1]
        debug(tag + ' <- ' + ' <- '.join(f'{os.path.basename(f.filename)}:{f.lineno} {f.name}' for f in frames))
    except Exception:
        pass

class SettingProperty(Enum):
    Potplayer_Path = 0

@contextmanager
def win32_reg_open(key, access=None, hive=None):
    if access is None:
        access = win32con.KEY_SET_VALUE
    if hive is None:
        hive = win32con.HKEY_CURRENT_USER
    handle = win32api.RegOpenKey(
        hive,
        key,
        0,
        access)
    yield handle
    win32api.RegCloseKey(handle)

def get_potplayer_path():
    # read Windows registry
    try:
        with win32_reg_open(r'Software\DAUM\PotPlayer64', win32con.KEY_SET_VALUE|win32con.KEY_QUERY_VALUE) as key:
            path = win32api.RegQueryValueEx(key, 'ProgramPath')[0]
            if os.path.exists(path):
                return path
    except:
        pass

    try:
        with win32_reg_open(r'Software\DAUM\PotPlayer', win32con.KEY_SET_VALUE|win32con.KEY_QUERY_VALUE) as key:
            path = win32api.RegQueryValueEx(key, 'ProgramPath')[0]
            if os.path.exists(path):
                return path
    except:
        pass

    # read macast configuration
    path = Setting.get(SettingProperty.Potplayer_Path, None)
    # using default location
    if path is None or not os.path.exists(path):
        if os.path.exists(POTPLAYER_PATH_64):
            return POTPLAYER_PATH_64
        elif os.path.exists(POTPLAYER_PATH_32):
            return POTPLAYER_PATH_32
    else:
        return path

    # cannot find potplayer
    if path is None:
        Setting.set(SettingProperty.Potplayer_Path, POTPLAYER_PATH_64)
    return None

class PotplayerRenderer(Renderer):
    def __init__(self):
        super(PotplayerRenderer, self).__init__()
        self.pid = None
        # current playing url / title / subtitle state
        self.url = None
        self.title = None
        self.sub_file = None
        # PotPlayer only accepts /sub at open time, so we remember whether
        # the subtitle has already been handed to the player.
        self.sub_attached = False
        self.start_position = 0
        self.position_thread_running = True
        self.position_thread = threading.Thread(target=self.position_tick, daemon=True)
        self.position_thread.start()
        # a thread is started here to increase the playback position once per second
        # to simulate that the media is playing.

    def position_tick(self):
        while self.position_thread_running:
            time.sleep(1)
            self.start_position += 1
            sec = self.start_position
            position = '%d:%02d:%02d' % (sec // 3600, (sec % 3600) // 60, sec % 60)
            self.set_state_position(position)

    def set_media_stop(self):
        if self.pid is not None:
            subprocess.Popen(['taskkill', '/f', '/pid', str(self.pid)], creationflags=subprocess.CREATE_NO_WINDOW).communicate()
        self.pid = None
        self.url = None
        self.title = None
        self.sub_file = None
        self.sub_attached = False
        self.set_state_transport('STOPPED')
        cherrypy.engine.publish('renderer_av_stop')

    def start_player(self, url):
        path = get_potplayer_path()
        if path is None:
            subprocess.Popen(['notepad.exe', Setting.setting_path], creationflags=subprocess.CREATE_NO_WINDOW)
            cherrypy.engine.publish('app_notify', "Error", "You should modify 'Potplayer_Path' to your local potplayer and restart Macast.")
            logger.error(f'cannot find potplayer at: {Setting.get(SettingProperty.Potplayer_Path, None)}')
            logger.error(f'cannot find potplayer at: {POTPLAYER_PATH_64}')
            logger.error(f'cannot find potplayer at: {POTPLAYER_PATH_32}')
            return
        try:
            proc = subprocess.Popen(f'"{path}" "{url}" /autoplay', creationflags=subprocess.CREATE_NO_WINDOW)
            self.pid = proc.pid
            debug(f'start_player url={url!r} pid={proc.pid}')
            # wait potplayer to stop
            proc.communicate()
            debug(f'potplayer exited pid={proc.pid}')
            logger.info('Potplayer stopped')
        except Exception as e:
            logger.exception("cannot start potplayer", exc_info=e)
            self.set_media_stop()
            cherrypy.engine.publish('app_notify', "Error", str(e))

    def set_media_url(self, url, start=0):
        debug(f'set_media_url url={url!r} start={start!r}')
        debug_stack('set_media_url')
        self.set_media_stop()
        self.start_position = 0
        self.url = url
        if url is None:
            # 协议层取流失败时会把 None 传进来（B站 playurl 接口报错），
            # 直接放弃，避免用 None 去开播放器、也避免 Macast 核心报 TypeError。
            logger.error('media url is None, skip playing')
            return
        if isinstance(url, str) and url.startswith('bilibili://'):
            # 手机把「云视听小电视」TV 端的内部深链投了过来，PotPlayer 打不开这种链接。
            # 这里只当作"进入投屏接收状态"，真正的视频地址会由 NVA 通道随后下发。
            logger.info(f'ignore bilibili deeplink: {url}')
            self.set_state_transport("PLAYING")
            cherrypy.engine.publish('renderer_av_uri', url)
            return
        threading.Thread(target=self.start_player, daemon=True, kwargs={'url': url}).start()
        self.set_state_transport("PLAYING")
        cherrypy.engine.publish('renderer_av_uri', url)

    def reopen_with_subtitle(self):
        """ PotPlayer 只能在打开媒体时通过 /sub 指定字幕文件，
        所以拿到弹幕文件后再用 /current 把同一个地址重开一次，把字幕(和标题)挂上去。
        """
        path = get_potplayer_path()
        if path is None or self.url is None or self.sub_file is None:
            return
        if not isinstance(self.url, str) or self.url.startswith('bilibili://'):
            return
        if not os.path.exists(self.sub_file):
            logger.error(f'subtitle file not found: {self.sub_file}')
            return
        args = f'"{path}" /current "{self.url}" /sub="{self.sub_file}" /autoplay'
        if self.title:
            args += f' /title="{self.title}"'
        try:
            self.sub_attached = True
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
            logger.info(f'reopen with subtitle: {self.sub_file}')
            debug(f'reopen_with_subtitle args={args}')
        except Exception as e:
            self.sub_attached = False
            logger.exception("cannot reopen potplayer with subtitle", exc_info=e)

    def set_media_title(self, title):
        debug(f'set_media_title title={title!r}')
        self.title = title

    def set_media_sub_file(self, data):
        if isinstance(data, dict):
            self.sub_file = data.get('url', subtitle)
        else:
            self.sub_file = data
        debug(f'set_media_sub_file sub_file={self.sub_file!r} attached={self.sub_attached}')
        if not self.sub_attached:
            self.reopen_with_subtitle()

    def set_media_sub_show(self, show):
        # PotPlayer 没有命令行开关可以隐藏字幕，关闭只能靠热键，这里不做处理
        if show and not self.sub_attached:
            self.reopen_with_subtitle()

    def stop(self):
        super(PotplayerRenderer, self).stop()
        self.set_media_stop()
        logger.info("PotPlayer stop")

    def start(self):
        super(PotplayerRenderer, self).start()
        logger.info("PotPlayer start")


if __name__ == '__main__':
    gui(PotplayerRenderer())
    # or using cli to disable taskbar menu
    # from macast import cli
    # cli(PotplayerRenderer())