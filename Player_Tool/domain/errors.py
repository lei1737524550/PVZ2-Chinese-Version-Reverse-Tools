"""Tool_2 统一异常类型。"""

class ToolError(Exception):
    """可直接展示给用户的业务错误。"""


class RtonFormatError(ToolError):
    """RTON 结构或编码不合法。"""
