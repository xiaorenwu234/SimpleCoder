"""
轻量级 Trace 追踪器 — 输出 Chrome Trace Event 格式（JSON）

兼容查看工具:
  - chrome://tracing          (Chrome 浏览器地址栏输入)
  - https://ui.perfetto.dev/  (拖入 JSON 文件)
  - https://www.speedscope.app/ (火焰图视图)

硬件监控维度（每次工具调用均采集差量）:
  粒度策略:
    线程级 (thread-local) : CPU、块IO、缺页、上下文切换、文件IO字节(eBPF)、网络IO字节(eBPF)
    进程级 (process-level): 内存RSS/swap、网络IO降级(psutil)、线程数、FD数（Linux无线程级等价）

  执行时间: 墙上时钟 wall_ms（进程级）
  CPU:      thread_cpu_ms（线程级，CLOCK_THREAD_CPUTIME_ID，并发安全，首选）
            cpu_user_ms / cpu_sys_ms / cpu_total_ms（线程级，RUSAGE_THREAD）
            cpu_pct_end（进程级瞬时占比，仅供参考）
  内存:     （已移除 RSS / swap 指标）
  IO块:     io_read_ops / io_write_ops（线程级，RUSAGE_THREAD）
  IO字节:   io_read_bytes / io_write_bytes（线程级，eBPF syscall追踪；不可用时=-1）
            io_bytes_source: 'thread_ebpf' | 'unavailable'
  网络:    net_sent_bytes / net_recv_bytes（线程级 eBPF sock_sendmsg/sock_recvmsg kretprobe；不可用时降级 psutil 系统级）
            net_bytes_source: 'thread_ebpf' | 'process_psutil'
  缺页:     page_faults_min / page_faults_maj（线程级，RUSAGE_THREAD）
  上下文:   ctx_vol / ctx_invol / ctx_total（线程级，RUSAGE_THREAD）
  线程:     thread_count / thread_delta（进程级）
  文件描述符: open_fds / open_fds_delta（进程级）


eBPF 文件路径追踪:
  原理: kprobe 挂载到 do_sys_openat2 (Linux 5.6+) 或 do_sys_open (旧内核)，
         捕获 openat 入口参数中的文件名，通过 BPF perf buffer 送到用户层。
  快照: _hw_snapshot 如快照当前线程已见文件集合，_hw_delta 取差集即本次调用新增文件。
  files_accessed_source: 'thread_ebpf'（线程级）| 'process_psutil'（降级进程级）
  注意: eBPF 捕获的是传入 openat 的原始路径（可能为相对路径），降级时 psutil 返回绝对路径。
  不可用时自动降级至 psutil。
"""
import sys
import time
import json
import threading
import os
import resource
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Dict, Any, List, Tuple, Set, FrozenSet
import asyncio


class EBPFIOCollector:
    """使用 eBPF kretprobe 采集线程级文件 I/O 字节数。

    通过 kretprobe 追踪 ksys_read/ksys_write 及向量 I/O 系统调用返回值，
    按 OS 线程 TID 在 BPF hash map 中累积字节数。

    WSL2 兼容：自动校准 bpf_tid_offset（WSL2 中 bpf_get_current_pid_tgid()
    返回的 TID 与 threading.get_native_id() 存在固定偏移，本类在加载时自动
    测量该偏移并在查询时补偿，无需 root 或手动配置）。

    使用方式:
        collector = EBPFIOCollector()
        if collector.available:
            r, w = collector.get_thread_io(tid)  # 累计值，取差量
        collector.cleanup()
    """

    # BPF C 程序：kretprobe 方式（不依赖 tracepoint 结构体，WSL2 / 旧内核友好）
    # 无进程级过滤 —— 在 Python 层通过 TID + 偏移量做进程隔离
    _BPF_PROG = """
#include <uapi/linux/ptrace.h>
#include <linux/types.h>

struct tid_io_t {
    u64 read_bytes;
    u64 write_bytes;
};

BPF_HASH(tid_io, u32, struct tid_io_t, 65536);

static __always_inline void _add_io(long n, int is_read) {
    if (n <= 0) return;
    u32 t = (u32)bpf_get_current_pid_tgid();
    struct tid_io_t z = {};
    struct tid_io_t *v = tid_io.lookup_or_try_init(&t, &z);
    if (!v) return;
    if (is_read) v->read_bytes  += (u64)n;
    else         v->write_bytes += (u64)n;
}

int kret_read(struct pt_regs *ctx)    { _add_io(PT_REGS_RC(ctx), 1); return 0; }
int kret_write(struct pt_regs *ctx)   { _add_io(PT_REGS_RC(ctx), 0); return 0; }
int kret_readv(struct pt_regs *ctx)   { _add_io(PT_REGS_RC(ctx), 1); return 0; }
int kret_writev(struct pt_regs *ctx)  { _add_io(PT_REGS_RC(ctx), 0); return 0; }
int kret_pread(struct pt_regs *ctx)   { _add_io(PT_REGS_RC(ctx), 1); return 0; }
int kret_pwrite(struct pt_regs *ctx)  { _add_io(PT_REGS_RC(ctx), 0); return 0; }

// ---- 文件路径追踪 (kprobe on do_sys_openat2 / do_sys_open) ----
#define MAX_FILE_PATH 256

struct file_event_t {
    u32 tid;
    char fname[MAX_FILE_PATH];
};

BPF_PERF_OUTPUT(file_events);

static __always_inline void _emit_open(struct pt_regs *ctx, const char __user *filename) {
    struct file_event_t ev = {};
    ev.tid = (u32)bpf_get_current_pid_tgid();
    bpf_probe_read_user_str(ev.fname, sizeof(ev.fname), filename);
    file_events.perf_submit(ctx, &ev, sizeof(ev));
}

// Linux 5.6+: do_sys_openat2(int dfd, const char __user *filename, struct open_how *how)
int kprobe_openat2(struct pt_regs *ctx) {
    const char __user *filename = (const char __user *)PT_REGS_PARM2(ctx);
    _emit_open(ctx, filename);
    return 0;
}

// Linux < 5.6: do_sys_open(int dfd, const char __user *filename, int flags, umode_t mode)
int kprobe_open(struct pt_regs *ctx) {
    const char __user *filename = (const char __user *)PT_REGS_PARM2(ctx);
    _emit_open(ctx, filename);
    return 0;
}
"""

    # (内核函数名, BPF程序函数名, 是否必需)
    # 必需项失败直接报错；可选项失败静默跳过
    # 使用 bytes 字面量（BCC 部分版本要求 bytes，兼容新旧版本）
    _PROBE_MAP = [
        (b'ksys_read',    b'kret_read',   True),
        (b'ksys_write',   b'kret_write',  True),
        (b'ksys_readv',   b'kret_readv',  False),
        (b'ksys_writev',  b'kret_writev', False),
        (b'ksys_pread64', b'kret_pread',  False),
        (b'ksys_pwrite64',b'kret_pwrite', False),
    ]

    # kretprobe on sock_sendmsg / sock_recvmsg，按线程 TID 隔离：
    #   - 比 TRACEPOINT_PROBE 更兼容（不依赖 CONFIG_FTRACE_SYSCALLS / tracefs）
    #   - sock_sendmsg 捕获所有 socket 发送（write/send/sendto/sendmsg 最终均经此路径）
    #   - sock_recvmsg 捕获所有 socket 接收
    #   - 按 TID 隔离：并发工具各自独立，互不干扰
    #   - 工具自身的同步 HTTP 请求（requests 等）从工具线程发出，TID 匹配，能正确捕获
    #   - LLM API 调用发生在工具执行间隙（asyncio 等待工具完成），不在工具窗口内，不会混入
    _NET_BPF_PROG = """
#include <linux/types.h>
#include <uapi/linux/ptrace.h>

struct tid_net_t {
    u64 send_bytes;
    u64 recv_bytes;
};

// key: TID（线程 ID），按线程隔离，并发工具互不干扰
BPF_HASH(tid_net, u32, struct tid_net_t, 65536);

static __always_inline void _add_net(long n, int is_send) {
    // sock_sendmsg/sock_recvmsg 返回 int，x86-64 上高 32 位不保证符号扩展
    // 必须先截断为 int 再判断正负，否则 -9(EFAULT) 等错误码会被当成大正数累加
    int ret = (int)n;
    if (ret <= 0) return;
    u32 tid = (u32)bpf_get_current_pid_tgid();   // 低 32 位 = TID
    struct tid_net_t z = {};
    struct tid_net_t *v = tid_net.lookup_or_try_init(&tid, &z);
    if (!v) return;
    if (is_send) __sync_fetch_and_add(&v->send_bytes, (u64)(u32)ret);
    else         __sync_fetch_and_add(&v->recv_bytes, (u64)(u32)ret);
}

int kret_sock_sendmsg(struct pt_regs *ctx) {
    _add_net(PT_REGS_RC(ctx), 1);
    return 0;
}

int kret_sock_recvmsg(struct pt_regs *ctx) {
    _add_net(PT_REGS_RC(ctx), 0);
    return 0;
}
"""

    def __init__(self) -> None:
        self._bpf = None
        self._net_bpf = None            # 独立的网络 I/O BPF 实例
        self._available: Optional[bool] = None
        self._init_error: str = ""
        # WSL2 PID 命名空间偏移：bpf_tid = os_tid + _tid_offset
        # 标准 Linux 为 0；WSL2 通常为固定正整数（如 5269）
        self._tid_offset: int = 0
        # 文件路径追踪（eBPF kprobe on openat）
        # _tid_files 按 bpf_tid 存储所有曾见过的文件路径（累计集合，用于快照差量）
        self._tid_files: Dict[int, Set[str]] = {}
        self._tid_files_lock = threading.Lock()
        self._file_tracking_available: bool = False
        self._net_tracking_available: bool = False   # 网络I/O eBPF追踪是否可用
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()

    def _ensure_loaded(self) -> bool:
        """首次调用时编译并加载 eBPF 程序（结果缓存，仅加载一次）。

        导入策略（依次尝试）:
          1. 直接 from bcc import BPF（正常安装或系统路径已在 sys.path）
          2. 若 BPF 不存在于当前 bcc（PyPI stub 包），插入系统路径后重新加载
        加载后自动校准 WSL2 TID 偏移量。
        """
        if self._available is not None:
            return self._available

        BPF = None
        import_error: str = ""

        # --- 尝试 1: 直接导入 ---
        try:
            from bcc import BPF as _BPF  # type: ignore
            BPF = _BPF
        except ImportError as e:
            import_error = str(e)

        # --- 尝试 2: PyPI stub 覆盖了系统 bcc（conda 环境常见问题）---
        # 特征：import 成功但 BPF 不在模块中（stub 包只有 __author__ 等元数据）
        if BPF is None or not callable(BPF):
            try:
                import sys as _sys, importlib
                _SYS_BCC = '/usr/lib/python3/dist-packages'
                if _SYS_BCC not in _sys.path:
                    _sys.path.insert(0, _SYS_BCC)
                # 强制重新加载，绕过 conda env 中的 stub
                import bcc as _bcc_mod
                importlib.reload(_bcc_mod)
                BPF = getattr(_bcc_mod, 'BPF', None)
            except Exception as e2:
                import_error = import_error or str(e2)

        if BPF is None or not callable(BPF):
            self._init_error = (
                f"bcc.BPF 不可用（{import_error or 'BPF 未在模块中'}）; "
                "请运行: sudo apt install python3-bcc"
            )
            self._available = False
            return False

        try:
            self._bpf = BPF(text=self._BPF_PROG.encode('utf-8'))
            # 挂载 kretprobe（必需项失败抛异常，可选项静默跳过）
            for kern_fn, bpf_fn, required in self._PROBE_MAP:
                try:
                    if required:
                        self._bpf.attach_kretprobe(event=kern_fn, fn_name=bpf_fn)
                    else:
                        # 可选探针：临时重定向 stderr fd 来屏蔽 BCC C 层的
                        # "cannot attach kprobe" 调试消息
                        _devnull = os.open(os.devnull, os.O_WRONLY)
                        _saved   = os.dup(2)
                        os.dup2(_devnull, 2)
                        try:
                            self._bpf.attach_kretprobe(event=kern_fn, fn_name=bpf_fn)
                        except Exception:
                            pass
                        finally:
                            os.dup2(_saved, 2)
                            os.close(_devnull)
                            os.close(_saved)
                except Exception as _e:
                    if required:
                        raise RuntimeError(
                            f"必需的 kretprobe {kern_fn!r} 挂载失败: {_e}"
                        )
            # 校准 WSL2 TID 偏移（标准 Linux 返回 0，无副作用）
            self._tid_offset = self._calibrate_tid_offset()
            self._available = True
            # ---- 可选：文件路径追踪（kprobe on openat，不影响 IO 字节采集）----
            try:
                self._bpf[b'file_events'].open_perf_buffer(self._file_event_callback)
                _file_probe_ok = False
                for _kfn, _bfn in [
                    (b'do_sys_openat2', b'kprobe_openat2'),
                    (b'do_sys_open',    b'kprobe_open'),
                ]:
                    _devnull = os.open(os.devnull, os.O_WRONLY)
                    _saved   = os.dup(2)
                    os.dup2(_devnull, 2)
                    try:
                        self._bpf.attach_kprobe(event=_kfn, fn_name=_bfn)
                        _file_probe_ok = True
                    except Exception:
                        pass
                    finally:
                        os.dup2(_saved, 2)
                        os.close(_devnull)
                        os.close(_saved)
                    if _file_probe_ok:
                        break
                if _file_probe_ok:
                    self._file_tracking_available = True
                    self._poll_stop.clear()
                    self._poll_thread = threading.Thread(
                        target=self._poll_perf_buffer,
                        daemon=True,
                        name='ebpf-file-poll',
                    )
                    self._poll_thread.start()
            except Exception:
                pass  # 文件追踪可选，失败不影响 IO 字节采集
            # ---- 可选：独立网络 I/O BPF 程序（kretprobe on sock_sendmsg/sock_recvmsg）----
            # 与文件 IO BPF 完全隔离：加载失败不影响文件 IO 追踪
            try:
                _devnull = os.open(os.devnull, os.O_WRONLY)
                _saved   = os.dup(2)
                os.dup2(_devnull, 2)
                try:
                    self._net_bpf = BPF(text=self._NET_BPF_PROG.encode('utf-8'))
                    self._net_bpf.attach_kretprobe(
                        event=b'sock_sendmsg', fn_name=b'kret_sock_sendmsg'
                    )
                    self._net_bpf.attach_kretprobe(
                        event=b'sock_recvmsg', fn_name=b'kret_sock_recvmsg'
                    )
                    self._net_tracking_available = True
                except Exception:
                    self._net_bpf = None
                    self._net_tracking_available = False
                finally:
                    os.dup2(_saved, 2)
                    os.close(_devnull)
                    os.close(_saved)
            except Exception:
                pass  # 网络I/O追踪可选，失败不影响其他采集
        except Exception as exc:
            err = str(exc)
            if 'kernel headers' in err or (
                'No such file or directory' in err and 'modules' in err
            ):
                self._init_error = (
                    "WSL2 内核头文件缺失，eBPF 编译失败。"
                    "解决方案: sudo modprobe kheaders"
                )
            else:
                self._init_error = err
            if self._bpf is not None:
                try:
                    self._bpf.cleanup()
                except Exception:
                    pass
                self._bpf = None
            self._available = False
        return self._available

    def _calibrate_tid_offset(self) -> int:
        """校准 WSL2 下 bpf_tid 和 os_tid 的偏移量。

        原理：向临时文件写入特征字节数，在 BPF map 中找到对应条目，
        计算 bpf_tid - os_tid 的差值。标准 Linux 返回 0。

        若校准失败（如写入被缓存未触发 kretprobe），静默返回 0。
        """
        import time as _time, tempfile as _tempfile, ctypes as _ctypes
        os_tid = threading.get_native_id()
        # 基于 TID 生成大概率唯一的字节数（~128KB–192KB 范围）
        MAGIC = 131072 + ((os_tid * 31337 + 12345) & 0xFFFF)
        try:
            # 快照写入前的 map 状态
            before: dict = {}
            try:
                for k, v in self._bpf[b'tid_io'].items():
                    before[k.value] = int(v.write_bytes)
            except Exception:
                pass

            # 写入 MAGIC 字节到临时文件（触发 ksys_write kretprobe）
            with _tempfile.NamedTemporaryFile(prefix='_bpf_cal_', delete=True) as tmp:
                tmp.write(b'\x00' * MAGIC)
                tmp.flush()
            _time.sleep(0.05)

            # 找到写字节差量 ≈ MAGIC 的条目
            for k, v in self._bpf[b'tid_io'].items():
                bpf_tid_val = k.value
                delta = int(v.write_bytes) - before.get(bpf_tid_val, 0)
                if abs(delta - MAGIC) < 1024:  # 1KB 容差
                    return bpf_tid_val - os_tid
            return 0
        except Exception:
            return 0

    @property
    def available(self) -> bool:
        """eBPF 是否可用（延迟初始化，首次访问时加载）。"""
        return self._ensure_loaded()

    @property
    def init_error(self) -> str:
        """不可用时的错误信息。"""
        self._ensure_loaded()
        return self._init_error

    def _file_event_callback(self, cpu, data, size) -> None:
        """BPF perf buffer 回调，处理文件打开事件并按 bpf_tid 存储路径。"""
        try:
            event = self._bpf[b'file_events'].event(data)
            fname = bytes(event.fname).rstrip(b'\x00').decode('utf-8', errors='replace')
            if not fname:
                return
            bpf_tid = int(event.tid)
            with self._tid_files_lock:
                if bpf_tid not in self._tid_files:
                    self._tid_files[bpf_tid] = set()
                self._tid_files[bpf_tid].add(fname)
        except Exception:
            pass

    def _poll_perf_buffer(self) -> None:
        """后台线程：持续轮询 BPF perf buffer，将文件事件送入回调。"""
        while not self._poll_stop.is_set():
            try:
                if self._bpf is not None:
                    self._bpf.perf_buffer_poll(timeout=100)
            except Exception:
                break

    def get_thread_files_snapshot(self, tid: int) -> Optional[FrozenSet[str]]:
        """返回指定 OS TID 当前已见过的文件路径快照。

        用于 before/after 差量计算，差集即工具调用期间新开打的文件。
        返回 None 表示 eBPF 文件追踪不可用（应降级至 psutil）。
        返回空 frozenset 表示该线程尚无记录。

        Args:
            tid: threading.get_native_id() 返回的 OS 线程 ID。
        """
        if not self._file_tracking_available:
            return None
        bpf_tid = tid + self._tid_offset
        with self._tid_files_lock:
            return frozenset(self._tid_files.get(bpf_tid, set()))

    def get_thread_io(self, tid: int) -> Tuple[int, int]:
        """获取指定 OS TID 的累计文件 I/O 字节数 (read_bytes, write_bytes)。

        参数 tid 为 threading.get_native_id() 返回的 OS 线程 ID。
        内部自动补偿 WSL2 BPF TID 偏移（_tid_offset），调用方无需感知。

        返回 (-1, -1) 表示 eBPF 不可用（调用方应降级）。
        返回 (0, 0) 表示该线程尚无 I/O 记录。
        """
        if not self._ensure_loaded():
            return (-1, -1)
        import ctypes as _ctypes
        bpf_tid = tid + self._tid_offset
        try:
            key = _ctypes.c_uint32(bpf_tid)
            val = self._bpf[b'tid_io'][key]
            return (int(val.read_bytes), int(val.write_bytes))
        except KeyError:
            return (0, 0)
        except Exception:
            return (-1, -1)

    def get_thread_net(self, tid: int) -> Tuple[int, int]:
        """获取指定 OS TID 的累计网络 I/O 字节数 (send_bytes, recv_bytes)。

        按线程 TID 隔离，捕获 sock_sendmsg / sock_recvmsg kretprobe。
        工具自身的同步 HTTP 请求从工具线程发出，TID 匹配，能正确归属。
        LLM API 调用发生在工具执行间隙，不在工具窗口内，不会混入。

        返回 (-1, -1) 表示 eBPF 网络I/O追踪不可用（调用方应降级至 psutil）。
        返回 (0, 0) 表示该线程尚无网络 I/O 记录。
        """
        if not self._net_tracking_available or self._net_bpf is None:
            return (-1, -1)
        import ctypes as _ctypes
        bpf_tid = tid + self._tid_offset
        try:
            key = _ctypes.c_uint32(bpf_tid)
            val = self._net_bpf[b'tid_net'][key]
            return (int(val.send_bytes), int(val.recv_bytes))
        except KeyError:
            return (0, 0)
        except Exception:
            return (-1, -1)

    def cleanup(self) -> None:
        """释放 eBPF 程序资源，并停止 perf buffer 轮询线程。"""
        self._poll_stop.set()
        if self._bpf is not None:
            try:
                self._bpf.cleanup()
            except Exception:
                pass
            self._bpf = None
        if self._net_bpf is not None:
            try:
                self._net_bpf.cleanup()
            except Exception:
                pass
            self._net_bpf = None
            self._net_tracking_available = False


class Tracer:
    """Chrome Trace Event 格式的 span 追踪器，线程安全 + async 安全"""
    
    def __init__(self, output_path: str = "trace.json"):
        self._events: list = []
        self._lock = threading.Lock()
        self._start_time: float = time.time()
        self.output_path = Path(output_path)
        # 硬件资源采样: 用 start_span 返回的 ts 作为 key 存储快照
        self._span_hw: dict = {}
        # 工具硬件统计累加器: tool_name -> list of deltas
        self._tool_hw_stats: Dict[str, list] = {}
        # psutil 可用性缓存（避免每次 snapshot 都 import + 异常）
        self._psutil_available: Optional[bool] = None
        # 并发追踪（轻量版，用于检测 eBPF 指标污染）
        # asyncio 单线程中多个工具"并行"时共享同一 TID，eBPF 差量窗口会重叠
        # 通过计数器在 start/end 时检测重叠，标记受污染的采集数据
        self._concurrent_lock = threading.Lock()
        self._concurrent_active: int = 0
        # 平台检测（macOS ru_maxrss 单位为字节，Linux 为 KB）
        self._is_macos: bool = sys.platform == 'darwin'
        # eBPF 线程级 I/O 采集器（首选；不可用时 io_read/write_bytes = -1）
        self._ebpf: EBPFIOCollector = EBPFIOCollector()
        # 后台预热 eBPF（避免懒加载在第一次工具调用时污染 hw 指标）
        self._warmup_thread = threading.Thread(
            target=self._ebpf._ensure_loaded, daemon=True, name='ebpf-warmup'
        )
        self._warmup_thread.start()
        
    def _now_us(self) -> int:
        """返回自 trace 开始以来的微秒数"""
        return int((time.time() - self._start_time) * 1_000_000)
    
    def _add_event(
        self,
        name: str,
        ph: str,
        ts: int,
        tid: int = 1,
        pid: int = 1,
        cat: str = "",
        dur: int = 0,
        args: Optional[Dict[str, Any]] = None,
    ):
        event = {
            "name": name,
            "ph": ph,          # X=complete, B=begin, E=end
            "ts": ts,
            "pid": pid,
            "tid": tid,
        }
        if cat:
            event["cat"] = cat
        if dur:
            event["dur"] = dur
        if args:
            event["args"] = args
        with self._lock:
            self._events.append(event)
    
    def _hw_snapshot(self) -> Dict[str, Any]:
        """采集当前线程硬件资源快照。

        线程级指标（thread-local，并发安全）:
            tid            : OS 线程 ID (threading.get_native_id)
            thread_cpu_ns  : CLOCK_THREAD_CPUTIME_ID — 本线程精确 CPU 时间（纳秒）
            cpu_user       : RUSAGE_THREAD.ru_utime — 用户态 CPU（秒）
            cpu_sys        : RUSAGE_THREAD.ru_stime — 内核态 CPU（秒）
            io_in/out      : 块读/写操作次数 (ru_inblock/ru_oublock)
            ctx_vol/invol  : 自愿/非自愿上下文切换
            page_faults_*  : 次/主缺页
            ebpf_io_read   : eBPF 累计读字节（-1 表示不可用）
            ebpf_io_write  : eBPF 累计写字节（-1 表示不可用）

        进程级背景上下文（process-level，并发时不隔离，仅供参考）:
            max_rss_raw / mem_rss / mem_vms / mem_swap : 内存
            thread_count / open_fds : 线程数 / FD 数
            cpu_pct : 进程瞬时 CPU 占比
            ebpf_net_send/recv : 线程级网络 I/O 字节（eBPF send/recv 类系统调用）
            net_bytes_sent/recv : 网络 I/O（eBPF 不可用时 psutil 进程级降级）
            open_files_list : 打开文件列表
        """
        # === 线程级 CPU（CLOCK_THREAD_CPUTIME_ID，首选）===
        try:
            thread_cpu_ns = time.clock_gettime_ns(time.CLOCK_THREAD_CPUTIME_ID)
        except (AttributeError, OSError):
            thread_cpu_ns = -1

        # === RUSAGE_THREAD 线程级资源（不降级为 RUSAGE_SELF）===
        try:
            usage = resource.getrusage(resource.RUSAGE_THREAD)
        except (AttributeError, ValueError, OSError):
            usage = None

        # === psutil 可用性探测（一次性）===
        if self._psutil_available is None:
            try:
                import psutil
                psutil.Process(os.getpid()).memory_info()
                self._psutil_available = True
            except Exception:
                self._psutil_available = False

        # === OS 线程 ID（用于 eBPF 查询）===
        tid = threading.get_native_id()

        # === eBPF 线程级计数器快照（最优先读取，避免后续 /proc 文件读取污染 delta）===
        # 将 eBPF 读取放在所有文件 I/O（/proc、psutil）之前，确保 after-snapshot
        # 的 tracer 自身 IO 不会被计入工具的 io_read_bytes 差量。
        _ebpf_io_r, _ebpf_io_w       = self._ebpf.get_thread_io(tid)
        _ebpf_net_s, _ebpf_net_r     = self._ebpf.get_thread_net(tid)
        _ebpf_files_snap             = self._ebpf.get_thread_files_snapshot(tid)

        # === /proc/self/task/{tid}/stat — Linux per-thread user/sys CPU ticks ===
        # 比 RUSAGE_THREAD.ru_utime 更可靠（后者在部分 Linux 配置下始终返回 0）
        # 粒度 = 1/SC_CLK_TCK 秒（通常 10ms @ 100Hz），配合 CLOCK_THREAD_CPUTIME_ID 可合成高精度分时
        _proc_utime_ticks: int = -1
        _proc_stime_ticks: int = -1
        _proc_clk_tck: int = -1
        if sys.platform != 'darwin':
            try:
                _clk = os.sysconf('SC_CLK_TCK')
                with open(f'/proc/self/task/{tid}/stat') as _pf:
                    _s = _pf.read()
                # comm 字段可含空格/括号，通过最后一个 ')' 定位字段起点
                # 格式：pid (comm) state ppid pgrp session tty_nr tpgid flags
                #       minflt cminflt majflt cmajflt utime(11) stime(12) ...
                _ri = _s.rfind(')')
                _fs = _s[_ri + 2:].split()
                _proc_utime_ticks = int(_fs[11])
                _proc_stime_ticks = int(_fs[12])
                _proc_clk_tck     = _clk
            except Exception:
                pass

        # macOS ru_oublock / Linux ru_outblock 字段名差异兼容
        if usage is not None:
            io_out = getattr(usage, 'ru_oublock', None)
            if io_out is None:
                io_out = getattr(usage, 'ru_outblock', 0)
        else:
            io_out = 0

        snap: Dict[str, Any] = {
            # 线程级
            'tid':             tid,
            'thread_cpu_ns':   thread_cpu_ns,
            'cpu_user':        usage.ru_utime if usage is not None else 0.0,
            'cpu_sys':         usage.ru_stime if usage is not None else 0.0,
            'io_in':           getattr(usage, 'ru_inblock', 0) if usage is not None else 0,
            'io_out':          io_out,
            'ctx_vol':         getattr(usage, 'ru_nvcsw',  0) if usage is not None else 0,
            'ctx_invol':       getattr(usage, 'ru_nivcsw', 0) if usage is not None else 0,
            'page_faults_min': getattr(usage, 'ru_minflt', 0) if usage is not None else 0,
            'page_faults_maj': getattr(usage, 'ru_majflt', 0) if usage is not None else 0,
            # 进程级背景上下文
            'wall_ts':         time.perf_counter(),
            'mem_vms':         0,  # 已移除虚存指标
            'thread_count':    0,
            'open_fds':        0,
            'cpu_pct':         0.0,
            'net_bytes_sent':  0,
            'net_bytes_recv':  0,
            'open_files_list': [],
            # /proc/self/task/{tid}/stat Linux per-thread user/sys ticks
            'proc_utime_ticks': _proc_utime_ticks,
            'proc_stime_ticks': _proc_stime_ticks,
            'proc_clk_tck':     _proc_clk_tck,
            # eBPF 线程级计数器（已在 /proc 读取前采样，避免 tracer 自身 IO 污染 delta）
            'ebpf_io_read':        _ebpf_io_r,    # -1 表示不可用
            'ebpf_io_write':       _ebpf_io_w,
            'ebpf_net_send':       _ebpf_net_s,   # -1 表示不可用
            'ebpf_net_recv':       _ebpf_net_r,
            'ebpf_files_snapshot': _ebpf_files_snap,
        }

        # === psutil 进程级背景上下文 ===
        if self._psutil_available:
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                mem = proc.memory_info()
                # snap['mem_rss']  # 已移除 RSS 指标
                # snap['mem_vms']  # 已移除虚存指标
                snap['cpu_pct']      = proc.cpu_percent(interval=None)
                snap['thread_count'] = proc.num_threads()
                try:
                    snap['open_fds'] = proc.num_fds()
                except (AttributeError, psutil.AccessDenied):
                    pass
                try:
                    net = psutil.net_io_counters()
                    if net:
                        snap['net_bytes_sent'] = net.bytes_sent
                        snap['net_bytes_recv'] = net.bytes_recv
                except Exception:
                    pass
                try:
                    snap['open_files_list'] = [f.path for f in proc.open_files()]
                except (AttributeError, psutil.AccessDenied, OSError):
                    pass
            except Exception:
                pass

        return snap

    @staticmethod
    def _hw_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        """计算两次硬件快照之间的资源消耗差量。
    
        线程级指标（thread-local，并发安全）:
            thread_cpu_ms  : 本线程 CPU 时间（CLOCK_THREAD_CPUTIME_ID）。-1 表示不可用
            cpu_user_ms    : 用户态 CPU 差量（RUSAGE_THREAD）
            cpu_sys_ms     : 内核态 CPU 差量（RUSAGE_THREAD）
            cpu_total_ms   : cpu_user_ms + cpu_sys_ms
            io_read_ops    : 块读次数差量（RUSAGE_THREAD）
            io_write_ops   : 块写次数差量（RUSAGE_THREAD）
            ctx_vol/invol  : 自愿/非自愿上下文切换差量（RUSAGE_THREAD）
            ctx_total      : 上下文切换总计
            page_faults_*  : 次/主缺页差量（RUSAGE_THREAD）
            io_read_bytes  : 文件读字节（eBPF 线程级）。-1 表示不可用
            io_write_bytes : 文件写字节（eBPF 线程级）。-1 表示不可用
            io_bytes_source: 'thread_ebpf' | 'unavailable'
    
        进程级背景上下文（process-level，标注以下堆叠）:
            wall_ms         : 墙上时钟耗时
            cpu_pct_end     : 进程瞬时 CPU 占比 [进程]
            thread_count    : 结束时线程数 [进程]
            thread_delta    : 线程数变化 [进程]
            open_fds        : 结束时 FD 数 [进程]
            open_fds_delta  : FD 数变化 [进程]
            net_sent_bytes  : 发送字节差量（eBPF 线程级优先，降级至 psutil 进程级）
            net_recv_bytes  : 接收字节差量（同上）
            net_bytes_source: 'thread_ebpf' | 'process_psutil'
            files_accessed  : 新增打开文件列表 [进程]
        """
        ctx_vol   = after['ctx_vol']   - before['ctx_vol']
        ctx_invol = after['ctx_invol'] - before['ctx_invol']
    
        # 线程级 CPU（CLOCK_THREAD_CPUTIME_ID）
        b_ns = before.get('thread_cpu_ns', -1)
        a_ns = after.get('thread_cpu_ns', -1)
        thread_cpu_ms = (a_ns - b_ns) / 1_000_000 if (b_ns >= 0 and a_ns >= 0) else -1.0
    
        # === User/Sys CPU 分时 ===
        # 策略：/proc/self/task/{tid}/stat 低精度比率 × CLOCK_THREAD 高精度总量 → 高精度分时
        # 降级：RUSAGE_THREAD（Linux 下 ru_utime 可能始终为 0）
        b_pu   = before.get('proc_utime_ticks', -1)
        a_pu   = after.get('proc_utime_ticks',  -1)
        b_ps   = before.get('proc_stime_ticks', -1)
        a_ps   = after.get('proc_stime_ticks',  -1)
        clktck = after.get('proc_clk_tck', -1)

        if b_pu >= 0 and a_pu >= 0 and b_ps >= 0 and a_ps >= 0 and clktck > 0:
            du = max(0, a_pu - b_pu)   # user delta ticks
            ds = max(0, a_ps - b_ps)   # sys  delta ticks
            total_ticks = du + ds
            if total_ticks > 0 and thread_cpu_ms >= 0:
                # /proc 比率 × CLOCK_THREAD 精确总量 → 高精度 user/sys
                ur = du / total_ticks
                cpu_user_ms   = round(thread_cpu_ms * ur,        4)
                cpu_sys_ms    = round(thread_cpu_ms * (1.0 - ur), 4)
                cpu_split_src = 'proc_ratio+clock'
            elif thread_cpu_ms >= 0:
                # 工具运行时间 < tick 粒度（正常 < 10ms），无法区分 user/sys
                cpu_user_ms   = -1.0   # -1 表示 sub-tick 无法区分
                cpu_sys_ms    = -1.0
                cpu_split_src = 'sub_tick'
            else:
                # thread_cpu_ms 不可用，直接换算 ticks
                cpu_user_ms   = du * 1000.0 / clktck
                cpu_sys_ms    = ds * 1000.0 / clktck
                cpu_split_src = 'proc_stat'
        else:
            # 降级：RUSAGE_THREAD（Linux 下 ru_utime 可能始终为 0）
            cpu_user_ms   = (after['cpu_user'] - before['cpu_user']) * 1000
            cpu_sys_ms    = (after['cpu_sys']  - before['cpu_sys'])  * 1000
            cpu_split_src = 'rusage_thread'

        # cpu_total_ms 以 CLOCK_THREAD_CPUTIME_ID 为准（最精确）
        if thread_cpu_ms >= 0:
            cpu_total_ms = thread_cpu_ms
        elif cpu_user_ms >= 0 and cpu_sys_ms >= 0:
            cpu_total_ms = cpu_user_ms + cpu_sys_ms
        else:
            cpu_total_ms = 0.0
    
        # eBPF 线程级文件 I/O 字节差量
        ebpf_r_b = before.get('ebpf_io_read', -1)
        ebpf_r_a = after.get('ebpf_io_read', -1)
        ebpf_w_b = before.get('ebpf_io_write', -1)
        ebpf_w_a = after.get('ebpf_io_write', -1)
        if ebpf_r_b >= 0 and ebpf_r_a >= 0 and ebpf_w_b >= 0 and ebpf_w_a >= 0:
            io_read_bytes  = max(0, ebpf_r_a - ebpf_r_b)
            io_write_bytes = max(0, ebpf_w_a - ebpf_w_b)
            io_bytes_source = 'thread_ebpf'
        else:
            io_read_bytes  = -1
            io_write_bytes = -1
            io_bytes_source = 'unavailable'
    
        # 文件访问列表（优先 eBPF 线程级，降级至 psutil 进程级）
        _SYS_PREFIXES = ('/proc/', '/dev/', '/sys/', '/run/', '/lib', '/usr/lib', '/usr/share')
        ebpf_before_files: Optional[FrozenSet[str]] = before.get('ebpf_files_snapshot')
        ebpf_after_files:  Optional[FrozenSet[str]] = after.get('ebpf_files_snapshot')
        if ebpf_before_files is not None and ebpf_after_files is not None:
            # eBPF 线程级：只看本线程新增的文件路径
            new_files = ebpf_after_files - ebpf_before_files
            files_accessed = sorted(
                f for f in new_files
                if f and not any(f.startswith(p) for p in _SYS_PREFIXES)
            )[:10]
            files_accessed_source = 'thread_ebpf'
        else:
            # 降级： psutil 进程级（并发时不隔离）
            before_files = set(before.get('open_files_list', []))
            after_files  = set(after.get('open_files_list', []))
            files_accessed = sorted(
                f for f in (after_files - before_files)
                if not any(f.startswith(p) for p in _SYS_PREFIXES)
            )[:10]
            files_accessed_source = 'process_psutil'
    
        # 网络 I/O 字节（eBPF 线程级优先，降级至 psutil 进程级）
        ebpf_ns_b = before.get('ebpf_net_send', -1)
        ebpf_ns_a = after.get('ebpf_net_send', -1)
        ebpf_nr_b = before.get('ebpf_net_recv', -1)
        ebpf_nr_a = after.get('ebpf_net_recv', -1)
        if ebpf_ns_b >= 0 and ebpf_ns_a >= 0 and ebpf_nr_b >= 0 and ebpf_nr_a >= 0:
            net_sent_bytes   = max(0, ebpf_ns_a - ebpf_ns_b)
            net_recv_bytes   = max(0, ebpf_nr_a - ebpf_nr_b)
            net_bytes_source = 'thread_ebpf'
        else:
            # 降级: psutil 进程级全局网卡计数器（并发时不隔离）
            net_sent_bytes   = max(0, after['net_bytes_sent'] - before['net_bytes_sent'])
            net_recv_bytes   = max(0, after['net_bytes_recv'] - before['net_bytes_recv'])
            net_bytes_source = 'process_psutil'

        return {
            # === 线程级（thread-local）===
            'thread_cpu_ms':     thread_cpu_ms,
            'cpu_user_ms':       cpu_user_ms,    # -1 表示 sub-tick 无法区分 user/sys
            'cpu_sys_ms':        cpu_sys_ms,     # -1 表示 sub-tick
            'cpu_total_ms':      cpu_total_ms,   # 以 CLOCK_THREAD_CPUTIME_ID 为准
            'cpu_split_source':  cpu_split_src,  # 'proc_ratio+clock' | 'sub_tick' | 'proc_stat' | 'rusage_thread'
            'io_read_ops':       after['io_in']  - before['io_in'],
            'io_write_ops':      after['io_out'] - before['io_out'],
            'ctx_vol':           ctx_vol,
            'ctx_invol':         ctx_invol,
            'ctx_total':         ctx_vol + ctx_invol,
            'page_faults_min':   after['page_faults_min'] - before['page_faults_min'],
            'page_faults_maj':   after['page_faults_maj'] - before['page_faults_maj'],
            # eBPF 线程级文件 I/O 字节差量（-1 表示不可用）
            'io_read_bytes':     io_read_bytes,
            'io_write_bytes':    io_write_bytes,
            'io_bytes_source':   io_bytes_source,
            # 文件访问列表（线程级 eBPF 或降级进程级 psutil）
            'files_accessed':        files_accessed,
            'files_accessed_source': files_accessed_source,
            # === 进程级背景上下文（并发时不隔离，标注以下堆叠）===
            'wall_ms':           (after['wall_ts'] - before['wall_ts']) * 1000,
            'cpu_pct_end':       after['cpu_pct'],
            # mem_rss / peak_rss / mem_swap 已移除
            'thread_count':      after['thread_count'],
            'thread_delta':      after['thread_count'] - before['thread_count'],
            'open_fds':          after['open_fds'],
            'open_fds_delta':    after['open_fds'] - before['open_fds'],
            'net_sent_bytes':    net_sent_bytes,
            'net_recv_bytes':    net_recv_bytes,
            'net_bytes_source':  net_bytes_source,
        }
        
    @contextmanager
    def span(self, name: str, category: str = "", hw_profile: bool = False, **args):
        """同步 span，用 contextmanager 包裹代码块
        
        用法:
            with tracer.span("my_operation", category="db", hw_profile=True):
                do_something()
        """
        tid = threading.get_ident()
        ts_start = self._now_us()
        hw_start = self._hw_snapshot() if hw_profile else None
        try:
            yield
        finally:
            dur = self._now_us() - ts_start
            final_args = dict(args) if args else {}
            if hw_start is not None:
                final_args['hw'] = self._hw_delta(hw_start, self._hw_snapshot())
            self._add_event(name, "X", ts_start, tid=tid, cat=category, dur=dur, args=final_args if final_args else None)
    
    @asynccontextmanager
    async def async_span(self, name: str, category: str = "", hw_profile: bool = False, **args):
        """异步 span —— 支持在 async with 中使用
        
        用法:
            async with tracer.async_span("fetch", category="http", hw_profile=True):
                await fetch_data()
        """
        tid = threading.get_ident()
        ts_start = self._now_us()
        hw_start = self._hw_snapshot() if hw_profile else None
        try:
            yield
        finally:
            dur = self._now_us() - ts_start
            final_args = dict(args) if args else {}
            if hw_start is not None:
                final_args['hw'] = self._hw_delta(hw_start, self._hw_snapshot())
            self._add_event(name, "X", ts_start, tid=tid, cat=category, dur=dur, args=final_args if final_args else None)
    
    def start_span(self, name: str, category: str = "", hw_profile: bool = False, **args) -> int:
        """手动开始一个 span，返回开始时间戳。配合 end_span 使用（用于无法用 contextmanager 的场景）
        
        若 hw_profile=True，会在返回的时间戳上关联硬件快照，end_span 时会自动计算差量。
        """
        ts = self._now_us()
        tid = threading.get_ident()
        hw_start = None
        if hw_profile:
            hw_start = self._hw_snapshot()
            self._span_hw[ts] = hw_start
        self._add_event(name, "B", ts, tid=tid, cat=category, args=args if args else None)
        return ts
    
    def end_span(self, name: str, start_ts: int) -> Optional[Dict[str, Any]]:
        """手动结束一个 span（与 start_span 的 B 事件配对为 E 事件）。
        
        若 start_span 时启用了 hw_profile，返回硬件差量 dict；否则返回 None。
        """
        ts_end = self._now_us()
        tid = threading.get_ident()
        hw_delta = None
        hw_start = self._span_hw.pop(start_ts, None)
        if hw_start is not None:
            hw_after = self._hw_snapshot()
            hw_delta = self._hw_delta(hw_start, hw_after)
        args = {}
        if hw_delta:
            args['hw'] = hw_delta
        self._add_event(name, "E", ts_end, tid=tid, args=args if args else None)
        return hw_delta
    
    def event(self, name: str, category: str = "", **args):
        """记录一个瞬时事件（无 duration）"""
        ts = self._now_us()
        tid = threading.get_ident()
        self._add_event(name, "i", ts, tid=tid, cat=category, args=args if args else None)
    
    def save(self, output_path: Optional[str] = None) -> str:
        """保存 trace 文件，返回文件路径"""
        path = Path(output_path) if output_path else self.output_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._events, f, indent=2, ensure_ascii=False)
        return str(path.resolve())
    
    def track_tool_start(self, tool_name: str) -> int:
        """工具开始执行时调用。返回当前并发数（含本次）。

        返回值 >= 2 表示此时有其他工具同时运行，eBPF 差量可能受污染。
        """
        with self._concurrent_lock:
            self._concurrent_active += 1
            return self._concurrent_active

    def track_tool_end(self, tool_name: str) -> int:
        """工具执行结束时调用。返回剩余并发数（本次已从计数中移除）。

        返回值 > 0 表示仍有其他工具在运行，说明它们的窗口与本工具有重叠。
        """
        with self._concurrent_lock:
            self._concurrent_active = max(0, self._concurrent_active - 1)
            return self._concurrent_active

    def accumulate_tool_hw(
        self,
        tool_name: str,
        hw_delta: Dict[str, Any],
        concurrent_count: int = 1,
        had_error: bool = False,
    ) -> None:
        """累积工具硬件开销到统计中。"""
        record = {
            **hw_delta,
            'concurrent_count': concurrent_count,  # 实际并发数（>1 时 eBPF 指标可能受污染）
            'had_error': had_error,
        }
        with self._lock:
            if tool_name not in self._tool_hw_stats:
                self._tool_hw_stats[tool_name] = []
            self._tool_hw_stats[tool_name].append(record)

    @staticmethod
    def _percentile(sorted_vals: List[float], pct: float) -> float:
        """Nearest-rank 百分位数（输入必须已排序）。"""
        if not sorted_vals:
            return 0.0
        idx = max(0, int(len(sorted_vals) * pct / 100) - 1)
        return round(sorted_vals[min(idx, len(sorted_vals) - 1)], 2)

    def get_tool_hw_report(self) -> Dict[str, Any]:
        """获取各工具的累计硬件开销报告。
        CPU 始终使用 thread_cpu_ms（线程级，并发安全）。
        文件 I/O 字节始终使用 eBPF 线程级数据（io_bytes_source='thread_ebpf'）。
        """
        with self._lock:
            stats_copy = {k: list(v) for k, v in self._tool_hw_stats.items()}

        report: Dict[str, Any] = {}
        for tool_name, deltas in stats_copy.items():
            n = len(deltas)
            if n == 0:
                continue

            # --- 线程级 CPU（CLOCK_THREAD_CPUTIME_ID，并发安全）---
            # 始终使用 thread_cpu_ms，不降级为进程级
            thread_vals = [d['thread_cpu_ms'] for d in deltas if d.get('thread_cpu_ms', -1) >= 0]
            if thread_vals:
                cpu_sorted = sorted(thread_vals)
                total_cpu  = sum(thread_vals)
            else:
                # 极少数平台不支持线程级 CPU，用空列表占位
                cpu_sorted = []
                total_cpu  = 0.0

            # 进程级 CPU（并发时可能混入其他线程，仅供参考）
            total_proc_cpu = sum(d['cpu_total_ms'] for d in deltas)

            # --- 基础汇总 ---
            total_wall  = sum(d['wall_ms']          for d in deltas)
            total_io_r  = sum(d['io_read_ops']      for d in deltas)
            total_io_w  = sum(d['io_write_ops']     for d in deltas)
            total_vms = 0  # 已移除虚存指标
            total_ctx   = sum(d['ctx_total']        for d in deltas)
            total_pfmin = sum(d['page_faults_min']  for d in deltas)
            total_pfmaj = sum(d['page_faults_maj']  for d in deltas)
            total_net_sent = sum(d.get('net_sent_bytes', 0) for d in deltas)
            total_net_recv = sum(d.get('net_recv_bytes', 0) for d in deltas)
            # 网络 I/O 字节来源标注聚合
            net_sources = {d.get('net_bytes_source', 'process_psutil') for d in deltas}
            if net_sources == {'thread_ebpf'}:
                net_bytes_src = 'thread_ebpf'
            elif 'thread_ebpf' in net_sources:
                net_bytes_src = 'mixed'
            else:
                net_bytes_src = 'process_psutil'
            # eBPF 线程级文件 I/O 字节（-1 表示不可用，应跳过不加入累计）
            valid_io_r = [d['io_read_bytes']  for d in deltas if d.get('io_read_bytes',  -1) >= 0]
            valid_io_w = [d['io_write_bytes'] for d in deltas if d.get('io_write_bytes', -1) >= 0]
            total_read_bytes  = sum(valid_io_r)
            total_write_bytes = sum(valid_io_w)
            # I/O 字节来源标注
            io_sources = {d.get('io_bytes_source', 'unavailable') for d in deltas}
            if io_sources == {'thread_ebpf'}:
                io_bytes_src = 'thread_ebpf'
            elif 'thread_ebpf' in io_sources:
                io_bytes_src = 'mixed'
            else:
                io_bytes_src = 'unavailable'

            all_files_accessed: set = set()
            for _d in deltas:
                all_files_accessed.update(_d.get('files_accessed', []))
            # files_accessed 来源表注聚合
            fa_sources = {_d.get('files_accessed_source', 'process_psutil') for _d in deltas}
            if fa_sources == {'thread_ebpf'}:
                fa_src = 'thread_ebpf'
            elif 'thread_ebpf' in fa_sources:
                fa_src = 'mixed'
            else:
                fa_src = 'process_psutil'
            errors = sum(1 for d in deltas if d.get('had_error', False))
            # 并发污染次数：执行期间 eBPF 差量窗口与其他工具重叠的调用次数
            concurrent_calls = sum(1 for d in deltas if d.get('ebpf_contaminated', False))

            # 已排序列表（用于百分位 / min / max）
            wall_sorted = sorted(d['wall_ms']    for d in deltas)
            peak_concurrent = max((d.get('concurrent_count', 1) for d in deltas), default=1)
            avg_concurrent  = round(sum(d.get('concurrent_count', 1) for d in deltas) / n, 1) if n > 0 else 1.0

            report[tool_name] = {
                # 调用次数
                'calls':              n,
                'errors':             errors,
                'error_rate_pct':     round(errors / n * 100, 1),
                # 并发污染次数（eBPF 数据不可信的调用）
                'concurrent_calls':   concurrent_calls,
                # 小样本警告标记
                'small_sample':       n < 10,
                # === CPU 线程级（CLOCK_THREAD_CPUTIME_ID）===
                'total_cpu_ms':       round(total_cpu, 2),
                'avg_cpu_ms':         round(total_cpu / n, 2) if n > 0 else 0,
                'min_cpu_ms':         round(cpu_sorted[0], 2)  if cpu_sorted else 0,
                'max_cpu_ms':         round(cpu_sorted[-1], 2) if cpu_sorted else 0,
                'p50_cpu_ms':         self._percentile(cpu_sorted, 50),
                'p95_cpu_ms':         self._percentile(cpu_sorted, 95),
                # 进程级 CPU（并发时可能混入其他线程，仅供参考）
                'proc_cpu_total_ms':  round(total_proc_cpu, 2),
                # 墙上时钟 (ms)
                'total_wall_ms':      round(total_wall, 2),
                'avg_wall_ms':        round(total_wall / n, 2),
                'min_wall_ms':        round(wall_sorted[0], 2),
                'max_wall_ms':        round(wall_sorted[-1], 2),
                'p50_wall_ms':        self._percentile(wall_sorted, 50),
                'p95_wall_ms':        self._percentile(wall_sorted, 95),
                'p99_wall_ms':        self._percentile(wall_sorted, 99),
                # CPU 占比
                'cpu_pct':            round(total_cpu / total_wall * 100, 1) if total_wall > 0 else 0,
                # IO 块操作次数（线程级）
                'total_io_read':      total_io_r,
                'total_io_write':     total_io_w,
                'avg_io_read':        round(total_io_r / n, 1),
                'avg_io_write':       round(total_io_w / n, 1),
                # 内存指标已移除（RSS / swap / peak_rss）
                'total_vms_delta_kb': total_vms,
                # 缺页（线程级）
                'total_page_faults_min': total_pfmin,
                'total_page_faults_maj': total_pfmaj,
                # 上下文切换（线程级）
                'total_ctx_switches': total_ctx,
                'avg_ctx_switches':   round(total_ctx / n, 1),
                # 并发
                'peak_concurrent':    peak_concurrent,
                'avg_concurrent':     avg_concurrent,
                # 网络 I/O（KB）
                'total_net_sent_kb':  round(total_net_sent / 1024, 1),
                'total_net_recv_kb':  round(total_net_recv / 1024, 1),
                'avg_net_sent_kb':    round(total_net_sent / 1024 / n, 1) if n > 0 else 0,
                'avg_net_recv_kb':    round(total_net_recv / 1024 / n, 1) if n > 0 else 0,
                'net_bytes_source':   net_bytes_src,
                # 文件 I/O 字节数 eBPF 线程级 (KB)
                'total_io_read_kb':   round(total_read_bytes  / 1024, 1),
                'total_io_write_kb':  round(total_write_bytes / 1024, 1),
                'avg_io_read_kb':     round(total_read_bytes  / 1024 / n, 1),
                'avg_io_write_kb':    round(total_write_bytes / 1024 / n, 1),
                'io_bytes_source':    io_bytes_src,
                # 所有调用中访问过的文件（去重聚合）
                'files_accessed':     sorted(all_files_accessed),
                'files_accessed_source': fa_src,
            }
        return report

    def get_concurrent_stats(self) -> Dict[str, Any]:
        """返回该会话的并发执行统计（已移除，返回固定值）。"""
        return {
            'current_active':   0,
            'peak_concurrent':  0,
            'active_tools':     {},
        }

    def cleanup(self) -> None:
        """释放 eBPF 等持有的系统资源。会话结束或 reset 时调用。"""
        try:
            self._ebpf.cleanup()
        except Exception:
            pass
    
    def stats(self) -> Dict[str, Any]:
        """返回当前 trace 的统计摘要"""
        with self._lock:
            total = len(self._events)
            categories = {}
            total_dur = 0
            for ev in self._events:
                if ev["ph"] == "X" and "dur" in ev:
                    total_dur += ev["dur"]
                    cat = ev.get("cat", "uncategorized")
                    if cat not in categories:
                        categories[cat] = {"count": 0, "total_us": 0}
                    categories[cat]["count"] += 1
                    categories[cat]["total_us"] += ev["dur"]
            
            return {
                "total_events": total,
                "total_duration_ms": total_dur / 1000,
                "categories": {
                    cat: {
                        "count": v["count"],
                        "total_ms": v["total_us"] / 1000,
                        "avg_ms": (v["total_us"] / v["count"]) / 1000 if v["count"] else 0,
                    }
                    for cat, v in sorted(categories.items(), key=lambda x: x[1]["total_us"], reverse=True)
                }
            }


# 全局单例 tracer
_tracer: Optional[Tracer] = None

def get_tracer(output_path: str = "trace.json") -> Tracer:
    """获取全局 tracer 单例"""
    global _tracer
    if _tracer is None:
        _tracer = Tracer(output_path=output_path)
    return _tracer

def reset_tracer():
    """重置 tracer（用于新会话），同时释放 eBPF 等系统资源。"""
    global _tracer
    if _tracer is not None:
        _tracer.cleanup()
    _tracer = None
