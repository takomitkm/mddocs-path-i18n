# 有人做过"路径层面的 i18n"吗

调研时间是 2026-11，问的是同一个问题：**把 Markdown 树的目录名/文件名翻成另一种语言，同时让树内引用仍然成立**，现成方案在哪。

结论先给：**通用工具没有**。不是没人想到，是网页端收益／成本比太差；而"编辑器里也要中文目录"这种需求太私人，没人做成产品。

## 一、静态站生成器：主流选择是"路径不翻"

| 实现 | 多语言机制 | 路径 |
|---|---|---|
| [Hugo 多语言](https://gohugo.io/content-management/multilingual) | 按文件名后缀（`about.en.md`/`about.fr.md`）或按目录（每语言一个 `contentDir`） | 要求**同一相对路径与基本名**才能互相关联；路径本身不翻 |
| [mkdocs-static-i18n](https://github.com/mastercoms/mkdocs-static-i18n) | 后缀式（`x.zh.md`）或 folder-based（`docs/en/…`、`docs/zh/…`） | 译文在语言目录下**镜像同一相对路径** |
| Docusaurus / VitePress / Astro Starlight | locale 前缀 + 同名文件 | 同上 |

这正是本工具要绕开的地方：**它们全都要求路径不变**，所以站点的侧边栏／面包屑／URL 只能是英文（除非每页都写 frontmatter `title`）。

## 二、动态站路由：有真正的"路径段翻译"，但静态导出用不了

- next-intl 的 `pathnames`：每语言一套路径段映射，`/en/about` ↔ `/de/ueber-uns`。
- SvelteKit、Nuxt 的 localized routes 同理。

限制写在官方文档里：静态导出时 **"You can't use pathnames, as these require server-side rewrites"**（[next-intl: Proxy / middleware](https://next-intl.dev/docs/routing/middleware)）。GitHub Pages 这种纯静态托管没有 rewrite 层，所以这条路直接堵死。

## 三、Quartz（本项目实际用的站点引擎）：permalink 不是解法

[quartz#2572](https://github.com/jackyzha0/quartz/issues/2572)（2026-09 提）：`permalink` 只是**别名跳转页**，内容页真实 URL 仍由文件路径推导出的 slug 决定；`sitemap`、`RSS`、`content-index`（搜索）、OG/Twitter 元数据全都用路径 slug。文件移动或改名，permalink 的跳转目标跟着变。

⇒ **想改 URL，就得改源文件的物理路径。** 这是本工具存在的唯一技术前提。

## 四、编辑器侧：Obsidian 已经解决了"改名＋改链接"，但只在它自己里面生效

- Obsidian 自带 `app.fileManager.renameFile(file, newPath)`：「Rename or move a file safely, and update all links to it」——笔记、附件、**文件夹**都支持（[QuickAdd 批量重命名脚本的作者原话与 API 注释](https://forum-zh.obsidian.md/t/topic/31659)）。
- 社区插件 [Bulk Rename](https://pkmer.cn/Pkmer-Docs/10-obsidian/obsidian%E7%A4%BE%E5%8C%BA%E6%8F%92%E4%BB%B6/obsidian-bulk-rename-plugin/) 就是拿它批量改名并自动更新全库引用。

**这条很重要**：如果目标只是"我在 Obsidian 里想看到中文目录"，那正确实现是**驱动 Obsidian 自己的 API**，而不是自己写一套改名＋链接重写。本工具的定位因此是**数据的持有者**（翻译表＋一致性校验），Obsidian 侧那半边应该做它的消费者（见 [DESIGN.md §9](DESIGN.md#9-扩展点想清楚再动)）。

## 五、中文路径本身的代价（这部分是真实存在的）

- **URL 里是 percent-encoded**：`https://…/参考/术语表` 在浏览器地址栏里显示为 `%E5%8F%82%E8%80%83/…` 之类，复制出来的分享链接同样如此。RFC 3986 只规定怎么转义，不规定路径该不该翻（[相关讨论](https://stackoverflow.com/questions/19719796/rails-need-advice-about-slug-url-and-cjk-characters)）。
- **工具的 CJK 路径坑**：git 在 bash 里传中文路径会 `pathspec did not match`（本机 argv 编码问题）、`git ls-tree` 的 `core.quotePath` 会把中文转成八进制串、某些 macOS 版本用 NFD 分解。所以本工具坚持：**中文只出现在产物树里，不进源仓库工作树**。

## 结论：什么时候该用

| 你想要 | 该不该用 |
|---|---|
| 站点 URL／侧边栏／面包屑是中文 | **该用**（静态站没有别的路） |
| obsidian 里目录名是中文 | 该用另一条路：驱动 Obsidian API；本表可作为它的数据源 |
| 只是想页面**标题**是中文 | 不该用：写 frontmatter `title` 即可，成本低一个数量级 |
| 多语言内容互相对照（同一页两版正文） | 不该用：那是"路径不变、内容分语言"，交给 SSG 的多语言机制 |
| 想让跨语言链接可分享稳定 | 不该用：路径一变，别处的链接就断；业界保留英文路径正是为此 |