# Unified public repository

`Raysance/GloryBond` is the sole application source and deployment repository. Bot/Web implementation, the full README, AGENTS, functional manuals and deployment methods are maintained together. The former organization application repositories are retired archives.

The initial migration imported 509 application/Web commits and 24 earlier GloryBond commits after sanitization. A subsequent privacy cleanup removed eight historical entries whose messages referred to people, nicknames, name initials or character names. The current baseline retains 501 application/Web entries and 24 earlier public entries, plus the consolidation and privacy-cleanup commits.

Every retained historical message and file snapshot was verified byte-for-byte. Parent links reconnect around removed entries, retaining the existing application implementation. Private backups contain the original audit records outside the repository. Neither names nor the removed commit list are republished here.

Current mappings are [application history](history-map-application.txt) and [earlier public history](history-map-public.txt). Removed entries are omitted. Local Codex checkpoints and stash refs remain private work state and are not imported. Future commit messages use general functional descriptions without personal names, nicknames or name initials.

Fixed private dependencies:

- `vendor/hok-player-client`: `5b960ccace718f9e1466442ac5d741f70111732f`
- `vendor/hok-camp-client`: `8abb729ef2a5de2b288e987539040cb838aa18b2`
- `vendor/react-agent-runtime`: `d49b40745a57eeaac9ad63ab6d81d6f7ac2df406`

Both `.env` and `config.yaml` remain only on local/production machines and are ignored. Separate SSH configuration synchronization precedes the normal GitHub Actions source deployment. See [development](DEVELOPMENT.md) and [publication boundaries](../deployment/PUBLICATION.md).
