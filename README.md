# pathmap

> 把一个 Markdown 树（vault）的**目录名和文件名**换成另一种语言，并把树内**所有引用一起改对**，产出一棵新的树。
>
> 一句话边界：**它不改你的 vault，只生成一棵翻译后的产物树。** 正文、frontmatter 一律不动。

```
vault/                         build/zh/
  guides/intro.md        →       指南/入门.md
  ref/dict.md            →       参考/术语表.md
                          树内 [[dict]]、[x](advanced/io.md) 全部改写成新名字
```

## 为什么需要它

静态站点生成器（Hugo／mkdocs／Quartz）的多语言机制都是"**路径不变、只换内容**"：同一条英文路径在 `content/zh/` 下再来一份。于是站点的侧边栏、面包屑、URL 永远是英文——只要那套 vault 没有 frontmatter `title`（很多 Obsidian 库就是没有，页名靠 H1＋文件名），显示名就只能是路径段。

**把路径真的翻译掉，就只有"物理上就是中文路径"这一条路**：Quartz 的 `permalink` 只是别名跳转，真实 URL／sitemap／RSS／搜索索引仍由文件路径推导（[quartz#2572](https://github.com/jackyzha0/quartz/issues/2572)）；而 next-intl 那类"每语言一套路径段"的方案要求服务端 rewrite，静态导出用不了。

而一旦改了路径，`[[双链]]` 就全断了——这就是本项目要解决的那一件事。前人的做法与坑见 [docs/PRIOR-ART.md](docs/PRIOR-ART.md)。

## 安装

只依赖标准库，Python ≥ 3.9。

```bash
pip install -e .          # 得到 pathmap 命令
# 或者不安装：
python -X utf8 -m pathmap --help
```

## 30 秒上手

```bash
# 1) 生成/补全翻译表：给每个路径一个键，名字先留空（空名 = 保持原样，产物依然是完整的）
pathmap scan --vault ../my-wiki --map pathmap.map.tsv

# 2) 填名字（记事本/Excel 都行，TSV 就是两列）
#    guides          -> 指南
#    guides/intro.md -> 入门

# 3) 生成产物树，再验收
pathmap apply  --vault ../my-wiki --map pathmap.map.tsv --out build/zh
pathmap verify --vault ../my-wiki --map pathmap.map.tsv --out build/zh
```

`verify` 返回 0 才叫过。把它接进 CI，就是"翻译漏了/链接断了会红"的闸。

## 三个数据文件

### `pathmap.map.tsv` — 翻译表

```
# <vault 相对路径> \t <该段的新名字> \t <备注，可省>
guides	指南
guides/intro.md	入门
ref/dict.md	术语表
assets/pic one.png	示意图
```

| 规则 | 说明 |
|---|---|
| **段级** | 每条只给**这一段**起名；路径由段拼接。父目录翻一次，下面不用重复写 |
| 空名字 | 该段保持原名（半成品表也能产出完整树） |
| 扩展名 | 自动保留：`bitproc.md` + `位流生产` → `位流生产.md`；名字里已带扩展名则不重复加 |
| 大小写 | 查找不区分大小写（Windows 检出与 Linux CI 用同一张表） |
| 优先级 | **显式条目 > `keep.txt` > 原名** |

### `keep.txt` / `skip.txt` — 两条 glob 规则

```
# keep.txt：这些名字保持原样（不必进翻译表）
assets/*.svg
man/**
```
```
# skip.txt：这些不进产物树
vendor/**
```

`*` 不跨路径段，`**` 跨段；`dir/**` 同时覆盖 `dir` 自己。**以 `.` 开头的段（`.obsidian`、`.git`）自动跳过**，不用写规则。

## 链接改写：它到底动了哪些字

| 写法 | 解析身份 | 产物里变成 |
|---|---|---|
| `[[dict]]` | 文件名（Obsidian 规则） | `[[术语表]]` |
| `[[dict\|术语]]` | 同上，`\|` 后面显示文本原样 | `[[术语表\|术语]]` |
| `[[io#接口]]` / `[[io#^块]]` | 锚点原样保留 | `[[输入输出#接口]]` |
| `[[a/b/io.md\|甲]]` | 带路径的写法则按路径解析 | `[[输入输出.md\|甲]]` |
| `![[pic one.png]]` | 附件，保留扩展名 | `![[示意图.png]]` |
| `[文本](advanced/io.md#接口)` | 相对当前文件 | `[文本](进阶/输入输出.md#接口)` |
| `[文本](<x y.md> "标题")` | 尖括号＋标题都保留 | `[文本](<进阶/输入输出.md> "标题")` |
| `[x](pic%20one.png)` | `%20` 解码后再算相对距离 | `[x](示意图.png)` |
| `[x](https://…)` `#锚点` `//cdn` | 不碰 | 原样 |

**代码块里的不算**：围栏代码块（``` / ~~~，含未闭合的）与行内代码先被遮罩，示例文本里的链接一个都不改。

**歧义不猜**：两篇同名页时 `[[same]]` 直接**报告并保持原样**，不做"选一个"这种赌。重名的产物路径同理——直接拒绝出树。

## 安全阀

| 场景 | 行为 |
|---|---|
| `--out` 落在 vault 内 | 拒绝（exit 2）：**绝不就地改名** |
| `--out` 是个非空目录且没有 `.pathmap-generated` 标记 | 拒绝覆盖；确认是你的目录再加 `--force` |
| 两个 vault 路径落到同一产物路径 | 拒绝出树，列出冲突双方 |
| `--dry-run` | 只算不写，照样报告链接问题 |
| `--link` | 附件用硬链接（Windows NTFS / POSIX 都行），省掉整棵树的字节复制 |

## verify 判据（什么算"过"）

对着**产物树**重新解析，而不是相信 apply 的自述：

1. 产物里每一页的每个引用都能解析到产物里的文件 → **死链 = 0**
2. 产物里没有重名文件（会让最短链接变歧义）→ **歧义 = 0**
3. 没有路径冲突、没有 `keep/skip` 里写了却一条都没匹配上的 glob（通常是拼错）
4. 没有 `.pathmap-generated` 标记的目录 → 警告（大概不是 pathmap 造的）

另有两条**不算错**、但会列出来：`map` 里有键而 vault 里没这个文件（orphan，多为改名后残留）、vault 里有文件但没有条目（保持原名放行）。想更严就加 `--require-map`，把后者也变成失败。

## 已知边界（故意的）

- **不改 frontmatter**：`title`、`aliases` 一律不碰。理由见 [docs/DESIGN.md](docs/DESIGN.md#frontmatter-为什么不动)。
- **不改正文**：翻译正文是另一件事，不在本工具范围。
- **只认单反引号的行内代码**：` ``a`b`` ` 这种多反引号行内片段不遮罩（围栏代码块不受影响）。
- **URL 里不做 percent-encode**：只处理空格（`%20`）。中文保留原样——浏览器、静态站、Obsidian 都吃 UTF-8 路径，强行转义反而让 diff 不可读。
- **不做双向同步**：没有"reverse"模式。产物是构建物，每次从 vault 整棵重建；两边不会漂移，因为只有一边是源。
- **`dir/**` 之外的 glob 不做代数化简**：够用就好，不实现的语法会当作字面量。

## 目录

```
pathmap/
  util.py      路径与文本的小工具、glob 编译
  rules.py     map / keep / skip 三种数据文件的读写与语义
  plan.py      走 vault、逐段定位、建索引、查冲突
  links.py     遮罩代码、解析与改写四种 wiki 链接和三种 md 链接
  apply.py     出产物树（含全部安全阀）
  verify.py    对产物重新解析，出判据
  scan.py      让翻译表跟 vault 同步
  cli.py       三个子命令，全部非交互
tests/
  fixtures/    11 个文件的小 vault（含重名、跳过、保留、图片、代码块示例）
  test_pathmap.py
```

测试：

```bash
python -X utf8 -m unittest discover -s tests
```

## 它从哪来

脱胎于某个 Obsidian＋静态站项目里的一套一次性脚本（`renameproc` 生成清单 → 人工在记事本里填中文名 → `rename` 复制整树并改名 → 另一个脚本删绝对路径前缀）。那套东西的设计里有两件事是对的，被继承下来了：**排除规则当数据**（`keep.txt`）与**段级拼接**（父目录翻一次）。其余全部重写：

| 原来的做法 | 现在 |
|---|---|
| 只改路径，不改 `[[双链]]` | 引用与改名同一笔事务完成 |
| `copytree` 复制 895 MB 整树 | 默认只写文本；附件可 `--link` 硬链接 |
| `notepad.exe` + `input()` 交互 | 三个子命令全非交互，可进 CI |
| 写死 `S:\work\WCIS` 绝对路径 | 零绝对路径 |
| 靠人眼看有没有漏 | `verify` 重解析产物，死链=0 才算过 |
| 正向／反向就地改名，两边漂移 | 只有一棵源树，产物每次重建 |

## 许可

尚未声明。要发布给外部用之前补一个（MIT/Apache-2.0 皆可）。