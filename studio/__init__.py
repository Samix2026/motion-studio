"""studio — read-only workflow integration for the Video Studio Agent.

One orchestration point that reports the state of the independently-runnable
subsystems (Reference Analyzer, Cost Gate, Word-level Sync, Review V1) for a
project. It duplicates no subsystem logic: it calls each as a library and never
writes to a project, a render, or a brand profile.

Two human gates:
  Gate 1 — cost approval BEFORE paid generation.
  Gate 2 — creative/technical approval BEFORE applying review proposals.
"""

__all__ = ["status"]