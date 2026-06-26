# DealMind 设计系统 v1.0

> 多人设销冠压力测试引擎 · 统一视觉与交互规范  
> 风格 DNA：**Notion 米白 + Linear 极简 + 中文优雅排版**  
> 来源：design/ref_01~05.png 参考图提炼  
> 适用范围：所有 Web 界面（13 个主页面 + 登录页 + 进阶页）

---

## 0. 设计原则（先想后做）

| # | 原则 | 含义 |
|---|------|------|
| 1 | **克制配色** | 99% 黑白灰 + 米白背景，强调色只用于状态（成功/警告/错误）。绝不用任何品牌彩色 |
| 2 | **字重制造层级** | 不靠颜色和大小做层级，靠字重（regular 400 / medium 500 / semibold 600 / bold 700）+ 行高拉开关系 |
| 3 | **大留白** | 卡片 padding 24-32px、卡片间距 24px、模块间距 32-48px。宁可少放内容也不挤 |
| 4 | **大圆角 + 无阴影** | 卡片 12-16px 圆角 + 1px 浅灰 border。几乎不用 box-shadow，浮层除外 |
| 5 | **数据可读优先** | 数字 tabular-nums 等宽对齐；图表单色（黑线灰网格），不要花哨渐变 |
| 6 | **微妙动效** | 所有 transition 200ms ease；只做 opacity / transform，禁用 bounce |

---

## 1. 品牌

| 字段 | 内容 |
|------|------|
| **品牌名** | DealMind |
| **副标题** | Sales Simulation Engine |
| **中文** | 多人设销冠压力测试引擎 |
| **Logo 文字** | 等宽 sans-serif 加粗（H1 24px bold），副标题 12px regular 灰色 |
| **Logo 图标** | 暂用 lucide `brain` 或 `target` 图标线性版（后期可换品牌 LOGO） |

### 1.1 Logo 排版规范

```
┌───────────────────────────┐
│  DealMind              ◐  │  ← 24px bold + 图标
│  Sales Simulation Engine  │  ← 12px regular #9ca3af
└───────────────────────────┘
```

出现位置：登录页左上角、应用左侧导航顶部、登录页页脚

---

## 2. 色彩系统

### 2.1 中性色（核心）

| 名称 | 色值 | 用途 |
|------|------|------|
| `--dm-bg` | `#f7f6f3` | 应用主背景（米白） |
| `--dm-bg-sidebar` | `#f5f4f0` | 左侧导航底色（比主背景稍深） |
| `--dm-bg-card` | `#ffffff` | 卡片纯白 |
| `--dm-bg-elevated` | `#fafaf8` | 嵌套卡片 / hover 态 |
| `--dm-bg-muted` | `#f0efeb` | 输入框默认底 / disabled |
| `--dm-bg-selected` | `#e8e7e3` | 菜单选中态 / Tab 激活态 |
| `--dm-bg-inverse` | `#1a1a1a` | Judge 卡片 / 主按钮黑底 |
| `--dm-border` | `#e5e4e0` | 主分割线 |
| `--dm-border-strong` | `#d4d3cf` | 强分割线 / 输入框 border |
| `--dm-border-focus` | `#1a1a1a` | 输入框 focus 态 |

### 2.2 文字色

| 名称 | 色值 | 用途 |
|------|------|------|
| `--dm-text` | `#1a1a1a` | 标题 / 重要正文 |
| `--dm-text-secondary` | `#525252` | 一般正文 |
| `--dm-text-muted` | `#888888` | 弱化说明文字 |
| `--dm-text-disabled` | `#bfbfbf` | 禁用态 |
| `--dm-text-inverse` | `#ffffff` | 黑底反白文字 |
| `--dm-text-link` | `#1a1a1a` | 链接（去掉默认蓝） |

### 2.3 状态色（仅用于反馈，禁止当装饰用）

| 名称 | 色值 | 用途 |
|------|------|------|
| `--dm-success` | `#2d7a3e` | "进行中" / 成功 / 正向趋势文字 |
| `--dm-success-bg` | `#d4f4dd` | 成功 tag 背景 |
| `--dm-warning` | `#9a6c1a` | 待跟进 / 警告 |
| `--dm-warning-bg` | `#fbeed4` | 警告 tag 背景 |
| `--dm-danger` | `#9b2c2c` | 流失 / 错误 / 负向趋势文字 |
| `--dm-danger-bg` | `#f8d7d7` | 错误 tag 背景 |
| `--dm-info` | `#1e5fa8` | 一般信息（极少使用） |
| `--dm-info-bg` | `#dbe7f6` | 信息 tag 背景 |

### 2.4 数据可视化色板（图表专用，单色阶为主）

| 名称 | 色值 | 用途 |
|------|------|------|
| `--dm-chart-primary` | `#1a1a1a` | 主线条 |
| `--dm-chart-secondary` | `#888888` | 次线条 |
| `--dm-chart-grid` | `#ececec` | 网格线 |
| `--dm-chart-area` | `rgba(26,26,26,0.05)` | 面积填充（极淡） |

### 2.5 Tag 配色矩阵

| Tag 用途 | 背景 | 文字 | 例 |
|---------|------|------|-----|
| 中性默认 | `#f0efeb` | `#525252` | 行业 / 角色标签 |
| 状态进行中 | `#d4f4dd` | `#2d7a3e` | 「进行中」 |
| 状态完成 | `#e8e7e3` | `#525252` | 「已完成」 |
| 状态错误 | `#f8d7d7` | `#9b2c2c` | 「失败」 |
| 强调激活 | `#1a1a1a` | `#ffffff` | 选中态 / 顶置 |

---

## 3. 字体系统

### 3.1 字体栈

```css
--dm-font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC",
                "Microsoft YaHei", "Inter", "Segoe UI",
                Roboto, Helvetica, Arial, sans-serif;

--dm-font-mono: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;

--dm-font-numeric: "Inter", -apple-system, sans-serif;
font-variant-numeric: tabular-nums;
```

### 3.2 字号 / 行高 / 字重

| Token | 字号 | 行高 | 字重 | 用途 |
|-------|------|------|------|------|
| `text-display` | 36px | 44px | 700 | 登录页大标题（"欢迎回来..."） |
| `text-h1` | 28px | 36px | 700 | 页面主标题（"Persona 人设库"） |
| `text-h2` | 22px | 30px | 600 | 卡片 / 区块标题 |
| `text-h3` | 18px | 26px | 600 | 子标题 |
| `text-body-lg` | 16px | 24px | 400 | 长段正文 |
| `text-body` | 14px | 22px | 400 | **默认正文** |
| `text-body-strong` | 14px | 22px | 500 | 强调正文 |
| `text-caption` | 13px | 20px | 400 | 卡片副标题 / 说明文字 |
| `text-small` | 12px | 18px | 400 | 时间戳 / 极弱说明 |
| `text-overline` | 11px | 16px | 500 | 分组标题（导航分组、字母全大写） |
| `text-number-xl` | 32px | 40px | 700 | 数字卡大数字 |
| `text-number-lg` | 24px | 32px | 600 | 次级数字 |

### 3.3 行间距和段落

- 正文段落之间留 16px
- 标题与下方正文留 12px
- 卡片标题与卡片内容留 16px

---

## 4. 间距 & 网格

### 4.1 间距 token（8px 基础网格）

| Token | 值 | 用途 |
|-------|----|----|
| `space-1` | 4px | icon 与文字间距 |
| `space-2` | 8px | tag 内 padding |
| `space-3` | 12px | 行内元素间距 |
| `space-4` | 16px | 卡片内段落间距 |
| `space-5` | 20px | 表单项之间 |
| `space-6` | 24px | **卡片内 padding（默认）** |
| `space-7` | 32px | 卡片之间间距 / 大块 padding |
| `space-8` | 40px | 模块之间 |
| `space-9` | 48px | 页面内大分区 |
| `space-10` | 64px | 顶层留白 |

### 4.2 容器宽度

| 容器 | 宽度 |
|------|------|
| 左侧导航 | 220px（折叠后 64px） |
| 顶部 Header | 100% × 64px |
| 主内容最大宽度 | 1440px 居中 |
| 详情抽屉 / 右栏 | 360px（小）/ 480px（中）/ 640px（大） |
| 登录页主卡片 | 480px |

---

## 5. 圆角 & 阴影

### 5.1 圆角

| Token | 值 | 用途 |
|-------|----|----|
| `radius-sm` | 4px | tag / 小标签 |
| `radius` | 8px | **按钮 / 输入框（默认）** |
| `radius-md` | 12px | 数字卡 / 内嵌小卡 |
| `radius-lg` | 16px | **主卡片（默认）** |
| `radius-xl` | 24px | 登录页大卡片 / 弹窗 |
| `radius-full` | 9999px | 头像 / 圆形按钮 |

### 5.2 阴影（极轻）

| Token | 值 | 用途 |
|-------|----|----|
| `shadow-none` | none | **默认（用 border 代替）** |
| `shadow-xs` | `0 1px 2px rgba(0,0,0,0.04)` | 主按钮 hover |
| `shadow-sm` | `0 2px 8px rgba(0,0,0,0.06)` | 下拉菜单 |
| `shadow-md` | `0 8px 24px rgba(0,0,0,0.08)` | 详情抽屉 |
| `shadow-lg` | `0 16px 48px rgba(0,0,0,0.12)` | Modal / Popover |

### 5.3 Border 替代阴影

> **核心规则**：除非元素需要"浮"出页面（菜单/抽屉/弹窗），否则统一用 `1px solid var(--dm-border)` 代替 box-shadow。

---

## 6. 图标系统

| 项 | 规范 |
|----|------|
| **图标库** | [lucide-vue-next](https://lucide.dev/)（替换 @element-plus/icons-vue） |
| **风格** | 线性 outline，stroke-width=1.5px |
| **尺寸** | 16px（内嵌文字行）/ 18px（按钮内）/ 20px（菜单/卡片）/ 24px（独立装饰） |
| **颜色** | 默认继承父级文字色，不单独设色 |
| **禁用** | 面型图标 / 多色图标 / 卡通图标（登录页插画除外） |

### 6.1 常用图标映射

| 场景 | lucide 图标 |
|------|-----------|
| 首页 | `Home` |
| 新建对话 | `MessageSquarePlus` |
| 对话现场 | `MessageCircle` |
| 会话历史 | `History` |
| 会话复盘 | `BarChart3` |
| 批量测试 | `Layers` |
| 批量报告 | `FileBarChart` |
| Persona 库 | `Users` |
| 产品知识库 | `Box` |
| 企业知识库 | `Building2` |
| 销售案例集 | `BookOpen` |
| 模型设置 | `Cpu` |
| 向量库管理 | `Database` |
| 销冠技能配置 | `Sparkles` |
| 运行状态 | `Activity` |

---

## 7. 核心组件规范

### 7.1 按钮（Button）

| 类型 | 视觉 | 用途 |
|------|------|------|
| **主按钮 primary** | 黑底 `#1a1a1a` 白字，圆角 8px，padding 8px 16px | 「启动模拟」「保存」「确认」 |
| **次按钮 secondary** | 白底 + 1px 灰 border + 黑字 | 「取消」「重置」「编辑」 |
| **文字按钮 text** | 透明底 + 黑字 + 下划线（hover） | 「查看详情」「查看全部」 |
| **危险按钮 danger** | 同主按钮但 hover 时变红字 | 删除 / 清空 |

```css
.dm-btn-primary {
  background: #1a1a1a;
  color: #fff;
  border-radius: 8px;
  padding: 8px 16px;
  font-weight: 500;
  font-size: 14px;
  transition: all 200ms ease;
}
.dm-btn-primary:hover { background: #000; }
.dm-btn-primary:active { transform: scale(0.98); }

.dm-btn-secondary {
  background: #fff;
  color: #1a1a1a;
  border: 1px solid #d4d3cf;
  border-radius: 8px;
  padding: 7px 15px; /* -1 抵消 border */
}
.dm-btn-secondary:hover { background: #fafaf8; }
```

**尺寸变体**：
- 大 large：padding 12px 24px，font-size 15px
- 默认 default：padding 8px 16px，font-size 14px
- 小 small：padding 6px 12px，font-size 13px

### 7.2 卡片（Card）

```
┌─────────────────────────────────────┐
│ 卡片标题（text-h2 / text-h3）        │ ← padding 24px
│                                     │
│ 卡片内容...                          │
│                                     │
│                                     │
│              ┌─────┐                │
│              │ btn │                │
│              └─────┘                │
└─────────────────────────────────────┘
   background: #fff
   border: 1px solid #e5e4e0
   border-radius: 16px
   padding: 24px
   shadow: none
```

**变体**：
- `dm-card-flat`：默认（白底 + border）
- `dm-card-elevated`：hover 时增加 shadow-xs
- `dm-card-inverse`：黑底白字（如 Judge Check 卡片）

### 7.3 输入框（Input）

```css
.dm-input {
  background: #fff;
  border: 1px solid #d4d3cf;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
  color: #1a1a1a;
  transition: border-color 200ms ease;
}
.dm-input:focus {
  border-color: #1a1a1a;
  outline: none;
}
.dm-input::placeholder { color: #888; }
```

- 必须有 label，放在输入框上方，14px medium
- 含图标的输入框：图标 left/right 16px padding，灰色

### 7.4 表格（Table）

| 元素 | 规范 |
|------|------|
| 表头 | 浅灰背景 `#fafaf8`，11px overline 灰字 |
| 行高 | 56px（默认）/ 48px（紧凑） |
| 行边框 | 仅底部 1px `#e5e4e0`，无外框 |
| Hover | 行底色变 `#fafaf8` |
| 选中 | 行底色 `#e8e7e3` |
| 操作列 | 文字按钮，间距 12px |
| 空状态 | 表格中央放 lucide `Inbox` 32px 灰 + 「暂无数据」文字 |

### 7.5 Tag

```css
.dm-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
}
```

- 默认中性：`background: #f0efeb; color: #525252;`
- 状态成功：见状态色矩阵
- 高亮：黑底白字（顶置 / 选中）

### 7.6 数字卡（Stat Card）

```
┌────────────────────────┐
│ 总会话数  ⓘ            │ ← text-caption 灰 + tooltip icon
│                        │
│ 2,842                  │ ← text-number-xl bold tabular-nums
│                        │
│ 较上期  ▲ 12.6%        │ ← text-small + 绿色趋势
└────────────────────────┘
```

- padding 20px 24px
- 数字必须 `font-variant-numeric: tabular-nums`
- 趋势 chip 紧凑：`▲/▼ + 数字%` 绿/红，背景透明

### 7.7 进度条（Pressure Bar）

参考 ref_02 / ref_04 中的压力画像：

```
价格敏感度  高    ●━━━━━━━━━━━○────  82/100
                ↑ 起点圆点    ↑ 滑块圆点
```

- 总宽度 100%
- 高度 2px 灰线 + 起点 8px 黑圆点 + 当前值 12px 黑圆点
- 数值右对齐 12px tabular-nums

### 7.8 Tab

```
┌──────┬──────┬──────┐
│ 登录 │ 本地模式 │  ← 选中底部 2px 黑线
└──────┴──────┴──────┘
─────────────────────  ← 全宽 1px 浅灰
```

- 切换时仅高亮线移动，无背景色变化
- 字号 14px medium

### 7.9 头像（Avatar）

- 圆形 `radius-full`
- 默认尺寸：24px（行内）/ 32px（菜单）/ 40px（卡片）/ 64px（详情）
- 含 fallback：用户名首字 + 中性灰背景

### 7.10 状态指示灯

```
● 进行中（绿）
● 在线（绿）
● 离线（灰）
● 错误（红）
```

- 8px 实心圆 + 12px 间距 + 文字

### 7.11 抽屉（Drawer）

- 从右滑入，宽度 480px（默认）
- 头部 64px：标题 + 关闭按钮
- 内容区可滚动
- 底部 64px：操作按钮（次按钮左 + 主按钮右）
- 背景蒙层 `rgba(0,0,0,0.32)` + blur(4px)

### 7.12 模态框（Modal）

- 圆角 16px，居中
- 默认宽度 480px
- 头部 24px padding，下方 1px 分割线
- 内容 24px padding
- 底部 16px 24px，右对齐按钮组

---

## 8. 布局规范

### 8.1 登录页布局（ref_01）

```
┌──────────────────────────────────────────────────────────┐
│ DealMind                                                 │ ← 24px 顶部 padding 48px 左侧
│ Sales Simulation Engine                                  │
│                                                          │
│  ┌──────────────────────┐    ┌────────────────────────┐ │
│  │                      │    │ ┌─────┬───────────────┐│ │
│  │  欢迎回来，          │    │ │登录 │ 本地模式      ││ │
│  │  多人设销冠压力测试  │    │ └─────┴───────────────┘│ │
│  │  引擎               │    │                        │ │
│  │                      │    │  邮箱                  │ │
│  │  登录并进入你的工作  │    │  [✉  请输入邮箱...]    │ │
│  │  区，管理压力测试...│    │                        │ │
│  │                      │    │  密码                  │ │
│  │  ┌────────────────┐  │    │  [🔒 请输入密码...👁]  │ │
│  │  │ login-illustr. │  │    │                忘记密码?│ │
│  │  │  png (610x410) │  │    │                        │ │
│  │  └────────────────┘  │    │  ┌──────────────────┐  │ │
│  │                      │    │  │      登录        │  │ │
│  └──────────────────────┘    │  └──────────────────┘  │ │
│                              │      ────  或  ────    │ │
│                              │                        │ │
│                              │  ┌──────────────────┐  │ │
│                              │  │  📂  进入工作区  │  │ │
│                              │  └──────────────────┘  │ │
│                              └────────────────────────┘ │
│                                                          │
│ © 2024 DealMind. 保留所有权利.                  版本 1.0.0│
└──────────────────────────────────────────────────────────┘
```

**关键点**：
- 整页背景 `#f7f6f3`
- 主内容居中，最大宽度 1100px
- 左侧文案 + 插画（占 50%）/ 右侧表单卡片（占 50%）
- 插画素材：`design/login-illustration.png`（610×410，由 ref_01 精确裁剪生成，Stage 0 复制到 `web/src/assets/login-illustration.png` 后 `<img>` 直接引用，**禁止替换为其他插画**）
- 「进入工作区」按钮：白底 + border + 含 lucide `FolderOpen` 图标
- 预设管理员账号：admin / dealmind2026（后端配置）
- 「进入工作区」按钮：**无账号直接进入首页**（D5 单人本地）

### 8.2 应用主布局

```
┌────────────────────────────────────────────────────────────┐
│ ┌─────────┐ ┌──────────────────────────────────────────┐  │
│ │         │ │ [Workspace ▾]            🔔  👤 张三 ▾   │  │ ← Header 64px
│ │ DealMind├─┴──────────────────────────────────────────┤  │
│ │         │                                            │  │
│ │ 模拟运营│                                            │  │
│ │ · 首页  │           主内容区                          │  │
│ │ · 新建  │       (米白背景 + 白卡片堆叠)               │  │
│ │ · 现场  │                                            │  │
│ │ ...     │                                            │  │
│ │         │                                            │  │
│ │ 规模测试│                                            │  │
│ │ · ...   │                                            │  │
│ │         │                                            │  │
│ │ ┌─────┐ │                                            │  │
│ │ │ Logo│ │                                            │  │
│ │ │卡片 │ │                                            │  │
│ │ └─────┘ │                                            │  │
│ │ v 1.0.0 │                                            │  │
│ └─────────┘ └──────────────────────────────────────────┘  │
│   220px                                                    │
└────────────────────────────────────────────────────────────┘
```

**左侧导航细节**：
- 宽 220px，背景 `#f5f4f0`，无 border
- 顶部 64px：Logo 区
- 中间菜单：分组标题 11px overline 灰、菜单项 14px 黑、含 18px 图标
- 菜单 hover：`background: rgba(0,0,0,0.04)`
- 菜单选中：`background: #e8e7e3; font-weight: 500;`
- 底部固定：产品 Logo 小卡 + 版本号

**Header 细节**：
- 高 64px，白底，底部 1px border
- 左侧：Workspace 下拉切换器（含图标 + 名称）
- 右侧：通知铃铛（含红点小气泡）+ 用户头像 + 名字 + 下拉

### 8.3 列表 + 详情双栏布局（ref_04）

```
┌────────────────────────────────────────────────────────┐
│ 顶部 toolbar：搜索 + 筛选 + 视图切换                   │
├─────────────────────────────────┬──────────────────────┤
│                                 │                      │
│  网格卡片区（左）3 列 grid       │  详情面板（右）       │
│                                 │  (固定 380px，可关闭) │
│  ┌─────┐ ┌─────┐ ┌─────┐        │                      │
│  │     │ │选中 │ │     │        │  头部头像 + 名字     │
│  └─────┘ └─────┘ └─────┘        │                      │
│  ┌─────┐ ┌─────┐ ┌─────┐        │  字段卡片堆叠        │
│  │     │ │     │ │     │        │  ...                 │
│  └─────┘ └─────┘ └─────┘        │                      │
│                                 │  底部操作按钮组       │
│  分页器（居中）                  │                      │
└─────────────────────────────────┴──────────────────────┘
```

- 卡片选中时增加 2px 黑色 border + 右上角小勾
- 详情面板独立滚动
- 关闭按钮 lucide `X` 在右上角

### 8.4 对话现场布局（ref_02）

```
┌─────────────────────────────────────────────────────────────────────┐
│ ┌──────┬─────────────┬──────────────────────────┬─────────────────┐│
│ │      │ 会话控制    │ 实时对话流               │ 产品知识命中     ││
│ │ Nav  │             │                          │                  ││
│ │      │ 信息卡      │ [Persona 蓝]             │ 84% 命中圆环图   ││
│ │      │             │ [Sales 绿]               │                  ││
│ │      │ 压力画像    │ [Persona]                │ 销售经验命中     ││
│ │      │ (实时)      │ [Sales]                  │                  ││
│ │      │             │ [Judge Check 黑卡]       │ 76% 命中         ││
│ │      │             │ ━━━ 阶段 3 ━━━           │                  ││
│ │      │             │ [Persona]                │ 当前画像         ││
│ │      │             │ [输入框]                  │                  ││
│ │      │ [暂停]       │                          │ Judge 下一步指令 ││
│ │      │ [终止]       │                          │                  ││
│ └──────┴─────────────┴──────────────────────────┴─────────────────┘│
│  220px    280px              flex                  340px            │
└─────────────────────────────────────────────────────────────────────┘
```

- 4 列布局，主对话流 flex 撑满
- Judge Check 用黑卡突出，与普通气泡形成视觉断点
- 阶段切换用细分割线 + 阶段名 chip

### 8.5 表单页布局（ref_03）

```
┌───────────────────────────────────────────────────────┐
│ 新建模拟                                              │ ← page title
│ 配置一场销售压力测试                                   │ ← subtitle
│                                                       │
│ ┌─────────────────────────────────┬─────────────────┐│
│ │  1. 选择产品                    │ 本场测试概览     ││
│ │  [下拉]                          │                 ││
│ │                                  │ 实时回显已配置的 ││
│ │  2. 选择 Persona                 │ 各项参数         ││
│ │  [下拉]                          │                 ││
│ │                                  │ - 产品           ││
│ │  3. 会话主题                     │ - Persona       ││
│ │  [输入]                          │ - 主题           ││
│ │                                  │ - Max Turns     ││
│ │  4. 对话配置 [3列输入]            │ ...             ││
│ │                                  │                 ││
│ │  5. 压力配置 [4个滑块]            │ 全局压力（实时） ││
│ │                                  │                 ││
│ │  6. 更多参数 [折叠面板]            │                 ││
│ │                                  │                 ││
│ │                  [启动模拟]       │                 ││
│ └─────────────────────────────────┴─────────────────┘│
│                                                       │
└───────────────────────────────────────────────────────┘
```

- 主表单卡 + 右侧实时回显卡
- 表单项分组用 `1./2./3.` 编号 + h3 标题
- 启动按钮右下角对齐，主按钮黑底

### 8.6 统计看板布局（ref_05）

```
┌─────────────────────────────────────────────────────────┐
│ 统计看板  [日期 ▾] [产品 ▾] [人设 ▾] [状态 ▾] [导出报告] │
├──┬──┬──┬──┬─────────────────────────────────────────────┤
│数│数│数│数│ ← 4 个数字卡（Q4 决策）                       │
│字│字│字│字│                                              │
│卡│卡│卡│卡│                                              │
├──┴──┴──┴──┼─────────────────────────────────────────────┤
│ 成交率趋势  │ 常见异议排行                                │
│ (折线图)    │ (横向条形图)                                │
├────────────┼─────────────────────────────────────────────┤
│ 不同人设成交│ 经验库命中率                                │
│ (条形图)    │ (折线图)                                    │
├────────────┴─────────────────────────────────────────────┤
│ 可复用话术产出趋势                                       │
└──────────────────────────────────────────────────────────┘
```

- 顶部 4 列等宽数字卡
- 中间 2×2 图表 grid
- 底部全宽长图表

---

## 9. 页面级模板（参考图映射）

| 参考图 | 阶段 | 关键复用规范 |
|--------|------|-------------|
| ref_01 登录页 | Stage 0 | 8.1 布局 + 7.8 Tab + 7.1 主/次按钮 |
| ref_02 对话现场 | Stage 6a/6b | 8.4 布局 + 7.7 进度条 + 7.2 卡片（含 inverse） |
| ref_03 新建模拟 | Stage 6a | 8.5 布局 + 7.3 输入框 + 7.7 滑块 |
| ref_04 Persona 库 | Stage 3 | 8.3 列表+详情 + 7.7 滑块 + 7.5 Tag |
| ref_05 统计看板 | Stage 8 / 10 | 8.6 布局 + 7.6 数字卡 + ECharts 黑白主题 |

---

## 10. 动效规范

| 场景 | 时长 | 缓动 |
|------|------|------|
| 按钮 hover | 200ms | ease |
| 卡片 hover | 200ms | ease |
| 抽屉滑入/出 | 300ms | cubic-bezier(0.4, 0, 0.2, 1) |
| Modal 进入 | 200ms | ease-out |
| Modal 离开 | 150ms | ease-in |
| 对话气泡 | 250ms | ease-out + 轻微 translateY(8px → 0) |
| Tab 下划线移动 | 200ms | ease |
| 数字变动 | 600ms | ease（CountUp 动画） |

**禁用**：bounce / elastic / 任何旋转动效

---

## 11. ECharts 主题配置

```js
// web/src/utils/echartsTheme.js
export const dealmindTheme = {
  color: ['#1a1a1a', '#888888', '#525252'],
  backgroundColor: 'transparent',
  textStyle: { fontFamily: 'inherit', color: '#525252', fontSize: 12 },
  title: { textStyle: { color: '#1a1a1a', fontWeight: 600, fontSize: 14 } },
  line: { lineStyle: { width: 2 }, symbolSize: 6 },
  categoryAxis: {
    axisLine: { lineStyle: { color: '#e5e4e0' } },
    axisTick: { show: false },
    axisLabel: { color: '#888' },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#888' },
    splitLine: { lineStyle: { color: '#ececec', type: 'dashed' } },
  },
  legend: { textStyle: { color: '#525252' }, icon: 'circle' },
  tooltip: {
    backgroundColor: '#1a1a1a',
    borderColor: '#1a1a1a',
    textStyle: { color: '#fff', fontSize: 12 },
    extraCssText: 'border-radius: 8px; padding: 8px 12px;',
  },
};
```

---

## 12. Element Plus 主题覆盖

> 策略：**保留 Element Plus，全局覆盖 CSS Variables + 自封装 4 个关键组件**

### 12.1 CSS Variables 覆盖（`web/src/styles/element-overrides.scss`）

```scss
:root {
  /* 品牌色 - 全部覆盖为黑色，去掉默认蓝 */
  --el-color-primary: #1a1a1a;
  --el-color-primary-light-3: #404040;
  --el-color-primary-light-5: #666666;
  --el-color-primary-light-7: #999999;
  --el-color-primary-light-8: #cccccc;
  --el-color-primary-light-9: #e5e5e5;
  --el-color-primary-dark-2: #000000;

  --el-color-success: #2d7a3e;
  --el-color-warning: #9a6c1a;
  --el-color-danger: #9b2c2c;
  --el-color-info: #888888;

  /* 文字 */
  --el-text-color-primary: #1a1a1a;
  --el-text-color-regular: #525252;
  --el-text-color-secondary: #888;
  --el-text-color-placeholder: #bfbfbf;

  /* 背景 */
  --el-bg-color: #ffffff;
  --el-bg-color-page: #f7f6f3;
  --el-bg-color-overlay: #ffffff;
  --el-fill-color: #f0efeb;
  --el-fill-color-light: #fafaf8;
  --el-fill-color-lighter: #fcfcfa;
  --el-fill-color-blank: #ffffff;

  /* border */
  --el-border-color: #e5e4e0;
  --el-border-color-light: #ececea;
  --el-border-color-lighter: #f0efeb;
  --el-border-color-darker: #d4d3cf;

  /* 圆角 */
  --el-border-radius-base: 8px;
  --el-border-radius-small: 4px;
  --el-border-radius-round: 16px;
  --el-border-radius-circle: 100%;

  /* 字体 */
  --el-font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
                    "Microsoft YaHei", "Inter", sans-serif;
  --el-font-size-base: 14px;
}

/* 全局基础 */
html, body {
  background-color: var(--el-bg-color-page);
  color: var(--el-text-color-primary);
  font-family: var(--el-font-family);
  font-size: var(--el-font-size-base);
  -webkit-font-smoothing: antialiased;
}

/* 卡片去阴影 + 大圆角 */
.el-card {
  border-radius: 16px;
  border: 1px solid var(--el-border-color);
  box-shadow: none !important;
}

/* 按钮：主按钮黑底 */
.el-button--primary {
  background: #1a1a1a;
  border-color: #1a1a1a;
  font-weight: 500;
}
.el-button--primary:hover {
  background: #000;
  border-color: #000;
}
.el-button {
  border-radius: 8px;
  font-weight: 500;
  transition: all 200ms ease;
}
.el-button--default {
  border-color: var(--el-border-color-darker);
}

/* 输入框 */
.el-input__wrapper {
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--el-border-color-darker) inset !important;
  background: #fff;
  padding: 4px 12px;
}
.el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1.5px #1a1a1a inset !important;
}

/* 表格 */
.el-table {
  --el-table-border-color: transparent;
  --el-table-row-hover-bg-color: #fafaf8;
  --el-table-header-bg-color: #fafaf8;
}
.el-table thead th {
  font-weight: 500;
  color: #888;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.el-table th, .el-table td {
  border-bottom: 1px solid var(--el-border-color) !important;
}

/* Tag */
.el-tag {
  border-radius: 4px;
  border: none;
  font-weight: 500;
  font-size: 12px;
}

/* 菜单 */
.el-menu {
  background: transparent;
  border-right: none !important;
}
.el-menu-item {
  height: 40px;
  line-height: 40px;
  border-radius: 8px;
  margin: 2px 8px;
  color: var(--el-text-color-primary);
}
.el-menu-item:hover { background: rgba(0,0,0,0.04); }
.el-menu-item.is-active {
  background: #e8e7e3;
  color: #1a1a1a;
  font-weight: 500;
}

/* Tab */
.el-tabs__active-bar {
  background-color: #1a1a1a;
  height: 2px;
}
.el-tabs__nav-wrap::after { background-color: var(--el-border-color); }
.el-tabs__item {
  font-weight: 500;
  color: #888;
}
.el-tabs__item.is-active { color: #1a1a1a; }

/* Drawer */
.el-drawer__header {
  margin-bottom: 0;
  padding: 20px 24px;
  border-bottom: 1px solid var(--el-border-color);
}
.el-drawer__body { padding: 24px; }

/* Dialog */
.el-dialog { border-radius: 16px; overflow: hidden; }
.el-dialog__header { padding: 20px 24px; border-bottom: 1px solid var(--el-border-color); }
.el-dialog__body { padding: 24px; }
.el-dialog__footer { padding: 16px 24px; border-top: 1px solid var(--el-border-color); }

/* Slider 黑色 */
.el-slider__bar { background-color: #1a1a1a; }
.el-slider__button {
  border-color: #1a1a1a;
  background-color: #1a1a1a;
}

/* 数字 tabular */
.dm-numeric { font-variant-numeric: tabular-nums; }
```

### 12.2 必须自封装的 4 个组件

| 组件 | 路径 | 说明 |
|------|------|------|
| `DmStatCard` | `web/src/components/DmStatCard.vue` | 数字卡（含趋势 chip），Element 无对应 |
| `DmPressureBar` | `web/src/components/DmPressureBar.vue` | 压力进度条（左端点 + 滑块） |
| `DmDialogueBubble` | `web/src/components/DmDialogueBubble.vue` | 对话气泡（含 Persona / Sales / Judge 三态） |
| `DmEmpty` | `web/src/components/DmEmpty.vue` | 空状态（lucide Inbox 图标 + 文字） |

### 12.3 字体 / 全局样式入口

`web/src/styles/global.scss`：
```scss
@import './element-overrides.scss';
@import './tokens.scss'; // CSS variables 自定义 token

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--dm-bg);
  color: var(--dm-text);
}

/* 滚动条美化 */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb {
  background: #d4d3cf;
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover { background: #888; }
```

---

## 13. 实施清单（Stage 0 时严格按此执行）

### 13.1 必装依赖

```bash
# 替换 @element-plus/icons-vue 为 lucide
npm install lucide-vue-next

# 字体（可选）
npm install @fontsource/inter @fontsource/jetbrains-mono
```

### 13.2 必装样式文件

```
web/src/styles/
  ├── element-overrides.scss   # Element Plus CSS variables 覆盖
  ├── tokens.scss              # 设计 token（颜色/字体/间距）
  ├── global.scss              # 全局基础（body / 滚动条 / 工具类）
  └── components/              # 自封装组件局部样式
```

### 13.3 必做的封装组件

| 优先级 | 组件 | 时机 |
|--------|------|------|
| P0 | `DmEmpty`（空状态） | Stage 0 |
| P0 | `DmStatCard`（数字卡） | Stage 8 |
| P0 | `DmPressureBar`（进度条） | Stage 3 |
| P0 | `DmDialogueBubble`（对话气泡） | Stage 6a |
| P1 | `DmPageHeader`（页面标题 + subtitle） | Stage 0 |
| P1 | `DmAvatar`（头像 + fallback） | Stage 0 |

### 13.4 设计走查清单（每个页面完成时核对）

- [ ] 整页背景 `#f7f6f3`，卡片白底 + 1px border
- [ ] 没有蓝色（除非状态信息）
- [ ] 所有按钮主黑次白
- [ ] 所有圆角 ≥ 8px
- [ ] 没有重阴影
- [ ] 图标统一 lucide（无 element 自带 icon）
- [ ] 数字 tabular-nums 对齐
- [ ] 标题字重对比明显
- [ ] 卡片 padding ≥ 24px
- [ ] 中文字体优先 PingFang SC

---

## 14. 设计资源

| 项 | 来源 |
|----|------|
| 参考图 | `design/ref_01~05.png` |
| 图标库 | https://lucide.dev/ |
| 字体 | 系统字体优先（PingFang SC / Microsoft YaHei） |
| 配色灵感 | Notion / Linear / Vercel Design System |
| 插画风格 | 线性手绘黑灰；登录页素材已就绪：`design/login-illustration.png`（610×410，从 ref_01 精确裁剪） |

---

## 15. 待办事项（产品交付前）

- [x] ~~准备登录页插画 SVG（参考 ref_01 左侧 2 人对话场景，黑灰线条）~~ → 已生成 `design/login-illustration.png`（610×410，直接由 ref_01 裁剪）
- [ ] 准备 DealMind LOGO（暂用文字 + lucide brain 图标，后期替换）
- [ ] 录制 / 截图各页面成品作为视觉回归基线（Stage 12 时做）

---

**本文档为整个项目唯一视觉与交互规范。Stage 0 ~ Stage 14 任何前端代码都必须遵守此规范。设计走查时拿 13.4 清单一项项过。**
