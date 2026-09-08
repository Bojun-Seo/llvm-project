<!--
Scratch file: the review-facing comment to post on the pull request, kept on the
doublefree-opus5 branch so it can be read rendered on the web. It is not part of
the patch series -- drop this commit before sending anything upstream.

The split is deliberate: this project turns the PR description into the squash
commit message, so PR_DESCRIPTION.txt is written as a commit message and holds
only what belongs in permanent history. Everything that is addressed to
reviewers rather than to future readers of `git log` lives here.
-->

Posting the review context separately from the description, since the
description becomes the commit message.

This is the working implementation behind the RFC.

**The double-free commit is a proof of concept.** It was written to give the RFC
discussion something concrete to argue about, not to be merged as it stands. It
builds, it is tested, and the behavior described in the commit message is real,
but I expect the open questions below to change its shape, and I would rather
settle those than polish an implementation that may not survive them. So the
open questions matter more to me here than the code details.

The two realloc fixes are in a different category. They are ordinary bug fixes
against existing behavior, they are not part of the RFC, and I do consider them
ready to review on their own terms.

## Example output

```console
$ clang++ -g -O0 -fno-omit-frame-pointer -fsanitize=leak double-free.cpp -o double-free
$ LSAN_OPTIONS=detect_double_free=1 ./double-free
==1234==ERROR: LeakSanitizer: attempting double-free on 0x504000000010 in thread T0:
The second free occurred here:
    #0 0x... in free
    #1 0x... in Free(void*) double-free.cpp:3
    #2 0x... in main double-free.cpp:8
The first free occurred here:
    #0 0x... in free
    #1 0x... in Free(void*) double-free.cpp:3
    #2 0x... in main double-free.cpp:7
The memory was allocated here:
    #0 0x... in malloc
    #1 0x... in main double-free.cpp:6
SUMMARY: LeakSanitizer: double-free
```

## Open questions for the RFC

1. **Is stand-alone LSan the right home?** The alternative I tried first was a
   separate `DoubleFreeSanitizer` runtime; this series is the "fold it into
   stand-alone LSan" answer, which is far less code and reuses the existing
   allocator. The cost is that `detect_double_free` is a visible-but-inert
   `LSAN_OPTIONS` flag under ASan and HWASan, because `RegisterLsanFlags()` is
   shared. I documented that in the flag description and the docs; if that is
   judged too sharp an edge, the flag can be registered only by the stand-alone
   runtime instead.
2. **Should invalid-free detection be its own flag?** It is bundled here because
   validating the pointer is a prerequisite for the double-free check, not an
   independent feature. That is a judgment call and I am happy to split it.
3. **Is the secondary allocator's cost acceptable?** With the option on, every
   free of a large allocation also scans the secondary chunk list. If that is too much for
   the default shape of the feature, large-allocation tracking could become its
   own opt-in.

## Cost and limitations

The user-facing documentation in `clang/docs/LeakSanitizer.md` is deliberately
short -- that file is a page about LeakSanitizer, not about this option, and the
rest of it is five brief sections. The detail that would have swamped it is
here instead, where reviewers need it.

**Cost, primary allocator.** These chunks keep their metadata mapped after they
are freed, so the allocation stack and the first-free stack live inline in the
existing per-chunk metadata, and the check is a single compare-exchange that
takes no lock. `ChunkMetadata` stays 16 bytes, so no memory is added per chunk.
With the option off what is left is a load of the flag and a branch on each
free, one extra store per allocation, and a larger `.text`. That is small, but
it is not nothing, and I have not been able to separate it from allocator noise
in a malloc/free microbenchmark, so I am not claiming a figure for it.

**Cost, secondary allocator.** These chunks are unmapped as soon as they are
freed, taking their metadata with them, so their stacks go into a side table.
Releasing one copies those stacks into the table and unmaps the chunk as one
step under the mutex that guards the table, so that a concurrent free cannot
unmap the metadata another thread is still validating. Every free of a large
allocation therefore also pays a scan of the secondary allocator's chunk list,
linear in the number of live large allocations. Programs that keep many large
allocations alive and free them in a hot loop are the ones to measure; small
allocations are unaffected.

**Side-table memory.** An 8-byte ring slot plus a 24-byte `DenseMap` bucket per
remembered address. The bucket array is a power of two held under a 3/4 load
factor, so the cost per entry swings between 40 and 72 bytes depending on where
the count sits between doublings. At the default `double_free_max_entries=65536`
the table settles at 131072 buckets: 3 MiB of buckets plus 0.5 MiB of ring, so
3.5 MiB, or 56 bytes per entry; a doubling transiently maps the old bucket array
alongside the new one. At the `4194304` cap the same arithmetic gives 224 MiB.
`0` means unlimited, a negative value is treated as `0`, and a value above
`4194304` is capped, both with a warning at startup. The option does not bound
the process-wide stack depot that retains the recorded traces, so total memory
use is not hard-capped by it.

**Eviction.** When the limit is reached the oldest entry goes, so a bounded
table always remembers the most recent frees. An evicted address is no longer
recognized as a double free and is reported as an invalid free instead.

**Address-keyed records are approximate for large allocations.** A record is
keyed by the address the allocator returned, so a new allocation at the same
address supersedes it. That is exact for the primary allocator, where an address
is only reused for the same chunk. For the secondary allocator, if an old freed
address later falls *inside* a new, larger mapping rather than at its start, the
stale record is not superseded; freeing that interior address is invalid either
way, but it may be reported as a double free carrying the older allocation's
stacks. In the other direction, a freed large mapping whose address is later
taken over by the primary allocator stops being recognized, because the address
is then checked against the primary allocator's metadata; that needs a primary
that maps its regions on demand, as on 32-bit, since a 64-bit one reserves its
whole space at startup.

**Racing a free against a new allocation of the same address** -- itself a
use-after-free -- can lose the record of the free, because the chunk state and
the fields written by the allocation path share one storage unit. What is
bounded is the detection: the double free may be misreported or missed, and a
missed one reaches the allocator exactly as it does today without the option.

**Reporting.** Both reporters hold the sanitizer error-report lock across
`Die()`, the way ASan's `ScopedInErrorReport` does. Without that, a thread that
reached a report while another was printing would append a truncated second
report as the process exited; an 8-thread stress test hit that in 44 of 120 runs
before the lock was extended, and in 0 of 120 after.

**Other notes.** The option is independent of leak checking: combine it with
`detect_leaks=0` to report double frees without running the leak check at exit.
Detection applies only to allocations made through the intercepted allocator; a
pointer from a different allocator cannot be recognized.

## The two realloc fixes are independent of the feature

The first two commits are pre-existing bugs that still reproduce on `main`
today. They were found while developing the double-free check rather than looked
for -- the feature has to touch `Reallocate()` -- and neither is a consequence of
it: each stands on its own and carries its own test. They are ordered first here,
and I am happy to pull them into their own pull request(s) if you would rather
review them separately from the RFC.

One ordering constraint is worth naming, though. The LSan fix incidentally makes
`realloc(NULL, 0)` register a one-byte allocation instead of a zero-byte one, and
a requested size of zero is exactly how the double-free check recognizes a slot
the allocator never handed out. Without that fix in front of it, the check
reports `free(realloc(NULL, 0))` -- perfectly legal code -- as an invalid free. So
within this series the LSan fix has to land first; the `sanitizer_common` one is
free-standing.

They fix different layers:

| | Breaks | Symptom |
|---|---|---|
| `[sanitizer_common] Keep the original allocation alive when Reallocate fails` | the memory | a failing `realloc()` puts the caller's chunk back on the free list, so a later `malloc()` hands out the same address and overwrites it |
| `[lsan] Do not release the original allocation when realloc fails` | the bookkeeping | even with the memory intact, a free hook fires for a pointer the caller still owns, and `__sanitizer_get_allocated_size()` reports a size that was never allocated |

Note that the LSan fix stops routing through `CombinedAllocator::Reallocate()`
altogether, which makes LSan immune to the first bug on its own. I kept the
`sanitizer_common` fix anyway: the function is still wrong, it still has another
in-tree caller in `InternalRealloc()`, and an out-of-tree user of the allocator
would reasonably expect it to match `realloc()` semantics.

## Testing

Ten lit tests under `compiler-rt/test/lsan/TestCases/` cover primary and
secondary chunks, the on/off/`max_entries=0` matrix, FIFO eviction (both the
remembered and the evicted address), `realloc()` against freed
small/large/interior pointers and a successful `realloc()` of a live large one,
`free_sized()`/`free_aligned_sized()`, invalid frees, free-hook behavior,
`double_free_max_entries` validation, concurrent frees from 16 threads, and
`fork()` with a churning thread.

The test set was chosen against line coverage rather than by eye: an
instrumented build of the runtime puts 194 of the 198 executable lines this
series adds to `lsan_allocator.cpp` under test, plus all of the changed lines in
`lsan_interceptors.cpp` and `lsan_posix.cpp`. The four that remain are the
`stack == nullptr` fallbacks in the two reporters, which no caller can reach
while the option is on, and the no-thread-context branch of the thread-id
helper, which is defensive and no test hits. The macOS/NetBSD guard in
`lsan.cpp` is compiled out on the platform these ran on, so it is not exercised
at all. The `CombinedAllocator::Reallocate` change adds a unit test to
`sanitizer_allocator_test.cpp`. The LSan `realloc()` change adds
`Linux/realloc_failure_keeps_original.cpp` and extends `realloc_zero.c`.

All three were checked against the parent commit as well, so they fail without
their fix: the unit test crashes, `realloc_failure_keeps_original.cpp` trips
`assert(g_freed == nullptr)`, and `realloc_zero.c` sees
`__sanitizer_get_ownership()` return 0 and `__sanitizer_get_allocated_size()`
return 0 for `realloc(NULL, 0)` instead of 1 and 1.

Three caveats worth stating plainly:

- **Everything above was run on x86-64 only.** The 32-bit claim in the commit
  message -- that `ChunkMetadata` still fits in 16 bytes, where a naive field
  append would have taken 20 -- is backed by compiling the header for a 32-bit
  target and letting the `static_assert` decide, not by a 32-bit test run. I had
  no 32-bit runtime to link against, so the 32-bit allocator paths
  (`SizeClassAllocator32`, the static large-chunk pointer array) have not been
  exercised. If a 32-bit bot is the gate for this, that is the gap to close
  first.
- The concurrent secondary case is a smoke test, not a reliable reproducer of
  the unmap race -- that window is a handful of instructions wide and does not
  hit on its own in a few hundred runs. It was verified separately by injecting
  a delay at exactly that point: the pre-fix code then faults inside the runtime
  in most runs, and the current code reports the double free instead.
- `realloc_failure_keeps_original.cpp` caps the address space with `RLIMIT_AS`
  to make the replacement allocation fail, which is why it lives under
  `TestCases/Linux/`.

## AI tool use

Per the [LLVM AI Tool Policy](https://llvm.org/docs/AIToolPolicy.html), this
contribution was developed with AI assistance; the commits and the description
carry an `Assisted-by:` trailer. I have reviewed the runtime code across the
whole series myself and can answer questions about any part of it, and the
design decisions and the open questions above are mine.

Two limits on that, which I would rather state than have you assume:

- The test code added by the two realloc fixes -- the `Reallocate` block in
  `sanitizer_allocator_test.cpp`,
  `TestCases/Linux/realloc_failure_keeps_original.cpp`, and the addition to
  `TestCases/realloc_zero.c` -- has been reviewed by the AI assistant only, not
  by me.
- All the test runs reported above were carried out by the AI assistant.
