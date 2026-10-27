# cli-graph

## The idea

One minimal MCP tool replaces all the others.

Every MCP server loads its full tool list into every session, whether the
session uses it or not. With a few servers that comes to hundreds of tool
schemas. The cost is context, attention and start-up time, and it grows
with every capability added.

This project inverts that. Each capability becomes a plain shell command.
A single MCP tool, `find_cli`, answers one question: *which command does
this task need?* The agent describes the task in plain words, gets back a
handful of matching commands with their usage, and runs one through the
shell. Adding a capability then adds a command, not a schema in every
session.

## How it works, in outline

- **One CLI, `mac`.** Every capability is `mac <area> <verb>`. Output and
  failures follow one contract, so any verb reads the same way. The CLI
  wraps the existing implementations rather than rewriting them, so there
  is still one code path per capability.

- **A command graph.** The CLI describes itself, and the graph of commands
  is generated from that description, never written by hand. A small
  hand-written layer adds the relations a description can't express: which
  command must come first, which feeds another, which words are aliases.

- **`find_cli`.** It searches the graph and returns the best matches plus
  their close neighbours. The search is plain and deterministic, with no
  model inside. A fixed set of real task phrases measures whether it finds
  the right command.

- **Safety moves with the command.** Confirmation rules and guards that
  used to hang on MCP tool names now attach to command prefixes, so
  outbound or destructive actions still ask first.

## Principles

- **Context is the budget.** Prefer anything that keeps the always-loaded
  surface small. A capability should cost nothing until a task needs it.

- **Generate, don't maintain.** Anything that can be derived from the CLI
  is derived, and a check fails when the derived copy is out of date.

- **One implementation.** Wrap existing tools, don't fork them. A command
  and the tool it replaced must give the same answer.

- **Measure discovery.** Judge `find_cli` on real phrasing against a fixed
  bar. If the bar slips, fix the search or the graph; don't add a
  workaround.

- **Keep what doesn't fit.** Servers whose value depends on staying
  resident stay MCP. Migrate only what a command does better.

## Before every commit

This repo is public. Scan the staged diff (`git diff --cached`) for
personal data before committing: names, emails, phone numbers,
addresses, account or ID numbers, home-directory paths
(`/Users/<name>/...`), vault/notes content, portfolio or financial
details, and secrets (API keys, tokens, passwords). Replace any hit with
a placeholder or generic example, or leave the file out; never commit it.

## Where things are

`README.md` covers the layout, the CLI contract, setup, tests and what to
regenerate after a change. The work is tracked under taskfw epic
`9839b040`, and `epic-9839b040-status.md` is a dated snapshot of it.
Always run Python through `uv run`.
