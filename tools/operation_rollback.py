"""
操作回滚系统 - 提供文件操作的版本控制和回滚能力
"""
import os
import shutil
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path


class OperationRollback:
    """操作回滚管理器"""
    
    def __init__(self, db_path: str = "rollback.db"):
        self.db_path = db_path
        self.backup_dir = os.path.join(os.getcwd(), ".agent_backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    backup_path TEXT,
                    description TEXT,
                    success INTEGER DEFAULT 1
                )
            ''')
            conn.commit()
    
    def backup_file(self, file_path: str, description: str = "") -> Optional[str]:
        """备份文件"""
        try:
            abs_path = os.path.abspath(file_path)
            
            if not os.path.exists(abs_path):
                return None
            
            # 创建备份路径
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_subdir = os.path.join(self.backup_dir, timestamp)
            os.makedirs(backup_subdir, exist_ok=True)
            
            backup_filename = f"{os.path.basename(abs_path)}.{timestamp}.bak"
            backup_path = os.path.join(backup_subdir, backup_filename)
            
            # 复制文件
            shutil.copy2(abs_path, backup_path)
            
            # 记录操作
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO operations (timestamp, operation_type, file_path, backup_path, description)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    'backup',
                    abs_path,
                    backup_path,
                    description
                ))
                conn.commit()
                operation_id = cursor.lastrowid
            
            return backup_path
            
        except Exception as e:
            print(f"备份文件失败: {e}")
            return None
    
    def record_operation(self, operation_type: str, file_path: str, 
                        backup_path: Optional[str] = None, 
                        description: str = "", success: bool = True):
        """记录操作"""
        try:
            abs_path = os.path.abspath(file_path)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO operations (timestamp, operation_type, file_path, backup_path, description, success)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    operation_type,
                    abs_path,
                    backup_path,
                    description,
                    1 if success else 0
                ))
                conn.commit()
                
        except Exception as e:
            print(f"记录操作失败: {e}")
    
    def get_operation_history(self, limit: int = 50) -> List[Dict]:
        """获取操作历史"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, timestamp, operation_type, file_path, backup_path, description, success
                    FROM operations
                    ORDER BY id DESC
                    LIMIT ?
                ''', (limit,))
                
                rows = cursor.fetchall()
                return [
                    {
                        'id': row[0],
                        'timestamp': row[1],
                        'operation_type': row[2],
                        'file_path': row[3],
                        'backup_path': row[4],
                        'description': row[5],
                        'success': bool(row[6])
                    }
                    for row in rows
                ]
        except Exception as e:
            print(f"获取操作历史失败: {e}")
            return []
    
    def rollback_operation(self, operation_id: int) -> Dict:
        """回滚指定操作"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取操作信息
                cursor.execute('''
                    SELECT id, operation_type, file_path, backup_path
                    FROM operations
                    WHERE id = ?
                ''', (operation_id,))
                
                row = cursor.fetchone()
                if not row:
                    return {'success': False, 'error': '操作不存在'}
                
                op_id, op_type, file_path, backup_path = row
                
                if not backup_path or not os.path.exists(backup_path):
                    return {'success': False, 'error': '备份文件不存在'}
                
                # 执行回滚
                shutil.copy2(backup_path, file_path)
                
                # 记录回滚操作
                cursor.execute('''
                    INSERT INTO operations (timestamp, operation_type, file_path, backup_path, description, success)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    'rollback',
                    file_path,
                    backup_path,
                    f'回滚操作 #{op_id}',
                    1
                ))
                conn.commit()
                
                return {
                    'success': True,
                    'message': f'成功回滚操作 #{op_id}',
                    'file_path': file_path
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def rollback_to_point(self, target_timestamp: str) -> Dict:
        """回滚到指定时间点"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取目标时间之后的所有文件操作
                cursor.execute('''
                    SELECT id, file_path, backup_path
                    FROM operations
                    WHERE timestamp > ? AND operation_type IN ('edit', 'write', 'delete')
                    ORDER BY timestamp DESC
                ''', (target_timestamp,))
                
                operations = cursor.fetchall()
                
                if not operations:
                    return {'success': True, 'message': '没有需要回滚的操作'}
                
                # 按文件路径分组，只回滚每个文件的最新操作
                file_operations = {}
                for op_id, file_path, backup_path in operations:
                    if file_path not in file_operations:
                        file_operations[file_path] = (op_id, backup_path)
                
                # 执行回滚
                rollback_count = 0
                for file_path, (op_id, backup_path) in file_operations.items():
                    if backup_path and os.path.exists(backup_path):
                        shutil.copy2(backup_path, file_path)
                        rollback_count += 1
                
                return {
                    'success': True,
                    'message': f'回滚了 {rollback_count} 个文件',
                    'rollback_count': rollback_count
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def cleanup_old_backups(self, days: int = 7):
        """清理旧备份"""
        try:
            from datetime import timedelta
            
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取旧备份
                cursor.execute('''
                    SELECT backup_path FROM operations
                    WHERE timestamp < ? AND backup_path IS NOT NULL
                ''', (cutoff_date,))
                
                old_backups = [row[0] for row in cursor.fetchall() if row[0]]
                
                # 删除备份文件
                for backup_path in old_backups:
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                
                # 清理数据库记录
                cursor.execute('''
                    DELETE FROM operations WHERE timestamp < ?
                ''', (cutoff_date,))
                conn.commit()
                
                return len(old_backups)
                
        except Exception as e:
            print(f"清理旧备份失败: {e}")
            return 0
