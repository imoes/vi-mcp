# PREREG Z11-1, amendment 3 (exploratory): does the locality failure change facts or only wording?

Status: written 22.11.2026 after the edit-test compare (21:46:42 UTC). No text of a changed answer has been read; only the counts
and where each changed answer first diverges are known. Everything here is **exploratory**. It changes nothing in the
pre-registered result: the edit test fails on locality (26 of 46 answers outside F are textually identical, 0.565 < 0.9), so H2
fails, and it stays failed.

## Question

20 of the 46 K answers to questions outside F changed after F's 95 sources were forgotten. Did the facts change, or only the
wording? The answer decides how the next design has to look: a forget that disturbs neighbours more locally, or interpolation only
when retrieval is confident.

## Procedure

1. **Items.** The 20 changed questions outside F (`edit_compare.json` → `outside_F_changed`). Each item shows the K answer before
   the forget and the K answer after it, as A and B. The order is seeded per question (`random.Random("z11:locality:" + id)`), and
   the key is in a separate file. A budget hit is marked as in the primary pass.
2. **Judge.** One fresh blind subagent with the primary rubric. It grades each side pointwise (correct, partial or wrong) against
   the reference and the document. It then gives a pair verdict on the fact the question asks for:
   - `same_facts`: both state the same facts;
   - `different_facts`: the facts differ, but neither answer is worse;
   - `A_worse` or `B_worse`: one answer is worse.
3. **Report.**
   - The counts of the pair verdicts. After the key is opened, the verdicts are mapped to `after_worse` and `before_worse`.
   - The per-side grades before and after the forget.
   - The two-sided exact sign test on the grade changes, labelled exploratory.

## Reading

- If most verdicts are `same_facts` and the grades do not drop, then the failure is wording drift under greedy decoding. The
  textual-identity criterion was then stricter than the purpose it stood for.
- If `after_worse` is frequent, then forgetting harms neighbours, and the design needs a locality-aware forget.

Neither reading rescues H2.
