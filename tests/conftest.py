"""
测试公共配置 - 提供共享的 fixture 和工具函数
"""
import os
import sys
import tempfile
import shutil
import pytest

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def temp_dir():
    """创建临时目录，测试结束后自动清理"""
    d = tempfile.mkdtemp(prefix="test_agent_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_file(temp_dir):
    """创建临时文件，返回文件路径"""
    filepath = os.path.join(temp_dir, "test_file.py")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# test file\ndef hello():\n    return 'world'\n")
    return filepath


@pytest.fixture
def sample_python_project(temp_dir):
    """创建一个示例 Python 项目目录结构"""
    # 主模块
    src_dir = os.path.join(temp_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    
    with open(os.path.join(src_dir, "__init__.py"), "w") as f:
        f.write("")
    
    with open(os.path.join(src_dir, "calculator.py"), "w") as f:
        f.write('''"""Simple calculator module."""

class Calculator:
    """A basic calculator."""
    
    def __init__(self, value: float = 0):
        self.value = value
    
    def add(self, x: float) -> float:
        """Add x to current value."""
        self.value += x
        return self.value
    
    def subtract(self, x: float) -> float:
        """Subtract x from current value."""
        self.value -= x
        return self.value
    
    def multiply(self, x: float) -> float:
        """Multiply current value by x."""
        self.value *= x
        return self.value
    
    def reset(self) -> float:
        """Reset to zero."""
        self.value = 0
        return self.value


def add_numbers(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def greet(name: str) -> str:
    """Return greeting."""
    return f"Hello, {name}!"
''')
    
    with open(os.path.join(src_dir, "utils.py"), "w") as f:
        f.write('''"""Utility functions."""
import os


def ensure_dir(path: str) -> str:
    """Ensure directory exists."""
    os.makedirs(path, exist_ok=True)
    return path


def safe_divide(a: float, b: float) -> float:
    """Safe division with zero check."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
''')
    
    # 测试文件
    tests_dir = os.path.join(temp_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    
    with open(os.path.join(tests_dir, "__init__.py"), "w") as f:
        f.write("")
    
    with open(os.path.join(tests_dir, "test_calc.py"), "w") as f:
        f.write('''from src.calculator import Calculator, add_numbers

def test_add_numbers():
    assert add_numbers(1, 2) == 3

def test_calculator():
    calc = Calculator()
    assert calc.add(5) == 5
    assert calc.subtract(3) == 2
''')
    
    return temp_dir


@pytest.fixture
def temp_db(temp_dir):
    """创建临时数据库路径"""
    return os.path.join(temp_dir, "test.db")
