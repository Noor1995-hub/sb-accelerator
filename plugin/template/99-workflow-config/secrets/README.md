# Secrets

Machine credentials placed here at provisioning. Currently one file:

- `feedback-token` — a fine-grained GitHub token (issues read/write on this deployment's own feedback repo, nothing else) used by `/report-feedback`.

These files are read only by the plugin's CLI, which never prints them. Claude must never read or display files in this folder. If a token needs replacing, your delaware consultant rotates it at a tune-up.
