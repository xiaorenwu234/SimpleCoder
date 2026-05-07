"""
测试代码库索引器 (tools/code_indexer.py)
"""
import os
import pytest
from tools.code_indexer import CodeIndexer


class TestCodeIndexer:
    """CodeIndexer 测试"""
    
    def test_init(self, temp_db):
        """测试初始化"""
        indexer = CodeIndexer(db_path=temp_db)
        assert indexer.db_path == temp_db
    
    def test_index_file(self, temp_dir, temp_db):
        """测试索引单个文件"""
        indexer = CodeIndexer(db_path=temp_db)
        
        # 创建测试文件
        test_file = os.path.join(temp_dir, "sample.py")
        with open(test_file, "w") as f:
            f.write('''"""Sample module."""

class MyClass:
    """A sample class."""
    
    def method_one(self, x: int) -> int:
        """Method one."""
        return x * 2
    
    def method_two(self) -> str:
        """Method two."""
        return "hello"


def standalone_func(a: str, b: int) -> bool:
    """A standalone function."""
    return len(a) > b
''')
        
        indexer.index_file(test_file)
        
        # 验证符号被索引
        symbols = indexer.search_symbol("MyClass")
        assert len(symbols) > 0
        assert any(s["type"] == "class" for s in symbols)
    
    def test_index_file_symbols(self, temp_dir, temp_db):
        """测试索引类、方法、函数"""
        indexer = CodeIndexer(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "symbols.py")
        with open(test_file, "w") as f:
            f.write('''class Foo:
    def bar(self):
        pass

def baz():
    pass
''')
        
        indexer.index_file(test_file)
        
        # 搜索类
        classes = indexer.search_symbol("Foo")
        assert len(classes) > 0
        assert classes[0]["type"] == "class"
        
        # 搜索方法
        methods = indexer.search_symbol("bar")
        assert len(methods) > 0
        
        # 搜索函数
        funcs = indexer.search_symbol("baz")
        assert len(funcs) > 0
        assert funcs[0]["type"] == "function"
    
    def test_index_file_imports(self, temp_dir, temp_db):
        """测试索引导入"""
        indexer = CodeIndexer(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "imports.py")
        with open(test_file, "w") as f:
            f.write('''import os
import sys
from pathlib import Path
from typing import List, Dict
''')
        
        indexer.index_file(test_file)
        
        # 验证引用搜索
        refs = indexer.find_references("os")
        assert len(refs) > 0
    
    def test_index_directory(self, sample_python_project, temp_db):
        """测试索引整个目录"""
        indexer = CodeIndexer(db_path=temp_db)
        
        count = indexer.index_directory(sample_python_project)
        assert count >= 3  # 至少 calculator.py, utils.py, test_calc.py
    
    def test_index_directory_skips_hidden(self, temp_dir, temp_db):
        """测试跳过隐藏目录"""
        indexer = CodeIndexer(db_path=temp_db)
        
        # 创建隐藏目录中的文件
        hidden_dir = os.path.join(temp_dir, ".hidden")
        os.makedirs(hidden_dir)
        with open(os.path.join(hidden_dir, "secret.py"), "w") as f:
            f.write("def secret(): pass")
        
        # 创建正常文件
        with open(os.path.join(temp_dir, "normal.py"), "w") as f:
            f.write("def normal(): pass")
        
        count = indexer.index_directory(temp_dir)
        # 应该只索引了 normal.py
        assert count == 1
    
    def test_search_symbol_by_type(self, temp_dir, temp_db):
        """测试按类型搜索符号"""
        indexer = CodeIndexer(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "typed.py")
        with open(test_file, "w") as f:
            f.write('''class MyClass:
    def my_method(self): pass

def my_function(): pass
''')
        
        indexer.index_file(test_file)
        
        # 只搜索类
        classes = indexer.search_symbol("my", symbol_type="class")
        assert all(s["type"] == "class" for s in classes)
        
        # 只搜索函数
        funcs = indexer.search_symbol("my", symbol_type="function")
        assert all(s["type"] == "function" for s in funcs)
    
    def test_search_symbol_not_found(self, temp_db):
        """测试搜索不存在的符号"""
        indexer = CodeIndexer(db_path=temp_db)
        results = indexer.search_symbol("nonexistent_symbol_xyz")
        assert len(results) == 0
    
    def test_find_references(self, temp_dir, temp_db):
        """测试查找引用"""
        indexer = CodeIndexer(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "refs.py")
        with open(test_file, "w") as f:
            f.write('''from os.path import join, exists
import json
''')
        
        indexer.index_file(test_file)
        refs = indexer.find_references("json")
        assert len(refs) > 0
    
    def test_get_file_info(self, temp_dir, temp_db):
        """测试获取文件信息"""
        indexer = CodeIndexer(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "info.py")
        with open(test_file, "w") as f:
            f.write("x = 1\n")
        
        indexer.index_file(test_file)
        info = indexer.get_file_info(test_file)
        assert info is not None
        assert info["language"] == "python"
    
    def test_get_index_stats(self, temp_dir, temp_db):
        """测试获取索引统计"""
        indexer = CodeIndexer(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "stats.py")
        with open(test_file, "w") as f:
            f.write("def func(): pass\n")
        
        indexer.index_file(test_file)
        stats = indexer.get_index_stats()
        assert "files" in stats
        assert "symbols" in stats
        assert "imports" in stats
        assert stats["files"] >= 1
    
    def test_detect_language(self, temp_db):
        """测试语言检测"""
        indexer = CodeIndexer(db_path=temp_db)
        
        assert indexer._detect_language("test.py") == "python"
        assert indexer._detect_language("test.js") == "javascript"
        assert indexer._detect_language("test.ts") == "typescript"
        assert indexer._detect_language("test.java") == "java"
        assert indexer._detect_language("test.go") == "go"
        assert indexer._detect_language("test.rs") == "rust"
        assert indexer._detect_language("test.xyz") == "unknown"
    
    def test_index_sample_project(self, sample_python_project, temp_db):
        """测试完整项目索引（集成测试）"""
        indexer = CodeIndexer(db_path=temp_db)
        
        # 索引项目
        count = indexer.index_directory(sample_python_project)
        assert count >= 2
        
        # 搜索 Calculator 类
        calc_results = indexer.search_symbol("Calculator")
        assert len(calc_results) > 0
        assert any(s["type"] == "class" for s in calc_results), f"Expected class in results, got: {calc_results}"
        
        # 搜索方法
        add_results = indexer.search_symbol("add")
        assert len(add_results) > 0
        
        # 搜索函数
        greet_results = indexer.search_symbol("greet")
        assert len(greet_results) > 0
        
        # 统计
        stats = indexer.get_index_stats()
        assert stats["symbols"] >= 5  # Calculator + methods + functions
