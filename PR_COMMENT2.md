<!--
Scratch file: the short comment to actually post on the pull request, kept on the
doublefree-opus5 branch so it can be read rendered on the web. It is not part of
the patch series -- drop this commit before sending anything upstream.

PR_COMMENT.md is the long review-facing writeup. Reviewers asked to keep the
design discussion on the forum rather than on the pull request, so that material
belongs in the RFC thread instead, and only the note below is posted here.
-->

Agreed, let's keep the design discussion on the forum rather than here.

One note so it does not get lost with the RFC: this branch is the stand-alone
LeakSanitizer alternative to the DSan runtime, so it opens with a revert of that
commit and ends with the LSan implementation. The two commits in between are
pre-existing `realloc()` bugs that still reproduce on `main` and are independent
of this proposal. I am happy to send them as a separate pull request if that is
easier to review.
