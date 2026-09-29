# `.face` 二进制格式规范

本文档记录小米手环 11 动态表盘文件 `.face` 的二进制布局。

**这份规范是通过对比官方编译器 `Compiler.exe` 的输入输出、逐字节分析其产物得出的，
不是官方文档。** 它在本项目对应的固件/工具链版本上实测有效，换版本不保证仍然成立。

所有多字节整数均为**小端序（little-endian）**。

> 参考实现（两份逐字节等价的独立实现）：
>
> - Python：`watchface-tool/watchface_tool/face_builder.py`
> - Java：`watchface-android/core/face/FaceBuilder.java`
>
> 想验证一份 `.face` 是否符合本规范，直接跑 `tools/verify_face.py`。

---

## 1. 整体布局

```
偏移          长度                 内容
──────────────────────────────────────────────────────────────
[0, 64)       64 B                 文件头
[64, 172)     108 B                Title 区
[172, 272)    100 B                元数据区
272 起        (N+1) × 16 B         索引表（含 1 条哨兵）
↑ 索引表结束 = 文件数据区起始
              ...                  文件数据区（各文件项，4 字节对齐）
              ...                  尾部位图（212×520 RGBA8888）
```

`N` = 文件数（帧图片数 + 1 个 `main.lua`）。

---

## 2. 文件头 `[0, 64)`

| 偏移 | 长度 | 值 | 说明 |
|---|---|---|---|
| 0 | 4 | `5A A5 34 12` | magic |
| 4 | 1 | `0` | 固定 |
| 5 | 1 | `10` | **表盘 ID 的长度** |
| 6 | 10 | 0 | 填充 |
| 16 | 4 | `0x00000800` | 固定常量 |
| 20 | 8 | 0 | 填充 |
| 28 | 4 | `1` | 固定 |
| 32 | 4 | `data_end` | **文件数据区的结束偏移**（= 尾部位图起始） |
| 36 | 4 | 0 | 填充 |
| 40 | 10 | ASCII | **表盘 ID**（不足补 `\0`） |
| 50 | 14 | 0 | 填充 |

### ⚠️ 坑：`[4]` 和 `[5]` 是两个独立字节

`[5]` 是 ID 长度（单字节），**不是** `uint16` 的一部分。

如果把 `[4..5]` 当成一个小端 `uint16` 来写（即写成 `0x0A00`），
整个文件会从第 4 字节开始**整体错位 1 字节**，产物无法被识别。
这个坑在早期实现里踩过。

---

## 3. Title 区 `[64, 172)`

| 偏移 | 长度 | 说明 |
|---|---|---|
| 64 | 40 | 填充 |
| **104** | **16** | **Title 字段**（ASCII，null 结尾） |
| 120 | 52 | 填充 |

### ⚠️ 坑：Title 是**固定 16 字节**

不是 12 字节，也不是变长。写成 12 会整体错位。

---

## 4. 元数据区 `[172, 272)`

| 偏移 | 值 | 说明 |
|---|---|---|
| 172 | `data_end` | 文件数据区结束偏移 |
| 176 | `1` | 固定 |
| 180 | `256` | 固定 |
| 184 | `0` | 固定 |
| 188 | `INDEX_START` (272) | 索引表起始 |
| 192 | `0` | 固定 |
| 196 | `INDEX_START` | 同上 |
| 200 | `0` | 固定 |
| 204 | `INDEX_START` | 同上 |
| 208 | `0` | 固定 |
| 212 | `INDEX_START` | 同上 |
| **216** | **`N`** | **文件数** |
| 220 | `INDEX_START` | 同上 |
| 224 | `0` | 固定 |
| 228 | `idx_end` | 有效索引表结束 = `272 + N × 16` |
| 232 | `0` | 固定 |
| 236 | `idx_end` | 同上 |
| 240 | `0` | 固定 |
| 244 | `idx_end` | 同上 |
| 248 | `0` | 固定 |
| 252 | `idx_end` | 同上 |
| 256 | `0` | 固定 |
| 260 | `0` | 固定 |
| **264** | **`idx_end`** | 同上 |
| **268** | **`16`** | **索引表条目大小** |

> 注意 `idx_end = 272 + N × 16`，**不含哨兵那一条**；
> 而数据区实际起始是 `272 + (N+1) × 16`（含哨兵）。

---

## 5. 索引表 `272` 起，`(N+1) × 16` 字节

每条 16 字节：

| 偏移 | 长度 | 字段 |
|---|---|---|
| +0 | 2 | `index`（从 0 递增） |
| +2 | 2 | `0x0500`（固定标记） |
| +4 | 4 | `0`（保留） |
| +8 | 4 | `offset`（该文件项在文件中的绝对偏移） |
| +12 | 4 | `size`（见下） |

### ⚠️ 关键：`size` 的计算方式

```
size = 20 + len(文件名) + len(数据)
```

- `20` = 文件项描述头的长度（3 + 1 + 16）
- **`size` 不包含末尾的 4 字节对齐 padding**

这一点很反直觉，但实测如此。写成含 padding 的值会导致数据区偏移计算全部错乱。

### 哨兵条目

索引表最后**额外多一条**，内容为：

```
index = N - 1      （重复最后一条的 index）
0x0500
0
offset = 0
size   = 0
```

---

## 6. 文件项（数据区）

每个文件项的布局：

| 长度 | 内容 |
|---|---|
| 3 B | **数据大小**（小端，只取低 3 字节 = 最多 16 MB） |
| 1 B | **文件名长度** |
| 16 B | 全零 |
| `文件名长度` | 文件名（ASCII） |
| `数据大小` | 文件内容 |
| 0~3 B | **4 字节对齐** padding |

其中 padding 长度为：

```python
pad = (4 - size % 4) % 4     # size = 20 + len(名) + len(数据)
```

### ⚠️ 坑：4 字节对齐是硬性的

不对齐会在数据区里留下 1/2/3 字节的 gap。这是**手工拼装失败最常见的原因** ——
产物能被解析，但内容是错位的。

### 文件名规则

- 前缀是 **`lua/`**，不是 `app/lua/`。
  例如 `lua/face_01.png`、`lua/face_02.png`、`lua/main.lua`。
- 帧名从 **`face_01`** 开始（1-based），不是 `face_00`。
- 扩展名必须与 `main.lua` 里引用的**完全一致**。
  改了编码格式（PNG ↔ JPEG）而没同步 Lua，表现是**手环上黑屏**。

---

## 7. 尾部位图

紧跟在数据区之后，**没有偏移索引指向它**，只能靠前面的数据累加算出来。

| 长度 | 内容 |
|---|---|
| 4 B | 全零 |
| 2 B | 宽度 u16（= 212） |
| 2 B | 高度 u16（= 520） |
| 4 B | 位图字节数（= 440 960） |
| 440 960 B | RGBA8888 像素数据 |

### ⚠️ 固定 431 KB，与帧数无关

`212 × 520 × 4 = 440 960` 字节（431 KB）。这是**表盘选择器里显示的静态预览图**，
大小由屏幕分辨率决定，**不随动画帧数变化**。

后果：**帧数很少时，这部分开销可能比全部帧数据加起来还大。**
所以"把几十帧的表盘再压小"是不可能的 —— 431 KB 是硬地板。

早期曾误以为它能缩小（格式上宽高是 u16 字段），但实测官方产物就是 212×520，
改成更小的尺寸并没有解决问题 —— **别在这上面花时间**。

---

## 8. 最小可复现骨架

```python
import struct

MAGIC            = b"\x5a\xa5\x34\x12"
ID_LEN           = 10
TITLE_LEN        = 16
INDEX_ENTRY_SIZE = 16
INDEX_START      = 272

def build_face(title, face_id, files, preview_rgba, w=212, h=520):
    """files: [(name, data), ...]；name 形如 'lua/face_01.png'"""
    n = len(files)
    first_data_off = INDEX_START + (n + 1) * INDEX_ENTRY_SIZE

    # 1) 算每个文件项的偏移与 size
    entries, cur = [], first_data_off
    for name, data in files:
        nb = name.encode("ascii")
        size = 20 + len(nb) + len(data)      # 不含 padding
        entries.append((nb, data, cur, size))
        cur += size + (4 - size % 4) % 4
    data_end = cur

    out = bytearray()

    # 2) 文件头 64B
    out += MAGIC
    out += b"\x00" + bytes([ID_LEN])         # [4]=0, [5]=10 —— 两个独立字节
    out += b"\x00" * 10                      # [6-15]
    out += struct.pack("<I", 0x800)          # [16-19]
    out += b"\x00" * 8
    out += struct.pack("<I", 1)              # [28-31]
    out += struct.pack("<I", data_end)       # [32-35]
    out += b"\x00" * 4
    out += str(face_id).encode("ascii").ljust(ID_LEN, b"\x00")[:ID_LEN]   # [40-49]
    out += b"\x00" * 14

    # 3) Title 区
    out += b"\x00" * 40
    out += title.encode("ascii", "replace").ljust(TITLE_LEN, b"\x00")[:TITLE_LEN]  # [104-119]
    out += b"\x00" * 52

    # 4) 元数据区
    idx_end = INDEX_START + n * INDEX_ENTRY_SIZE
    out += struct.pack("<I", data_end)
    for v in (1, 256, 0):
        out += struct.pack("<I", v)
    for _ in range(4):
        out += struct.pack("<II", INDEX_START, 0)
    out += struct.pack("<I", n)              # [216] 文件数
    out += struct.pack("<II", INDEX_START, 0)
    for _ in range(3):
        out += struct.pack("<II", idx_end, 0)
    out += struct.pack("<II", 0, idx_end)
    out += struct.pack("<I", INDEX_ENTRY_SIZE)   # [268]

    # 5) 索引表 + 哨兵
    for i, (nb, data, off, size) in enumerate(entries):
        out += struct.pack("<HHIII", i, 0x0500, 0, off, size)
    out += struct.pack("<HHIII", n - 1, 0x0500, 0, 0, 0)

    # 6) 数据区
    for nb, data, off, size in entries:
        out += (len(data) & 0xFFFFFF).to_bytes(3, "little")
        out += bytes([len(nb)])
        out += b"\x00" * 16
        out += nb + data
        out += b"\x00" * ((4 - size % 4) % 4)

    # 7) 尾部位图
    out += b"\x00" * 4
    out += struct.pack("<HHI", w, h, len(preview_rgba))
    out += preview_rgba

    return bytes(out)
```

---

## 9. `.fprj`（项目文件，与 `.face` 无关但同属构建输入）

如果走官方 `Compiler.exe` 路线，还需要一个 `.fprj` 项目文件：

- 编码：**UTF-16 LE + BOM（`FF FE`）**
- 换行：**LF**
- 关键属性：`DeviceType="466"`、`Shape="34"`（Lua 表盘）

见 `watchface-tool/watchface_tool/fprj.py`。

---

## 10. 构建管线（走官方编译器时）

```
.fprj + app/lua/*.png|jpg + main.lua
        │
        ▼
Compiler.exe -b <fprj> <outDir> <name.face> <faceId>
        │
        ▼
     .face
```

`Compiler.exe` 只会把 `.info` 写到 `<fprj 同级目录>/output/`，
**这个目录必须预先存在**，否则会静默失败。

注意 `Compiler.exe` 是 **x86 Windows 二进制**，安卓上跑不了 ——
这正是本项目安卓版采用纯代码拼装（第 8 节）的原因。
