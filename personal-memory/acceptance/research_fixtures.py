"""Synthetic-only research corpus, safe to commit and regenerate."""
from pathlib import Path


def build_fixture(vault: Path) -> dict:
    notes = {
        '计算机和AI/架构.md': '# Transformer\nTransformer 使用自注意力并行处理输入序列，不必像RNN那样逐词顺序处理。\n',
        '计算机和AI/检索.md': '# 语义检索\nEmbedding把文字编码成向量，向量相似度检索帮助按意思找回笔记。\n',
        '计算机和AI/教程.md': '# RAG教程\n建议先分段、生成向量、检索，再把材料交给模型回答。这是一份教程，不是实践记录。\n',
        '计算机和AI/实践.md': '# 2026年10月8日\n今天我搭建了一个合成RAG原型，尚未测试回答效果，也没有说明这是不是第一次。\n',
        '我的存在/截至9月的日记.md': '\n'.join(f'# 2026 年 10 月 {d} 日\n合成观察{d}：'+('今天轻松且期待下一次活动。' if d in (4,12) else '今天疲惫，想休息，情绪有反复。') for d in (4,5,8,12)),
        '我的存在/日期不清.md': '# 10月3日\n这是年份不明的一条合成记录。\n# 2026年2月30日\n这是非法日期的一条合成记录。\n',
        '我的存在/嵌套.md': '# 2026年\n## 10月4日\n### 上午\n上午合成记录期待活动。\n### 晚上\n晚上合成记录感觉疲惫。\n## 10月5日\n另一日合成记录。\n',
        '我的存在/诱饵.md': '# RAG\nRAG这个词出现于合成故事中，不能把此日记作为技术实践的证据。\n',
        'wiki/a/同名.md': '# 星光\n甲目录里保存了关于星光的合成技术说明。\n',
        'wiki/b/同名.md': '# 星光\n乙目录里保存了另一个关于星光的合成说明。\n',
        '计算机和AI/长行.md': '# 长行\n'+('甲😀乙丙丁' * 3500)+'\n',
    }
    for name,text in notes.items():
        p=vault/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    return dict(expected_dates=[f'2026-10-{d:02}' for d in (4,5,8,12)],
                technical_targets=['计算机和AI/架构.md','计算机和AI/检索.md','计算机和AI/教程.md','计算机和AI/实践.md'],
                diary='我的存在/截至9月的日记.md',notes=len(notes))
