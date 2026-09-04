# sbs

把两个视频拼成一个对比视频的命令行工具。只依赖 `ffmpeg` / `ffprobe`，Python 侧零第三方依赖。

```bash
sbs render input.mp4 output.mp4
```

竖版素材左右并排、横版素材上下堆叠，标签用文件名自动生成，帧率和时长不一致会自己对齐。

## 安装

```bash
uv tool install git+https://github.com/thejiajun/sbs-video
```

升级 / 卸载：

```bash
uv tool upgrade sbs-video
uv tool uninstall sbs-video
```

另外需要 `ffmpeg`，且编译时带 `--enable-libfreetype`（Homebrew 的 `ffmpeg` / `ffmpeg-full` 默认都带，标签靠它画）：

```bash
brew install ffmpeg
```

## 用法

```
sbs render <clip-a> <clip-b> [options]
```

不给任何参数时，工具自己决定这些事：

| 事项 | 默认行为 |
|------|----------|
| 布局 | 竖版/方形素材左右并排，横版素材上下堆叠 |
| 标签 | 用两个文件名（去后缀、转大写）当标签 |
| 尺寸 | 每块画面短边 1080 —— 竖版出 2160×1920，横版出 1920×2160 |
| 帧率 | 对齐到两段里较高的那个 |
| 时长 | 到较短的那段为止 |
| 声音 | 用第二段的声音（没有就静音） |
| 输出 | 当前目录下 `<a>-vs-<b>.mp4` |

### 参数

| 参数 | 说明 |
|------|------|
| `-o, --out PATH` | 输出文件 |
| `-l, --labels "A,B"` | 自定义标签文字，例如 `"ORIGINAL,EDITED"` |
| `--no-labels` | 不画标签 |
| `--layout auto\|lr\|tb` | 强制左右并排 / 上下堆叠 |
| `--panel PX` | 每块画面的短边，默认 1080，出 4K 用 2160 |
| `--fit cover\|contain` | `cover` 裁切填满（默认）；`contain` 留黑边保留完整画面 |
| `--length shortest\|longest` | `longest` 会把较短那段的最后一帧冻住补齐 |
| `--audio a\|b\|both\|none` | `both` 会混音；某一段没音轨时自动退回有音轨的那段 |
| `--divider PX` | 中缝分隔线粗细，默认 4，`0` 关闭 |
| `--font PATH` | 标签字体，默认用自带的 Space Mono Regular |
| `--color-a / --color-b HEX` | 两个标签的颜色，默认白色 + 淡紫 `#cfc3ff` |
| `--fps N` | 强制输出帧率 |
| `--crf N` / `--preset NAME` | x264 画质档位，默认 `18` / `medium` |
| `-n, --dry-run` | 只打印 ffmpeg 命令，不渲染（打印出来的命令可以直接粘贴执行） |
| `--open` | 渲染完直接打开（macOS） |

### 常用例子

```bash
# 最省事：文件名当标签，布局自动判断
sbs render input.mp4 output.mp4

# 出 4K，指定标签，两段声音混在一起
sbs render orig.mp4 vfx.mp4 -l "ORIGINAL,EDITED" --panel 2160 --audio both

# 两段画幅不一样，留黑边保留完整画面；短的那段冻帧补到一样长
sbs render a.mov b.mov --fit contain --length longest -o cmp.mp4

# 只要画面，不要标签和分隔线
sbs render a.mp4 b.mp4 --no-labels --divider 0

# 看看它到底会跑什么命令（打印出来的可以直接粘贴执行）
sbs render a.mp4 b.mp4 --dry-run
```

## 实现说明

一条 filter_complex 一次成片：

```
[0:v] fps → scale(cover/contain) → setsar → (tpad 冻帧)  ┐
                                                          ├ hstack/vstack → drawbox 分隔线 → drawtext ×2 → x264
[1:v] 同上                                                ┘
```

几个值得记住的点：

- **画面尺寸由第一段素材的比例决定**，`--panel` 给的是每块画面的**短边**。所以 9:16 素材 `--panel 1080` 得到 1080×1920 的画面块、2160×1920 的成片。
- **标签走 `textfile=`**，不走 `text=`。filtergraph 里的引号、冒号、反斜杠转义是个坑，读文件可以完全绕开；再配上 `expansion=none`，文件名里带 `%{n}` 这种也会原样显示。
- **帧率必须先对齐**。`hstack` / `vstack` 要求两路同步，24fps 和 30fps 直接拼会错位，所以两路都先过一遍 `fps=`，并且保留精确有理数（29.97 是 `30000/1001`，不是 `29.97`）。
- **旋转元数据要单独读**。手机竖拍的素材容器里存的是 1920×1080 + rotation，ffmpeg 解码时会自动转正，但判断布局用的宽高得自己换过来。

`render.build()` 是纯函数：进两个 `ClipInfo` 加一组选项，出 ffmpeg 的 argv。所以滤镜图能脱离 ffmpeg 测试。

## 开发

```bash
git clone git@github.com:thejiajun/sbs-video.git
cd sbs-video
uv sync
uv run pytest
```

装本地改动版：

```bash
uv tool install --force .
```

## 已知边界

- 只做 side-by-side。wipe 揭示、画中画不在这里。
- 标签是直角药丸、没有字间距 —— ffmpeg 的 `drawtext` 画不了圆角和 letter-spacing。要圆角药丸得换成离屏渲染 PNG 再叠，那会引入浏览器依赖，不值。
- 两段素材必须自己对齐好时间点。工具不做内容对位，只做画面拼接。

## License

MIT
