// realloc() validates its pointer the same way free() does, and for the same
// reason: a secondary chunk is unmapped as soon as it is freed, so the old
// chunk's metadata must not be read before the pointer is known to be live.
// Reallocating an already freed or otherwise invalid pointer is therefore
// diagnosed, and a pointer that realloc() replaced cannot be freed again.
//
// RUN: %clangxx_lsan -O0 %s -o %t
// RUN: %env_lsan_opts=detect_leaks=0:detect_double_free=1 not %run %t realloc-freed-small 2>&1 | FileCheck %s --check-prefix=CHECK-DOUBLE
// RUN: %env_lsan_opts=detect_leaks=0:detect_double_free=1 not %run %t realloc-freed-large 2>&1 | FileCheck %s --check-prefix=CHECK-DOUBLE
// RUN: %env_lsan_opts=detect_leaks=0:detect_double_free=1 not %run %t free-replaced 2>&1 | FileCheck %s --check-prefix=CHECK-DOUBLE
// RUN: %env_lsan_opts=detect_leaks=0:detect_double_free=1 not %run %t realloc-interior 2>&1 | FileCheck %s --check-prefix=CHECK-BAD
// REQUIRES: lsan-standalone
// UNSUPPORTED: darwin, target={{.*netbsd.*}}

#include <cstdio>
#include <cstdlib>
#include <cstring>

__attribute__((noinline)) static void Free(void *p) { free(p); }
__attribute__((noinline)) static void *Realloc(void *p, size_t n) {
  return realloc(p, n);
}

int main(int argc, char **argv) {
  if (argc != 2)
    return 1;

  if (!strcmp(argv[1], "realloc-freed-small")) {
    void *p = malloc(16);
    Free(p);
    // Growing an already freed pointer is a double free.
    Realloc(p, 32);
  } else if (!strcmp(argv[1], "realloc-freed-large")) {
    // Same for a chunk from the secondary allocator, whose metadata is gone by
    // the time realloc() runs.
    void *p = malloc(2 << 20);
    Free(p);
    Realloc(p, 3 << 20);
  } else if (!strcmp(argv[1], "free-replaced")) {
    void *p = malloc(16);
    void *q = Realloc(p, 4096);
    if (!q)
      return 1;
    // p was released by the successful realloc.
    Free(p);
  } else {
    // An interior pointer was never handed out, so this is an invalid free
    // rather than a double free.
    void *p = (char *)malloc(64) + 16;
    Realloc(p, 128);
  }

  fprintf(stderr, "not reached\n");
  return 0;
}

// CHECK-DOUBLE: ERROR: LeakSanitizer: attempting double-free on
// CHECK-DOUBLE: The memory was allocated here:
// CHECK-DOUBLE: SUMMARY: LeakSanitizer: double-free
// CHECK-DOUBLE-NOT: not reached

// CHECK-BAD: ERROR: LeakSanitizer: attempting free on address which was not
// CHECK-BAD: SUMMARY: LeakSanitizer: bad-free
// CHECK-BAD-NOT: not reached
