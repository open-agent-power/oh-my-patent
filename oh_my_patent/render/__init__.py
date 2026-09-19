"""渲染层：把 :class:`~oh_my_patent.schema.PatentDraft` 输出成文书。

当前只提供 .docx 一种载体。渲染器与模型之间只通过
:class:`~oh_my_patent.schema.PatentDraft` 交互，因此将来要加 PDF 或
纯文本输出，只需在 ``render`` 下新增模块，解析层与模型层不必改动。
"""

from .docx import DocxRenderer, render_docx

__all__ = ["DocxRenderer", "render_docx"]
