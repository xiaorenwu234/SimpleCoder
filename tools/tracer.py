"""
轻量级 Trace 追踪器 — 输出 Chrome Trace Event 格式（JSON）

兼容查看工具:
  - chrome://tracing          (Chrome 浏览器地址栏输入)
  - https://ui.perfetto.dev/  (拖入 JSON 文件)
  - https://www.speedscope.app/ (火焰图视图)

硬件监控维度（每次工具调用均采集差量）:
  执行时间: 墙上时钟 wall_ms
  CPU:      用户态 cpu_user_ms / 系统态 cpu_sys_ms / 合计 cpu_total_ms / 瞬时占比 cpu_pct
            线程级 thread_cpu_ms (并发安全，首选指标)
  内存:     RSS增量 mem_delta_kb / 当前RSS mem_rss_kb / 虚拟内存 mem_vms_kb / 峰值RSS peak_rss_kb / swap增量 mem_swap_delta_kb
  IO:       块读 io_read_ops / 块写 io_write_ops
            网络 net_sent_bytes / net_recv_bytes (进程级)
  缺页:     次缺页 page_faults_min / 主缺页 page_faults_maj
  上下文:   自愿切换 ctx_vol / 非自愿 ctx_invol / 合计 ctx_total
  线程:     执行时线程数 thread_count / 线程变化量 thread_delta
  文件描述符: 执行时FD数 open_fds / 变化量 open_fds_delta
  并发:     执行时并发工具数 concurrent_count
"""
import sys
import time
import json
import threading
import os
import resource
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Dict, Any, List
import asyncio


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
        # 并发追踪: 当前活跃工具数 + 各工具活跃数 + 峰值
        self._active_tool_count: int = 0
        self._active_tools: Dict[str, int] = {}   # tool_name -> active count
        self._peak_concurrent: int = 0            # 全局峰值并发
        self._concurrent_lock = threading.Lock()  # 独立锁避免与 _lock 嵌套
        # 平台检测（macOS ru_maxrss 单位为字节，Linux 为 KB）
        self._is_macos: bool = sys.platform == 'darwin'
        
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
        """采集当前进程硬件资源快照（macOS / Linux 兼容）

        CPU 采集策略说明：
          - thread_cpu_ns : time.CLOCK_THREAD_CPUTIME_ID — 「本线程」精硬 CPU 时间，
                            并发场景下不受其他工具线程干扰，为首选指标。
          - cpu_user/sys  : resource.getrusage(RUSAGE_SELF) — 「进程」级累计值，
                            并发时包含所有工具线程的总消耗，可用于说明进程整体负荷。
          - cpu_pct       : psutil.cpu_percent(None) — 非阻塞快照，只反映结束时刻点。

        resource 模块字段（POSIX，极简容器可能缺失，统一 getattr 兜底）:
            cpu_user:        用户态 CPU 时间 (秒)
            cpu_sys:         系统态 CPU 时间 (秒)
            io_in:           块输入操作次数
            io_out:          块输出操作次数  (macOS=ru_oublock, Linux=ru_outblock)
            ctx_vol:         自愿上下文切换次数
            ctx_invol:       非自愿上下文切换次数
            page_faults_min: 次缺页 (ru_minflt)
            page_faults_maj: 主缺页 (ru_majflt)
            max_rss_raw:     峰值 RSS (macOS=字节, Linux=KB)

        psutil 字段（不可用时降级为 0）:
            mem_rss:    当前 RSS 内存 (字节)
            mem_vms:    虚拟内存大小 (字节)
            mem_swap:   swap 已用量 (字节)
            thread_count: 线程数
            open_fds:   打开的文件描述符数
            cpu_pct:    瞬时 CPU 占用率 (%，非阻塞)
        """
        usage = resource.getrusage(resource.RUSAGE_SELF)

        # --- psutil 首次探测 ---
        if self._psutil_available is None:
            try:
                import psutil
                psutil.Process(os.getpid()).memory_info()
                self._psutil_available = True
            except Exception:
                self._psutil_available = False

        # --- 线程级 CPU 时间（核心指标，并发安全）---
        # CLOCK_THREAD_CPUTIME_ID 只统计本线程消耗的 CPU 时间，不受并发工具干扰
        try:
            thread_cpu_ns = time.clock_gettime_ns(time.CLOCK_THREAD_CPUTIME_ID)
        except (AttributeError, OSError):
            # 少数平台不支持时降级为 -1（后续差量为 -1 表示不可用）
            thread_cpu_ns = -1

        # --- resource 模块指标 ---
        # macOS: ru_oublock（一个 t）, Linux: ru_outblock（两个 t）
        io_in  = getattr(usage, 'ru_inblock', 0)
        io_out = getattr(usage, 'ru_oublock', getattr(usage, 'ru_outblock', 0))

        snap: Dict[str, Any] = {
            'thread_cpu_ns':   thread_cpu_ns,   # 线程级精硬 CPU (纳秒)
            'cpu_user':        usage.ru_utime,  # 进程级用户态 CPU (秒)
            'cpu_sys':         usage.ru_stime,  # 进程级系统态 CPU (秒)
            'io_in':           io_in,
            'io_out':          io_out,
            'ctx_vol':         getattr(usage, 'ru_nvcsw',   0),
            'ctx_invol':       getattr(usage, 'ru_nivcsw',  0),
            'page_faults_min': getattr(usage, 'ru_minflt',  0),
            'page_faults_maj': getattr(usage, 'ru_majflt',  0),
            'max_rss_raw':     getattr(usage, 'ru_maxrss',  0),
            'wall_ts':         time.perf_counter(),
            # psutil 默认值
            'mem_rss':         0,
            'mem_vms':         0,
            'mem_swap':        0,
            'thread_count':    0,
            'open_fds':        0,
            'cpu_pct':         0.0,
            # 网络 I/O 默认值
            'net_bytes_sent':  0,
            'net_bytes_recv':  0,
        }

        # --- psutil 采集 ---
        if self._psutil_available:
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                mem = proc.memory_info()
                snap['mem_rss']      = mem.rss
                snap['mem_vms']      = mem.vms
                # cpu_percent(interval=None) 返回自上次调用以来的 CPU 占比（非阻塞）
                snap['cpu_pct']      = proc.cpu_percent(interval=None)
                snap['thread_count'] = proc.num_threads()
                try:
                    snap['open_fds'] = proc.num_fds()   # Unix 专属
                except (AttributeError, psutil.AccessDenied):
                    pass
                try:
                    snap['mem_swap'] = psutil.swap_memory().used
                except Exception:
                    pass
                # 网络 I/O 统计（进程级，包含所有线程）
                try:
                    net_counters = psutil.net_io_counters()
                    if net_counters:
                        snap['net_bytes_sent'] = net_counters.bytes_sent
                        snap['net_bytes_recv'] = net_counters.bytes_recv
                except Exception:
                    pass
            except Exception:
                pass

        return snap
    
    @staticmethod
    def _hw_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        """计算两次硬件快照之间的资源消耗差量。

        CPU 指标说明:
            thread_cpu_ms  : 「本线程」消耗的精硬 CPU，并发安全。-1 表示平台不支持。
            cpu_user_ms    : 进程级用户态 CPU 差量（并发时含其他工具线程的贡献）
            cpu_sys_ms     : 进程级系统态 CPU 差量
            cpu_total_ms   : cpu_user_ms + cpu_sys_ms
            cpu_pct_end    : 结束时刻 psutil 的进程 CPU 占比快照

        其他字段:
            wall_ms:            墙上时钟耗时 (ms)
            io_read_ops:        块读操作次数
            io_write_ops:       块写操作次数
            ctx_vol:            自愿上下文切换次数
            ctx_invol:          非自愿上下文切换次数
            ctx_total:          上下文切换总次数
            page_faults_min:    次缺页次数
            page_faults_maj:    主缺页次数
            mem_delta_kb:       RSS 变化量 (KB)
            mem_rss_kb:         执行结束时 RSS (KB)
            mem_vms_kb:         执行结束时虚拟内存 (KB)
            mem_vms_delta_kb:   虚拟内存变化量 (KB)
            mem_swap_delta_kb:  swap 变化量 (KB)
            peak_rss_kb:        进程历史峰值 RSS (KB)
            thread_count:       执行结束时线程数
            thread_delta:       线程数变化量
            open_fds:           执行结束时 FD 数
            open_fds_delta:     FD 数变堖量
        """
        # macOS ru_maxrss 单位为字节，Linux 为 KB
        is_macos = sys.platform == 'darwin'
        max_rss_after_kb = (
            after['max_rss_raw'] // 1024 if is_macos else after['max_rss_raw']
        )

        ctx_vol   = after['ctx_vol']   - before['ctx_vol']
        ctx_invol = after['ctx_invol'] - before['ctx_invol']

        # 线程级 CPU 差量：两端均可用时才计算，否则保持 -1
        b_ns = before.get('thread_cpu_ns', -1)
        a_ns = after.get('thread_cpu_ns', -1)
        thread_cpu_ms = (a_ns - b_ns) / 1_000_000 if (b_ns >= 0 and a_ns >= 0) else -1.0

        return {
            # 线程级精硬 CPU（首选，并发安全）
            'thread_cpu_ms':     thread_cpu_ms,
            # 墙上时钟
            'wall_ms':           (after['wall_ts'] - before['wall_ts']) * 1000,
            # 进程级 CPU（并发时混入其他线程，仅供参考）
            'cpu_user_ms':       (after['cpu_user'] - before['cpu_user']) * 1000,
            'cpu_sys_ms':        (after['cpu_sys']  - before['cpu_sys'])  * 1000,
            'cpu_total_ms':      ((after['cpu_user'] + after['cpu_sys'])
                                  - (before['cpu_user'] + before['cpu_sys'])) * 1000,
            'cpu_pct_end':       after['cpu_pct'],
            'io_read_ops':       after['io_in']  - before['io_in'],
            'io_write_ops':      after['io_out'] - before['io_out'],
            'ctx_vol':           ctx_vol,
            'ctx_invol':         ctx_invol,
            'ctx_total':         ctx_vol + ctx_invol,
            'page_faults_min':   after['page_faults_min'] - before['page_faults_min'],
            'page_faults_maj':   after['page_faults_maj'] - before['page_faults_maj'],
            'mem_delta_kb':      (after['mem_rss'] - before['mem_rss']) // 1024,
            'mem_rss_kb':        after['mem_rss'] // 1024,
            'mem_vms_kb':        after['mem_vms'] // 1024,
            'mem_vms_delta_kb':  (after['mem_vms'] - before['mem_vms']) // 1024,
            'mem_swap_delta_kb': (after['mem_swap'] - before['mem_swap']) // 1024,
            'peak_rss_kb':       max_rss_after_kb,
            'thread_count':      after['thread_count'],
            'thread_delta':      after['thread_count'] - before['thread_count'],
            'open_fds':          after['open_fds'],
            'open_fds_delta':    after['open_fds'] - before['open_fds'],
            # 网络 I/O 差量（字节）
            'net_sent_bytes':    after['net_bytes_sent'] - before['net_bytes_sent'],
            'net_recv_bytes':    after['net_bytes_recv'] - before['net_bytes_recv'],
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
        """工具开始执行时调用，线程安全。返回此刻全局并发数。"""
        with self._concurrent_lock:
            self._active_tool_count += 1
            self._active_tools[tool_name] = self._active_tools.get(tool_name, 0) + 1
            if self._active_tool_count > self._peak_concurrent:
                self._peak_concurrent = self._active_tool_count
            return self._active_tool_count

    def track_tool_end(self, tool_name: str) -> int:
        """工具执行结束时调用，线程安全。返回剰余全局并发数。"""
        with self._concurrent_lock:
            self._active_tool_count = max(0, self._active_tool_count - 1)
            cnt = self._active_tools.get(tool_name, 1)
            if cnt <= 1:
                self._active_tools.pop(tool_name, None)
            else:
                self._active_tools[tool_name] = cnt - 1
            return self._active_tool_count

    def accumulate_tool_hw(
        self,
        tool_name: str,
        hw_delta: Dict[str, Any],
        concurrent_count: int = 1,
        had_error: bool = False,
    ) -> None:
        """累积工具硬件开销到统计中，同时记录并发数和错误状态。"""
        record = {
            **hw_delta,
            'concurrent_count': concurrent_count,
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
        """获取各工具的累计硬件开销报告，包含百分位数、峰值、并发等丰富统计。
        CPU 首选 thread_cpu_ms（线程级精硬，并发安全）；平台不支持时降级为 cpu_total_ms（进程级）。
        """
        with self._lock:
            stats_copy = {k: list(v) for k, v in self._tool_hw_stats.items()}

        report: Dict[str, Any] = {}
        for tool_name, deltas in stats_copy.items():
            n = len(deltas)
            if n == 0:
                continue

            # --- 线程级 CPU（并发安全）---
            thread_vals = [d['thread_cpu_ms'] for d in deltas if d.get('thread_cpu_ms', -1) >= 0]
            thread_available = len(thread_vals) == n  # 全部有效才启用

            # --- 进程级 CPU（并发时可能混入其他线程，常规参考）---
            total_proc_cpu = sum(d['cpu_total_ms'] for d in deltas)

            # 已排序列表
            if thread_available:
                cpu_sorted = sorted(thread_vals)
                total_cpu  = sum(thread_vals)
            else:
                cpu_sorted = sorted(d['cpu_total_ms'] for d in deltas)
                total_cpu  = total_proc_cpu

            # 基础汇总
            total_wall  = sum(d['wall_ms']        for d in deltas)
            total_io_r  = sum(d['io_read_ops']    for d in deltas)
            total_io_w  = sum(d['io_write_ops']   for d in deltas)
            total_mem   = sum(d['mem_delta_kb']   for d in deltas)
            total_vms   = sum(d['mem_vms_delta_kb'] for d in deltas)
            total_swap  = sum(d['mem_swap_delta_kb'] for d in deltas)
            total_ctx   = sum(d['ctx_total']      for d in deltas)
            total_pfmin = sum(d['page_faults_min'] for d in deltas)
            total_pfmaj = sum(d['page_faults_maj'] for d in deltas)
            total_net_sent = sum(d.get('net_sent_bytes', 0) for d in deltas)
            total_net_recv = sum(d.get('net_recv_bytes', 0) for d in deltas)
            errors      = sum(1 for d in deltas if d.get('had_error', False))

            # 已排序列表（用于百分位 / min / max）
            wall_sorted = sorted(d['wall_ms']    for d in deltas)
            rss_sorted  = sorted(d['mem_rss_kb'] for d in deltas)

            # 并发统计
            concurrent_vals = [d.get('concurrent_count', 1) for d in deltas]
            peak_concurrent = max(concurrent_vals)
            avg_concurrent  = round(sum(concurrent_vals) / n, 2)

            report[tool_name] = {
                # 调用次数
                'calls':              n,
                'errors':             errors,
                'error_rate_pct':     round(errors / n * 100, 1),
                # CPU 来源标注
                'cpu_source':         'thread' if thread_available else 'process',
                # 小样本警告标记
                'small_sample':       n < 10,
                # CPU (ms) — 首选线程级，降级时为进程级
                'total_cpu_ms':       round(total_cpu, 2),
                'avg_cpu_ms':         round(total_cpu / n, 2),
                'min_cpu_ms':         round(cpu_sorted[0], 2),
                'max_cpu_ms':         round(cpu_sorted[-1], 2),
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
                # IO
                'total_io_read':      total_io_r,
                'total_io_write':     total_io_w,
                'avg_io_read':        round(total_io_r / n, 1),
                'avg_io_write':       round(total_io_w / n, 1),
                # 内存 (KB)
                'total_mem_delta_kb': total_mem,
                'avg_mem_delta_kb':   round(total_mem / n, 1),
                'peak_mem_rss_kb':    rss_sorted[-1] if rss_sorted else 0,
                'total_vms_delta_kb': total_vms,
                'total_swap_delta_kb': total_swap,
                # 缺页
                'total_page_faults_min': total_pfmin,
                'total_page_faults_maj': total_pfmaj,
                # 上下文切换
                'total_ctx_switches': total_ctx,
                'avg_ctx_switches':   round(total_ctx / n, 1),
                # 并发
                'peak_concurrent':    peak_concurrent,
                'avg_concurrent':     avg_concurrent,
                # 网络 I/O (字节)
                'total_net_sent_kb':  round(total_net_sent / 1024, 1),
                'total_net_recv_kb':  round(total_net_recv / 1024, 1),
                'avg_net_sent_kb':    round(total_net_sent / 1024 / n, 1) if n > 0 else 0,
                'avg_net_recv_kb':    round(total_net_recv / 1024 / n, 1) if n > 0 else 0,
            }
        return report

    def get_concurrent_stats(self) -> Dict[str, Any]:
        """返回该会话的并发执行统计。"""
        with self._concurrent_lock:
            return {
                'current_active':   self._active_tool_count,
                'peak_concurrent':  self._peak_concurrent,
                'active_tools':     dict(self._active_tools),
            }
    
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
    """重置 tracer（用于新会话）"""
    global _tracer
    _tracer = None
