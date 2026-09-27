# Commits

Every commit in this repository is authored and committed as
`Kurianjose7586 <kurianjose005@gmail.com>`, the owner's GitHub account.

- A SessionStart hook in `.claude/settings.json` sets this in `.git/config` at
  the start of each session. Before committing, check with
  `git var GIT_AUTHOR_IDENT`; if it shows anyone else, run
  `git config user.name "Kurianjose7586"` and
  `git config user.email "kurianjose005@gmail.com"` first.
- Do not add a `Co-Authored-By` trailer naming Claude, or any other
  attribution that makes a Claude account appear on the commit.
