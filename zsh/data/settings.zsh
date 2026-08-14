# Generic shell config. Oh My Zsh sources every *.zsh in $ZSH_CUSTOM, so this file loads without
# ~/.zshrc needing a single line added to it -- which is what makes a fresh machine painless: let
# the Oh My Zsh installer write its own ~/.zshrc, then deploy this.
#
# Nothing that must run *before* Oh My Zsh init belongs here. ZSH_THEME and plugins=() have to stay
# in ~/.zshrc, which Oh My Zsh owns and regenerates.

# uv's PATH shim. Guarded against double-adding, so it stays harmless when the uv installer also
# appends this same line to ~/.zshrc.
. "$HOME/.local/bin/env"

alias claude='claude --effort max'
alias k='kubectl'

export COLORTERM=truecolor

# Append each command as it runs, but do not share history live between concurrent shells.
unsetopt share_history
setopt inc_append_history
