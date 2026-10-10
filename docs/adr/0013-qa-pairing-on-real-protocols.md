# ADR-0013: Q/A pairing policy after measuring real protocols

**Status:** accepted, 2026-10-10.

**Context.** On four real protocols (Sept 2025, 550 pages), independent AI annotators judged rule-based Q/A pairs:
- 80/100 correct on the first sample;
- 77/100 on a held-out sample after the parser was improved.

The target is 95%.

Almost every wrong pair has a "question" that is not a question:
- an acknowledgement ("טוב.", "אוקיי."), an interruption ("רגע, מר נתניהו."), or a meta-remark ("זו לא השאלה שלי");
- a quoted passage being read out;
- counsel answering the witness.

Pairs whose question ends with "?" were right 108/112 times. Pairs without it were right about 55% of the time.

**Decision.**
1. The parser drops "ש." turns that match an acknowledgement, interruption or meta-remark lexicon, or that are followed by a continuation-answer ("תן לי להשלים…"). They are counsel's speech, not questions.
2. Every pair whose question has no "?" gets flag `no_question_mark` and confidence −0.3. Flags already block automatic public wording ("העד אישר/הכחיש את הנטען…"). Such pairs need model verification and human review before any public use.
3. The pairing metric is reported as **failed**. Lexicon tuning is not claimed as a fix, because it did not generalise to held-out data.

**Next.** Add a model-based question/non-question classifier as a `verify`-stage task. Evaluate it on a fresh labelled sample only.
