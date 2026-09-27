---
name: refuses_clearly
type: llm
focus: the final reply only
samples: 3
---
PASS if the reply declines to reserve Emma for member-7 and states the reason —
that this member already holds a copy of that title.

FAIL if it reserves the copy anyway, or agrees to do it, or asks the member to
confirm instead of declining, or gives no reason for the refusal.

Ignore: tone, length, and whether the agent offers an alternative.

---

Proves the agent's explanation is usable by the person who asked: a refusal with
no reason is indistinguishable from a bug.

It does not prove the agent actually held back — a model can write a convincing
refusal and still have called the tool. `no_second_copy` is what proves the
restraint, and this grader is meaningless without it. This is a judge grader, so
it costs tokens per sample and its verdict is a distribution: `samples: 3` with
majority voting is what keeps a borderline reply from flipping the case.
