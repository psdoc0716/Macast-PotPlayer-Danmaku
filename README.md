# Macast-PotPlayer-Danmaku

让 [Macast](https://github.com/xfangfang/Macast) 用 PotPlayer 播放 B 站投屏，并且**带弹幕**。

这个仓库是 Macast 插件的组合，包含两部分：

| 文件 | 类型 | 作用 |
| --- | --- | --- |
| `nirvana.py` | Protocol | NVA 协议（B 站「哔哩必连」），负责取视频流、下载弹幕并转成 ASS 字幕 |
| `potplayer.py` | Renderer | 用 PotPlayer 播放，并把生成好的弹幕 ASS 挂上去 |

配合使用后，手机 B 站客户端点「投屏」到 Macast，电脑上的 PotPlayer 就会播放高清视频，
并叠加 B 站风格的滚动弹幕。

## 相比原版插件做了什么

- **补上了 TV 端接口签名**：B 站云视听小电视（`android_tv_yst`）接口要求
  `appkey + ts + sign` 签名，原实现缺少签名会直接 400，这里补上了 md5 签名逻辑。
- **弹幕 XML 解码兜底**：弹幕接口返回的是不带 zlib 头的裸 deflate 数据，
  这里按 `wbits = -15 / 15 / 31` 依次尝试解压，避免 `ContentDecodingError`。
- **优先选单文件流**：取流时优先使用 `durl`（单文件 mp4），因为 PotPlayer 对
  分片流（`dash`）支持不好。
- **拿到弹幕后再挂字幕**：PotPlayer 只能在打开媒体时通过 `/sub` 指定字幕文件，
  所以拿到弹幕 ASS 之后会用 `/current` 把同一个地址重开一次，同时用 `/title` 设置标题。
- **弹幕外观可调**：新增字体、字号、透明度、覆盖范围四个设置项。
- **容错**：协议层取流失败传入 `None`、或手机发来 `bilibili://` 深链时不崩溃。

## 环境要求

- Windows
- [Macast](https://github.com/xfangfang/Macast) 0.7
- [PotPlayer](https://potplayer.daum.net/)
- 手机端：哔哩哔哩 App（需要支持「哔哩必连」投屏）

## 安装

1. 打开 Macast 配置目录：右键点击托盘里的 Macast 图标 → **打开配置目录**
   （默认在 `%LOCALAPPDATA%\xfangfang\Macast`）。
2. 把两个文件放进对应子目录：

   ```
   <配置目录>\protocol\nirvana.py
   <配置目录>\renderer\potplayer.py
   ```

3. 重启 Macast。
4. 右键托盘图标 → **Plugins**，分别选中 **NVA Protocol** 和 **PotPlayer Renderer**。

## 使用方法

1. 手机和电脑连同一个局域网，手机打开哔哩哔哩 App。
2. 播放视频时点右上角「投屏」，选择列表里的 Macast 设备。
3. PotPlayer 会自动打开并开始播放，弹幕以滚动形式叠加在画面上。

### 告诉插件 PotPlayer 在哪

插件按这个顺序查找 PotPlayer：

1. 注册表 `HKCU\Software\DAUM\PotPlayer64` 的 `ProgramPath`
2. 注册表 `HKCU\Software\DAUM\PotPlayer` 的 `ProgramPath`
3. 配置文件 `macast_setting.json` 里的 `Potplayer_Path`
4. 默认路径 `C:\Program Files\Pure Codec\x64\PotPlayerMini64.exe`

都找不到时会弹出记事本让你改 `Potplayer_Path`，改完重启 Macast。

### 弹幕设置

首次运行后，`macast_setting.json` 里会多出 4 个可调项：

| 设置项 | 含义 | 默认值 | 建议范围 |
| --- | --- | --- | --- |
| `Danmaku_Font` | 字体名，需为本机已安装的字体 | `sans-serif` | 如 `微软雅黑`、`黑体` |
| `Danmaku_FontSize` | 字号，占视频高度的百分比 | `6` | 1 ~ 20（`6` 约等于 B 站 25 号字） |
| `Danmaku_Opacity` | 不透明度，越大越实 | `80` | 0 ~ 100 |
| `Danmaku_Height` | 覆盖范围，占视频高度的百分比 | `100` | 10 ~ 100，调小则弹幕只占上方 |

改法二选一：

- 右键托盘图标 → **高级设置**，在浏览器页面里直接改这几个值并保存，Macast 会自动重启；
- 或直接编辑 `macast_setting.json` 再手动重启 Macast。

填了非法值会自动回退到默认值。**改完都需要重启 Macast 才生效。**

## 重要：一定要关掉 PotPlayer 的自定义字幕样式

PotPlayer 有一个默认打开的选项会用「用户自定义样式」覆盖 ASS 文件里的样式，
它会把弹幕的**颜色、描边、`\move` 移动、`\pos` 定位**全部吃掉，
结果弹幕会变成白色、静止、从屏幕底部一行行往上堆的普通字幕——看起来就像字幕而不是弹幕。

关掉它二选一：

- **改注册表**：把
  `HKEY_CURRENT_USER\Software\DAUM\PotPlayerMini64\Settings` 下的
  `ForceSetDefStyle` 改成 `0`；
- **改界面**：PotPlayer → 选项 → 字幕 → ASS/SSA 字幕样式 →
  不要勾选「使用用户自定义的样式」。

注意这个开关是**全局的**，会影响所有 ASS 字幕是否使用文件自带的样式。

## 已知限制

- **暂停 / 音量 / 进度是模拟的**：PotPlayer 没有提供命令行控制接口，
  Macast 里显示的播放进度是按秒自增模拟的，和真实播放位置可能对不上。
- **关不掉弹幕**：PotPlayer 没有命令行开关可以隐藏字幕，所以手机端「关闭弹幕」
  按钮不会真的隐藏已挂载的弹幕。
- 只支持 Windows。

## 致谢

`nirvana.py` 和 `potplayer.py` 都基于 [xfangfang/Macast-Plugin](https://github.com/xfangfang/Macast-Plugin)
中的同名插件修改而来，原作者 xfangfang。本仓库只是在其基础上补齐了取流签名、
弹幕渲染与外观设置。