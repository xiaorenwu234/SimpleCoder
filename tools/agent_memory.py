"""
跨会话记忆系统 - 持久化存储用户偏好、项目上下文和交互历史
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from collections import defaultdict


class AgentMemory:
    """Agent记忆管理器"""
    
    def __init__(self, db_path: str = "agent_memory.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 用户偏好表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # 项目上下文表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS project_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_path TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_path, key)
                )
            ''')
            
            # 对话历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,  -- user, assistant, system
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata TEXT  -- JSON
                )
            ''')
            
            # 学习到的知识表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS learned_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    usage_count INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_used TEXT NOT NULL,
                    UNIQUE(category, key)
                )
            ''')
            
            # 工具使用统计
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tool_usage_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    avg_execution_time REAL DEFAULT 0.0,
                    last_used TEXT,
                    UNIQUE(tool_name)
                )
            ''')
            
            conn.commit()
    
    # ========== 用户偏好 ==========
    
    def set_preference(self, key: str, value: Any):
        """设置用户偏好"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_preferences (key, value, updated_at)
                VALUES (?, ?, ?)
            ''', (key, json.dumps(value), datetime.now().isoformat()))
            conn.commit()
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """获取用户偏好"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM user_preferences WHERE key = ?', (key,))
            row = cursor.fetchone()
            
            if row:
                return json.loads(row[0])
            return default
    
    def get_all_preferences(self) -> Dict[str, Any]:
        """获取所有用户偏好"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM user_preferences')
            
            return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
    
    # ========== 项目上下文 ==========
    
    def set_project_context(self, project_path: str, key: str, value: Any):
        """设置项目上下文"""
        abs_path = os.path.abspath(project_path)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO project_context (project_path, key, value, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (abs_path, key, json.dumps(value), datetime.now().isoformat()))
            conn.commit()
    
    def get_project_context(self, project_path: str, key: str, default: Any = None) -> Any:
        """获取项目上下文"""
        abs_path = os.path.abspath(project_path)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT value FROM project_context WHERE project_path = ? AND key = ?',
                (abs_path, key)
            )
            row = cursor.fetchone()
            
            if row:
                return json.loads(row[0])
            return default
    
    def get_full_project_context(self, project_path: str) -> Dict[str, Any]:
        """获取完整的项目上下文"""
        abs_path = os.path.abspath(project_path)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT key, value FROM project_context WHERE project_path = ?',
                (abs_path,)
            )
            
            return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
    
    # ========== 对话历史 ==========
    
    @staticmethod
    def _sanitize_text(text: str) -> str:
        """清理文本中的非UTF-8字符（如surrogate字符），防止数据库写入错误"""
        if text is None:
            return text
        return text.encode('utf-8', errors='replace').decode('utf-8')

    def add_conversation(self, session_id: str, role: str, content: str, metadata: Dict = None):
        """添加对话记录"""
        content = self._sanitize_text(content)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO conversation_history (session_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                session_id,
                role,
                content,
                datetime.now().isoformat(),
                json.dumps(metadata) if metadata else None
            ))
            conn.commit()
    
    def get_conversation_history(self, session_id: str, limit: int = 50) -> List[Dict]:
        """获取对话历史"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content, timestamp, metadata
                FROM conversation_history
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ''', (session_id, limit))
            
            return [
                {
                    'role': row[0],
                    'content': row[1],
                    'timestamp': row[2],
                    'metadata': json.loads(row[3]) if row[3] else {}
                }
                for row in cursor.fetchall()
            ][::-1]  # 反转以获得正序
    
    def get_recent_context(self, session_id: str, max_tokens: int = 4000) -> str:
        """获取最近的对话上下文（用于prompt）"""
        history = self.get_conversation_history(session_id, limit=20)
        
        context_parts = []
        total_tokens = 0
        
        for msg in reversed(history):
            msg_text = f"{msg['role']}: {msg['content']}"
            msg_tokens = len(msg_text) // 4  # 粗略估算
            
            if total_tokens + msg_tokens > max_tokens:
                break
            
            context_parts.append(msg_text)
            total_tokens += msg_tokens
        
        return '\n'.join(reversed(context_parts))
    
    # ========== 学习到的知识 ==========
    
    def add_knowledge(self, category: str, key: str, value: Any, confidence: float = 1.0):
        """添加学习到的知识"""
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO learned_knowledge 
                (category, key, value, confidence, usage_count, created_at, last_used)
                VALUES (?, ?, ?, ?, 
                    COALESCE((SELECT usage_count FROM learned_knowledge WHERE category = ? AND key = ?), 0) + 1,
                    COALESCE((SELECT created_at FROM learned_knowledge WHERE category = ? AND key = ?), ?),
                    ?)
            ''', (category, key, json.dumps(value), confidence,
                  category, key, category, key, now, now))
            conn.commit()
    
    def get_knowledge(self, category: str, key: str = None) -> Dict[str, Any]:
        """获取知识"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if key:
                cursor.execute('''
                    SELECT key, value, confidence, usage_count
                    FROM learned_knowledge
                    WHERE category = ? AND key = ?
                ''', (category, key))
            else:
                cursor.execute('''
                    SELECT key, value, confidence, usage_count
                    FROM learned_knowledge
                    WHERE category = ?
                    ORDER BY usage_count DESC
                ''', (category,))
            
            return {
                row[0]: {
                    'value': json.loads(row[1]),
                    'confidence': row[2],
                    'usage_count': row[3]
                }
                for row in cursor.fetchall()
            }
    
    # ========== 工具使用统计 ==========
    
    def record_tool_usage(self, tool_name: str, success: bool, execution_time: float):
        """记录工具使用"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tool_usage_stats (tool_name, success_count, failure_count, avg_execution_time, last_used)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    success_count = success_count + ?,
                    failure_count = failure_count + ?,
                    avg_execution_time = (avg_execution_time + ?) / 2,
                    last_used = ?
            ''', (
                tool_name,
                1 if success else 0,
                0 if success else 1,
                execution_time,
                datetime.now().isoformat(),
                1 if success else 0,
                0 if success else 1,
                execution_time,
                datetime.now().isoformat()
            ))
            conn.commit()
    
    def get_tool_stats(self) -> Dict[str, Dict]:
        """获取工具使用统计"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tool_name, success_count, failure_count, avg_execution_time, last_used
                FROM tool_usage_stats
                ORDER BY (success_count + failure_count) DESC
            ''')
            
            return {
                row[0]: {
                    'success_count': row[1],
                    'failure_count': row[2],
                    'avg_execution_time': row[3],
                    'last_used': row[4]
                }
                for row in cursor.fetchall()
            }
    
    # ========== 清理和维护 ==========
    
    def cleanup_old_data(self, days: int = 30):
        """清理旧数据"""
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 清理旧对话
            cursor.execute('''
                DELETE FROM conversation_history WHERE timestamp < ?
            ''', (cutoff_date,))
            
            # 清理不常用的知识
            cursor.execute('''
                DELETE FROM learned_knowledge 
                WHERE last_used < ? AND usage_count < 3
            ''', (cutoff_date,))
            
            conn.commit()
    
    def export_memory(self, output_path: str):
        """导出记忆数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            data = {
                'preferences': {},
                'project_context': {},
                'knowledge': {},
                'tool_stats': {},
                'exported_at': datetime.now().isoformat()
            }
            
            # 导出偏好
            cursor.execute('SELECT key, value FROM user_preferences')
            data['preferences'] = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
            
            # 导出项目上下文
            cursor.execute('SELECT project_path, key, value FROM project_context')
            for row in cursor.fetchall():
                if row[0] not in data['project_context']:
                    data['project_context'][row[0]] = {}
                data['project_context'][row[0]][row[1]] = json.loads(row[2])
            
            # 导出知识
            cursor.execute('SELECT category, key, value FROM learned_knowledge')
            for row in cursor.fetchall():
                if row[0] not in data['knowledge']:
                    data['knowledge'][row[0]] = {}
                data['knowledge'][row[0]][row[1]] = json.loads(row[2])
            
            # 写入文件
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
