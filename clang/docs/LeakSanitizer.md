# LeakSanitizer

```{contents}
:local: true
```

## Introduction

LeakSanitizer is a run-time memory leak detector. It can be combined with
{doc}`AddressSanitizer` to get both memory error and leak detection, or
used in a stand-alone mode. LSan adds almost no performance overhead
until the very end of the process, at which point there is an extra leak
detection phase.

## Usage

{doc}`AddressSanitizer`: integrates LeakSanitizer and enables it by default on
supported platforms.

```console
$ cat memory-leak.c
#include <stdlib.h>
void *p;
int main() {
  p = malloc(7);
  p = 0; // The memory is leaked here.
  return 0;
}
% clang -fsanitize=address -g memory-leak.c ; ASAN_OPTIONS=detect_leaks=1 ./a.out
==23646==ERROR: LeakSanitizer: detected memory leaks
Direct leak of 7 byte(s) in 1 object(s) allocated from:
    #0 0x4af01b in __interceptor_malloc /projects/compiler-rt/lib/asan/asan_malloc_linux.cc:52:3
    #1 0x4da26a in main memory-leak.c:4:7
    #2 0x7f076fd9cec4 in __libc_start_main libc-start.c:287
SUMMARY: AddressSanitizer: 7 byte(s) leaked in 1 allocation(s).
```

To use LeakSanitizer in stand-alone mode, link your program with
`-fsanitize=leak` flag. Make sure to use `clang` (not `ld`) for the
link step, so that it would link in proper LeakSanitizer run-time library
into the final executable.

### Double-free detection

Stand-alone LeakSanitizer can optionally detect calls to `free` on an
allocation that has already been freed. The check is disabled by default;
enable it at run time through `LSAN_OPTIONS`:

```console
$ clang++ -g -O0 -fno-omit-frame-pointer -fsanitize=leak double-free.cpp -o double-free
$ LSAN_OPTIONS=detect_double_free=1 ./double-free
==1234==ERROR: LeakSanitizer: attempting double-free on 0x504000000010 in thread T0:
The second free occurred here:
...
The first free occurred here:
...
The memory was allocated here:
...
SUMMARY: LeakSanitizer: double-free
```

A double free is undefined behavior, so an optimizing compiler is allowed to
delete the second `free` before the runtime can observe it. Build with `-O0`,
or route the frees through a function the optimizer cannot see through, when
writing a reproducer.

The option is independent of leak checking. To report double frees without
running the leak check at exit, combine it with `detect_leaks=0`.

The option applies to stand-alone LeakSanitizer only. `LSAN_OPTIONS` is also
read when LeakSanitizer runs inside AddressSanitizer or HWAddressSanitizer, but
there the allocator belongs to that tool, which does its own double-free
detection; setting the option in that configuration has no effect.

Validating the freed pointer is a prerequisite for the check, so while the
option is enabled an invalid free becomes a diagnostic as well:

```console
==1234==ERROR: LeakSanitizer: attempting free on address which was not malloc()-ed: 0x...
SUMMARY: LeakSanitizer: bad-free
```

Without the option such a free reaches the allocator, which may dereference
metadata for an address that is not mapped and fault inside the runtime.

Both reports are fatal and are serialized with the sanitizer error-report lock,
so concurrent reports cannot interleave.

#### Memory and performance cost

Allocations served by the primary allocator keep their metadata mapped after
they are freed, so the allocation stack and the first-free stack are stored
inline in the existing per-chunk metadata. `ChunkMetadata` remains 16 bytes on
both 32-bit and 64-bit targets, and the check itself is a single
compare-exchange that takes no lock. This is what keeps the cost of the option
roughly constant as thread count grows.

Allocations served by the secondary allocator are unmapped as soon as they are
freed, taking their metadata with them, so their stacks are kept in a side
table. Releasing such a chunk has to copy those stacks into the table and
unmap the chunk as one step, under the mutex that guards the table, so that a
concurrent free cannot unmap the metadata another thread is still validating.
Every free of a large allocation therefore also pays a scan of the secondary
allocator's chunk list, which is linear in the number of live large
allocations. Programs that keep many large allocations alive and free them in a
hot loop are the ones to measure; small allocations are unaffected.

`double_free_max_entries` bounds that side table; its default is `65536` and
`0` means unlimited. When the limit is reached the oldest entry is evicted, so
a bounded table always remembers the most recent frees. An evicted address is
no longer recognized as a double free and is reported as an invalid free
instead. A negative value is treated as `0` and a value above `4194304` is
capped, both with a warning at startup. The option does not bound the
process-wide stack depot, which retains the recorded stack traces, so total
memory use is not hard-capped by it.

#### Limitations

A record is keyed by the address the allocator returned, so a new allocation at
the same address supersedes it. This is exact for the primary allocator, where
an address is only reused for the same chunk. It is approximate for the
secondary allocator: if an old freed address later falls *inside* a new, larger
mapping rather than at its start, the stale record is not superseded. Freeing
that interior address is invalid either way, but it may be reported as a double
free carrying the older allocation's stack traces. In the other direction, a
freed large mapping whose address is later taken over by the primary allocator
stops being recognized, because the address is then checked against the primary
allocator's own metadata.

A program that races a free of a chunk against a new allocation of the same
address - itself a use-after-free - can lose the record of the free, because
the chunk state and the fields written by the allocation path share one storage
unit. The effect is bounded to a misreported or missed double free.

Detection applies to allocations made through the intercepted allocator. It
cannot recognize a pointer that came from a different allocator.

Double-free detection is not supported on macOS or NetBSD, where the fork
handling does not go through the LSan `pthread_atfork` hooks that protect the
side table. Setting `detect_double_free=1` there prints a warning and leaves
the feature disabled.

When AddressSanitizer is used instead of stand-alone LeakSanitizer, use
AddressSanitizer's own double-free diagnostics.

## Security Considerations

LeakSanitizer is a bug detection tool and its runtime is not meant to be
linked against production executables. While it may be useful for testing,
LeakSanitizer's runtime was not developed with security-sensitive
constraints in mind and may compromise the security of the resulting executable.

## Supported Platforms

- Android
- Fuchsia
- Linux
- macOS
- NetBSD

## More Information

[https://github.com/google/sanitizers/wiki/AddressSanitizerLeakSanitizer](https://github.com/google/sanitizers/wiki/AddressSanitizerLeakSanitizer)

