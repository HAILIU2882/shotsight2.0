# Module Worktrees

This directory is the preferred location for local module worktrees created by
the main agent or subagents.

Example:

```sh
cd /Users/hailiu/Desktop/Projects/shotsight2.0
git worktree add worktrees/review -b codex/review main
```

The contents of module worktrees are ignored by the parent repository so nested
working copies are not accidentally committed. Keep this README and `.gitkeep`
tracked so every checkout includes the expected folder.
