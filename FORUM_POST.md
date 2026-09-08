<!--
Scratch file: the reply to post in the RFC thread on Discourse, kept on the
doublefree-opus5 branch so it can be read rendered on the web. It is not part of
the patch series -- drop this commit before sending anything upstream.

The design discussion moves here from the pull request, so this is where the
material in PR_COMMENT.md belongs. Keep it short: the open questions are the
point, the implementation details are in the commit messages and the docs.
-->

I have reimplemented this as an optional feature of stand-alone LeakSanitizer
rather than a separate runtime, and updated the pull request:
[llvm/llvm-project#213846](https://github.com/llvm/llvm-project/pull/213846).
Enable it with `LSAN_OPTIONS=detect_double_free=1`; it is off by default. The
first commit of that series reverts the `DoubleFreeSanitizer` runtime I proposed
earlier. Folding the check into LSan came out at roughly a third of the code,
because it reuses the existing allocator and interceptors instead of duplicating
them.

### How it works

Chunks served by the primary allocator keep their metadata mapped after they are
freed, so the allocation stack and the first-free stack are stored inline in
`ChunkMetadata`, which stays 16 bytes, and the check is a single compare-exchange
that takes no lock. Chunks served by the secondary allocator are unmapped along
with their metadata, so their stacks go into a side table guarded by one mutex
and bounded by `double_free_max_entries` (default 65536, 3.5 MiB) with FIFO
eviction. Validating the freed pointer is a prerequisite for the check, so while
the option is on an invalid free is reported as `bad-free` instead of being
handed to the allocator, which would otherwise fault inside the runtime.

### Costs and limits

- With the option on, every free of a large allocation also scans the secondary
  allocator's chunk list, linear in the number of live large allocations. Small
  allocations are unaffected.
- Records for large allocations are keyed by the returned address, so they are
  approximate: an evicted or superseded record degrades to `bad-free` rather
  than a double-free report. Primary chunks are exact.
- Not supported on macOS or NetBSD, where fork handling does not go through the
  LSan `pthread_atfork` hooks that protect the side table.
- Tested on x86-64 only. The 32-bit metadata layout is pinned by a
  `static_assert`, but no 32-bit run was made.

### Open questions

1. **Is stand-alone LSan the right home?** The cost of this shape is that
   `detect_double_free` is a visible-but-inert `LSAN_OPTIONS` flag under ASan and
   HWASan, because `RegisterLsanFlags()` is shared. I documented that in the flag
   description and the docs; if that is judged too sharp an edge, the flag can be
   registered by the stand-alone runtime only.
2. **Should invalid-free detection be its own flag?** It is bundled here because
   validating the pointer is a prerequisite for the double-free check, not an
   independent feature. That is a judgment call and I am happy to split it.
3. **Is the secondary allocator's cost acceptable?** If the scan above is too
   much for the default shape of the feature, large-allocation tracking could
   become its own opt-in.

The pull request also carries two pre-existing `realloc()` bug fixes that are
independent of this proposal; I can send those separately if that is easier.

This post and the implementation were written with AI assistance; the commits
carry an `Assisted-by:` trailer.
