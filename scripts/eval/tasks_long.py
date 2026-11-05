"""Frozen P4 history tasks, selected before any model result.

long_selection.json contains full SHAs, changed file lists, all exclusions and
offline parent/reference pytest outcomes. Eligibility counts implementation .py
only: >=60 changed lines OR >=3 code files; tests, docs and .pyi do not count.
The previous documentation/type-stub rule is void. Keep descending commit time
within each fixed repository priority, SHA tie-break, and full groups of four.
First four are development; remaining eight are final. Each episode uses one
repository (more-itertools MIT; boltons BSD-3-Clause). Each task gets a fresh parent tree at the same path while
the lead conversation is resumed; earlier code changes are intentionally lost.
"""
from __future__ import annotations
import json
from pathlib import Path

BRIEFS = {
    "21d3d883": ("multidimensional-reshape", "Extend reshape(matrix, shape) to support arbitrary uniform nested input and a sequence of output dimensions. "
                 "Return a lazy iterator producing the requested nested tuple structure in input order, stopping at the requested shape or exhaustion. "
                 "Treat strings and bytes as scalar values. Preserve the existing integer-shape interface that specifies the column count for a two-dimensional input. "
                 "Update its documentation and annotations."),
    "a7236314": ("is-prime", "Add a public is_prime(n) recipe for integer primality checks, including small and large inputs. "
                 "Return False for integers below two and composite numbers, and True for primes. Avoid trial division that becomes impractical for large integers; "
                 "document that very large inputs may use a probabilistic result. Update exports and type declarations."),
    "6270b5e3": ("boltons-iterutils", "Several iterutils operations mishandle edge cases. Make remap preserve namedtuple types while applying transformations; "
                 "leave non-rebuildable sequence objects intact. chunk_ranges should produce no ranges for empty input and reject overlap at least as large as its chunk. "
                 "bucketize must accept a one-shot source together with a list of keys and reject mismatched lengths. redundant must honor falsey callable keys. "
                 "untyped_sorted should evaluate its key once per input item. Treat a negative split_iter maxsplit as unlimited, and correct automatic fractional backoff counts. "
                 "Add chunked_filter(src, size, key=None): its callable receives batches and returns one keep flag per item; default to item truthiness and reject invalid callables or flag counts."),
    "922e7b2b": ("boltons-file-path-names", "Fix file, path and named-container edge cases. FilePerms must round-trip all permission bit groups and clear old group bits when reassigned. "
                 "AtomicSaver must close its file and clean temporary parts appropriately even when flushing or syncing fails, without hiding the failure. "
                 "iter_find_files max_depth must behave consistently with trailing separators. shrinkuser must work when the user's home is a filesystem root. "
                 "namedtuple and namedlist must reject invalid Python identifiers, including Unicode names that are alphanumeric but not valid identifiers, while honoring rename=True."),
    "f898d8f8": ("boltons-gc-types-trace", "Fix the GC, type and tracing helpers. gcutils.get_all should find live instances of indirect subclasses when include_subtypes is enabled, "
                 "and respect disabling it. Nested GCToggler contexts must restore the GC state present at each matching entry, including when GC started disabled. "
                 "typeutils.get_all_subclasses must support metaclasses and avoid duplicate subclass results. When a wrap_trace hook suppresses a raise event, "
                 "the wrapped method should return None instead of failing because its return value was never assigned."),
    "40fffc5b": ("boltons-indexed-set", "Make IndexedSet set operations work with one-shot iterators and multiple operands while preserving ordered-set behavior. "
                 "Correct intersection_update, difference_update and symmetric_difference_update, including operations on itself. "
                 "Fix stale tail-removal bookkeeping and require integer-compatible pop indices. Correct complement-set intersection and symmetric difference, "
                 "including in-place variants across finite and complemented operands, so they obey the same membership rules as their non-mutating counterparts."),
    "bbadc7ae": ("boltons-mapping-updates", "Correct OrderedMultiDict update and equality both in dictutils and its urlutils copy: preserve all repeated incoming values, "
                 "and do not confuse extra None/None entries with exhaustion. OneToOne.update should support one-shot pair iterables and mapping-like objects, "
                 "preserve its inverse mapping, and support |=. Validate inputs without leaving invalid partial state. ManyToMany.update must not alias another instance's sets; "
                 "failed add operations must not leave empty entries, and replace must merge into an existing replacement key while keeping inverse relationships consistent."),
    "3fe7b949": ("boltons-barrel-list", "Make BarrelList behave consistently with list for comparisons, concatenation, repetition, remove, clear, copy, pickling and self-extension. "
                 "Fix pop argument validation, negative and stepped slice deletion, and empty boundary cases. Add list-compatible sort(key=None, reverse=False) with key evaluated once per item, "
                 "and index(item, start=0, stop=None) with normal list slice-bound behavior. Preserve the contents across its internal sublists."),
    "673e010d": ("boltons-ellipsize", "Add public ellipsize(text, max_len=160, *, ellipsis='…') to shorten text within the total length limit, including its suffix. "
                 "Return text unchanged when it fits. Prefer word boundaries, remove trailing spaces and sentence punctuation at a cut, and preserve decimal points within numbers. "
                 "Hard-cut a single overlong token. Support a custom suffix and raise ValueError when max_len cannot leave room for content plus the suffix."),
    "99dec84c": ("boltons-timezone-fold", "Fix USTimeZone handling of ambiguous fall-back times and spring-forward gaps using datetime.fold. "
                 "UTC-to-local conversions must choose the correct offset and mark repeated local times with fold=1. "
                 "Respect historical US DST rule periods and years before DST, preserve ordinary conversions, and reject fromutc arguments with a different tzinfo."),
    "842a2b17": ("subfactorial", "Add a public subfactorial(n) utility that counts permutations with no fixed positions. "
                 "It should handle non-negative integral sizes, include the empty permutation, and reject negative sizes with ValueError. "
                 "Export it consistently with the library's existing combinatorial utilities and document its public interface."),
    "52cfcfed": ("restore-pairwise", "The pairwise utility disappeared from the library's public recipes, breaking callers and existing utilities that use it. "
                 "Restore public pairwise(iterable) behavior: lazily yield consecutive overlapping pairs and produce nothing for fewer than two inputs. "
                 "Keep exports, API documentation and type declarations consistent."),
    "93c1cf84": ("restore-pred", "A recent change renamed first_true's pred keyword to predicate and broke existing callers. "
                 "Restore the public first_true(iterable, default=None, pred=None) interface and its documentation and type declaration. "
                 "Internal library callers must work with that interface. Preserve first-match, default, and truth-testing behavior."),
    "d63a26e5": ("rename-predicate", "Make first_true's optional predicate keyword consistently named predicate instead of pred: "
                 "first_true(iterable, default=None, predicate=None). Update callers within the library, documentation and type declarations. "
                 "Keep first-match and default behavior, including ordinary truth testing when no callable is supplied."),
    "18c57c72": ("running-statistics", "Add public running_min, running_max and running_statistics for numeric streams, with an optional keyword-only maxlen sliding window. "
                 "Extend running_mean with that same window interface. Without maxlen use all observations so far; reject nonpositive windows. "
                 "running_statistics yields immutable Stats records with size, minimum, median, maximum and mean. "
                 "Handle the initial partial window, empty streams and supported numeric types, and update exports, docs and annotations."),
    "f91c7339": ("sized-iterator", "Add a public sized_iterator(iterable, length) wrapper so callers can supply the known length of a generator. "
                 "It should be an ordinary iterator yielding the original elements lazily and exposing the supplied length via len(). "
                 "That declared length stays unchanged as it is consumed. Update public exports, documentation and type declarations."),
    "428a0a2c": ("synchronized", "Add public synchronized(func), usable as a decorator on iterator-returning callables. "
                 "Each call must return an iterator whose next operations can safely be shared by multiple consumer threads. "
                 "Forward the original positional and keyword arguments, preserve wrapped-function metadata, and support generator functions and itertools constructors. "
                 "Update exports, documentation and type declarations."),
    "1b7f033d": ("concurrent-tee", "Add concurrent_tee(iterable, n=2), a threading-safe counterpart to itertools.tee. "
                 "Separate threads consuming different branches must each see the complete original stream, even at different speeds. "
                 "Splitting an existing branch must retain its current position. Return no branches for n=0 and reject negative counts. "
                 "One branch is consumed by one thread unless separately serialized. Update exports, docs and type declarations."),
    "4f399222": ("serialize", "Add public serialize(iterable), an iterator wrapper that lets multiple threads safely consume one iterator or generator instance. "
                 "The wrapper must preserve ordinary iterator identity and exhaustion behavior while preventing concurrent next operations from losing or duplicating values. "
                 "Update exports, documentation and type declarations."),
    "ccf96ac6": ("random-derangement", "Add public random_derangement(iterable), returning one randomly chosen positional derangement as a tuple without constructing all permutations. "
                 "No element position may remain fixed. Accept finite iterables, return an empty tuple for empty input, and raise IndexError when no derangement exists for a singleton. "
                 "Update exports, documentation and type declarations."),
    "5bd5c263": ("extract", "Add public extract(iterable, indices), yielding the requested positions in the order requested, including repeated and unsorted indices. "
                 "Consume the finite indices eagerly but consume the data lazily so infinite input streams work. "
                 "Reject negative indices with ValueError and out-of-range indices with IndexError. Update exports, docs and type declarations."),
    "5c8336c5": ("windowed-median", "Extend running_median with keyword-only window=None. With a window, report the median of the most recent observations, "
                 "including partial windows at the start; without it preserve the cumulative behavior and supported numeric types. "
                 "Require an integer-compatible window argument and handle empty input. Keep both older Python and Python 3.14+ supported and update type declarations."),
}

SELECTION_FILE = Path(__file__).with_name("long_selection.json")
SELECTION = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
T = []
for index, row in enumerate(SELECTION["accepted"]):
    name, brief = BRIEFS[row["commit"][:8]]
    T.append({**{k: row[k] for k in ("repo", "commit", "timestamp", "size", "code_lines", "code", "non_test_files", "tests")},
              "id": "long-" + name, "brief": brief, "split": "dev" if index < 4 else "final"})
IDS = [t["id"] for t in T]

# Separate opt-in split: T / IDS and the legacy all schedule retain their meanings.
P5_SELECTION_FILE = Path(__file__).with_name("p5_long_selection.json")
P5_SELECTION = json.loads(P5_SELECTION_FILE.read_text(encoding="utf-8")) if P5_SELECTION_FILE.exists() else {}
P5_T = [{**row, "id": "p5-long-" + row["commit"][:12], "split": "p5",
         "brief": row["brief"]} for row in P5_SELECTION.get("accepted", [])]
P5_AUDITED_T = [{**row, "id": "p5-long-" + row["commit"][:12], "split": "p5"}
                for row in P5_SELECTION.get("audited_tasks", [])]


def by_id(task_id):
    return next(t for t in T + P5_T + P5_AUDITED_T if t["id"] == task_id)
