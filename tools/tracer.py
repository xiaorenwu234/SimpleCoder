"""
轻量级 Trace 追踪器 — 输出 Chrome Trace Event 格式（JSON）

兼容查看工具:
  - chrome://tracing          (Chrome 浏览器地址栏输入)
  - https://ui.perfetto.dev/  (拖入 JSON 文件)
  - https://www.speedscope.app/ (火焰图视图)
"""
import time
import json
import threading
import os
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Dict, Any
import asyncio


class Tracer:
    """Chrome Trace Event 格式的 span 追踪器，线程安全 + async 安全"""
    
    def __init__(self, output_path: str = "trace.json"):
        self._events: list = []
        self._lock = threading.Lock()
        self._start_time: float = time.time()
        self.output_path = Path(output_path)
        
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
    
    @contextmanager
    def span(self, name: str, category: str = "", **args):
        """同步 span，用 contextmanager 包裹代码块
        
        用法:
            with tracer.span("my_operation", category="db", key="val"):
                do_something()
        """
        tid = threading.get_ident()
        ts_start = self._now_us()
        try:
            yield
        finally:
            dur = self._now_us() - ts_start
            self._add_event(name, "X", ts_start, tid=tid, cat=category, dur=dur, args=args if args else None)
    
    @asynccontextmanager
    async def async_span(self, name: str, category: str = "", **args):
        """异步 span —— 支持在 async with 中使用
        
        用法:
            async with tracer.async_span("fetch", category="http"):
                await fetch_data()
        """
        tid = threading.get_ident()
        ts_start = self._now_us()
        try:
            yield
        finally:
            dur = self._now_us() - ts_start
            self._add_event(name, "X", ts_start, tid=tid, cat=category, dur=dur, args=args if args else None)
    
    def start_span(self, name: str, category: str = "", **args) -> int:
        """手动开始一个 span，返回开始时间戳。配合 end_span 使用（用于无法用 contextmanager 的场景）"""
        ts = self._now_us()
        tid = threading.get_ident()
        self._add_event(name, "B", ts, tid=tid, cat=category, args=args if args else None)
        return ts
    
    def end_span(self, name: str, start_ts: int) -> None:
        """手动结束一个 span（与 start_span 的 B 事件配对为 E 事件）"""
        ts_end = self._now_us()
        tid = threading.get_ident()
        self._add_event(name, "E", ts_end, tid=tid)
    
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
