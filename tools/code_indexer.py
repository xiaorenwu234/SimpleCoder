"""
代码库索引和语义搜索工具
"""
import os
import ast
import json
import sqlite3
from typing import List, Dict, Optional, Set
from pathlib import Path
from datetime import datetime


class CodeIndexer:
    """代码库索引器"""
    
    def __init__(self, db_path: str = "code_index.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 文件表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    language TEXT,
                    size INTEGER,
                    last_modified TEXT,
                    indexed_at TEXT
                )
            ''')
            
            # 符号表（类、函数、方法）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,  -- class, function, method
                    line_number INTEGER,
                    end_line_number INTEGER,
                    signature TEXT,
                    docstring TEXT,
                    FOREIGN KEY (file_id) REFERENCES files(id)
                )
            ''')
            
            # 导入关系表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER,
                    module TEXT,
                    names TEXT,  -- JSON array
                    line_number INTEGER,
                    FOREIGN KEY (file_id) REFERENCES files(id)
                )
            ''')
            
            # 引用关系表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS code_references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file_id INTEGER,
                    source_line INTEGER,
                    target_symbol TEXT,
                    FOREIGN KEY (source_file_id) REFERENCES files(id)
                )
            ''')
            
            conn.commit()
    
    def index_directory(self, directory: str, file_extensions: List[str] = None):
        """索引整个目录"""
        if file_extensions is None:
            file_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs']
        
        files_indexed = 0
        for root, dirs, files in os.walk(directory):
            # 跳过隐藏目录和常见忽略目录
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in 
                      ['node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build']]
            
            for file in files:
                file_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1]
                
                if ext in file_extensions:
                    try:
                        self.index_file(file_path)
                        files_indexed += 1
                    except Exception as e:
                        print(f"索引文件失败 {file_path}: {e}")
        
        return files_indexed
    
    def index_file(self, file_path: str):
        """索引单个文件"""
        abs_path = os.path.abspath(file_path)
        
        if not os.path.exists(abs_path):
            return
        
        # 获取文件信息
        stat = os.stat(abs_path)
        language = self._detect_language(abs_path)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 插入或更新文件
            cursor.execute('''
                INSERT OR REPLACE INTO files (path, language, size, last_modified, indexed_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                abs_path,
                language,
                stat.st_size,
                datetime.fromtimestamp(stat.st_mtime).isoformat(),
                datetime.now().isoformat()
            ))
            
            file_id = cursor.lastrowid
            if file_id == 0:  # 如果是更新，获取ID
                cursor.execute('SELECT id FROM files WHERE path = ?', (abs_path,))
                file_id = cursor.fetchone()[0]
            
            # 如果是Python文件，解析AST
            if language == 'python':
                self._index_python_file(conn, file_id, abs_path)
    
    def _index_python_file(self, conn, file_id: int, file_path: str):
        """索引Python文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source, filename=file_path)
            cursor = conn.cursor()
            
            # 清除旧符号
            cursor.execute('DELETE FROM symbols WHERE file_id = ?', (file_id,))
            cursor.execute('DELETE FROM imports WHERE file_id = ?', (file_id,))
            
            # 遍历AST
            for node in ast.walk(tree):
                # 索引类
                if isinstance(node, ast.ClassDef):
                    cursor.execute('''
                        INSERT INTO symbols (file_id, name, type, line_number, end_line_number, docstring)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        file_id,
                        node.name,
                        'class',
                        node.lineno,
                        node.end_lineno or node.lineno,
                        ast.get_docstring(node)
                    ))
                    
                    # 索引类中的方法
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            cursor.execute('''
                                INSERT INTO symbols (file_id, name, type, line_number, end_line_number, signature, docstring)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                file_id,
                                f"{node.name}.{item.name}",
                                'method',
                                item.lineno,
                                item.end_lineno or item.lineno,
                                self._get_function_signature(item),
                                ast.get_docstring(item)
                            ))
                
                # 索引函数
                elif isinstance(node, ast.FunctionDef):
                    cursor.execute('''
                        INSERT INTO symbols (file_id, name, type, line_number, end_line_number, signature, docstring)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        file_id,
                        node.name,
                        'function',
                        node.lineno,
                        node.end_lineno or node.lineno,
                        self._get_function_signature(node),
                        ast.get_docstring(node)
                    ))
                
                # 索引导入
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        cursor.execute('''
                            INSERT INTO imports (file_id, module, names, line_number)
                            VALUES (?, ?, ?, ?)
                        ''', (
                            file_id,
                            alias.name,
                            json.dumps([]),
                            node.lineno
                        ))
                
                elif isinstance(node, ast.ImportFrom):
                    names = [alias.name for alias in node.names]
                    cursor.execute('''
                        INSERT INTO imports (file_id, module, names, line_number)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        file_id,
                        node.module or '',
                        json.dumps(names),
                        node.lineno
                    ))
            
            conn.commit()
            
        except Exception as e:
            print(f"解析Python文件失败 {file_path}: {e}")
    
    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        """获取函数签名"""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        return f"({', '.join(args)})"
    
    def _detect_language(self, file_path: str) -> str:
        """检测文件语言"""
        ext = os.path.splitext(file_path)[1].lower()
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.go': 'go',
            '.rs': 'rust',
            '.rb': 'ruby',
            '.php': 'php'
        }
        return language_map.get(ext, 'unknown')
    
    def search_symbol(self, name: str, symbol_type: str = None) -> List[Dict]:
        """搜索符号"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = 'SELECT s.name, s.type, s.line_number, f.path, s.docstring FROM symbols s JOIN files f ON s.file_id = f.id WHERE s.name LIKE ?'
            params = [f'%{name}%']
            
            if symbol_type:
                query += ' AND s.type = ?'
                params.append(symbol_type)
            
            cursor.execute(query, params)
            
            return [
                {
                    'name': row[0],
                    'type': row[1],
                    'line': row[2],
                    'file': row[3],
                    'docstring': row[4]
                }
                for row in cursor.fetchall()
            ]
    
    def find_references(self, symbol_name: str) -> List[Dict]:
        """查找符号引用"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 在导入中查找
            cursor.execute('''
                SELECT f.path, i.module, i.names, i.line_number
                FROM imports i JOIN files f ON i.file_id = f.id
                WHERE i.module LIKE ? OR i.names LIKE ?
            ''', (f'%{symbol_name}%', f'%{symbol_name}%'))
            
            return [
                {
                    'file': row[0],
                    'module': row[1],
                    'names': json.loads(row[2]) if row[2] else [],
                    'line': row[3]
                }
                for row in cursor.fetchall()
            ]
    
    def get_file_info(self, file_path: str) -> Optional[Dict]:
        """获取文件信息"""
        abs_path = os.path.abspath(file_path)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT path, language, size, last_modified FROM files WHERE path = ?', (abs_path,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'path': row[0],
                    'language': row[1],
                    'size': row[2],
                    'last_modified': row[3]
                }
            return None
    
    def get_index_stats(self) -> Dict:
        """获取索引统计"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM files')
            file_count = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM symbols')
            symbol_count = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM imports')
            import_count = cursor.fetchone()[0]
            
            return {
                'files': file_count,
                'symbols': symbol_count,
                'imports': import_count
            }
