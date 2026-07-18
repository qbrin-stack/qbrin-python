"""Gate an agent's action on a qbrin verification.

Run:  QBRIN_API_KEY=qbrin_...  python examples/verify_agent_action.py
"""

import os

from qbrin import Qbrin

qb = Qbrin(api_key=os.environ["QBRIN_API_KEY"])

# The agent wants to refund $500. Verify against the org's own policy + order data.
verdict = qb.verify("Can a Support Manager refund $500 for order ORD-200?")

print("decision:   ", verdict.decision)
print("explanation:", verdict.explanation)

if verdict.is_verified:
    print("answer:     ", verdict.answer)
    for e in verdict.evidence:
        print(f"  [{e.n}] {e.source or '?'} · {e.title or e.document_id}: {e.snippet!r}")
    # → safe to proceed with the action, with sources logged.
elif verdict.is_rejected:
    print("The sources contradict this — do NOT act. Surface the explanation to the user.")
else:  # need_more_evidence
    print("Not enough evidence — ask the user for context or connect the missing source.")
