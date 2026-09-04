# clipcompare

把两个视频拼成一个对比视频的命令行工具，三种呈现方式。只依赖 `ffmpeg` / `ffprobe`，Python 侧零第三方依赖。

```bash
clipcompare side input.mp4 output.mp4    # 并排
clipcompare wipe before.mp4 after.mp4    # 扫描揭示
clipcompare pip  before.mp4 after.mp4    # 画中画
```

`sbs` 是这个命令的短别名，敲 `sbs side ...` 完全等价。

## 三种模式

| 模式 | 画面 | 适合 |
|------|------|------|
| **side** | 两段同时在画面上，竖版左右并排、横版上下堆叠 | 内容不同、需要逐帧对照 |
| **wipe** | 一条缓动的白线扫过，原地把 B 揭示在 A 之上 | 同机位同时间点的前后对比（调色、修复、VFX） |
| **pip** | 一段全屏，另一段作为圆角小窗嵌在角落 | 主推成片、原片只作佐证 |

`wipe` 和 `pip` 要求两段素材**同机位、同时间点**——它们是「原地对比」，工具不做内容对位。`side` 没这个要求。

## 安装

```bash
uv tool install git+https://github.com/thejiajun/clipcompare
```

升级 / 卸载：

```bash
uv tool upgrade clipcompare
uv tool uninstall clipcompare
```

> 这个工具早期叫 `sbs-video`。如果机器上装的是旧名字，先卸载再装新的：
> `uv tool uninstall sbs-video && uv tool install git+https://github.com/thejiajun/clipcompare`
> —— `--force` 重装不会清掉旧包目录，会留下上一版的残留。

另外需要 `ffmpeg`，且编译时带 `--enable-libfreetype`（Homebrew 的 `ffmpeg` / `ffmpeg-full` 默认都带，标签靠它画）：

```bash
brew install ffmpeg
```

## 标签

三种写法，按需选：

```bash
-l "ORIGINAL,EDITED"     # 两个一起写
-A "原始素材"             # 只写第一个，第二个仍取文件名
-B "PIKA 成片"            # 只写第二个
--no-labels              # 都不要
```

不写就用两个文件名（去后缀、转大写）。默认字体是自带的 **TikTok Sans Medium**（从官方可变字体按 `wght=500` 实例化——它自带的默认实例是 Light，压在画面上太单薄）。TikTok Sans 只有拉丁字形，所以中文标签会自动换系统黑体，中英混排也正常。三种模式都画标签——`wipe` 的标签跟着扫描线在原地切换（扫描前显示 A，扫描后显示 B），`pip` 的小窗标签会按小窗尺寸缩小字号。

## 通用参数

所有模式都吃这些：

| 参数 | 说明 |
|------|------|
| `-o, --out PATH` | 输出文件 |
| `-l / -A / -B / --no-labels` | 标签，见上 |
| `--font PATH` | 标签字体。默认自带 TikTok Sans Medium，中文自动换系统黑体 |
| `--color-a / --color-b HEX` | 两个标签的颜色，默认白色 + 淡紫 `#cfc3ff` |
| `--fit cover\|contain` | `cover` 裁切填满（默认）；`contain` 留黑边保留完整画面 |
| `--audio a\|b\|both\|none` | 默认 `b`；`both` 混音；某段没音轨时自动退回有音轨的那段 |
| `--fps N` | 强制输出帧率，默认对齐到两段里较高的那个 |
| `--crf N` / `--preset NAME` | x264 画质档位，默认 `18` / `medium` |
| `-n, --dry-run` | 只打印 ffmpeg 命令（打印出来的可以直接粘贴执行） |
| `--open` | 渲染完直接打开（macOS） |

## 各模式专有参数

### side

| 参数 | 说明 |
|------|------|
| `--layout auto\|lr\|tb` | 默认 auto：竖版/方形左右并排，横版上下堆叠 |
| `--panel PX` | 每块画面的**短边**，默认 1080 —— 竖版出 2160×1920，横版出 1920×2160 |
| `--length shortest\|longest` | `longest` 把较短那段的最后一帧冻住补齐 |
| `--divider PX` | 中缝分隔线粗细，默认 4，`0` 关闭。线是叠加绘制的，输出尺寸不变，调粗会盖住两侧画面各一半线宽 |

### wipe

| 参数 | 说明 |
|------|------|
| `--direction lr\|rl\|tb\|bt` | 扫描方向，默认 `lr`（B 从左边被揭示出来） |
| `--pace early\|balanced\|late` | 扫描在片长的哪个位置触发，默认 `early` |
| `--wipe-start SEC\|N%` | 直接指定起点，覆盖 `--pace` |
| `--wipe-dur SEC` | 扫描时长，默认 0.35 |
| `--stroke PX` | 白线粗细（1080 基准），默认 3 |
| `--trim-to SEC` | 成片裁到 N 秒 |
| `--panel PX` | 输出短边，默认 0 = 保持 A 的原始分辨率 |

`--pace` 三档的起点（片长的百分比，带上下限）：`early` 22%（0.4–0.9s）· `balanced` 30%（0.6–1.1s）· `late` 45%（0.9–1.8s）。扫描时长统一 0.35s。

### pip

| 参数 | 说明 |
|------|------|
| `--inset a\|b` | 哪一段做小窗，默认 `a`（于是 B 全屏） |
| `--corner tl\|tr\|bl\|br` | 小窗在哪个角，默认 `tr` |
| `--inset-scale F` | 小窗占主画面宽度的比例，默认 0.30 |
| `--margin F` | 小窗离边缘的距离（占宽度比例），默认 0.025 |
| `--radius PX` | 圆角半径（1080 基准），默认 22 |
| `--stroke PX` | 白边粗细（1080 基准），默认 3，`0` 关闭边框 |
| `--border COLOR` | 边框颜色，默认 white |
| `--length shortest\|longest` | 同 side |
| `--panel PX` | 输出短边，默认 0 = 保持主画面原始分辨率 |

## 常用例子

```bash
# 最省事：文件名当标签，布局自动判断
clipcompare side input.mp4 output.mp4

# 出 4K，指定标签，两段声音混在一起
clipcompare side orig.mp4 vfx.mp4 -l "ORIGINAL,EDITED" --panel 2160 --audio both

# 两段画幅不一样，留黑边保完整画面；短的那段冻帧补齐
clipcompare side a.mov b.mov --fit contain --length longest -o cmp.mp4

# 调色前后：扫描线晚一点触发，线粗一点
clipcompare wipe raw.mp4 graded.mp4 --pace late --stroke 5 -l "RAW,GRADED"

# 扫描起点直接定在第 1.2 秒，成片裁到 3 秒
clipcompare wipe a.mp4 b.mp4 --wipe-start 1.2 --trim-to 3

# 成片全屏、原片放右下角小窗
clipcompare pip original.mp4 final.mp4 --inset a --corner br --inset-scale 0.25

# 看看它到底会跑什么命令
clipcompare pip a.mp4 b.mp4 --dry-run
```

## 实现说明

一条 filter_complex 一次成片（pip 会先单独渲一张遮罩）：

```
side   [0:v] fps → scale → (tpad 冻帧) ┐
                                        ├ hstack/vstack → drawbox 分隔线 → drawtext ×2
       [1:v] 同上                       ┘

wipe   [0:v] fps → scale ─────────────┐
                                       ├ xfade(custom expr) → drawtext ×2(按时间启停)
       [1:v] 同上 → trim(扫描起点) ────┘

pip    [main] fps → scale ────────────┐
                                       ├ overlay → drawtext ×2
       [inset] fps → scale → pad(白边) ┴ alphamerge(圆角遮罩)
```

几个值得记住的点：

- **画面尺寸由第一段素材的比例决定**，`side` 的 `--panel` 给的是每块画面的**短边**。9:16 素材 `--panel 1080` 得到 1080×1920 的画面块、2160×1920 的成片。
- **标签走 `textfile=`**，不走 `text=`。filtergraph 里的引号、冒号、反斜杠转义是个坑，读文件可以完全绕开；再配上 `expansion=none`，文件名里带 `%{n}` 这种也会原样显示。
- **帧率必须先对齐**。堆叠和 xfade 都要求两路同步，24fps 和 30fps 直接拼会错位，所以两路都先过一遍 `fps=`，并且保留精确有理数（29.97 是 `30000/1001`，不是 `29.97`）。
- **旋转元数据要单独读**。手机竖拍的素材容器里存的是 1920×1080 + rotation，ffmpeg 解码时会自动转正，但判断布局用的宽高得自己换过来。
- **中文标签会自动换字体**。自带的 TikTok Sans 只有拉丁字形（910 个字符），而标签默认取自文件名 —— 中文文件名走默认路径就会渲染成豆腐块。所以带中文的标签会自动找系统黑体（`STHeiti Medium.ttc` 等），两个标签各自判断。用 fontconfig 按字族名找（`font=PingFang SC`）反而会解析到渲染不出中文的 face，所以只按文件路径找。

### wipe 的两个坑

都是实打实调出来的：

1. **xfade 的 `P` 是 1→0，不是 0→1**。缓动要挂在 `q = 1-P` 上，否则扫描会反向：先跳到 B、倒着扫回去、再弹回来。
2. **缓动表达式必须内联，不能用 `st()`/`ld()` 寄存器**。xfade 会把切片分到多个线程上跑，而这些线程共享表达式寄存器数组，st/ld 会竞争，结果是画面上散落白点噪声。把 ease-in-out-circ 重复内联写几遍是无竞争的，而且不慢——表达式只在扫描那几帧上求值。

另外 B 路会先 `trim` 到扫描起点，这样扫描过程中线两侧显示的是**同一时间戳**，运动在线的两边是连续的；不 trim 的话两侧会各走各的时间。

### pip 的圆角

不用浏览器截图，用 `geq` 生成两张遮罩：

```
小窗画面  → 半径 R 切圆角
边框底板  → 半径 R+stroke 切圆角，填边框色
画面盖在底板上，四边各内缩 stroke
```

露出来的那圈底板就是边框，沿弧线宽度均匀。

**为什么要两张而不是一张**：曾经的做法是先给画面 `pad` 一圈边框色再整体切一次圆角 —— 那是错的。越靠近角落，遮罩往里切的深度约 `0.29×(R+stroke)`，远大于边框厚度 `stroke`，于是边框在四条弧线上被整段切掉，露出画面自己的直角。圆角越大豁口越明显。

两张遮罩都用**到圆角圆心的距离场**而不是硬阈值：

```
alpha = clip(255 * (r - distance + 0.5), 0, 255)
```

所以边缘有一像素的过渡，圆角是抗锯齿的。

遮罩靠 `-loop 1` 喂进来，是**无限流**，所以每个碰到遮罩的 `alphamerge` 都必须写 `shortest=1` —— 否则小窗流会继承这个无限长度，最终的 `overlay` 失去结束条件，`--length longest` 会一直渲染下去不停。

## 开发

```bash
git clone git@github.com:thejiajun/clipcompare.git
cd clipcompare
uv sync
uv run pytest
```

装本地改动版：

```bash
uv tool install --force .
```

构建后端用 hatchling 而不是 setuptools，这是踩过坑换的：setuptools 的 `build/lib/` 是增量的，源码里删掉的文件不会从那里消失，会被重新打进 wheel —— 包改名之后，旧包目录和旧字体就这么一路跟着装进了新环境，而且 `--force` 重装还会复用缓存的 wheel，让人以为改动没生效。

每个模式的 `build()` 都是纯函数：进两个 `ClipInfo` 加一组选项，出 ffmpeg 的 argv。所以滤镜图能脱离 ffmpeg 测试，79 个测试跑完不到 0.1 秒。

## 已知边界

- `wipe` / `pip` 要求两段素材同机位同时间点，工具不做内容对位。
- 标签是直角药丸、没有字间距 —— ffmpeg 的 `drawtext` 画不了圆角和 letter-spacing。要圆角药丸得换成离屏渲染 PNG 再叠，那会引入浏览器依赖，不值。
- 中文字体回退目前只覆盖 macOS 自带黑体和常见的 Linux Noto CJK 路径。都找不到时会提示你用 `--font` 指定。
- 只支持两段素材。三段以上的网格对比不在这里。

## License

MIT
