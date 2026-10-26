# Rupis

**R**edstone **s**cript —— 面向 Minecraft 红石结构的脚本语言与解释器。
**注意，当前版本并不是正式版，在Rupis ide或是rupis解释器中还有很多问题，请谨慎使用！**

Rupis 用来描述红石电路：写 `.rpi` 脚本，解释器把它编译成一份"方块世界数据"，
再导出成 `/setblock` 命令、JSON，或 Java 版结构方块直接加载的 `.mcstructure` 文件。

```
dpos base[100,64,200]
drp high{rsig=15}

strudef rep_unit(facing, delay){locked=false}:{
    rrep{facing=facing,delay=delay,locked=locked}[0,0,0]
    rw{rsig=15}[1,0,0]
}

def rep_chain(n, f):{
    for i = (0 to n-1):{
        stru rep_unit(f,1){}[base + xi]
    }
    return 0
}

rep_chain(5, east)
```

---

## 一、快速开始

解释器本身不需要任何第三方库，只要 Python 3.8+。

```bash
python main.py examples/demo.rpi                       # 输出 /setblock 命令
python main.py examples/demo.rpi --format json         # 输出 JSON
python main.py examples/demo.rpi --format structure -o demo.mcstructure
python main.py examples/demo.rpi --format summary      # 只看统计
python main.py examples/demo.rpi --check               # 只做语法检查
python -m rupis examples/demo.rpi                      # 等价写法
```

想要图形界面就启动自带的 **Rupis IDE**（需要一个 Qt 绑定，见第二节）：

```bash
pip install PySide6          # 或者 PyQt6
python main.py --ide          # 打开 IDE
python ide.py examples/demo.rpi   # 直接打开某个脚本
```

在游戏里使用：把 `--format commands` 输出的命令整段粘贴进聊天栏（先 `/gamerule commandBlockOutput false` 更干净），
或者把 `.mcstructure` 放进存档的 `structures/` 目录，用结构方块加载。

跑测试：

```bash
python -m unittest discover -s tests
```

---

## 二、命令行参数

| 参数 | 说明 |
| ---- | ---- |
| `脚本.rpi` | 要执行的脚本 |
| `--ide` | 启动图形界面 IDE（可以跟一个脚本文件） |
| `-f, --format` | `commands`（默认）/ `json` / `structure` / `summary` |
| `-o, --output` | 输出到文件；不给就打印到标准输出 |
| `--check` | 只做语法检查，不执行 |
| `-v, --verbose` | 执行时把每条放置指令实时打印到标准错误 |
| `--data-version` | `.mcstructure` 的 DataVersion，默认 3955（1.21.4） |

---

## 三、Rupis IDE

自带的图形编辑器，用 Qt 写的（PySide6 / PyQt6 / PyQt5 都能跑，代码里做了兼容层）。

```bash
pip install PySide6
python main.py --ide
python ide.py examples/demo.rpi
```

界面：

```
┌ 菜单栏 ─────────────────────────────────────────────┐
│ 工具栏：新建 打开 保存 │ ▶运行 ✓检查 导出结构 │ 主题   │
├──────────┬─────────────────────────────────────────┤
│ 脚本列表  │ 查找/替换条（Ctrl+F 时弹出来）             │
│          ├─────────────────────────────────────────┤
│          │ 编辑器（行号 + 语法高亮）                │
│          ├─────────────────────────────────────────┤
│          │ 提示栏（当前关键字 / 元件 / 状态键的说明）   │
│          ├─────────────────────────────────────────┤
│          │ [输出] [控制台] [终端]  ← 标签页切换        │
│          │  运行结果 / 交互式 Rupis / cmd 终端        │
├──────────┴─────────────────────────────────────────┤
│ 状态栏：提示信息 │ 文件名 │ 行:列                      │
└────────────────────────────────────────────────────┘
```

功能：

| 功能 | 说明 |
| ---- | ---- |
| 语法高亮 | 关键字、元件指令、内置常量、字符串、注释、数字、结构/函数名 |
| 脚本列表 | 左边列出文件夹里的 `.rpi`，**单击直接打开**，当前打开的文件会高亮 |
| 行号槽 | 左边独立绘制，点击行号直接跳过去 |
| 自动缩进 | 回车继承上一行缩进；`{` 之后自动多缩进一级 |
| 整块缩进 | `Tab` / `Shift+Tab` 对选中行批量缩进 / 反缩进 |
| 括号配对 | 输入 `(` `[` `{` 自动补右括号，再按右括号直接跳过 |
| 括号高亮 | 光标贴着的括号会高亮，并配对到另一个（跳过字符串和注释） |
| 批量注释 | `Ctrl+/` 给选中行加 / 去 `//` |
| 补全 | `Ctrl+Space`，包含关键字、元件、你自己定义的 `stru`/`def` 名；`lib` 导入的模块，输入 `模块名.` 还会补出该模块的成员 |
| 提示栏 | 光标停在关键字 / 元件 / 状态键上时，下面显示它的用法说明 |
| 查找替换 | `Ctrl+F` / `Ctrl+H`，支持正则、区分大小写、全部替换，命中处高亮 |
| 跳转到定义 | `F12` 跳到 `strudef` / `def` 的定义处 |
| 整行操作 | `Alt+↑/↓` 搬移整行，`Ctrl+Shift+D` 复制行，`Ctrl+Shift+K` 删行 |
| 字号缩放 | `Ctrl+=` / `Ctrl+-` / `Ctrl+0` |
| 后台运行 | 脚本在子线程里跑，界面不卡；出错时自动跳到出错行并标红 |
| 内嵌终端 | 底部面板带一个 cmd 终端，工作目录就是 IDE 的工作路径 |
| 导出 | `.mcstructure`、`/setblock` 命令（`.mcfunction`）、JSON，三种格式 |
| 主题切换 | 深色 / 浅色，主题 / 字号 / 窗口大小会记下来 |
| 右键菜单 | 撤销重做、注释、跳转到定义、查找 |

### 底部面板：输出 / 控制台 / 终端

底部有三页，用标签切换（`Ctrl+1` 输出、`Ctrl+2` 控制台、`Ctrl+3` 终端）。

**输出** 页放运行结果：方块统计 + 全部 `/setblock` 命令，可以一键复制。

**控制台** 页是个交互式 Rupis 解释器，一行一行写、回车就执行：

```
› dpos base[100,64,200]
› rw{rsig=15}[base]
已放置 1 个方块（当前共 1 个）
› base
(100, 64, 200)
› 1 + 2 * 3
7
```

- 会话状态一直保留：`dpos` / `drp` 变量、函数、结构、已放置的方块都能接着用
- 代码块可以跨行写（`{` 之后接着敲，`}` 收尾，提示符会变成 `…`）
- 上下方向键翻历史
- 出错只打印消息，不会打断会话
- 命令：`:help` `:reset` `:world` `:vars` `:load 文件路径`
- 「载入当前脚本」按钮把编辑器里正在写的脚本跑进当前会话，方便对着它试验

**终端** 页是能真正敲命令的 cmd（Windows）/ sh（其他平台）：

```
D:\large_project\Rupis>dir /b
examples
ide.py
main.py
README.md
rupis
tests
D:\large_project\Rupis>cd examples
D:\large_project\Rupis\examples>echo 到了 examples
到了 examples
```

- **工作目录就是 IDE 的工作路径**：IDE 打开了脚本文件夹就跟着它走，还没打开就是启动 IDE 时的目录；提示符里显示的就是当前目录
- 「转到脚本目录」一键跳回 IDE 正在编辑的文件夹，「选择目录…」可以随便挑
- `cd` 之后目录会一直留着，下一条命令就在新目录里跑
- `Ctrl+C` 打断正在跑的命令（连它起的子进程一起收拾掉），`Ctrl+L` 清屏
- 上下方向键翻历史
- 一条命令一个进程：所以 `dir`、`cd`、`python xxx.py`、`git status` 都正常，
  但需要真终端的交互式程序（`python` 不带参数这种）会因为拿不到输入而直接退出

快捷键：

| 键 | 功能 | 键 | 功能 |
| -- | ---- | -- | ---- |
| `F5` | 运行 | `Ctrl+S` | 保存 |
| `F9` | 检查语法 | `Ctrl+E` | 导出 `.mcstructure` |
| `Ctrl+N` | 新建 | `Ctrl+O` | 打开 |
| `Ctrl+F` / `Ctrl+H` | 查找 / 替换 | `F3` / `Shift+F3` | 查找下一个 / 上一个 |
| `F12` | 跳转到定义 | `Ctrl+G` | 跳转到行 |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | 输出 / 控制台 / 终端 | `Ctrl+L` | 清除输出 |
| `Ctrl+/` | 注释 / 取消注释 | `Alt+↑/↓` | 上移 / 下移整行 |
| `Ctrl+Shift+D` | 复制当前行 | `Ctrl+Shift+K` | 删除当前行 |
| `Ctrl+=` / `Ctrl+-` | 放大 / 缩小字号 | | |

完整的清单在「帮助 → 快捷键一览」。
| `Ctrl+Space` | 补全 | `Ctrl+/` | 注释 / 取消注释 |

---

## 四、语言规范

### 4.1 基础约定

- 坐标格式 `[x,y,z]`，坐标系与 MC 原版一致（Y 为高度）。
- 注释：`// 单行注释`、`/* 多行注释 */`（`/** ... **/` 同样可用）。
- 标识符：字母、数字、下划线，不能以数字开头，**区分大小写**。
- 表达式：支持 `+ - * / %`、比较 `== != > < >= <=`、逻辑 `&& ||`、一元 `-` 与 `!`。
- 语句结尾的分号 `;` 可写可不写。

### 4.2 `dpos` 坐标变量与 `drp` 状态模板变量

`dpos` 和 `drp` 现在都是**带名字的变量**，可以声明任意多个：

```
dpos 名称[x,y,z]        // 声明/覆盖一个 dpos 坐标变量
drp 名称{键=值, ...}     // 声明/覆盖一个 drp 状态模板变量
```

```
dpos base[100,64,200]     // 坐标变量 base = (100,64,200)
dpos spawn[0,64,0]        // 坐标变量 spawn = (0,64,0)
drp  high{rsig=15}        // 状态模板 high = {rsig=15}
drp  low{rsig=1,powered=false}
drp  off{low}             // drp 变量也可以引用另一个 drp 变量
```

引用方式：

| 位置 | 写法 | 含义 |
| ---- | ---- | ---- |
| 坐标槽 | `[base]` | 用 dpos 变量 `base` 的坐标 |
| 坐标槽 | `[base + x1,y2]` | `base` 再叠加偏移 |
| 状态槽 | `{high}` | 用 drp 变量 `high` 的状态模板 |

```
rw{rsig=15}[base + x1]      // 显式状态 + 坐标变量
rw{high}[base]              // drp 模板 + 坐标变量
rw{high}[base + x0,y1,z0]   // drp 模板 + 带偏移的坐标变量
```

**没有"当前默认"这回事**：变量名互不影响，不写引用就不会生效。
不写状态槽 = 这个方块没有任何自定义状态（用 Minecraft 自己的默认值）。

### 4.3 放置指令

`rw` **专属于红石粉**，其他红石元件各有独立指令。

| 指令 | 对应元件 | 常用状态参数 |
| ---- | -------- | ------------ |
| `rw` | 红石粉 redstone_wire | `rsig`(0~15)、`len`、`axis` |
| `rrep` | 红石中继器 repeater | `facing`、`delay`(1~4)、`locked`、`powered` |
| `rco` | 红石比较器 comparator | `facing`、`mode`(compare/subtract)、`powered` |
| `obs` | 侦测器 observer | `facing` |
| `rtorch` | 红石火把 redstone_torch | `powered` |
| `rlamp` | 红石灯 redstone_lamp | `powered` |
| `piston` | 活塞 piston | `facing`、`extended` |
| `sticky` | 粘性活塞 sticky_piston | `facing`、`extended` |
| `rbl` | 快捷方块（石头、玻璃、石英块……） | 方块自身状态 |
| `block` | 原生方块（完整命名空间 ID） | 方块自身状态 |

```
rw {rsig=15}[base + x1]
rw {rsig=12, len=4}[base + x0,y1,z0]
rrep {facing=east, delay=2, locked=false}[base + x0,y0,z1]
rbl stone{}[base + y1]
block minecraft:iron_block{waterlogged=false}[base + x2]
```

#### 状态键 → Minecraft 属性名对照

Rupis 用自己的状态名，导出时自动翻译成 MC 真实属性名：

| Rupis 键 | MC 属性 | 适用元件 |
| -------- | ------- | -------- |
| `rsig` | `power` | rw |
| `powered` | `lit` | rtorch / rlamp |
| `facing` / `delay` / `locked` | 同名 | rrep |
| `mode` | `mode` | rco |
| `extended` | `extended` | piston / sticky |

#### `len` 与 `axis`（rw 专用扩展）

`len` 生成连续长线，`axis` 指定延伸方向（默认 `x`）：

```
rw{rsig=15, len=4}[base]              // 连续 4 格，沿 X
rw{rsig=12, len=3, axis=z}[base + x5] // 沿 Z 轴排 3 格
```

#### `rbl` 可用缩写

`stone`、`smoothstone`、`cobblestone`、`stonebrick`、`brick`、`quartz`、`smoothquartz`、
`glass`、`glasspane`、`obsidian`、`netherrack`、`iron`、`gold`、`diamond`、`emerald`、
`wool`、`concrete`、`terracotta`、`slab`、`stairs`、`ironbars`、`chest`、`furnace`,
`hopper`、`target`、`noteblock`、`redstone_block`、`lever`、`button`、`daylight`、
`sea_lantern`、`glowstone`、`snow`、`sand`、`dirt`、`planks`、`log` 等；
`rbl` 里也允许直接写完整 ID（`rbl minecraft:xxx{}`）。

### 4.4 结构定义 `strudef` 与调用 `stru`

```
strudef 结构名(参数列表){默认状态}:{
    // 内部指令，相对坐标 [0,0,0] 是结构原点
    rrep{facing=facing,delay=delay}[0,0,0]
    rw{rsig=15}[1,0,0]
}

stru 结构名(参数列表){覆盖状态}[坐标]
```

- 结构内部坐标是**局部相对坐标**，以 `stru` 的调用位置为原点。
- 参数列表可为空，多个参数逗号分隔。
- `{默认状态}` 可省略，也可以写一个 drp 变量名（`{high}`）；省略时 `stru` 调用不传状态就用元件默认值。
- `{默认状态}` 里的键在结构体内**可以当变量读**（如 `locked=locked`）。
- `stru` 的 `{覆盖状态}` 与 `strudef` 的 `{默认状态}` 合并，调用方优先；
  写 `{}` 表示"不覆盖"。

### 4.5 函数定义 `def`

```
def 函数名(参数列表):{
    // 控制流、表达式、也可以放放置指令
    return 返回值
}
```

- `def` 是**逻辑函数**：参数是局部变量，本身不生成方块（但函数体里可以调用 `stru`/`def`）。
- `strudef` 是**方块模板**：`stru` 调用，带局部坐标系。
- 省略 `def` 后的冒号也行（`def f(a){...}`）。

### 4.6 控制流

```
if(表达式):{
    // 条件成立执行
}else:{
    // 不成立执行
}

for 变量 = (起始 to 结束):{
    // 闭区间递增；起始 > 结束时自动倒序
}

while(表达式):{
    // 条件为真持续执行
}
```

额外支持 `break` / `continue`。`if` / `for` / `while` 的冒号可省略。

### 4.7 变量

```
let 变量名 = 表达式;
```

也支持直接赋值（扩展语法，变量不存在时视为新建）：`i = i + 1;`

### 4.8 内置常量

| 常量 | 含义 |
| ---- | ---- |
| `north` `south` `east` `west` `up` `down` | 方向 |
| `x` `y` `z` | 坐标轴名（配合 `axis=` 用） |
| `compare` `subtract` | 比较器模式 |
| `true` `false` | 布尔 |

### 4.9 导入 Python 模块 `lib`

`lib` 就是 Python 的 `import`：把 Python 标准库（或者装好的第三方库）拉进脚本。

```
lib math                ≡ import math
lib math as m           ≡ import math as m
lib os.path             ≡ import os.path       （绑定的是顶层包 os）
lib os.path as p        ≡ import os.path as p  （p 才是整个 os.path）
```

导入后按 `模块名.成员` 使用，成员可以是常量、函数、类：

```
lib math
rw{rsig=math.floor(3.7)}[0,0,0]      // → rsig=3
rw{rsig=math.sqrt(16)}[0,0,0]        // → rsig=4
```

调用可以带关键字参数（注意：Rupis 自己 `def` 出来的函数**不支持**关键字参数）：

```
lib textwrap
let w = textwrap.wrap("hello world", width=5)
```

规则：

- 凡是能写表达式的地方都能用模块成员 —— 状态槽、`let`、`if` 条件、函数返回值都行。
- `lib` 写在函数体里时，只在该函数的作用域内生效。
- 模块找不到、属性不存在、对象不可调用 → 报错并指出行列。
- 状态槽里的值必须是数字或布尔（和别的状态键一样），字符串会报错。
- IDE 里写了 `lib math` 之后，输入 `math.` 再按 `Ctrl+Space`，会列出该模块的成员。

---

## 五、语义细则

### 5.1 状态优先级

| 优先级 | 来源 | 说明 |
| ------ | ---- | ---- |
| 1 | 状态槽里显式写的 `{键=值}` | 只用这些键；元件不支持的键 → **报错并指出行列** |
| 1' | 状态槽里引用的 drp 变量 `{high}` | 取模板里的键；元件不支持的键 → **忽略**（模板语义） |
| 2 | 结构默认状态 | `strudef` 默认值 + `stru` 覆盖值合并；只填补上面没写的键 |
| 3 | （无） | 没有全局 drp，不写状态槽就没有任何状态 |

- 结构默认状态里元件不支持的键 → 忽略。
- 同一坐标被放置多次 → 后者覆盖前者（世界模型里只保留最终状态）。

### 5.2 坐标规则

| 写法 | 含义 |
| ---- | ---- |
| `[100,64,200]` | 绝对坐标（世界模式下） |
| `[base]` | dpos 变量 `base` 的坐标 |
| `[base + x1]` | `base` + X 轴偏移 1 |
| `[base + x-2,y1,z0]` | `base` + (-2, 1, 0) |
| `[base + xi]` | `base` + X 轴偏移 = 变量 `i` 的值 |
| `[base + zi]` | `base` + Z 轴偏移 = 变量 `i` 的值 |
| `[base + x20+3]` | `base` + X 轴偏移 23（扩展：偏移里可写简单算术） |
| 结构内的 `[1,0,0]` | 结构局部坐标，原点 = `stru` 调用位置 |

全局模式下 `[x,y,z]` 是绝对坐标；结构模式下 `[x,y,z]` 是相对结构原点的局部坐标，
**dpos 变量在结构内也一样**（结构内部所有坐标都是相对结构原点的）。

### 5.3 作用域

- 全局 `let` 在全局作用域；`if` / `for` / `while` 的代码块**不**另开作用域。
- `def` 的参数与函数体变量是局部变量，只能看到全局变量和其他函数。
- `strudef` 实例化时：参数 → 局部变量；默认状态里的键 → 也作为局部变量可读。
- `dpos` / `drp` 变量是全局的（在任何作用域都能引用），重复声明则后者覆盖前者。
- `lib` 导入的模块名跟普通变量一样受作用域约束：全局 `lib` 全局可见，
  写在 `def` 里的 `lib` 只在该函数里可见。

---

## 六、导出格式

| 格式 | 说明 |
| ---- | ---- |
| `commands` | `/setblock x y z minecraft:xxx[facing=east,delay=2]`，一行一个 |
| `json` | `{"size":[...],"origin":[...],"blocks":[{"pos":[..],"id":"..","states":{..}}]}` |
| `structure` | `.mcstructure`（gzip NBT），Java 版结构方块可直接加载 |
| `summary` | 方块总数、包围盒、按方块统计 |

`.mcstructure` 里 0 号调色板固定是 `minecraft:air`（空位全部指向它），
方块索引顺序为 `index = x + y*sizeX + z*sizeX*sizeY`。

---

## 七、项目结构

```
Rupis/
├── main.py              # 命令行入口（python main.py 脚本.rpi）
├── ide.py               # IDE 启动器（python ide.py 脚本.rpi）
├── rupis/
│   ├── __init__.py      # 对外 API：run_source / compile_source / parse_source
│   ├── __main__.py      # 支持 python -m rupis
│   ├── cli.py           # 命令行参数处理
│   ├── lexer.py         # 词法分析
│   ├── parser.py        # 语法分析（递归下降）→ AST
│   ├── ast_nodes.py     # AST 节点定义
│   ├── interpreter.py   # 执行 AST → 方块世界
│   ├── blocks.py        # 元件注册表、方向常量、rbl 缩写表
│   ├── exporters.py     # commands / json / structure / summary 导出
│   ├── nbt.py           # 极简 NBT 写入器
│   ├── errors.py        # 错误类型与源码定位
│   └── ide/             # 图形界面 IDE
│       ├── __init__.py  # 入口（python -m rupis.ide）
│       ├── __main__.py
│       ├── qtcompat.py  # PySide6 / PyQt6 / PyQt5 兼容层
│       ├── theme.py     # 深色 / 浅色配色 + 样式表
│       ├── syntax.py    # 关键字、元件、常量词表 + 说明文字
│       ├── highlighter.py # QSyntaxHighlighter 高亮规则
│       ├── editor.py    # 编辑器控件（行号、缩进、括号、补全、查找、整行操作）
│       ├── find.py      # 查找 / 替换面板
│       ├── console.py   # 交互式 Rupis 控制台
│       ├── terminal.py  # 内嵌 cmd / sh 终端
│       └── app.py       # 主窗口
├── examples/
│   ├── demo.rpi         # 官方规范示例 + 扩展用法（含 dpos / drp 变量）
│   └── lib_demo.rpi     # lib 导入 Python 模块示例
└── tests/
    ├── test_rupis.py    # 解释器单元测试（76 个）
    └── test_ide.py      # IDE 单元测试（103 个）
```

作为库使用：

```python
from rupis import run_source

interp = run_source(open("demo.rpi", encoding="utf-8").read(), "demo.rpi")
for placement in interp.world.values():
    print(placement.command())
```

---

## 八、已知限制

- 解释器只生成"方块世界数据"，不做红石电路的**逻辑仿真**（不会算出电路是否真的触发）。
- `rw` 的 `len` 只沿单轴延伸；拐弯的长线请拆成多条指令。
- 函数调用层数上限 256、循环迭代上限 100 万，防止死循环拖死进程。
- `.mcstructure` 导出的是 Java 版格式；基岩版需要转换。
- IDE 需要额外装一个 Qt 绑定（PySide6 / PyQt6 / PyQt5）；解释器本身零依赖。
- IDE 里的终端没有真正的伪终端（PTY）：需要交互式输入的程序（`python` 不带参数、
  `top` 之类）拿不到输入会直接退出；普通的命令行工具不受影响。
- `lib` 会真的执行被导入模块的 Python 代码（`import` 本来就这样），等于脚本可以调用
  任意 Python 功能；只在自己写的脚本里用。IDE 做模块成员补全时也会在 IDE 进程里
  导入一次该模块。
