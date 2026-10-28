"""The knowledge base and note claims of the evaluation (contracts section 21).

    facts.build_knowledge(rule_seed)   what the data files say, as facts (the answer key)
    claims                             what a note says, as claims in a fixed form
    judge.judge(claim, knowledge)      right, partly right, wrong or not judged: all code
    extract                            a cheap model reads note files and writes their claims
                                       (`notes-claims`)
    doc                                the readable English copy (`knowledge --doc`)
    lessons                            what each encounter teaches (from `content/encounters`)

Everything here is evaluation: it holds the recipes and the answers, and **nothing reaches an
agent, the play server or a web page** (the guard test of `tests/eval` covers this package). The
metrics that use it are in `eval/metrics/knowledge.py`.
"""

from .claims import FILE_NAME, Claim, NoteClaims, load_note_claims, parse_claim, save_note_claims
from .facts import Fact, Knowledge, build_knowledge
from .judge import Verdict, counts, judge, subject_of

__all__ = [
    "FILE_NAME",
    "Claim",
    "Fact",
    "Knowledge",
    "NoteClaims",
    "Verdict",
    "build_knowledge",
    "counts",
    "judge",
    "load_note_claims",
    "parse_claim",
    "save_note_claims",
    "subject_of",
]
