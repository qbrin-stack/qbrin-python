"""Grounded Q&A: every claim cited, honest abstain when unknown.

Run:  QBRIN_API_KEY=qbrin_...  python examples/ask_with_citations.py
"""

import os

from qbrin import Qbrin

qb = Qbrin(api_key=os.environ["QBRIN_API_KEY"])

a = qb.ask("What is our refund policy for enterprise customers?")
print(a.answer)
print()
for c in a.citations:
    print(f"  [{c.n}] {c.source or '?'} · {c.title or c.document_id}")
