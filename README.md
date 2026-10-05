# clipcompare

把两个或更多视频拼成一个对比视频的命令行工具，四种呈现方式。只依赖 `ffmpeg` / `ffprobe`，Python 侧零第三方依赖。

```bash
clipcompare side input.mp4 output.mp4    # 并排
clipcompare wipe before.mp4 after.mp4    # 扫描揭示
clipcompare pip  before.mp4 after.mp4    # 画中画
clipcompare grid a.mp4 b.mp4 c.mp4 ...   # N×M 网格
```

`sbs` 是这个命令的短别名，敲 `sbs side ...` 完全等价。

## 四种模式

| 模式 | 画面 | 适合 |
|------|------|------|
| **side** | 两段同时在画面上，竖版左右并排、横版上下堆叠 | 内容不同、需要逐帧对照 |
| **wipe** | 一条缓动的白线扫过，原地把 B 揭示在 A 之上 | 同机位同时间点的前后对比（调色、修复、VFX） |
| **pip** | 一段全屏，另一段作为圆角小窗嵌在角落 | 主推成片、原片只作佐证 |
| **grid** | 任意多段按阅读顺序铺成 N×M 网格，一起播或轮流播 | 一次看完一批版本（多语言配音、多组参数、多个模型） |

`wipe` 和 `pip` 要求两段素材**同机位、同时间点**——它们是「原地对比」，工具不做内容对位。`side` 没这个要求。

## 纯音频片段

任何模式都可以直接吃 mp3 / wav / m4a / aac / ogg / flac（或任何 ffprobe 认为没有画面的文件；mp3 里内嵌的封面图不算画面）。纯音频片段在画面上是一块深色面板，底部一条跟着声音实时跳动的波形带，上方留给标签和提示词。

最常用的是 `grid --sequential`：一次只播一段，正在播的那格描边、只有它的波形在动，声音跟着它走，两段之间默认停 0.5 秒。全是音频时没有比例可跟，四段以内排成一行、铺满 1920×1080：

```bash
# 两版配音：左边播完停半秒，再播右边
sbs grid v3.mp3 v4.mp3 --sequential -l "Eleven v3,Eleven v4"

# 五个角色各一组：每组左右两格、顶部写角色名，五组接着播
sbs grid kali-v3.mp3 kali-v4.mp3 alia-v3.mp3 alia-v4.mp3 ... \
  --sequential --group 2 -l "Eleven v3,Eleven v4" --title "Kali,Alia,..."
```

## 图片

`side` 和 `grid` 也吃 png / jpg / webp 静态图。**全是图片时出一张图**（默认 `.png`，`-o` 写 `.jpg` / `.webp` 就出对应格式），版式和视频一样：标题条、标签、设计系统配色和 Telka 字体、格子间的缝都在。

- 四张以内默认排成一行；`--cols` / `--rows` 照样能改。
- 图片按原尺寸放，不会被自动放大（单格短边上限仍是 1080）；要放大用 `--panel`。
- 颜色按全彩 RGB 输出，不像视频那样降到 yuv420p，细节对比不失真。
- 提示词（`--captions` 或 manifest 的 `prompt`）显示为格子里的静态文字：整段一次显示，底色只盖住文字那几行。
- 图片和视频 / 音频混在一起时，图片在整段视频时长内保持不动；`--sequential` 时它也有自己的一轮。
- `--sequential`、`--pause`、`--head`、`--audio` 对纯图片不起作用；`--group`、`--html`、`wipe`、`pip` 不支持图片，会直接报错说明。

```bash
# 三张截图拼一行，顶部写标题
sbs grid c1.png c2.png c3.png -o compare.png \
  -l "Kling original · 13.0 Mbps,Old fit crf 18 · 5.1 Mbps,New fit copy · 13.0 Mbps" \
  --title "Yuna b01 · forehead crop 2x"
```

## 提示词对比（manifest）

对比 TTS / 生成模型的不同版本时，真正想看的是「提示词改了什么、听起来差在哪」。把片段、标签、提示词、组名写进一个 JSON，一条命令出整段对比视频，外加一个可以来回切换版本的网页：

```bash
sbs grid --manifest megan-project/clips.json --html megan-project/compare.html
```

```json
{
  "titles": ["Alia", "Yasmine"],
  "out": "megan-project-sbs.mp4",
  "clips": [
    {"file": "megan-project/alia-1-v3-plain.mp3", "label": "v3 · plain", "prompt": "...", "baseline": true,
     "segments": [{"text": "...", "start": 0, "end": 16.2, "estimated": true}, ...]},
    {"file": "https://cdn.example.com/alia-2.mp3", "label": "v3 · bracket", "prompt": "[warm] ..."}
  ]
}
```

- **分组**：组大小 = 片段数 ÷ 组名数（也可以写 `"group"`）；manifest 默认轮流播放（`"sequential": false` 关掉），组间照常停 0.5 秒。
- **路径**：`file` 先在 manifest 所在文件夹找，再找上一级，再找当前目录；也可以是 http(s) URL。`out` 写在 manifest 旁边。
- **manifest 本身**可以是文件、URL（`--manifest https://…`，需要鉴权时加 `--header "Authorization: Bearer …"`）或标准输入（`--manifest -`）。URL manifest 里的相对 `file` 按那个 URL 解析，`out` 只取文件名、写到当前目录。
- **URL 片段**先下载到 `~/.cache/clipcompare/media/`（按 URL 缓存，带 curl 的 User-Agent——有的媒体服务器会拒绝 Python 默认 UA），再从本地文件渲染：一段片段要被读好几次（probe、找开头黑帧、静止帧），本地文件每次都一样快、一样完整。

**视频里看到的**：每格左上角是标签，下面一行是它跟 baseline 比的差异摘要（`+6 tags · 10 emphasis · no 'energetic'`，baseline 那格写 `baseline`）。轮到哪格，哪格中间就大字显示提示词，跟着声音一段一段往前走：正在说的那段全亮，前一段末行和后面几段调暗；段落时间是估算的会注一行 `timing estimated`。没有 `segments` 的就整段一次显示。字号按**最长的一段**（不是整段提示词）来定，从 30px 往下缩到放得下为止，最小 15px，再放不下才用 … 截断；`--group` 的所有组共用一个字号。

**差异标记**（视频和网页一样）：先去掉 `[tag]`，按词用 difflib 对齐 baseline：

| 标记 | 含义 |
|------|------|
| 紫色 `--ds-accent-700` 的 `[tag]` | baseline 没有的指令（tag 里按逗号拆开比，`[speaking quickly, warm]` 只要有一个新指令就算新） |
| 紫色下划线 | 同一个词只改了大小写或标点（`TEN`、`saved...`），或 baseline 没有的标点（`—`） |
| 普通米白 `--ds-eggshell` | 其他（包括 baseline 也有的 tag） |

画法：ffmpeg 的 `drawtext` 一次只能画一种颜色、也不能画下划线，所以排版在 Python 里做——直接从字体文件读字宽（`metrics.py`，不依赖 Pillow），按样式切成一段段，每段一个 drawtext 画在算好的 x 上，下划线是量好宽度的 drawbox。每个（片段，段落）先渲成一张 PNG，正片只在对应时间段叠上去。

**网页（`--html OUT.html`）**：一个自包含的 HTML，CSS / JS 内联、不连 CDN，`file://` 离线可用；字体用本机的 Telka，没有就退回系统无衬线。每组一个播放器：

- 点版本按钮或按 `1`–`9` 切换，**停在剧本里的同一位置**：两边都有段落时间时按「第几段、段内百分比」换算，否则按时长比例换算；空格播放 / 暂停。
- 提示词带同样的差异标记，正在说的那段高亮并滚到顶部。
- 每个版本标出时长和 WPM（去掉 tag 后的词数 ÷ 时长）。
- 本地音频按相对网页的路径引用、不复制；URL 原样引用，加 `--copy-media` 会下载到网页旁边的 `media/`，整个文件夹拷走也能离线听。
- 单写 `--html` 只出网页；有 `-o` 或 manifest 里有 `out` 时视频和网页一起出。

不用 manifest 也能加提示词：`--captions prompts.json`（字符串数组，每段一个，`null` 表示没有）；没有 baseline 时所有 tag 都标紫、没有差异摘要。

## 安装

```bash
uv tool install git+https://github.com/thejiajun/clipcompare
```

升级 / 卸载：

```bash
uv tool upgrade clipcompare
uv tool uninstall clipcompare
```

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

不写就用两个文件名（去后缀、转大写）。默认字体跟 Pika 设计系统（`@mellis-labs/design-system`）走：标签用 **Telka Medium**（`--ds-font-sans`），`--title` 用 **Telka Extended Medium**（`--ds-font-display`）。Telka 是商业授权字体，设计系统只从 Pika CDN 加载、不随包分发，所以这里**不打包**：本机装了（`~/Library/Fonts`、`/Library/Fonts` 或 Linux 的字体目录里有 `Telka-Medium.otf` / `Telka-ExtendedMedium.otf`）就用，没装就退回自带的 **TikTok Sans Medium**（从官方可变字体按 `wght=500` 实例化——它自带的默认实例是 Light，压在画面上太单薄）。两者都只有拉丁字形，所以中文标签会自动换系统黑体，中英混排也正常。每种模式都画标签——`wipe` 的标签跟着扫描线在原地切换（扫描前显示 A，扫描后显示 B），`pip` 的小窗标签会按小窗尺寸缩小字号。

## 设计系统配色

默认颜色全部取自 Pika 设计系统的 token（`src/clipcompare/tokens.py`，常量按 token 命名；画面永远是深色底，半透明 token 取暗色主题的值）：

| 用在哪 | token | 值 |
|------|------|------|
| 波形面板底色、标题条 | `--ds-black` | `#111111` |
| 波形、正在播放的描边、第二个标签的字、新 tag、下划线 | `--ds-accent-700`（= `--ds-brand`） | `#cfc3ff` |
| 标签 / 标题 / 提示词的字 | `--ds-eggshell`（暗色 `--ds-text-primary`） | `#fcfaf7` |
| 差异摘要、`timing estimated` | `--ds-text-secondary`（暗色） | `#fcfaf7b3` |
| 标签 / 标题的底 | `--ds-invert-600`（暗色） | `rgb(34 34 34 / 60%)` |
| 波形面板的中线 | `--ds-primary-300`（暗色） | `rgb(252 250 247 / 10%)` |

`side` 的分隔线、`wipe` 的扫描线、`pip` 的边框仍是白色。

## 通用参数

所有模式都吃这些：

| 参数 | 说明 |
|------|------|
| `-o, --out PATH` | 输出文件 |
| `-l / -A / -B / --no-labels` | 标签，见上 |
| `--font PATH` | 标签和标题字体。默认本机装了 Telka 就用 Telka，否则自带 TikTok Sans Medium；中文自动换系统黑体 |
| `--color-a / --color-b HEX` | 两个标签的颜色，默认 `--ds-eggshell` `#fcfaf7` + `--ds-accent-700` `#cfc3ff` |
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
| `--panel PX` | 每块画面的**短边**，默认 1080 —— 竖版出 2160×1920，横版出 1920×2160；两张图片时默认用图片自己的短边（最多 1080） |
| `--length shortest\|longest` | `longest` 把较短那段的最后一帧冻住补齐 |
| `--divider PX` | 中缝分隔线粗细，默认 4，`0` 关闭。线是叠加绘制的，输出尺寸不变，调粗会盖住两侧画面各一半线宽 |
| `--head SEC` | 每段只取前 SEC 秒：同时播放时成片就是前 SEC 秒；配合 `--sequential` 时每段轮到时只播前 SEC 秒 |
| `--sequential` | 轮流播放：A 先播完，B 再播。等待的一侧停在画面上（B 停在第一个有画面的帧 —— 自动跳过开头的黑帧，AI 生成的视频常见；A 播完停在最后一帧），声音跟着正在播的那一侧走；成片时长 = 两段相加。`--audio none` 静音，`--length` 不起作用 |

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

### grid

`grid` 吃任意多段（至少两段），按阅读顺序（先从左到右，再往下）铺格子。每格的比例跟第一段走；`--fit` 决定其余不同比例的片段是裁切还是留黑边。标签用 `-l "A,B,C,..."` 按顺序一一对应，不写就用文件名；标签颜色用 `--color`。

| 参数 | 说明 |
|------|------|
| `--cols N` / `--rows M` | 列数 / 行数。都不写时自动：让整张画面接近 16:9，再去掉多余的空列（全是图片或音频时四段以内排一行）；只写一个时另一个自动补齐 |
| `--panel PX` | 每格的**短边**。默认自动：整张画面长边不超过 3840，单格短边不超过 1080 |
| `--gap PX` | 格子之间的黑缝，1080p 下的像素，默认 4，`0` 无缝。没铺满的空格也填黑 |
| `--length shortest\|longest` | 同时播放时：`shortest` 按最短那段截；`longest` 让短的冻住最后一帧 |
| `--sequential` | 轮流播放：按阅读顺序一次只播一格，没轮到的停在第一个有画面的帧（自动跳过开头黑帧），播完的停在最后一帧，**正在播的那格描边**，声音跟着它走 |
| `--highlight HEX` | 正在播放那格的描边颜色，默认 `--ds-accent-700` `#cfc3ff` |
| `--head SEC` | 每段只取前 SEC 秒（同时播放、轮流播放都适用） |
| `--pause SEC` | 轮流播放时两段之间停多久（画面停住、没有声音），默认 0.5，`0` 无停顿 |
| `--title TEXT` | 网格上方标题条里居中的标题（不会压到格子之间的缝）；配合 `--group` 时每组一个，逗号分隔 |
| `--manifest FILE\|URL\|-` | 从 JSON 读片段、标签、提示词、组名和输出，见「提示词对比」 |
| `--header "NAME: VALUE"` | 拉取 URL manifest 时带的 HTTP 头，可重复 |
| `--captions FILE` | 每段一条提示词（JSON 字符串数组），播放时显示在格子里 |
| `--html OUT.html` | 另出一个可切换版本的网页 |
| `--copy-media` | 配合 `--html`：把 URL 片段下载到网页旁边，离线可用 |
| `--group N` | 每 N 段一组（如 `2` 就是一对一对比），每组单独成一张网格、按顺序接起来播。片段数必须能被 N 整除；`-l` 可以只写 N 个标签，每组共用 |
| `--audio auto\|none\|mix\|N` | 默认 `auto`：轮流播放时跟着正在播的那格，同时播放时用第一段有声音的；`mix` 全部混音；数字 = 只用第 N 段的声音 |

## 常用例子

```bash
# 最省事：文件名当标签，布局自动判断
clipcompare side input.mp4 output.mp4

# 出 4K，指定标签，两段声音混在一起
clipcompare side orig.mp4 vfx.mp4 -l "ORIGINAL,EDITED" --panel 2160 --audio both

# 两段画幅不一样，留黑边保完整画面；短的那段冻帧补齐
clipcompare side a.mov b.mov --fit contain --length longest -o cmp.mp4

# 两段都有人声（比如两版配音）：左边播完再播右边，声音不会叠在一起
sbs side dub-a.mp4 dub-b.mp4 --sequential

# 一批配音版本拼成网格，每段只听前 8 秒，轮流播
clipcompare grid dub-*.mp4 --sequential --head 8

# 固定 4 列，同时播放，混音
clipcompare grid v1.mp4 v2.mp4 v3.mp4 v4.mp4 v5.mp4 --cols 4 --audio mix

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

### wipe 的两条硬约束

改这部分代码前先看这两条，违反任何一条都会出可见的错误画面：

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

**必须是两张，不能合并成一张**。给画面 `pad` 一圈边框色再整体切一次圆角是行不通的：越靠近角落，遮罩往里切的深度约 `0.29×(R+stroke)`，远大于边框厚度 `stroke`，边框会在四条弧线上被整段切掉，露出画面自己的直角。圆角越大豁口越明显。

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

构建后端是 hatchling，它不产生增量的 `build/` 目录 —— setuptools 的那个会把源码里已删除的文件继续打进 wheel。改完代码若发现装进去的还是旧的，用 `uv tool install --reinstall .`，`--force` 在版本号不变时会复用缓存的 wheel。

每个模式的 `build()` 都是纯函数：进两个 `ClipInfo` 加一组选项，出 ffmpeg 的 argv。所以滤镜图能脱离 ffmpeg 测试，200 多个测试跑完不到半秒（网页里的换算逻辑用 node 跑，没装 node 时跳过）。

## 已知边界

- `wipe` / `pip` 要求两段素材同机位同时间点，工具不做内容对位。
- 标签是直角药丸、没有字间距 —— ffmpeg 的 `drawtext` 画不了圆角和 letter-spacing。要圆角药丸得换成离屏渲染 PNG 再叠，那会引入浏览器依赖，不值。
- 中文字体回退目前只覆盖 macOS 自带黑体和常见的 Linux Noto CJK 路径。都找不到时会提示你用 `--font` 指定。
- 纯音频片段的波形面板只在 `grid` 里会自动铺满 16:9；`side` 两段音频出 2160×1080，`wipe` / `pip` 能用但意义不大。`--pause` 目前只有 `grid` 有。
- 提示词排版忽略字距调整（kerning），一行最多偏几个像素；字号 15px 还放不下的段落会被截断，完整内容看网页。
- `--group` 先把每组单独渲染、再不重编码地拼起来，所以每组的格数、尺寸都相同；某一组完全没有声音时拼接会出错。
- `side` / `wipe` / `pip` 只吃两段；三段以上用 `grid`。`grid` 的片段越多，ffmpeg 同时解码的路数越多，渲染越慢。

## License

MIT
