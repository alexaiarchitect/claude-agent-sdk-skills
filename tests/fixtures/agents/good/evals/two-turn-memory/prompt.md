---
name: two-turn-memory
category: memory
tags: [memory, multi-turn]
runs: 3
max_turns: 8
mocks: [library]
turns:
  - "Reserve 'Dune' for member-42."
  - "Actually, make that two copies."
# no body: `turns` drives this case, and a body would be silently ignored
---
