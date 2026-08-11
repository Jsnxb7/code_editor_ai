#!/usr/bin/env bash

export BOB_TERMINAL_ROOT="${BOB_TERMINAL_ROOT:-/workspace}"
export BOB_TERMINAL_START="${BOB_TERMINAL_START:-$BOB_TERMINAL_ROOT}"

case "$BOB_TERMINAL_START" in
  "$BOB_TERMINAL_ROOT"|"$BOB_TERMINAL_ROOT"/*) ;;
  *) BOB_TERMINAL_START="$BOB_TERMINAL_ROOT" ;;
esac

if [[ ! -d "$BOB_TERMINAL_START" ]]; then
  BOB_TERMINAL_START="$BOB_TERMINAL_ROOT"
fi

builtin cd -- "$BOB_TERMINAL_START" || exit 1

cd() {
  local previous="$PWD"
  builtin cd -- "${1:-$BOB_TERMINAL_ROOT}" || return $?
  case "$PWD" in
    "$BOB_TERMINAL_ROOT"|"$BOB_TERMINAL_ROOT"/*) ;;
    *)
      builtin cd -- "$previous" || builtin cd -- "$BOB_TERMINAL_ROOT"
      printf 'Access denied: the terminal cannot leave your user workspace.\n' >&2
      return 1
      ;;
  esac
}

__bob_terminal_prompt() {
  case "$PWD" in
    "$BOB_TERMINAL_ROOT"|"$BOB_TERMINAL_ROOT"/*) ;;
    *) builtin cd -- "$BOB_TERMINAL_ROOT" ;;
  esac
  local relative="${PWD#"$BOB_TERMINAL_ROOT"}"
  PS1="bob:${relative:-/}\\$ "
}

PROMPT_COMMAND=__bob_terminal_prompt
