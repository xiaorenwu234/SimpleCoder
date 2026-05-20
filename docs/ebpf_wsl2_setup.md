# WSL2 eBPF 环境配置指南

SimpleCoder 使用 eBPF kretprobe 追踪线程级文件 I/O 字节数，本文记录在 WSL2 下的完整配置步骤。

---

## 环境说明

| 项目 | 版本/值 |
|---|---|
| 系统 | WSL2（Ubuntu 24.04） |
| Python | 3.12（conda: simple-coder） |
| BCC | 0.35.0（系统包 `/usr/lib/python3/dist-packages/bcc`） |
| 内核 | `5.15.x-microsoft-standard-WSL2` |

**注意**：WSL2 内核含 `CONFIG_IKHEADERS=m`，支持加载 kheaders 模块暴露内核头文件，
BCC 编译 eBPF 程序依赖此头文件。

---

## 第一步：安装系统级 BCC

```bash
sudo apt update
sudo apt install -y python3-bcc linux-tools-common
```

**重要**：不要用 `pip install bcc`，PyPI 上的 `bcc` 是空 stub 包（只有元数据，没有 `BPF` 类），
系统真实 bcc 在 `/usr/lib/python3/dist-packages/bcc/`。

验证：
```bash
python3 -c "import sys; sys.path.insert(0, '/usr/lib/python3/dist-packages'); from bcc import BPF; print('OK')"
```

---

## 第二步：加载 kheaders 内核模块

BCC 编译 eBPF 程序需要内核头文件，WSL2 通过 `kheaders` 模块提供：

```bash
sudo modprobe kheaders
```

验证模块加载：
```bash
ls /sys/kernel/kheaders.tar.xz   # 应该存在此文件
```

BCC 首次编译时会自动解压到 `/tmp/kheaders-{version}/`。

**常见问题**：若编译报 `"header file ownership unexpected"`，是因为 `/tmp/kheaders-*/`
目录所有者不是 root（uid≠0）。修复方法：
```bash
sudo rm -rf /tmp/kheaders-*
sudo python3 -c "import sys; sys.path.insert(0, '/usr/lib/python3/dist-packages'); from bcc import BPF"
# 以 root 身份预提取，确保目录 uid=0
```

---

## 第三步：赋予 Python 解释器 BPF 能力

WSL2 默认 `unprivileged_bpf_disabled=2`，普通用户无法使用 BPF。
通过 `setcap` 给 Python 解释器授权（无需 root 运行整个程序）：

```bash
sudo setcap cap_bpf,cap_perfmon,cap_net_admin+eip \
    $(which python3)
# 如果使用 conda 环境，需要指定 conda 内的 python 路径：
sudo setcap cap_bpf,cap_perfmon,cap_net_admin+eip \
    /home/xht/miniconda3/envs/simple-coder/bin/python3.12
```

验证权限：
```bash
getcap /home/xht/miniconda3/envs/simple-coder/bin/python3.12
# 输出应含：cap_net_admin,cap_bpf,cap_perfmon=eip
```

---

## 第四步：配置 tracefs 权限

BPF kretprobe 需要写入 `/sys/kernel/tracing/kprobe_events`：

```bash
sudo chmod a+rx  /sys/kernel/tracing
sudo chmod a+rw  /sys/kernel/tracing/kprobe_events
```

**说明**：此权限重启后失效。如需持久化，可写入 `/etc/rc.local` 或 systemd 服务：
```bash
# /etc/rc.local（在 exit 0 之前添加）
chmod a+rx  /sys/kernel/tracing
chmod a+rw  /sys/kernel/tracing/kprobe_events
```

---

## 第五步：验证整体配置

运行以下脚本，确认 eBPF 可正常采集 I/O 字节数：

```bash
cd /home/xht/SimpleCoder
python3 -c "
import sys, threading, time
sys.path.insert(0, '.')
from tools.tracer import EBPFIOCollector

c = EBPFIOCollector()
print(f'available={c.available}')
print(f'tid_offset={c._tid_offset}')   # WSL2 通常为 5000-6000

if c.available:
    with open('/home/xht/test_io.bin', 'wb') as f:
        f.write(b'X' * 10000)
    time.sleep(0.1)
    r, w = c.get_thread_io(threading.get_native_id())
    print(f'write_bytes={w} (expected >= 10000): {\"PASS\" if w >= 10000 else \"FAIL\"}')
    c.cleanup()
"
```

期望输出：
```
available=True
tid_offset=5269
write_bytes=xxxxx (expected >= 10000): PASS
```

---

## WSL2 特有问题：PID 命名空间偏移

**现象**：`bpf_get_current_pid_tgid()` 返回的 TID 与 Python `threading.get_native_id()` 不一致，
导致按 TID 查找 BPF map 失败。

**原因**：WSL2 内核的 BPF helper 返回全局命名空间 PID，而 Python 用户空间 API 返回
WSL2 命名空间内的 PID，两者之间有固定偏移（本机测试为 **5269**）。

**SimpleCoder 的解决方案**（已内置于 `EBPFIOCollector`）：
- 在 `_ensure_loaded()` 中调用 `_calibrate_tid_offset()`
- 写入特征字节数 → 在 BPF map 中找到对应条目 → 计算 `bpf_tid - os_tid` 的差值
- 后续所有 `get_thread_io(tid)` 调用自动补偿偏移：`bpf_tid = os_tid + offset`
- 无需手动配置，跨 WSL2 实例自动校准

---

## 关于 `/proc/self/io` 不可用

WSL2 环境中，`/proc/self/io` 读取会返回 `Permission denied`，
原因是 WSL2 的 ptrace 访问控制机制，即使对自身进程也不允许普通用户读取。

`CONFIG_TASK_IO_ACCOUNTING=y` 虽然已启用，但访问受到 ptrace scope 限制，
因此 SimpleCoder 选择 eBPF 方案而非 `/proc/*/io`。

---

## 每次开机后需重新执行的命令

WSL2 重启后以下配置会失效，需重新执行：

```bash
# 1. 加载 kheaders 模块（如 BCC 提示找不到头文件时）
sudo modprobe kheaders

# 2. 开放 tracefs 写权限
sudo chmod a+rx /sys/kernel/tracing
sudo chmod a+rw /sys/kernel/tracing/kprobe_events
```

`setcap` 权限是持久化的（写入 ELF 文件），无需每次重设。

---

## 快速排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `ImportError: cannot import name 'BPF'` | conda 环境装了 PyPI stub bcc | 代码中已处理：自动插入 `/usr/lib/python3/dist-packages` 路径 |
| `Failed to compile BPF module` + `kernel headers` | kheaders 未加载 | `sudo modprobe kheaders` |
| `header file ownership unexpected` | `/tmp/kheaders-*/` uid≠0 | `sudo rm -rf /tmp/kheaders-*` 然后以 root 预提取 |
| `open(/sys/kernel/tracing/kprobe_events): Permission denied` | tracefs 未开放写权限 | `sudo chmod a+rw /sys/kernel/tracing/kprobe_events` |
| `available=True` 但 `io_write_bytes` 始终为 0 | TID 偏移未校准 | 检查 `c._tid_offset`，应为正整数（WSL2 通常 5000+） |
| `Operation not permitted` 加载 BPF | Python 没有 CAP_BPF | 重新执行 `sudo setcap cap_bpf,cap_perfmon,cap_net_admin+eip <python路径>` |
